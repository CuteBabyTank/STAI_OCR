"""Regression tests for the receipt post-processing pipeline (extraction.py).

The fixtures here are real model outputs captured from gemma4:e4b reading the
Bench Boutique and Uniqlo receipts, so a passing test means the pipeline handles
what the model actually emits — not a hand-idealized version of it.
"""

from extraction import _dedupe_items, _fix_payment_fields, _remap_summary_lines


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
# _remap_summary_lines — unchanged behaviour, guarded against regression
# --------------------------------------------------------------------------- #
def test_summary_line_moved_out_of_items():
    data = {"items": _items(("Coffee", 1, 120.0, 120.0),
                            ("VAT 12%", None, None, 104.14)),
            "vat_amount": None}
    out = _remap_summary_lines(data)
    assert len(out["items"]) == 1
    assert out["vat_amount"] == 104.14
