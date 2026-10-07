"""
Source health check and repair helper.

For every source in config/sources.json:
  1. fetch the configured URL and report OK / HTTP error / SOFT_404 / BLOCKED / SSL / DNS failure,
     plus how many tender listings the extractor finds on it;
  2. for broken or empty sources, look for tender/procurement pages linked from the
     organization's official homepage and test those candidates the same way.

Nothing is changed automatically: candidates are printed (and saved to data/source_check.json)
so a person can review them before updating config/sources.json. URLs are only ever taken
from links on the organization's own website, never constructed by guesswork.

    python scripts/check_sources.py                 # all sources
    python scripts/check_sources.py --sector BANK
    python scripts/check_sources.py --source src_07_sonali_tender
"""

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bs4 import BeautifulSoup  # noqa: E402

from app.crawler.crawler import TenderCrawler  # noqa: E402
from app.parsers.date_cleaner import today_dhaka  # noqa: E402
from app.parsers.html_parser import HtmlNoticeExtractor  # noqa: E402
from app.utils.config import config  # noqa: E402

LINK_HINT = re.compile(r"tender|procure|rfp|rfq|eoi|quotation|bid|notice|purchase|consultan|দরপত্র|বিজ্ঞপ্তি|ক্রয়", re.I)


def official_domain(org_id: str) -> str:
    for b in config.ifrs9_banks:
        if b["id"] == org_id:
            return b.get("official_domain", "")
    for o in config.organizations:
        if o["organization_id"] == org_id:
            return o.get("official_domain", "")
    return ""


async def probe(crawler: TenderCrawler, url: str, verify_ssl: bool = True) -> dict:
    page = await crawler.fetch_page({"url": url, "verify_ssl": verify_ssl})
    if not page.ok and page.error == "SSL_ERROR" and verify_ssl:
        retry = await probe(crawler, url, verify_ssl=False)
        retry["needs_verify_ssl_false"] = retry["ok"]
        return retry
    info = {"url": url, "final_url": page.final_url, "ok": page.ok, "error": page.error, "status": page.status,
            "listings": 0, "dated_recent": 0}
    if page.ok:
        today = today_dhaka()
        listings = HtmlNoticeExtractor(page.final_url or url, today=today).extract(page.text)
        info["listings"] = len(listings)
        info["dated_recent"] = sum(
            1 for l in listings
            if (l.published and (today - l.published).days <= 365) or (l.deadline and (today - l.deadline.date()).days <= 365))
        info["_html"] = page.text
    return info


async def discover(crawler: TenderCrawler, domain: str) -> list:
    """Tender-like links on the official homepage (and their quality)."""
    if not domain:
        return []
    home = None
    for scheme_host in (f"https://www.{domain}", f"https://{domain}", f"http://www.{domain}"):
        home = await probe(crawler, scheme_host + "/")
        if home["ok"]:
            break
    if not home or not home["ok"]:
        return [{"url": f"https://{domain}/", "ok": False, "error": home["error"] if home else "NO_HOMEPAGE"}]
    soup = BeautifulSoup(home["_html"], "lxml")
    base = home["final_url"] or home["url"]
    host = urlparse(base).netloc.replace("www.", "")
    seen, candidates = set(), []
    for a in soup.find_all("a", href=True):
        text = " ".join(a.get_text(" ").split())
        url = urljoin(base, a["href"]).split("#")[0]
        if not url.startswith("http") or url in seen:
            continue
        link_host = urlparse(url).netloc.replace("www.", "")
        # stay on the organization's own site (sub-domains such as tender.<org> are allowed)
        if not (link_host == host or link_host.endswith("." + host)):
            continue
        if url.lower().endswith((".pdf", ".jpg", ".png", ".doc", ".docx")):
            continue
        if LINK_HINT.search(text) or LINK_HINT.search(urlparse(url).path):
            seen.add(url)
            candidates.append((text[:60], url))
    results = []
    for text, url in candidates[:8]:
        r = await probe(crawler, url)
        r.pop("_html", None)
        r["link_text"] = text
        results.append(r)
    results.sort(key=lambda r: (r.get("dated_recent", 0), r.get("listings", 0)), reverse=True)
    return results


async def main(args) -> None:
    sources = config.sources
    if args.source:
        sources = [s for s in sources if s["id"] in args.source]
    if args.sector:
        sources = [s for s in sources if config.organization(s["organization_id"])["sector"] == args.sector]
    crawler = TenderCrawler()
    sem = asyncio.Semaphore(8)
    report = []

    async def check(src):
        async with sem:
            r = await probe(crawler, src["url"], verify_ssl=src.get("verify_ssl", True))
            r.pop("_html", None)
            entry = {"source_id": src["id"], "organization": config.organization(src["organization_id"])["name"],
                     "current": r, "candidates": []}
            if args.discover and (not r["ok"] or r["listings"] == 0):
                entry["candidates"] = await discover(crawler, official_domain(src["organization_id"]))
            report.append(entry)

    await asyncio.gather(*(check(s) for s in sources))
    await crawler.close()
    report.sort(key=lambda e: e["source_id"])

    ok = sum(1 for e in report if e["current"]["ok"] and e["current"]["listings"])
    print(f"\n{ok}/{len(report)} sources reachable with tender listings\n")
    for e in report:
        c = e["current"]
        state = "OK " if c["ok"] and c["listings"] else ("EMPTY" if c["ok"] else c["error"])
        print(f"{e['source_id']:48} {state:22} listings={c['listings']:<4} recent={c['dated_recent']:<4} {c['url']}")
        for cand in e["candidates"][:4]:
            if cand.get("ok") and cand.get("listings"):
                print(f"{'':52}candidate listings={cand['listings']:<4} recent={cand['dated_recent']:<4} "
                      f"{cand['url']}  [{cand.get('link_text', '')}]")
    out = ROOT / "data" / "source_check.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\nFull report: {out}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--source", action="append")
    p.add_argument("--sector", choices=["BANK", "NGO", "IT"])
    p.add_argument("--no-discover", dest="discover", action="store_false",
                   help="Only check configured URLs; do not look for replacement pages")
    asyncio.run(main(p.parse_args()))
