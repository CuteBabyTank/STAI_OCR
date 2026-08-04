"""
W2-A — the second-pass recovery seam (`core._recover_missing_fields`).

What this covers
----------------
One prompt asking for twenty fields is where the empty fields come from: a small
vision model spends its attention on the item block and the total and quietly
answers null for the TIN, the address and the receipt number without ever looking
for them. So when the first read leaves those empty — or when
`assess_item_coverage` says the item block was not read end to end — the pipeline
asks the SAME model about the SAME image a second time, for only the fields that
are missing, with the place each one is printed named in the prompt.

The rule that makes this safe is that the second pass may only ADD. These tests
pin exactly that: a recovered value lands only where the field is still null, a
re-read item list is adopted only when it beats the first one against the
receipt's own printed figures, and every failure mode of the extra call (a dead
endpoint, prose instead of JSON, a model that answers null again) leaves the
first-pass extraction untouched.

What is NOT measured here: whether the model's second answer is *correct*. That
is extraction accuracy, which no unit test can stand in for. What is measured is
that a wrong second answer cannot corrupt a right first one.
"""

from __future__ import annotations

import json as _json

import pytest


def _stub_chat(core, monkeypatch, responses):
    """Point core._chat at a scripted list of model replies and record the prompts.

    Returns the list the prompts land in, so a test can assert on what was asked
    as well as on what came back."""
    prompts: list[str] = []
    queue = list(responses)

    def _chat(**kwargs):
        prompts.append(kwargs["messages"][0]["content"])
        payload = queue.pop(0) if queue else {}
        content = payload if isinstance(payload, str) else _json.dumps(payload)
        return {"message": {"content": content}, "done_reason": "stop"}

    monkeypatch.setattr(core, "ollama", object())
    monkeypatch.setattr(core, "_chat", _chat)
    return prompts


def _first_pass(**overrides) -> dict:
    """A receipt read whose item block checks out but whose header is empty."""
    payload = {
        "vendor_name": "Pepper Lunch",
        "vendor_tin": None,
        "vendor_address": None,
        "receipt_number": None,
        "receipt_date_raw": "14/06/26",
        "items": [{"description": "Ramen", "quantity": 1,
                   "unit_price": 545.0, "amount": 545.0}],
        "items_printed_count": 1,
        "items_section_verified": True,
        "subtotal": 545.0,
        "total_amount": 545.0,
        "currency": "PHP",
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------- #
# The pass fires on evidence, and only on evidence
# --------------------------------------------------------------------------- #
def test_a_missing_field_is_asked_for_again_and_filled(core, monkeypatch):
    prompts = _stub_chat(core, monkeypatch, [
        _first_pass(),
        {"vendor_tin": "123-456-789-000", "vendor_address": "5F SM Megamall",
         "receipt_number": "OR-4471"},
    ])
    data, _reasons, _conf, _resp, _audit = core._run_vision_model(b"fake", "m")

    assert len(prompts) == 2, "the second look must actually happen"
    assert "vendor_tin" in prompts[1] and "receipt_number" in prompts[1]
    assert data.vendor_tin == "123-456-789-000"
    assert data.vendor_address == "5F SM Megamall"
    assert data.receipt_number == "OR-4471"


def test_a_clean_read_costs_exactly_one_call(core, monkeypatch):
    """The pass must not tax the receipts that were read properly."""
    complete = _first_pass(vendor_tin="123-456-789-000",
                           vendor_address="5F SM Megamall",
                           receipt_number="OR-4471", vatable_sales=486.61,
                           vat_amount=58.39, cash=1000.0, change=455.0)
    prompts = _stub_chat(core, monkeypatch, [complete])
    core._run_vision_model(b"fake", "m")
    assert len(prompts) == 1


def test_the_second_pass_can_be_switched_off(core, monkeypatch):
    monkeypatch.setattr(core, "OCR_RECOVERY_PASS", False)
    prompts = _stub_chat(core, monkeypatch, [_first_pass()])
    core._run_vision_model(b"fake", "m")
    assert len(prompts) == 1


# --------------------------------------------------------------------------- #
# It may only ADD
# --------------------------------------------------------------------------- #
def test_a_value_read_first_time_is_never_overwritten(core, monkeypatch):
    """The whole safety property. The second answer contradicts the first on every
    field it was not asked about; none of them may move."""
    _stub_chat(core, monkeypatch, [
        _first_pass(),
        {"vendor_name": "Wrong Vendor", "subtotal": 9999.0, "total_amount": 9999.0,
         "vendor_tin": "123-456-789-000"},
    ])
    data, _r, _c, _resp, _a = core._run_vision_model(b"fake", "m")
    assert data.vendor_name == "Pepper Lunch"
    assert data.subtotal == 545.0
    assert data.total_amount == 545.0
    assert data.vendor_tin == "123-456-789-000"   # the one field that was empty


def test_a_placeholder_in_the_second_answer_is_not_a_value(core, monkeypatch):
    _stub_chat(core, monkeypatch, [
        _first_pass(),
        {"vendor_tin": "N/A", "vendor_address": "", "receipt_number": "-"},
    ])
    data, _r, _c, _resp, _a = core._run_vision_model(b"fake", "m")
    assert (data.vendor_tin, data.vendor_address, data.receipt_number) == (None,) * 3


# --------------------------------------------------------------------------- #
# Every failure mode leaves the first read intact
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("second", [
    "not json at all",                 # a model that answered with prose
    "[]",                              # valid JSON, wrong shape
    {"vendor_tin": None},              # looked again, still nothing printed
])
def test_a_failed_second_look_never_loses_the_first_read(core, monkeypatch, second):
    _stub_chat(core, monkeypatch, [_first_pass(), second])
    data, _r, _c, _resp, _a = core._run_vision_model(b"fake", "m")
    assert data.vendor_name == "Pepper Lunch"
    assert data.total_amount == 545.0
    assert data.vendor_tin is None
    assert len(data.items) == 1


def test_a_dead_endpoint_on_the_second_call_does_not_fail_the_extraction(
        core, monkeypatch):
    calls = {"n": 0}

    def _chat(**kwargs):
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("connection refused")
        return {"message": {"content": _json.dumps(_first_pass())},
                "done_reason": "stop"}

    monkeypatch.setattr(core, "ollama", object())
    monkeypatch.setattr(core, "_chat", _chat)
    data, _r, _c, _resp, _a = core._run_vision_model(b"fake", "m")
    assert data.vendor_name == "Pepper Lunch"


# --------------------------------------------------------------------------- #
# The item block
# --------------------------------------------------------------------------- #
def test_a_half_read_item_block_is_re_read_and_completed(core, monkeypatch):
    """The first read returns one ₱300 line against a printed ₱500 subtotal. The
    re-read reaches the subtotal, so it is the better list."""
    short = _first_pass(
        items=[{"description": "Rice", "quantity": 1, "unit_price": 300.0,
                "amount": 300.0}],
        items_printed_count=2, items_section_verified=False,
        subtotal=500.0, total_amount=500.0,
    )
    prompts = _stub_chat(core, monkeypatch, [short, {
        "items": [{"description": "Rice", "quantity": 1, "unit_price": 300.0,
                   "amount": 300.0},
                  {"description": "Cooking oil", "quantity": 2,
                   "unit_price": 100.0, "amount": 200.0}],
        "items_printed_count": 2, "items_section_verified": True,
    }])
    data, _r, _c, _resp, _a = core._run_vision_model(b"fake", "m")

    assert "item block" in prompts[1]
    assert [i.description for i in data.items] == ["Rice", "Cooking oil"]
    assert data.items_coverage["status"] == "complete"


def test_a_worse_re_read_of_the_item_block_is_rejected(core, monkeypatch):
    short = _first_pass(
        items=[{"description": "Rice", "quantity": 1, "unit_price": 300.0,
                "amount": 300.0}],
        items_printed_count=2, subtotal=500.0, total_amount=500.0,
    )
    _stub_chat(core, monkeypatch, [short, {
        "items": [{"description": "Something else", "amount": 42.0}],
        "items_printed_count": 1,
    }])
    data, _r, _c, _resp, _a = core._run_vision_model(b"fake", "m")
    assert [i.description for i in data.items] == ["Rice"]
    assert data.items_coverage["status"] == "incomplete"


def test_a_partially_read_item_block_is_held_for_review(core, monkeypatch):
    """The point of the coverage field: a receipt whose lines don't account for
    the money must not be auto-accepted just because it has a total."""
    short = _first_pass(items=[{"description": "Rice", "amount": 300.0}],
                        items_printed_count=6, items_section_verified=False,
                        subtotal=500.0, total_amount=500.0)
    _stub_chat(core, monkeypatch, [short, {}])
    data, reasons, _c, _resp, audit = core._run_vision_model(b"fake", "m")
    assert data.items_coverage["status"] == "incomplete"
    assert data.items_coverage["reported_count"] == 6
    assert "items_incomplete" in {f["code"] for f in audit}
    assert reasons, "a half-read item block is a reason to confirm by hand"


# --------------------------------------------------------------------------- #
# What reaches the ledger
# --------------------------------------------------------------------------- #
def test_the_date_is_stored_parsed_with_the_printed_form_beside_it(
        core, finance_fixture, monkeypatch):
    _stub_chat(core, monkeypatch, [_first_pass(), {}])
    data, _r, _c, _resp, _a = core._run_vision_model(b"fake", "m")
    assert data.receipt_date == "2026-06-14", "14/06/26 is 14 June, not 6 Jun 2014"

    receipt_id = core.save_receipt(data, "receipt.jpg", False, index=False)
    row = core.get_receipt(receipt_id)
    assert row["receipt_date"] == "2026-06-14"
    assert row["receipt_date_raw"] == "14/06/26"


def test_the_item_coverage_verdict_is_stored(core, finance_fixture, monkeypatch):
    """Stored, not just returned: a half-read receipt has to stay identifiable
    after the upload page has been closed."""
    short = _first_pass(items=[{"description": "Rice", "amount": 300.0}],
                        items_printed_count=6, subtotal=500.0, total_amount=500.0)
    _stub_chat(core, monkeypatch, [short, {}])
    data, _r, _c, _resp, _a = core._run_vision_model(b"fake", "m")

    row = core.get_receipt(core.save_receipt(data, "r.jpg", True, index=False))
    assert row["items_status"] == "incomplete"
    assert row["items_printed_count"] == 6
