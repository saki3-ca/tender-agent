"""
One-off diagnostic: how is each e-paper site built? (GitHub runner, real Chrome under xvfb)

For every site it prints compact JSON lines: status, title, links that look like the e-paper,
images on the page, images/JSON the page loaded by itself (network log), and framework hints.
Not part of the monitor.
"""
import asyncio
import json
import os
import re
import sys
from urllib.parse import urljoin

import httpx

SITES = [s for s in os.getenv("PROBE_SITES", "").split() if s] or [
    "https://enayadiganta.com/",
    "https://epaper.observerbd.com/",
    "https://eamardesh.com/",
    "https://epaper.deshrupantor.com/",
    "https://epaper.samakal.com/",
    "https://epaper.dainikamadershomoy.com/",
    "https://epaper.kalbela.com/",
    "https://epaper.ajkerpatrika.com/",
    "https://epaper.dainikbangla.com.bd/",
    "https://epaper.dailyinqilab.com/",
    "https://epaper.newagebd.net/",
    "https://epaper.dhakatribune.com/",
    "https://epaper.protidinerbangladesh.com/",
]
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
EPAPER_WORDS = re.compile(r"e-?paper|ই-?পেপার|ইপেপার|epaper", re.I)


def out(tag, **kw):
    print("PROBE " + tag + " " + json.dumps(kw, ensure_ascii=False)[:6000], flush=True)


async def plain(url):
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent": UA}) as c:
            r = await c.get(url)
            out("httpx", url=url, status=r.status_code, final=str(r.url), size=len(r.text),
                server=r.headers.get("server"), cf=("cf-ray" in r.headers))
    except Exception as e:  # noqa: BLE001
        out("httpx", url=url, error=f"{type(e).__name__}: {str(e)[:150]}")


async def inspect(browser, url, depth=0):
    ctx = await browser.new_context(locale="en-US", timezone_id="Asia/Dhaka", viewport={"width": 1280, "height": 900})
    page = await ctx.new_page()
    net = []

    async def on_response(resp):
        try:
            ct = resp.headers.get("content-type", "")
            if ct.startswith("image/") and "svg" not in ct:
                size = int(resp.headers.get("content-length") or 0)
                net.append({"k": "img", "u": resp.url[:200], "s": resp.status, "b": size})
            elif "json" in ct and resp.request.resource_type in ("xhr", "fetch"):
                body = (await resp.text())[:400]
                net.append({"k": "json", "u": resp.url[:200], "s": resp.status, "body": body})
        except Exception:  # noqa: BLE001
            pass

    page.on("response", lambda r: asyncio.ensure_future(on_response(r)))
    try:
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        for _ in range(20):
            if "just a moment" not in (await page.title()).lower():
                break
            await page.wait_for_timeout(1500)
        await page.wait_for_timeout(6000)
        await page.mouse.wheel(0, 1500)
        await page.wait_for_timeout(2500)
        info = await page.evaluate(
            """() => {
              const abs = u => { try { return new URL(u, location.href).href } catch(e) { return u } };
              const imgs = [...document.images].map(i => abs(i.currentSrc || i.src || i.dataset.src || i.dataset.original || '')).filter(Boolean);
              const links = [...document.querySelectorAll('a[href]')].map(a => ({t: (a.textContent||'').trim().slice(0,40), h: abs(a.getAttribute('href'))}));
              const hints = [];
              if (window.__NEXT_DATA__) hints.push('next');
              if (window.__NUXT__) hints.push('nuxt');
              if (window.jQuery) hints.push('jquery');
              if (document.querySelector('[ng-app],[ng-version]')) hints.push('angular');
              if (document.querySelector('#__next')) hints.push('#__next');
              if (document.querySelector('#root')) hints.push('#root');
              const data = Object.keys(document.body.dataset||{}).slice(0,5);
              return {title: document.title, final: location.href, imgs, links, hints, data,
                      html: document.documentElement.outerHTML.length,
                      pageish: [...document.querySelectorAll('[data-page],[data-src],[data-large],[data-full],[data-image]')].slice(0,8).map(e => e.outerHTML.slice(0,200))};
            }"""
        )
        epl = [l for l in info["links"] if EPAPER_WORDS.search(l["t"]) or EPAPER_WORDS.search(l["h"])]
        seen, uniq = set(), []
        for l in epl:
            if l["h"] not in seen:
                seen.add(l["h"]); uniq.append(l)
        big = [n for n in net if n["k"] == "img" and n["b"] > 60000]
        out("page", url=url, depth=depth, status=resp.status if resp else None, title=info["title"], final=info["final"],
            hints=info["hints"], html=info["html"], n_imgs=len(info["imgs"]), n_links=len(info["links"]),
            epaper_links=uniq[:12], imgs=info["imgs"][:14], pageish=info["pageish"])
        out("net", url=url, n_img_responses=sum(1 for n in net if n["k"] == "img"), big_imgs=big[:12],
            json_calls=[n for n in net if n["k"] == "json"][:8])
        await ctx.close()
        return uniq
    except Exception as e:  # noqa: BLE001
        out("error", url=url, depth=depth, error=f"{type(e).__name__}: {str(e)[:200]}")
        await ctx.close()
        return []


async def main():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"],
                                          ignore_default_args=["--enable-automation"])
        for url in SITES:
            await plain(url)
            links = await inspect(browser, url)
            home_host = re.sub(r"^www\.", "", url.split("/")[2])
            # newspaper home pages: follow the e-paper link once
            if "epaper." not in url and links:
                target = next((l["h"] for l in links if l["h"].rstrip("/") != url.rstrip("/")), None)
                if target:
                    out("follow", from_=url, to=target)
                    await inspect(browser, target, depth=1)
        await browser.close()


asyncio.run(main())
