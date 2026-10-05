"""
Telegram alerting module for ACNABIN Tender Agent.
Formats opportunity alerts and daily digests, checks deduplication keys,
and dispatches messages via the Telegram Bot API.
"""

from typing import Any, Dict, Optional
import httpx
from app.utils.logging import logger
from app.utils.config import config
from app.db.supabase import db


class TelegramAlerter:
    """Sends formatted opportunity and digest alerts to Telegram."""

    def __init__(self):
        self.bot_token = config.telegram_bot_token
        self.chat_id = config.telegram_chat_id
        self.dashboard_url = config.settings.get("dashboard_base_url", "https://tender-agent-d01.pages.dev")

    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    async def send_opportunity_alert(self, opp: Dict[str, Any], alert_type: str = "NEW") -> bool:
        """
        Sends an immediate opportunity alert to Telegram.
        Enforces deduplication key check.
        """
        opp_id = opp["id"]
        deadline_str = str(opp.get("submission_deadline") or "no_deadline")
        dedupe_key = f"{opp_id}_{alert_type}_{deadline_str}"

        # Deduplication check
        if db.alert_exists(dedupe_key):
            logger.debug(f"Alert already sent for dedupe_key: {dedupe_key}; skipping.")
            return False

        message = self.format_opportunity_message(opp, alert_type)

        if not self.is_configured():
            logger.info(f"Telegram not configured; recording simulated alert: {dedupe_key}")
            db.record_alert({
                "opportunity_id": opp_id,
                "alert_type": alert_type,
                "channel": "telegram",
                "recipient": "simulated_console",
                "dedupe_key": dedupe_key,
                "payload": {"text": message},
                "status": "SIMULATED_SUCCESS"
            })
            return True

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "Markdown",
            "disable_web_page_preview": False
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()

                db.record_alert({
                    "opportunity_id": opp_id,
                    "alert_type": alert_type,
                    "channel": "telegram",
                    "recipient": str(self.chat_id),
                    "dedupe_key": dedupe_key,
                    "payload": {"text": message},
                    "status": "SENT"
                })
                logger.info("Telegram alert sent successfully", extra={"opp_id": opp_id, "dedupe_key": dedupe_key})
                return True
        except Exception as e:
            logger.error(f"Failed to send Telegram alert: {e}", extra={"error": str(e)})
            return False

    def format_opportunity_message(self, opp: Dict[str, Any], alert_type: str = "NEW") -> str:
        """Formats the alert text exactly per Section 23 specification."""
        priority = opp.get("priority", "HIGH")
        header_title = f"{alert_type} ACNABIN OPPORTUNITY  [{priority}]"
        
        pipeline_label = "IFRS 9 TARGET" if opp.get("pipeline") == "IFRS9_TARGET" else "GENERAL MARKET"
        if opp.get("outside_ifrs9_target"):
            pipeline_label += " (outside IFRS 9 target)"

        days_left = opp.get("days_remaining")
        deadline_text = f"{opp.get('submission_deadline', 'Not specified')} ({days_left} days left)" if days_left is not None else str(opp.get("submission_deadline", "Not specified"))

        evidence_items = opp.get("evidence", [])
        evidence_text = "No direct quote extracted"
        if evidence_items:
            ev = evidence_items[0]
            evidence_text = f"Page {ev.get('page', 1)}: \"{ev.get('text', '')[:180]}\""

        dash_link = f"{self.dashboard_url}/opportunity.html?id={opp.get('id')}"

        text = (
            f"*{header_title}*\n\n"
            f"*Organization:* {opp.get('organization_name', 'N/A')}\n"
            f"*Pipeline:* {pipeline_label}\n"
            f"*Tender:* {opp.get('title', 'N/A')}\n"
            f"*Reference:* {opp.get('reference_number') or 'NOT STATED'}\n"
            f"*Category:* {opp.get('category', 'OTHER_PROFESSIONAL')}\n"
            f"*Fit:* {opp.get('fit_type', 'DIRECT_FIT')}\n"
            f"*Why relevant:* {opp.get('relevance_reason', 'Matched ACNABIN domain criteria')}\n"
            f"*Potential service:* {opp.get('potential_acnabin_service', 'Advisory / Assurance')}\n"
            f"*Published:* {opp.get('publication_date_raw') or 'NOT STATED'}\n"
            f"*Deadline:* {deadline_text}\n"
            f"*Eligibility:* {opp.get('eligibility_summary', 'Potentially eligible — verify tender eligibility and ACNABIN credentials.')}\n"
            f"*Source:* {opp.get('source_url', 'N/A')} (Tier {opp.get('source_tier', 1)})\n"
            f"*Tender document:* {opp.get('document_url') or 'See source link'}\n"
            f"*Evidence:* {evidence_text}\n"
            f"*Confidence:* {opp.get('ai_confidence', 'MEDIUM')}\n"
            f"*Dashboard:* [View Opportunity on Dashboard]({dash_link})\n"
        )
        return text

    async def send_daily_digest(self, digest_summary: Dict[str, Any]) -> bool:
        """Sends daily digest message to Telegram."""
        date_str = digest_summary.get("date", "")
        v_high = digest_summary.get("very_high_count", 0)
        high = digest_summary.get("high_count", 0)
        med = digest_summary.get("medium_count", 0)
        amendments = digest_summary.get("amendments_count", 0)
        deadlines_near = digest_summary.get("deadlines_near_count", 0)

        message = (
            f"*ACNABIN DAILY PROCUREMENT DIGEST — {date_str}*\n\n"
            f"• *VERY HIGH Priority:* {v_high}\n"
            f"• *HIGH Priority:* {high}\n"
            f"• *MEDIUM Priority:* {med}\n"
            f"• *Amendments / Extensions:* {amendments}\n"
            f"• *Deadlines <= 7 days:* {deadlines_near}\n"
            f"• *Sources Monitored:* {digest_summary.get('sources_checked', 0)}\n\n"
            f"Access the full intelligence queue on the [ACNABIN Dashboard]({self.dashboard_url})."
        )

        dedupe_key = f"digest_{date_str}"
        if db.alert_exists(dedupe_key):
            return False

        if not self.is_configured():
            db.record_alert({
                "alert_type": "DAILY_DIGEST",
                "channel": "telegram",
                "recipient": "simulated",
                "dedupe_key": dedupe_key,
                "payload": {"text": message},
                "status": "SIMULATED_SUCCESS"
            })
            return True

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                await client.post(url, json={"chat_id": self.chat_id, "text": message, "parse_mode": "Markdown"})
                db.record_alert({
                    "alert_type": "DAILY_DIGEST",
                    "channel": "telegram",
                    "recipient": str(self.chat_id),
                    "dedupe_key": dedupe_key,
                    "payload": {"text": message},
                    "status": "SENT"
                })
                return True
        except Exception as e:
            logger.error(f"Failed to send digest: {e}")
            return False
