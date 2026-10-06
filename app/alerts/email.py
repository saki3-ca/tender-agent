"""
Email alert for newly discovered, active Priority tenders.

One message per run lists every Priority tender found for the first time in that run
(each tender is emailed once; deduplicated through the alerts table). Sent over SMTP,
e.g. Gmail with an app password. Does nothing unless SMTP_USER, SMTP_PASSWORD and
ALERT_EMAIL_TO are configured.
"""

import asyncio
import html
import smtplib
import ssl
from email.message import EmailMessage
from typing import Any, Dict, List

from app.alerts.telegram import _fmt_deadline
from app.utils.config import config
from app.utils.logging import logger


def _link(t: Dict[str, Any]) -> str:
    return t.get("document_url") or t.get("notice_url") or t["source_url"]


def _published(t: Dict[str, Any]) -> str:
    return t["published_date"].strftime("%d %b %Y") if t.get("published_date") else "Not stated"


def _sort_key(t: Dict[str, Any]):
    # Earliest deadline first; tenders without a deadline last
    d = t.get("deadline")
    return (d is None, d.timestamp() if d else 0)


def format_subject(tenders: List[Dict[str, Any]]) -> str:
    n = len(tenders)
    ifrs9 = sum(1 for t in tenders if t.get("is_ifrs9"))
    subject = f"{n} new ACNABIN priority tender{'s' if n != 1 else ''}"
    if ifrs9:
        subject += f" ({ifrs9} IFRS 9 / ECL)"
    if n == 1:
        subject += f": {tenders[0]['organization_name']}"
    return subject


def format_text(tenders: List[Dict[str, Any]]) -> str:
    blocks = []
    for t in tenders:
        blocks.append("\n".join([
            f"{t['organization_name']} ({'Bank' if t['sector'] == 'BANK' else 'NGO'})"
            + ("  [IFRS 9 / ECL]" if t.get("is_ifrs9") else ""),
            t["title"],
            f"Relevance: {', '.join(t.get('categories') or [])}",
            f"Published: {_published(t)}   Deadline: {_fmt_deadline(t)}",
            f"Link: {_link(t)}",
        ]))
    text = "\n\n".join(blocks)
    if config.dashboard_base_url:
        text += f"\n\nDashboard: {config.dashboard_base_url}/"
    return text


def format_html(tenders: List[Dict[str, Any]]) -> str:
    rows = []
    for t in tenders:
        e = html.escape
        badge = (' <span style="background:#7a5c00;color:#fff;padding:1px 6px;border-radius:3px;'
                 'font-size:11px">IFRS 9 / ECL</span>') if t.get("is_ifrs9") else ""
        rows.append(
            '<tr><td style="padding:12px 0;border-bottom:1px solid #ddd">'
            f'<div style="font-size:12px;color:#555">{e(t["organization_name"])} &middot; '
            f'{"Bank" if t["sector"] == "BANK" else "NGO"}{badge}</div>'
            f'<div style="font-size:15px;font-weight:600;margin:4px 0">'
            f'<a href="{e(_link(t))}" style="color:#0b3d6e;text-decoration:none">{e(t["title"])}</a></div>'
            f'<div style="font-size:13px;color:#333">Deadline: <b>{e(_fmt_deadline(t))}</b>'
            f' &nbsp;|&nbsp; Published: {e(_published(t))}</div>'
            f'<div style="font-size:12px;color:#555">Relevance: {e(", ".join(t.get("categories") or []))}</div>'
            '</td></tr>')
    footer = ""
    if config.dashboard_base_url:
        url = html.escape(config.dashboard_base_url)
        footer = f'<p style="font-size:13px"><a href="{url}/">Open the tender dashboard</a></p>'
    return (
        '<div style="font-family:Arial,Helvetica,sans-serif;max-width:680px">'
        f'<h2 style="font-size:18px;color:#0b3d6e">{html.escape(format_subject(tenders))}</h2>'
        f'<table style="width:100%;border-collapse:collapse">{"".join(rows)}</table>{footer}'
        '<p style="font-size:11px;color:#888">Sent by the ACNABIN tender monitor. '
        'Each tender is emailed once, when it is first found.</p></div>')


class EmailAlerter:
    def __init__(self, store):
        self.store = store
        self.recipients = [r.strip() for r in config.alert_email_to.split(",") if r.strip()]
        self.enabled = bool(config.settings.get("alerts", {}).get("enabled", True)
                            and config.smtp_user and config.smtp_password and self.recipients)
        self.pending: List[Dict[str, Any]] = []

    def add(self, tender: Dict[str, Any]) -> None:
        if self.enabled and not self.store.alert_sent(f"email_priority_{tender['id']}"):
            self.pending.append(tender)

    def _send(self, msg: EmailMessage) -> None:
        context = ssl.create_default_context()
        if config.smtp_port == 465:
            with smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, context=context, timeout=30) as s:
                s.login(config.smtp_user, config.smtp_password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=30) as s:
                s.starttls(context=context)
                s.login(config.smtp_user, config.smtp_password)
                s.send_message(msg)

    async def flush(self) -> int:
        """Sends one message with all pending tenders. Returns the number of tenders emailed."""
        if not self.pending:
            return 0
        tenders = sorted(self.pending, key=_sort_key)
        msg = EmailMessage()
        msg["Subject"] = format_subject(tenders)
        msg["From"] = f"ACNABIN Tender Monitor <{config.alert_email_from or config.smtp_user}>"
        msg["To"] = ", ".join(self.recipients)
        msg.set_content(format_text(tenders))
        msg.add_alternative(format_html(tenders), subtype="html")
        try:
            await asyncio.to_thread(self._send, msg)
        except Exception as e:  # noqa: BLE001 - an alert failure must not fail the run
            logger.warning(f"Email alert failed: {e}")
            return 0
        for t in tenders:
            self.store.record_alert(f"email_priority_{t['id']}", {"title": t["title"]}, "SENT", channel="email")
        self.pending = []
        return len(tenders)
