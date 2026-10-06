from datetime import datetime, timedelta, timezone

from app.alerts import email as email_mod
from app.alerts.email import EmailAlerter, format_html, format_subject


class FakeStore:
    def __init__(self):
        self.recorded = {}

    def alert_sent(self, key):
        return key in self.recorded

    def record_alert(self, key, payload, status, channel="telegram"):
        self.recorded[key] = channel


def tender(i, ifrs9=False, deadline_days=5):
    return {"id": f"t{i}", "organization_name": "Test Bank <PLC>", "sector": "BANK",
            "title": f"Appointment of External Auditor {i}", "categories": ["Audit & Assurance"],
            "is_ifrs9": ifrs9, "published_date": None, "deadline_has_time": False,
            "deadline": datetime.now(timezone.utc) + timedelta(days=deadline_days),
            "source_url": "https://example.org/tenders"}


def configure(monkeypatch):
    monkeypatch.setenv("SMTP_USER", "sender@example.org")
    monkeypatch.setenv("SMTP_PASSWORD", "app-password")
    monkeypatch.setenv("ALERT_EMAIL_TO", "a@example.org, b@example.org")


def test_disabled_without_settings(monkeypatch):
    for k in ("SMTP_USER", "SMTP_PASSWORD", "ALERT_EMAIL_TO"):
        monkeypatch.delenv(k, raising=False)
    a = EmailAlerter(FakeStore())
    a.add(tender(1))
    assert not a.enabled and a.pending == []


async def test_one_email_per_run_and_never_twice(monkeypatch):
    configure(monkeypatch)
    sent = []
    monkeypatch.setattr(EmailAlerter, "_send", lambda self, msg: sent.append(msg))
    store = FakeStore()
    a = EmailAlerter(store)
    assert a.recipients == ["a@example.org", "b@example.org"]
    a.add(tender(1, deadline_days=9))
    a.add(tender(2, ifrs9=True, deadline_days=2))
    assert await a.flush() == 2
    assert len(sent) == 1
    assert sent[0]["Subject"] == "2 new ACNABIN priority tenders (1 IFRS 9 / ECL)"
    body = sent[0].get_body(("plain",)).get_content()
    assert body.index("Auditor 2") < body.index("Auditor 1")  # earliest deadline first
    assert store.recorded == {"email_priority_t1": "email", "email_priority_t2": "email"}

    b = EmailAlerter(store)
    b.add(tender(1))
    assert await b.flush() == 0 and len(sent) == 1


async def test_failed_send_is_not_recorded(monkeypatch):
    configure(monkeypatch)
    def boom(self, msg):
        raise OSError("smtp down")
    monkeypatch.setattr(EmailAlerter, "_send", boom)
    store = FakeStore()
    a = EmailAlerter(store)
    a.add(tender(1))
    assert await a.flush() == 0 and store.recorded == {}


def test_html_escapes_text():
    html = format_html([tender(1)])
    assert "Test Bank &lt;PLC&gt;" in html and "<PLC>" not in html
    assert format_subject([tender(1)]) == "1 new ACNABIN priority tender: Test Bank <PLC>"
