"""
W2-A — field confidence and value-equality gating.

Closes the checklist item "field-confidence availability and value-equality gating"
(IMPLEMENTATION_STATUS.md §3.3 item 12), which had **zero tests**. Confidence is what
tells a reviewer which fields to check first; a confidence number attached to the wrong
value is worse than none, because it invites trust.

Runs offline: logprobs are synthesised. No model is called — `compute_extraction_confidence`
is a pure function over (logprobs, raw json, validated data).

The gating rule under test
--------------------------
Confidence is a *read* confidence: the probability the model assigned to the tokens it
printed. Deterministic post-processing may later replace a number (payment repair,
summary-line remapping). When it does, the printed token's probability no longer describes
the value in the field, so the field must be left **unscored** rather than inherit a
probability that refers to a different number.
"""

from __future__ import annotations

import json
import math

import pytest


def _logprobs_for(text: str, per_char: float = -0.01, spans=None):
    """Tokenize `text` one character per token so char offsets are unambiguous.

    `spans` optionally maps a substring to a different per-token logprob, which is
    how a "low confidence" region is simulated.
    """
    entries = []
    low_ranges = []
    for needle, lp in (spans or {}).items():
        # Mark *every* occurrence: a value like "250.0" can appear as both a
        # unit_price and an amount, and marking only the first would leave the field
        # under test scored normally — the assertion would then pass or fail for a
        # reason unrelated to what it claims to check.
        start = text.find(needle)
        while start != -1:
            low_ranges.append((start, start + len(needle), lp))
            start = text.find(needle, start + 1)
    for i, char in enumerate(text):
        lp = per_char
        for a, b, low in low_ranges:
            if a <= i < b:
                lp = low
        entries.append({"token": char, "logprob": lp})
    return entries


def _receipt_json(**overrides) -> dict:
    payload = {
        "vendor_name": "SM Supermarket",
        "receipt_date": "2026-06-15",
        "total_amount": 350.0,
        "currency": "PHP",
        "items": [{"description": "Rice", "quantity": 1, "unit_price": 350.0,
                   "amount": 350.0}],
    }
    payload.update(overrides)
    return payload


def _data(core, raw: dict):
    return core.ReceiptData(**raw)


# --------------------------------------------------------------------------- #
# Token span reconstruction — the offsets everything else depends on
# --------------------------------------------------------------------------- #
def test_spans_reconstruct_the_output_text_exactly(core):
    """If the reconstruction drifts by one character, every field's confidence is
    read off the wrong tokens — silently, and with plausible-looking numbers."""
    text = '{"vendor_name": "SM"}'
    spans, rebuilt = core._logprob_token_spans(_logprobs_for(text))
    assert rebuilt == text
    assert spans[0][0] == 0
    assert spans[-1][1] == len(text)


def test_multi_character_tokens_advance_the_offset_correctly(core):
    entries = [{"token": '{"a": ', "logprob": -0.1}, {"token": "123", "logprob": -0.2}]
    spans, rebuilt = core._logprob_token_spans(entries)
    assert rebuilt == '{"a": 123'
    assert spans[1] == (6, 9, -0.2)


def test_entries_missing_a_token_or_logprob_are_skipped(core):
    entries = [{"token": "a", "logprob": -0.1}, {"token": None, "logprob": -0.2},
               {"token": "b"}]
    _, rebuilt = core._logprob_token_spans(entries)
    assert rebuilt == "a"


def test_no_logprobs_yields_no_spans(core):
    assert core._logprob_token_spans(None) == ([], "")
    assert core._logprob_token_spans([]) == ([], "")


# --------------------------------------------------------------------------- #
# Span scoring
# --------------------------------------------------------------------------- #
def test_span_confidence_is_the_geometric_mean_probability(core):
    spans = [(0, 1, math.log(0.5)), (1, 2, math.log(0.5))]
    assert core._span_confidence(spans, 0, 2) == pytest.approx(0.5)


def test_span_confidence_covers_only_overlapping_tokens(core):
    spans = [(0, 1, math.log(0.9)), (5, 6, math.log(0.1))]
    assert core._span_confidence(spans, 0, 1) == pytest.approx(0.9)


def test_a_span_matching_no_token_is_unscored(core):
    assert core._span_confidence([(0, 1, -0.1)], 50, 60) is None


def test_a_confident_read_scores_near_one(core):
    spans = [(0, 5, math.log(0.99))]
    assert core._span_confidence(spans, 0, 5) > 0.98


# --------------------------------------------------------------------------- #
# Availability — a confidence report is produced at all
# --------------------------------------------------------------------------- #
def test_a_clean_extraction_produces_field_confidences(core):
    raw = _receipt_json()
    text = json.dumps(raw)
    report = core.compute_extraction_confidence(
        _logprobs_for(text), raw, _data(core, raw)
    )
    assert report["fields"]["vendor_name"] > 0.9
    assert report["overall"] is not None


def test_item_confidences_align_with_the_final_items(core):
    raw = _receipt_json()
    text = json.dumps(raw)
    report = core.compute_extraction_confidence(
        _logprobs_for(text), raw, _data(core, raw)
    )
    assert len(report["items"]) == 1
    assert report["items"][0]["amount"] > 0.9


def test_without_logprobs_the_report_is_empty_not_fabricated(core):
    """Older Ollama builds do not return logprobs. The honest result is "no
    confidence", never a default number that reads as certainty."""
    raw = _receipt_json()
    report = core.compute_extraction_confidence(None, raw, _data(core, raw))
    assert report == {"overall": None, "fields": {}, "items": []}


def test_a_null_field_is_not_scored(core):
    """A field the model printed as `null` was not read, so it has no read
    confidence. Scoring the literal `null` token would score the absence."""
    raw = _receipt_json(vendor_tin=None)
    text = json.dumps(raw)
    report = core.compute_extraction_confidence(
        _logprobs_for(text), raw, _data(core, raw)
    )
    assert "vendor_tin" not in report["fields"]


def test_a_low_probability_read_is_reported_as_low(core):
    """The point of the whole mechanism: the reviewer must be able to tell which
    field to check. A garbled vendor name must not score like a clean one."""
    raw = _receipt_json()
    text = json.dumps(raw)
    report = core.compute_extraction_confidence(
        _logprobs_for(text, spans={"SM Supermarket": math.log(0.3)}),
        raw, _data(core, raw),
    )
    assert report["fields"]["vendor_name"] < 0.5
    assert report["fields"]["currency"] > 0.9


def test_overall_confidence_falls_when_a_field_is_uncertain(core):
    raw = _receipt_json()
    text = json.dumps(raw)
    confident = core.compute_extraction_confidence(
        _logprobs_for(text), raw, _data(core, raw)
    )["overall"]
    uncertain = core.compute_extraction_confidence(
        _logprobs_for(text, spans={"350.0": math.log(0.2)}), raw, _data(core, raw)
    )["overall"]
    assert uncertain < confident


# --------------------------------------------------------------------------- #
# Value-equality gating — the part that keeps confidence honest
# --------------------------------------------------------------------------- #
def test_a_numeric_field_changed_by_post_processing_is_not_scored(core):
    """The model printed `total_amount: 350.0`; deterministic repair replaced it with
    500.0. The token probability describes 350.0 and says nothing about 500.0, so the
    field must be left unscored rather than borrow it."""
    raw = _receipt_json()
    text = json.dumps(raw)
    repaired = _data(core, _receipt_json(total_amount=500.0))
    report = core.compute_extraction_confidence(_logprobs_for(text), raw, repaired)
    assert "total_amount" not in report["fields"]


def test_an_unchanged_numeric_field_is_still_scored(core):
    """The gate must not be so strict that it discards every number."""
    raw = _receipt_json()
    text = json.dumps(raw)
    report = core.compute_extraction_confidence(
        _logprobs_for(text), raw, _data(core, raw)
    )
    assert report["fields"]["total_amount"] > 0.9


def test_rounding_within_tolerance_still_counts_as_the_same_value(core):
    """350.0 vs 350.004 is the same reading. The gate targets *replaced* values, not
    float noise."""
    raw = _receipt_json()
    text = json.dumps(raw)
    report = core.compute_extraction_confidence(
        _logprobs_for(text), raw, _data(core, _receipt_json(total_amount=350.004))
    )
    assert "total_amount" in report["fields"]


def test_a_string_field_is_not_value_gated(core):
    """Gating applies to numeric fields. A cleaned-up vendor string keeps the
    confidence of what was read, since cleaning does not invent a new reading."""
    raw = _receipt_json()
    text = json.dumps(raw)
    report = core.compute_extraction_confidence(
        _logprobs_for(text), raw, _data(core, _receipt_json(vendor_name="SM Supermarket"))
    )
    assert "vendor_name" in report["fields"]


# --------------------------------------------------------------------------- #
# Item alignment across de-duplication
# --------------------------------------------------------------------------- #
def test_item_confidence_follows_the_item_through_dedupe(core):
    """Cleaning drops the amount-less echo row but never changes an amount, so the
    surviving item must keep the confidence of the row it came from — not the
    confidence of whichever row happens to sit at the same index."""
    raw = _receipt_json(items=[
        {"description": "Rice", "quantity": 1, "unit_price": 100.0, "amount": 100.0},
        {"description": "Eggs", "quantity": 2, "unit_price": 125.0, "amount": 250.0},
    ])
    text = json.dumps(raw)
    final = _data(core, _receipt_json(items=[raw["items"][1]]))  # only Eggs survived

    report = core.compute_extraction_confidence(
        _logprobs_for(text, spans={"250.0": math.log(0.2)}), raw, final
    )
    assert len(report["items"]) == 1
    assert report["items"][0]["amount"] < 0.5, "confidence was taken from the wrong row"


def test_an_item_with_no_matching_raw_row_is_unscored_not_guessed(core):
    raw = _receipt_json()
    text = json.dumps(raw)
    invented = _data(core, _receipt_json(items=[
        {"description": "Not from the model", "quantity": 1,
         "unit_price": 9_999.0, "amount": 9_999.0},
    ]))
    report = core.compute_extraction_confidence(_logprobs_for(text), raw, invented)
    assert report["items"] == [{}]


def test_a_receipt_with_no_items_still_reports_header_confidence(core):
    raw = _receipt_json(items=[])
    text = json.dumps(raw)
    report = core.compute_extraction_confidence(
        _logprobs_for(text), raw, _data(core, raw)
    )
    assert report["items"] == []
    assert report["fields"]["vendor_name"] > 0.9


# --------------------------------------------------------------------------- #
# Persistence — confidence has to survive to the reviewer
# --------------------------------------------------------------------------- #
def test_confidence_is_stored_with_the_receipt(finance_fixture, core):
    raw = _receipt_json()
    data = _data(core, raw)
    report = core.compute_extraction_confidence(
        _logprobs_for(json.dumps(raw)), raw, data
    )
    receipt_id = core.save_receipt(data, "test.jpg", flagged=False,
                                  confidence=report, index=False)

    saved = core.get_receipt(receipt_id)
    assert saved["confidence"] == pytest.approx(report["overall"])
    assert json.loads(saved["field_confidence"])["fields"]["vendor_name"] > 0.9


def test_a_receipt_saved_without_confidence_stores_null(finance_fixture, core):
    """Confidence is optional (older Ollama). Absence must read as absence."""
    receipt_id = core.save_receipt(_data(core, _receipt_json()), "t.jpg",
                                  flagged=False, index=False)
    saved = core.get_receipt(receipt_id)
    assert saved["confidence"] is None
    assert saved["field_confidence"] is None
