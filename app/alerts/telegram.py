"""
Telegram alert for newly discovered, active Priority tenders.
Sent once per tender (deduplicated through the alerts table). Does nothing if
TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are not configured.
"""

import html
from typing import Any, Dict

import httpx

from app.utils.config import config
from app.utils.logging import logger


def _fmt_deadline(t: Dict[str, Any]) -> str:
    d = t.get("deadline")
    if not d:
        return "Not stated"
    return d.strftime("%d %b %Y %H:%M") if t.get("deadline_has_time") else d.strftime("%d %b %Y")


def format_message(t: Dict[str, Any]) -> str:
    lines = [
        "<b>New ACNABIN priority tender</b>" + (" — IFRS 9 / ECL" if t.get("is_ifrs9") else ""),
        f"<b>{html.escape(t['organization_name'])}</b>",
        html.escape(t["title"]),
        f"Relevance: {html.escape(', '.join(t.get('categories') or []))}",
        f"Published: {t['published_date'].strftime('%d %b %Y') if t.get('published_date') else 'Not stated'}",
        f"Deadline: {_fmt_deadline(t)}",
        f"Source: {html.escape(t.get('document_url') or t.get('notice_url') or t['source_url'])}",
    ]
    if config.dashboard_base_url:
        page = "bank" if t["sector"] == "BANK" else "ngo"
        lines.append(f"Dashboard: {config.dashboard_base_url}/{page}.html?tab=priority")
    return "\n".join(lines)


def _safe(e: Exception) -> str:
    """Error text without the bot token (httpx errors include the request URL, which contains it)."""
    text = f"{type(e).__name__}: {e}"
    token = config.telegram_bot_token
    return text.replace(token, "***") if token else text


class TelegramAlerter:
    def __init__(self, store):
        self.store = store
        self.enabled = bool(config.settings.get("alerts", {}).get("enabled", True)
                            and config.telegram_bot_token and config.telegram_chat_id)

    async def send_text(self, dedupe_key: str, text: str) -> bool:
        """A plain message (e.g. 'office PC stopped'), sent once per dedupe_key."""
        if not self.enabled or self.store.alert_sent(dedupe_key):
            return False
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(f"https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage",
                                         json={"chat_id": config.telegram_chat_id, "text": text})
                resp.raise_for_status()
            self.store.record_alert(dedupe_key, {"text": text}, "SENT")
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Telegram message failed: {_safe(e)}")
            return False

    async def send_status(self, text: str) -> bool:
        """Run report: sent every time (no dedupe, not recorded in the alerts table)."""
        if not self.enabled:
            return False
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(f"https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage",
                                         json={"chat_id": config.telegram_chat_id, "text": text,
                                               "disable_web_page_preview": True})
                resp.raise_for_status()
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Telegram run report failed: {_safe(e)}")
            return False

    async def send_new_priority(self, tender: Dict[str, Any]) -> bool:
        if not self.enabled:
            return False
        key = f"priority_{tender['id']}"
        if self.store.alert_sent(key):
            return False
        text = format_message(tender)
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage",
                    json={"chat_id": config.telegram_chat_id, "text": text, "parse_mode": "HTML",
                          "disable_web_page_preview": True},
                )
                resp.raise_for_status()
            self.store.record_alert(key, {"text": text}, "SENT")
            return True
        except Exception as e:
            logger.warning(f"Telegram alert failed: {_safe(e)}")
            return False
