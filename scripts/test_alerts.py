"""
Check the alert settings in .env:  python scripts/test_alerts.py

Sends one Telegram test message and logs in to the email server (no email is sent).
Add --email to also send one test email to ALERT_EMAIL_TO.
"""

import smtplib
import sys
from email.message import EmailMessage
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.utils.config import config  # noqa: E402


def telegram() -> bool:
    token, chat = config.telegram_bot_token, config.telegram_chat_id
    if not token or not chat or "your_" in token or "your_" in chat:
        print("Telegram: NOT SET (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID in .env)")
        return False
    r = httpx.post(f"https://api.telegram.org/bot{token}/sendMessage",
                   data={"chat_id": chat, "text": "ACNABIN Tender Agent: Telegram test OK"}, timeout=20)
    ok = r.status_code == 200 and r.json().get("ok")
    print(f"Telegram: {'OK - test message sent' if ok else 'FAILED ' + r.text[:200]}")
    return bool(ok)


def email(send: bool) -> bool:
    host, port = config.smtp_host or "smtp.gmail.com", int(config.smtp_port or 587)
    user, password, to = config.smtp_user, config.smtp_password, config.alert_email_to
    if not user or not password or "your_" in password or not to:
        print("Email: NOT SET (SMTP_USER / SMTP_PASSWORD / ALERT_EMAIL_TO in .env)")
        return False
    try:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls()
            s.login(user, password)
            if send:
                msg = EmailMessage()
                msg["Subject"], msg["From"], msg["To"] = "ACNABIN Tender Agent: email test", user, to
                msg.set_content("Email alerts from this PC work.")
                s.send_message(msg)
        print(f"Email: OK - logged in as {user}" + (f", test email sent to {to}" if send else ""))
        return True
    except Exception as e:  # noqa: BLE001
        print(f"Email: FAILED {e!r}")
        return False


if __name__ == "__main__":
    results = [telegram(), email("--email" in sys.argv)]
    sys.exit(0 if all(results) else 1)
