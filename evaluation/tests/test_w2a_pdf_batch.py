"""
W2-A / W3 — PDF page expansion and per-page failure isolation in batch.

Closes two checklist items that had **zero coverage** (IMPLEMENTATION_STATUS.md §3.3
items 2 and 14) and one W3 receipt-pipeline check ("a failed page does not stop unrelated
batch pages"). No PDF fixture existed in the repository; these synthesise one with Pillow,
so nothing needs to be committed as a binary.

Runs offline. PDF rasterization is real (`pypdfium2`); only the vision model is stubbed,
because what is under test is the page-expansion and failure-isolation machinery around
it, not what the model reads.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image


def _page(color=(240, 240, 240), size=(600, 800)) -> Image.Image:
    return Image.new("RGB", size, color)


def _pdf(page_count: int = 1) -> bytes:
    """A synthetic PDF with `page_count` distinct pages."""
    pages = [_page((240 - i * 10, 240, 240)) for i in range(page_count)]
    buf = io.BytesIO()
    pages[0].save(buf, format="PDF", save_all=True, append_images=pages[1:])
    return buf.getvalue()


def _jpeg(size=(800, 600)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (120, 130, 140)).save(buf, format="JPEG", quality=92)
    return buf.getvalue()


def _dims(data: bytes):
    return Image.open(io.BytesIO(data)).size


# --------------------------------------------------------------------------- #
# PDF detection
# --------------------------------------------------------------------------- #
def test_a_pdf_is_detected_by_its_magic_bytes(core):
    """Content type is client-supplied and often wrong or absent; the file header is
    not. Misdetecting a PDF sends raw PDF bytes to the vision model as if they were
    an image."""
    assert core._is_pdf(_pdf(), None) is True


def test_a_pdf_is_detected_by_content_type(core):
    assert core._is_pdf(b"not really a pdf", "application/pdf") is True


def test_an_image_is_not_detected_as_a_pdf(core):
    assert core._is_pdf(_jpeg(), "image/jpeg") is False


# --------------------------------------------------------------------------- #
# Page expansion
# --------------------------------------------------------------------------- #
def test_a_single_page_pdf_expands_to_one_image(core):
    assert len(core.pdf_to_page_images(_pdf(1))) == 1


def test_a_multipage_pdf_expands_to_one_image_per_page(core):
    """The seam that lets a long PDF flow through the same per-page path as a photo.
    Silently dropping pages would lose receipts with no error."""
    assert len(core.pdf_to_page_images(_pdf(5))) == 5


def test_expanded_pages_are_jpeg(core):
    for page in core.pdf_to_page_images(_pdf(2)):
        assert Image.open(io.BytesIO(page)).format == "JPEG"


def test_expanded_pages_are_preprocessed_to_the_size_ceiling(core):
    """Rendering at PDF_RENDER_SCALE can exceed the endpoint's 1600 px ceiling, above
    which it returns empty content. Every page must come back already normalized."""
    for page in core.pdf_to_page_images(_pdf(2)):
        assert max(_dims(page)) <= core.OCR_MAX_IMAGE_DIM


def test_the_page_ceiling_bounds_expansion(core, monkeypatch):
    """`OCR_PDF_MAX_PAGES` is the guard against a pathological upload turning into
    unbounded work. Patched low so the test stays fast."""
    monkeypatch.setattr(core, "PDF_MAX_PAGES", 2)
    assert len(core.pdf_to_page_images(_pdf(5))) == 2


def test_render_scale_changes_the_rasterized_size(core, monkeypatch):
    """Confirms the knob is live rather than dead config — the `VISION_MAX_DIM`
    lesson from the W0 audit, where a documented setting did nothing."""
    monkeypatch.setattr(core, "PDF_RENDER_SCALE", 0.5)
    small = core.pdf_to_page_images(_pdf(1))[0]
    monkeypatch.setattr(core, "PDF_RENDER_SCALE", 2.0)
    large = core.pdf_to_page_images(_pdf(1))[0]
    assert max(_dims(small)) < max(_dims(large))


def test_a_corrupt_pdf_raises_rather_than_returning_nothing(core):
    """Returning [] would report "0 pages extracted" as a success."""
    with pytest.raises(Exception):
        core.pdf_to_page_images(b"%PDF-1.4 this is not a real pdf body")


# --------------------------------------------------------------------------- #
# The upload seam
# --------------------------------------------------------------------------- #
def test_a_raster_upload_yields_exactly_one_page(core):
    assert len(core.iter_page_images(_jpeg(), "image/jpeg")) == 1


def test_a_pdf_upload_yields_its_pages(core):
    assert len(core.iter_page_images(_pdf(3), "application/pdf")) == 3


def test_a_raster_upload_is_preprocessed_through_the_seam(core):
    oversized = io.BytesIO()
    Image.new("RGB", (3024, 4032), (10, 20, 30)).save(oversized, format="JPEG")
    page = core.iter_page_images(oversized.getvalue(), "image/jpeg")[0]
    assert max(_dims(page)) == core.OCR_MAX_IMAGE_DIM


# --------------------------------------------------------------------------- #
# Batch failure isolation
# --------------------------------------------------------------------------- #
@pytest.fixture
def stub_vision(core, monkeypatch):
    """Replace the vision call with a scripted one keyed on page bytes.

    `fail_on` is a set of 1-based page ordinals (in submission order) that raise.
    Concurrency is pinned to 1 so ordinals are deterministic.
    """

    def _install(fail_on: set[int] | None = None):
        fail_on = fail_on or set()
        seen = {"n": 0}

        def fake_run(page_bytes, model):
            seen["n"] += 1
            if seen["n"] in fail_on:
                raise RuntimeError(f"page {seen['n']} is unreadable")
            data = core.ReceiptData(
                vendor_name=f"Vendor {seen['n']}",
                receipt_date="2026-06-15",
                total_amount=100.0,
                currency="PHP",
                items=[core.LineItem(description="Item", quantity=1,
                                     unit_price=100.0, amount=100.0)],
            )
            # (data, review_reasons, confidence, raw_response, audit) — the 5th
            # element is the arithmetic audit added alongside `audit_extraction`.
            return data, [], {"overall": 0.9}, {}, []

        monkeypatch.setattr(core, "_run_vision_model", fake_run)
        return seen

    return _install


def test_every_page_of_a_pdf_becomes_its_own_result(finance_fixture, core, stub_vision):
    stub_vision()
    results = core.extract_batch([(_pdf(3), "application/pdf", "scan.pdf")], concurrency=1)
    assert len(results) == 3


def test_pdf_pages_are_numbered(finance_fixture, core, stub_vision):
    """A user reviewing a 3-page scan needs to know which page a receipt came from."""
    stub_vision()
    results = core.extract_batch([(_pdf(3), "application/pdf", "scan.pdf")], concurrency=1)
    assert sorted(r["page"] for r in results) == [1, 2, 3]


def test_a_single_image_upload_has_no_page_number(finance_fixture, core, stub_vision):
    stub_vision()
    results = core.extract_batch([(_jpeg(), "image/jpeg", "photo.jpg")], concurrency=1)
    assert results[0]["page"] is None


def test_one_failing_page_does_not_stop_the_others(finance_fixture, core, stub_vision):
    """The core isolation guarantee for the 1000-page path. Without it, one
    unreadable page in the middle aborts an entire import."""
    stub_vision(fail_on={2})
    results = core.extract_batch([(_pdf(4), "application/pdf", "scan.pdf")], concurrency=1)
    assert len(results) == 4
    assert sum(1 for r in results if r["error"] is None) == 3


def test_a_failed_page_reports_its_error(finance_fixture, core, stub_vision):
    stub_vision(fail_on={2})
    results = core.extract_batch([(_pdf(3), "application/pdf", "scan.pdf")], concurrency=1)
    failed = [r for r in results if r["error"]]
    assert len(failed) == 1
    assert "unreadable" in failed[0]["error"]


def test_a_failed_page_saves_no_receipt(finance_fixture, core, stub_vision):
    """A failure must not leave a half-written row behind."""
    stub_vision(fail_on={1})
    results = core.extract_batch([(_pdf(2), "application/pdf", "scan.pdf")], concurrency=1)
    failed = next(r for r in results if r["error"])
    assert failed["receipt_id"] is None
    assert failed["data"] is None


def test_successful_pages_are_persisted(finance_fixture, core, stub_vision):
    stub_vision(fail_on={1})
    results = core.extract_batch([(_pdf(3), "application/pdf", "scan.pdf")], concurrency=1)
    for result in (r for r in results if r["error"] is None):
        assert core.get_receipt(result["receipt_id"]) is not None


def test_one_invalid_file_does_not_stop_the_other_files(finance_fixture, core, stub_vision):
    """Validation failures are surfaced as failed results, not raised — so a mixed
    upload still processes everything it can."""
    stub_vision()
    results = core.extract_batch(
        [
            (_jpeg(), "image/jpeg", "good.jpg"),
            (b"", "image/jpeg", "empty.jpg"),                 # rejected: empty
            (_jpeg(), "application/zip", "wrong_type.zip"),   # rejected: type
            (_jpeg(), "image/jpeg", "also_good.jpg"),
        ],
        concurrency=1,
    )
    assert len(results) == 4
    assert sum(1 for r in results if r["error"] is None) == 2
    assert {r["source_file"] for r in results if r["error"]} == {"empty.jpg",
                                                                 "wrong_type.zip"}


def test_page_labels_distinguish_receipts_from_the_same_pdf(finance_fixture, core,
                                                            stub_vision):
    """`source_file` on the saved row is suffixed `#pN`, which is what makes a
    multi-page scan traceable back to a page rather than to the whole file."""
    stub_vision()
    results = core.extract_batch([(_pdf(2), "application/pdf", "scan.pdf")], concurrency=1)
    labels = {core.get_receipt(r["receipt_id"])["source_file"] for r in results}
    assert labels == {"scan.pdf#p1", "scan.pdf#p2"}


def test_progress_is_reported_for_every_page_including_failures(finance_fixture, core,
                                                               stub_vision):
    """The UI's progress bar must reach 100% even when pages fail, or a partly failed
    import appears to hang."""
    stub_vision(fail_on={2})
    seen: list[tuple[int, int]] = []
    core.extract_batch([(_pdf(3), "application/pdf", "scan.pdf")],
                       concurrency=1, progress=lambda d, t: seen.append((d, t)))
    assert seen[-1] == (3, 3)


def test_batch_results_cover_every_submitted_page_under_concurrency(
    finance_fixture, core, stub_vision
):
    """With workers > 1 results arrive in completion order, so only the set matters —
    but nothing may be dropped."""
    stub_vision()
    results = core.extract_batch([(_pdf(6), "application/pdf", "scan.pdf")], concurrency=3)
    assert sorted(r["page"] for r in results) == [1, 2, 3, 4, 5, 6]
