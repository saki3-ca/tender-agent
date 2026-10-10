"""
ACNABIN Tender Monitor — one monitoring run.

    python run_monitor.py                      # all enabled sources
    python run_monitor.py --source src_07_sonali_tender --source src_ngo_04_actionaid_bangladesh
    python run_monitor.py --sector NGO
    python run_monitor.py --no-epaper              # hourly run
    python run_monitor.py --epaper                 # daily newspaper run
    python run_monitor.py --pc-browser             # only the Cloudflare-protected papers (Jugantor, Pratidin)

Writes to Supabase when SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are set; otherwise
writes data/local_run.json. Prints a summary including every source that failed.
"""

import argparse
import asyncio
import os
import sys

from app.utils.config import ConfigError, config
from app.utils.logging import logger


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one ACNABIN tender monitoring cycle")
    parser.add_argument("--source", action="append", help="Only crawl this source id (repeatable)")
    parser.add_argument("--sector", choices=["BANK", "NGO", "IT"], help="Only crawl sources of this sector")
    parser.add_argument("--local", action="store_true", help="Do not write to Supabase; write data/local_run.json")
    kind = parser.add_mutually_exclusive_group()
    kind.add_argument("--epaper", dest="epaper", action="store_const", const=True,
                      help="Only newspaper e-paper sources (slow: every page is read by Gemini)")
    kind.add_argument("--no-epaper", dest="epaper", action="store_const", const=False,
                      help="Skip newspaper e-paper sources")
    parser.add_argument("--pc-browser", action="store_true",
                        help="Only sources marked pc_browser, read in Chrome (the --epaper run in GitHub Actions does this too)")
    args = parser.parse_args()
    if args.pc_browser:
        from app.crawler import pc_browser
        os.environ[pc_browser.ENV_FLAG] = "1"
        args.source = [s["id"] for s in config.sources if s.get("pc_browser") and s.get("enabled", True)]

    try:
        config.validate()
    except ConfigError as e:
        logger.critical(f"Configuration error: {e}")
        return 1

    from app.db.supabase import Store
    from app.pipeline import Monitor

    store = Store()
    if args.local:
        store.client = None
    monitor = Monitor(store)
    stats = asyncio.run(monitor.run(args.source, sector=args.sector, epaper=args.epaper))

    print("\n=== ACNABIN Tender Monitor — run summary ===")
    for key, value in stats.items():
        print(f"  {key:18} {value}")
    failed = [s for s in monitor.source_results if not s["ok"]]
    if failed:
        print(f"\nSources with errors ({len(failed)}):")
        for s in sorted(failed, key=lambda r: r["source_id"]):
            print(f"  {s['source_id']:45} {s['error']}  {s['url']}")
    if not store.is_connected:
        print(f"\nLocal results written to {store.write_local_snapshot()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
