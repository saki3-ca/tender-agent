from datetime import date, time

import pytest

from app.parsers.date_cleaner import extract_dates, find_dates, parse_first_date

TODAY = date(2026, 10, 5)


@pytest.mark.parametrize("text", [
    "05 October 2026", "5 October 2026", "05 Oct 2026", "05/10/2026", "05-10-2026", "05.10.2026",
    "2026-10-05", "October 5, 2026", "Oct 5 2026", "5th October 2026", "05-Oct-2026", "05 October, 2026",
    "০৫/১০/২০২৬", "৫ অক্টোবর ২০২৬",
])
def test_supported_formats_all_mean_5_october_2026(text):
    found = parse_first_date(text, TODAY)
    assert found is not None and found.value == date(2026, 10, 5)


def test_numeric_dates_are_day_first():
    assert parse_first_date("03/04/2026", TODAY).value == date(2026, 4, 3)


def test_invalid_and_implausible_dates_are_not_invented():
    assert parse_first_date("31/02/2026", TODAY) is None
    assert parse_first_date("Ref 12/34/5678", TODAY) is None
    assert parse_first_date("01/01/1999", TODAY) is None
    assert parse_first_date("No date here", TODAY) is None


def test_time_next_to_date():
    f = parse_first_date("October 12, 2026; 11:00 AM", TODAY)
    assert f.value == date(2026, 10, 12) and f.time == time(11, 0)
    f = parse_first_date("Tender will be received up to 11.50 AM on 11/10/2026", TODAY)
    assert f.value == date(2026, 10, 11) and f.time == time(11, 50)


def test_labelled_publication_and_deadline():
    text = ("Memo No: ABC/2026/12  Date: 28/09/2026\n"
            "Last date of selling tender documents: 10/10/2026\n"
            "Last date of submission: 12/10/2026 at 3:00 PM\n"
            "Tender opening date: 12/10/2026 3:30 PM")
    info = extract_dates(text, TODAY)
    assert info.published == date(2026, 9, 28)
    assert info.deadline.date() == date(2026, 10, 12)
    assert info.deadline_has_time and info.deadline.hour == 15


def test_closing_date_label_is_a_deadline_not_a_publication_date():
    info = extract_dates("Closing Date: 20 October 2026", TODAY)
    assert info.deadline.date() == date(2026, 10, 20)
    assert info.published is None


def test_deadline_without_time_lasts_until_end_of_day():
    info = extract_dates("Deadline: 15/10/2026", TODAY)
    assert (info.deadline.hour, info.deadline.minute) == (23, 59)
    assert info.deadline_has_time is False


def test_unlabelled_date_has_no_role():
    info = extract_dates("Annual report 2025 published on the website. 12 August 2026", TODAY)
    assert info.deadline is None
    assert date(2026, 8, 12) in info.unlabelled or info.published == date(2026, 8, 12)


def test_find_dates_returns_all_dates_in_order():
    dates = [f.value for f in find_dates("from 01-Oct-2026 to 14-Oct-2026", TODAY)]
    assert dates == [date(2026, 10, 1), date(2026, 10, 14)]
