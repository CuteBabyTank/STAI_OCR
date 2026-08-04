"""Regression tests for the receipt post-processing pipeline (extraction.py).

The fixtures here are real model outputs captured from gemma4:e4b reading the
Bench Boutique and Uniqlo receipts, so a passing test means the pipeline handles
what the model actually emits — not a hand-idealized version of it.
"""

from datetime import date

from extraction import (
    _clean_str,
    _dedupe_items,
    _fix_payment_fields,
    _normalize_blank_fields,
    _normalize_dates,
    _normalize_item_report,
    _remap_summary_lines,
    assess_item_coverage,
    audit_receipt,
    build_recovery_prompt,
    merge_recovered_items,
    missing_fields,
    normalize_receipt_date,
    stitch_item_halves,
    undo_vat_added_to_total,
    undo_discount_omitted_from_total,
    vat_is_inside_subtotal,
)

TODAY = date(2026, 8, 4)  # fixed, so the ambiguous-date rules are deterministic


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


# --------------------------------------------------------------------------- #
# normalize_receipt_date — the ISO date is derived here, not by the model
# --------------------------------------------------------------------------- #
def test_iso_and_spelled_dates_read_as_printed():
    for printed, expected in [
        ("2026-06-14", "2026-06-14"),
        ("2026/6/4", "2026-06-04"),
        ("20260614", "2026-06-14"),
        ("14 JUN 2026", "2026-06-14"),
        ("JUN 14, 2026", "2026-06-14"),
        ("JUNE 14 2026", "2026-06-14"),
        ("2026-JUN-14", "2026-06-14"),
    ]:
        assert normalize_receipt_date(printed, TODAY) == expected, printed


def test_a_component_over_twelve_is_the_day():
    assert normalize_receipt_date("25/06/2026", TODAY) == "2026-06-25"
    assert normalize_receipt_date("14/06/2026", TODAY) == "2026-06-14"


def test_a_year_first_date_keeps_its_order():
    """The format these receipts print most often. "26-06-14" must not come back
    as 2014-06-26 or as June 26th."""
    assert normalize_receipt_date("26-06-14", TODAY) == "2026-06-14"
    assert normalize_receipt_date("26/08/04", TODAY) == "2026-08-04"


def test_an_all_short_date_falls_back_when_the_year_first_reading_is_implausible():
    """"08/04/26" can only be month-first: reading it year-first dates the receipt
    to 2008, which is not a receipt anyone is filing."""
    assert normalize_receipt_date("08/04/26", TODAY) == "2026-08-04"
    assert normalize_receipt_date("14-06-26", TODAY) == "2026-06-14"


def test_a_trailing_four_digit_year_keeps_the_month_day_fallback():
    """A 4-digit year at the end rules out year-month-day, so the documented
    Philippine/US convention applies: 03/08/2026 is 8 March."""
    assert normalize_receipt_date("03/08/2026", TODAY) == "2026-03-08"


def test_times_and_day_names_are_stripped():
    assert normalize_receipt_date("06/14/26 14:32", TODAY) == "2026-06-14"
    assert normalize_receipt_date("Wed 14/06/26", TODAY) == "2026-06-14"
    assert normalize_receipt_date("06-14-2026 3:45 PM", TODAY) == "2026-06-14"


def test_an_unreadable_date_is_none_not_a_guess():
    for printed in ("", "N/A", "not printed", "31/02/2026", "June", None):
        assert normalize_receipt_date(printed, TODAY) is None, printed


def test_the_raw_printed_date_wins_over_the_models_own_iso_answer():
    """The model only had to copy the raw string; the ISO field is where it does
    the reordering that goes wrong. Here it read "14/06/26" and answered 2014."""
    out = _normalize_dates({"receipt_date": "2014-06-26", "receipt_date_raw": "14/06/26"})
    assert out["receipt_date"] == "2026-06-14"
    assert out["receipt_date_raw"] == "14/06/26"


def test_a_non_iso_date_in_the_iso_field_is_still_parsed():
    out = _normalize_dates({"receipt_date": "14/06/2026", "receipt_date_raw": None})
    assert out["receipt_date"] == "2026-06-14"


def test_an_unparseable_date_is_reported_missing_rather_than_wrong():
    out = _normalize_dates({"receipt_date": "31/02/2026", "receipt_date_raw": "31/02/2026"})
    assert out["receipt_date"] is None
    assert out["receipt_date_raw"] == "31/02/2026"   # kept for the audit to name


def test_audit_flags_a_date_it_could_not_read():
    codes = {f["code"] for f in audit_receipt(
        {"receipt_date_raw": "31/02/2026", "receipt_date": None})}
    assert "date_unreadable" in codes


def test_audit_flags_a_future_date():
    codes = {f["code"] for f in audit_receipt({"receipt_date": "2099-01-01"})}
    assert "date_implausible" in codes


# --------------------------------------------------------------------------- #
# Placeholders — "" / "N/A" / "-" are missing values, not values
# --------------------------------------------------------------------------- #
def test_placeholder_strings_become_null():
    for value in ("", "  ", "N/A", "n/a", "-", "---", "none", "NULL", "unknown",
                  "not printed", "xxx", "...", "?"):
        assert _clean_str(value) is None, value


def test_a_short_real_value_is_not_mistaken_for_a_placeholder():
    assert _clean_str("X") == "X"
    assert _clean_str("0") == "0"
    assert _clean_str("  Jollibee   Inc ") == "Jollibee Inc"


def test_blank_fields_are_nulled_and_the_currency_normalized():
    out = _normalize_blank_fields({
        "vendor_name": "Pepper Lunch", "vendor_tin": "N/A", "vendor_address": "",
        "receipt_number": "-", "currency": "₱",
        "items": [{"description": "  Ramen  ", "amount": 545.0},
                  {"description": "N/A", "amount": 120.0}],
    })
    assert out["vendor_tin"] is None
    assert out["vendor_address"] is None
    assert out["receipt_number"] is None
    assert out["vendor_name"] == "Pepper Lunch"
    assert out["currency"] == "PHP"
    assert out["items"][0]["description"] == "Ramen"
    assert out["items"][1]["description"] is None


def test_missing_fields_lists_placeholders_as_missing():
    data = {"vendor_name": "Mart", "vendor_tin": "N/A", "total_amount": None}
    assert missing_fields(data, ("vendor_name", "vendor_tin", "total_amount")) == [
        "vendor_tin", "total_amount"]


# --------------------------------------------------------------------------- #
# assess_item_coverage — the "was the item block actually read?" verdict
# --------------------------------------------------------------------------- #
def _read(items, **overrides):
    data = {"items": items}
    data.update(overrides)
    return data


def test_items_that_reach_the_subtotal_are_complete():
    out = assess_item_coverage(_read(
        _items(("Rice", 1, 300.0, 300.0), ("Oil", 2, 100.0, 200.0)),
        subtotal=500.0, items_printed_count=2, items_section_verified=True))
    assert out["status"] == "complete"
    assert out["sum_matches"] is True and out["checked_against"] == "subtotal"


def test_a_short_item_list_is_incomplete():
    out = assess_item_coverage(_read(_items(("Rice", 1, 300.0, 300.0)),
                                     subtotal=500.0))
    assert out["status"] == "incomplete"
    assert out["reasons"]


def test_a_printed_count_higher_than_the_rows_is_incomplete():
    """The check that works with no subtotal and no total — the case where a
    dropped line is otherwise undetectable."""
    out = assess_item_coverage(_read(_items(("Rice", 1, 300.0, 300.0)),
                                     items_printed_count=7))
    assert out["status"] == "incomplete"
    assert out["reported_count"] == 7 and out["extracted_count"] == 1


def test_a_row_with_no_amount_is_incomplete():
    out = assess_item_coverage(_read(_items(("Rice", 1, 300.0, 300.0),
                                            ("Oil", None, None, None))))
    assert out["status"] == "incomplete"
    assert out["unpriced_count"] == 1


def test_items_with_nothing_to_check_against_are_unverified_not_complete():
    """Silence is not confirmation: with no subtotal, no total and no count, we
    cannot say the block was fully read — and must not imply it was."""
    out = assess_item_coverage(_read(_items(("Rice", 1, 300.0, 300.0))))
    assert out["status"] == "unverified"
    assert out["complete"] is False


def test_no_items_at_all_is_empty():
    assert assess_item_coverage({"items": []})["status"] == "empty"
    assert assess_item_coverage({})["status"] == "empty"


def test_a_model_claim_of_completeness_cannot_override_the_arithmetic():
    out = assess_item_coverage(_read(_items(("Rice", 1, 300.0, 300.0)),
                                     subtotal=500.0, items_printed_count=1,
                                     items_section_verified=True))
    assert out["status"] == "incomplete"


def test_the_self_report_is_coerced_from_whatever_the_model_emits():
    out = _normalize_item_report({"items_printed_count": "7",
                                  "items_section_verified": "yes"})
    assert out["items_printed_count"] == 7
    assert out["items_section_verified"] is True
    junk = _normalize_item_report({"items_printed_count": "lots",
                                   "items_section_verified": "maybe"})
    assert junk["items_printed_count"] is None
    assert junk["items_section_verified"] is None


def test_audit_reports_a_partially_read_item_block():
    findings = {f["code"]: f for f in audit_receipt(
        _read(_items(("Rice", 1, 300.0, 300.0)), items_printed_count=7))}
    assert findings["items_incomplete"]["severity"] == "error"
    assert findings["items_incomplete"]["expected"] == 7


def test_audit_reports_the_models_own_doubt_as_a_warning_only():
    """An unconfirmed read is worth showing, but on its own it is not evidence
    that anything is wrong — it must not hold up an otherwise clean receipt."""
    findings = {f["code"]: f for f in audit_receipt(
        _read(_items(("Rice", 1, 300.0, 300.0)), subtotal=300.0,
              items_printed_count=1, items_section_verified=False))}
    assert findings["items_unverified"]["severity"] == "warning"
    assert "items_incomplete" not in findings


def test_audit_stays_silent_on_a_receipt_that_reports_nothing_about_its_items():
    """Most receipts arrive with no self-report at all. A finding on every one of
    them would train the user to ignore the ones that matter."""
    codes = {f["code"] for f in audit_receipt(
        _read(_items(("Rice", 1, 300.0, 300.0)), subtotal=300.0))}
    assert "items_incomplete" not in codes and "items_unverified" not in codes


# --------------------------------------------------------------------------- #
# merge_recovered_items — a second look may add lines, never swap them out
# --------------------------------------------------------------------------- #
def test_a_re_read_that_reaches_the_subtotal_replaces_a_short_list():
    data = _read(_items(("Rice", 1, 300.0, 300.0)), subtotal=500.0)
    out = merge_recovered_items(data, _items(("Rice", 1, 300.0, 300.0),
                                             ("Oil", 2, 100.0, 200.0)))
    assert [i["description"] for i in out["items"]] == ["Rice", "Oil"]


def test_a_shorter_re_read_never_displaces_the_first_list():
    """One lucky row equal to the subtotal must not delete the real ones."""
    data = _read(_items(("Rice", 1, 300.0, 300.0), ("Oil", 2, 100.0, 200.0)),
                 subtotal=500.0)
    out = merge_recovered_items(data, _items(("Groceries", None, None, 500.0)))
    assert [i["description"] for i in out["items"]] == ["Rice", "Oil"]


def test_a_re_read_that_agrees_with_the_receipt_is_not_replaced():
    data = _read(_items(("Rice", 1, 300.0, 300.0), ("Oil", 2, 100.0, 200.0)),
                 subtotal=500.0)
    out = merge_recovered_items(data, _items(("Rice", 1, 300.0, 300.0)))
    assert len(out["items"]) == 2


def test_with_no_anchor_only_a_re_read_containing_the_first_list_wins():
    data = _read(_items(("Rice", 1, 300.0, 300.0)))
    kept = merge_recovered_items(dict(data), _items(("Sugar", 1, 50.0, 50.0),
                                                    ("Flour", 1, 40.0, 40.0)))
    assert [i["description"] for i in kept["items"]] == ["Rice"]
    grown = merge_recovered_items(dict(data), _items(("Rice", 1, 300.0, 300.0),
                                                     ("Sugar", 1, 50.0, 50.0)))
    assert [i["description"] for i in grown["items"]] == ["Rice", "Sugar"]


def test_an_empty_first_list_takes_whatever_the_re_read_found():
    out = merge_recovered_items(_read([]), _items(("Rice", 1, 300.0, 300.0)))
    assert len(out["items"]) == 1


def test_a_re_read_that_returns_nothing_leaves_the_first_list_alone():
    data = _read(_items(("Rice", 1, 300.0, 300.0)))
    for junk in ([], None, "no items", [{}]):
        assert len(merge_recovered_items(dict(data), junk)["items"]) == 1


def test_a_re_read_that_gets_closer_wins_even_without_reaching_the_total():
    """The grocery case. Six lines account for ₱469.25 of a ₱689.75 total; the
    re-read finds two of the three missing lines and reaches ₱639.75. Demanding an
    exact hit would throw that away and keep the shorter, more wrong list."""
    data = _read(_items(("FemmeSu 2Ply 250", None, None, 68.75),
                        ("MYSAN SkyFlakes", None, None, 60.50),
                        ("NissinEggnig 130", None, None, 100.50),
                        ("JohnDairy 81BryChsCk", None, None, 45.00),
                        ("GleegrtaJpste 150", None, None, 79.75),
                        ("DelMontePttCrsprg", None, None, 114.75)),
                 total_amount=689.75)
    found = list(data["items"]) + _items(("Lucky Me Pancit Canton", None, None, 85.00),
                                         ("Datu Puti Suka 1L", None, None, 85.00))
    out = merge_recovered_items(dict(data), found)
    assert len(out["items"]) == 8


def test_a_garbled_name_does_not_stop_a_better_re_read_being_adopted():
    """Descriptions off a thermal receipt garble differently on every read, so the
    match that decides "this is the same block, read again" is on AMOUNTS."""
    data = _read(_items(("GleegrtaJpste 150", None, None, 79.75),
                        ("DelMontePttCrsprg", None, None, 114.75)),
                 total_amount=289.75)
    reread = _items(("Glee Grated Jpaste 150", None, None, 79.75),
                    ("DelMonte Ptt Crsprg", None, None, 114.75),
                    ("Nescafe 3in1 10s", None, None, 95.00))
    out = merge_recovered_items(dict(data), reread)
    assert len(out["items"]) == 3


def test_a_re_read_that_shares_almost_nothing_is_still_refused():
    """The guard that survives the amount-based matching: a list that keeps none
    of the prices we already read is a different receipt, not a better read."""
    data = _read(_items(("Rice", None, None, 300.0), ("Oil", None, None, 200.0)),
                 total_amount=900.0)
    invented = _items(("Wine", None, None, 400.0), ("Cheese", None, None, 350.0))
    assert len(merge_recovered_items(dict(data), invented)["items"]) == 2
    assert [i["description"] for i in merge_recovered_items(dict(data), invented)["items"]] \
        == ["Rice", "Oil"]


def test_a_re_read_that_moves_further_from_the_total_is_refused():
    data = _read(_items(("Rice", None, None, 300.0), ("Oil", None, None, 200.0)),
                 total_amount=520.0)
    worse = _items(("Rice", None, None, 300.0), ("Oil", None, None, 200.0),
                   ("Rice", None, None, 300.0))
    assert len(merge_recovered_items(dict(data), worse)["items"]) == 2


# --------------------------------------------------------------------------- #
# stitch_item_halves — two half-crops of one block, joined at the seam
# --------------------------------------------------------------------------- #
def test_the_overlap_between_two_halves_is_dropped_once():
    upper = _items(("Rice", None, None, 300.0), ("Oil", None, None, 200.0),
                   ("Sugar", None, None, 50.0))
    lower = _items(("Oil", None, None, 200.0), ("Sugar", None, None, 50.0),
                   ("Flour", None, None, 40.0))
    out = stitch_item_halves(upper, lower)
    assert [i["description"] for i in out] == ["Rice", "Oil", "Sugar", "Flour"]


def test_halves_with_no_overlap_are_simply_joined():
    upper = _items(("Rice", None, None, 300.0))
    lower = _items(("Flour", None, None, 40.0))
    assert len(stitch_item_halves(upper, lower)) == 2


def test_a_repeated_product_away_from_the_seam_is_not_collapsed():
    """Bench Boutique prints the same deodorant three times. Only a run at the
    seam is an artifact of the crop; repeats elsewhere are real money."""
    upper = _items(("Deo Body Spray", None, None, 128.0),
                   ("Deo Body Spray", None, None, 128.0),
                   ("Socks", None, None, 99.0))
    lower = _items(("Socks", None, None, 99.0),
                   ("Deo Body Spray", None, None, 128.0))
    out = stitch_item_halves(upper, lower)
    assert [i["amount"] for i in out] == [128.0, 128.0, 99.0, 128.0]


def test_one_empty_half_returns_the_other():
    upper = _items(("Rice", None, None, 300.0))
    assert stitch_item_halves(upper, []) == upper
    assert stitch_item_halves(None, upper) == upper
    assert stitch_item_halves(None, None) == []


def test_a_seam_line_read_differently_by_each_half_is_left_for_the_gate():
    """The failure mode the stitch cannot fix: the shared line garbled two ways,
    so it survives twice. It must overshoot visibly rather than be silently
    de-duplicated by name alone — the caller's arithmetic gate rejects it."""
    upper = _items(("Sugar 1kg", None, None, 50.0))
    lower = _items(("Sugor 1kg", None, None, 50.0), ("Flour", None, None, 40.0))
    out = stitch_item_halves(upper, lower)
    assert len(out) == 3


# --------------------------------------------------------------------------- #
# build_recovery_prompt — the focused second-pass question
# --------------------------------------------------------------------------- #
def test_the_recovery_prompt_asks_only_for_what_is_missing():
    prompt = build_recovery_prompt(["vendor_tin", "change"], False,
                                   {"vendor_name": "Pepper Lunch"})
    assert "vendor_tin" in prompt and "change" in prompt
    assert "subtotal" not in prompt.split("RULES")[0]
    assert "Pepper Lunch" in prompt          # context, so it knows the receipt
    assert "items" not in prompt.split("RULES")[-1]


def test_the_recovery_prompt_asks_for_the_item_block_when_it_was_half_read():
    prompt = build_recovery_prompt([], True, {})
    assert "items" in prompt and "items_printed_count" in prompt


def test_there_is_no_recovery_prompt_when_nothing_is_missing():
    assert build_recovery_prompt([], False, {"vendor_name": "Mart"}) == ""
