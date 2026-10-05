"""
Open / closed status and the ACTIVE rule.

    ACTIVE = status is open (not closed / cancelled / awarded / withdrawn)
             AND (
                   deadline exists AND deadline >= now
                OR deadline unknown AND publication date within the last N days (default 7)
                OR deadline and publication date both unknown AND the notice first appeared on a
                   source that was already being monitored, within the last N days
                   (it was demonstrably published recently; no date is invented)
             )

A known deadline always decides: a past deadline is expired even if the notice was
published recently. Everything is evaluated against the current time, never a fixed date.
The same rule is implemented in SQL by the v_active_tenders view.
"""

import re
from datetime import date, datetime, timedelta
from typing import Optional

from app.parsers.date_cleaner import DHAKA_TZ
from app.utils.config import config

_STATUS_LABELS = [
    (re.compile(r"cancel|withdraw|বাতিল", re.I), "CANCELLED"),
    (re.compile(r"award|result", re.I), "AWARDED"),
]


class StatusDetector:
    def __init__(self, phrases=None):
        phrases = phrases or config.relevance["closed_status"]
        self.closed = [re.compile(r"(?<![\w])(?:" + p + r")(?![\w])", re.I) if p.isascii() else re.compile(p)
                       for p in phrases]

    def status(self, listing_text: str) -> str:
        """OPEN, CLOSED, CANCELLED or AWARDED, from the listing title/row text only."""
        for pattern in self.closed:
            m = pattern.search(listing_text or "")
            if m:
                for label_re, label in _STATUS_LABELS:
                    if label_re.search(m.group(0)):
                        return label
                return "CLOSED"
        return "OPEN"


def is_active(
    status: str,
    published: Optional[date],
    deadline: Optional[datetime],
    first_seen: Optional[datetime] = None,
    is_baseline: bool = True,
    now: Optional[datetime] = None,
    recent_days: Optional[int] = None,
) -> bool:
    now = now or datetime.now(DHAKA_TZ)
    recent_days = recent_days if recent_days is not None else config.recent_publication_days
    if status != "OPEN":
        return False
    if deadline is not None:
        return deadline >= now
    today = now.astimezone(DHAKA_TZ).date()
    if published is not None:
        return published >= today - timedelta(days=recent_days)
    if first_seen is not None and not is_baseline:
        return first_seen >= now - timedelta(days=recent_days)
    return False
