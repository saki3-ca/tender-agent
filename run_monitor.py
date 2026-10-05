"""
ACNABIN Tender Monitor — one monitoring run.

    python run_monitor.py                      # all enabled sources
    python run_monitor.py --source src_07_sonali_tender --source src_ngo_04_actionaid_bangladesh
    python run_monitor.py --sector NGO

Writes to Supabase when SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are set; otherwise
writes data/local_run.json. Prints a summary including every source that failed.
"""

import argparse
import asyncio
import sys

from app.utils.config import ConfigError, config
from app.utils.logging import logger


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one ACNABIN tender monitoring cycle")
    parser.add_argument("--source", action="append", help="Only crawl this source id (repeatable)")
    parser.add_argument("--sector", choices=["BANK", "NGO"], help="Only crawl sources of this sector")
    parser.add_argument("--local", action="store_true", help="Do not write to Supabase; write data/local_run.json")
    args = parser.parse_args()

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
    stats = asyncio.run(monitor.run(args.source, sector=args.sector))

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
