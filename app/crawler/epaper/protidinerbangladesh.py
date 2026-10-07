"""
Protidiner Bangladesh E-Paper Crawler.

Popular Bangla daily newspaper in Bangladesh.
"""

import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import httpx
from bs4 import BeautifulSoup

from app.crawler.crawler import USER_AGENT
from app.parsers.date_cleaner import DHAKA_TZ
from app.parsers.epaper_gemini import GeminiEpaperParser

logger = logging.getLogger("epaper_protidinerbangladesh")
BASE_URL = "https://epaper.protidinerbangladesh.com"


class ProtidinerBangladeshEpaperCrawler:
    def __init__(self):
        self.parser = GeminiEpaperParser()

    async def crawl_edition(self, target_date: Optional[date] = None, max_pages: int = 14
                            ) -> Tuple[int, Optional[str], List[Dict[str, Any]]]:
        """Crawls all pages of Protidiner Bangladesh for the given date."""
        today = target_date or datetime.now(DHAKA_TZ).date()

        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            resp = await client.get(BASE_URL, headers={"User-Agent": USER_AGENT})
            if resp.status_code >= 400:
                return resp.status_code, f"HTTP_{resp.status_code}", []

            soup = BeautifulSoup(resp.text, "html.parser")
            page_candidates = []
            for img in soup.find_all("img"):
                src = img.get("src", "")
                if "/thumb/page" in src:
                    full_src = src.replace("/thumb/", "/pages/")
                    if full_src not in page_candidates:
                        page_candidates.append(full_src)

            logger.info(f"Protidiner Bangladesh e-paper: Found {len(page_candidates)} pages")
            extracted_tenders: List[Dict[str, Any]] = []

            for idx, img_url in enumerate(page_candidates[:max_pages], 1):
                page_view_url = f"{BASE_URL}/"
                logger.info(f"Processing Protidiner Bangladesh Page {idx}: {img_url}")

                try:
                    img_resp = await client.get(img_url, headers={"User-Agent": USER_AGENT})
                    if img_resp.status_code != 200:
                        continue

                    tenders = await self.parser.extract_tenders_from_image(img_resp.content, "image/jpeg")
                    if tenders:
                        logger.info(f"Protidiner Bangladesh Page {idx}: Extracted {len(tenders)} tender notice(s)")
                        for t in tenders:
                            t["_page_no"] = str(idx)
                            t["_page_title"] = f"Page {idx}"
                            t["_page_url"] = page_view_url
                            t["_image_url"] = img_url
                            t["_edition_date"] = today.strftime("%d/%m/%Y")
                            t["_newspaper"] = "Protidiner Bangladesh"
                            extracted_tenders.append(t)
                except Exception as e:
                    logger.warning(f"Protidiner Bangladesh page {idx} error: {e}")
                    continue

            return 200, None, extracted_tenders
