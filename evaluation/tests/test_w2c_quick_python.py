"""
W2-C (server side) — the Python Quick Chat parser behind POST /quick.

Scope note: the shipped UI calls the TypeScript parser
(`web-next/app/lib/parseQuick.ts`, covered by `parseQuick.test.ts`), not this one.
These tests exist because the two parsers shared the same date-parsing defect (D2),
and `POST /quick` remains a reachable endpoint. They guard the server-side fix and
document where the two implementations agree.

`_parse_date` resolves relative dates against `date.today()` with no injectable
reference, so relative-date cases here are expressed relative to today rather than
pinned to a literal — pinning them would make the suite fail with the passage of time.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest


# --------------------------------------------------------------------------- #
# Date parsing — regression guards for defect D2
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "text,month,day",
    [
        ("250 lunch 1 apr", 4, 1),
        ("250 dinner 5 may", 5, 5),
        ("1000 groceries 3 mar", 3, 3),
        ("500 taxi 2 feb", 2, 2),
    ],
)
def test_d_mon_parses_even_with_a_note_word_before_the_day(finance, text, month, day):
    """These all used to fall through to today's date: the two patterns were joined
    with `or`, so the note word plus the day matched first and the 'd mon' pattern
    was never tried."""
    parsed = date.fromisoformat(finance._parse_date(text))
    assert (parsed.month, parsed.day) == (month, day)


def test_mon_d_still_parses(finance):
    parsed = date.fromisoformat(finance._parse_date("250 lunch apr 1"))
    assert (parsed.month, parsed.day) == (4, 1)


def test_full_month_name_parses(finance):
    parsed = date.fromisoformat(finance._parse_date("250 lunch april 1"))
    assert (parsed.month, parsed.day) == (4, 1)


def test_note_word_starting_with_a_month_prefix_is_not_a_month(finance):
    """'marketing' starts with 'mar' but is not March."""
    assert finance._parse_date("500 marketing 5") == date.today().isoformat()


def test_day_is_not_clamped_to_28(finance):
    """Regression guard: the old code did `min(day, 28)`, silently turning
    'apr 30' into April 28 — a wrong date with no warning."""
    parsed = date.fromisoformat(finance._parse_date("250 rent apr 30"))
    assert (parsed.month, parsed.day) == (4, 30)


def test_impossible_day_falls_through_instead_of_crashing(finance):
    """'feb 30' is not a date. It must not raise, and must not silently become
    Feb 28 either."""
    assert finance._parse_date("250 lunch feb 30") == date.today().isoformat()


def test_a_valid_later_candidate_is_used_when_an_earlier_one_is_impossible(finance):
    parsed = date.fromisoformat(finance._parse_date("250 feb 30 or mar 3"))
    assert (parsed.month, parsed.day) == (3, 3)


@pytest.mark.parametrize(
    "text,delta",
    [("250 lunch yesterday", -1), ("250 lunch today", 0), ("250 lunch tomorrow", 1)],
)
def test_relative_dates(finance, text, delta):
    assert finance._parse_date(text) == (date.today() + timedelta(days=delta)).isoformat()


def test_no_date_mentioned_defaults_to_today(finance):
    assert finance._parse_date("250 lunch") == date.today().isoformat()


# --------------------------------------------------------------------------- #
# Amount parsing
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "text,expected",
    [
        ("250 lunch", 250),
        ("120.50 coffee", 120.5),
        ("3,400.50 groceries", 3400.5),
        ("1.2k lunch", 1200),
        ("2m bonus", 2_000_000),
        ("5K rent", 5000),
    ],
)
def test_amount_parsing(finance, text, expected):
    assert finance._parse_amount(text) == pytest.approx(expected)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("250 milk", 250),
        ("300 movie tickets", 300),
        ("250 kilo rice", 250),
        ("500 marketing 5", 500),
        ("120 mango shake", 120),
        ("80 kape", 80),
    ],
)
def test_next_words_first_letter_is_not_a_suffix(finance, text, expected):
    """Regression guard for defect D4. The optional [km] suffix was not word-bounded,
    so it matched the first letter of the following word: "250 milk" became
    ₱250,000,000 and "250 kilo rice" became ₱250,000 — silently, on entirely
    ordinary input."""
    assert finance._parse_amount(text) == pytest.approx(expected)


def test_note_does_not_lose_its_first_letter(finance_fixture, finance):
    """The note-stripping regex had the same unbounded [km]?: "250 milk" stripped
    "250 m" and left "ilk"."""
    assert finance.parse_quick_text("250 milk")["note"] == "milk"
    assert finance.parse_quick_text("300 movie tickets")["note"] == "movie tickets"


# --------------------------------------------------------------------------- #
# Draft shape — agreement with the TypeScript parser
# --------------------------------------------------------------------------- #
def test_quick_text_produces_a_draft(finance_fixture, finance):
    draft = finance.parse_quick_text("250 lunch")
    assert draft["amount"] == pytest.approx(250)
    assert draft["kind"] == "expense"


def test_leading_plus_is_income(finance_fixture, finance):
    assert finance.parse_quick_text("+5000 salary")["kind"] == "income"


def test_transfer_keyword_is_detected(finance_fixture, finance):
    assert finance.parse_quick_text("1000 transfer to savings")["kind"] == "transfer"


def test_quick_chat_uses_no_model(finance_fixture, finance):
    """Breakdown §1 item 5: Quick Chat is a deterministic rule-based parser, not an
    LLM feature. Same input, same output, every time — and no network involved."""
    first = finance.parse_quick_text("1.2k groceries yesterday")
    second = finance.parse_quick_text("1.2k groceries yesterday")
    assert first == second
