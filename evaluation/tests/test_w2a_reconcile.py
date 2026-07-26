"""
W2-A — receipt arithmetic reconciliation (`extraction.reconcile`).

Covers the checklist item "Reconciliation tolerance behavior", which had **zero tests**
before this file (see IMPLEMENTATION_STATUS.md §3.3). This is the function behind Snag's
central verification claim: it is what decides whether a receipt's stated total is
supported by its own line items, and its output feeds `core.needs_disambiguation` ->
`needs_review` / `flagged`.

Runs offline: `reconcile` is a pure function over a dict. No model, no database.

Tolerance semantics under test
------------------------------
A receipt is flagged when the line items do not add up to the total, allowing for:

  * an absolute floor of ₱1.00 — thermal receipts round, and a one-peso gap is noise,
    not evidence of a misread field;
  * a relative band of 2% of the total — a bigger receipt has more line items and more
    accumulated rounding, so the acceptable gap scales with it;
  * a stated discount — if the items reconcile once the discount is subtracted, the
    receipt is consistent and must NOT be flagged.

The boundary is asserted from those semantics (floor, band, discount) rather than by
reading the constant back out of the implementation, so a change to the rule fails here
instead of being silently ratified.
"""

from __future__ import annotations

import pytest

from extraction import reconcile


def _receipt(items, total, **extra) -> dict:
    """A receipt dict shaped like the model's post-processed output."""
    return {
        "items": [{"description": f"Item {i}", "amount": a} for i, a in enumerate(items)],
        "total_amount": total,
        **extra,
    }


# --------------------------------------------------------------------------- #
# The consistent case — no warning
# --------------------------------------------------------------------------- #
def test_items_that_add_up_exactly_are_not_flagged():
    assert reconcile(_receipt([100.0, 250.0, 50.0], 400.0)) == []


def test_a_single_item_equal_to_the_total_is_not_flagged():
    assert reconcile(_receipt([99.0], 99.0)) == []


def test_cent_level_rounding_is_not_flagged():
    """Line items are summed and rounded to 2dp before comparison, so float noise
    from summing many amounts must not produce a warning."""
    assert reconcile(_receipt([0.1, 0.2, 0.3, 0.4, 99.0], 100.0)) == []


# --------------------------------------------------------------------------- #
# The inconsistent case — warning, and it must be readable
# --------------------------------------------------------------------------- #
def test_items_far_below_the_total_are_flagged():
    warnings = reconcile(_receipt([100.0], 500.0))
    assert len(warnings) == 1


def test_items_far_above_the_total_are_flagged():
    """The check is symmetric: extra or duplicated items are as much a defect as
    missing ones."""
    assert len(reconcile(_receipt([500.0, 500.0], 500.0))) == 1


def test_the_warning_states_both_figures():
    """A human triaging a flagged receipt needs to see what was compared, not just
    that something was wrong."""
    warning = reconcile(_receipt([100.0], 500.0))[0]
    assert "100.00" in warning and "500.00" in warning


def test_only_one_warning_is_produced_per_receipt():
    """Reconciliation is a single check; duplicated reasons would inflate any
    review-reason count computed from this list."""
    assert len(reconcile(_receipt([1.0, 2.0], 900.0))) == 1


# --------------------------------------------------------------------------- #
# The ₱1.00 absolute floor — governs small receipts
# --------------------------------------------------------------------------- #
# On a ₱20 receipt, 2% is ₱0.40, so the ₱1.00 floor is the wider of the two and wins.
def test_a_one_peso_gap_on_a_small_receipt_is_tolerated():
    assert reconcile(_receipt([19.0], 20.0)) == []


def test_a_gap_beyond_the_floor_on_a_small_receipt_is_flagged():
    assert len(reconcile(_receipt([18.0], 20.0))) == 1


def test_the_floor_is_inclusive():
    """The comparison is `> tolerance`, so a gap exactly equal to the floor is
    accepted. Pinning this stops the boundary drifting by one cent unnoticed."""
    assert reconcile(_receipt([19.0], 20.0)) == []
    assert len(reconcile(_receipt([18.99], 20.0))) == 1


# --------------------------------------------------------------------------- #
# The 2% relative band — governs large receipts
# --------------------------------------------------------------------------- #
# On a ₱10,000 receipt, 2% is ₱200, which is wider than the ₱1.00 floor and wins.
def test_a_gap_inside_the_relative_band_is_tolerated_on_a_large_receipt():
    assert reconcile(_receipt([9_850.0], 10_000.0)) == []


def test_a_gap_beyond_the_relative_band_is_flagged_on_a_large_receipt():
    assert len(reconcile(_receipt([9_700.0], 10_000.0))) == 1


def test_the_band_is_inclusive_at_exactly_two_percent():
    assert reconcile(_receipt([9_800.0], 10_000.0)) == []
    assert len(reconcile(_receipt([9_799.0], 10_000.0))) == 1


def test_the_band_scales_with_the_total():
    """The same ₱150 gap is acceptable on a ₱10,000 receipt and a defect on a ₱1,000
    one. This is the whole point of a relative tolerance."""
    assert reconcile(_receipt([9_850.0], 10_000.0)) == []
    assert len(reconcile(_receipt([850.0], 1_000.0))) == 1


# --------------------------------------------------------------------------- #
# Discounts — a receipt that reconciles after the discount is consistent
# --------------------------------------------------------------------------- #
def test_items_reconciling_after_a_discount_are_not_flagged():
    """Items are usually listed at list price with the discount applied at the
    bottom. Flagging that would make every discounted receipt a false review."""
    assert reconcile(_receipt([1_000.0], 800.0, discount=200.0)) == []


def test_a_discount_that_still_does_not_reconcile_is_flagged():
    assert len(reconcile(_receipt([1_000.0], 500.0, discount=200.0))) == 1


def test_a_receipt_reconciling_before_the_discount_is_still_accepted():
    """Some receipts list already-discounted amounts. Either reading may be correct,
    so both are accepted rather than guessing which convention the vendor used."""
    assert reconcile(_receipt([800.0], 800.0, discount=200.0)) == []


def test_a_null_discount_is_treated_as_zero():
    assert reconcile(_receipt([100.0], 100.0, discount=None)) == []
    assert len(reconcile(_receipt([100.0], 500.0, discount=None))) == 1


# --------------------------------------------------------------------------- #
# Cases where reconciliation cannot run — silence, not a false accusation
# --------------------------------------------------------------------------- #
# With nothing to compare, `reconcile` must stay quiet. The gap is still caught:
# `needs_disambiguation` raises its own reason for a missing total or missing items
# (asserted below), so silence here does not mean the receipt is auto-accepted.
def test_a_receipt_with_no_items_produces_no_reconciliation_warning():
    assert reconcile(_receipt([], 500.0)) == []


def test_a_receipt_with_no_total_produces_no_reconciliation_warning():
    assert reconcile(_receipt([100.0], None)) == []


def test_a_zero_total_produces_no_reconciliation_warning():
    """A ₱0.00 total is a misread, not a receipt whose items should sum to zero.
    Comparing against it would produce a nonsense warning."""
    assert reconcile(_receipt([100.0], 0.0)) == []


def test_a_negative_total_produces_no_reconciliation_warning():
    assert reconcile(_receipt([100.0], -500.0)) == []


def test_items_with_unreadable_amounts_are_skipped():
    """A garbled amount must not be coerced to zero and counted — that would turn an
    OCR gap into a fabricated arithmetic error."""
    data = {
        "items": [{"description": "Rice", "amount": 100.0},
                  {"description": "???", "amount": "unreadable"}],
        "total_amount": 100.0,
    }
    assert reconcile(data) == []


def test_a_receipt_whose_items_are_all_unreadable_produces_no_warning():
    data = {"items": [{"description": "???", "amount": None}], "total_amount": 500.0}
    assert reconcile(data) == []


def test_a_missing_items_key_does_not_raise():
    assert reconcile({"total_amount": 100.0}) == []


def test_an_empty_receipt_does_not_raise():
    assert reconcile({}) == []


# --------------------------------------------------------------------------- #
# Numeric coercion at the boundary (W2-A "numeric-field coercion")
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("total", ["500.00", "₱500.00", "500", " 500.00 "])
def test_a_total_arriving_as_a_string_is_still_reconciled(total):
    """The model returns JSON, but not reliably typed. If a string total silently
    skipped reconciliation, an inconsistent receipt would pass unflagged."""
    assert len(reconcile(_receipt([100.0], total))) == 1
    assert reconcile(_receipt([500.0], total)) == []


def test_amounts_arriving_as_strings_are_summed():
    data = {
        "items": [{"description": "A", "amount": "100.00"},
                  {"description": "B", "amount": "400.00"}],
        "total_amount": 500.0,
    }
    assert reconcile(data) == []


# --------------------------------------------------------------------------- #
# The reason reaches the review flag — the contract that makes this matter
# --------------------------------------------------------------------------- #
def test_an_unreconciled_receipt_is_sent_for_human_review(core):
    """`reconcile` only matters because its output becomes a review reason. If this
    wiring broke, receipts with unsupported totals would be auto-accepted while every
    unit test above still passed."""
    unbalanced = core.ReceiptData(
        vendor_name="SM Supermarket",
        total_amount=500.0,
        items=[core.LineItem(description="Rice", quantity=1, unit_price=100.0, amount=100.0)],
    )
    reasons = core.needs_disambiguation(unbalanced)
    assert any("reconcile" in r.lower() or "add up" in r.lower() for r in reasons)


def test_a_reconciling_receipt_is_not_sent_for_review(core):
    """False-review rate: a receipt whose math is sound must not be flagged."""
    balanced = core.ReceiptData(
        vendor_name="SM Supermarket",
        total_amount=100.0,
        items=[core.LineItem(description="Rice", quantity=1, unit_price=100.0, amount=100.0)],
    )
    assert core.needs_disambiguation(balanced) == []


def test_a_receipt_with_no_total_is_still_flagged_by_another_reason(core):
    """Reconciliation stays silent without a total (above). This confirms the receipt
    is still caught — silence in one check is covered by another."""
    no_total = core.ReceiptData(
        vendor_name="X", total_amount=None,
        items=[core.LineItem(description="Rice", quantity=1, unit_price=100.0, amount=100.0)],
    )
    assert any("total" in r.lower() for r in core.needs_disambiguation(no_total))
