"""
W2-F — receipt-to-statement reconciliation (`reconciliation.py`).

This is the capability the consultation proof point names and the product previously did
not have at all. IMPLEMENTATION_STATUS.md §5 recorded 11 of 13 proof-point capabilities as
absent; this module and these tests are what close them.

Distinct from `extraction.reconcile` (receipt-internal arithmetic), which is covered by
`test_w2a_reconcile.py`. Conflating the two is the specific error the follow-up warns
against, so they are kept in separate files.

Runs entirely offline: matching is deterministic string and arithmetic work, no model.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def reconciliation():
    """Imported lazily — `reconciliation` imports `core`, whose DB path is bound at
    import time (see conftest.py)."""
    import reconciliation as _reconciliation

    return _reconciliation


@pytest.fixture
def make_receipt(finance_fixture, core):
    """Save a receipt and return its id."""
    def _make(vendor: str, receipt_date: str, total: float, currency: str = "PHP") -> int:
        data = core.ReceiptData(
            vendor_name=vendor, receipt_date=receipt_date, total_amount=total,
            currency=currency,
            items=[core.LineItem(description="Item", quantity=1,
                                 unit_price=total, amount=total)],
        )
        return core.save_receipt(data, f"{vendor}.jpg", flagged=False, index=False)

    return _make


def _csv(*rows: str) -> str:
    return "\n".join(("Posting Date,Description,Amount", *rows))


# --------------------------------------------------------------------------- #
# Amount parsing — banks disagree about everything
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "value, expected",
    [
        ("1234.56", 1234.56),
        ("1,234.56", 1234.56),
        ("₱1,234.56", 1234.56),
        ("PHP 1,234.56", 1234.56),
        ("-1,234.56", -1234.56),
        ("(1,234.56)", -1234.56),      # accounting parentheses
        ("1,234.56-", -1234.56),       # trailing-minus convention
        (1234.56, 1234.56),
        (-50, -50.0),
    ],
)
def test_statement_amounts_are_parsed(reconciliation, value, expected):
    assert reconciliation.parse_statement_amount(value) == pytest.approx(expected)


@pytest.mark.parametrize("value", [None, "", "   ", "-", "n/a", "PENDING"])
def test_an_unreadable_amount_is_none_not_zero(reconciliation, value):
    """A charge silently read as 0.00 would reconcile against nothing and vanish from
    the report — the money would appear accounted for."""
    assert reconciliation.parse_statement_amount(value) is None


def test_a_boolean_is_not_an_amount(reconciliation):
    assert reconciliation.parse_statement_amount(True) is None


# --------------------------------------------------------------------------- #
# Date parsing
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "value, expected",
    [
        ("2026-06-15", "2026-06-15"),
        ("15/06/2026", "2026-06-15"),   # day/month — Philippine convention
        ("15-06-2026", "2026-06-15"),
        ("15 Jun 2026", "2026-06-15"),
        ("Jun 15, 2026", "2026-06-15"),
        ("15-Jun-2026", "2026-06-15"),
        ("2026/06/15", "2026-06-15"),
    ],
)
def test_statement_dates_are_parsed(reconciliation, value, expected):
    assert reconciliation.parse_statement_date(value) == expected


def test_an_unparseable_date_is_none_not_today(reconciliation):
    """Defaulting to today would silently place a charge in the current period and
    make it match receipts it has nothing to do with."""
    assert reconciliation.parse_statement_date("sometime last week") is None
    assert reconciliation.parse_statement_date("") is None


# --------------------------------------------------------------------------- #
# Merchant normalization — the thing that makes name variation survivable
# --------------------------------------------------------------------------- #
def test_channel_noise_and_reference_numbers_are_stripped(reconciliation):
    assert reconciliation.normalize_merchant(
        "POS PURCHASE SM SUPERMARKET MAKATI 0412 REF#88213"
    ) == "sm supermarket"


def test_card_network_words_are_stripped(reconciliation):
    assert reconciliation.normalize_merchant("VISA DEBIT JOLLIBEE CUBAO") == "jollibee"


def test_corporate_suffixes_are_stripped(reconciliation):
    assert reconciliation.normalize_merchant("Jollibee Foods Corp.") == "jollibee foods"


def test_normalization_is_case_insensitive(reconciliation):
    assert (reconciliation.normalize_merchant("SM Supermarket")
            == reconciliation.normalize_merchant("sm supermarket"))


def test_empty_input_normalizes_to_empty(reconciliation):
    assert reconciliation.normalize_merchant(None) == ""
    assert reconciliation.normalize_merchant("") == ""


def test_a_statement_descriptor_matches_its_receipt_vendor(reconciliation):
    """The real case: the statement carries extra context around the vendor name."""
    similarity = reconciliation.merchant_similarity(
        "POS PURCHASE SM SUPERMARKET MAKATI 0412", "SM Supermarket"
    )
    assert similarity == pytest.approx(1.0)


def test_unrelated_merchants_do_not_match(reconciliation):
    assert reconciliation.merchant_similarity("JOLLIBEE CUBAO", "Shell Gas Station") == 0.0


def test_similarity_is_symmetric(reconciliation):
    a = reconciliation.merchant_similarity("SM SUPERMARKET MAKATI", "SM Supermarket")
    b = reconciliation.merchant_similarity("SM Supermarket", "SM SUPERMARKET MAKATI")
    assert a == pytest.approx(b)


def test_an_empty_name_never_matches(reconciliation):
    """Otherwise every receipt with an unread vendor would match every charge."""
    assert reconciliation.merchant_similarity("", "SM Supermarket") == 0.0


# --------------------------------------------------------------------------- #
# CSV ingestion
# --------------------------------------------------------------------------- #
def test_a_signed_amount_column_is_read(reconciliation):
    rows = reconciliation.parse_statement_csv(
        _csv("2026-06-15,SM SUPERMARKET,-500.00")
    )
    assert rows[0]["amount"] == pytest.approx(-500.0)


def test_separate_debit_and_credit_columns_are_read(reconciliation):
    """The other layout banks emit. A debit is money out and must come back negative
    regardless of how the file expressed it."""
    text = ("Date,Description,Debit,Credit\n"
            "2026-06-15,SM SUPERMARKET,500.00,\n"
            "2026-06-16,REFUND,,120.00")
    rows = reconciliation.parse_statement_csv(text)
    assert rows[0]["amount"] == pytest.approx(-500.0)
    assert rows[1]["amount"] == pytest.approx(120.0)


def test_a_positive_charge_convention_can_be_flipped(reconciliation):
    """Some card issuers export charges as positive. The output is always normalized
    to negative-is-money-out so nothing downstream has to know."""
    rows = reconciliation.parse_statement_csv(
        _csv("2026-06-15,SM SUPERMARKET,500.00"), charges_are_negative=False
    )
    assert rows[0]["amount"] == pytest.approx(-500.0)


def test_column_headers_are_matched_flexibly(reconciliation):
    text = ("Transaction Date,Particulars,Transaction Amount\n"
            "15/06/2026,JOLLIBEE CUBAO,-250.00")
    rows = reconciliation.parse_statement_csv(text)
    assert rows[0]["posted_date"] == "2026-06-15"
    assert rows[0]["amount"] == pytest.approx(-250.0)


def test_an_unreadable_row_is_kept_with_an_error(reconciliation):
    """Dropping it would remove a charge from the report entirely — the one outcome
    worse than reporting it as unknown."""
    rows = reconciliation.parse_statement_csv(
        _csv("2026-06-15,SM SUPERMARKET,-500.00", "2026-06-16,MYSTERY,PENDING")
    )
    assert len(rows) == 2
    assert rows[1]["amount"] is None
    assert rows[1]["error"]


def test_an_empty_file_is_rejected(reconciliation):
    with pytest.raises(reconciliation.ReconciliationError):
        reconciliation.parse_statement_csv("")


def test_a_file_without_a_description_column_is_rejected(reconciliation):
    with pytest.raises(reconciliation.ReconciliationError, match="description"):
        reconciliation.parse_statement_csv("Date,Amount\n2026-06-15,-500.00")


def test_a_file_without_any_amount_column_is_rejected(reconciliation):
    with pytest.raises(reconciliation.ReconciliationError, match="amount"):
        reconciliation.parse_statement_csv("Date,Description\n2026-06-15,SM")


def test_a_header_only_file_is_rejected(reconciliation):
    with pytest.raises(reconciliation.ReconciliationError):
        reconciliation.parse_statement_csv("Posting Date,Description,Amount")


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #
def test_importing_a_statement_persists_its_lines(finance_fixture, reconciliation):
    result = reconciliation.import_statement(
        _csv("2026-06-15,SM SUPERMARKET,-500.00", "2026-06-16,JOLLIBEE,-250.00"),
        "june.csv",
    )
    assert result["rows"] == 2
    assert len(reconciliation.statement_lines(result["statement_id"])) == 2


def test_the_statement_period_is_derived_from_its_rows(finance_fixture, reconciliation):
    result = reconciliation.import_statement(
        _csv("2026-06-20,LATE,-100.00", "2026-06-01,EARLY,-100.00"), "june.csv"
    )
    assert result["period_start"] == "2026-06-01"
    assert result["period_end"] == "2026-06-20"


def test_a_statement_can_be_listed_and_fetched(finance_fixture, reconciliation):
    statement_id = reconciliation.import_statement(
        _csv("2026-06-15,SM,-500.00"), "june.csv")["statement_id"]
    assert reconciliation.get_statement(statement_id)["source_file"] == "june.csv"
    assert any(s["id"] == statement_id for s in reconciliation.list_statements())


def test_deleting_a_statement_removes_its_lines_and_matches(
    finance_fixture, reconciliation, make_receipt
):
    make_receipt("SM Supermarket", "2026-06-15", 500.0)
    statement_id = reconciliation.import_statement(
        _csv("2026-06-16,SM SUPERMARKET,-500.00"), "june.csv")["statement_id"]
    reconciliation.match_statement(statement_id)

    assert reconciliation.delete_statement(statement_id) is True
    assert reconciliation.statement_lines(statement_id) == []
    assert reconciliation.get_statement(statement_id) is None


def test_deleting_an_unknown_statement_reports_failure(finance_fixture, reconciliation):
    assert reconciliation.delete_statement(999_999) is False


# --------------------------------------------------------------------------- #
# Matching — the core of the proof point
# --------------------------------------------------------------------------- #
def test_a_receipt_matches_its_charge(finance_fixture, reconciliation, make_receipt):
    receipt_id = make_receipt("SM Supermarket", "2026-06-15", 500.0)
    statement_id = reconciliation.import_statement(
        _csv("2026-06-16,POS PURCHASE SM SUPERMARKET MAKATI,-500.00"), "june.csv"
    )["statement_id"]

    result = reconciliation.match_statement(statement_id)
    assert len(result["matches"]) == 1
    assert result["matches"][0]["receipt_id"] == receipt_id
    assert result["matches"][0]["status"] == "matched"


def test_settlement_lag_is_tolerated(finance_fixture, reconciliation, make_receipt):
    """A card charge posts days after the purchase. Treating that as a mismatch would
    make almost every card receipt a false discrepancy."""
    make_receipt("SM Supermarket", "2026-06-15", 500.0)
    statement_id = reconciliation.import_statement(
        _csv("2026-06-19,SM SUPERMARKET,-500.00"), "june.csv")["statement_id"]
    assert reconciliation.match_statement(statement_id)["matches"][0]["status"] == "matched"


def test_a_charge_posting_long_after_the_receipt_is_not_a_plain_match(
    finance_fixture, reconciliation, make_receipt
):
    """Same amount six weeks later is a different purchase, not a late settlement."""
    make_receipt("SM Supermarket", "2026-06-15", 500.0)
    statement_id = reconciliation.import_statement(
        _csv("2026-07-30,SM SUPERMARKET,-500.00"), "june.csv")["statement_id"]
    matches = reconciliation.match_statement(statement_id)["matches"]
    assert matches[0]["status"] == "date_outside_window"


def test_a_charge_is_matched_by_only_one_receipt(
    finance_fixture, reconciliation, make_receipt
):
    """One-to-one assignment. If one receipt could explain both identical charges, a
    duplicate billing would disappear from the report."""
    make_receipt("SM Supermarket", "2026-06-15", 500.0)
    statement_id = reconciliation.import_statement(
        _csv("2026-06-16,SM SUPERMARKET,-500.00", "2026-06-16,SM SUPERMARKET,-500.00"),
        "june.csv",
    )["statement_id"]

    result = reconciliation.match_statement(statement_id)
    assert len(result["matches"]) == 1
    assert len(result["matched_line_ids"]) == 1


def test_two_receipts_match_two_identical_charges(
    finance_fixture, reconciliation, make_receipt
):
    """The legitimate case — two real purchases — must still fully reconcile."""
    make_receipt("SM Supermarket", "2026-06-15", 500.0)
    make_receipt("SM Supermarket", "2026-06-15", 500.0)
    statement_id = reconciliation.import_statement(
        _csv("2026-06-16,SM SUPERMARKET,-500.00", "2026-06-16,SM SUPERMARKET,-500.00"),
        "june.csv",
    )["statement_id"]
    assert len(reconciliation.match_statement(statement_id)["matches"]) == 2


def test_a_refund_is_never_matched_to_a_receipt(
    finance_fixture, reconciliation, make_receipt
):
    """A credit is not a purchase. Matching it to a receipt would cancel out a real
    charge and hide it."""
    make_receipt("SM Supermarket", "2026-06-15", 500.0)
    statement_id = reconciliation.import_statement(
        _csv("2026-06-16,SM SUPERMARKET REFUND,500.00"), "june.csv")["statement_id"]
    assert reconciliation.match_statement(statement_id)["matches"] == []


def test_an_amount_discrepancy_is_reported_as_one_problem_not_two(
    finance_fixture, reconciliation, make_receipt
):
    """A ₱500 receipt against a ₱550 charge is an overcharge, not an unrelated
    missing receipt plus an unrelated unmatched receipt. This pairing is the whole
    reason the matcher has a second pass."""
    make_receipt("SM Supermarket", "2026-06-15", 500.0)
    statement_id = reconciliation.import_statement(
        _csv("2026-06-16,SM SUPERMARKET MAKATI,-550.00"), "june.csv")["statement_id"]

    matches = reconciliation.match_statement(statement_id)["matches"]
    assert len(matches) == 1
    assert matches[0]["status"] == "amount_mismatch"
    assert matches[0]["amount_delta"] == pytest.approx(-50.0)  # receipt is 50 less


def test_a_discrepancy_pairing_requires_the_merchant_to_agree(
    finance_fixture, reconciliation, make_receipt
):
    """Without this, any two roughly-similar amounts in the same week would be paired
    and reported as an overcharge between unrelated purchases."""
    make_receipt("Jollibee", "2026-06-15", 500.0)
    statement_id = reconciliation.import_statement(
        _csv("2026-06-16,SHELL GAS STATION,-550.00"), "june.csv")["statement_id"]
    assert reconciliation.match_statement(statement_id)["matches"] == []


def test_a_wildly_different_amount_is_not_a_discrepancy_pairing(
    finance_fixture, reconciliation, make_receipt
):
    make_receipt("SM Supermarket", "2026-06-15", 500.0)
    statement_id = reconciliation.import_statement(
        _csv("2026-06-16,SM SUPERMARKET,-9000.00"), "june.csv")["statement_id"]
    assert reconciliation.match_statement(statement_id)["matches"] == []


def test_an_exact_match_outranks_a_discrepancy_pairing(
    finance_fixture, reconciliation, make_receipt
):
    """Given both options, the exact-amount receipt must claim the charge."""
    exact = make_receipt("SM Supermarket", "2026-06-15", 500.0)
    make_receipt("SM Supermarket", "2026-06-15", 520.0)
    statement_id = reconciliation.import_statement(
        _csv("2026-06-16,SM SUPERMARKET,-500.00"), "june.csv")["statement_id"]

    matches = reconciliation.match_statement(statement_id)["matches"]
    assert matches[0]["receipt_id"] == exact
    assert matches[0]["status"] == "matched"


def test_matching_can_be_scoped_to_specific_receipts(
    finance_fixture, reconciliation, make_receipt
):
    make_receipt("SM Supermarket", "2026-06-15", 500.0)
    allowed = make_receipt("SM Supermarket", "2026-06-15", 500.0)
    statement_id = reconciliation.import_statement(
        _csv("2026-06-16,SM SUPERMARKET,-500.00"), "june.csv")["statement_id"]

    result = reconciliation.match_statement(statement_id, receipt_ids=[allowed])
    assert result["matches"][0]["receipt_id"] == allowed


def test_matches_are_persisted_and_replaced_on_rerun(
    finance_fixture, reconciliation, make_receipt, core
):
    """Re-running must not accumulate duplicate match rows."""
    make_receipt("SM Supermarket", "2026-06-15", 500.0)
    statement_id = reconciliation.import_statement(
        _csv("2026-06-16,SM SUPERMARKET,-500.00"), "june.csv")["statement_id"]

    reconciliation.match_statement(statement_id)
    reconciliation.match_statement(statement_id)
    with core._connect() as con:
        stored = con.execute("SELECT COUNT(*) FROM statement_matches").fetchone()[0]
    assert stored == 1


def test_matching_an_unknown_statement_is_rejected(finance_fixture, reconciliation):
    with pytest.raises(reconciliation.ReconciliationError):
        reconciliation.match_statement(999_999)


def test_the_matcher_can_run_without_persisting(
    finance_fixture, reconciliation, make_receipt, core
):
    make_receipt("SM Supermarket", "2026-06-15", 500.0)
    statement_id = reconciliation.import_statement(
        _csv("2026-06-16,SM SUPERMARKET,-500.00"), "june.csv")["statement_id"]

    reconciliation.match_statement(statement_id, persist=False)
    with core._connect() as con:
        assert con.execute("SELECT COUNT(*) FROM statement_matches").fetchone()[0] == 0


def test_thresholds_are_caller_overridable(
    finance_fixture, reconciliation, make_receipt
):
    """Every threshold is a documented parameter proposed by the team, not a constant
    baked into the algorithm — the team must be able to defend and change them."""
    make_receipt("SM Supermarket", "2026-06-15", 500.0)
    statement_id = reconciliation.import_statement(
        _csv("2026-07-30,SM SUPERMARKET,-500.00"), "june.csv")["statement_id"]

    widened = reconciliation.match_statement(statement_id, max_posting_lag_days=60)
    assert widened["matches"][0]["status"] == "matched"


# --------------------------------------------------------------------------- #
# Duplicate detection
# --------------------------------------------------------------------------- #
def test_duplicate_charges_are_detected(finance_fixture, reconciliation):
    statement_id = reconciliation.import_statement(
        _csv("2026-06-16,SM SUPERMARKET,-500.00", "2026-06-16,SM SUPERMARKET,-500.00"),
        "june.csv",
    )["statement_id"]
    duplicates = reconciliation.find_duplicate_charges(statement_id)
    assert len(duplicates) == 1
    assert duplicates[0]["count"] == 2


def test_charges_on_different_days_are_not_duplicates(finance_fixture, reconciliation):
    statement_id = reconciliation.import_statement(
        _csv("2026-06-16,SM SUPERMARKET,-500.00", "2026-06-17,SM SUPERMARKET,-500.00"),
        "june.csv",
    )["statement_id"]
    assert reconciliation.find_duplicate_charges(statement_id) == []


def test_different_amounts_are_not_duplicates(finance_fixture, reconciliation):
    statement_id = reconciliation.import_statement(
        _csv("2026-06-16,SM SUPERMARKET,-500.00", "2026-06-16,SM SUPERMARKET,-501.00"),
        "june.csv",
    )["statement_id"]
    assert reconciliation.find_duplicate_charges(statement_id) == []


def test_duplicate_receipts_are_detected(finance_fixture, reconciliation, make_receipt):
    """The same paper receipt photographed and uploaded twice."""
    first = make_receipt("SM Supermarket", "2026-06-15", 500.0)
    second = make_receipt("SM Supermarket", "2026-06-15", 500.0)
    duplicates = reconciliation.find_duplicate_receipts([first, second])
    assert len(duplicates) == 1
    assert sorted(duplicates[0]["receipt_ids"]) == sorted([first, second])


def test_duplicate_detection_survives_merchant_name_variation(
    finance_fixture, reconciliation, make_receipt
):
    first = make_receipt("SM Supermarket", "2026-06-15", 500.0)
    second = make_receipt("SM SUPERMARKET INC.", "2026-06-15", 500.0)
    assert len(reconciliation.find_duplicate_receipts([first, second])) == 1


# --------------------------------------------------------------------------- #
# The discrepancy report
# --------------------------------------------------------------------------- #
@pytest.fixture
def scenario(finance_fixture, reconciliation, make_receipt):
    """One statement exercising every category the report must separate."""
    receipts = {
        "matched": make_receipt("SM Supermarket", "2026-06-15", 500.0),
        "overcharged": make_receipt("Jollibee", "2026-06-17", 250.0),
        "no_charge": make_receipt("Shell", "2026-06-20", 1_000.0),
    }
    statement_id = reconciliation.import_statement(
        _csv(
            "2026-06-16,POS PURCHASE SM SUPERMARKET MAKATI,-500.00",  # clean match
            "2026-06-18,JOLLIBEE CUBAO,-275.00",                      # overcharged by 25
            "2026-06-19,MERALCO BILL PAYMENT,-3200.00",               # no receipt
            "2026-06-21,SM SUPERMARKET REFUND,320.00",                # refund
            "2026-06-22,UNKNOWN MERCHANT,PENDING",                    # unreadable
        ),
        "june.csv",
    )["statement_id"]
    return {"statement_id": statement_id, "receipts": receipts}


def test_the_report_separates_every_category(reconciliation, scenario):
    report = reconciliation.discrepancy_report(scenario["statement_id"])
    assert report["counts"]["matched"] == 1
    assert report["counts"]["amount_mismatch"] == 1
    assert report["counts"]["missing_receipt"] == 1
    assert report["counts"]["refunds"] == 1
    assert report["counts"]["unreadable_lines"] == 1


def test_every_charge_is_accounted_for_in_exactly_one_bucket(reconciliation, scenario):
    """The invariant that stops a category silently swallowing rows: a charge the
    report loses is money the user never learns about."""
    report = reconciliation.discrepancy_report(scenario["statement_id"])
    assert report["accounted_for"] is True


def test_the_report_names_the_unexplained_total(reconciliation, scenario):
    """The number a user actually acts on: money charged with nothing to show for it."""
    report = reconciliation.discrepancy_report(scenario["statement_id"])
    assert report["totals"]["unexplained_total"] == pytest.approx(3_200.0)


def test_the_report_quantifies_the_amount_discrepancy(reconciliation, scenario):
    report = reconciliation.discrepancy_report(scenario["statement_id"])
    assert report["totals"]["amount_discrepancy_total"] == pytest.approx(25.0)


def test_a_receipt_with_no_charge_is_reported(reconciliation, scenario):
    """The other direction: a receipt that never appeared on the statement. Could be a
    cash purchase, could be a charge that has not posted yet — either way the user
    needs to see it."""
    report = reconciliation.discrepancy_report(scenario["statement_id"])
    unmatched = {r["receipt_id"] for r in report["unmatched_receipts"]}
    assert scenario["receipts"]["no_charge"] in unmatched


def test_the_matched_receipt_is_not_reported_as_unmatched(reconciliation, scenario):
    report = reconciliation.discrepancy_report(scenario["statement_id"])
    unmatched = {r["receipt_id"] for r in report["unmatched_receipts"]}
    assert scenario["receipts"]["matched"] not in unmatched


def test_the_report_flags_itself_for_review_when_anything_is_wrong(
    reconciliation, scenario
):
    assert reconciliation.discrepancy_report(scenario["statement_id"])["needs_review"]


def test_a_fully_reconciled_statement_does_not_ask_for_review(
    finance_fixture, reconciliation, make_receipt
):
    """False-review rate matters here exactly as it does for receipts: a clean
    statement that still demands attention trains the user to ignore the report."""
    receipt_id = make_receipt("SM Supermarket", "2026-06-15", 500.0)
    statement_id = reconciliation.import_statement(
        _csv("2026-06-16,SM SUPERMARKET,-500.00"), "clean.csv")["statement_id"]

    # Scoped to this receipt so the fixture's own seeded receipts (which have no
    # charges on this statement) do not muddy the assertion.
    report = reconciliation.discrepancy_report(statement_id, receipt_ids=[receipt_id])
    assert report["counts"]["missing_receipt"] == 0
    assert report["counts"]["amount_mismatch"] == 0
    assert report["counts"]["unmatched_receipts"] == 0
    assert report["needs_review"] is False


def test_the_report_carries_the_matched_pairs_with_their_evidence(
    reconciliation, scenario
):
    """A user disputing a match must be able to see why the two rows were paired."""
    report = reconciliation.discrepancy_report(scenario["statement_id"])
    match = report["matched"][0]
    assert match["charge_amount"] == pytest.approx(500.0)
    assert match["receipt_total"] == pytest.approx(500.0)
    assert match["date_delta_days"] == 1
    assert match["merchant_similarity"] > 0


def test_reporting_on_an_unknown_statement_is_rejected(finance_fixture, reconciliation):
    with pytest.raises(reconciliation.ReconciliationError):
        reconciliation.discrepancy_report(999_999)


def test_the_report_renders_as_readable_text(reconciliation, scenario):
    text = reconciliation.format_discrepancy_report(
        reconciliation.discrepancy_report(scenario["statement_id"])
    )
    assert "Amount discrepancies:" in text
    assert "Charges with no receipt:" in text
    assert "MERALCO" in text
    assert "human review" in text


def test_the_rendered_report_does_not_claim_to_have_corrected_anything(
    reconciliation, scenario
):
    """Duplicates and discrepancies are candidates for review. The tool must not
    present itself as having fixed the user's books."""
    text = reconciliation.format_discrepancy_report(
        reconciliation.discrepancy_report(scenario["statement_id"])
    )
    assert "candidates for human review, not corrections" in text


# --------------------------------------------------------------------------- #
# The two kinds of reconciliation stay distinct
# --------------------------------------------------------------------------- #
def test_statement_reconciliation_does_not_touch_receipt_internal_arithmetic(
    finance_fixture, reconciliation, core
):
    """A receipt whose own line items do not add up is flagged by
    `extraction.reconcile`. That is a *different* defect from being mischarged, and
    this module must not silently absorb it: an internally inconsistent receipt can
    still match its charge exactly, and both facts must remain visible."""
    inconsistent = core.ReceiptData(
        vendor_name="SM Supermarket", receipt_date="2026-06-15", total_amount=500.0,
        currency="PHP",
        items=[core.LineItem(description="Rice", quantity=1, unit_price=100.0,
                             amount=100.0)],
    )
    assert core.needs_disambiguation(inconsistent)  # internally inconsistent
    receipt_id = core.save_receipt(inconsistent, "bad.jpg", flagged=True, index=False)

    statement_id = reconciliation.import_statement(
        _csv("2026-06-16,SM SUPERMARKET,-500.00"), "june.csv")["statement_id"]
    result = reconciliation.match_statement(statement_id, receipt_ids=[receipt_id])

    assert result["matches"][0]["status"] == "matched"
    assert core.get_receipt(receipt_id)["flagged"] == 1
