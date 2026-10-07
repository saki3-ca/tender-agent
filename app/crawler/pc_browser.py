"""
Pages read in the installed Google Chrome, in a normal visible window, for the few sources whose
Cloudflare setting serves pages to browsers only. Used by run_monitor.py --pc-browser on the
office PC (a home/office IP and a real browser window); never in GitHub Actions.
"""

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator, Awaitable, Callable, Tuple

ENV_FLAG = "EPAPER_PC_BROWSER"

GetHtml = Callable[[str], Awaitable[Tuple[int, str]]]


def enabled() -> bool:
    return os.getenv(ENV_FLAG) == "1"


@asynccontextmanager
async def chrome_pages() -> AsyncIterator[GetHtml]:
    """Yields get(url) -> (status, html); status is 403 if the browser check did not clear."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=False,
                                          args=["--window-position=0,0", "--window-size=1200,800"])
        page = await browser.new_page()

        async def get(url: str) -> Tuple[int, str]:
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            for _ in range(20):
                if "just a moment" not in (await page.title()).lower():
                    break
                await page.wait_for_timeout(1500)
            else:
                return 403, await page.content()
            await page.wait_for_timeout(2000)
            status = resp.status if resp and resp.status < 400 else 200
            return status, await page.content()

        try:
            yield get
        finally:
            await browser.close()
