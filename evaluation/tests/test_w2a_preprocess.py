"""
W2-A — image preprocessing, the single per-page normalization step before OCR.

Covers the checklist item "Image preprocessing and PDF page expansion". Runs offline:
images are synthesised with Pillow, no model involved.

Preprocessing is ~18 ms against a ~6,000 ms vision call, so it is not a latency lever.
It is tested because it decides what pixels the model actually sees — a wrong rotation
or an unnecessary lossy re-encode costs accuracy, not time.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image


def _jpeg(size=(800, 600), color=(120, 130, 140), quality=92) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def _png(size=(800, 600)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


def _dims(data: bytes):
    return Image.open(io.BytesIO(data)).size


# --------------------------------------------------------------------------- #
# The no-op fast path
# --------------------------------------------------------------------------- #
def test_a_conforming_jpeg_is_returned_byte_identical(core):
    """A JPEG already within the size limit, upright and RGB has nothing that needs
    changing. Re-encoding it would be a second lossy generation over the faint
    thermal-receipt text the model has to read, for no benefit."""
    original = _jpeg((800, 600))
    assert core.preprocess_image(original) is original or \
        core.preprocess_image(original) == original


def test_the_fast_path_does_not_inflate_the_payload(core):
    """Re-encoding the sample receipt grew it 251 KB -> 318 KB. For a conforming
    image the output must never be larger than the input."""
    original = _jpeg((800, 600))
    assert len(core.preprocess_image(original)) <= len(original)


def test_an_image_exactly_at_the_limit_is_not_resized(core):
    original = _jpeg((core.OCR_MAX_IMAGE_DIM, 400))
    assert _dims(core.preprocess_image(original))[0] == core.OCR_MAX_IMAGE_DIM


# --------------------------------------------------------------------------- #
# Resizing — the actual token saving
# --------------------------------------------------------------------------- #
def test_an_oversized_image_is_downscaled_to_the_limit(core):
    out = core.preprocess_image(_jpeg((3024, 4032)))
    assert max(_dims(out)) == core.OCR_MAX_IMAGE_DIM


def test_downscaling_preserves_aspect_ratio(core):
    w, h = _dims(core.preprocess_image(_jpeg((3000, 1500))))
    assert w == core.OCR_MAX_IMAGE_DIM
    assert h == pytest.approx(core.OCR_MAX_IMAGE_DIM // 2, abs=2)


def test_a_landscape_oversized_image_is_bounded_by_its_longest_edge(core):
    out = core.preprocess_image(_jpeg((4032, 3024)))
    assert max(_dims(out)) == core.OCR_MAX_IMAGE_DIM


# --------------------------------------------------------------------------- #
# Format and mode normalization
# --------------------------------------------------------------------------- #
def test_a_png_is_converted_to_jpeg(core):
    out = core.preprocess_image(_png((800, 600)))
    assert Image.open(io.BytesIO(out)).format == "JPEG"


def test_a_palette_image_is_converted_to_rgb(core):
    buf = io.BytesIO()
    Image.new("P", (400, 300)).save(buf, format="PNG")
    out = core.preprocess_image(buf.getvalue())
    assert Image.open(io.BytesIO(out)).mode in ("RGB", "L")


# --------------------------------------------------------------------------- #
# EXIF orientation — a correctness path, not a performance one
# --------------------------------------------------------------------------- #
def test_an_exif_rotated_photo_is_uprighted(core):
    """Phone photos carry rotation in EXIF rather than in the pixels. If it is not
    applied the model reads a sideways receipt. Orientation 6 = rotate 90° CW, so a
    portrait-tagged landscape image must come back with its axes swapped."""
    im = Image.new("RGB", (800, 400), (200, 100, 50))
    exif = im.getexif()
    exif[0x0112] = 6
    buf = io.BytesIO()
    im.save(buf, format="JPEG", exif=exif)

    out_w, out_h = _dims(core.preprocess_image(buf.getvalue()))
    assert (out_w, out_h) == (400, 800), "EXIF orientation was not applied"


def test_an_exif_rotated_photo_is_not_taken_by_the_fast_path(core):
    """Regression guard for the no-op shortcut: a conforming-looking JPEG that still
    needs rotation must NOT be returned unchanged."""
    im = Image.new("RGB", (800, 400), (10, 10, 10))
    exif = im.getexif()
    exif[0x0112] = 6
    buf = io.BytesIO()
    im.save(buf, format="JPEG", exif=exif)
    original = buf.getvalue()

    assert core.preprocess_image(original) != original


def test_orientation_1_is_treated_as_upright(core):
    """Orientation 1 means "already correct" and must still hit the fast path."""
    im = Image.new("RGB", (800, 400), (10, 10, 10))
    exif = im.getexif()
    exif[0x0112] = 1
    buf = io.BytesIO()
    im.save(buf, format="JPEG", exif=exif)
    original = buf.getvalue()

    assert core.preprocess_image(original) == original


def test_rotation_and_resize_combine_correctly(core):
    """Both transforms at once: the longest edge is still bounded after transposing."""
    im = Image.new("RGB", (4000, 2000), (5, 5, 5))
    exif = im.getexif()
    exif[0x0112] = 6
    buf = io.BytesIO()
    im.save(buf, format="JPEG", exif=exif)

    w, h = _dims(core.preprocess_image(buf.getvalue()))
    assert max(w, h) == core.OCR_MAX_IMAGE_DIM
    assert h > w, "expected portrait after a 90 degree rotation"


# --------------------------------------------------------------------------- #
# Robustness — preprocessing must never break extraction
# --------------------------------------------------------------------------- #
def test_undecodable_bytes_are_passed_through(core):
    junk = b"this is not an image"
    assert core.preprocess_image(junk) == junk


def test_empty_input_is_passed_through(core):
    assert core.preprocess_image(b"") == b""


def test_the_real_sample_receipt_is_downscaled_to_the_ceiling(core):
    """Receipt.jpg is the one real image in the repo. 1600 px is the endpoint's hard
    ceiling — above it the shared endpoint returns empty content — so this must land
    exactly on it, not above."""
    from pathlib import Path

    sample = Path(__file__).resolve().parents[2] / "Receipt.jpg"
    out = core.preprocess_image(sample.read_bytes())
    assert max(_dims(out)) == 1600
