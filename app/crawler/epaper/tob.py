"""
The Business Online (tob.news) E-Paper Crawler.

NOTE: tob.news/epaper could not be opened when this crawler was written (blocked in the build
sandbox), so page discovery is deliberately generic: it takes every large page image linked from
the e-paper page, skipping thumbnails and logos. Verify on a PC / in the daily e-paper workflow
and tighten `page_images` if the site's markup differs.
"""

import logging
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from app.crawler.crawler import USER_AGENT
from app.parsers.date_cleaner import DHAKA_TZ
from app.parsers.epaper_gemini import GeminiEpaperParser

logger = logging.getLogger("epaper_tob")
BASE_URL = "https://tob.news/epaper/"

_IMG_EXT = re.compile(r"\.(jpe?g|png|webp)(\?|$)", re.I)
_SKIP = re.compile(r"thumb|thum|small|icon|logo|avatar|banner|ads?/|sprite|favicon", re.I)


def page_images(html: str, base_url: str = BASE_URL) -> List[str]:
    """Absolute URLs of the e-paper page images found in the e-paper HTML, in document order."""
    soup = BeautifulSoup(html, "html.parser")
    found: List[str] = []
    candidates = []
    for a in soup.find_all("a"):
        candidates.append(a.get("href", ""))
    for img in soup.find_all("img"):
        for attr in ("data-src", "data-large", "data-full", "src"):
            if img.get(attr):
                candidates.append(img[attr])
    for raw in candidates:
        if not raw or not _IMG_EXT.search(raw) or _SKIP.search(raw):
            continue
        url = urljoin(base_url, raw)
        if url not in found:
            found.append(url)
    return found


class TobEpaperCrawler:
    def __init__(self):
        self.parser = GeminiEpaperParser()

    async def crawl_edition(self, target_date: Optional[date] = None, max_pages: int = 12
                            ) -> Tuple[int, Optional[str], List[Dict[str, Any]]]:
        """Crawls the pages of The Business Online e-paper for the given date."""
        today = target_date or datetime.now(DHAKA_TZ).date()

        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            resp = await client.get(BASE_URL, headers={"User-Agent": USER_AGENT})
            if resp.status_code >= 400:
                return resp.status_code, f"HTTP_{resp.status_code}", []

            images = page_images(resp.text, str(resp.url))
            logger.info(f"The Business Online e-paper: Found {len(images)} pages")
            extracted: List[Dict[str, Any]] = []

            for idx, img_url in enumerate(images[:max_pages], 1):
                try:
                    img_resp = await client.get(img_url, headers={"User-Agent": USER_AGENT})
                    if img_resp.status_code != 200:
                        continue
                    mime = img_resp.headers.get("content-type", "image/jpeg").split(";")[0]
                    tenders = await self.parser.extract_tenders_from_image(img_resp.content, mime)
                    for t in tenders or []:
                        t["_page_no"] = str(idx)
                        t["_page_title"] = f"Page {idx}"
                        t["_page_url"] = BASE_URL
                        t["_image_url"] = img_url
                        t["_edition_date"] = today.strftime("%d/%m/%Y")
                        t["_newspaper"] = "The Business Online"
                        extracted.append(t)
                except Exception as e:
                    logger.warning(f"The Business Online page {idx} error: {e}")
                    continue

            return 200, None, extracted
