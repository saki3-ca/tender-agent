"""
Email alerting module for ACNABIN Tender Agent.
Dispatches immediate alerts and daily digests via SMTP (port 587) or HTTP email service.
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Any, Dict, Optional
from app.utils.logging import logger
from app.utils.config import config
from app.db.supabase import db


class EmailAlerter:
    """Dispatches procurement alerts via SMTP."""

    def __init__(self):
        self.host = os.getenv("SMTP_HOST", "")
        self.port = int(os.getenv("SMTP_PORT", 587))
        self.username = os.getenv("SMTP_USERNAME", "")
        self.password = os.getenv("SMTP_PASSWORD", "")
        self.recipient = os.getenv("ALERT_EMAIL_TO", "")
        self.dashboard_url = config.settings.get("dashboard_base_url", "https://tender-agent-d01.pages.dev")

    def is_configured(self) -> bool:
        return bool(self.host and self.username and self.password and self.recipient)

    def send_opportunity_email(self, opp: Dict[str, Any], alert_type: str = "NEW") -> bool:
        """Sends an immediate opportunity alert email."""
        opp_id = opp["id"]
        deadline_str = str(opp.get("submission_deadline") or "no_deadline")
        dedupe_key = f"email_{opp_id}_{alert_type}_{deadline_str}"

        if db.alert_exists(dedupe_key):
            return False

        subject = f"[{opp.get('priority', 'HIGH')}] {alert_type} ACNABIN Opportunity: {opp.get('organization_name')} — {opp.get('title')[:60]}"
        body = self._format_email_body(opp, alert_type)

        if not self.is_configured():
            logger.info(f"SMTP not configured; recording simulated email: {dedupe_key}")
            db.record_alert({
                "opportunity_id": opp_id,
                "alert_type": f"EMAIL_{alert_type}",
                "channel": "email",
                "recipient": self.recipient or "simulated@acnabin.com",
                "dedupe_key": dedupe_key,
                "payload": {"subject": subject},
                "status": "SIMULATED_SUCCESS"
            })
            return True

        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = self.username
            msg["To"] = self.recipient
            msg.attach(MIMEText(body, "html"))

            with smtplib.SMTP(self.host, self.port) as server:
                server.starttls()
                server.login(self.username, self.password)
                server.sendmail(self.username, [self.recipient], msg.as_string())

            db.record_alert({
                "opportunity_id": opp_id,
                "alert_type": f"EMAIL_{alert_type}",
                "channel": "email",
                "recipient": self.recipient,
                "dedupe_key": dedupe_key,
                "payload": {"subject": subject},
                "status": "SENT"
            })
            logger.info("Email alert dispatched successfully", extra={"opp_id": opp_id, "recipient": self.recipient})
            return True
        except Exception as e:
            logger.error(f"Failed to send email alert: {e}", extra={"error": str(e)})
            return False

    def _format_email_body(self, opp: Dict[str, Any], alert_type: str) -> str:
        priority = opp.get("priority", "HIGH")
        color = "#f43f5e" if priority == "VERY HIGH" else "#f59e0b"
        dash_link = f"{self.dashboard_url}/opportunity.html?id={opp.get('id')}"

        return f"""
        <!DOCTYPE html>
        <html>
        <body style="font-family: Arial, sans-serif; background: #0f172a; color: #f8fafc; padding: 20px;">
          <div style="max-width: 650px; margin: auto; background: #1e293b; border-radius: 8px; padding: 25px; border-top: 4px solid {color};">
            <h2 style="color: {color}; margin-top: 0;">{alert_type} ACNABIN OPPORTUNITY [{priority}]</h2>
            <p><strong>Organization:</strong> {opp.get('organization_name')}</p>
            <p><strong>Pipeline:</strong> {opp.get('pipeline')} {'(outside target)' if opp.get('outside_ifrs9_target') else ''}</p>
            <p><strong>Tender Title:</strong> {opp.get('title')}</p>
            <p><strong>Reference:</strong> {opp.get('reference_number') or 'NOT STATED'}</p>
            <p><strong>Category:</strong> {opp.get('category')}</p>
            <p><strong>Fit Type:</strong> {opp.get('fit_type')}</p>
            <p><strong>Submission Deadline:</strong> <span style="color: #38bdf8;">{opp.get('submission_deadline') or 'Not Stated'} ({opp.get('days_remaining', 'N/A')} days left)</span></p>
            <p><strong>Scope Summary:</strong> {opp.get('scope_of_work') or opp.get('title')}</p>
            <p><strong>Eligibility:</strong> {opp.get('eligibility') or 'Potentially eligible — verify tender eligibility and ACNABIN credentials.'}</p>
            <p><strong>Source URL:</strong> <a href="{opp.get('source_url')}" style="color: #38bdf8;">{opp.get('source_url')}</a></p>
            <div style="margin-top: 25px; text-align: center;">
              <a href="{dash_link}" style="background: #4f46e5; color: #fff; padding: 10px 20px; text-decoration: none; border-radius: 6px; font-weight: bold; display: inline-block;">View Opportunity on Dashboard</a>
            </div>
          </div>
        </body>
        </html>
        """
