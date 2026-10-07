"""
Daily Jugantor E-Paper Crawler.

Major Bangla daily newspaper in Bangladesh. The page scans (/storage/<date>/<page>/<id>_<page>.jpg)
are public, but their names contain an id that is only listed on the edition page, which
Cloudflare serves to browsers only: that page is read in Chrome on the office PC (pc_browser).
"""

import logging
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.crawler import pc_browser
from app.crawler.crawler import USER_AGENT
from app.parsers.date_cleaner import DHAKA_TZ
from app.parsers.epaper_gemini import GeminiEpaperParser

logger = logging.getLogger("epaper_jugantor")
BASE_URL = "https://epaper.jugantor.com"


def page_images(html: str, date_str: str) -> Dict[int, str]:
    """Full-page scans of the edition, by page number (clippings and feature pages excluded)."""
    found = re.findall(
        rf'(https://epaper\.jugantor\.com/storage/{date_str}/(\d+)/\d+_\2\.jpg)', html)
    return {int(page): url for url, page in found}


class JugantorEpaperCrawler:
    def __init__(self):
        self.parser = GeminiEpaperParser()

    async def crawl_edition(self, target_date: Optional[date] = None, max_pages: int = 24
                            ) -> Tuple[int, Optional[str], List[Dict[str, Any]]]:
        today = target_date or datetime.now(DHAKA_TZ).date()
        date_str = today.strftime("%Y-%m-%d")

        if not pc_browser.enabled():
            return 0, "NEEDS_PC_BROWSER: read by the scheduled task on the office PC", []
        async with pc_browser.chrome_pages() as get_html:
            status, html = await get_html(BASE_URL)
        if status != 200:
            return status, "BLOCKED" if status == 403 else f"HTTP_{status}", []

        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            pages = page_images(html, date_str)
            edition = re.search(rf'{re.escape(BASE_URL)}/(\w+)/{date_str}\?page=', html)
            logger.info(f"Daily Jugantor e-paper: {len(pages)} pages for {date_str}")
            extracted_tenders: List[Dict[str, Any]] = []

            for page_no in sorted(pages)[:max_pages]:
                img_url = pages[page_no]
                page_view_url = (f"{BASE_URL}/{edition.group(1)}/{date_str}?page={page_no}"
                                 if edition else f"{BASE_URL}/")
                try:
                    img_resp = await client.get(img_url, headers={"User-Agent": USER_AGENT})
                    if img_resp.status_code != 200 or len(img_resp.content) < 10000:
                        continue
                    tenders = await self.parser.extract_tenders_from_image(img_resp.content, "image/jpeg")
                    for t in tenders:
                        t["_page_no"] = str(page_no)
                        t["_page_title"] = f"Page {page_no}"
                        t["_page_url"] = page_view_url
                        t["_image_url"] = img_url
                        t["_edition_date"] = today.strftime("%d/%m/%Y")
                        t["_newspaper"] = "Daily Jugantor"
                        extracted_tenders.append(t)
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"Daily Jugantor page {page_no} error: {e}")

            return 200, None, extracted_tenders
