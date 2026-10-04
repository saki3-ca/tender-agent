"""
Date normalization and text cleaning module.
Handles Bangla digit (০-৯) normalization, Bangla month parsing,
and strict DD/MM/YYYY formatting for Bangladeshi procurement notices.
"""

import re
from datetime import datetime, timezone
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

DHAKA_TZ = ZoneInfo("Asia/Dhaka")

BANGLA_TO_ASCII_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")

BANGLA_MONTHS = {
    "জানুয়ারি": 1, "জানুয়ারি": 1, "জানুয়ারী": 1,
    "ফেব্রুয়ারি": 2, "ফেব্রুয়ারি": 2, "ফেব্রুয়ারী": 2,
    "মার্চ": 3,
    "এপ্রিল": 4,
    "মে": 5,
    "জুন": 6,
    "জুলাই": 7,
    "আগস্ট": 8, "আগষ্ট": 8,
    "সেপ্টেম্বর": 9,
    "অক্টোবর": 10,
    "নভেম্বর": 11,
    "ডিসেম্বর": 12
}

ENGLISH_MONTHS = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12
}


def normalize_bangla_digits(text: str) -> str:
    """Converts Bangla numeral characters to standard ASCII digits."""
    if not text:
        return ""
    return text.translate(BANGLA_TO_ASCII_DIGITS)


def parse_deadline(date_str: str) -> Tuple[Optional[datetime], Optional[str]]:
    """
    Parses date strings found in Bangladeshi tender documents.
    Enforces DD/MM/YYYY convention. Never parses as MM/DD/YYYY.
    Returns (UTC datetime, note/raw).
    """
    if not date_str:
        return None, None

    cleaned = normalize_bangla_digits(date_str.strip())

    # 1. Regex for DD/MM/YYYY or DD-MM-YYYY or DD.MM.YYYY
    # Optionally with time: 14:00 or 2:00 PM
    dmy_match = re.search(r'(\b\d{1,2})[/\.-](\d{1,2})[/\.-](\d{4})(?:\s+(\d{1,2}):(\d{2})(?:\s*(am|pm|AM|PM))?)?', cleaned)
    if dmy_match:
        day = int(dmy_match.group(1))
        month = int(dmy_match.group(2))
        year = int(dmy_match.group(3))
        hour = int(dmy_match.group(4)) if dmy_match.group(4) else 17 # Default tender close 17:00 if unspecified
        minute = int(dmy_match.group(5)) if dmy_match.group(5) else 0
        ampm = dmy_match.group(6)

        if ampm:
            ampm_lower = ampm.lower()
            if ampm_lower == "pm" and hour < 12:
                hour += 12
            elif ampm_lower == "am" and hour == 12:
                hour = 0

        try:
            dhaka_dt = datetime(year, month, day, hour, minute, tzinfo=DHAKA_TZ)
            utc_dt = dhaka_dt.astimezone(timezone.utc)
            return utc_dt, None
        except ValueError:
            return None, "INVALID_DATE_VALUES"

    # 2. Regex for DD MonthName YYYY (e.g., 25 October 2026 or 25 অক্টোবর ২০২৬)
    # Check English month names
    for mname, mnum in ENGLISH_MONTHS.items():
        m_pattern = rf'(\b\d{{1,2}})\s+{mname}\w*[\s,]+(\d{{4}})'
        m_match = re.search(m_pattern, cleaned, re.IGNORECASE)
        if m_match:
            day = int(m_match.group(1))
            year = int(m_match.group(2))
            try:
                dhaka_dt = datetime(year, mnum, day, 17, 0, tzinfo=DHAKA_TZ)
                return dhaka_dt.astimezone(timezone.utc), None
            except ValueError:
                return None, "INVALID_DATE_VALUES"

    # Check Bangla month names
    for bn_month, mnum in BANGLA_MONTHS.items():
        if bn_month in cleaned:
            # Pattern: 15 অক্টোবর 2026
            bn_pattern = rf'(\b\d{{1,2}})\s+{bn_month}\s+(\d{{4}})'
            bn_match = re.search(bn_pattern, cleaned)
            if bn_match:
                day = int(bn_match.group(1))
                year = int(bn_match.group(2))
                try:
                    dhaka_dt = datetime(year, mnum, day, 17, 0, tzinfo=DHAKA_TZ)
                    return dhaka_dt.astimezone(timezone.utc), None
                except ValueError:
                    return None, "INVALID_DATE_VALUES"

    # If date is ambiguous or cannot be parsed with certainty
    return None, "REQUIRES_VERIFICATION"


def calculate_days_remaining(deadline_utc: Optional[datetime]) -> Optional[int]:
    """Calculates integer days remaining until deadline relative to current time in Asia/Dhaka."""
    if not deadline_utc:
        return None
    now_dhaka = datetime.now(DHAKA_TZ)
    deadline_dhaka = deadline_utc.astimezone(DHAKA_TZ)
    diff = deadline_dhaka.date() - now_dhaka.date()
    return diff.days
