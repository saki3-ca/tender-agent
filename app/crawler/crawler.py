"""
HTTP fetching for tender pages and tender documents.

- One shared async client; requests to the same domain are spaced out (politeness delay).
- Failures are returned as error strings, never raised, so one broken source cannot stop a run.
- Pages that return 200 but are really "not found" pages or bot-challenge pages are reported
  as SOFT_404 / BLOCKED instead of being parsed for tenders.
"""

import asyncio
import re
import time
from dataclasses import dataclass
from typing import Dict, Optional
from urllib.parse import urlparse

import httpx

from app.utils.config import config
from app.utils.logging import logger

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36 ACNABIN-TenderMonitor/2.0"
)

_NOT_FOUND = re.compile(r"page not found|404 not found|\b404\b.*not found|the page you (?:are looking for|requested)", re.I)
_CHALLENGE = re.compile(
    r"security check required|client challenge|just a moment|attention required|verify you are human|"
    r"captcha|access denied|request rejected|enable javascript and cookies", re.I)


@dataclass
class FetchResult:
    url: str
    final_url: str = ""
    status: int = 0
    text: str = ""
    content: bytes = b""
    content_type: str = ""
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None


class TenderCrawler:
    def __init__(self):
        self.timeout = float(config.crawler_setting("request_timeout_seconds", 30))
        self.domain_delay = float(config.crawler_setting("per_domain_delay_seconds", 1.5))
        self.max_doc_bytes = int(config.crawler_setting("max_document_bytes", 15_000_000))
        self._locks: Dict[str, asyncio.Lock] = {}
        self._last: Dict[str, float] = {}
        self._clients: Dict[bool, httpx.AsyncClient] = {}

    def _client(self, verify_ssl: bool) -> httpx.AsyncClient:
        if verify_ssl not in self._clients:
            self._clients[verify_ssl] = httpx.AsyncClient(
                verify=verify_ssl,
                timeout=self.timeout,
                follow_redirects=True,
                headers={
                    "User-Agent": USER_AGENT,
                    "From": config.crawler_contact_email,
                    "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9,bn;q=0.8",
                },
            )
        return self._clients[verify_ssl]

    async def close(self) -> None:
        for client in self._clients.values():
            await client.aclose()
        self._clients.clear()

    async def _polite(self, url: str) -> asyncio.Lock:
        domain = urlparse(url).netloc
        lock = self._locks.setdefault(domain, asyncio.Lock())
        await lock.acquire()
        wait = self.domain_delay - (time.monotonic() - self._last.get(domain, 0.0))
        if wait > 0:
            await asyncio.sleep(wait)
        return lock

    def _release(self, url: str, lock: asyncio.Lock) -> None:
        self._last[urlparse(url).netloc] = time.monotonic()
        lock.release()

    async def fetch(self, url: str, verify_ssl: bool = True, binary: bool = False) -> FetchResult:
        result = FetchResult(url=url)
        lock = await self._polite(url)
        try:
            resp = await self._client(verify_ssl).get(url)
            result.status = resp.status_code
            result.final_url = str(resp.url)
            result.content_type = resp.headers.get("content-type", "").lower()
            if resp.status_code >= 400:
                body = resp.text[:3000] if not binary else ""
                result.error = "BLOCKED" if (resp.status_code in (401, 403, 429, 503) and _CHALLENGE.search(body)) \
                    else f"HTTP_{resp.status_code}"
                return result
            if binary:
                if len(resp.content) > self.max_doc_bytes:
                    result.error = "DOCUMENT_TOO_LARGE"
                    return result
                result.content = resp.content
            else:
                result.text = resp.text
        except httpx.TimeoutException:
            result.error = "TIMEOUT"
        except httpx.ConnectError as e:
            msg = str(e)
            result.error = "SSL_ERROR" if ("certificate" in msg.lower() or "ssl" in msg.lower()) else "CONNECTION_FAILED"
        except Exception as e:  # noqa: BLE001 - any failure is reported, never raised
            result.error = f"ERROR: {type(e).__name__}: {str(e)[:150]}"
        finally:
            self._release(url, lock)
        return result

    async def fetch_page(self, source: Dict) -> FetchResult:
        """Fetches a source page and classifies soft failures (not-found and challenge pages)."""
        if source.get("requires_js"):
            result = await self._fetch_with_playwright(source["url"])
        else:
            result = await self.fetch(source["url"], verify_ssl=source.get("verify_ssl", True))
            # Some sites answer simple HTTP clients with a "security check" page but serve a normal
            # browser. Retry once in a headless browser (no disguise; if it is still blocked, it stays blocked).
            if result.error == "BLOCKED" or (not result.ok and result.status in (401, 403)):
                rendered = await self._fetch_with_playwright(source["url"])
                if rendered.ok or rendered.error != "PLAYWRIGHT_NOT_INSTALLED":
                    result = rendered
        if result.ok:
            head = result.text[:6000]
            title_m = re.search(r"<title[^>]*>(.*?)</title>", head, re.I | re.S)
            title = title_m.group(1) if title_m else ""
            final_path = urlparse(result.final_url or result.url).path.lower()
            if "/404" in final_path or _NOT_FOUND.search(title):
                result.error = "SOFT_404"
            elif _CHALLENGE.search(title) or (len(result.text) < 8000 and _CHALLENGE.search(result.text)):
                result.error = "BLOCKED"
            elif urlparse(source["url"]).path.strip("/") and not final_path.strip("/"):
                result.error = "REDIRECTED_TO_HOMEPAGE"
        return result

    async def _fetch_with_playwright(self, url: str) -> FetchResult:
        result = FetchResult(url=url)
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            result.error = "PLAYWRIGHT_NOT_INSTALLED"
            return result
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page(user_agent=USER_AGENT)
                # "networkidle" never happens on pages with chat widgets / long polling: wait for load,
                # then give scripts a few seconds to render the list.
                resp = await page.goto(url, wait_until="load", timeout=int(self.timeout * 1000))
                await page.wait_for_timeout(4000)
                result.status = resp.status if resp else 0
                result.final_url = page.url
                result.text = await page.content()
                await browser.close()
                if result.status >= 400:
                    challenge = result.status in (401, 403, 429, 503) and _CHALLENGE.search(result.text[:8000])
                    result.error = "BLOCKED" if challenge else f"HTTP_{result.status}"
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Playwright render failed for {url}: {e}")
            result.error = f"RENDER_FAILED: {str(e)[:150]}"
        return result
