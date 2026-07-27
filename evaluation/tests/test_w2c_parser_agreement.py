"""
W2-C — the two Quick Chat parsers must agree.

Closes the checklist item "server/client parser consistency, if both are in scope"
(IMPLEMENTATION_STATUS.md §3.3). Both parsers were tested; neither was tested *against*
the other. Defect D2 was present in **both**, which is precisely why agreement has to be
measured rather than assumed — two independent implementations of the same spec drift, and
the shipped UI calls only one of them.

The corpus is `evaluation/datasets/quickchat_corpus.json`, read by this file and by
`web-next/app/lib/parseQuick.corpus.test.ts`. Each suite asserts its own parser against the
same expectations, so a divergence fails on one side and is immediately localizable.

What is compared, and why not everything
----------------------------------------
Only parser-intrinsic fields: kind, amount, note, and the resolved date. Account and
category ids are excluded — the TypeScript parser is *given* accounts and categories as
arguments while the Python one reads them from the database, so an id mismatch would
reflect different inputs, not different parsing.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

CORPUS_PATH = Path(__file__).resolve().parents[1] / "datasets" / "quickchat_corpus.json"
CORPUS = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
CASES = CORPUS["cases"]
REJECTED = CORPUS["rejected_cases"]


def _ids(cases):
    return [c["case_id"] for c in cases]


# --------------------------------------------------------------------------- #
# The corpus itself
# --------------------------------------------------------------------------- #
def test_the_corpus_is_shared_with_the_typescript_suite():
    """If the TS suite stops reading this file the two sides can silently diverge
    again, which is the exact failure this corpus exists to prevent."""
    ts_test = (Path(__file__).resolve().parents[2] / "web-next" / "app" / "lib"
               / "parseQuick.corpus.test.ts")
    assert ts_test.exists(), "the TypeScript half of the agreement check is missing"
    assert "quickchat_corpus.json" in ts_test.read_text(encoding="utf-8")


def test_case_ids_are_unique():
    all_ids = _ids(CASES) + _ids(REJECTED)
    assert len(all_ids) == len(set(all_ids))


def test_the_corpus_covers_the_known_regressions():
    """D4 (the 1,000,000x amount defect) was found in production behaviour, not by
    unit tests. Its cases must stay in the shared corpus so neither parser can
    regress alone."""
    tagged = {t for c in CASES for t in c.get("tags", [])}
    assert "D4" in tagged


def test_every_case_states_an_expected_kind_and_amount():
    for case in CASES:
        assert case["kind"] in ("expense", "income", "transfer"), case["case_id"]
        assert isinstance(case["amount"], (int, float)), case["case_id"]


# --------------------------------------------------------------------------- #
# The Python parser against the shared corpus
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("case", CASES, ids=_ids(CASES))
def test_python_parser_reads_the_expected_kind(finance_fixture, finance, case):
    assert finance.parse_quick_text(case["input"])["kind"] == case["kind"]


@pytest.mark.parametrize("case", CASES, ids=_ids(CASES))
def test_python_parser_reads_the_expected_amount(finance_fixture, finance, case):
    draft = finance.parse_quick_text(case["input"])
    assert draft["amount"] == pytest.approx(case["amount"])


@pytest.mark.parametrize(
    "case", [c for c in CASES if "note" in c], ids=_ids([c for c in CASES if "note" in c])
)
def test_python_parser_reads_the_expected_note(finance_fixture, finance, case):
    """The note is what the user sees in their ledger. D4 corrupted it silently
    ("250 milk" -> "ilk") while the amount defect drew all the attention."""
    assert finance.parse_quick_text(case["input"])["note"] == case["note"]


@pytest.mark.parametrize("case", CASES, ids=_ids(CASES))
def test_python_parser_resolves_the_expected_date(finance_fixture, finance, case):
    expected = (date.today() + timedelta(days=case["date_offset_days"])).isoformat()
    assert finance.parse_quick_text(case["input"])["occurred_at"][:10] == expected


@pytest.mark.parametrize("case", REJECTED, ids=_ids(REJECTED))
def test_python_parser_rejects_what_the_corpus_marks_invalid(finance_fixture, finance,
                                                             case):
    """Both parsers must refuse the same inputs. A parser that invents a draft from
    "lunch with friends" would put an unintended transaction in front of the user."""
    assert finance.parse_quick_text(case["input"])["ok"] is False


# --------------------------------------------------------------------------- #
# Cross-parser invariants that hold regardless of account/category wiring
# --------------------------------------------------------------------------- #
def test_an_expense_never_gets_a_transfer_target(finance_fixture, finance):
    for case in (c for c in CASES if c["kind"] == "expense"):
        assert finance.parse_quick_text(case["input"])["to_account_id"] is None


def test_a_transfer_targets_a_different_account_than_its_source(finance_fixture, finance):
    """`create_transaction` rejects a self-transfer, so a draft proposing one would be
    rejected the moment the user accepted it."""
    for case in (c for c in CASES if c["kind"] == "transfer"):
        draft = finance.parse_quick_text(case["input"])
        if draft.get("to_account_id") is not None:
            assert draft["to_account_id"] != draft["account_id"]


def test_income_is_never_categorized_as_an_expense(finance_fixture, finance):
    """Expense categories are meaningless on income and would corrupt budget totals."""
    for case in (c for c in CASES if c["kind"] == "income"):
        assert finance.parse_quick_text(case["input"])["category_id"] is None


def test_every_accepted_case_produces_a_positive_amount(finance_fixture, finance):
    for case in CASES:
        assert finance.parse_quick_text(case["input"])["amount"] > 0


def test_a_draft_is_never_silently_treated_as_verified(finance_fixture, finance):
    """W3 Quick Chat pipeline check: the parser returns a *draft*. It must not write
    to the ledger — acceptance is the user's step."""
    before = len(finance.list_transactions())
    for case in CASES:
        finance.parse_quick_text(case["input"])
    assert len(finance.list_transactions()) == before
