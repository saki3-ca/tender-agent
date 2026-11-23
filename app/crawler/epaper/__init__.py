"""
E-Paper crawlers package for daily newspapers in Bangladesh.
"""

import asyncio

import httpx


async def get_page_image(client: httpx.AsyncClient, url: str, attempts: int = 3, **kwargs) -> httpx.Response:
    """Download one page image, retrying dropped connections and 5xx answers (newspaper servers often drop a
    request: Financial Express page 2 was lost on 23 Nov 2026 to one "Server disconnected")."""
    for attempt in range(1, attempts + 1):
        try:
            resp = await client.get(url, **kwargs)
            if resp.status_code < 500 or attempt == attempts:
                return resp
        except (httpx.TransportError, httpx.TimeoutException):
            if attempt == attempts:
                raise
        await asyncio.sleep(3 * attempt)
    raise RuntimeError("unreachable")
