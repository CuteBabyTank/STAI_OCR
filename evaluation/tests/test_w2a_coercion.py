"""
W2-A — JSON coercion and numeric-field coercion.

Covers two checklist items that had no direct tests (IMPLEMENTATION_STATUS.md §3.3 items
3 and 6): `extraction._coerce_json`, which salvages a JSON object from model output that
may be wrapped in fences or prose, and `extraction._num`, which converts the loosely typed
values inside it to floats.

These sit at the boundary between an unreliable model and a typed schema. Everything
downstream — reconciliation, confidence, the ledger — assumes they did their job. Runs
offline: both are pure functions.
"""

from __future__ import annotations

import json

import pytest

from extraction import _clean_item_description, _coerce_json, _num


# --------------------------------------------------------------------------- #
# _num — the model returns numbers as whatever it feels like
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "value, expected",
    [
        (100, 100.0),
        (100.5, 100.5),
        ("100", 100.0),
        ("100.50", 100.5),
        ("₱100.50", 100.5),          # peso sign
        ("P100.50", 100.5),          # ASCII stand-in for the peso sign
        ("1,250.00", 1250.0),        # thousands separator
        ("₱1,250.00", 1250.0),
        ("  100.50  ", 100.5),       # whitespace
        ("-50.00", -50.0),           # change/adjustment rows can be negative
        ("PHP 99", 99.0),
    ],
)
def test_numeric_values_are_coerced(value, expected):
    assert _num(value) == pytest.approx(expected)


@pytest.mark.parametrize("value", [None, "", "   ", "-", ".", "n/a", "unreadable", "—"])
def test_unreadable_values_become_none_rather_than_zero(value):
    """This is the important half. Coercing an unreadable amount to 0.0 would turn an
    OCR gap into a confident wrong number — the line item would silently reconcile as
    free, and reconciliation would compare against a fabricated sum."""
    assert _num(value) is None


def test_booleans_are_not_treated_as_numbers():
    """`True` is `1` in Python. A model returning a boolean where an amount belongs
    must not yield ₱1.00."""
    assert _num(True) is None
    assert _num(False) is None


def test_a_list_does_not_become_a_fabricated_number():
    """Regression guard for defect **D6**. `_num` used to fall through to the string
    path for containers: `str([1, 2])` -> strip punctuation -> `"12"` -> **12.0**, a
    figure appearing nowhere on the receipt. `_num` runs on the *unvalidated* model
    dict, so that number then passed pydantic as a legitimate float."""
    assert _num([1, 2]) is None


def test_a_dict_does_not_become_a_fabricated_number():
    """Same defect: `{"amount": 1}` stringified to `1.0`."""
    assert _num({"amount": 1}) is None


def test_a_nested_amount_object_is_rejected_rather_than_flattened():
    """The realistic shape — a model wrapping the value it was asked for."""
    assert _num({"value": 500, "currency": "PHP"}) is None


# --------------------------------------------------------------------------- #
# _coerce_json — the model does not reliably return bare JSON
# --------------------------------------------------------------------------- #
def test_bare_json_is_parsed():
    assert _coerce_json('{"vendor_name": "SM"}') == {"vendor_name": "SM"}


def test_a_json_fenced_block_is_unwrapped():
    text = '```json\n{"vendor_name": "SM"}\n```'
    assert _coerce_json(text) == {"vendor_name": "SM"}


def test_a_bare_fenced_block_is_unwrapped():
    text = '```\n{"vendor_name": "SM"}\n```'
    assert _coerce_json(text) == {"vendor_name": "SM"}


def test_leading_prose_is_discarded():
    """Instruction-tuned models like to introduce their answer."""
    text = 'Here is the receipt data you asked for:\n{"vendor_name": "SM"}'
    assert _coerce_json(text) == {"vendor_name": "SM"}


def test_trailing_prose_is_discarded():
    text = '{"vendor_name": "SM"}\nLet me know if you need anything else!'
    assert _coerce_json(text) == {"vendor_name": "SM"}


def test_prose_on_both_sides_is_discarded():
    text = 'Sure! Here you go:\n{"vendor_name": "SM"}\nHope that helps.'
    assert _coerce_json(text) == {"vendor_name": "SM"}


def test_surrounding_whitespace_is_tolerated():
    assert _coerce_json('\n\n  {"a": 1}  \n\n') == {"a": 1}


def test_a_nested_object_survives_extraction():
    """The brace scan takes the first `{` to the last `}`, so nested structures — the
    normal shape of a receipt with line items — must come back whole."""
    payload = {"vendor_name": "SM", "items": [{"description": "Rice", "amount": 100.0}]}
    text = f"Result:\n{json.dumps(payload)}\nDone."
    assert _coerce_json(text) == payload


def test_a_fenced_block_wins_over_surrounding_braces():
    """When the model brackets its answer AND chats around it, the fence is the more
    reliable signal."""
    text = 'Ignore {this}. Here:\n```json\n{"vendor_name": "SM"}\n```\nBye {ok}.'
    assert _coerce_json(text) == {"vendor_name": "SM"}


# --------------------------------------------------------------------------- #
# _coerce_json — failure is visible, never silent
# --------------------------------------------------------------------------- #
# A parse failure must raise so `extract_receipt_validated` can turn it into a
# GuardrailError. Returning `{}` instead would produce an empty receipt that then
# reconciles vacuously and saves as a blank row.
def test_output_with_no_json_raises():
    with pytest.raises(json.JSONDecodeError):
        _coerce_json("I could not read this receipt, sorry.")


def test_truncated_json_raises():
    """The most likely real failure: `num_predict` cut the response mid-object."""
    with pytest.raises(json.JSONDecodeError):
        _coerce_json('{"vendor_name": "SM", "items": [{"description": "Ri')


def test_empty_output_raises():
    with pytest.raises(json.JSONDecodeError):
        _coerce_json("")


def test_malformed_json_raises():
    with pytest.raises(json.JSONDecodeError):
        _coerce_json("{vendor_name: SM,}")


# --------------------------------------------------------------------------- #
# _clean_item_description — the qty/price notation the model folds into names
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Peri-Peri Chicken 2 @ ₱270.00", "Peri-Peri Chicken"),
        ("Rice @ 50.00", "Rice"),
        ("Rice 2 @", "Rice"),
        ("Rice @", "Rice"),
        ("Rice x2", "Rice"),
        ("Peri-Peri Chicken Peri-Peri Chicken", "Peri-Peri Chicken"),  # exact doubling
        ("  Rice  ", "Rice"),
    ],
)
def test_descriptions_are_tidied(raw, expected):
    assert _clean_item_description(raw) == expected


def test_a_description_that_is_only_notation_is_not_emptied():
    """Falling back to the original beats returning an empty description — a blank
    line item is harder to review than a messy one."""
    assert _clean_item_description("2 @ 270.00")


def test_none_stays_none():
    assert _clean_item_description(None) is None


def test_a_genuine_name_containing_a_number_survives():
    """Guard against over-eager stripping: "Coke 1.5L" is a product, not notation."""
    assert _clean_item_description("Coke 1.5L") == "Coke 1.5L"


def test_a_non_doubled_repeat_is_left_alone():
    """Only an exact whole-phrase doubling collapses. "Chicken Chicken Rice" is three
    real words, not an echo."""
    assert _clean_item_description("Chicken Chicken Rice") == "Chicken Chicken Rice"
