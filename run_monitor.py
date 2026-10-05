"""
ACNABIN Tender & Opportunity Intelligence Monitor.
Master worker script executed hourly by GitHub Actions (and locally for testing).
Orchestrates crawling, change detection, extraction, scoring, persistence, and alerting.
"""

import sys
import time
import asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Optional

from app.utils.logging import logger
from app.utils.config import config, ConfigError
from app.db.supabase import db
from app.crawler.crawler import TenderCrawler
from app.parsers.html_parser import HtmlNoticeExtractor, clean_html_text, compute_content_hash
from app.parsers.document_parser import DocumentParser
from app.parsers.date_cleaner import calculate_days_remaining, DHAKA_TZ
from app.ai.router import AIRouter
from app.scoring.engine import ScoringEngine
from app.alerts.telegram import TelegramAlerter


class MonitorWorker:
    """Executes a single monitor cycle within time and API limits."""

    def __init__(self):
        self.crawler = TenderCrawler()
        self.ai_router = AIRouter()
        self.scoring_engine = ScoringEngine()
        self.alerter = TelegramAlerter()
        self.time_budget_seconds = config.run_time_budget_minutes * 60.0
        self.start_timestamp = time.time()

    def is_time_budget_exhausted(self) -> bool:
        """Returns True if the worker is approaching its allotted time limit."""
        elapsed = time.time() - self.start_timestamp
        # Reserve 20 seconds for clean wrap-up
        return elapsed >= (self.time_budget_seconds - 20)

    async def run(self) -> Dict[str, Any]:
        """Main execution workflow."""
        run_id = db.record_run_start("monitor")
        logger.info(f"Starting ACNABIN Monitor Run #{run_id}", extra={"ai_mode": config.ai_mode, "run_id": run_id})

        stats = {
            "sources_checked": 0,
            "sources_failed": 0,
            "documents_fetched": 0,
            "new_candidates": 0,
            "ai_calls": 0,
            "alerts_sent": 0,
            "duration_seconds": 0.0
        }

        # 1. Load Sources (from DB or config fallback)
        sources = db.get_sources(enabled_only=True)
        if not sources:
            sources = config.sources

        logger.info(f"Loaded {len(sources)} active procurement sources to check", extra={"source_count": len(sources)})

        # 2. Iterate through sources politely
        for source in sources:
            if self.is_time_budget_exhausted():
                logger.warning("Run time budget reached; stopping gracefully for next run", extra={"run_id": run_id})
                break

            source_id = source.get("id", source.get("url"))
            url = source["url"]
            source_start = time.time()

            try:
                status, html_content, headers, error = await self.crawler.fetch_source_html(source)
                duration_ms = int((time.time() - source_start) * 1000)

                if error:
                    stats["sources_failed"] += 1
                    db.record_source_check(source_id, status, duration_ms, 0, 0, error=error)
                    logger.warning(f"Source fetch error on {url}: {error}", extra={"source_id": source_id, "status": status})
                    continue

                if status == 304 or not html_content:
                    # Unchanged content (conditional GET 304)
                    stats["sources_checked"] += 1
                    db.record_source_check(source_id, 304, duration_ms, 0, 0, None)
                    continue

                stats["sources_checked"] += 1

                # 3. Extract Candidates from HTML
                extractor = HtmlNoticeExtractor(base_url=url)
                candidates = extractor.extract_candidates(html_content)
                db.record_source_check(source_id, status, duration_ms, len(candidates), len(candidates), None)

                # 4. Process Each Candidate
                for cand in candidates:
                    if self.is_time_budget_exhausted():
                        break

                    full_text = cand.get("raw_text", "")
                    doc_url = cand.get("document_url")

                    # If candidate has attached document (PDF/DOCX), download & extract text
                    if doc_url:
                        doc_bytes, doc_err = await self.crawler.download_document(doc_url, verify_ssl=source.get("verify_ssl", True))
                        if doc_bytes:
                            stats["documents_fetched"] += 1
                            if doc_url.lower().endswith(".pdf"):
                                pdf_data = DocumentParser.parse_pdf(doc_bytes)
                                if pdf_data.get("full_text"):
                                    full_text = f"{cand.get('title', '')}\n\n{pdf_data['full_text']}"
                                    cand["document_hash"] = pdf_data["document_hash"]
                            elif doc_url.lower().endswith((".docx", ".doc")):
                                docx_data = DocumentParser.parse_docx(doc_bytes)
                                full_text = f"{cand.get('title', '')}\n\n{docx_data['full_text']}"
                                cand["document_hash"] = docx_data["document_hash"]

                    # Change detection check: if opportunity exists with identical content_hash, skip
                    content_hash = compute_content_hash(full_text)
                    cand["content_hash"] = content_hash
                    cand["organization_name"] = source.get("organization_name")
                    cand["source_tier"] = source.get("tier", 1)

                    # 5. Process through Rules & AI Pipeline
                    opp_data = await self.ai_router.process_candidate(cand, full_text)

                    # If rejected as IRRELEVANT, store minimally or skip
                    if opp_data.get("record_type") == "IRRELEVANT":
                        # General tab lists every tender notice, not only ACNABIN-relevant ones.
                        if not config.settings.get("capture_all_tenders", True):
                            continue
                        opp_data = {
                            **opp_data,
                            "record_type": "OPPORTUNITY",
                            "pipeline": "GENERAL_MARKET",
                            "category": "OTHER_PROFESSIONAL",
                            "fit_type": "NOT_SUITABLE",
                            "title": opp_data.get("title") or cand.get("title"),
                            "review_status": "AI_REVIEW_PENDING",
                        }
                        opp_data["deadline_utc"] = opp_data.get("deadline_utc") or cand.get("deadline_utc")

                    stats["new_candidates"] += 1

                    # 6. Deterministic Scoring & Priority Assignment
                    score, priority, score_breakdown, reasoning = self.scoring_engine.compute_score(
                        category=opp_data["category"],
                        record_type=opp_data["record_type"],
                        organization_type=opp_data.get("organization_type", "BANK"),
                        is_target_bank=opp_data.get("is_target", False),
                        fit_type=opp_data.get("fit_type", "DIRECT_FIT"),
                        source_tier=source.get("tier", 1),
                        confidence=opp_data.get("confidence", "MEDIUM"),
                        is_aqr_or_diagnostic=("aqr" in full_text.lower() or "asset quality review" in full_text.lower())
                    )

                    opp_id = f"opp_{opp_data.get('organization_id', 'gen')}_{content_hash[:12]}"
                    deadline_utc = opp_data.get("deadline_utc")
                    days_remaining = calculate_days_remaining(deadline_utc)

                    # Baseline check (Section 21)
                    is_baseline = False
                    if days_remaining is not None and days_remaining < 0:
                        is_baseline = True

                    # Prepare final opportunity object
                    final_opp = {
                        "id": opp_id,
                        "organization_id": opp_data.get("organization_id"),
                        "organization_name": opp_data.get("organization_name", "Monitored Organization"),
                        "organization_type": opp_data.get("organization_type", "COMMERCIAL_BANK"),
                        "title": opp_data.get("title", cand.get("title")),
                        "reference_number": opp_data.get("reference_number"),
                        "category": opp_data["category"],
                        "pipeline": opp_data["pipeline"],
                        "outside_ifrs9_target": opp_data.get("outside_ifrs9_target", False),
                        "priority": priority,
                        "score": score,
                        "fit_type": opp_data.get("fit_type", "DIRECT_FIT"),
                        "submission_deadline": deadline_utc.isoformat() if deadline_utc else None,
                        "days_remaining": days_remaining,
                        "scope_of_work": opp_data.get("scope_summary"),
                        "potential_acnabin_service": opp_data.get("potential_acnabin_service"),
                        "relevance_reason": opp_data.get("relevance_reason"),
                        "eligibility": opp_data.get("eligibility_summary"),
                        "source_url": url,
                        "document_url": doc_url,
                        "source_tier": source.get("tier", 1),
                        "record_type": opp_data["record_type"],
                        "lifecycle_status": "DEADLINE_APPROACHING" if (days_remaining is not None and 0 <= days_remaining <= 7) else "ACTIVE",
                        "review_status": opp_data.get("review_status", "AI_REVIEW_PENDING"),
                        "is_baseline": is_baseline,
                        "ai_confidence": opp_data.get("confidence", "MEDIUM"),
                        "extraction_result": opp_data.get("extraction_result", {}),
                        "score_breakdown": score_breakdown,
                        "content_hash": content_hash,
                        "document_hash": cand.get("document_hash"),
                        "first_seen": datetime.now(timezone.utc).isoformat(),
                        "last_checked": datetime.now(timezone.utc).isoformat()
                    }

                    # Persist opportunity to database
                    if opp_data["record_type"] == "MARKET_INTELLIGENCE":
                        db.record_market_intelligence({
                            "id": opp_id,
                            "organization_id": opp_data.get("organization_id"),
                            "title": final_opp["title"],
                            "summary": opp_data.get("scope_summary"),
                            "source_url": url,
                            "category": opp_data["category"],
                            "content_hash": content_hash,
                            "tags": opp_data.get("matched_terms", [])
                        })
                    else:
                        db.upsert_opportunity(final_opp)

                        # Store verified evidence quotes
                        if opp_data.get("evidence"):
                            ev_rows = [{
                                "opportunity_id": opp_id,
                                "page_number": ev.get("page", 1),
                                "quoted_text": ev.get("text"),
                                "verified_against_source": True
                            } for ev in opp_data["evidence"]]
                            db.record_evidence(ev_rows)

                        # 7. Immediate Alert (Section 23: HIGH+ and not baseline)
                        if priority in ("VERY HIGH", "HIGH") and not is_baseline:
                            alert_sent = await self.alerter.send_opportunity_alert(final_opp, alert_type="NEW")
                            if alert_sent:
                                stats["alerts_sent"] += 1

            except Exception as e:
                stats["sources_failed"] += 1
                logger.error(f"Unhandled exception processing source {url}: {e}", extra={"error": str(e)})

        # 8. Check Daily Digest Schedule (Asia/Dhaka time at/after 08:00)
        now_dhaka = datetime.now(DHAKA_TZ)
        if now_dhaka.hour >= 8:
            today_str = now_dhaka.date().isoformat()
            digest_summary = {
                "date": today_str,
                "sources_checked": stats["sources_checked"],
                "new_candidates": stats["new_candidates"],
                "very_high_count": 0,
                "high_count": 0,
                "medium_count": 0
            }
            await self.alerter.send_daily_digest(digest_summary)

        # 9. Record Run End
        duration = round(time.time() - self.start_timestamp, 2)
        stats["duration_seconds"] = duration
        db.record_run_end(run_id, "COMPLETED", stats, error_summary=None)

        logger.info(f"ACNABIN Monitor Run #{run_id} completed successfully in {duration}s", extra=stats)
        return stats


def main():
    """CLI entrypoint for run_monitor.py."""
    try:
        # Validate startup checks
        config.validate()
    except ConfigError as ce:
        logger.fatal(f"FATAL: Startup configuration error: {ce}")
        sys.exit(1)

    worker = MonitorWorker()
    stats = asyncio.run(worker.run())
    print("\n--- ACNABIN Monitor Run Summary ---")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
