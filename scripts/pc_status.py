"""
Is the office PC running?  python scripts/pc_status.py

Shows when the office PC task last ran (it records every run in the runs table as run_type 'office_pc'),
how long ago that was, and the result of its latest runs. Works from any PC that has the .env file.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.supabase import Store  # noqa: E402

TZ = ZoneInfo("Asia/Dhaka")


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def main() -> int:
    store = Store()
    if not store.client:
        print("No database connection (.env with SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY needed).")
        return 1
    rows = (store.client.table("runs").select("start_time,status,sources_checked,sources_failed,error_summary")
            .eq("run_type", "office_pc").order("start_time", desc=True).limit(6).execute().data)
    if not rows:
        print("The office PC has never run (task not installed yet).")
        return 1
    last = _dt(rows[0]["start_time"])
    minutes = int((datetime.now(timezone.utc) - last).total_seconds() // 60)
    ok = minutes <= 30
    print(f"Office PC: {'RUNNING NORMALLY' if ok else 'NOT RUNNING - check that the PC is on, awake and online'}")
    print(f"Last run started {last.astimezone(TZ):%d %b %Y %H:%M} Dhaka time ({minutes} min ago)\n")
    print("Latest runs:")
    for r in rows:
        line = f"  {_dt(r['start_time']).astimezone(TZ):%d %b %H:%M}  {r['status']:<10} ok={r['sources_checked']} failed={r['sources_failed']}"
        if r.get("error_summary"):
            line += f"  {r['error_summary'][:120]}"
        print(line)
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
