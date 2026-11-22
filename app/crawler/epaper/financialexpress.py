"""
The Financial Express E-Paper Crawler.

English business daily in Bangladesh, high concentration of bank, corporate,
government, and public procurement tenders.
"""

import json
import logging
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import httpx
from bs4 import BeautifulSoup

from app.crawler.crawler import USER_AGENT
from app.parsers.date_cleaner import DHAKA_TZ
from app.parsers.epaper_gemini import GeminiEpaperParser

logger = logging.getLogger("epaper_financialexpress")
BASE_URL = "https://epaper.thefinancialexpress.com.bd"


class FinancialExpressEpaperCrawler:
    def __init__(self):
        self.parser = GeminiEpaperParser()

    async def crawl_edition(self, target_date: Optional[date] = None, max_pages: int = 16
                            ) -> Tuple[int, Optional[str], List[Dict[str, Any]]]:
        """Crawls all pages of Financial Express for the given date."""
        today = target_date or datetime.now(DHAKA_TZ).date()
        date_folder = today.strftime("%Y/%m/%d")

        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            resp = await client.get(BASE_URL, headers={"User-Agent": USER_AGENT})
            if resp.status_code >= 400:
                return resp.status_code, f"HTTP_{resp.status_code}", []

            soup = BeautifulSoup(resp.text, "html.parser")
            page_candidates = []
            for img in soup.find_all("img"):
                src = img.get("src", "")
                if "thumb/page" in src.lower():
                    # convert thumb to pages URL
                    full_src = src.replace("/thumb/", "/pages/").replace("//", "/")
                    full_url = str(httpx.URL(BASE_URL).join(full_src))
                    if full_url not in page_candidates:
                        page_candidates.append(full_url)

            if not page_candidates:
                # fallback generator: page01.jpg to page16.jpg
                for i in range(1, max_pages + 1):
                    page_candidates.append(f"{BASE_URL}/{date_folder}/pages/page{i:02d}.jpg")

            logger.info(f"Financial Express e-paper: Found {len(page_candidates)} pages")
            extracted_tenders: List[Dict[str, Any]] = []

            for idx, img_url in enumerate(page_candidates[:max_pages], 1):
                page_view_url = f"{BASE_URL}/index.php?page={idx}"
                logger.info(f"Processing Financial Express Page {idx}: {img_url}")

                try:
                    # The full page image is only ~700 px wide: small tender ads are unreadable on it (this is how
                    # Rupali Bank's cash-assistance audit EOI of 19 Nov 2026 was missed). Each article/advert is
                    # also published as its own sharper image: read those, and the page only if there are none.
                    images = await self._article_images(client, idx, today) or [img_url]
                    for image_url in images:
                        img_resp = await client.get(image_url, headers={"User-Agent": USER_AGENT})
                        if img_resp.status_code != 200:
                            continue
                        tenders = await self.parser.extract_tenders_from_image(img_resp.content, "image/jpeg")
                        if tenders:
                            logger.info(f"Financial Express Page {idx}: Extracted {len(tenders)} tender notice(s)")
                        for t in tenders:
                            t["_page_no"] = str(idx)
                            t["_page_title"] = f"Page {idx}"
                            t["_page_url"] = page_view_url
                            t["_image_url"] = image_url
                            t["_edition_date"] = today.strftime("%d/%m/%Y")
                            t["_newspaper"] = "The Financial Express"
                            extracted_tenders.append(t)
                except Exception as e:
                    logger.warning(f"Financial Express page {idx} error: {e}")
                    continue

            return 200, None, extracted_tenders

    async def _article_images(self, client: httpx.AsyncClient, page_no: int, day: date) -> List[str]:
        """Sharp per-article images of one page (epaper.php fragment: <date>/images/<page>_<n>.jpg)."""
        try:
            resp = await client.get(f"{BASE_URL}/epaper.php",
                                    params={"page_num": f"{page_no:02d}", "date": day.strftime("%Y_%m_%d")},
                                    headers={"User-Agent": USER_AGENT})
        except httpx.HTTPError:
            return []
        if resp.status_code != 200:
            return []
        return article_image_urls(resp.text, page_no, day)


def article_image_urls(fragment_html: str, page_no: int, day: date) -> List[str]:
    folder = day.strftime("%Y/%m/%d")
    found = re.findall(rf"{re.escape(folder)}/images/{page_no:02d}_\d+\.jpe?g", fragment_html)
    return [f"{BASE_URL}/{p}" for p in dict.fromkeys(found)]
