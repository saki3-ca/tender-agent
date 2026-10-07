"""
Bangladesh Pratidin E-Paper Crawler.

Highest circulation Bangla daily newspaper in Bangladesh.
Protected by Cloudflare; uses Selenium for bypass.
"""

import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import httpx
from bs4 import BeautifulSoup

from app.crawler.crawler import USER_AGENT
from app.parsers.date_cleaner import DHAKA_TZ
from app.utils.cloudflare_bypass import fetch_with_selenium, fetch_image_with_selenium

logger = logging.getLogger("epaper_bdpratidin")
BASE_URL = "https://www.bd-pratidin.com/epaper"


class BdPratidinEpaperCrawler:
    def __init__(self, use_groq: bool = True):
        if use_groq:
            try:
                from app.parsers.epaper_groq import DualParserStrategy
                self.parser = DualParserStrategy()
                logger.info("Using Groq + Gemini dual parser strategy for Bangladesh Pratidin")
            except Exception as e:
                logger.warning(f"Groq parser unavailable: {e}; falling back to Gemini")
                from app.parsers.epaper_gemini import GeminiEpaperParser
                self.parser = GeminiEpaperParser()
        else:
            from app.parsers.epaper_gemini import GeminiEpaperParser
            self.parser = GeminiEpaperParser()

    async def crawl_edition(self, target_date: Optional[date] = None, max_pages: int = 14
                            ) -> Tuple[int, Optional[str], List[Dict[str, Any]]]:
        """Crawls all pages of Bangladesh Pratidin for the given date."""
        today = target_date or datetime.now(DHAKA_TZ).date()
        date_folder = today.strftime("%Y/%m/%d")

        # Use Selenium to bypass Cloudflare challenge
        logger.info("Fetching Bangladesh Pratidin homepage with Selenium (Cloudflare bypass)...")
        html = await fetch_with_selenium(BASE_URL, timeout=30)
        page_candidates = []

        if html:
            soup = BeautifulSoup(html, "html.parser")
            for img in soup.find_all("img"):
                src = img.get("src", "")
                if "paper" in src and (".jpg" in src or ".png" in src):
                    if src not in page_candidates:
                        page_candidates.append(src)

        # If none found from raw HTML, discover from CDN path
        if not page_candidates:
            for p in range(1, max_pages + 1):
                page_candidates.append(f"https://cdn.bd-pratidin.com/public/paper/{date_folder}/pages/{p}.jpg")

        logger.info(f"Bangladesh Pratidin e-paper: Found {len(page_candidates)} pages")
        extracted_tenders: List[Dict[str, Any]] = []

        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            for idx, img_url in enumerate(page_candidates[:max_pages], 1):
                page_view_url = f"{BASE_URL}/"
                logger.info(f"Processing Bangladesh Pratidin Page {idx}: {img_url}")

                try:
                    # Try regular HTTP first, fall back to Selenium if blocked
                    img_resp = await client.get(img_url, headers={"User-Agent": USER_AGENT})
                    img_data = img_resp.content if img_resp.status_code == 200 else None

                    if not img_data:
                        logger.info(f"HTTP fetch blocked; trying Selenium for {img_url}")
                        img_data = await fetch_image_with_selenium(img_url, timeout=30)

                    if not img_data or len(img_data) < 10000:
                        continue

                    tenders = await self.parser.extract_tenders_from_image(img_data, "image/jpeg")
                    if tenders:
                        logger.info(f"Bangladesh Pratidin Page {idx}: Extracted {len(tenders)} tender notice(s)")
                        for t in tenders:
                            t["_page_no"] = str(idx)
                            t["_page_title"] = f"Page {idx}"
                            t["_page_url"] = page_view_url
                            t["_image_url"] = img_url
                            t["_edition_date"] = today.strftime("%d/%m/%Y")
                            t["_newspaper"] = "Bangladesh Pratidin"
                            extracted_tenders.append(t)
                except Exception as e:
                    logger.warning(f"Bangladesh Pratidin page {idx} error: {e}")
                    continue

        return 200, None, extracted_tenders
