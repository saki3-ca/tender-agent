"""
Search Engine Discovery Module.
Uses official search APIs (Google Custom Search, Brave Search API, SerpAPI) to discover
new tender announcements and unlisted notice pages.
Strictly complies with the rule: Never scrapes search engine result pages.
"""

import os
import hashlib
from typing import Any, Dict, List, Optional
import httpx
from app.utils.logging import logger
from app.utils.config import config
from app.db.supabase import db


class SearchDiscoveryAgent:
    """Discovers tender announcements via compliant search APIs."""

    def __init__(self):
        self.provider = os.getenv("SEARCH_PROVIDER", config.settings.get("search", {}).get("provider", "google")).lower()
        self.api_key = os.getenv("SEARCH_API_KEY", "")
        self.engine_id = os.getenv("SEARCH_ENGINE_ID", "")
        self.daily_limit = int(config.settings.get("search", {}).get("daily_query_limit", 100))

    def is_configured(self) -> bool:
        return bool(self.api_key and (self.engine_id or self.provider == "brave"))

    async def search_query(self, query: str) -> List[str]:
        """Executes a search query via the configured API provider and returns discovered URLs."""
        if not self.is_configured():
            logger.debug(f"Search API not configured; skipping discovery query: {query}")
            return []

        # Deduplicate and cache query
        query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()

        if self.provider == "google":
            return await self._search_google(query, query_hash)
        elif self.provider == "brave":
            return await self._search_brave(query, query_hash)
        else:
            logger.warning(f"Unsupported search provider: {self.provider}")
            return []

    async def _search_google(self, query: str, query_hash: str) -> List[str]:
        url = "https://www.googleapis.com/customsearch/v1"
        params = {
            "key": self.api_key,
            "cx": self.engine_id,
            "q": query,
            "num": 10
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
                items = data.get("items", [])
                links = [it["link"] for it in items if "link" in it]
                return links
        except Exception as e:
            logger.error(f"Google Search API error: {e}")
            return []

    async def _search_brave(self, query: str, query_hash: str) -> List[str]:
        url = "https://api.search.brave.com/res/v1/web/search"
        headers = {
            "Accept": "application/json",
            "X-Subscription-Token": self.api_key
        }
        params = {"q": query, "count": 10}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, headers=headers, params=params)
                resp.raise_for_status()
                data = resp.json()
                results = data.get("web", {}).get("results", [])
                return [r["url"] for r in results if "url" in r]
        except Exception as e:
            logger.error(f"Brave Search API error: {e}")
            return []

    def generate_bank_queries(self, target_banks: List[Dict[str, Any]]) -> List[str]:
        """Constructs targeted query patterns per Section 13."""
        queries = []
        # Sector-wide queries
        queries.extend([
            '"Bangladesh Bank" tender "audit" OR "consultant" OR "IFRS 9"',
            'Bangladesh "IFRS 9" tender OR RFP OR EOI',
            'Bangladesh "Expected Credit Loss" RFP OR tender',
            'Bangladesh "Asset Quality Review" tender OR EOI'
        ])

        # Org specific queries
        for b in target_banks[:10]:
            name = b["canonical_name"]
            queries.append(f'"{name}" tender OR RFP OR EOI OR "নিরীক্ষা" OR "দরপত্র"')

        return queries
