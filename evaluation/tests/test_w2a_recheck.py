"""
W2-A — the check-driven re-read (`core._recheck_arithmetic`).

What this covers
----------------
The rule "if it doesn't add up, go and look again". `audit_receipt` already names
which sum failed and by how much; `extraction.RECHECK_RECIPES` turns that into an
instruction (re-read the item block / re-read these five tax figures), and the
look is given a crop of that part of the paper. After each look the receipt is
re-audited, so fixing the item block can clear the checks downstream of it without
spending another call.

The risk this design has to survive is the obvious one: a model told "these
numbers don't add up" will happily ADJUST one until they do, and an invented
figure that balances is worse than a transcribed one that doesn't — it turns a
visible problem into an invisible wrong number. Two things stand between the model
and that outcome, and both are pinned here:

  * the prompt says a receipt that genuinely doesn't balance is an acceptable
    answer, and that nudging a figure to close the gap is the worst outcome; and
  * nothing a look returns is kept unless `audit_score` — computed over the WHOLE
    audit, not just the check that triggered the look — strictly improves.

That second rule is what allows this pass to overwrite a figure the first read
transcribed, which nothing else in the pipeline may do. These tests exist to make
sure that permission stays paid for by proof.
"""

from __future__ import annotations

import json as _json

import pytest


def _stub_chat(core, monkeypatch, first, then=None):
    """core._chat answers `first` once, then `then` for every later call."""
    prompts: list[str] = []
    queue = [first]

    def _chat(**kwargs):
        prompts.append(kwargs["messages"][0]["content"])
        payload = queue.pop(0) if queue else (then if then is not None else {})
        content = payload if isinstance(payload, str) else _json.dumps(payload)
        return {"message": {"content": content}, "done_reason": "stop"}

    monkeypatch.setattr(core, "ollama", object())
    monkeypatch.setattr(core, "_chat", _chat)
    # The recovery pass is a separate mechanism with its own suite; switching it
    # off here keeps the call sequence attributable to this one.
    monkeypatch.setattr(core, "OCR_RECOVERY_PASS", False)
    return prompts


def _image(width: int = 600, height: int = 1800) -> bytes:
    from PIL import Image
    import io

    buf = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buf, format="JPEG")
    return buf.getvalue()


def _short_items() -> dict:
    """One ₱300 line against a printed ₱500 subtotal: a line was missed."""
    return {
        "vendor_name": "Test Mart", "currency": "PHP",
        "receipt_date_raw": "14/06/26", "receipt_number": "OR-1",
        "vendor_tin": "123", "vendor_address": "Manila",
        "items": [{"description": "Rice", "quantity": 1, "unit_price": 300.0,
                   "amount": 300.0}],
        "subtotal": 500.0, "total_amount": 500.0, "cash": 500.0, "change": 0.0,
    }


def _misread_vat() -> dict:
    """Pepper Lunch with its VAT misread as 5.39 instead of 58.39: every other
    figure is right, and the printed breakdown proves the tax figure is wrong
    (486.61 + 5.39 is not 545.00)."""
    return {
        "vendor_name": "Pepper Lunch", "currency": "PHP",
        "receipt_date_raw": "14/06/26", "receipt_number": "OR-2",
        "vendor_tin": "123", "vendor_address": "Manila",
        "items": [{"description": "Ramen", "quantity": 1, "unit_price": 545.0,
                   "amount": 545.0}],
        "subtotal": 545.0, "total_amount": 545.0, "vatable_sales": 486.61,
        "vat_amount": 5.39, "cash": 1000.0, "change": 455.0,
    }


def _clean() -> dict:
    """A receipt whose arithmetic is fully consistent."""
    return {
        "vendor_name": "Test Mart", "currency": "PHP",
        "receipt_date_raw": "14/06/26", "receipt_number": "OR-3",
        "vendor_tin": "123", "vendor_address": "Manila",
        "items": [{"description": "Rice", "quantity": 1, "unit_price": 300.0,
                   "amount": 300.0},
                  {"description": "Oil", "quantity": 2, "unit_price": 100.0,
                   "amount": 200.0}],
        "subtotal": 500.0, "vatable_sales": 500.0, "vat_amount": 53.57,
        "total_amount": 500.0, "cash": 1000.0, "change": 500.0,
    }


# --------------------------------------------------------------------------- #
# It fires on a failed check, and only on a failed check
# --------------------------------------------------------------------------- #
def test_a_receipt_that_adds_up_is_never_re_read(core, monkeypatch):
    prompts = _stub_chat(core, monkeypatch, _clean())
    core._run_vision_model(_image(), "m")
    assert len(prompts) == 1


def test_line_items_short_of_the_subtotal_are_read_again(core, monkeypatch):
    prompts = _stub_chat(core, monkeypatch, _short_items(), then={
        "items": [{"description": "Rice", "quantity": 1, "unit_price": 300.0,
                   "amount": 300.0},
                  {"description": "Cooking oil", "quantity": 2,
                   "unit_price": 100.0, "amount": 200.0}],
    })
    data, _r, _c, _resp, audit = core._run_vision_model(_image(), "m")

    assert len(prompts) > 1, "a list that doesn't reach the subtotal must be re-read"
    assert "item block" in prompts[1]
    assert [i.description for i in data.items] == ["Rice", "Cooking oil"]
    assert "items_vs_subtotal" not in {f["code"] for f in audit}


def test_the_item_look_uses_a_different_framing_from_the_first_read(core, monkeypatch):
    """At temperature 0, asking the same question about the same pixels returns
    the same answer. The re-read has to change something — here, the block is read
    in two enlarged halves, which is also the only way to put more pixels on a
    line without a bigger model."""
    prompts = _stub_chat(core, monkeypatch, _short_items(), then={})
    core._run_vision_model(_image(), "m")
    assert "PART 1 OF 2" in prompts[1]
    assert "PART 2 OF 2" in prompts[2]
    assert "enlarged and sharpened" in prompts[1]
    # No band may be told to read the list "from its first line to its last": the
    # lines it cannot see are exactly what it would invent.
    assert "FIRST product line" not in prompts[1]


def test_a_short_receipt_falls_back_to_one_look_at_the_whole_block(core, monkeypatch):
    """Halving a receipt that already fits the encoder's grid gains nothing and
    risks slicing the list; the single middle crop is still the right look."""
    prompts = _stub_chat(core, monkeypatch, _short_items(), then={})
    core._run_vision_model(_image(600, 500), "m")
    assert "CROP of the MIDDLE" in prompts[1]
    assert len(prompts) <= 3


def test_a_misread_tax_figure_is_corrected(core, monkeypatch):
    """The case that needs permission to OVERWRITE a transcribed value: the
    printed breakdown (486.61 + VAT = 545.00) proves 5.39 is a misread of 58.39."""
    prompts = _stub_chat(core, monkeypatch, _misread_vat(),
                         then={"vat_amount": 58.39})
    data, _r, _c, _resp, audit = core._run_vision_model(_image(), "m")

    assert len(prompts) > 1
    assert data.vat_amount == 58.39
    assert "sales_breakdown_vs_subtotal" not in {f["code"] for f in audit}


def test_the_tax_look_is_aimed_at_the_bottom_of_the_receipt(core, monkeypatch):
    prompts = _stub_chat(core, monkeypatch, _misread_vat(), then={})
    core._run_vision_model(_image(), "m")
    assert "CROP of the BOTTOM" in prompts[1]
    assert "vatable_sales" in prompts[1]


# --------------------------------------------------------------------------- #
# Nothing is kept without proof
# --------------------------------------------------------------------------- #
def test_an_answer_that_makes_the_arithmetic_worse_is_discarded(core, monkeypatch):
    """The gate. A second answer is not automatically the better one."""
    _stub_chat(core, monkeypatch, _misread_vat(), then={"vat_amount": 200.0})
    data, _r, _c, _resp, _a = core._run_vision_model(_image(), "m")
    assert data.vat_amount == 5.39, "the first read must survive a worse second one"


def test_a_fix_that_breaks_another_check_is_discarded(core, monkeypatch):
    """`audit_score` is computed over the whole audit on purpose: closing one gap
    by opening a bigger one somewhere else is not an improvement."""
    _stub_chat(core, monkeypatch, _misread_vat(), then={
        # Makes the breakdown add up — by moving the subtotal away from the total,
        # the items and the payment lines all at once.
        "vat_amount": 5.39, "vatable_sales": 486.61, "subtotal": 492.0,
    })
    data, _r, _c, _resp, _a = core._run_vision_model(_image(), "m")
    assert data.subtotal == 545.0
    assert data.vat_amount == 5.39


def test_an_unchanged_answer_changes_nothing(core, monkeypatch):
    """The model looks again and confirms what it said. That is a legitimate
    outcome — the receipt simply doesn't balance — and must not be recorded as a
    correction or trigger another look."""
    prompts = _stub_chat(core, monkeypatch, _misread_vat(),
                         then={"vat_amount": 5.39, "vatable_sales": 486.61})
    data, _r, _c, _resp, audit = core._run_vision_model(_image(), "m")
    assert data.vat_amount == 5.39
    assert "sales_breakdown_vs_subtotal" in {f["code"] for f in audit}
    assert len(prompts) <= 1 + core.OCR_RECONCILE_MAX_LOOKS


@pytest.mark.parametrize("answer", ["not json", "[]", {}, {"items": []}])
def test_a_failed_look_leaves_the_first_read_untouched(core, monkeypatch, answer):
    _stub_chat(core, monkeypatch, _short_items(), then=answer)
    data, _r, _c, _resp, _a = core._run_vision_model(_image(), "m")
    assert [i.description for i in data.items] == ["Rice"]
    assert data.subtotal == 500.0


def test_a_dead_endpoint_mid_recheck_does_not_fail_the_extraction(core, monkeypatch):
    calls = {"n": 0}

    def _chat(**kwargs):
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("connection refused")
        return {"message": {"content": _json.dumps(_short_items())},
                "done_reason": "stop"}

    monkeypatch.setattr(core, "ollama", object())
    monkeypatch.setattr(core, "_chat", _chat)
    monkeypatch.setattr(core, "OCR_RECOVERY_PASS", False)
    data, _r, _c, _resp, _a = core._run_vision_model(_image(), "m")
    assert data.subtotal == 500.0


# --------------------------------------------------------------------------- #
# The loop terminates
# --------------------------------------------------------------------------- #
def test_a_receipt_that_never_reconciles_stops_at_the_cap(core, monkeypatch):
    """A model that keeps returning the same unhelpful answer must not be asked
    forever — nor asked the same question twice."""
    prompts = _stub_chat(core, monkeypatch, _short_items(), then={"items": []})
    core._run_vision_model(_image(), "m")
    # An item look is two calls (the two halves) but one question, so the ceiling
    # is two calls per look.
    assert len(prompts) <= 1 + 2 * core.OCR_RECONCILE_MAX_LOOKS


def test_the_same_question_is_never_asked_twice(core, monkeypatch):
    """A short item list fails items-vs-subtotal AND items-vs-total. They are one
    misread block, so they are one question: the second look has to be a different
    one or not happen at all."""
    prompts = _stub_chat(core, monkeypatch, _short_items(), then={"items": []})
    core._run_vision_model(_image(), "m")
    assert len(set(prompts[1:])) == len(prompts[1:]), "a look was repeated verbatim"


def test_the_item_block_is_the_first_thing_looked_at(core, monkeypatch):
    """Priority: the items are upstream of the subtotal, the total and the payment
    lines, so fixing them can clear those checks without another call."""
    monkeypatch.setattr(core, "OCR_RECONCILE_MAX_LOOKS", 1)
    broken = _short_items() | {"cash": 1000.0, "change": 100.0}  # payment fails too
    prompts = _stub_chat(core, monkeypatch, broken, then={})
    core._run_vision_model(_image(), "m")
    assert len(prompts) == 3, "one look: the item block in two halves"
    assert "line-item block" in prompts[1]


def test_the_pass_can_be_switched_off(core, monkeypatch):
    monkeypatch.setattr(core, "OCR_RECONCILE_PASS", False)
    prompts = _stub_chat(core, monkeypatch, _short_items(), then={})
    core._run_vision_model(_image(), "m")
    assert len(prompts) == 1


# --------------------------------------------------------------------------- #
# The prompt must not ask for a balanced receipt
# --------------------------------------------------------------------------- #
def test_the_prompt_forbids_adjusting_a_figure_to_close_the_gap(core, monkeypatch):
    prompts = _stub_chat(core, monkeypatch, _misread_vat(), then={})
    core._run_vision_model(_image(), "m")
    ask = prompts[1]
    assert "NEVER adjust one so that the receipt adds up" in ask
    assert "do not balance is a REAL and ACCEPTABLE answer" in ask
    # It names the failed check and what was said last time, so the model can
    # confirm or correct rather than start from nothing.
    assert "5.39" in ask and "486.61" in ask


# --------------------------------------------------------------------------- #
# audit_score — the comparison the whole pass rests on
# --------------------------------------------------------------------------- #
def test_audit_score_ranks_a_reconciled_receipt_best(core):
    from extraction import audit_score

    assert audit_score(_clean()) < audit_score(_short_items())
    assert audit_score(_clean()) < audit_score(_misread_vat())


def test_audit_score_counts_errors_before_the_size_of_the_gap(core):
    from extraction import audit_score

    one_error = _short_items()                       # items miss by 200
    smaller_gap_more_errors = _short_items() | {"subtotal": 100000.0}
    assert audit_score(one_error) < audit_score(smaller_gap_more_errors)
