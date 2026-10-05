"""
Asynchronous Web Crawler module for ACNABIN Tender Agent.
Implements polite domain rate-limiting, conditional GETs (ETag / If-Modified-Since),
custom User-Agent with contact email, Playwright fallback for JavaScript-rendered sites,
and graceful timeout budgeting.
"""

import time
import asyncio
from datetime import datetime, timezone
from urllib.parse import urlparse
from typing import Any, Dict, List, Optional, Tuple

import httpx
from app.utils.logging import logger
from app.utils.config import config
from app.parsers.html_parser import HtmlNoticeExtractor, clean_html_text, compute_content_hash
from app.parsers.document_parser import DocumentParser


class DomainRateLimiter:
    """Tracks last request timestamp per domain to enforce rate limits."""

    def __init__(self, default_interval: float = 5.0):
        self.default_interval = default_interval
        self._last_access: Dict[str, float] = {}

    async def wait_for_domain(self, url: str, interval: Optional[float] = None) -> None:
        domain = urlparse(url).netloc
        needed_interval = interval if interval is not None else self.default_interval
        now = time.time()
        last_time = self._last_access.get(domain, 0.0)
        elapsed = now - last_time
        if elapsed < needed_interval:
            wait_time = needed_interval - elapsed
            await asyncio.sleep(wait_time)
        self._last_access[domain] = time.time()


class TenderCrawler:
    """Manages crawling of sources, conditional HTTP fetching, and document extraction."""

    def __init__(self):
        self.rate_limiter = DomainRateLimiter(
            default_interval=float(config.settings.get("crawler", {}).get("default_rate_limit_seconds", 5.0))
        )
        self.contact_email = config.crawler_contact_email
        self.user_agent = f"ACNABIN-Tender-Intelligence-Bot/1.0 (+https://tender-agent-d01.pages.dev; contact: {self.contact_email})"
        self.timeout = float(config.settings.get("crawler", {}).get("request_timeout_seconds", 30))

    def _get_headers(self, etag: Optional[str] = None, last_modified: Optional[str] = None) -> Dict[str, str]:
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,bn;q=0.8",
        }
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        return headers

    async def fetch_source_html(self, source: Dict[str, Any]) -> Tuple[int, Optional[str], Dict[str, str], Optional[str]]:
        """
        Fetches HTML from a source URL using conditional GETs.
        Returns: (http_status, html_content, response_headers, error_message)
        """
        url = source["url"]
        verify_ssl = source.get("verify_ssl", True)
        if not verify_ssl:
            logger.warning("Crawling source with verify_ssl=False", extra={"url": url, "source_id": source.get("id")})

        await self.rate_limiter.wait_for_domain(url, interval=float(source.get("rate_limit_seconds", 5.0)))

        headers = self._get_headers(etag=source.get("etag"), last_modified=source.get("last_modified"))

        # If requires_js is True, try Playwright if installed
        if source.get("requires_js", False):
            return await self._fetch_with_playwright(url)

        try:
            async with httpx.AsyncClient(
                verify=verify_ssl,
                timeout=self.timeout,
                follow_redirects=True
            ) as client:
                resp = await client.get(url, headers=headers)

                # 304 Not Modified
                if resp.status_code == 304:
                    return 304, None, dict(resp.headers), None

                # Suspected geo-block or access denied
                if resp.status_code in (403, 401) and any(kw in resp.text.lower() for kw in ["geo", "forbidden", "cloudflare", "access denied"]):
                    return resp.status_code, None, dict(resp.headers), "GEO_BLOCK_SUSPECTED"

                resp.raise_for_status()
                return resp.status_code, resp.text, dict(resp.headers), None

        except httpx.HTTPStatusError as e:
            return e.response.status_code, None, {}, str(e)
        except httpx.ConnectTimeout:
            return 0, None, {}, "CONNECTION_TIMEOUT"
        except httpx.ConnectError as e:
            # Often broken TLS or DNS resolution
            if "certificate" in str(e).lower() or "ssl" in str(e).lower():
                return 0, None, {}, f"SSL_ERROR: {e}"
            return 0, None, {}, f"CONNECT_ERROR: {e}"
        except Exception as e:
            return 0, None, {}, f"UNEXPECTED_ERROR: {e}"

    async def _fetch_with_playwright(self, url: str) -> Tuple[int, Optional[str], Dict[str, str], Optional[str]]:
        """Renders dynamic JavaScript pages with Playwright Chromium."""
        try:
            from playwright.async_api import async_playwright
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page(user_agent=self.user_agent)
                response = await page.goto(url, wait_until="networkidle", timeout=int(self.timeout * 1000))
                status = response.status if response else 200
                content = await page.content()
                await browser.close()
                return status, content, {}, None
        except Exception as e:
            logger.warning(f"Playwright render failed for {url}: {e}; falling back to httpx")
            # Fallback to standard httpx
            try:
                async with httpx.AsyncClient(verify=False, timeout=self.timeout, follow_redirects=True) as client:
                    resp = await client.get(url, headers=self._get_headers())
                    return resp.status_code, resp.text, dict(resp.headers), None
            except Exception as fe:
                return 0, None, {}, str(fe)

    async def download_document(self, doc_url: str, verify_ssl: bool = True) -> Tuple[Optional[bytes], Optional[str]]:
        """Downloads document binary (PDF/DOCX/XLSX) with rate limiting."""
        await self.rate_limiter.wait_for_domain(doc_url, interval=2.0)
        try:
            async with httpx.AsyncClient(verify=verify_ssl, timeout=self.timeout, follow_redirects=True) as client:
                resp = await client.get(doc_url, headers={"User-Agent": self.user_agent})
                resp.raise_for_status()
                return resp.content, None
        except Exception as e:
            logger.error(f"Failed to download document from {doc_url}: {e}")
            return None, str(e)
