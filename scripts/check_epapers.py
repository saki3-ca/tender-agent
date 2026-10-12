"""
Finds today's page images of every epaper_generic newspaper (no Gemini calls, so no quota is used) and
downloads the first page of each: shows which papers work right now.

    python scripts/check_epapers.py                 # all
    python scripts/check_epapers.py kalbela inqilab # only sources whose id contains one of these words
"""
import asyncio
import io
import sys
from datetime import datetime

import httpx

sys.path.insert(0, ".")
from app.crawler import pc_browser  # noqa: E402
from app.crawler.epaper.generic import GenericEpaperCrawler  # noqa: E402
from app.parsers.date_cleaner import DHAKA_TZ  # noqa: E402
from app.utils.config import config  # noqa: E402


async def check(source, day):
    crawler = GenericEpaperCrawler(source)
    async with httpx.AsyncClient(timeout=60, follow_redirects=True, proxy=pc_browser.proxy_url()) as client:
        status, error, pages = await crawler.discover(client, day)
        if error:
            return f"{source['id']:34} FAIL  {error[:70]} (status {status})"
        n, url = pages[0]
        r = await client.get(url, headers=crawler._headers())
        size = ""
        try:
            from PIL import Image
            size = "%dx%d" % Image.open(io.BytesIO(r.content)).size
        except Exception:  # noqa: BLE001
            pass
        return (f"{source['id']:34} OK    {len(pages):2} pages (first {n}, last {pages[-1][0]}); page {n}: HTTP {r.status_code}, "
                f"{len(r.content) // 1024} KB {size} {r.headers.get('content-type', '')}  {url[:90]}")


async def main(words):
    day = datetime.now(DHAKA_TZ).date()
    sources = [s for s in config.sources if s.get("type") == "epaper_generic" and (not words or any(w in s["id"] for w in words))]
    print(f"Edition date (Dhaka): {day}; {len(sources)} newspapers", flush=True)
    for s in sources:
        try:
            print(await check(s, day), flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"{s['id']:34} ERROR {type(e).__name__}: {str(e)[:100]}", flush=True)


asyncio.run(main(sys.argv[1:]))
