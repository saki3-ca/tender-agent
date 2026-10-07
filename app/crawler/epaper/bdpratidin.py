"""
Bangladesh Pratidin E-Paper Crawler.

Highest circulation Bangla daily newspaper in Bangladesh. Each page view (/epaper/<date>/<page>)
names its scan as cdn.bd-pratidin.com/public/paper/<y>/<m>/<d>/thumb/<id>-<page>.jpg; the
full-size scan is the same path without "thumb/" and is public. Cloudflare serves the page
views to browsers only: they are read in Chrome on the office PC (pc_browser).
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

logger = logging.getLogger("epaper_bdpratidin")
BASE_URL = "https://www.bd-pratidin.com/epaper"


def page_numbers(html: str, date_str: str) -> List[int]:
    return sorted({int(p) for p in re.findall(rf'/epaper/{date_str}/(\d+)"', html)})


def full_page_image(html: str, date_folder: str, page_no: int) -> Optional[str]:
    m = re.search(rf'https://cdn\.bd-pratidin\.com/public/paper/{date_folder}/thumb/(\d+-{page_no})\.jpg', html)
    return f"https://cdn.bd-pratidin.com/public/paper/{date_folder}/{m.group(1)}.jpg" if m else None


def _blocked(status: int) -> Optional[str]:
    if status == 200:
        return None
    return "BLOCKED" if status == 403 else f"HTTP_{status}"


class BdPratidinEpaperCrawler:
    def __init__(self):
        self.parser = GeminiEpaperParser()

    async def crawl_edition(self, target_date: Optional[date] = None, max_pages: int = 24
                            ) -> Tuple[int, Optional[str], List[Dict[str, Any]]]:
        today = target_date or datetime.now(DHAKA_TZ).date()
        date_str = today.strftime("%Y-%m-%d")
        date_folder = today.strftime("%Y/%m/%d")

        if not pc_browser.enabled():
            return 0, "NEEDS_PC_BROWSER: read by the scheduled task on the office PC", []
        async with pc_browser.chrome_pages() as get_html, \
                httpx.AsyncClient(timeout=60.0, follow_redirects=True,
                                  headers={"User-Agent": USER_AGENT}) as client:
            status, html = await get_html(BASE_URL)
            if error := _blocked(status):
                return status, error, []

            pages = page_numbers(html, date_str)
            logger.info(f"Bangladesh Pratidin e-paper: {len(pages)} pages for {date_str}")
            extracted_tenders: List[Dict[str, Any]] = []

            for page_no in pages[:max_pages]:
                page_view_url = f"{BASE_URL}/{date_str}/{page_no}"
                try:
                    status, view = await get_html(page_view_url)
                    if error := _blocked(status):
                        return status, error, extracted_tenders
                    img_url = full_page_image(view, date_folder, page_no)
                    if not img_url:
                        continue
                    img_resp = await client.get(img_url)
                    if img_resp.status_code != 200 or len(img_resp.content) < 10000:
                        continue
                    tenders = await self.parser.extract_tenders_from_image(img_resp.content, "image/jpeg")
                    for t in tenders:
                        t["_page_no"] = str(page_no)
                        t["_page_title"] = f"Page {page_no}"
                        t["_page_url"] = page_view_url
                        t["_image_url"] = img_url
                        t["_edition_date"] = today.strftime("%d/%m/%Y")
                        t["_newspaper"] = "Bangladesh Pratidin"
                        extracted_tenders.append(t)
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"Bangladesh Pratidin page {page_no} error: {e}")

            return 200, None, extracted_tenders
