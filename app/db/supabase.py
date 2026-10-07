"""
Storage for the tender monitor.

With SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY set, data is written to Supabase
(tables: tenders, source_status, runs, alerts). Without credentials the monitor still
runs and writes its results to data/local_run.json for review.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from app.utils.config import BASE_DIR, config
from app.utils.logging import logger

try:
    from supabase import create_client
except ImportError:  # pragma: no cover
    create_client = None

TENDER_COLUMNS = {
    "id", "sector", "organization_id", "organization_name", "organization_type", "is_target_bank",
    "title", "description", "reference_number", "published_date", "deadline", "deadline_has_time",
    "status", "is_priority", "is_ifrs9", "categories", "matched_keywords", "source_id", "source_url",
    "notice_url", "document_url", "document_text", "document_checked", "is_baseline", "first_seen", "last_seen",
    "members_only", "is_it", "it_priority", "it_categories", "it_partners",
}
# Set once when a tender is first discovered, never overwritten afterwards
INSERT_ONLY_COLUMNS = {"first_seen"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _chunks(items: List[Any], size: int) -> Iterable[List[Any]]:
    for i in range(0, len(items), size):
        yield items[i:i + size]


class Store:
    def __init__(self):
        self.client = None
        if config.supabase_url and config.supabase_service_role_key and create_client:
            try:
                self.client = create_client(config.supabase_url, config.supabase_service_role_key)
            except Exception as e:
                logger.warning(f"Could not connect to Supabase; using local file output: {e}")
        # Local fallback state
        self._local: Dict[str, Any] = {"tenders": {}, "source_status": {}, "runs": []}

    @property
    def is_connected(self) -> bool:
        return self.client is not None

    # ------------------------------------------------------------------ tenders
    def known_tenders(self, ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """Existing rows for these ids (to keep first_seen and reuse document results)."""
        if not ids:
            return {}
        if not self.client:
            return {i: self._local["tenders"][i] for i in ids if i in self._local["tenders"]}
        found: Dict[str, Dict[str, Any]] = {}
        for chunk in _chunks(sorted(set(ids)), 150):
            res = self.client.table("tenders").select(
                "id,title,description,published_date,deadline,deadline_has_time,reference_number,"
                "document_text,document_checked,first_seen,is_baseline"
            ).in_("id", chunk).execute()
            for row in res.data or []:
                found[row["id"]] = row
        return found

    def open_tenders_for_orgs(self, org_ids: Iterable[str]) -> List[Dict[str, Any]]:
        """Stored tenders of these organizations whose deadline has not long passed (for duplicate checks)."""
        if not self.client:
            return []
        since = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        rows: List[Dict[str, Any]] = []
        for chunk in _chunks(sorted(set(org_ids)), 100):
            res = self.client.table("tenders").select("id,organization_id,title,deadline,source_id")                 .in_("organization_id", chunk).gte("deadline", since).execute()
            rows += res.data or []
        return rows

    def delete_tenders(self, ids: Iterable[str]) -> None:
        if not self.client:
            for i in ids:
                self._local["tenders"].pop(i, None)
            return
        for chunk in _chunks(sorted(set(ids)), 100):
            self.client.table("tenders").delete().in_("id", chunk).execute()

    def save_tenders(self, tenders: List[Dict[str, Any]], known_ids: Iterable[str]) -> None:
        known = set(known_ids)
        rows = [{k: v for k, v in t.items() if k in TENDER_COLUMNS} for t in tenders]
        new_rows = [r for r in rows if r["id"] not in known]
        existing_rows = [{k: v for k, v in r.items() if k not in INSERT_ONLY_COLUMNS} for r in rows if r["id"] in known]
        if not self.client:
            for r in new_rows:
                self._local["tenders"][r["id"]] = r
            for r in existing_rows:
                self._local["tenders"][r["id"]].update(r)
            return
        for batch in (new_rows, existing_rows):
            for chunk in _chunks(batch, 200):
                self.client.table("tenders").upsert(chunk).execute()

    # ----------------------------------------------------------- admin sources
    def admin_sources(self) -> List[Dict[str, Any]]:
        """Sources added or corrected on the dashboard's Admin page."""
        if not self.client:
            return []
        try:
            return self.client.table("admin_sources").select("*").execute().data or []
        except Exception as e:
            logger.warning(f"Could not read admin_sources (run the latest migration?): {e}")
            return []

    # ----------------------------------------------------------- source status
    def source_states(self) -> Dict[str, Dict[str, Any]]:
        if not self.client:
            return dict(self._local["source_status"])
        try:
            res = self.client.table("source_status").select("*").execute()
            return {r["source_id"]: r for r in res.data or []}
        except Exception as e:
            logger.warning(f"Could not read source_status: {e}")
            return {}

    def save_source_states(self, rows: List[Dict[str, Any]]) -> None:
        if not self.client:
            for r in rows:
                self._local["source_status"][r["source_id"]] = r
            return
        for chunk in _chunks(rows, 200):
            self.client.table("source_status").upsert(chunk).execute()

    # -------------------------------------------------------------------- runs
    def run_started(self) -> Optional[int]:
        if not self.client:
            return None
        try:
            res = self.client.table("runs").insert(
                {"run_type": "monitor", "start_time": _now(), "status": "RUNNING"}).execute()
            return res.data[0]["id"] if res.data else None
        except Exception as e:
            logger.warning(f"Could not record run start: {e}")
            return None

    def run_finished(self, run_id: Optional[int], status: str, stats: Dict[str, Any],
                     error_summary: Optional[str] = None) -> None:
        payload = {
            "end_time": _now(),
            "status": status,
            "duration_seconds": stats.get("duration_seconds"),
            "sources_checked": stats.get("sources_ok", 0),
            "sources_failed": stats.get("sources_failed", 0),
            "documents_fetched": stats.get("documents_read", 0),
            "new_candidates": stats.get("new_tenders", 0),
            "alerts_sent": stats.get("alerts_sent", 0),
            "error_summary": error_summary,
        }
        if not self.client or run_id is None:
            self._local["runs"].append(payload)
            return
        try:
            self.client.table("runs").update(payload).eq("id", run_id).execute()
        except Exception as e:
            logger.warning(f"Could not record run end: {e}")

    # ------------------------------------------------------------------ alerts
    def alert_sent(self, dedupe_key: str) -> bool:
        if not self.client:
            return False
        try:
            res = self.client.table("alerts").select("id").eq("dedupe_key", dedupe_key).limit(1).execute()
            return bool(res.data)
        except Exception:
            return False

    def record_alert(self, dedupe_key: str, payload: Dict[str, Any], status: str, channel: str = "telegram") -> None:
        if not self.client:
            return
        try:
            self.client.table("alerts").insert({
                "alert_type": "NEW_PRIORITY", "channel": channel, "dedupe_key": dedupe_key,
                "payload": payload, "status": status,
            }).execute()
        except Exception as e:
            logger.warning(f"Could not record alert: {e}")

    # ------------------------------------------------------------------- local
    def write_local_snapshot(self, path: Optional[Path] = None) -> Path:
        path = path or (BASE_DIR / "data" / "local_run.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self._local, f, ensure_ascii=False, indent=2, default=str)
        return path
