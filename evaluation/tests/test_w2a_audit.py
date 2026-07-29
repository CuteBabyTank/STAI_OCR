"""
W2-A — the post-extraction arithmetic audit (`extraction.audit_receipt`).

What this covers
----------------
`audit_receipt` runs once per receipt, immediately after the vision model's output
has been cleaned and schema-validated (`core._run_vision_model`). It is a pure
function of the extracted values — no model, no database — so unlike the extraction
accuracy metrics it gates, **these are real correctness tests, not stand-ins**: they
measure exactly the behaviour a user will get.

The headline check is line items against the printed SUBTOTAL. `reconcile()` already
compared items to the TOTAL, but that check passes on a receipt whose errors cancel:
drop a ₱120 line and invent a ₱120 discount and the total still works out. The
subtotal is the receipt's own claim about what its lines add up to, so comparing
against it is what catches a misread line.

What is NOT measured here: whether the model reads receipts correctly. The audit
tells you a receipt does not add up; it cannot tell you which number is wrong, and
it deliberately corrects nothing (the pipeline's rule is "transcribe, then repair,
never compute").
"""

from __future__ import annotations

import pytest


@pytest.fixture
def audit():
    from extraction import audit_receipt

    return audit_receipt


def _codes(findings: list[dict]) -> set[str]:
    return {f["code"] for f in findings}


def _by_code(findings: list[dict], code: str) -> dict:
    return next(f for f in findings if f["code"] == code)


def _receipt(**overrides) -> dict:
    """A receipt whose arithmetic is fully consistent. Each test breaks exactly one
    thing, so any finding is attributable to that change."""
    base = {
        "vendor_name": "Test Mart",
        "currency": "PHP",
        "items": [
            {"description": "Rice 5kg", "quantity": 1, "unit_price": 300.0, "amount": 300.0},
            {"description": "Cooking oil", "quantity": 2, "unit_price": 100.0, "amount": 200.0},
        ],
        "subtotal": 500.0,
        "vatable_sales": 500.0,
        "vat_amount": 53.57,          # VAT-inclusive: 500 - 500/1.12
        "discount": 0.0,
        "total_amount": 500.0,
        "cash": 1000.0,
        "change": 500.0,
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------- #
# The baseline: a clean receipt must stay silent
# --------------------------------------------------------------------------- #
def test_a_consistent_receipt_produces_no_findings(audit):
    """A false warning on every receipt trains the user to ignore all of them."""
    assert audit(_receipt()) == []


def test_a_receipt_with_no_subtotal_is_not_reported_as_a_mismatch(audit):
    """Plenty of receipts never print a subtotal. An absent figure is not a failed
    check — flagging it would put a warning on a large share of real receipts."""
    findings = audit(_receipt(subtotal=None))
    assert "items_vs_subtotal" not in _codes(findings)


def test_a_receipt_with_no_items_is_not_reported_as_a_mismatch(audit):
    findings = audit(_receipt(items=[]))
    assert "items_vs_subtotal" not in _codes(findings)


def test_an_empty_receipt_audits_cleanly(audit):
    """The audit must never raise on a sparse extraction — it runs on EVERY receipt,
    including the ones the model barely read, and an exception there would take down
    the extraction that produced it."""
    assert audit({}) == []
    assert audit({"items": [], "subtotal": None, "total_amount": None}) == []


# --------------------------------------------------------------------------- #
# The headline check: line items vs the printed subtotal
# --------------------------------------------------------------------------- #
def test_items_that_do_not_reach_the_subtotal_are_flagged(audit):
    """The defining case: the model missed a line. Items sum to 500 but the receipt
    says the lines add to 620, so ₱120 of the receipt was never read."""
    findings = audit(_receipt(subtotal=620.0, total_amount=620.0))
    f = _by_code(findings, "items_vs_subtotal")
    assert f["severity"] == "error"
    assert f["expected"] == 620.0
    assert f["found"] == 500.0
    assert f["difference"] == -120.0
    assert "620.00" in f["message"] and "500.00" in f["message"]


def test_items_that_exceed_the_subtotal_are_flagged(audit):
    """The opposite error — a line counted twice — is as much a defect as a missing
    one, and an asymmetric check would silently accept every duplicate."""
    findings = audit(_receipt(subtotal=380.0, total_amount=380.0))
    f = _by_code(findings, "items_vs_subtotal")
    assert f["found"] == 500.0 and f["expected"] == 380.0
    assert f["difference"] == 120.0


def test_the_subtotal_check_survives_a_cancelling_total(audit):
    """The reason this check exists. A ₱120 line is missing AND a ₱120 discount was
    invented, so items reconcile to the total perfectly and `reconcile()` stays
    silent. Only the subtotal comparison catches it."""
    from extraction import reconcile

    data = _receipt(subtotal=620.0, discount=120.0, total_amount=500.0)
    assert reconcile(data) == [], "precondition: the total-based check passes here"
    assert "items_vs_subtotal" in _codes(audit(data))


def test_rounding_noise_does_not_trip_the_subtotal_check(audit):
    """Per-line rounding on a long receipt is normal. A tolerance that fires on a
    50-centavo gap would flag most real receipts."""
    assert "items_vs_subtotal" not in _codes(audit(_receipt(subtotal=500.4)))


def test_the_tolerance_scales_with_the_receipt(audit):
    """Absolute floor of ₱1 with a 2% band: a ₱3 gap is noise on a ₱10,000 receipt
    and a real error on a ₱100 one. Asserted on both sides of each boundary."""
    small = _receipt(
        items=[{"description": "x", "quantity": 1, "unit_price": 100.0, "amount": 100.0}],
        subtotal=103.0, vatable_sales=None, vat_amount=None,
        total_amount=103.0, cash=None, change=None,
    )
    assert "items_vs_subtotal" in _codes(audit(small))

    big = _receipt(
        items=[{"description": "x", "quantity": 1, "unit_price": 10000.0, "amount": 10000.0}],
        subtotal=10003.0, vatable_sales=None, vat_amount=None,
        total_amount=10003.0, cash=None, change=None,
    )
    assert "items_vs_subtotal" not in _codes(audit(big))


def test_an_unreadable_line_amount_does_not_fabricate_a_mismatch(audit):
    """A line whose amount came back None must not be counted as ₱0 — that would
    turn every partly-unreadable receipt into a subtotal error."""
    data = _receipt(
        items=[
            {"description": "Rice", "quantity": 1, "unit_price": 300.0, "amount": 300.0},
            {"description": "Smudged", "quantity": 1, "unit_price": None, "amount": None},
        ],
        subtotal=300.0, vatable_sales=300.0, vat_amount=32.14,
        total_amount=300.0, cash=300.0, change=0.0,
    )
    assert "items_vs_subtotal" not in _codes(audit(data))


# --------------------------------------------------------------------------- #
# The other checks
# --------------------------------------------------------------------------- #
def test_the_total_check_is_still_reported(audit):
    """`reconcile()` remains the source of truth for items-vs-total; the audit must
    surface it rather than reimplement it, or the two will drift."""
    findings = audit(_receipt(subtotal=500.0, total_amount=900.0))
    assert "items_vs_total" in _codes(findings)
    assert _by_code(findings, "items_vs_total")["severity"] == "error"


def test_a_wrong_vat_figure_is_a_warning_not_an_error(audit):
    """VAT conventions vary and the figure is often just absent or odd; it should be
    visible without holding up the receipt."""
    f = _by_code(audit(_receipt(vat_amount=200.0)), "vat_rate")
    assert f["severity"] == "warning"


@pytest.mark.parametrize("vat", [53.57, 60.0])
def test_both_vat_conventions_are_accepted(audit, vat):
    """VAT-inclusive (500 - 500/1.12 = 53.57) and VAT-exclusive (500 x 12% = 60)
    are both legitimate. Flagging one would warn on every receipt of that kind."""
    assert "vat_rate" not in _codes(audit(_receipt(vat_amount=vat)))


def test_cash_that_does_not_cover_the_total_is_flagged(audit):
    f = _by_code(audit(_receipt(cash=1000.0, change=600.0)), "payment_vs_total")
    assert f["severity"] == "warning"
    assert f["expected"] == 500.0 and f["found"] == 400.0


def test_a_line_whose_quantity_times_price_is_wrong_is_flagged(audit):
    """Points at the ONE bad line by name, which is the difference between "check
    this receipt" and "check this line"."""
    data = _receipt(items=[
        {"description": "Rice 5kg", "quantity": 1, "unit_price": 300.0, "amount": 300.0},
        {"description": "Cooking oil", "quantity": 2, "unit_price": 100.0, "amount": 200.0},
        {"description": "Eggs", "quantity": 3, "unit_price": 50.0, "amount": 100.0},
    ], subtotal=600.0, vatable_sales=None, vat_amount=None,
       total_amount=600.0, cash=None, change=None)
    f = _by_code(audit(data), "line_item_math")
    assert "Eggs" in f["message"]
    assert f["expected"] == 150.0 and f["found"] == 100.0


def test_a_negative_total_is_an_error(audit):
    """Not a tolerance question: a minus sign or a refund line was read as a
    purchase, and the ledger would take money the user never spent."""
    f = _by_code(audit(_receipt(total_amount=-500.0)), "negative_total")
    assert f["severity"] == "error"


def test_a_sales_breakdown_that_misses_the_subtotal_is_a_warning(audit):
    f = _by_code(
        audit(_receipt(vatable_sales=200.0, vat_amount=None)),
        "sales_breakdown_vs_subtotal",
    )
    assert f["severity"] == "warning"


def test_a_discount_is_allowed_between_subtotal_and_total(audit):
    """A discounted receipt is the normal case, not a discrepancy."""
    data = _receipt(subtotal=500.0, discount=50.0, total_amount=450.0,
                    cash=500.0, change=50.0)
    assert "subtotal_vs_total" not in _codes(audit(data))


# --------------------------------------------------------------------------- #
# Shape and formatting
# --------------------------------------------------------------------------- #
def test_every_finding_carries_the_numbers_not_just_prose(audit):
    """The findings feed the API and UI and should feed a future eval that counts
    failures by code. A bag of sentences could do none of that."""
    for f in audit(_receipt(subtotal=620.0, total_amount=620.0)):
        assert set(f) == {"code", "severity", "message", "expected", "found", "difference"}
        assert f["severity"] in ("error", "warning")
        assert f["message"].strip()


def test_findings_are_reported_in_the_receipts_own_currency(audit):
    """A dollar receipt described in pesos is a wrong number on screen."""
    data = _receipt(currency="USD", subtotal=620.0, total_amount=620.0)
    assert "$" in _by_code(audit(data), "items_vs_subtotal")["message"]


def test_audit_messages_filters_by_severity(audit):
    from extraction import audit_messages

    findings = audit(_receipt(subtotal=620.0, total_amount=620.0, vat_amount=200.0))
    errors = audit_messages(findings, severity="error")
    warnings = audit_messages(findings, severity="warning")
    assert errors and warnings
    assert len(audit_messages(findings)) == len(errors) + len(warnings)


# --------------------------------------------------------------------------- #
# The wiring: it must actually run, on every extraction path
# --------------------------------------------------------------------------- #
def test_a_subtotal_mismatch_sends_the_receipt_for_human_review(core):
    """The point of the check. An error finding has to reach `needs_disambiguation`,
    or the audit is decoration."""
    data = core.ReceiptData(**{
        "vendor_name": "Test Mart", "currency": "PHP",
        "items": [core.LineItem(description="Rice", quantity=1,
                                unit_price=300.0, amount=300.0)],
        "subtotal": 620.0, "total_amount": 620.0,
    })
    reasons = core.needs_disambiguation(data)
    assert any("subtotal" in r.lower() for r in reasons)


def test_a_warning_alone_does_not_send_a_receipt_for_review(core):
    """Warnings are shown, not blocking. If an odd VAT figure forced review, the
    review queue would fill with receipts that are fine."""
    data = core.ReceiptData(**{
        "vendor_name": "Test Mart", "currency": "PHP",
        "items": [core.LineItem(description="Rice", quantity=1,
                                unit_price=500.0, amount=500.0)],
        "subtotal": 500.0, "vatable_sales": 500.0, "vat_amount": 200.0,
        "total_amount": 500.0,
    })
    assert core.needs_disambiguation(data) == []
    assert "vat_rate" in {f["code"] for f in core.audit_extraction(data)}


def test_the_audit_runs_on_the_shared_extraction_path(core, monkeypatch):
    """`_run_vision_model` is the single hot path both the single-file and batch
    entry points go through. Verifying the audit here is what guarantees no upload
    route can skip it."""
    import json as _json

    payload = {
        "vendor_name": "Test Mart", "currency": "PHP",
        "items": [{"description": "Rice", "quantity": 1,
                   "unit_price": 300.0, "amount": 300.0}],
        "subtotal": 620.0, "total_amount": 620.0,
    }
    monkeypatch.setattr(core, "ollama", object())
    monkeypatch.setattr(core, "_chat", lambda **kw: {
        "message": {"content": _json.dumps(payload)}, "done_reason": "stop",
    })

    _data, reasons, _conf, _resp, audit = core._run_vision_model(b"fake", "m")
    assert "items_vs_subtotal" in {f["code"] for f in audit}
    assert any("subtotal" in r.lower() for r in reasons)


def test_a_batch_result_carries_its_audit(core, finance_fixture, monkeypatch):
    """Batch is the 1000-page path; a finding that only appears on the single-file
    route would be invisible for bulk imports."""
    data = core.ReceiptData(
        vendor_name="Test Mart", currency="PHP",
        items=[core.LineItem(description="Rice", quantity=1,
                             unit_price=300.0, amount=300.0)],
        subtotal=620.0, total_amount=620.0,
    )
    findings = core.audit_extraction(data)
    monkeypatch.setattr(core, "_run_vision_model",
                        lambda *a, **k: (data, ["r"], {"overall": 0.9}, {}, findings))

    results = core.extract_batch([(b"\xff\xd8\xff-fake", "image/jpeg", "r.jpg")],
                                 concurrency=1)
    # Asserted first: the batch path swallows exceptions into `error`, so without
    # this a persistence failure would surface as a confusing empty audit.
    assert results[0]["error"] is None
    assert "items_vs_subtotal" in {f["code"] for f in results[0]["audit"]}


def test_a_failed_page_still_reports_an_audit_key(core, finance_fixture):
    """Key parity: a consumer iterating batch results must not have to test for the
    field's existence before reading it."""
    results = core.extract_batch([(b"not an image", "image/jpeg", "bad.jpg")],
                                 concurrency=1)
    assert results[0]["error"] is not None
    assert results[0]["audit"] == []
