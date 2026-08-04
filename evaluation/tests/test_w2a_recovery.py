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


def _stub_chat(core, monkeypatch, responses, then=None):
    """Point core._chat at scripted model replies and record the prompts.

    `responses` is consumed in order; once it runs out, `then` (if given) answers
    every remaining call. The recovery pass makes up to two looks — one per region
    of the receipt — so a test that only cares about *what* was recovered uses
    `then` to answer both identically and lets `_apply_recovery_patch` do the
    filtering, rather than pinning the order of the looks.

    Returns the list the prompts land in, so a test can assert on what was asked
    as well as on what came back."""
    prompts: list[str] = []
    queue = list(responses)

    def _chat(**kwargs):
        prompts.append(kwargs["messages"][0]["content"])
        payload = queue.pop(0) if queue else (then if then is not None else {})
        content = payload if isinstance(payload, str) else _json.dumps(payload)
        return {"message": {"content": content}, "done_reason": "stop"}

    monkeypatch.setattr(core, "ollama", object())
    monkeypatch.setattr(core, "_chat", _chat)
    return prompts


def _receipt_image(width: int = 600, height: int = 1800) -> bytes:
    """A real (blank) JPEG tall enough for the recovery pass to crop. The model is
    stubbed, so only the bytes' shape matters — but they have to be decodable, or
    `crop_region` correctly declines to crop and the region looks never happen."""
    from PIL import Image
    import io

    buf = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buf, format="JPEG")
    return buf.getvalue()


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
    prompts = _stub_chat(core, monkeypatch, [_first_pass()], then={
        "vendor_tin": "123-456-789-000", "vendor_address": "5F SM Megamall",
        "receipt_number": "OR-4471", "cash": 1000.0, "change": 455.0,
        "vat_amount": 58.39,
    })
    data, _reasons, _conf, _resp, _audit = core._run_vision_model(b"fake", "m")

    assert len(prompts) > 1, "the second look must actually happen"
    asked = " ".join(prompts[1:])
    assert "vendor_tin" in asked and "receipt_number" in asked and "change" in asked
    assert data.vendor_tin == "123-456-789-000"
    assert data.vendor_address == "5F SM Megamall"
    assert data.receipt_number == "OR-4471"
    # The three that kept coming back empty — the reason the pass aims at the
    # bottom of the receipt specifically.
    assert (data.cash, data.change, data.vat_amount) == (1000.0, 455.0, 58.39)


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
    _stub_chat(core, monkeypatch, [_first_pass()], then={
        "vendor_name": "Wrong Vendor", "subtotal": 9999.0, "total_amount": 9999.0,
        "vendor_tin": "123-456-789-000",
    })
    data, _r, _c, _resp, _a = core._run_vision_model(b"fake", "m")
    assert data.vendor_name == "Pepper Lunch"
    assert data.subtotal == 545.0
    assert data.total_amount == 545.0
    assert data.vendor_tin == "123-456-789-000"   # the one field that was empty


def test_a_placeholder_in_the_second_answer_is_not_a_value(core, monkeypatch):
    _stub_chat(core, monkeypatch, [_first_pass()],
               then={"vendor_tin": "N/A", "vendor_address": "", "receipt_number": "-"})
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
# One receipt, one read — no two images may share a prompt prefix
# --------------------------------------------------------------------------- #
# Two receipts from the same merchant came back with identical values. Nothing
# here caches an extraction, so the reuse is in the inference server's KV cache,
# which matches on the longest shared prompt prefix — and every request used to
# send a byte-identical prompt. These tests pin the property that removes the
# condition: two different images never share a prefix.
def test_two_different_images_do_not_share_a_prompt_prefix(core, monkeypatch):
    prompts = _stub_chat(core, monkeypatch, [_first_pass(), _first_pass()],
                         then=_first_pass())
    core._run_vision_model(_receipt_image(600, 900), "m")
    first = prompts[0]
    prompts.clear()
    core._run_vision_model(_receipt_image(600, 901), "m")
    second = prompts[0]

    assert first != second
    # Not merely different somewhere: they must diverge at the very first token,
    # or a prefix cache still matches everything up to the difference.
    assert first[:40] != second[:40]


def test_the_same_image_reads_identically(core, monkeypatch):
    """The marker is derived from the image, not from a clock or a counter: the
    same file re-read must produce the same request, or nothing is reproducible."""
    image = _receipt_image()
    prompts = _stub_chat(core, monkeypatch, [_first_pass(), _first_pass()],
                         then=_first_pass())
    core._run_vision_model(image, "m")
    first = prompts[0]
    prompts.clear()
    core._run_vision_model(image, "m")
    assert prompts[0] == first


def test_the_prompt_tells_the_model_not_to_reuse_an_earlier_receipt(core, monkeypatch):
    prompts = _stub_chat(core, monkeypatch, [_first_pass()], then={})
    core._run_vision_model(_receipt_image(), "m")
    assert "same merchant" in prompts[0]
    assert core._image_fingerprint(_receipt_image()) in prompts[0]


def test_the_image_fingerprint_is_recorded_on_the_receipt(core, monkeypatch):
    image = _receipt_image()
    _stub_chat(core, monkeypatch, [_first_pass()], then={})
    data, _r, _c, _resp, _a = core._run_vision_model(image, "m")
    assert data.image_sha256 == core._image_fingerprint(image)
    assert data.image_sha256 != core._image_fingerprint(_receipt_image(600, 901))


def test_a_re_upload_of_the_same_file_is_identifiable(core, finance_fixture,
                                                      monkeypatch):
    """The one legitimate reason two rows carry identical values. Reported, never
    blocked — filing the same receipt twice on purpose is the user's call."""
    image = _receipt_image()
    _stub_chat(core, monkeypatch, [_first_pass()], then={})
    data, _r, _c, _resp, _a = core._run_vision_model(image, "m")
    first_id = core.save_receipt(data, "r.jpg", False, index=False)
    second_id = core.save_receipt(data, "r-again.jpg", False, index=False)

    assert core.receipts_from_same_image(data.image_sha256) == [first_id, second_id]
    assert core.receipts_from_same_image(data.image_sha256, exclude_id=second_id) == [first_id]
    assert core.receipts_from_same_image(None) == []


# --------------------------------------------------------------------------- #
# The looks are aimed at the part of the paper the field is printed on
# --------------------------------------------------------------------------- #
def test_the_bottom_of_the_receipt_is_re_read_as_an_enlarged_crop(core, monkeypatch):
    """Why VAT, cash and change kept coming back empty: they are the smallest
    print at the very bottom of an image already squeezed to fit the encoder. The
    crop gives those lines the whole frame."""
    prompts = _stub_chat(core, monkeypatch, [_first_pass()], then={})
    core._run_vision_model(_receipt_image(), "m")

    bottom = [p for p in prompts[1:] if "CROP of the BOTTOM" in p]
    assert bottom, "the summary/payment fields must be asked for on a bottom crop"
    assert "cash" in bottom[0] and "change" in bottom[0] and "vat_amount" in bottom[0]
    assert "vendor_tin" not in bottom[0], "header fields don't belong on this crop"


def test_the_header_is_re_read_as_a_top_crop(core, monkeypatch):
    prompts = _stub_chat(core, monkeypatch, [_first_pass()], then={})
    core._run_vision_model(_receipt_image(), "m")

    top = [p for p in prompts[1:] if "CROP of the TOP" in p]
    assert top and "vendor_tin" in top[0] and "vendor_address" in top[0]
    assert "cash" not in top[0]


def test_only_the_region_that_is_missing_something_is_re_read(core, monkeypatch):
    """A receipt whose header is complete costs one look, not two."""
    header_ok = _first_pass(vendor_tin="123", vendor_address="Manila",
                            receipt_number="OR-1")
    prompts = _stub_chat(core, monkeypatch, [header_ok], then={})
    core._run_vision_model(_receipt_image(), "m")
    assert len(prompts) == 2
    assert "CROP of the BOTTOM" in prompts[1]


def test_the_item_block_is_re_read_on_the_whole_receipt_never_a_crop(core, monkeypatch):
    """A crop that splits the item list guarantees the partial read the re-read
    exists to fix."""
    short = _first_pass(items=[{"description": "Rice", "amount": 300.0}],
                        items_printed_count=6, subtotal=500.0, total_amount=500.0)
    prompts = _stub_chat(core, monkeypatch, [short], then={})
    core._run_vision_model(_receipt_image(), "m")

    items_look = [p for p in prompts[1:] if "item block" in p]
    assert items_look and "CROP" not in items_look[0]


def test_an_uncroppable_image_still_gets_its_second_look(core, monkeypatch):
    """Pillow missing, bytes undecodable, or a receipt too short to be worth
    cropping: the pass falls back to the full image rather than skipping."""
    prompts = _stub_chat(core, monkeypatch, [_first_pass()],
                         then={"cash": 1000.0, "change": 455.0})
    data, _r, _c, _resp, _a = core._run_vision_model(b"not an image", "m")
    assert len(prompts) > 1
    assert (data.cash, data.change) == (1000.0, 455.0)


def test_cropping_declines_on_an_image_too_short_to_gain_from_it(core):
    assert core.crop_region(_receipt_image(300, 200), "bottom") is None
    assert core.crop_region(b"not an image", "bottom") is None
    assert core.crop_region(_receipt_image(), "middle") is None


def test_the_crop_is_cut_from_the_original_upload_not_the_downscaled_copy(
        core, monkeypatch):
    """The point of the crop is resolution. Cutting it from the image that was
    already squeezed into OCR_MAX_IMAGE_DIM would re-enlarge detail that had
    already been thrown away — the original has to reach the recovery pass."""
    seen: list[bytes] = []
    monkeypatch.setattr(core, "crop_region",
                        lambda image, region: (seen.append(image), None)[1])
    _stub_chat(core, monkeypatch, [_first_pass()], then={})

    original = _receipt_image(2400, 6000)          # a phone photo
    downscaled = core.preprocess_image(original)   # what the model is shown
    assert downscaled != original, "precondition: preprocessing must have resized it"
    core._run_vision_model(downscaled, "m", original)

    assert seen and all(img == original for img in seen)


def test_the_batch_path_hands_the_original_upload_through(core, finance_fixture,
                                                          monkeypatch):
    """The scan UI posts to /extract/batch, so the crops have to reach full
    resolution on that path too, not just the single-file one."""
    got: dict = {}

    def _fake(page_bytes, model, source_bytes=None):
        got["page"], got["source"] = page_bytes, source_bytes
        return (core.ReceiptData(vendor_name="Mart", total_amount=1.0), [],
                {"overall": 0.9}, {}, [])

    monkeypatch.setattr(core, "_run_vision_model", _fake)
    original = _receipt_image(2400, 6000)
    core.extract_batch([(original, "image/jpeg", "r.jpg")], concurrency=1)

    assert got["source"] == original
    assert got["page"] != original, "the model is still shown the preprocessed image"


# --------------------------------------------------------------------------- #
# The magnifier — `zoom_region` / `plan_zoom_bands`
# --------------------------------------------------------------------------- #
# Cropping alone was only half the fix: a band cut from an image already
# downscaled to OCR_MAX_IMAGE_DIM came out SMALLER than the ceiling and used to be
# passed through at that size, so a "zoomed" look was often no bigger than the
# read that had already failed on it. These pin the enlargement.
def _size(image_bytes):
    from PIL import Image
    import io

    return Image.open(io.BytesIO(image_bytes)).size


def test_a_small_band_is_enlarged_not_merely_cropped(core):
    """The defect this function exists for: a crop below the pixel budget must be
    scaled UP to fill it, or the small print stays small."""
    source = _receipt_image(500, 1500)          # well under the 1600px ceiling
    out = core.zoom_region(source, (0.5, 1.0))
    assert out
    width, height = _size(out)
    assert width > 500, "the band was handed back at its original width"
    assert max(width, height) <= core.OCR_MAX_IMAGE_DIM


def test_enlargement_is_capped(core):
    """Interpolation invents no detail; past the cap it only spends pixels."""
    source = _receipt_image(200, 900)
    width, _ = _size(core.zoom_region(source, (0.0, 1.0)))
    assert width <= 200 * core.OCR_ZOOM_MAX_UPSCALE + 1


def test_a_big_band_is_still_brought_down_to_the_budget(core):
    out = core.zoom_region(_receipt_image(2400, 6000), (0.45, 1.0))
    assert max(_size(out)) <= core.OCR_MAX_IMAGE_DIM


def test_the_band_is_the_slice_it_was_asked_for(core):
    source = _receipt_image(600, 2000)
    top = core.zoom_region(source, (0.0, 0.25), enhance=False)
    whole = core.zoom_region(source, (0.0, 1.0), enhance=False)
    assert _size(top)[1] / _size(top)[0] < _size(whole)[1] / _size(whole)[0]


def test_enhancement_produces_a_readable_grayscale_image(core):
    from PIL import Image
    import io

    out = core.zoom_region(_receipt_image(600, 1800), (0.45, 1.0), enhance=True)
    im = Image.open(io.BytesIO(out))
    im.load()                      # decodes: a corrupt result would raise here
    assert im.mode == "L", "a receipt is monochrome; the colour channels are noise"


def test_zooming_declines_when_it_cannot_help(core):
    assert core.zoom_region(_receipt_image(300, 200), (0.0, 1.0)) is None   # too short
    assert core.zoom_region(b"not an image", (0.0, 1.0)) is None
    assert core.zoom_region(_receipt_image(), (0.8, 0.2)) is None           # inverted
    assert core.zoom_region(_receipt_image(), (0.0, 1.5)) is None           # out of range


def test_a_long_receipt_is_planned_into_more_bands_than_a_short_one(core):
    """The band count comes from the shape of the paper: a card slip is one look,
    a till receipt two, a grocery roll three."""
    slip = core.plan_zoom_bands(_receipt_image(600, 900), (0.0, 1.0))
    till = core.plan_zoom_bands(_receipt_image(600, 1800), (0.10, 0.92))
    roll = core.plan_zoom_bands(_receipt_image(600, 6000), (0.10, 0.92))
    assert len(slip) == 1
    assert len(till) == 2
    assert len(roll) == core.OCR_ZOOM_MAX_BANDS, "the count is capped: each band is a call"


def test_bands_cover_the_whole_span_and_overlap_their_neighbours(core):
    bands = core.plan_zoom_bands(_receipt_image(600, 6000), (0.10, 0.92))
    assert bands[0][0] == 0.10 and bands[-1][1] == 0.92
    for earlier, later in zip(bands, bands[1:]):
        assert later[0] < earlier[1], "a line falling on an un-overlapped seam is lost"


def test_an_unreadable_image_plans_a_single_band(core):
    assert core.plan_zoom_bands(b"not an image", (0.0, 1.0)) == [(0.0, 1.0)]


def test_a_three_band_receipt_is_read_in_three_looks_and_stitched(core, monkeypatch):
    """End to end: a long roll whose items don't add up is re-read band by band,
    and the bands are joined back into one list."""
    band_answers = [
        {"items": [{"description": "Rice", "amount": 300.0}]},
        {"items": [{"description": "Rice", "amount": 300.0},
                   {"description": "Oil", "amount": 120.0}]},
        {"items": [{"description": "Oil", "amount": 120.0},
                   {"description": "Sugar", "amount": 80.0}]},
    ]
    prompts = _stub_chat(core, monkeypatch, [
        {"vendor_name": "Mart", "currency": "PHP", "vendor_tin": "1",
         "vendor_address": "Manila", "receipt_number": "OR-9",
         "receipt_date_raw": "14/06/26",
         "items": [{"description": "Rice", "amount": 300.0}],
         "subtotal": 500.0, "total_amount": 500.0, "cash": 500.0, "change": 0.0},
        *band_answers,
    ])
    monkeypatch.setattr(core, "OCR_RECOVERY_PASS", False)
    data, _r, _c, _resp, _a = core._run_vision_model(_receipt_image(600, 6000), "m")

    import re

    banded = [p for p in prompts if re.search(r"PART \d+ OF 3", p)]
    assert len(banded) == 3
    assert [i.description for i in data.items] == ["Rice", "Oil", "Sugar"]


def test_a_crop_is_the_part_of_the_receipt_it_says_it_is(core):
    from PIL import Image
    import io

    tall = _receipt_image(600, 2000)
    for region in ("top", "bottom"):
        out = core.crop_region(tall, region)
        assert out, region
        cropped = Image.open(io.BytesIO(out))
        # Shorter than the original in aspect: a slice, not the whole receipt.
        assert cropped.height / cropped.width < 2000 / 600


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
