"""
Prothom Alo E-Paper Crawler.

Fetches the daily digital edition pages of Prothom Alo (Dhaka edition / all pages),
downloads high-resolution page images, and uses Gemini Vision to extract tenders.
"""

import asyncio
import json
import logging
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import httpx

from app.crawler.crawler import USER_AGENT
from app.parsers.date_cleaner import DHAKA_TZ, deadline_datetime, extract_dates, parse_first_date
from app.parsers.epaper_gemini import GeminiEpaperParser
from app.parsers.html_parser import Listing
from app.utils.config import config

logger = logging.getLogger("epaper_prothomalo")

BASE_URL = "https://epaper.prothomalo.com"


class ProthomAloEpaperCrawler:
    def __init__(self, edition_id: int = 1):
        self.edition_id = edition_id
        self.parser = GeminiEpaperParser()

    async def fetch_page_list(self, client: httpx.AsyncClient, edate_str: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetches the edition HTML and extracts the pglist_ array."""
        urls = []
        if edate_str:
            urls.append(f"{BASE_URL}/Home/DIndex?eid={self.edition_id}&edate={edate_str}")
        urls.append(f"{BASE_URL}/")

        headers = {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}
        for url in urls:
            try:
                resp = await client.get(url, headers=headers)
                if resp.status_code >= 400:
                    continue
                html = resp.text
                m = re.search(r"var\s+pglist_\s*=\s*(\[.*?\]);", html, re.DOTALL)
                if m:
                    pages = json.loads(m.group(1))
                    if pages:
                        return pages
            except Exception as e:
                logger.warning(f"Failed to load Prothom Alo from {url}: {e}")

        return []

    async def crawl_edition(self, target_date: Optional[date] = None, max_pages: int = 16
                            ) -> Tuple[int, Optional[str], List[Dict[str, Any]]]:
        """Crawls all pages for the given date (default today) and extracts tenders."""
        today = target_date or datetime.now(DHAKA_TZ).date()
        edate_str = today.strftime("%d/%m/%Y")

        async with httpx.AsyncClient(timeout=60.0) as client:
            pages = await self.fetch_page_list(client, edate_str)
            if not pages:
                return 404, "NO_PAGES_FOUND", []

            logger.info(f"Prothom Alo e-paper: Found {len(pages)} pages for {edate_str}")
            extracted_tenders: List[Dict[str, Any]] = []

            for page in pages[:max_pages]:
                page_no = page.get("PageNo", "")
                page_title = page.get("NewsProPageTitle", "")
                page_id = page.get("PageId", "")
                image_url = (
                    page.get("HighResolution_Without_mr")
                    or page.get("HighResolution")
                    or page.get("XHighResolution")
                )

                if not image_url:
                    continue

                page_view_url = f"{BASE_URL}/Home/DIndex?eid={self.edition_id}&edate={edate_str}&pgid={page_id}"
                logger.info(f"Processing Prothom Alo Page {page_no} ({page_title}): {image_url}")

                try:
                    img_resp = await client.get(image_url, headers={"User-Agent": USER_AGENT})
                    if img_resp.status_code != 200:
                        logger.warning(f"Failed to download page {page_no} image: HTTP {img_resp.status_code}")
                        continue

                    # Send page image to Gemini Vision
                    tenders = await self.parser.extract_tenders_from_image(img_resp.content, "image/jpeg")
                    if tenders:
                        logger.info(f"Page {page_no} ({page_title}): Extracted {len(tenders)} tender notice(s)")
                        for t in tenders:
                            t["_page_no"] = page_no
                            t["_page_title"] = page_title
                            t["_page_url"] = page_view_url
                            t["_image_url"] = image_url
                            t["_edition_date"] = edate_str
                            extracted_tenders.append(t)
                except Exception as e:
                    logger.warning(f"Error processing page {page_no}: {e}")
                    continue

            return 200, None, extracted_tenders
