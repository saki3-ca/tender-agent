"""
Generic e-paper crawler: one class for the newspapers that only differ in where their page images are.

Each source in config/sources.json has "type": "epaper_generic", the newspaper's name and an "epaper"
block that says how to find today's page images:

  "epaper": {
    "mode": "template" | "html" | "browser",
    ...mode options below...
    "max_pages": 24
  }

mode "template"  The image address is a pattern with {yyyy} {mm} {dd} {date} {page} {page2} (page number, and
                 the same with two digits: 01, 02 ...); pages 1, 2, 3 ... are
                 tried until the pages stop existing.
                   "image_template": "https://cdn.example.com/{yyyy}/{mm}/{dd}/page-{page}.jpg"
mode "html"      The page images are named in the e-paper's HTML. "image_regex" finds them (named group
                 "url", optionally "page"); "replace": [old, new] turns thumbnail addresses into full pages.
                   "page_url": "https://epaper.example.com/{date}"   (default: the source url)
                   "image_regex": "(?P<url>https://cdn\\.example\\.com/[^\"']+?/(?P<page>\\d+)\\.jpg)"
mode "browser"   The e-paper is opened in Chrome (virtual display in GitHub Actions) and the large images it
                 loads are the pages. For sites that build the pages with JavaScript or sit behind Cloudflare.
                   "min_image_kb": 150

Common options: "date_format" (default "%Y-%m-%d") for {date}, "referer", "min_bytes" (smaller images are
not pages), "view_url" (address stored as the link to the page; may use {date} and {page}).
"""

import asyncio
import logging
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import httpx

from app.crawler import pc_browser
from app.crawler.crawler import USER_AGENT
from app.parsers.date_cleaner import DHAKA_TZ
from app.parsers.epaper_gemini import GeminiEpaperParser

logger = logging.getLogger("epaper_generic")

DEFAULT_MAX_PAGES = 24
MIN_PAGE_BYTES = 30000

Page = Tuple[int, str]          # (page number, image address)


def fill(template: str, day: date, page: Optional[int] = None, date_format: str = "%Y-%m-%d") -> str:
    """{yyyy} {mm} {dd} {date} {page} {page2} in a pattern."""
    return (template
            .replace("{yyyy}", f"{day.year:04d}").replace("{mm}", f"{day.month:02d}").replace("{dd}", f"{day.day:02d}")
            .replace("{date}", day.strftime(date_format))
            .replace("{page2}", "" if page is None else f"{page:02d}")
            .replace("{page}", "" if page is None else str(page)))


def pages_from_html(html: str, base_url: str, regex: str, replace: Optional[List[str]] = None) -> List[Page]:
    """Page images named in the HTML, by page number (the order they appear in when there is no number)."""
    html = html.replace("\\/", "/").replace("&amp;", "&")      # addresses inside page data are written https:\/\/...
    pattern = re.compile(regex)
    found: Dict[int, str] = {}
    seen_urls = set()
    order = 0
    for m in pattern.finditer(html):
        groups = m.groupdict()
        url = groups.get("url") or m.group(0)
        if replace and len(replace) == 2:
            url = url.replace(replace[0], replace[1])
        url = urljoin(base_url, url)
        if url in seen_urls:                # the same image named twice is one page
            continue
        seen_urls.add(url)
        order += 1
        try:
            number = int(groups.get("page") or order)
        except ValueError:
            number = order
        found.setdefault(number, url)
    return sorted(found.items())


class GenericEpaperCrawler:
    def __init__(self, source: Dict[str, Any]):
        self.source = source
        self.cfg: Dict[str, Any] = source.get("epaper", {})
        self.name: str = source.get("newspaper") or source.get("id", "newspaper")
        self.parser = GeminiEpaperParser()

    # ------------------------------------------------------------------ discovery
    def _headers(self) -> Dict[str, str]:
        return {"User-Agent": USER_AGENT, "Referer": self.cfg.get("referer") or self.source["url"]}

    async def _pages_template(self, client: httpx.AsyncClient, day: date, limit: int) -> Tuple[Optional[str], List[Page]]:
        template = self.cfg["image_template"]
        fmt = self.cfg.get("date_format", "%Y-%m-%d")
        min_bytes = int(self.cfg.get("min_bytes", MIN_PAGE_BYTES))
        pages: List[Page] = []
        misses = 0
        for n in range(1, limit + 1):
            url = fill(template, day, n, fmt)
            try:
                r = await client.head(url, headers=self._headers())
                if r.status_code in (403, 405) or r.status_code >= 500:     # HEAD not allowed: ask for the image itself
                    r = await client.get(url, headers=self._headers())
                ok = r.status_code == 200 and int(r.headers.get("content-length") or min_bytes) >= min_bytes
            except httpx.HTTPError:
                ok = False
            if ok:
                pages.append((n, url))
                misses = 0
            else:
                misses += 1
                if misses >= 2 and (pages or n >= 3):
                    break
        return (None if pages else "NO_PAGES: no page images found for the edition"), pages

    async def _pages_html(self, client: httpx.AsyncClient, day: date) -> Tuple[int, Optional[str], List[Page]]:
        fmt = self.cfg.get("date_format", "%Y-%m-%d")
        page_url = fill(self.cfg.get("page_url", self.source["url"]), day, None, fmt)
        if self.cfg.get("fetch") == "browser":
            async with pc_browser.chrome_pages() as get_html:
                status, html = await get_html(page_url)
        else:
            r = await client.get(page_url, headers=self._headers())
            status, html = r.status_code, r.text
        if status != 200:
            return status, "BLOCKED" if status == 403 else f"HTTP_{status}", []
        pages = pages_from_html(html, page_url, fill(self.cfg["image_regex"], day, None, fmt), self.cfg.get("replace"))
        return status, (None if pages else "NO_PAGES: no page images found for the edition"), pages

    async def _pages_browser(self, day: date) -> Tuple[int, Optional[str], List[Page]]:
        fmt = self.cfg.get("date_format", "%Y-%m-%d")
        page_url = fill(self.cfg.get("page_url", self.source["url"]), day, None, fmt)
        min_kb = int(self.cfg.get("min_image_kb", 150))
        async with pc_browser.chrome_pages() as get_html:
            status, _html = await get_html(page_url)
            if status != 200:
                return status, "BLOCKED" if status == 403 else f"HTTP_{status}", []
            urls = await get_html.large_images(min_kb * 1024)  # type: ignore[attr-defined]
        pages = [(i, u) for i, u in enumerate(urls, 1)]
        return 200, (None if pages else "NO_PAGES: no page images found for the edition"), pages

    # ------------------------------------------------------------------ crawl
    async def crawl_edition(self, target_date: Optional[date] = None, max_pages: Optional[int] = None
                            ) -> Tuple[int, Optional[str], List[Dict[str, Any]]]:
        day = target_date or datetime.now(DHAKA_TZ).date()
        limit = int(max_pages or self.cfg.get("max_pages", DEFAULT_MAX_PAGES))
        mode = self.cfg.get("mode", "html")
        needs_browser = mode == "browser" or self.cfg.get("fetch") == "browser"
        if needs_browser and not pc_browser.enabled():
            return 0, "NEEDS_PC_BROWSER: needs a browser (set EPAPER_PC_BROWSER=1; GitHub Actions does this)", []

        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True, proxy=pc_browser.proxy_url()) as client:
            if mode == "template":
                status, (error, pages) = 200, await self._pages_template(client, day, limit)
            elif mode == "browser":
                status, error, pages = await self._pages_browser(day)
            else:
                status, error, pages = await self._pages_html(client, day)
            if error:
                return status, error, []

            logger.info(f"{self.name} e-paper: {len(pages)} pages for {day.isoformat()}")
            fmt = self.cfg.get("date_format", "%Y-%m-%d")
            view = self.cfg.get("view_url", self.source["url"])
            min_bytes = int(self.cfg.get("min_bytes", MIN_PAGE_BYTES))
            tenders: List[Dict[str, Any]] = []
            for number, img_url in pages[:limit]:
                try:
                    resp = await client.get(img_url, headers=self._headers())
                    if resp.status_code != 200 or len(resp.content) < min_bytes:
                        continue
                    mime = resp.headers.get("content-type", "image/jpeg").split(";")[0]
                    items = await self.parser.extract_tenders_from_image(resp.content, mime if mime.startswith("image/") else "image/jpeg")
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"{self.name} page {number} error: {e}")
                    continue
                for t in items:
                    t["_page_no"] = str(number)
                    t["_page_title"] = f"Page {number}"
                    t["_page_url"] = fill(view, day, number, fmt)
                    t["_image_url"] = img_url
                    t["_edition_date"] = day.strftime("%d/%m/%Y")
                    t["_newspaper"] = self.name
                    tenders.append(t)
            return 200, None, tenders
