"""
Pages read in a real Chrome window, for the few sources whose Cloudflare setting serves pages to
browsers only (Jugantor, Bangladesh Pratidin).

Runs unattended in GitHub Actions: the workflow starts the job under a virtual display (xvfb), so Chrome
runs as a normal "headed" browser and does not announce itself as automation. It also still works as the
office PC task (run_monitor.py --pc-browser).

If Cloudflare blocks the GitHub runner's IP address even for a real browser, set EPAPER_PROXY_URL
(for example a residential proxy: http://user:pass@host:port); Chrome and the image downloads then use it.
"""

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, Optional, Tuple
from urllib.parse import unquote, urlparse

logger = logging.getLogger("pc_browser")

ENV_FLAG = "EPAPER_PC_BROWSER"
PROXY_ENV = "EPAPER_PROXY_URL"
CHROME_PATH_ENV = "EPAPER_CHROME_PATH"   # optional: a specific Chrome / Chromium executable

ATTEMPTS = 3                  # fresh tries per page when the browser check does not clear
CHALLENGE_WAIT_STEPS = 30     # x 1.5 s: how long one try waits for "Just a moment…" to go away

GetHtml = Callable[[str], Awaitable[Tuple[int, str]]]

# Several newspapers are read in parallel; this keeps at most two Chrome windows open at once.
_BROWSER_SLOTS = asyncio.Semaphore(2)


def enabled() -> bool:
    return os.getenv(ENV_FLAG) == "1"


def proxy_url() -> Optional[str]:
    """Proxy for the browser and the image downloads, if one is configured."""
    return (os.getenv(PROXY_ENV) or "").strip() or None


def proxy_settings(url: Optional[str]) -> Optional[Dict[str, str]]:
    """Playwright proxy settings from http://user:pass@host:port (credentials are optional)."""
    if not url:
        return None
    u = urlparse(url)
    if not u.hostname:
        return None
    settings = {"server": f"{u.scheme or 'http'}://{u.hostname}" + (f":{u.port}" if u.port else "")}
    if u.username:
        settings["username"] = unquote(u.username)
        settings["password"] = unquote(u.password or "")
    return settings


def _needs_headless() -> bool:
    """No screen at all (Linux without DISPLAY): a headed window cannot open."""
    return sys.platform.startswith("linux") and not os.getenv("DISPLAY")


async def _launch(p: Any) -> Any:
    """Installed Google Chrome first; the bundled Chromium when Chrome is not installed."""
    kwargs: Dict[str, Any] = {
        "headless": _needs_headless(),
        "args": ["--window-position=0,0", "--window-size=1200,800", "--disable-blink-features=AutomationControlled"],
        "ignore_default_args": ["--enable-automation"],
    }
    if path := (os.getenv(CHROME_PATH_ENV) or "").strip():
        return await p.chromium.launch(executable_path=path, **kwargs)
    try:
        return await p.chromium.launch(channel="chrome", **kwargs)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Google Chrome is not available ({str(e).splitlines()[0]}); using the bundled Chromium")
        return await p.chromium.launch(**kwargs)


@asynccontextmanager
async def chrome_pages() -> AsyncIterator[GetHtml]:
    """Yields get(url) -> (status, html); status is 403 if the browser check did not clear.

    get.large_images(min_bytes) -> addresses of the big images the page loaded (page scans), in load order.
    """
    from playwright.async_api import async_playwright

    async with _BROWSER_SLOTS, async_playwright() as p:
        browser = await _launch(p)
        context_args: Dict[str, Any] = {"locale": "en-US", "timezone_id": "Asia/Dhaka",
                                        "viewport": {"width": 1200, "height": 800}}
        if proxy := proxy_settings(proxy_url()):
            context_args["proxy"] = proxy
        context = await browser.new_context(**context_args)
        page = await context.new_page()

        seen_images: Dict[str, int] = {}

        async def note_image(resp: Any) -> None:
            try:
                if (resp.headers.get("content-type") or "").startswith("image/") and resp.status == 200 and resp.url not in seen_images:
                    size = int(resp.headers.get("content-length") or 0) or len(await resp.body())
                    seen_images[resp.url] = size
            except Exception:  # noqa: BLE001
                pass

        page.on("response", lambda r: asyncio.ensure_future(note_image(r)))

        async def large_images(min_bytes: int) -> list:
            """Scrolls the page so lazy images load, then lists the large ones."""
            for _ in range(4):
                await page.mouse.wheel(0, 2000)
                await page.wait_for_timeout(1200)
            await page.wait_for_timeout(2000)
            return [u for u, size in seen_images.items() if size >= min_bytes]

        async def get(url: str) -> Tuple[int, str]:
            last_status = 403
            for attempt in range(1, ATTEMPTS + 1):
                try:
                    resp = await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                except Exception as e:  # noqa: BLE001 (timeouts, dropped connections)
                    logger.warning(f"{url}: attempt {attempt}/{ATTEMPTS} failed to load: {str(e).splitlines()[0]}")
                    last_status = 504
                    await page.wait_for_timeout(3000)
                    continue
                for _ in range(CHALLENGE_WAIT_STEPS):
                    if "just a moment" not in (await page.title()).lower():
                        await page.wait_for_timeout(2000)
                        status = resp.status if resp and resp.status < 400 else 200
                        return status, await page.content()
                    await page.wait_for_timeout(1500)
                logger.warning(f"{url}: browser check did not clear (attempt {attempt}/{ATTEMPTS})")
                last_status = 403
                await page.wait_for_timeout(5000)
            return last_status, await page.content() if last_status == 403 else ""

        get.large_images = large_images  # type: ignore[attr-defined]
        try:
            yield get
        finally:
            await browser.close()
