"""
E-paper reader driven by config: finds the edition's page images on the e-paper home page with a regular
expression from config/sources.json, then reads each page with Gemini Vision (like the paper-specific readers).

Source fields (type "epaper_generic"):
  newspaper        display name, e.g. "Daily Inqilab"
  url              e-paper home page (shows today's edition)
  page_regex       regex over the home page HTML (JSON-escaped slashes "\\/" are undone first). It must have a
                   named group "n" (page number). The image URL is the whole match, or image_template
                   formatted with the named groups. Relative URLs are resolved against the home page.
                   {Y} {m} {d} are replaced by today's date (Dhaka).
  image_template   optional, e.g. "https://epaper.samakal.com/{path}/pages/{id}.jpg"
  page_html        optional: the match is a page *view* (HTML), not an image. Each view is downloaded and
                   tile_regex ({n} = page number) finds the article images on it; images smaller than
                   min_image_bytes (spacers, empty tiles) are skipped. Used for The Daily Observer.
  max_pages        default 20
  allowed_hosts    optional domains images may come from (default: the url's host); every page, tile and
                   redirect target outside them is skipped
"""

import logging
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import httpx

from app.crawler.crawler import USER_AGENT
from app.crawler.epaper import get_page_image
from app.parsers.date_cleaner import DHAKA_TZ
from app.parsers.epaper_gemini import GeminiEpaperParser

logger = logging.getLogger("epaper_generic")


def page_images(html: str, base_url: str, page_regex: str, image_template: Optional[str] = None,
                fields: Optional[Dict[str, str]] = None) -> List[Tuple[int, str]]:
    """(page number, absolute URL) for each page found in the HTML, first occurrence per page, by page number."""
    text = html.replace("\\/", "/")
    pages: Dict[int, str] = {}
    for m in re.finditer(page_regex, text):
        n = int(m.group("n"))
        if n in pages:
            continue
        url = image_template.format(**(fields or {}), **m.groupdict()) if image_template else m.group(0)
        pages[n] = urljoin(base_url, url)
    return sorted(pages.items())


def edition_urls(html: str, base_url: str, today: date, source: Dict[str, Any]) -> List[Tuple[int, str]]:
    dates = {"Y": f"{today:%Y}", "m": f"{today:%m}", "d": f"{today:%d}"}
    regex = source["page_regex"]
    for k, v in dates.items():
        regex = regex.replace("{" + k + "}", v)
    return page_images(html, base_url, regex, source.get("image_template"), dates)


class GenericEpaperCrawler:
    def __init__(self, source: Dict[str, Any]):
        self.source = source
        self.newspaper = source.get("newspaper") or source["id"]
        self.parser = GeminiEpaperParser()

    def _allowed(self, url: str) -> bool:
        """Only fetch from the newspaper's own domains (the source URL's host, or allowed_hosts)."""
        host = (urlparse(url).hostname or "").lower()
        hosts = self.source.get("allowed_hosts") or [urlparse(self.source["url"]).hostname or ""]
        return urlparse(url).scheme in ("http", "https") and any(
            host == h.lower().removeprefix("www.") or host.endswith("." + h.lower().removeprefix("www."))
            for h in hosts if h)

    async def _get(self, client: httpx.AsyncClient, url: str) -> Optional[httpx.Response]:
        if not self._allowed(url):
            logger.warning(f"{self.newspaper}: skipped URL outside the newspaper's domains: {url[:120]}")
            return None
        # Redirects are followed by hand so every hop is checked before it is requested
        for _ in range(5):
            r = await get_page_image(client, url, follow_redirects=False)
            if not r.is_redirect:
                return r
            url = urljoin(url, r.headers.get("location", ""))
            if not self._allowed(url):
                logger.warning(f"{self.newspaper}: redirect outside the newspaper's domains skipped: {url[:120]}")
                return None
        return None

    async def _images(self, client: httpx.AsyncClient, page_no: int, page_url: str) -> List[Tuple[str, bytes]]:
        """Image bytes to read for one page: the page image, or the article tiles of a page view."""
        r = await self._get(client, page_url)
        if r is None or r.status_code != 200 or not r.content:
            return []
        if not self.source.get("page_html"):
            return [(page_url, r.content)]
        tile_regex = self.source["tile_regex"].replace("{n}", str(page_no))
        tiles = list(dict.fromkeys(urljoin(page_url, t) for t in re.findall(tile_regex, r.text)))
        out = []
        for t in tiles:
            img = await self._get(client, t)
            if img is not None and img.status_code == 200 and len(img.content) >= int(self.source.get("min_image_bytes", 15000)):
                out.append((t, img.content))
        return out

    async def crawl_edition(self, target_date: Optional[date] = None
                            ) -> Tuple[int, Optional[str], List[Dict[str, Any]]]:
        today = target_date or datetime.now(DHAKA_TZ).date()
        max_pages = int(self.source.get("max_pages", 20))
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True,
                                     headers={"User-Agent": USER_AGENT}) as client:
            resp = await client.get(self.source["url"])
            if resp.status_code >= 400:
                return resp.status_code, f"HTTP_{resp.status_code}", []
            pages = edition_urls(resp.text, str(resp.url), today, self.source)[:max_pages]
            logger.info(f"{self.newspaper} e-paper: {len(pages)} pages")
            found: List[Dict[str, Any]] = []
            for page_no, page_url in pages:
                try:
                    for img_url, data in await self._images(client, page_no, page_url):
                        for t in await self.parser.extract_tenders_from_image(data, "image/jpeg"):
                            t.update({"_page_no": str(page_no), "_page_title": f"Page {page_no}",
                                      "_page_url": self.source.get("public_url") or self.source["url"],
                                      "_image_url": img_url, "_edition_date": today.strftime("%d/%m/%Y"),
                                      "_newspaper": self.newspaper})
                            found.append(t)
                except Exception as e:  # noqa: BLE001 - one bad page must not stop the edition
                    logger.warning(f"{self.newspaper} page {page_no} error: {e}")
            return resp.status_code, None, found
