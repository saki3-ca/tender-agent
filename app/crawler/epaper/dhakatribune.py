"""
Dhaka Tribune E-Paper Crawler.

Major English daily newspaper in Bangladesh.
"""

import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.crawler.crawler import USER_AGENT
from app.parsers.date_cleaner import DHAKA_TZ
from app.parsers.epaper_gemini import GeminiEpaperParser

logger = logging.getLogger("epaper_dhakatribune")
BASE_URL = "https://epaper.dhakatribune.com"


class DhakaTribuneEpaperCrawler:
    def __init__(self):
        self.parser = GeminiEpaperParser()

    async def crawl_edition(self, target_date: Optional[date] = None, max_pages: int = 14
                            ) -> Tuple[int, Optional[str], List[Dict[str, Any]]]:
        """Crawls pages of Dhaka Tribune for the given date."""
        today = target_date or datetime.now(DHAKA_TZ).date()
        date_str = today.strftime("%Y-%m-%d")

        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            extracted_tenders: List[Dict[str, Any]] = []

            for page_num in range(1, max_pages + 1):
                # High-res image generation URL
                img_url = (
                    f"https://epaper-media-crop.dhakatribune.com/?width=1800&quality=85"
                    f"&image=/en/epaper/{date_str}/main-edition/{page_num}/full.jpg"
                )
                page_view_url = f"{BASE_URL}/?date={date_str}&edition=1&page={page_num}"
                logger.info(f"Processing Dhaka Tribune Page {page_num}: {img_url}")

                try:
                    img_resp = await client.get(img_url, headers={"User-Agent": USER_AGENT})
                    if img_resp.status_code != 200 or len(img_resp.content) < 10000:
                        # Page does not exist (reached end of edition)
                        if page_num > 4:
                            break
                        continue

                    tenders = await self.parser.extract_tenders_from_image(img_resp.content, "image/jpeg")
                    if tenders:
                        logger.info(f"Dhaka Tribune Page {page_num}: Extracted {len(tenders)} tender notice(s)")
                        for t in tenders:
                            t["_page_no"] = str(page_num)
                            t["_page_title"] = f"Page {page_num}"
                            t["_page_url"] = page_view_url
                            t["_image_url"] = img_url
                            t["_edition_date"] = today.strftime("%d/%m/%Y")
                            t["_newspaper"] = "Dhaka Tribune"
                            extracted_tenders.append(t)
                except Exception as e:
                    logger.warning(f"Dhaka Tribune page {page_num} error: {e}")
                    continue

            return 200, None, extracted_tenders
