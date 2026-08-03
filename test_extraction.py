"""Regression tests for the receipt post-processing pipeline (extraction.py).

The fixtures here are real model outputs captured from gemma4:e4b reading the
Bench Boutique and Uniqlo receipts, so a passing test means the pipeline handles
what the model actually emits — not a hand-idealized version of it.
"""

from extraction import (
    _dedupe_items,
    _fix_payment_fields,
    _remap_summary_lines,
    audit_receipt,
    undo_vat_added_to_total,
    undo_discount_omitted_from_total,
    vat_is_inside_subtotal,
)


def _items(*rows):
    return [{"description": d, "quantity": q, "unit_price": u, "amount": a}
            for d, q, u, a in rows]


# --------------------------------------------------------------------------- #
# _dedupe_items — must collapse model artifacts, never genuine repeated lines
# --------------------------------------------------------------------------- #
def test_repeated_identical_lines_are_kept():
    """A receipt can legitimately print the same product at the same price on
    several lines (Bench Boutique prints 'Kiss & Tell Deo Body Spray 128.00'
    three times). Collapsing them loses money."""
    data = {"items": _items(
        ("Kiss & Tell Deo Body Spray", 1, 128.0, 128.0),
        ("Kiss & Tell Deo Body Spray", 1, 128.0, 128.0),
        ("Kiss & Tell Deo Body Spray", 1, 128.0, 128.0),
    )}
    assert len(_dedupe_items(data)["items"]) == 3


def test_amountless_echo_row_is_still_dropped():
    """The artifact this function exists for: the model emits the priced row
    plus a bare echo of the same name with no amount."""
    data = {"items": _items(
        ("Peri-Peri Chicken", 1, 540.0, 540.0),
        ("Peri-Peri Chicken", None, None, None),
    )}
    items = _dedupe_items(data)["items"]
    assert len(items) == 1
    assert items[0]["amount"] == 540.0


def test_amountless_echo_before_priced_row_is_dropped():
    data = {"items": _items(
        ("Peri-Peri Chicken", None, None, None),
        ("Peri-Peri Chicken", 1, 540.0, 540.0),
    )}
    items = _dedupe_items(data)["items"]
    assert len(items) == 1
    assert items[0]["amount"] == 540.0


def test_distinct_items_untouched():
    data = {"items": _items(
        ("AirSense jacket", 1, 3490.0, 3490.0),
        ("Knitted shirt jacket", 1, 3490.0, 3490.0),
        ("AirSense pants", 1, 1990.0, 1990.0),
    )}
    assert len(_dedupe_items(data)["items"]) == 3


# --------------------------------------------------------------------------- #
# _fix_payment_fields — may re-label OCR'd numbers, never overwrite a printed
# total with a derived one
# --------------------------------------------------------------------------- #
def test_printed_total_confirmed_by_cash_is_not_overwritten():
    """Bench Boutique prints TOTAL SALE 972.00 and CASH 972.00. The model read
    both correctly but only captured part of the item list, so subtotal came
    back as 256. The printed total must survive."""
    data = {"items": _items(("Kiss & Tell Deo Body Spray", 1, 128.0, 128.0)),
            "subtotal": 256.0, "total_amount": 972.0, "cash": 972.0,
            "change": None, "discount": None}
    assert _fix_payment_fields(data)["total_amount"] == 972.0


def test_printed_total_survives_partial_item_capture():
    """Same shape without the cash corroboration: an incomplete item list must
    not be allowed to rewrite a total the model read off the receipt."""
    data = {"items": _items(("Widget", 1, 100.0, 100.0)),
            "subtotal": 100.0, "total_amount": 972.0, "cash": None,
            "change": None, "discount": None}
    assert _fix_payment_fields(data)["total_amount"] == 972.0


def test_rotated_payment_fields_are_still_repaired():
    """The case this function exists for: no printed Total, so the model puts
    the cash figure in total_amount. subtotal 540 + cash 1000 -> change 460."""
    data = {"items": [], "subtotal": 540.0, "total_amount": 1000.0,
            "cash": 460.0, "change": None, "discount": None}
    out = _fix_payment_fields(data)
    assert (out["total_amount"], out["cash"], out["change"]) == (540.0, 1000.0, 460.0)


def test_missing_total_is_filled_from_subtotal():
    data = {"items": [], "subtotal": 540.0, "total_amount": None,
            "cash": None, "change": None, "discount": None}
    assert _fix_payment_fields(data)["total_amount"] == 540.0


def test_consistent_payments_are_left_alone():
    data = {"items": [], "subtotal": 540.0, "total_amount": 540.0,
            "cash": 1000.0, "change": 460.0, "discount": None}
    out = _fix_payment_fields(data)
    assert (out["total_amount"], out["cash"], out["change"]) == (540.0, 1000.0, 460.0)


# --------------------------------------------------------------------------- #
# undo_vat_added_to_total — VAT printed inside the subtotal is never added on
# --------------------------------------------------------------------------- #
def _pepper_lunch():
    """The Pepper Lunch receipt as the model read it: every printed figure is
    correct, but total_amount (545.00 + 58.39) and change (1,000.00 − 603.39) are
    arithmetic the model invented. The paper prints no Total line and CHANGE 455.00.
    """
    return {"items": _items(("DINE-IN", None, None, 425.0),
                            ("SET MEAL A", None, None, 120.0)),
            "subtotal": 545.0, "vatable_sales": 486.61, "vat_amount": 58.39,
            "vat_exempt_sales": 0.0, "zero_rated_sales": 0.0, "discount": None,
            "total_amount": 603.39, "cash": 1000.0, "change": 396.61,
            "currency": "PHP"}


def test_vat_inflated_total_is_corrected():
    out = _fix_payment_fields(_pepper_lunch())
    assert (out["total_amount"], out["cash"], out["change"]) == (545.0, 1000.0, 455.0)


def test_vat_inflated_total_survives_the_payment_identity():
    """The reason the bug got through: cash − change == total holds on the invented
    pair, so the consistency shortcut in _fix_payment_fields certified it. The VAT
    correction has to run before that check, not after."""
    data = _pepper_lunch()
    assert abs(data["cash"] - data["change"] - data["total_amount"]) < 0.01
    assert undo_vat_added_to_total(data)["total_amount"] == 545.0


def test_tax_exclusive_receipt_keeps_its_added_tax():
    """A receipt that really does charge tax on top: the breakdown adds up to the
    subtotal on its own, so 100.00 + 12.00 = 112.00 is the correct total."""
    data = {"items": _items(("Widget", 1, 100.0, 100.0)), "subtotal": 100.0,
            "vatable_sales": 100.0, "vat_amount": 12.0, "discount": None,
            "total_amount": 112.0, "cash": 200.0, "change": 88.0}
    assert vat_is_inside_subtotal(data) is False
    out = _fix_payment_fields(data)
    assert (out["total_amount"], out["change"]) == (112.0, 88.0)


def test_vat_inclusive_receipt_with_a_correct_total_is_untouched():
    data = {"items": _items(("Ramen", 1, 545.0, 545.0)), "subtotal": 545.0,
            "vatable_sales": 486.61, "vat_amount": 58.39, "discount": None,
            "total_amount": 545.0, "cash": 1000.0, "change": 455.0}
    out = _fix_payment_fields(data)
    assert (out["total_amount"], out["change"]) == (545.0, 455.0)


def test_printed_change_is_not_recomputed_when_only_the_total_was_inflated():
    """Change 455.00 was read off the paper; correcting the total must leave it
    alone rather than re-deriving a figure we already have."""
    data = _pepper_lunch() | {"change": 455.0}
    out = undo_vat_added_to_total(data)
    assert (out["total_amount"], out["change"]) == (545.0, 455.0)


# --------------------------------------------------------------------------- #
# undo_discount_omitted_from_total — copying the subtotal must not skip a discount
# --------------------------------------------------------------------------- #
def test_subtotal_copied_as_total_is_reduced_by_a_printed_discount():
    """Rule 10b tells the model to copy the subtotal when no Total line is printed.
    On a discounted receipt a literal reading overstates the charge, and the printed
    payment lines are the evidence that corrects it: 1,000 − 550 = 450."""
    data = {"items": _items(("Shirt", 1, 500.0, 500.0)), "subtotal": 500.0,
            "discount": 50.0, "total_amount": 500.0, "cash": 1000.0, "change": 550.0}
    out = _fix_payment_fields(data)
    assert out["total_amount"] == 450.0


def test_total_equal_to_subtotal_is_kept_when_the_payments_agree_with_it():
    """A receipt whose discount was already applied before the subtotal was printed:
    cash − change confirms 500.00, so the total must not be reduced a second time."""
    data = {"items": _items(("Shirt", 1, 500.0, 500.0)), "subtotal": 500.0,
            "discount": 50.0, "total_amount": 500.0, "cash": 1000.0, "change": 500.0}
    out = _fix_payment_fields(data)
    assert out["total_amount"] == 500.0


def test_discount_correction_needs_both_payment_figures():
    """With no cash/change there is no independent check, so nothing is invented."""
    data = {"items": _items(("Shirt", 1, 500.0, 500.0)), "subtotal": 500.0,
            "discount": 50.0, "total_amount": 500.0, "cash": None, "change": None}
    assert undo_discount_omitted_from_total(data)["total_amount"] == 500.0


def test_undiscounted_receipt_is_untouched_by_the_discount_guard():
    data = {"items": _items(("Ramen", 1, 545.0, 545.0)), "subtotal": 545.0,
            "discount": None, "total_amount": 545.0, "cash": 1000.0, "change": 455.0}
    assert undo_discount_omitted_from_total(data)["total_amount"] == 545.0


def test_audit_flags_an_uncorrected_vat_inflated_total():
    """A row that reaches the ledger inflated by some other route — a manual edit,
    or a receipt saved before this fix — must be flagged for review, not accepted."""
    codes = {f["code"]: f for f in audit_receipt(_pepper_lunch())}
    assert codes["vat_added_to_total"]["severity"] == "error"
    assert codes["vat_added_to_total"]["difference"] == 58.39


def test_audit_stays_quiet_on_a_genuine_tax_exclusive_total():
    data = {"items": _items(("Widget", 1, 100.0, 100.0)), "subtotal": 100.0,
            "vatable_sales": 100.0, "vat_amount": 12.0, "total_amount": 112.0,
            "cash": 112.0, "change": 0.0, "discount": None}
    codes = [f["code"] for f in audit_receipt(data)]
    assert "vat_added_to_total" not in codes
    assert "subtotal_vs_total" not in codes


# --------------------------------------------------------------------------- #
# _remap_summary_lines — unchanged behaviour, guarded against regression
# --------------------------------------------------------------------------- #
def test_summary_line_moved_out_of_items():
    data = {"items": _items(("Coffee", 1, 120.0, 120.0),
                            ("VAT 12%", None, None, 104.14)),
            "vat_amount": None}
    out = _remap_summary_lines(data)
    assert len(out["items"]) == 1
    assert out["vat_amount"] == 104.14
