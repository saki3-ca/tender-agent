"""Temporary: details needed to finish the newspaper patterns."""
import asyncio, hashlib, json, re
import httpx

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gemini) Chrome/130.0 Safari/537.36".replace("Gemini", "Gecko")


def out(tag, **kw):
    print("DBG " + tag + " " + json.dumps(kw, ensure_ascii=False)[:5000], flush=True)


async def main():
    async with httpx.AsyncClient(timeout=40, follow_redirects=True, headers={"User-Agent": UA}) as c:
        # 1) Amader Shomoy: are pages 13..26 real pages or one placeholder?
        rows = []
        for n in range(8, 27):
            u = f"https://epaper.dainikamadershomoy.com/files/e-paper/2026/10/13/pages/page{n:02d}.jpg"
            r = await c.get(u)
            rows.append((n, r.status_code, len(r.content), hashlib.md5(r.content).hexdigest()[:8], r.headers.get("content-type")))
        out("amadershomoy-pages", rows=rows)
        # 2) Ajker Patrika and Amar Desh: where do the page images appear in the raw HTML?
        for name, url in (("ajkerpatrika", "https://epaper.ajkerpatrika.com/"), ("amardesh", "https://eamardesh.com/")):
            r = await c.get(url)
            t = r.text
            hits = [m.start() for m in re.finditer("compressedepaper", t)]
            out(name + "-html", status=r.status_code, size=len(t), compressedepaper=len(hits), eimages=t.count("eimages"), dailyamardesh=t.count("dailyamardesh"))
            for h in hits[:3]:
                out(name + "-ctx", ctx=t[max(0, h - 200):h + 260])
            for key in ("page_1", "pageList", "pages", "edition_1", "newspaperDate"):
                i = t.find(key)
                if i >= 0:
                    out(name + "-key-" + key, ctx=t[max(0, i - 120):i + 200])
        # 3) Naya Diganta: page image names
        r = await c.get("https://enayadiganta.com/")
        t = r.text
        out("naya-html", status=r.status_code, size=len(t), medium=t.count("medium.jpg"))
        for m in list(re.finditer(r"medium\.jpg", t))[:4]:
            out("naya-ctx", ctx=t[max(0, m.start() - 160):m.start() + 60])
        rows = []
        for p in range(1, 31):
            u = f"https://dev2.enayadiganta.com/images/20261013/1_{p}_medium.jpg"
            h = await c.head(u)
            rows.append((p, h.status_code, h.headers.get("content-length")))
        out("naya-medium", rows=rows)
        rows = []
        for p in (1, 2, 3):
            for pat in ("https://dev2.enayadiganta.com/images/20261013/1_{p}.jpg", "https://dev2.enayadiganta.com/images/20261013/1_{p}_large.jpg",
                        "https://dev2.enayadiganta.com/images/20261013/1_{p}_small.jpg"):
                h = await c.head(pat.format(p=p))
                rows.append((pat.split("/")[-1].format(p=p), h.status_code, h.headers.get("content-length")))
        out("naya-other-sizes", rows=rows)

    # 4) Dhaka Tribune: ask its service from inside Chrome (the plain request is challenged)
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=False, args=["--disable-blink-features=AutomationControlled"], ignore_default_args=["--enable-automation"])
        ctx = await b.new_context(locale="en-US", timezone_id="Asia/Dhaka")
        page = await ctx.new_page()
        await page.goto("https://epaper.dhakatribune.com/", wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(8000)
        base = "https://epaperapi.dhakatribune.com/api/v1/public"
        for path in ("epaper-list?m=10&y=2026", "epaper-list?m=9&y=2026"):
            txt = await page.evaluate("async (u) => { const r = await fetch(u); return r.status + ' ' + (await r.text()); }", f"{base}/{path}")
            try:
                items = json.loads(txt.split(" ", 1)[1])["data"]["items"]
                out("dt-" + path, n=len(items), days=[(i["gmt_date"][5:], i.get("status"), str(i.get("note"))[:18]) for i in items])
            except Exception as e:  # noqa: BLE001
                out("dt-" + path + "-raw", err=str(e), txt=txt[:300])
        for d in ("2026-10-10", "2026-10-11", "2026-10-12"):
            txt = await page.evaluate("async (u) => { const r = await fetch(u); return r.status + ' ' + (await r.text()); }", f"{base}/epaper-data?date={d}")
            out("dt-data-" + d, txt=txt[:1500])
        await b.close()

asyncio.run(main())
