from datetime import date, datetime, timedelta

from app.classification.status import StatusDetector, is_active
from app.parsers.date_cleaner import DHAKA_TZ

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=DHAKA_TZ)


def dl(y, m, d, h=23, mi=59):
    return datetime(y, m, d, h, mi, tzinfo=DHAKA_TZ)


def test_future_deadline_is_active():
    assert is_active("OPEN", None, dl(2026, 10, 20), now=NOW)


def test_deadline_later_today_is_active_and_earlier_today_is_expired():
    assert is_active("OPEN", None, dl(2026, 10, 5, 15, 0), now=NOW)
    assert not is_active("OPEN", None, dl(2026, 10, 5, 11, 0), now=NOW)


def test_example_F_past_deadline_is_expired():
    assert not is_active("OPEN", date(2026, 9, 1), dl(2026, 9, 15), now=NOW)


def test_known_deadline_wins_over_recent_publication():
    # published 2 days ago but the stated deadline already passed
    assert not is_active("OPEN", date(2026, 10, 3), dl(2026, 10, 4), now=NOW)


def test_example_G_recent_publication_without_deadline_is_active():
    assert is_active("OPEN", date(2026, 10, 3), None, now=NOW)


def test_seven_day_window_boundary():
    assert is_active("OPEN", date(2026, 9, 28), None, now=NOW, recent_days=7)
    assert not is_active("OPEN", date(2026, 9, 27), None, now=NOW, recent_days=7)


def test_old_publication_without_deadline_is_not_active():
    assert not is_active("OPEN", date(2026, 9, 15), None, now=NOW)


def test_no_dates_baseline_item_is_not_active():
    assert not is_active("OPEN", None, None, first_seen=NOW, is_baseline=True, now=NOW)


def test_no_dates_item_newly_appearing_on_monitored_page_is_active_for_7_days():
    assert is_active("OPEN", None, None, first_seen=NOW - timedelta(days=2), is_baseline=False, now=NOW)
    assert not is_active("OPEN", None, None, first_seen=NOW - timedelta(days=9), is_baseline=False, now=NOW)


def test_explicit_closed_status_takes_precedence():
    for status in ("CLOSED", "CANCELLED", "AWARDED"):
        assert not is_active(status, date(2026, 10, 4), dl(2026, 10, 30), now=NOW)


def test_status_detection_from_listing_text():
    s = StatusDetector()
    assert s.status("Cancellation of tender for supply of furniture") == "CANCELLED"
    assert s.status("Tender for printer supply (Cancelled)") == "CANCELLED"
    assert s.status("Notification of Award: external audit 2026") == "AWARDED"
    assert s.status("Tender for ATM booth | Status: Closed") == "CLOSED"
    assert s.status("Withdrawn - RFQ for laptops") == "CANCELLED"
    assert s.status("Invitation for Tender for Internal Audit Services") == "OPEN"
    assert s.status("Time extension notice of e-tender") == "OPEN"
    assert s.status("Corrigendum to RFP for IFRS 9 consultancy") == "OPEN"
