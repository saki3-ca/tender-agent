"""
Supabase Database and Storage Client for ACNABIN Tender Agent.
Interacts with Postgres using service-role permissions and manages Storage buckets.
Includes an in-memory test fallback adapter for offline testing and development.
"""

import os
from datetime import datetime, date, timezone
from typing import Any, Dict, List, Optional
from app.utils.logging import logger
from app.utils.config import config

try:
    from supabase import create_client, Client
except ImportError:
    create_client = None
    Client = None


class InMemoryDatabaseAdapter:
    """Mock in-memory adapter used for unit testing or when cloud credentials are not supplied."""

    def __init__(self):
        self.organizations: Dict[str, Dict[str, Any]] = {}
        self.sources: Dict[str, Dict[str, Any]] = {}
        self.source_checks: List[Dict[str, Any]] = []
        self.documents: Dict[str, Dict[str, Any]] = {}
        self.opportunities: Dict[str, Dict[str, Any]] = {}
        self.opportunity_versions: List[Dict[str, Any]] = []
        self.opportunity_sources: List[Dict[str, Any]] = []
        self.evidence: List[Dict[str, Any]] = []
        self.market_intelligence: Dict[str, Dict[str, Any]] = {}
        self.alerts: Dict[str, Dict[str, Any]] = {}
        self.ai_reviews: List[Dict[str, Any]] = []
        self.ai_usage: Dict[str, Dict[str, Any]] = {}
        self.manual_overrides: List[Dict[str, Any]] = []
        self.notes: List[Dict[str, Any]] = []
        self.runs: Dict[int, Dict[str, Any]] = {}
        self._run_seq = 1

    def upsert_organization(self, data: Dict[str, Any]) -> None:
        self.organizations[data["organization_id"]] = data

    def get_organizations(self) -> List[Dict[str, Any]]:
        return list(self.organizations.values())

    def get_sources(self, enabled_only: bool = True) -> List[Dict[str, Any]]:
        sources = list(self.sources.values())
        if enabled_only:
            return [s for s in sources if s.get("enabled", True)]
        return sources

    def upsert_source(self, data: Dict[str, Any]) -> None:
        self.sources[data["id"]] = data

    def record_source_check(self, data: Dict[str, Any]) -> None:
        self.source_checks.append(data)

    def record_run_start(self, run_type: str = "monitor") -> int:
        run_id = self._run_seq
        self._run_seq += 1
        self.runs[run_id] = {
            "id": run_id,
            "run_type": run_type,
            "start_time": datetime.now(timezone.utc).isoformat(),
            "status": "RUNNING"
        }
        return run_id

    def record_run_end(self, run_id: int, status: str, stats: Dict[str, Any], error_summary: Optional[str] = None) -> None:
        if run_id in self.runs:
            self.runs[run_id].update({
                "end_time": datetime.now(timezone.utc).isoformat(),
                "status": status,
                "error_summary": error_summary,
                **stats
            })

    def get_opportunity(self, opp_id: str) -> Optional[Dict[str, Any]]:
        return self.opportunities.get(opp_id)

    def upsert_opportunity(self, data: Dict[str, Any]) -> None:
        self.opportunities[data["id"]] = data

    def record_opportunity_version(self, data: Dict[str, Any]) -> None:
        self.opportunity_versions.append(data)

    def record_evidence(self, data: Dict[str, Any]) -> None:
        self.evidence.append(data)

    def record_market_intelligence(self, data: Dict[str, Any]) -> None:
        self.market_intelligence[data["id"]] = data

    def record_alert(self, data: Dict[str, Any]) -> None:
        self.alerts[data["dedupe_key"]] = data

    def alert_exists(self, dedupe_key: str) -> bool:
        return dedupe_key in self.alerts

    def record_ai_review(self, data: Dict[str, Any]) -> None:
        self.ai_reviews.append(data)

    def record_ai_usage(self, provider: str, model: str, prompt_tokens: int, completion_tokens: int) -> None:
        today_str = date.today().isoformat()
        key = f"{provider}:{model}:{today_str}"
        if key not in self.ai_usage:
            self.ai_usage[key] = {
                "provider": provider,
                "model": model,
                "usage_date": today_str,
                "call_count": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0
            }
        rec = self.ai_usage[key]
        rec["call_count"] += 1
        rec["prompt_tokens"] += prompt_tokens
        rec["completion_tokens"] += completion_tokens
        rec["total_tokens"] += (prompt_tokens + completion_tokens)

    def get_ai_calls_today(self, provider: str) -> int:
        today_str = date.today().isoformat()
        total = 0
        for key, rec in self.ai_usage.items():
            if rec["provider"] == provider and rec["usage_date"] == today_str:
                total += rec["call_count"]
        return total

    def get_manual_overrides(self, opp_id: str) -> Dict[str, str]:
        overrides = {}
        for row in self.manual_overrides:
            if row.get("opportunity_id") == opp_id:
                overrides[row["field_name"]] = row["new_value"]
        return overrides


class SupabaseDatabase:
    """Production Supabase client wrapping PostgREST with fallback to in-memory adapter."""

    def __init__(self):
        self.url = config.supabase_url
        self.key = config.supabase_service_role_key
        self.client: Optional[Client] = None
        self.mock_adapter = InMemoryDatabaseAdapter()

        if self.url and self.key and create_client:
            try:
                self.client = create_client(self.url, self.key)
                logger.info("Connected to Supabase production instance", extra={"supabase_url": self.url})
            except Exception as e:
                logger.warning("Could not initialize Supabase client; falling back to memory adapter", extra={"error": str(e)})
        else:
            logger.info("Supabase credentials not found. Operating in local in-memory mode.")

    @property
    def is_connected(self) -> bool:
        return self.client is not None

    def upsert_organization(self, data: Dict[str, Any]) -> None:
        self.mock_adapter.upsert_organization(data)
        if self.client:
            try:
                self.client.table("organizations").upsert(data).execute()
            except Exception as e:
                logger.error("Failed to upsert organization into Supabase", extra={"org_id": data.get("organization_id"), "error": str(e)})

    def get_organizations(self) -> List[Dict[str, Any]]:
        if self.client:
            try:
                res = self.client.table("organizations").select("*").execute()
                return res.data or []
            except Exception as e:
                logger.error("Failed to query organizations from Supabase", extra={"error": str(e)})
        return self.mock_adapter.get_organizations()

    def get_sources(self, enabled_only: bool = True) -> List[Dict[str, Any]]:
        if self.client:
            try:
                q = self.client.table("sources").select("*")
                if enabled_only:
                    q = q.eq("enabled", True)
                res = q.execute()
                return res.data or []
            except Exception as e:
                logger.error("Failed to query sources from Supabase", extra={"error": str(e)})
        return self.mock_adapter.get_sources(enabled_only=enabled_only)

    def upsert_source(self, data: Dict[str, Any]) -> None:
        self.mock_adapter.upsert_source(data)
        if self.client:
            try:
                self.client.table("sources").upsert(data).execute()
            except Exception as e:
                logger.error("Failed to upsert source into Supabase", extra={"source_id": data.get("id"), "error": str(e)})

    def record_source_check(self, source_id: str, http_status: Optional[int], duration_ms: int, items_found: int, new_items: int, error: Optional[str] = None) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        payload = {
            "source_id": source_id,
            "check_time": now_iso,
            "http_status": http_status,
            "duration_ms": duration_ms,
            "items_found": items_found,
            "new_items": new_items,
            "error": error
        }
        self.mock_adapter.record_source_check(payload)
        if self.client:
            try:
                self.client.table("source_checks").insert(payload).execute()
                # Also update source health in sources table
                status_enum = "OK" if (http_status and http_status in (200, 304) and not error) else "ERROR"
                self.client.table("sources").update({
                    "last_checked": now_iso,
                    "last_status": status_enum,
                    "error_message": error
                }).eq("id", source_id).execute()
            except Exception as e:
                logger.error("Failed to insert source_check into Supabase", extra={"error": str(e)})

    def record_run_start(self, run_type: str = "monitor") -> int:
        local_id = self.mock_adapter.record_run_start(run_type)
        if self.client:
            try:
                res = self.client.table("runs").insert({
                    "run_type": run_type,
                    "start_time": datetime.now(timezone.utc).isoformat(),
                    "status": "RUNNING"
                }).execute()
                if res.data and len(res.data) > 0:
                    return res.data[0]["id"]
            except Exception as e:
                logger.error("Failed to record run start in Supabase", extra={"error": str(e)})
        return local_id

    def record_run_end(self, run_id: int, status: str, stats: Dict[str, Any], error_summary: Optional[str] = None) -> None:
        self.mock_adapter.record_run_end(run_id, status, stats, error_summary)
        if self.client:
            try:
                self.client.table("runs").update({
                    "end_time": datetime.now(timezone.utc).isoformat(),
                    "status": status,
                    "error_summary": error_summary,
                    **stats
                }).eq("id", run_id).execute()
            except Exception as e:
                logger.error("Failed to record run end in Supabase", extra={"run_id": run_id, "error": str(e)})

    def get_opportunity(self, opp_id: str) -> Optional[Dict[str, Any]]:
        if self.client:
            try:
                res = self.client.table("opportunities").select("*").eq("id", opp_id).execute()
                if res.data and len(res.data) > 0:
                    return res.data[0]
            except Exception as e:
                logger.error("Failed to get opportunity from Supabase", extra={"opp_id": opp_id, "error": str(e)})
        return self.mock_adapter.get_opportunity(opp_id)

    OPPORTUNITY_FIELDS = {
        "id", "organization_id", "organization_name", "organization_type", "title",
        "reference_number", "tender_type", "category", "pipeline", "outside_ifrs9_target",
        "priority", "score", "fit_type", "publication_date", "publication_date_raw",
        "submission_deadline", "deadline_raw", "days_remaining", "opening_datetime",
        "prebid_meeting", "clarification_deadline", "scope_of_work", "eligibility",
        "eligibility_concerns", "minimum_experience", "required_certifications",
        "required_team", "required_documents", "bid_security", "tender_fee",
        "contract_period", "estimated_value", "submission_method", "submission_address",
        "contact_person", "contact_email", "contact_phone", "source_url", "document_url",
        "source_tier", "source_verification", "record_type", "lifecycle_status",
        "review_status", "is_baseline", "ai_confidence", "extraction_result",
        "review_result", "score_breakdown", "embedding", "content_hash", "document_hash",
        "first_seen", "last_checked", "updated_at"
    }

    def upsert_opportunity(self, data: Dict[str, Any]) -> None:
        # Check manual overrides first: do not overwrite human-locked fields
        overrides = self.get_manual_overrides(data["id"])
        if overrides:
            for field, val in overrides.items():
                data[field] = val

        self.mock_adapter.upsert_opportunity(data)
        if self.client:
            try:
                # Sanitize to valid schema columns
                cleaned_payload = {k: v for k, v in data.items() if k in self.OPPORTUNITY_FIELDS}
                self.client.table("opportunities").upsert(cleaned_payload).execute()
            except Exception as e:
                logger.error("Failed to upsert opportunity into Supabase", extra={"opp_id": data.get("id"), "error": str(e)})

    def record_opportunity_version(self, data: Dict[str, Any]) -> None:
        self.mock_adapter.record_opportunity_version(data)
        if self.client:
            try:
                self.client.table("opportunity_versions").insert(data).execute()
            except Exception as e:
                logger.error("Failed to record opportunity version in Supabase", extra={"error": str(e)})

    def record_evidence(self, evidence_items: List[Dict[str, Any]]) -> None:
        for ev in evidence_items:
            self.mock_adapter.record_evidence(ev)
        if self.client and evidence_items:
            try:
                self.client.table("evidence").insert(evidence_items).execute()
            except Exception as e:
                logger.error("Failed to insert evidence into Supabase", extra={"error": str(e)})

    def record_market_intelligence(self, data: Dict[str, Any]) -> None:
        self.mock_adapter.record_market_intelligence(data)
        if self.client:
            try:
                self.client.table("market_intelligence").upsert(data).execute()
            except Exception as e:
                logger.error("Failed to upsert market intelligence into Supabase", extra={"intel_id": data.get("id"), "error": str(e)})

    def alert_exists(self, dedupe_key: str) -> bool:
        if self.client:
            try:
                res = self.client.table("alerts").select("id").eq("dedupe_key", dedupe_key).execute()
                return bool(res.data and len(res.data) > 0)
            except Exception as e:
                logger.error("Failed to check alert dedupe in Supabase", extra={"dedupe_key": dedupe_key, "error": str(e)})
        return self.mock_adapter.alert_exists(dedupe_key)

    def record_alert(self, data: Dict[str, Any]) -> None:
        self.mock_adapter.record_alert(data)
        if self.client:
            try:
                self.client.table("alerts").insert(data).execute()
            except Exception as e:
                logger.error("Failed to record alert in Supabase", extra={"dedupe_key": data.get("dedupe_key"), "error": str(e)})

    def record_ai_usage(self, provider: str, model: str, prompt_tokens: int, completion_tokens: int) -> None:
        self.mock_adapter.record_ai_usage(provider, model, prompt_tokens, completion_tokens)
        if self.client:
            try:
                today_str = date.today().isoformat()
                # PostgREST rpc or upsert call count
                self.client.rpc("increment_ai_usage", {
                    "p_provider": provider,
                    "p_model": model,
                    "p_date": today_str,
                    "p_prompt_tokens": prompt_tokens,
                    "p_completion_tokens": completion_tokens
                }).execute()
            except Exception:
                # If RPC not present, fallback to local tracking
                pass

    def get_ai_calls_today(self, provider: str) -> int:
        if self.client:
            try:
                today_str = date.today().isoformat()
                res = self.client.table("ai_usage").select("call_count").eq("provider", provider).eq("usage_date", today_str).execute()
                if res.data:
                    return sum(row.get("call_count", 0) for row in res.data)
            except Exception:
                pass
        return self.mock_adapter.get_ai_calls_today(provider)

    def get_manual_overrides(self, opp_id: str) -> Dict[str, str]:
        if self.client:
            try:
                res = self.client.table("manual_overrides").select("field_name, new_value").eq("opportunity_id", opp_id).execute()
                if res.data:
                    return {r["field_name"]: r["new_value"] for r in res.data}
            except Exception:
                pass
        return self.mock_adapter.get_manual_overrides(opp_id)


# Global Database Singleton
db = SupabaseDatabase()
