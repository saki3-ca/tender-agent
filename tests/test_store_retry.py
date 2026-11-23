import httpx
import pytest

from app.db import supabase as db


class FlakyQuery:
    def __init__(self, failures):
        self.failures = failures
        self.calls = 0

    def execute(self):
        self.calls += 1
        if self.calls <= self.failures:
            raise httpx.ReadTimeout("The read operation timed out")
        return "ok"


def test_execute_retries_network_timeouts(monkeypatch):
    monkeypatch.setattr(db.time, "sleep", lambda s: None)
    q = FlakyQuery(failures=2)
    assert db._execute(q) == "ok"
    assert q.calls == 3


def test_execute_gives_up_after_three_attempts(monkeypatch):
    monkeypatch.setattr(db.time, "sleep", lambda s: None)
    q = FlakyQuery(failures=5)
    with pytest.raises(httpx.ReadTimeout):
        db._execute(q)
    assert q.calls == 3
