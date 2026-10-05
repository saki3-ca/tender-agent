"""
Date extraction for tender notices.

Dates are always parsed into real date/datetime objects (never compared as strings)
and are never guessed: if a date cannot be found with confidence, the result is None.

Supported formats (English and Bangla digits / month names):
    05/10/2026  05-10-2026  05.10.2026  05/10/26  2026-10-05
    05 October 2026  5 Oct 2026  02 August, 2026  01-Oct-2026  28. Sep 2026  5th October 2026
    October 5, 2026  Oct 5 2026  September 30, 2026; 6:05 PM
    ১৫/১০/২০২৬  ২০ নভেম্বর ২০২৬
Numeric dates are read as DD/MM/YYYY (the Bangladesh convention), never MM/DD/YYYY.

Role detection: a date is a *deadline* or a *publication date* only when a label such as
"Last date of submission", "Closing date", "Deadline" or "Published", "Date of issue",
"Date:" appears just before it. Unlabelled dates are reported separately.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

DHAKA_TZ = ZoneInfo("Asia/Dhaka")

BANGLA_TO_ASCII_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")

ENGLISH_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
BANGLA_MONTHS = {
    "জানুয়ারি": 1, "জানুয়ারী": 1, "জানুয়ারি": 1,
    "ফেব্রুয়ারি": 2, "ফেব্রুয়ারী": 2, "ফেব্রুয়ারি": 2,
    "মার্চ": 3, "এপ্রিল": 4, "মে": 5, "জুন": 6, "জুলাই": 7,
    "আগস্ট": 8, "আগষ্ট": 8, "সেপ্টেম্বর": 9, "অক্টোবর": 10,
    "নভেম্বর": 11, "ডিসেম্বর": 12,
}

_MON = r"(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
_BN_MON = "(" + "|".join(sorted(BANGLA_MONTHS, key=len, reverse=True)) + ")"

_PATTERNS = [
    # 2026-10-05
    ("ymd", re.compile(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)")),
    # 05/10/2026, 05-10-2026, 05.10.2026, 05/10/26
    ("dmy", re.compile(r"(?<![\d./-])(\d{1,2})\s?([./-])\s?(\d{1,2})\s?\2\s?(\d{4}|\d{2})(?![\d./-])")),
    # 05 October 2026, 01-Oct-2026, 02 August, 2026, 28. Sep 2026, 5th Oct 2026
    ("d_mon_y", re.compile(r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?[\s.,-]{0,3}" + _MON + r"[\s.,-]{1,3}(\d{4})(?!\d)", re.I)),
    # 18-Oct-26 (two-digit year only with a month name and hyphens, as on UN portals)
    ("d_mon_yy", re.compile(r"(?<!\d)(\d{1,2})-" + _MON + r"-(\d{2})(?![\d-])", re.I)),
    # October 5, 2026 / Oct 5 2026
    ("mon_d_y", re.compile(r"\b" + _MON + r"\s{0,2}(\d{1,2})(?:st|nd|rd|th)?,?\s{1,3}(\d{4})(?!\d)", re.I)),
    # ২০ নভেম্বর ২০২৬ (after digit normalisation)
    ("bn", re.compile(r"(?<!\d)(\d{1,2})\s*" + _BN_MON + r"[\s,]*(\d{4})(?!\d)")),
]

_TIME_AFTER = re.compile(
    r"^[\s,;@(\-–]{0,4}(?:at\s+|time\s*:?\s*)?(\d{1,2})(?:[:.](\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?(?=\W|$)", re.I)
_TIME_BEFORE = re.compile(
    r"(\d{1,2})[:.](\d{2})\s*(a\.?m\.?|p\.?m\.?)?\s*(?:hrs?|hours)?\s*(?:\(?bst\)?)?\s*(?:on|,|of)?\s*$", re.I)

# Labels that give a date its role. Matching is done on the text just before the date.
_DEADLINE_LABEL = re.compile(
    r"last\s+date|deadline|closing|closes|closed\s+on|due\s+date|end\s+date|"
    r"submission|submit(?:ted)?|will\s+be\s+received|received\s+(?:up\s*to|upto|till|until|by|before|on)|"
    r"on\s+or\s+before|\bbefore\b|not\s+later\s+than|no\s+later\s+than|apply\s+by|up\s*to|upto|till|until|"
    r"শেষ\s*তারিখ|দাখিল|সময়সীমা|গ্রহণের\s*শেষ",
    re.I)
_PUBLISHED_LABEL = re.compile(
    r"publish(?:ed|ing)?|publication|posted|issue\s+date|date\s+of\s+issue|issued|start\s+date|"
    r"\bdated?\b|তারিখ|প্রকাশ",
    re.I)
_IGNORE_LABEL = re.compile(
    r"opening|opened|pre[\s-]?bid|meeting|validity|valid\s+(?:up\s*to|till|until)|"
    r"commencement|completion|delivery|period|year\s+ended|as\s+on|as\s+at|fy\b|financial\s+year",
    re.I)

LABEL_WINDOW_CHARS = 90


@dataclass
class FoundDate:
    start: int
    end: int
    value: date
    time: Optional[time] = None


@dataclass
class DateInfo:
    published: Optional[date] = None
    deadline: Optional[datetime] = None        # timezone-aware (Asia/Dhaka)
    deadline_has_time: bool = False
    unlabelled: List[date] = field(default_factory=list)


def normalize_bangla_digits(text: str) -> str:
    """Converts Bangla numerals (০-৯) to ASCII digits."""
    return (text or "").translate(BANGLA_TO_ASCII_DIGITS)


def today_dhaka() -> date:
    return datetime.now(DHAKA_TZ).date()


def _plausible(d: date, today: date) -> bool:
    return today.year - 5 <= d.year <= today.year + 3


def _build_date(kind: str, m: re.Match) -> Optional[date]:
    try:
        if kind == "ymd":
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        elif kind == "dmy":
            d, mo, y = int(m.group(1)), int(m.group(3)), int(m.group(4))
            if y < 100:
                y += 2000
        elif kind == "d_mon_y":
            d, mo, y = int(m.group(1)), ENGLISH_MONTHS[m.group(2)[:3].lower()], int(m.group(3))
        elif kind == "d_mon_yy":
            d, mo, y = int(m.group(1)), ENGLISH_MONTHS[m.group(2)[:3].lower()], 2000 + int(m.group(3))
        elif kind == "mon_d_y":
            mo, d, y = ENGLISH_MONTHS[m.group(1)[:3].lower()], int(m.group(2)), int(m.group(3))
        elif kind == "bn":
            d, mo, y = int(m.group(1)), BANGLA_MONTHS[m.group(2)], int(m.group(3))
        else:
            return None
        return date(y, mo, d)
    except (ValueError, KeyError):
        return None


def _parse_time(hour: str, minute: Optional[str], ampm: Optional[str]) -> Optional[time]:
    h, mi = int(hour), int(minute or 0)
    if ampm:
        a = ampm.lower().replace(".", "")
        if not 1 <= h <= 12:
            return None
        if a == "pm" and h < 12:
            h += 12
        elif a == "am" and h == 12:
            h = 0
    elif minute is None:
        return None  # a bare number is not a time
    if 0 <= h < 24 and 0 <= mi < 60:
        return time(h, mi)
    return None


def _time_near(text: str, start: int, end: int) -> Optional[time]:
    after = _TIME_AFTER.match(text[end:end + 22])
    if after:
        t = _parse_time(after.group(1), after.group(2), after.group(3))
        if t:
            return t
    before = _TIME_BEFORE.search(text[max(0, start - 28):start])
    if before:
        return _parse_time(before.group(1), before.group(2), before.group(3))
    return None


def find_dates(text: str, today: Optional[date] = None) -> List[FoundDate]:
    """Finds all plausible dates in text, in order of appearance."""
    if not text:
        return []
    today = today or today_dhaka()
    norm = normalize_bangla_digits(text)
    found: List[FoundDate] = []
    for kind, pattern in _PATTERNS:
        for m in pattern.finditer(norm):
            d = _build_date(kind, m)
            if d and _plausible(d, today):
                found.append(FoundDate(m.start(), m.end(), d))
    # Drop overlapping matches, keeping the longest
    found.sort(key=lambda f: (f.start, -(f.end - f.start)))
    result: List[FoundDate] = []
    for f in found:
        if result and f.start < result[-1].end:
            continue
        f.time = _time_near(norm, f.start, f.end)
        result.append(f)
    return result


def parse_first_date(text: str, today: Optional[date] = None) -> Optional[FoundDate]:
    """Parses the first date in a short string such as a table cell."""
    dates = find_dates(text, today)
    return dates[0] if dates else None


def deadline_datetime(d: date, t: Optional[time]) -> Tuple[datetime, bool]:
    """Deadline as an aware datetime. Without a stated time the deadline lasts until end of day."""
    if t is None:
        return datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=DHAKA_TZ), False
    return datetime(d.year, d.month, d.day, t.hour, t.minute, tzinfo=DHAKA_TZ), True


def _label_role(window: str) -> Optional[str]:
    """Role of the label closest to the end of the window: 'deadline', 'published', 'ignore' or None."""
    spans = []
    deadline_spans = [(m.start(), m.end()) for m in _DEADLINE_LABEL.finditer(window)]
    ignore_spans = [(m.start(), m.end()) for m in _IGNORE_LABEL.finditer(window)]
    for _, e in deadline_spans:
        spans.append((e, "deadline"))
    for _, e in ignore_spans:
        spans.append((e, "ignore"))
    for m in _PUBLISHED_LABEL.finditer(window):
        # "Closing date", "Last date", "Opening date", "শেষ তারিখ": the word "date" belongs
        # to the preceding label and does not mean publication date.
        if any(s <= m.start() < e + 6 for s, e in deadline_spans + ignore_spans):
            continue
        spans.append((m.end(), "published"))
    if not spans:
        return None
    spans.sort()
    return spans[-1][1]


def extract_dates(text: str, today: Optional[date] = None) -> DateInfo:
    """
    Extracts the publication date and submission deadline from free text using labels.
    - deadline: the latest date labelled as a deadline (e.g. sale of documents vs submission)
    - published: the first date labelled as a publication/issue date
    """
    today = today or today_dhaka()
    info = DateInfo()
    if not text:
        return info
    norm = normalize_bangla_digits(text)
    dates = find_dates(norm, today)
    deadline_candidates: List[FoundDate] = []
    prev_end = 0
    for f in dates:
        window = norm[max(prev_end, f.start - LABEL_WINDOW_CHARS):f.start]
        role = _label_role(window)
        if role == "deadline":
            deadline_candidates.append(f)
        elif role == "published":
            if info.published is None and f.value <= today + timedelta(days=1):
                info.published = f.value
        elif role is None:
            info.unlabelled.append(f.value)
        prev_end = f.end

    if deadline_candidates:
        best = max(deadline_candidates, key=lambda f: (f.value, f.time or time(23, 59)))
        info.deadline, info.deadline_has_time = deadline_datetime(best.value, best.time)
    return info
