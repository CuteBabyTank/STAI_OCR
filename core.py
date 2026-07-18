"""
core.py — shared logic for STAI_OCR, exposed to the Next.js frontend through
the REST API (api.py). Pure extraction primitives live in extraction.py.

Adds, on top of the original extraction pipeline:
  - Structured Outputs : Pydantic schema validation of the model's JSON
  - Guardrails         : input validation (file type/size) + output validation
                         (schema + reconciliation) before a record is trusted
  - Disambiguation      : flags receipts that need a human decision instead of
                         silently guessing
  - Memory              : a persistent SQLite ledger of every processed receipt
  - SQL Agent           : answers natural-language questions about the ledger
                         by generating + executing SQL against that SQLite db
  - LLMOps Monitoring   : every extraction and every SQL-agent turn is logged
                         to MLflow (latency, token-ish counts, errors, params)
"""

from __future__ import annotations

import io
import json
import math
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import mlflow
from pydantic import BaseModel, Field, ValidationError

try:
    import ollama
except ImportError:  # pragma: no cover
    ollama = None

# Per-token logprobs (the basis for measured confidence) need a recent ollama
# client. Feature-detect so an older client degrades gracefully — extraction
# still works, confidence is simply omitted — instead of raising on the kwarg.
_OLLAMA_SUPPORTS_LOGPROBS = False
_OLLAMA_SUPPORTS_THINK = False
if ollama is not None:
    try:
        import inspect as _inspect
        _params = _inspect.signature(ollama.chat).parameters
        _OLLAMA_SUPPORTS_LOGPROBS = "logprobs" in _params
        _OLLAMA_SUPPORTS_THINK = "think" in _params
    except (ValueError, TypeError):  # pragma: no cover
        pass


def _chat(**kwargs):
    """Call ``ollama.chat`` with hidden 'thinking' disabled, retrying once on a
    transient failure.

    The LLM now runs on a shared remote Ollama endpoint (set via OLLAMA_HOST)
    rather than locally. Several models served there are reasoning ('thinking')
    models that otherwise spend their whole token budget on hidden reasoning and
    return empty content — think=False makes them answer directly. This is a
    no-op for clients or models without thinking support; all prompts, guardrails,
    structured-output parsing and confidence logic are unchanged.

    Because the endpoint is shared, it can briefly be busy / time out / return a
    5xx. We retry once after a short backoff so a one-off hiccup doesn't surface
    to the user as a 500."""
    if _OLLAMA_SUPPORTS_THINK:
        kwargs.setdefault("think", False)
    for _attempt in range(2):
        try:
            return ollama.chat(**kwargs)
        except Exception:  # noqa: BLE001 - retry once, then let it propagate
            if _attempt == 0:
                time.sleep(1.5)
                continue
            raise

# Vision input controls. Defaults preserve original behaviour (no downscale, 8192
# context); a constrained deployment sets these via env to fit CPU/RAM limits.
_VISION_MAX_DIM = int(os.environ.get("VISION_MAX_DIM", "0"))     # 0 = no downscaling
_VISION_NUM_CTX = int(os.environ.get("VISION_NUM_CTX", "8192"))


def _downscale_image(image_bytes: bytes, max_dim: int) -> bytes:
    """Shrink an image so its longest side is <= max_dim, re-encoded as JPEG.
    Best-effort: on any failure the original bytes are returned unchanged."""
    try:
        import io as _io
        from PIL import Image
        img = Image.open(_io.BytesIO(image_bytes))
        w, h = img.size
        if max(w, h) <= max_dim:
            return image_bytes
        scale = max_dim / float(max(w, h))
        resized = img.convert("RGB").resize((max(1, int(w * scale)), max(1, int(h * scale))))
        buf = _io.BytesIO()
        resized.save(buf, format="JPEG", quality=88)
        return buf.getvalue()
    except Exception:  # noqa: BLE001 - never let preprocessing break extraction
        return image_bytes

try:
    from PIL import Image, ImageOps
except ImportError:  # pragma: no cover - pillow ships with the app, but stay safe
    Image = None
    ImageOps = None

try:
    import pypdfium2 as pdfium
except ImportError:  # pragma: no cover - PDF support is optional
    pdfium = None

try:
    import numpy as np
except ImportError:  # pragma: no cover - numpy ships with pandas, but stay safe
    np = None

# Re-use the shared prompt/cleanup pipeline so behavior doesn't change.
from extraction import (
    DEFAULT_MODEL,
    EXTRACTION_PROMPT,
    _clean_items,
    _coerce_json,
    _dedupe_items,
    _fix_payment_fields,
    _num,
    _remap_summary_lines,
    reconcile,
)

_TOP_LEVEL_NUMERIC_FIELDS = (
    "subtotal",
    "vatable_sales",
    "vat_exempt_sales",
    "zero_rated_sales",
    "vat_amount",
    "discount",
    "total_amount",
    "cash",
    "change",
)
_ITEM_NUMERIC_FIELDS = ("quantity", "unit_price", "amount")


def _coerce_numeric_fields(data: dict) -> dict:
    """Convert every numeric-looking field (which may still be a string like
    '17,855.36' or '₱19,249.00' straight from the model) into an actual float
    using the same `_num` parsing already trusted elsewhere in the pipeline.
    Without this, raw strings survive cleanup untouched and Pydantic's float
    parser rejects thousands separators during schema validation."""
    for field in _TOP_LEVEL_NUMERIC_FIELDS:
        if field in data:
            data[field] = _num(data[field])
    for item in data.get("items") or []:
        for field in _ITEM_NUMERIC_FIELDS:
            if field in item:
                item[field] = _num(item[field])
    return data


# --------------------------------------------------------------------------- #
# Confidence — a *measured* score from the model's token probability
# distribution, NOT a number the model reports about itself.
# --------------------------------------------------------------------------- #
# When we ask Ollama for `logprobs`, every generated token comes back with the
# log-probability the model assigned to it while decoding. A field's value is
# some contiguous run of those tokens (e.g. the digits of "540.00"). We score a
# field as the GEOMETRIC MEAN of its value-tokens' probabilities:
#
#       confidence(field) = exp( mean_i  log p_i )   over the value's tokens
#
# That is a real property of the output distribution: if the model was torn
# between "540" and "340" for a digit, that token's probability is ~0.5 and it
# drags the field's confidence down; a digit it was certain about sits near 1.0.
# Structural/key tokens ({ , " , "vendor_name": ) are near-certain and are
# excluded — we only score the tokens that form the *value* the user sees.
_HEADER_STR_FIELDS = (
    "vendor_name", "vendor_tin", "vendor_address", "receipt_number",
    "receipt_date", "discount_type", "currency", "category",
)
_HEADER_CONF_FIELDS = _HEADER_STR_FIELDS + _TOP_LEVEL_NUMERIC_FIELDS
_ITEM_CONF_FIELDS = ("description", "quantity", "unit_price", "amount")

# A JSON value literal: null, a quoted string, a number (with optional commas),
# or a boolean. Used to grab exactly the value that follows a `"key":`.
_JSON_VALUE_RE = r'(null|"(?:[^"\\]|\\.)*"|-?\d[\d,]*(?:\.\d+)?|true|false)'


def _logprob_token_spans(logprobs) -> tuple[list[tuple[int, int, float]], str]:
    """Turn Ollama's per-token logprobs into [(start, end, logprob)] character
    spans over the reconstructed output text. The reconstruction is exact
    (verified: "".join(tokens) == message.content), so these offsets line up
    with the JSON we parse the fields out of."""
    spans: list[tuple[int, int, float]] = []
    parts: list[str] = []
    pos = 0
    for entry in logprobs or []:
        # Support both the ollama object (.token/.logprob) and a plain dict.
        tok = getattr(entry, "token", None)
        lp = getattr(entry, "logprob", None)
        if tok is None and isinstance(entry, dict):
            tok, lp = entry.get("token"), entry.get("logprob")
        if tok is None or lp is None:
            continue
        spans.append((pos, pos + len(tok), float(lp)))
        parts.append(tok)
        pos += len(tok)
    return spans, "".join(parts)


def _span_confidence(spans, a: int, b: int) -> float | None:
    """Geometric-mean probability of the tokens overlapping char range [a, b)."""
    lps = [lp for (s, e, lp) in spans if s < b and e > a]
    if not lps:
        return None
    return math.exp(sum(lps) / len(lps))


def _geomean(probs) -> float | None:
    vals = [p for p in probs if p is not None and p > 0]
    if not vals:
        return None
    return math.exp(sum(math.log(p) for p in vals) / len(vals))


def _value_span_after_key(text: str, key: str, start: int = 0):
    """Char span (a, b) of the value literal following `"key":`, searching from
    `start`. Returns None if the key isn't found."""
    m = re.search(r'"%s"\s*:\s*%s' % (re.escape(key), _JSON_VALUE_RE), text[start:])
    if not m:
        return None
    return start + m.start(1), start + m.end(1)


def _match_bracket(text: str, open_idx: int, opener: str, closer: str) -> int:
    """Index just past the bracket that matches the one at `open_idx`, string-aware."""
    depth = 0
    in_str = esc = False
    for i in range(open_idx, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == opener:
            depth += 1
        elif c == closer:
            depth -= 1
            if depth == 0:
                return i + 1
    return len(text)


def _score_raw_items(text: str, spans) -> list[dict]:
    """Per-item field confidences, in the order items appear in the raw output."""
    out: list[dict] = []
    im = re.search(r'"items"\s*:\s*\[', text)
    if not im:
        return out
    arr_end = _match_bracket(text, im.end() - 1, "[", "]")
    cursor = im.end()
    while True:
        ob = text.find("{", cursor, arr_end)
        if ob == -1:
            break
        oe = _match_bracket(text, ob, "{", "}")
        conf: dict[str, float] = {}
        for key in _ITEM_CONF_FIELDS:
            span = _value_span_after_key(text, key, ob)
            if not span or span[0] >= oe:
                continue
            if text[span[0]:span[1]] == "null":
                continue
            p = _span_confidence(spans, *span)
            if p is not None:
                conf[key] = p
        out.append(conf)
        cursor = oe
    return out


def compute_extraction_confidence(logprobs, orig_json: dict, data: "ReceiptData") -> dict:
    """Build the confidence report for one extraction, straight from the model's
    token logprobs. Returns:

        {"overall": float|None,                  # geo-mean over all scored values
         "fields": {field: prob, ...},           # header/summary fields, 0..1
         "items":  [{field: prob, ...}, ...]}    # aligned to data.items

    Only values the model actually printed are scored. Numeric header fields are
    gated on matching the final value, so a figure the reconciler *re-derived*
    (rather than read) is honestly left unscored instead of borrowing a token
    probability that no longer applies."""
    spans, text = _logprob_token_spans(logprobs)
    empty = {"overall": None, "fields": {}, "items": []}
    if not spans or not text:
        return empty

    fields: dict[str, float] = {}
    for key in _HEADER_CONF_FIELDS:
        fv = getattr(data, key, None)
        if fv is None:
            continue
        span = _value_span_after_key(text, key)
        if not span:
            continue
        literal = text[span[0]:span[1]]
        if literal == "null":
            continue
        # Gate numeric fields on value-equality: if post-processing changed the
        # number that lands in this field, its read-confidence no longer applies.
        if key in _TOP_LEVEL_NUMERIC_FIELDS and not _num_close(_num(literal), _num(fv)):
            continue
        p = _span_confidence(spans, *span)
        if p is not None:
            fields[key] = p

    # Map raw-item confidences onto the final (cleaned/de-duped) items by amount,
    # then description — cleaning never changes an item's amount, so it's a stable key.
    raw_items = orig_json.get("items") or []
    raw_conf = _score_raw_items(text, spans)
    items: list[dict] = []
    used: set[int] = set()
    for it in data.items:
        idx = _best_raw_item(it, raw_items, used)
        if idx is not None and idx < len(raw_conf):
            used.add(idx)
            items.append(raw_conf[idx])
        else:
            items.append({})

    probs = list(fields.values()) + [c.get("amount") for c in items]
    return {"overall": _geomean(probs), "fields": fields, "items": items}


def _num_close(a, b, tol: float = 0.01) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= tol


def _best_raw_item(final_item, raw_items, used: set[int]) -> int | None:
    """Index of the unused raw item that best matches a final line item."""
    amt = _num(getattr(final_item, "amount", None))
    if amt is not None:
        for j, ri in enumerate(raw_items):
            if j not in used and _num_close(_num(ri.get("amount")), amt):
                return j
    desc = re.sub(r"[^a-z0-9]", "", (getattr(final_item, "description", "") or "").lower())
    if desc:
        for j, ri in enumerate(raw_items):
            if j in used:
                continue
            rd = re.sub(r"[^a-z0-9]", "", (ri.get("description") or "").lower())
            if rd and (rd in desc or desc in rd):
                return j
    return None

# --------------------------------------------------------------------------- #
# Config
#
# Everything below is overridable via environment variables so the same code runs
# on a laptop demo and on production hardware without edits. Defaults are tuned
# for a single local Ollama on a modest machine.
# --------------------------------------------------------------------------- #
def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() not in ("0", "false", "no", "off", "")


DB_PATH = Path(os.getenv("LEDGER_DB_PATH", str(Path(__file__).parent / "ledger.db")))

# Input guardrail: a generous hard ceiling (bad/hostile uploads are rejected),
# but ordinary large phone photos are accepted and shrunk by preprocess_image().
MAX_IMAGE_BYTES = _env_int("OCR_MAX_IMAGE_BYTES", 25 * 1024 * 1024)  # 25 MB
ALLOWED_CONTENT_TYPES = {
    "image/png", "image/jpeg", "image/jpg", "image/webp", "image/bmp",
    "image/tiff", "image/gif", "application/pdf",
}

# Vision preprocessing. Downscaling the longest edge to ~1600px roughly halves
# the image tokens a phone photo would otherwise consume, with no measurable
# accuracy loss on legible receipts, and honors EXIF orientation so rotated
# photos read correctly. Set OCR_MAX_IMAGE_DIM=0 to disable resizing entirely.
OCR_MAX_IMAGE_DIM = _env_int("OCR_MAX_IMAGE_DIM", 1600)
OCR_JPEG_QUALITY = _env_int("OCR_JPEG_QUALITY", 88)
# Rasterization DPI for PDF pages (higher = sharper but slower/larger).
PDF_RENDER_SCALE = _env_float("OCR_PDF_RENDER_SCALE", 2.0)  # ~144 DPI
PDF_MAX_PAGES = _env_int("OCR_PDF_MAX_PAGES", 1000)

# Ollama runtime options.
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "30m")  # keep the model resident
OCR_NUM_CTX = _env_int("OCR_NUM_CTX", 8192)
OCR_NUM_PREDICT = _env_int("OCR_NUM_PREDICT", 1024)
# How many extractions to run concurrently against Ollama in a batch. The real
# throughput ceiling is the server's OLLAMA_NUM_PARALLEL; match this to it.
OCR_CONCURRENCY = max(1, _env_int("OCR_CONCURRENCY", 3))

# LLMOps: starting an MLflow run per extraction is meaningful overhead (and, on a
# shared SQLite backend, lock contention) when importing thousands of pages.
# Allow disabling it or sampling a fraction of calls for production bulk loads.
MLFLOW_ENABLED = _env_bool("MLFLOW_ENABLED", True)
MLFLOW_SAMPLE_RATE = _env_float("MLFLOW_SAMPLE_RATE", 1.0)

# Text-only model used by the SQL agent, the RAG answerer, and the ReAct planner.
# qwen2.5:7b reasons/routes and summarizes numbers far more reliably than a 3B model
# (which mis-routed tools, looped, and garbled amounts). It runs partly on CPU on a
# 4GB GPU so it's a bit slower per turn — worth it for correct answers. Overridable
# via AGENT_MODEL env (e.g. "llama3.2:3b" for faster/smaller on constrained hosts).
AGENT_MODEL = os.environ.get("AGENT_MODEL", "qwen2.5:latest")
# Embedding model used by the RAG retriever. Small (~275 MB), fast, local.
EMBED_MODEL = os.environ.get("EMBED_MODEL", "nomic-embed-text")

if MLFLOW_ENABLED:
    mlflow.set_experiment("stai_ocr_receipts")


# --------------------------------------------------------------------------- #
# LLMOps helper — an MLflow run that becomes a no-op when tracing is disabled or
# not sampled, so the extraction/agent code stays identical either way.
# --------------------------------------------------------------------------- #
class _NullRun:
    """Stand-in for an MLflow run that swallows every log_* call."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _traced_run(run_name: str):
    """Return an MLflow run context, or a no-op when monitoring is off/unsampled.

    Delegates to _fresh_run so it inherits the self-healing behaviour (clearing a
    run left dangling by an abandoned request), which matters because batch
    extraction opens runs from worker threads. Sampling keeps a representative
    fraction of traces while shedding per-call overhead on large bulk imports."""
    return _fresh_run(run_name)


def _mlog_metric(key: str, value) -> None:
    if MLFLOW_ENABLED and mlflow.active_run() is not None:
        mlflow.log_metric(key, value)


def _mlog_param(key: str, value) -> None:
    if MLFLOW_ENABLED and mlflow.active_run() is not None:
        mlflow.log_param(key, value)


# --------------------------------------------------------------------------- #
# SQLite connection helper — WAL mode + a busy timeout so concurrent writers
# (e.g. many batch workers saving receipts at once) queue instead of erroring out
# with "database is locked". Applied to every read/write connection.
# --------------------------------------------------------------------------- #
_SQLITE_BUSY_TIMEOUT_MS = _env_int("SQLITE_BUSY_TIMEOUT_MS", 30_000)


def _connect(path: Path | str = DB_PATH) -> sqlite3.Connection:
    con = sqlite3.connect(path, timeout=_SQLITE_BUSY_TIMEOUT_MS / 1000)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        con.execute(f"PRAGMA busy_timeout={_SQLITE_BUSY_TIMEOUT_MS}")
    except sqlite3.OperationalError:
        pass
    return con


def _fresh_run(run_name: str):
    """Start an MLflow run, first clearing any run left dangling by a previously
    abandoned request. MLflow's active-run state is process-global, so if a
    streaming generator (agent_stream) is abandoned when a client disconnects, its
    run can stay 'active' and make every later start_run() raise 'Run is already
    active'. Ending any lingering run first makes each call self-healing.

    Honors the MLFLOW_ENABLED / MLFLOW_SAMPLE_RATE knobs: when tracing is off or
    this call isn't sampled it returns a no-op run, so bulk imports don't pay the
    per-call MLflow overhead."""
    import random

    if not MLFLOW_ENABLED or (MLFLOW_SAMPLE_RATE < 1.0 and random.random() > MLFLOW_SAMPLE_RATE):
        return _NullRun()
    try:
        if mlflow.active_run() is not None:
            mlflow.end_run()
    except Exception:  # noqa: BLE001
        pass
    try:
        return mlflow.start_run(run_name=run_name)
    except Exception:  # noqa: BLE001 - a cross-thread leak: force-end and retry once
        try:
            mlflow.end_run()
        except Exception:  # noqa: BLE001
            pass
        return mlflow.start_run(run_name=run_name)


# --------------------------------------------------------------------------- #
# 1. Structured Outputs — Pydantic schema
# --------------------------------------------------------------------------- #
class LineItem(BaseModel):
    description: Optional[str] = None
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    amount: Optional[float] = None


class ReceiptData(BaseModel):
    vendor_name: Optional[str] = None
    vendor_tin: Optional[str] = None
    vendor_address: Optional[str] = None
    receipt_number: Optional[str] = None
    receipt_date: Optional[str] = None
    items: list[LineItem] = Field(default_factory=list)
    subtotal: Optional[float] = None
    vatable_sales: Optional[float] = None
    vat_exempt_sales: Optional[float] = None
    zero_rated_sales: Optional[float] = None
    vat_amount: Optional[float] = None
    discount: Optional[float] = None
    discount_type: Optional[str] = None
    total_amount: Optional[float] = None
    cash: Optional[float] = None
    change: Optional[float] = None
    currency: Optional[str] = None
    category: Optional[str] = None  # one of VALID_CATEGORIES; see categorize()


# --------------------------------------------------------------------------- #
# 1b. Expense categorization — a fixed, small taxonomy for the dashboard
# --------------------------------------------------------------------------- #
# The vision model is asked to pick one of these at extraction time. We never
# trust that blindly: categorize() validates the model's answer and, when it is
# missing or off-list, falls back to a keyword heuristic on the vendor name and
# item descriptions, then finally to "Other". Keeping this list tiny keeps the
# pie chart readable and the model's choices consistent.
VALID_CATEGORIES = ("Food", "Shopping", "Health", "Other")

# Checked in this order; first hit wins. Health before Food/Shopping so a
# "pharmacy" never gets mislabeled by a stray generic word.
_CATEGORY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("Health", ("pharmacy", "drug", "drugstore", "mercury", "watson", "clinic",
                "hospital", "medical", "medicine", "dental", "optical", "health",
                "wellness", "apothecary", "rx")),
    ("Food", ("restaurant", "cafe", "coffee", "grill", "kitchen", "food", "dining",
              "diner", "bakery", "pizza", "burger", "chicken", "bbq", "eatery",
              "bistro", "resto", "lunch", "meal", "tea", "juice", "snack",
              "catering", "canteen", "grocery", "groceries", "supermarket",
              "market", "deli", "pepper", "jollibee", "mcdo", "starbucks")),
    ("Shopping", ("mart", "store", "shop", "mall", "retail", "department",
                  "boutique", "hardware", "apparel", "clothing", "clothes",
                  "electronics", "fashion", "shoes", "lazada", "shopee",
                  "robinson", "watsons")),
]


def _match_category(text: str) -> str:
    """Keyword-match free text (vendor + items) to a category; 'Other' if none."""
    low = (text or "").lower()
    for cat, keywords in _CATEGORY_KEYWORDS:
        if any(kw in low for kw in keywords):
            return cat
    return "Other"


def _normalize_model_category(value) -> Optional[str]:
    """Return a canonical VALID_CATEGORIES value if the model's answer maps to
    one, else None (so the caller falls back to the keyword heuristic)."""
    if not value:
        return None
    v = str(value).strip().lower()
    synonyms = {
        "food": "Food", "food & dining": "Food", "dining": "Food",
        "restaurant": "Food", "groceries": "Food", "grocery": "Food",
        "shopping": "Shopping", "retail": "Shopping", "retail/shopping": "Shopping",
        "merchandise": "Shopping",
        "health": "Health", "health/pharmacy": "Health", "pharmacy": "Health",
        "medical": "Health",
        "other": "Other",
    }
    return synonyms.get(v)


def categorize(data: "ReceiptData") -> str:
    """Resolve a receipt's spending category. Trusts the model's `category` when
    it maps to the fixed taxonomy; otherwise infers from vendor + items."""
    from_model = _normalize_model_category(getattr(data, "category", None))
    if from_model:
        return from_model
    items = " ".join(i.description or "" for i in getattr(data, "items", []) or [])
    return _match_category(f"{data.vendor_name or ''} {items}")


# --------------------------------------------------------------------------- #
# 1c. Image / PDF preprocessing — normalize the bytes the vision model sees
# --------------------------------------------------------------------------- #
def preprocess_image(image_bytes: bytes) -> bytes:
    """Normalize a raster image for the vision model:
      - honor EXIF orientation (rotated phone photos read correctly)
      - downscale the longest edge to OCR_MAX_IMAGE_DIM
      - re-encode as JPEG

    Downscaling is the single biggest per-image speedup: on the sample receipt it
    cut image prefill from 4414 to 3123 tokens (~30%) with identical extraction.
    Best-effort — returns the original bytes unchanged if Pillow is unavailable or
    the bytes can't be decoded (the model still gets a valid image to try)."""
    if Image is None or not image_bytes:
        return image_bytes
    try:
        im = Image.open(io.BytesIO(image_bytes))
        im = ImageOps.exif_transpose(im)
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        w, h = im.size
        longest = max(w, h)
        if OCR_MAX_IMAGE_DIM and longest > OCR_MAX_IMAGE_DIM:
            scale = OCR_MAX_IMAGE_DIM / longest
            im = im.resize((max(1, round(w * scale)), max(1, round(h * scale))), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=OCR_JPEG_QUALITY)
        return buf.getvalue()
    except Exception:  # noqa: BLE001 - never let normalization break extraction
        return image_bytes


def _is_pdf(image_bytes: bytes, content_type: str | None) -> bool:
    if content_type and "pdf" in content_type.lower():
        return True
    return image_bytes[:5] == b"%PDF-"


def pdf_to_page_images(pdf_bytes: bytes) -> list[bytes]:
    """Rasterize each page of a PDF to a preprocessed JPEG. Requires pypdfium2;
    raises GuardrailError with an actionable message if it isn't installed."""
    if pdfium is None:
        raise GuardrailError(
            "PDF support requires the 'pypdfium2' package (pip install pypdfium2)."
        )
    pages: list[bytes] = []
    doc = pdfium.PdfDocument(pdf_bytes)
    try:
        n = min(len(doc), PDF_MAX_PAGES)
        for i in range(n):
            page = doc[i]
            bitmap = page.render(scale=PDF_RENDER_SCALE)
            pil = bitmap.to_pil()
            buf = io.BytesIO()
            pil.save(buf, format="JPEG", quality=OCR_JPEG_QUALITY)
            pages.append(preprocess_image(buf.getvalue()))
    finally:
        doc.close()
    return pages


def iter_page_images(image_bytes: bytes, content_type: str | None) -> list[bytes]:
    """Expand an upload into one preprocessed image per page: a single normalized
    image for a raster upload, or N page images for a PDF. This is the seam that
    lets a 1000-page PDF flow through the same per-page extraction path."""
    if _is_pdf(image_bytes, content_type):
        return pdf_to_page_images(image_bytes)
    return [preprocess_image(image_bytes)]


# --------------------------------------------------------------------------- #
# 2. Guardrails — input + output validation
# --------------------------------------------------------------------------- #
class GuardrailError(ValueError):
    """Raised when an input or output fails a safety/validity check."""


def validate_input(image_bytes: bytes, content_type: str | None) -> None:
    if not image_bytes:
        raise GuardrailError("Empty file.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise GuardrailError(f"File exceeds the {MAX_IMAGE_BYTES // (1024 * 1024)}MB limit.")
    if content_type and content_type not in ALLOWED_CONTENT_TYPES:
        raise GuardrailError(f"Unsupported file type: {content_type}")


def validate_output(raw: dict) -> ReceiptData:
    """Schema-validate the model's JSON. Coerces stray strings like '120.00'
    into floats; rejects anything that doesn't fit the contract at all."""
    try:
        return ReceiptData.model_validate(raw)
    except ValidationError as exc:
        raise GuardrailError(f"Model output failed schema validation: {exc}") from exc


# --------------------------------------------------------------------------- #
# 3. Disambiguation — decide if a human needs to confirm before we trust it
# --------------------------------------------------------------------------- #
def needs_disambiguation(data: ReceiptData) -> list[str]:
    """Return reasons a record should be confirmed by a human before being
    saved to the ledger, instead of being auto-accepted."""
    reasons = list(reconcile(data.model_dump()))
    if data.total_amount is None:
        reasons.append("No total amount was read off the receipt.")
    if data.vendor_tin is None and data.discount_type:
        reasons.append(
            f"A '{data.discount_type}' discount was found but no vendor TIN was "
            "read — confirm this is the correct vendor before filing."
        )
    if not data.items:
        reasons.append("No line items were extracted.")
    return reasons


# --------------------------------------------------------------------------- #
# 4. LLMOps Monitoring — MLflow-wrapped extraction
# --------------------------------------------------------------------------- #
def _run_vision_model(
    image_bytes: bytes, model: str
) -> tuple[ReceiptData, list[str], dict, dict]:
    """Normalize the image, call the vision model, and run the full cleanup +
    validation + disambiguation + confidence pipeline. This is the SINGLE hot path
    shared by both the single-file (`extract_receipt_validated`) and batch
    (`_extract_page_saved`) entry points, so they can never drift.

    Returns (data, disambiguation_reasons, confidence, raw_response). No MLflow, no
    input validation, and no image normalization here — callers own those (single-
    file via extract_receipt_validated, batch via iter_page_images), so the image is
    preprocessed exactly once. Uses `_chat` (not raw ollama.chat) so hidden
    'thinking' is disabled and transient endpoint hiccups retry — required for the
    shared remote Ollama endpoint."""
    if ollama is None:
        raise RuntimeError("The `ollama` package is not installed.")

    # Ask for the per-token probability distribution so confidence is measured,
    # not guessed (only when the client supports it).
    logprob_kwargs = {"logprobs": True, "top_logprobs": 1} if _OLLAMA_SUPPORTS_LOGPROBS else {}
    chat_args = dict(
        model=model,
        messages=[{"role": "user", "content": EXTRACTION_PROMPT, "images": [image_bytes]}],
        format="json",
        # num_ctx: prompt + tokenized image can exceed Ollama's 4096 default.
        options={"temperature": 0, "num_predict": OCR_NUM_PREDICT, "num_ctx": OCR_NUM_CTX},
        keep_alive=OLLAMA_KEEP_ALIVE,
        **logprob_kwargs,
    )
    response = _chat(**chat_args)
    content = response["message"]["content"]
    # A reasoning model can occasionally emit empty content even with thinking
    # disabled; retry once so an empty read doesn't 500 on parsing.
    if not (content or "").strip():
        response = _chat(**chat_args)
        content = response["message"]["content"]

    raw = _coerce_json(content)
    # Keep a pristine copy of the model's own items (pre-cleanup) so confidence can
    # be aligned back to the values it actually printed.
    orig_json = json.loads(json.dumps(raw))
    raw = _fix_payment_fields(_dedupe_items(_remap_summary_lines(_clean_items(raw))))
    raw = _coerce_numeric_fields(raw)
    data = validate_output(raw)
    data.category = categorize(data)  # normalize to the fixed taxonomy
    reasons = needs_disambiguation(data)

    try:
        confidence = compute_extraction_confidence(response.get("logprobs"), orig_json, data)
    except Exception:  # noqa: BLE001 - confidence must never break extraction
        confidence = {"overall": None, "fields": {}, "items": []}
    return data, reasons, confidence, response


def extract_receipt_validated(
    image_bytes: bytes, model: str = DEFAULT_MODEL, content_type: str | None = None
) -> tuple[ReceiptData, list[str], dict]:
    """Full guarded pipeline for a single raster image: validate input -> normalize
    the image -> call the vision model -> clean up -> validate schema -> check for
    disambiguation needs -> measure confidence.

    Returns (data, disambiguation_reasons, confidence). `confidence` is a measured
    report derived from the model's token-level logprobs (see
    compute_extraction_confidence) — an honest read of the output distribution,
    never a self-reported number. For PDFs, expand with iter_page_images first."""
    with _fresh_run(f"extract_{int(time.time())}"):
        _mlog_param("model", model)
        _mlog_param("image_bytes", len(image_bytes))
        t0 = time.time()
        try:
            validate_input(image_bytes, content_type)
            # Normalize once here (EXIF-rotate + downscale + re-encode); the batch
            # path normalizes in iter_page_images instead.
            image_bytes = preprocess_image(image_bytes)
            data, reasons, confidence, response = _run_vision_model(image_bytes, model)

            _mlog_metric("latency_seconds", time.time() - t0)
            # token usage isn't always returned by every Ollama build; log if present
            _mlog_metric("prompt_eval_count", response.get("prompt_eval_count", 0))
            _mlog_metric("eval_count", response.get("eval_count", 0))
            _mlog_metric("items_extracted", len(data.items))
            _mlog_metric("needs_disambiguation", int(bool(reasons)))
            if confidence.get("overall") is not None:
                _mlog_metric("extraction_confidence", confidence["overall"])
            _mlog_metric("error", 0)
            return data, reasons, confidence
        except Exception as exc:
            _mlog_metric("error", 1)
            _mlog_param("error_message", str(exc)[:250])
            _mlog_metric("latency_seconds", time.time() - t0)
            raise


def _extract_page_saved(
    page_bytes: bytes, model: str, source_file: str, page_no: int | None
) -> dict:
    """Extract one already-preprocessed page image and persist it. Returns a
    per-page result dict. Never raises — failures are captured in the dict so one
    bad page can't abort a large batch. Indexing is deferred (index=False) and
    backfilled lazily on the next search."""
    label = source_file if page_no is None else f"{source_file}#p{page_no}"
    try:
        data, reasons, confidence, _ = _run_vision_model(page_bytes, model)
        receipt_id = save_receipt(
            data, label, flagged=bool(reasons), confidence=confidence, index=False
        )
        return {
            "source_file": source_file,
            "page": page_no,
            "receipt_id": receipt_id,
            "data": data.model_dump(),
            "needs_review": bool(reasons),
            "review_reasons": reasons,
            "confidence": confidence,
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001 - isolate per-page failures
        return {
            "source_file": source_file,
            "page": page_no,
            "receipt_id": None,
            "data": None,
            "needs_review": False,
            "review_reasons": [],
            "error": str(exc)[:500],
        }


def extract_batch(
    files: list[tuple[bytes, str | None, str]],
    model: str = DEFAULT_MODEL,
    concurrency: int | None = None,
    progress=None,
) -> list[dict]:
    """Extract many uploads at once, expanding PDFs to one result per page, and
    persist each. `files` is a list of (raw_bytes, content_type, source_file).

    Pages are processed through a bounded thread pool so the vision calls overlap
    (throughput scales with the Ollama server's OLLAMA_NUM_PARALLEL, which this
    `concurrency` should match). Failures are isolated per page. `progress`, if
    given, is called with (done, total) after each page completes. Returns one
    result dict per page in completion order.

    This is the 1000-page path: memory stays bounded to the pages in flight, one
    unreadable page never aborts the run, and the heavy embedding step is deferred
    to a lazy backfill so import throughput isn't gated on it."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    concurrency = max(1, concurrency or OCR_CONCURRENCY)

    # Expand every upload into per-page (bytes, source, page_no) work items first.
    # PDFs may explode into many pages; a plain image is a single page (page_no=None).
    work: list[tuple[bytes, str, int | None]] = []
    for raw, content_type, source_file in files:
        try:
            validate_input(raw, content_type)
            pages = iter_page_images(raw, content_type)
        except Exception as exc:  # noqa: BLE001 - surface as a failed result, keep going
            work.append((b"__error__:" + str(exc)[:400].encode(), source_file, None))
            continue
        if len(pages) == 1:
            work.append((pages[0], source_file, None))
        else:
            for i, pb in enumerate(pages, start=1):
                work.append((pb, source_file, i))

    total = len(work)
    results: list[dict] = []
    done = 0

    with _traced_run(f"extract_batch_{int(time.time())}"):
        _mlog_param("model", model)
        _mlog_param("files", len(files))
        _mlog_param("pages", total)
        _mlog_param("concurrency", concurrency)
        t0 = time.time()

        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = []
            for page_bytes, source_file, page_no in work:
                if page_bytes.startswith(b"__error__:"):
                    results.append({
                        "source_file": source_file, "page": page_no, "receipt_id": None,
                        "data": None, "needs_review": False, "review_reasons": [],
                        "error": page_bytes[len(b"__error__:"):].decode(errors="replace"),
                    })
                    done += 1
                    if progress:
                        progress(done, total)
                    continue
                futures.append(
                    pool.submit(_extract_page_saved, page_bytes, model, source_file, page_no)
                )
            for fut in as_completed(futures):
                results.append(fut.result())
                done += 1
                if progress:
                    progress(done, total)

        ok = sum(1 for r in results if r["error"] is None)
        _mlog_metric("pages", total)
        _mlog_metric("succeeded", ok)
        _mlog_metric("failed", total - ok)
        _mlog_metric("latency_seconds", time.time() - t0)

    return results


# --------------------------------------------------------------------------- #
# 5. Memory — persistent SQLite ledger
# --------------------------------------------------------------------------- #
def init_db() -> None:
    with _connect() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS receipts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_file TEXT,
                processed_at TEXT,
                vendor_name TEXT,
                vendor_tin TEXT,
                vendor_address TEXT,
                receipt_number TEXT,
                receipt_date TEXT,
                subtotal REAL,
                vatable_sales REAL,
                vat_exempt_sales REAL,
                zero_rated_sales REAL,
                vat_amount REAL,
                discount REAL,
                discount_type TEXT,
                total_amount REAL,
                cash REAL,
                change REAL,
                currency TEXT,
                category TEXT,
                flagged INTEGER
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS line_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                receipt_id INTEGER,
                description TEXT,
                quantity REAL,
                unit_price REAL,
                amount REAL,
                FOREIGN KEY (receipt_id) REFERENCES receipts(id)
            )
            """
        )
        
        # Migration: add missing columns if they don't exist
        # This allows the schema to evolve without losing existing data
        cursor = con.execute("PRAGMA table_info(receipts)")
        existing_columns = {row[1] for row in cursor.fetchall()}
        
        columns_to_add = [
            ("vendor_address", "TEXT"),
            ("vatable_sales", "REAL"),
            ("vat_exempt_sales", "REAL"),
            ("zero_rated_sales", "REAL"),
            ("discount_type", "TEXT"),
            ("category", "TEXT"),
            # Measured OCR confidence: overall score (0..1) + per-field JSON.
            ("confidence", "REAL"),
            ("field_confidence", "TEXT"),
        ]
        
        for col_name, col_type in columns_to_add:
            if col_name not in existing_columns:
                try:
                    con.execute(f"ALTER TABLE receipts ADD COLUMN {col_name} {col_type}")
                except sqlite3.OperationalError:
                    pass  # Column already exists or other error; ignore
        
        con.commit()


def save_receipt(data: ReceiptData, source_file: str, flagged: bool,
                 confidence: dict | None = None, index: bool = True) -> int:
    """Persist a receipt + its line items (and its measured confidence) and return
    the new id.

    `index=True` also embeds the receipt for semantic search inline. Bulk imports
    pass `index=False` to skip the per-receipt embedding call (a meaningful cost at
    thousands of pages); ensure_index() then backfills the embeddings lazily on the
    next semantic search, so nothing is lost."""
    init_db()
    overall_conf = (confidence or {}).get("overall")
    field_conf_json = json.dumps(confidence) if confidence else None
    with _connect() as con:
        cur = con.execute(
            """
            INSERT INTO receipts (source_file, processed_at, vendor_name, vendor_tin,
                vendor_address, receipt_number, receipt_date, subtotal, vatable_sales,
                vat_exempt_sales, zero_rated_sales, vat_amount, discount, discount_type,
                total_amount, cash, change, currency, category, flagged,
                confidence, field_confidence)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                source_file,
                datetime.utcnow().isoformat(),
                data.vendor_name,
                data.vendor_tin,
                data.vendor_address,
                data.receipt_number,
                data.receipt_date,
                data.subtotal,
                data.vatable_sales,
                data.vat_exempt_sales,
                data.zero_rated_sales,
                data.vat_amount,
                data.discount,
                data.discount_type,
                data.total_amount,
                data.cash,
                data.change,
                data.currency,
                categorize(data),
                int(flagged),
                overall_conf,
                field_conf_json,
            ),
        )
        receipt_id = cur.lastrowid
        for item in data.items:
            con.execute(
                "INSERT INTO line_items (receipt_id, description, quantity, unit_price, amount) "
                "VALUES (?,?,?,?,?)",
                (receipt_id, item.description, item.quantity, item.unit_price, item.amount),
            )

    # RAG: build + embed a text representation of this receipt so it can be found
    # by semantic search later. Best-effort — never let indexing block a save.
    if index:
        try:
            index_receipt(receipt_id, data, source_file)
        except Exception:  # noqa: BLE001
            pass
    return receipt_id


def list_receipts(limit: int = 100) -> list[dict]:
    init_db()
    with _connect() as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT * FROM receipts ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_receipt_items(receipt_id: int) -> list[dict]:
    """The line items for one receipt, ordered as stored."""
    init_db()
    with _connect() as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT description, quantity, unit_price, amount "
            "FROM line_items WHERE receipt_id = ? ORDER BY id",
            (receipt_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_receipt(receipt_id: int) -> dict | None:
    """Return one receipt's full header row (all columns), or None if not found."""
    init_db()
    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        row = con.execute(
            "SELECT * FROM receipts WHERE id = ?", (receipt_id,)
        ).fetchone()
        return dict(row) if row else None


# Header fields a user is allowed to edit from the receipt detail page.
_EDITABLE_RECEIPT_FIELDS = (
    "vendor_name", "vendor_tin", "vendor_address", "receipt_number", "receipt_date",
    "subtotal", "vatable_sales", "vat_exempt_sales", "zero_rated_sales", "vat_amount",
    "discount", "discount_type", "total_amount", "cash", "change", "currency", "category",
)
_EDITABLE_NUMERIC_FIELDS = {
    "subtotal", "vatable_sales", "vat_exempt_sales", "zero_rated_sales", "vat_amount",
    "discount", "total_amount", "cash", "change",
}


def update_receipt(receipt_id: int, fields: dict) -> dict | None:
    """Update a receipt's editable header fields in place. Only whitelisted fields
    are written; numeric fields are coerced with the same parser used elsewhere.
    Returns the updated row, or None if the receipt doesn't exist. Re-indexes the
    receipt for RAG (best-effort) so semantic search reflects the edits."""
    init_db()
    updates: dict = {}
    for key, value in (fields or {}).items():
        if key not in _EDITABLE_RECEIPT_FIELDS:
            continue
        if key in _EDITABLE_NUMERIC_FIELDS:
            updates[key] = _num(value)
        else:
            v = None if value is None else str(value).strip()
            updates[key] = v or None
    with sqlite3.connect(DB_PATH) as con:
        if con.execute("SELECT id FROM receipts WHERE id = ?", (receipt_id,)).fetchone() is None:
            return None
        if updates:
            set_clause = ", ".join(f"{k} = ?" for k in updates)
            con.execute(
                f"UPDATE receipts SET {set_clause} WHERE id = ?",
                (*updates.values(), receipt_id),
            )
            con.commit()

    # Keep RAG search consistent with the edited values (never let this block a save).
    try:
        row = get_receipt(receipt_id)
        items = get_receipt_items(receipt_id)
        data = ReceiptData(
            **{k: row.get(k) for k in ReceiptData.model_fields if k != "items"},
            items=[LineItem(**it) for it in items],
        )
        index_receipt(receipt_id, data, row.get("source_file") or "")
    except Exception:  # noqa: BLE001
        pass
    return get_receipt(receipt_id)


def delete_receipt(receipt_id: int) -> bool:
    """Delete a receipt and everything derived from it — its line items AND its
    RAG embedding in receipt_docs — so it disappears from the ledger, the SQL
    agent, and semantic search alike. Returns True if a row was removed."""
    init_db()
    with _connect() as con:
        cur = con.execute("DELETE FROM receipts WHERE id = ?", (receipt_id,))
        con.execute("DELETE FROM line_items WHERE receipt_id = ?", (receipt_id,))
        # RAG memory: receipt_docs may not exist if semantic search was never used.
        try:
            con.execute("DELETE FROM receipt_docs WHERE receipt_id = ?", (receipt_id,))
        except sqlite3.OperationalError:
            pass
        con.commit()
        return cur.rowcount > 0


def backfill_categories() -> None:
    """Assign a category to any receipt saved before categorization existed,
    inferring from vendor name + its line items. Idempotent; only touches rows
    whose category is NULL/empty, so it is cheap to call on every dashboard load."""
    init_db()
    with _connect() as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT id, vendor_name FROM receipts WHERE category IS NULL OR category = ''"
        ).fetchall()
        for r in rows:
            items = con.execute(
                "SELECT description FROM line_items WHERE receipt_id = ?", (r["id"],)
            ).fetchall()
            text = (r["vendor_name"] or "") + " " + " ".join(
                (i["description"] or "") for i in items
            )
            con.execute(
                "UPDATE receipts SET category = ? WHERE id = ?",
                (_match_category(text), r["id"]),
            )
        con.commit()


def expense_summary(limit: int = 1000) -> dict:
    """Aggregate spending for the dashboard: grand total, receipt count,
    per-category totals (sorted high→low), the top category, and the dominant
    currency. Categorizes any legacy uncategorized receipts first."""
    backfill_categories()
    rows = list_receipts(limit=limit)
    by_category: dict[str, float] = {}
    currency_counts: dict[str, int] = {}
    total = 0.0
    for r in rows:
        amount = r.get("total_amount") or 0.0
        total += amount
        cat = r.get("category") or "Other"
        by_category[cat] = by_category.get(cat, 0.0) + amount
        cur = r.get("currency")
        if cur:
            currency_counts[cur] = currency_counts.get(cur, 0) + 1
    ordered = dict(sorted(by_category.items(), key=lambda kv: kv[1], reverse=True))
    top_category = next(iter(ordered), None)
    currency = max(currency_counts, key=currency_counts.get) if currency_counts else None
    return {
        "total": round(total, 2),
        "count": len(rows),
        "by_category": ordered,
        "top_category": top_category,
        "currency": currency,
        "mixed_currency": len(currency_counts) > 1,
    }


# --------------------------------------------------------------------------- #
# Income & budgets (personal-finance layer on top of the receipt ledger)
# --------------------------------------------------------------------------- #
def init_finance_tables() -> None:
    """Create the income + budget tables if absent. Idempotent, mirrors init_db()."""
    with _connect() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS income (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT,
                amount REAL,
                currency TEXT,
                income_date TEXT,
                recurring INTEGER DEFAULT 0,
                created_at TEXT
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS budgets (
                category TEXT PRIMARY KEY,
                monthly_limit REAL,
                currency TEXT
            )
            """
        )
        con.commit()


def _month_key(iso: str | None) -> str | None:
    """'2026-06-22' -> '2026-06'. None/blank/malformed -> None."""
    if iso and len(iso) >= 7 and re.match(r"^\d{4}-\d{2}", iso):
        return iso[:7]
    return None


def _receipt_month(r: dict) -> str | None:
    """The month a receipt belongs to. Prefer the printed receipt date; when it is
    missing or unparseable, fall back to when the receipt was added (processed_at)
    so an undated receipt still counts toward the timeline, totals, and budgets
    rather than silently vanishing."""
    return _month_key(r.get("receipt_date")) or _month_key(r.get("processed_at"))


def _month_range(start: str, end: str) -> list[str]:
    """Inclusive list of 'YYYY-MM' keys from start to end (both 'YYYY-MM')."""
    sy, sm = int(start[:4]), int(start[5:7])
    ey, em = int(end[:4]), int(end[5:7])
    out: list[str] = []
    y, m = sy, sm
    while (y, m) <= (ey, em):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def add_income(source: str, amount: float, currency: str | None,
               income_date: str | None, recurring: bool) -> int:
    """Record an income entry. A recurring=1 row is a monthly-salary template
    anchored at income_date; it is expanded across months at aggregation time."""
    init_finance_tables()
    with _connect() as con:
        cur = con.execute(
            "INSERT INTO income (source, amount, currency, income_date, recurring, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (source, amount, currency, income_date or date.today().isoformat(),
             int(bool(recurring)), datetime.utcnow().isoformat()),
        )
        con.commit()
        return cur.lastrowid


def list_income() -> list[dict]:
    init_finance_tables()
    with _connect() as con:
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT * FROM income ORDER BY income_date DESC, id DESC").fetchall()
        return [dict(r) for r in rows]


def delete_income(income_id: int) -> bool:
    init_finance_tables()
    with _connect() as con:
        cur = con.execute("DELETE FROM income WHERE id = ?", (income_id,))
        con.commit()
        return cur.rowcount > 0


def set_budget(category: str, monthly_limit: float, currency: str | None) -> None:
    """Upsert a monthly spending limit for a category."""
    init_finance_tables()
    with _connect() as con:
        con.execute(
            "INSERT INTO budgets (category, monthly_limit, currency) VALUES (?,?,?) "
            "ON CONFLICT(category) DO UPDATE SET monthly_limit=excluded.monthly_limit, "
            "currency=excluded.currency",
            (category, monthly_limit, currency),
        )
        con.commit()


def list_budgets() -> list[dict]:
    init_finance_tables()
    with _connect() as con:
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT * FROM budgets ORDER BY category").fetchall()
        return [dict(r) for r in rows]


def _income_by_month(latest_month: str | None) -> dict[str, float]:
    """Total income per 'YYYY-MM'. Recurring entries are expanded from their
    anchor month through latest_month (or their anchor month if that is later)."""
    by_month: dict[str, float] = {}
    for r in list_income():
        amt = r.get("amount") or 0.0
        mk = _month_key(r.get("income_date"))
        if not mk:
            continue
        if r.get("recurring"):
            end = latest_month if latest_month and latest_month >= mk else mk
            for m in _month_range(mk, end):
                by_month[m] = by_month.get(m, 0.0) + amt
        else:
            by_month[mk] = by_month.get(mk, 0.0) + amt
    return by_month


def _pct_change(current: float, prev: float) -> Optional[float]:
    """Percent change prev->current, rounded. None when there is no prior base."""
    if prev == 0:
        return None
    return round((current - prev) / abs(prev) * 100, 1)


def _prev_month(key: str) -> str:
    y, m = int(key[:4]), int(key[5:7])
    m -= 1
    if m < 1:
        m, y = 12, y - 1
    return f"{y:04d}-{m:02d}"


def analytics_summary(granularity: str = "month", year: int | None = None,
                      month: int | None = None, limit: int = 5000) -> dict:
    """Period-aware dashboard payload. `granularity` is "month" or "year"; `year`
    and `month` select the focused period (defaults to the latest with activity).

    Returns a `bars` series for the cashflow chart (monthly bars for the focused
    year, or yearly bars in year mode), plus period-scoped category totals, budget
    usage, top vendors, totals and period-over-period deltas — so every panel on
    the dashboard reflects the same selected period and stays consistent.
    """
    backfill_categories()
    init_finance_tables()
    receipts = list_receipts(limit=limit)
    granularity = granularity if granularity in ("year", "month", "all") else "month"

    # Per-receipt effective month + dominant currency.
    currency_counts: dict[str, int] = {}
    expense_by_month: dict[str, float] = {}
    for r in receipts:
        cur = r.get("currency")
        if cur:
            currency_counts[cur] = currency_counts.get(cur, 0) + 1
        mk = _receipt_month(r)
        if mk:
            expense_by_month[mk] = expense_by_month.get(mk, 0.0) + (r.get("total_amount") or 0.0)
    currency = max(currency_counts, key=currency_counts.get) if currency_counts else None

    # Expand income (incl. recurring) through the later of last activity / today.
    anchors = set(expense_by_month) | set(_income_by_month(None))
    today_key = date.today().strftime("%Y-%m")
    range_end = max(anchors | {today_key}) if anchors else today_key
    income_by_month = _income_by_month(range_end)

    all_months = sorted(set(expense_by_month) | set(income_by_month))
    data_years = sorted({int(m[:4]) for m in all_months})
    latest_month = max(all_months) if all_months else today_key

    # Resolve the focused period (defaults to latest activity).
    if year is None:
        year = int(latest_month[:4])
    if month is None:
        month = int(latest_month[5:7]) if int(latest_month[:4]) == year else 12
    month = max(1, min(12, month))

    def _month_income(m):
        return income_by_month.get(m, 0.0)

    def _month_expense(m):
        return expense_by_month.get(m, 0.0)

    # Cashflow bars: months of the focused year (month mode) or one bar per year
    # (year mode and all-time both show every year).
    if granularity in ("year", "all"):
        bars = [
            {
                "key": str(y),
                "label": str(y),
                "income": round(sum(_month_income(m) for m in all_months if m.startswith(str(y))), 2),
                "expense": round(sum(_month_expense(m) for m in all_months if m.startswith(str(y))), 2),
            }
            for y in data_years
        ]
        focus_key = "all" if granularity == "all" else str(year)
    else:
        year_months = [m for m in all_months if m.startswith(f"{year:04d}")]
        bars = [
            {
                "key": m,
                "label": datetime(int(m[:4]), int(m[5:7]), 1).strftime("%b"),
                "income": round(_month_income(m), 2),
                "expense": round(_month_expense(m), 2),
            }
            for m in year_months
        ]
        focus_key = f"{year:04d}-{month:02d}"

    # Predicate: does an effective-month string fall in the focused scope?
    def _in_scope(mk: str | None) -> bool:
        if granularity == "all":
            return True  # all-time: every receipt counts
        if not mk:
            return False
        return mk.startswith(f"{year:04d}") if granularity == "year" else mk == focus_key

    # Scope-restricted receipts → category totals + vendors + count.
    by_category: dict[str, float] = {}
    vendor_totals: dict[str, dict] = {}
    scope_count = 0
    for r in receipts:
        if not _in_scope(_receipt_month(r)):
            continue
        scope_count += 1
        amt = r.get("total_amount") or 0.0
        cat = r.get("category") or "Other"
        by_category[cat] = by_category.get(cat, 0.0) + amt
        v = (r.get("vendor_name") or "Unknown").strip() or "Unknown"
        agg = vendor_totals.setdefault(v, {"vendor": v, "total": 0.0, "count": 0})
        agg["total"] += amt
        agg["count"] += 1

    by_category = {k: round(v, 2) for k, v in sorted(by_category.items(), key=lambda kv: kv[1], reverse=True)}
    top_category = next(iter(by_category), None)
    top_vendors = sorted(
        (dict(total=round(a["total"], 2), vendor=a["vendor"], count=a["count"])
         for a in vendor_totals.values()),
        key=lambda a: a["total"], reverse=True,
    )[:8]

    # Scope totals.
    if granularity == "all":
        scope_income = sum(income_by_month.values())
        budget_factor = max(1, len(all_months))  # monthly limit × months of data
    elif granularity == "year":
        scope_income = sum(_month_income(m) for m in all_months if m.startswith(f"{year:04d}"))
        budget_factor = 12  # a monthly limit becomes an annual allowance
    else:
        scope_income = _month_income(focus_key)
        budget_factor = 1
    scope_expense = sum(by_category.values())

    # Period-over-period deltas (none for all-time — there is no prior period).
    if granularity == "all":
        prev_income = prev_expense = 0.0
        prev_label = ""
        period_label = "All time"
    elif granularity == "year":
        prev_income = sum(_month_income(m) for m in all_months if m.startswith(f"{year - 1:04d}"))
        prev_expense = sum(_month_expense(m) for m in all_months if m.startswith(f"{year - 1:04d}"))
        prev_label = str(year - 1)
        period_label = str(year)
    else:
        pk = _prev_month(focus_key)
        prev_income = _month_income(pk)
        prev_expense = _month_expense(pk)
        prev_label = datetime(int(pk[:4]), int(pk[5:7]), 1).strftime("%b")
        period_label = datetime(year, month, 1).strftime("%B %Y")

    def _delta(cur_v, prev_v):
        return {"current": round(cur_v, 2), "prev": round(prev_v, 2), "pct": _pct_change(cur_v, prev_v)}

    mom = {
        "income": _delta(scope_income, prev_income),
        "expense": _delta(scope_expense, prev_expense),
        "net": _delta(scope_income - scope_expense, prev_income - prev_expense),
        "label": prev_label,
    }

    # Budgets scoped to the same period (limit scaled by the period length).
    budgets = []
    for b in list_budgets():
        limit_v = (b.get("monthly_limit") or 0.0) * budget_factor
        spent = by_category.get(b["category"], 0.0)
        budgets.append({
            "category": b["category"],
            "limit": round(limit_v, 2),
            "spent": round(spent, 2),
            "pct": round(spent / limit_v * 100, 1) if limit_v else None,
            "currency": b.get("currency") or currency,
        })

    return {
        "bars": bars,
        "focus_key": focus_key,
        "by_category": by_category,
        "top_category": top_category,
        "top_vendors": top_vendors,
        "budgets": budgets,
        "mom": mom,
        "income_total": round(scope_income, 2),
        "expense_total": round(scope_expense, 2),
        "net_total": round(scope_income - scope_expense, 2),
        "receipt_count": scope_count,
        "period": {
            "granularity": granularity,
            "year": year,
            "month": month,
            "label": period_label,
            "min_year": data_years[0] if data_years else year,
            "max_year": max(data_years[-1] if data_years else year, int(today_key[:4])),
        },
        "currency": currency,
        "mixed_currency": len(currency_counts) > 1,
    }


def get_latest_receipt_id() -> int | None:
    """Id of the most recently saved receipt (highest id), or None if the ledger is
    empty. Used to auto-scope a singular question to the latest upload."""
    init_db()
    con = _readonly_connection()
    try:
        row = con.execute("SELECT MAX(id) AS m FROM receipts").fetchone()
    finally:
        con.close()
    return int(row["m"]) if row and row["m"] is not None else None


def recent_receipts(max_gap_seconds: int = 180, limit: int = 12) -> list[dict]:
    """The most recent *upload batch*: the newest receipt plus any added back-to-back
    with it (each within `max_gap_seconds` of the previous by processed_at). Used to
    tell whether "my recent receipt" points to one receipt or several — so the agent
    can ask which one instead of guessing."""
    init_db()
    con = _readonly_connection()
    try:
        rows = [
            dict(r) for r in con.execute(
                "SELECT id, vendor_name, receipt_date, total_amount, currency, processed_at "
                "FROM receipts ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        ]
    finally:
        con.close()
    if not rows:
        return []

    def _ts(s):
        try:
            return datetime.fromisoformat(str(s or "").replace("Z", ""))
        except (ValueError, TypeError):
            return None

    batch = [rows[0]]
    for prev, cur in zip(rows, rows[1:]):
        tp, tc = _ts(prev.get("processed_at")), _ts(cur.get("processed_at"))
        if tp and tc and 0 <= (tp - tc).total_seconds() <= max_gap_seconds:
            batch.append(cur)
        else:
            break
    return batch


def get_receipts_by_ids(receipt_ids) -> list[dict]:
    """Fetch id/vendor/date/total for a set of receipts, for scope display and
    disambiguation (e.g. listing which receipts a follow-up could refer to)."""
    scope = _normalize_scope(receipt_ids)
    if not scope:
        return []
    init_db()
    con = _readonly_connection()
    try:
        ph = ",".join("?" * len(scope))
        rows = con.execute(
            f"SELECT id, vendor_name, receipt_date, total_amount, currency "
            f"FROM receipts WHERE id IN ({ph}) ORDER BY id",
            scope,
        ).fetchall()
    finally:
        con.close()
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------- #
# 6. SQL Agent — natural-language questions over the ledger
# --------------------------------------------------------------------------- #
SCHEMA_DESCRIPTION = """
Table receipts(id, source_file, processed_at, vendor_name, vendor_tin,
  vendor_address, receipt_number, receipt_date, subtotal, vatable_sales,
  vat_exempt_sales, zero_rated_sales, vat_amount, discount, discount_type,
  total_amount, cash, change, currency, category, flagged)
  - id: unique identifier for each receipt
  - source_file: original filename of the uploaded receipt image
  - processed_at: timestamp when the receipt was processed (ISO format)
  - vendor_name: name of the store/merchant (e.g. "Starbucks", "Walmart", "Jollibee")
  - vendor_tin: merchant tax registration number if printed (TIN/GST/Tax ID/etc.)
  - vendor_address: address of the merchant/store location
  - receipt_number: receipt/invoice number printed on the receipt
  - receipt_date: date of transaction (YYYY-MM-DD format when possible)
  - subtotal: amount before tax and discounts
  - vatable_sales: taxable sales amount (portion subject to VAT/GST/sales tax)
  - vat_exempt_sales: tax-exempt sales amount
  - zero_rated_sales: zero-rated sales amount
  - vat_amount: printed tax/VAT/GST amount
  - discount: total discount amount (promo, loyalty, coupon, senior/PWD, etc.)
  - discount_type: type of discount applied (e.g. "Promo", "Loyalty", "Senior Citizen")
  - total_amount: final amount due/total paid
  - cash: amount of cash tendered by customer
  - change: change given back to customer
  - currency: currency code shown on the receipt (e.g. "PHP", "USD", "EUR"); may be NULL
  - category: spending category, one of 'Food', 'Shopping', 'Health', 'Other'
  - flagged: 1 if receipt needs manual review, 0 otherwise

Table line_items(id, receipt_id, description, quantity, unit_price, amount)
  - id: unique identifier for each line item
  - receipt_id: foreign key to receipts.id
  - description: product/service name
  - quantity: number of units (may be NULL)
  - unit_price: price per unit (may be NULL)
  - amount: total amount for this line item
"""

_SQL_AGENT_PROMPT = """You are a SQL expert for a personal receipts ledger database.
Today's date is {today}.

Schema:
{schema}

Rules:
- Write exactly ONE read-only SQLite SELECT statement that answers the question.
- Never use INSERT, UPDATE, DELETE, DROP, ALTER, ATTACH, or PRAGMA.
- Do not include a trailing semicolon, comments, or any explanation.
- Do not wrap the query in markdown code fences.
- Use SQLite date functions (date(), strftime()) for date math.
- Use LIKE with '%' for partial matches on text fields (vendor names, etc.).
- For monetary values, use total_amount from receipts unless line-item detail is requested.
- For questions about spending categories (food, shopping, health), filter on the
  receipts.category column with an exact match — e.g. category = 'Food'. It is always
  one of 'Food', 'Shopping', 'Health', 'Other'. Do NOT match category words against
  item descriptions.
- "Receipt N", "receipt #N", "receipt number N", "the Nth receipt" mean the internal
  receipts.id column: use WHERE receipts.id = N (or line_items.receipt_id = N for its
  items). This is NOT the printed receipt_number text column — never match a bare
  number against receipt_number.
- "my most recent / latest / last / newest receipt" or "the receipt I just added"
  means the one most recently ADDED — the highest receipts.id. Resolve it with a
  subquery, e.g. WHERE receipt_id = (SELECT id FROM receipts ORDER BY id DESC LIMIT 1),
  or ORDER BY id DESC LIMIT 1 directly. "Recent" here is about when it was ADDED
  (id / processed_at), NOT the printed receipt_date.
- A single receipt's own subtotal / total / tax / discount lives on the receipts row:
  SELECT that column directly, e.g. SELECT subtotal FROM receipts WHERE id = N. NEVER
  SUM those columns over a JOIN with line_items — the join repeats the receipt once
  per line item and multiplies the value.
- When matching an ITEM by its description (line_items.description LIKE '%...%'), do
  NOT also filter by vendor_name unless the user EXPLICITLY named a vendor. An item
  name does not imply a vendor — never guess one (e.g. do not add "Jollibee").
- Use ROUND(SUM(...), 2) for monetary totals to avoid floating point issues.
- Always include an alias for aggregate results (AS total_spend, AS count, etc.).
- When counting, use COUNT(*) not COUNT(column) unless you need non-null counts.
- For date ranges, use: receipt_date >= 'YYYY-MM-DD' AND receipt_date <= 'YYYY-MM-DD'
- To get current month: receipt_date >= date('now', 'start of month')
- To get current year: receipt_date >= date('now', 'start of year')

Examples:
Question: How many receipts have been processed?
SQL: SELECT COUNT(*) AS receipt_count FROM receipts

Question: What's the total amount I've spent?
SQL: SELECT ROUND(SUM(total_amount), 2) AS total_spend FROM receipts WHERE total_amount IS NOT NULL

Question: How much did I spend at SM Supermarket?
SQL: SELECT ROUND(SUM(total_amount), 2) AS total_spend FROM receipts WHERE vendor_name LIKE '%SM Supermarket%' AND total_amount IS NOT NULL

Question: Which receipts were flagged for review?
SQL: SELECT id, vendor_name, receipt_date, total_amount FROM receipts WHERE flagged = 1

Question: How much did I spend on Food?
SQL: SELECT ROUND(SUM(total_amount), 2) AS total_spend FROM receipts WHERE category = 'Food' AND total_amount IS NOT NULL

Question: What is my spending by category?
SQL: SELECT category, ROUND(SUM(total_amount), 2) AS total_spend FROM receipts WHERE total_amount IS NOT NULL GROUP BY category ORDER BY total_spend DESC

Question: How much VAT did I pay this month?
SQL: SELECT ROUND(SUM(vat_amount), 2) AS total_vat FROM receipts WHERE vat_amount IS NOT NULL AND receipt_date >= date('now', 'start of month')

Question: What are my top 5 vendors by total spend?
SQL: SELECT vendor_name, ROUND(SUM(total_amount), 2) AS total_spend FROM receipts WHERE vendor_name IS NOT NULL AND total_amount IS NOT NULL GROUP BY vendor_name ORDER BY total_spend DESC LIMIT 5

Question: How many items did I buy from Jollibee?
SQL: SELECT COUNT(*) AS item_count FROM line_items li JOIN receipts r ON li.receipt_id = r.id WHERE r.vendor_name LIKE '%Jollibee%'

Question: What are the line items on receipt 2?
SQL: SELECT description, quantity, unit_price, amount FROM line_items WHERE receipt_id = 2

Question: How much did the JUMB BEEF PR cost?
SQL: SELECT description, unit_price, amount FROM line_items WHERE description LIKE '%JUMB BEEF PR%'

Question: What's on my most recent receipt?
SQL: SELECT description, quantity, unit_price, amount FROM line_items WHERE receipt_id = (SELECT id FROM receipts ORDER BY id DESC LIMIT 1)

Question: How much was my last receipt?
SQL: SELECT vendor_name, receipt_date, total_amount FROM receipts ORDER BY id DESC LIMIT 1

Question: What was the subtotal of receipt 3?
SQL: SELECT subtotal FROM receipts WHERE id = 3

Question: What's the total and tax on receipt #4?
SQL: SELECT total_amount, vat_amount FROM receipts WHERE id = 4

Question: What's the average receipt amount?
SQL: SELECT ROUND(AVG(total_amount), 2) AS average_amount FROM receipts WHERE total_amount IS NOT NULL

Question: Show me all receipts from last week
SQL: SELECT id, vendor_name, receipt_date, total_amount FROM receipts WHERE receipt_date >= date('now', '-7 days') ORDER BY receipt_date DESC

Question: How much did I save from discounts?
SQL: SELECT ROUND(SUM(discount), 2) AS total_discounts FROM receipts WHERE discount IS NOT NULL AND discount > 0

Question: What's my vatable sales vs VAT-exempt sales?
SQL: SELECT ROUND(SUM(vatable_sales), 2) AS vatable_total, ROUND(SUM(vat_exempt_sales), 2) AS exempt_total, ROUND(SUM(zero_rated_sales), 2) AS zero_rated_total FROM receipts

Question: How much did I spend on Senior Citizen discounts?
SQL: SELECT ROUND(SUM(discount), 2) AS total_discount FROM receipts WHERE discount_type = 'Senior Citizen' AND discount IS NOT NULL

Question: Show receipts with their vendor address and receipt details
SQL: SELECT vendor_name, vendor_address, receipt_number, receipt_date, total_amount, vat_amount FROM receipts WHERE vendor_name IS NOT NULL ORDER BY receipt_date DESC LIMIT 10

Question: {question}
SQL:"""

_SQL_RETRY_PROMPT = """Your previous SQLite query failed to execute.

Schema:
{schema}

Previous query:
{sql}

SQLite error:
{error}

Common fixes:
- Check column names match the schema exactly
- Use IS NULL / IS NOT NULL for null checks, not = NULL
- Use LIKE for text pattern matching, not =
- Ensure JOIN conditions are correct
- Check that aggregate functions are used correctly
- Verify date formats are YYYY-MM-DD

Write ONE corrected read-only SQLite SELECT statement. No semicolon, no comments, no markdown, no explanation — SQL only.

Question: {question}
SQL:"""

# A `receipt_id = N` / `id = N` predicate (optionally table-qualified) in a WHERE.
_RECEIPT_FILTER_PRED = r"(?:\w+\.)?(?:receipt_id|id)\s*=\s*\d+"


def _strip_receipt_filter(sql: str) -> str:
    """Remove a `receipt_id = N` / `id = N` predicate from a query's WHERE clause so a
    query that matched a stale/nonexistent receipt can be retried by item/vendor. Handles
    the common shapes: '<pred> AND ...', '... AND <pred>', and 'WHERE <pred>' alone."""
    s = sql
    s = re.sub(rf"\s+AND\s+{_RECEIPT_FILTER_PRED}\b", "", s, flags=re.IGNORECASE)
    s = re.sub(rf"\b{_RECEIPT_FILTER_PRED}\s+AND\s+", "", s, flags=re.IGNORECASE)
    # sole condition: drop the whole WHERE up to the next clause / end
    s = re.sub(rf"\s+WHERE\s+{_RECEIPT_FILTER_PRED}\s*(?=$|\bGROUP\b|\bORDER\b|\bLIMIT\b)",
               " ", s, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", s).strip()

_ANSWER_PROMPT = """You are summarizing SQL query results from a personal receipts ledger for a user.
Today's date is {today}.

Question: {question}
SQL used: {sql}
Result rows (JSON): {rows}

Rules for your answer:
- Write a short, direct, natural-language answer (1-3 sentences).
- Use only the data in the result rows - do not invent numbers.
- For monetary values, use comma separators and 2 decimal places (e.g. "12,345.67").
  {currency_hint}
- For counts, use the exact number from the results.
- If the rows are empty, say "No matching records were found."
- Do not mention SQL, queries, or databases.
- Do not add information not present in the results.
- If showing a list, keep it concise (max 5-7 items).

Answer:"""

_FORBIDDEN_SQL = re.compile(r"\b(insert|update|delete|drop|alter|attach|pragma)\b", re.IGNORECASE)
_SQL_FENCE = re.compile(r"```(?:sql)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)


def _extract_sql(raw_text: str) -> str:
    """Pull a single clean SELECT statement out of whatever the model returned."""
    text = raw_text.strip()

    # Remove markdown fences
    fence_match = _SQL_FENCE.search(text)
    if fence_match:
        text = fence_match.group(1).strip()

    # Remove "SQL:" prefix
    text = re.sub(r"^\s*SQL\s*:\s*", "", text, flags=re.IGNORECASE)

    # Cut at first semicolon or double newline
    text = text.split(";")[0]
    text = text.split("\n\n")[0]

    return text.strip().strip("`").strip()


def _validate_sql(sql: str) -> None:
    """Validate that the SQL is safe to execute."""
    if not sql:
        raise GuardrailError("Model returned an empty query.")
    
    sql_upper = sql.upper().strip()
    if not sql_upper.startswith("SELECT"):
        raise GuardrailError(f"Refused to run a non-read-only query: {sql}")
    if _FORBIDDEN_SQL.search(sql):
        raise GuardrailError(f"Refused to run an unsafe query: {sql}")
    if ";" in sql:
        raise GuardrailError(f"Refused a multi-statement query: {sql}")


def _format_peso(value) -> str:
    """Format a number as Philippine Peso currency."""
    if value is None:
        return "₱0.00"
    try:
        return f"₱{float(value):,.2f}"
    except (ValueError, TypeError):
        return "₱0.00"


_CURRENCY_SYMBOL = {
    "PHP": "₱", "USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥", "INR": "₹",
    "AUD": "A$", "CAD": "C$", "SGD": "S$", "HKD": "HK$", "MYR": "RM", "THB": "฿",
}


def _ledger_currency_symbol() -> str:
    """The symbol for the ledger's dominant currency, so answers don't default to
    '$' for e.g. peso receipts. Empty string if unknown/mixed."""
    try:
        con = _readonly_connection()
        try:
            row = con.execute(
                "SELECT currency, COUNT(*) c FROM receipts WHERE currency IS NOT NULL "
                "GROUP BY currency ORDER BY c DESC LIMIT 1"
            ).fetchone()
        finally:
            con.close()
        if row and row["currency"]:
            return _CURRENCY_SYMBOL.get(str(row["currency"]).strip().upper(), "")
    except Exception:  # noqa: BLE001
        pass
    return ""


def _generate_answer(question: str, sql: str, rows: list[dict], model: str) -> str:
    """Turn raw SQL rows into a natural-language answer."""
    if not rows:
        return "No matching records were found in the ledger for that question."
    
    try:
        if ollama is None:
            raise RuntimeError("ollama not installed")
        
        today = date.today().isoformat()
        sym = _ledger_currency_symbol()
        currency_hint = (
            f"Prefix monetary amounts with '{sym}' (the user's currency) unless a row "
            f"names a different currency. Do NOT use '$' unless the currency is USD."
            if sym else
            "Do NOT invent a currency symbol; if none is given, use the plain number."
        )
        resp = _chat(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": _ANSWER_PROMPT.format(
                        question=question,
                        sql=sql,
                        rows=json.dumps(rows, default=str)[:4000],
                        today=today,
                        currency_hint=currency_hint,
                    ),
                }
            ],
            options={"temperature": 0},
        )
        answer = resp["message"]["content"].strip()
        if answer:
            return answer
    except Exception:
        pass
    
    # Fallback: simple templated summary
    if len(rows) == 1 and len(rows[0]) == 1:
        ((_, value),) = rows[0].items()
        # Try to detect if it's a monetary value
        if any(key for key in rows[0].keys() if 'amount' in key.lower() or 'spend' in key.lower() or 'vat' in key.lower() or 'discount' in key.lower()):
            return _format_peso(value)
        return str(value)
    
    if len(rows) == 1:
        # Single row with multiple columns - try to format nicely
        parts = []
        for key, value in rows[0].items():
            if 'amount' in key.lower() or 'spend' in key.lower() or 'vat' in key.lower() or 'discount' in key.lower():
                parts.append(f"{key.replace('_', ' ')}: {_format_peso(value)}")
            elif 'count' in key.lower() or 'number' in key.lower():
                parts.append(f"{key.replace('_', ' ')}: {value}")
            else:
                parts.append(f"{key.replace('_', ' ')}: {value}")
        return ", ".join(parts)
    
    return f"Found {len(rows)} matching record(s)."


# --------------------------------------------------------------------------- #
# Scope isolation — a deterministic guardrail so a question about ONE receipt can
# never read another. We do NOT trust the model to add a WHERE clause. Instead the
# generated SQL runs against an in-memory database that physically contains ONLY
# the receipts in scope, so out-of-scope rows don't exist to be read — even
# `SELECT * FROM receipts` returns just the allowed rows.
# --------------------------------------------------------------------------- #
def _normalize_scope(receipt_ids) -> list[int] | None:
    """Validate + de-dupe a scope list. Rejects anything that isn't a positive
    integer id (protects the sandbox builder from bad or hostile input)."""
    if not receipt_ids:
        return None
    out: set[int] = set()
    for r in receipt_ids:
        try:
            v = int(r)
        except (TypeError, ValueError):
            raise GuardrailError(f"Invalid receipt id in scope: {r!r}")
        if v <= 0:
            raise GuardrailError(f"Invalid receipt id in scope: {r!r}")
        out.add(v)
    return sorted(out)


def _readonly_connection() -> sqlite3.Connection:
    """Open the ledger read-only so the SQL tool can never mutate it, even if a
    write somehow got past _validate_sql. Falls back to a normal connection if the
    platform rejects the file: URI."""
    try:
        con = sqlite3.connect(
            f"file:{Path(DB_PATH).as_posix()}?mode=ro", uri=True,
            timeout=_SQLITE_BUSY_TIMEOUT_MS / 1000,
        )
        con.execute(f"PRAGMA busy_timeout={_SQLITE_BUSY_TIMEOUT_MS}")
    except sqlite3.OperationalError:
        con = _connect()
    con.row_factory = sqlite3.Row
    return con


def _build_scoped_db(scope: list[int]) -> sqlite3.Connection:
    """Return an in-memory SQLite connection holding ONLY the scoped receipts and
    their line items. This is the hard boundary: rows outside the scope are never
    copied in, so no query can reach them. The schema is mirrored from the live
    ledger via PRAGMA so migrated columns are always included."""
    mem = sqlite3.connect(":memory:")
    mem.row_factory = sqlite3.Row
    placeholders = ",".join("?" * len(scope))
    src = _readonly_connection()
    try:
        for table, id_col in (("receipts", "id"), ("line_items", "receipt_id")):
            info = src.execute(f"PRAGMA table_info({table})").fetchall()
            if not info:
                continue
            cols = [r["name"] for r in info]
            coldefs = ", ".join(f'"{r["name"]}" {r["type"] or ""}'.strip() for r in info)
            mem.execute(f'CREATE TABLE "{table}" ({coldefs})')
            rows = src.execute(
                f'SELECT {",".join(cols)} FROM "{table}" WHERE "{id_col}" IN ({placeholders})',
                scope,
            ).fetchall()
            if rows:
                qmarks = ",".join("?" * len(cols))
                mem.executemany(
                    f'INSERT INTO "{table}" ({",".join(cols)}) VALUES ({qmarks})',
                    [tuple(r) for r in rows],
                )
        mem.commit()
    finally:
        src.close()
    return mem


def _assert_in_scope(rows: list[dict], scope: list[int]) -> list[dict]:
    """Defense in depth: confirm no returned row references a receipt outside the
    scope (catches any bug in the sandbox builder before results leave the door)."""
    allowed = set(scope)
    for row in rows:
        for key in ("id", "receipt_id"):
            val = row.get(key)
            if val is None:
                continue
            try:
                in_scope = int(val) in allowed
            except (TypeError, ValueError):
                continue
            if not in_scope:
                raise GuardrailError(
                    "A query result referenced a receipt outside the requested scope; "
                    "refused to return it."
                )
    return rows


def _sql_agent_core(question: str, model: str, receipt_ids: list[int] | None = None) -> dict:
    """Generate SQL -> validate -> execute (retrying once on error) -> summarize.

    No MLflow here so it can be reused as a tool inside the ReAct agent without
    creating stray nested runs. When `receipt_ids` is given, the query runs against
    an in-memory database containing ONLY those receipts — a deterministic guardrail
    so a "single receipt" question can't read the rest of the ledger, regardless of
    what SQL the model writes. Unscoped queries run against a read-only ledger.
    """
    if ollama is None:
        raise RuntimeError("The `ollama` package is not installed.")

    scope = _normalize_scope(receipt_ids)
    today = date.today().isoformat()
    prompt = _SQL_AGENT_PROMPT.format(schema=SCHEMA_DESCRIPTION, question=question, today=today)

    gen = _chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        options={"temperature": 0},
    )
    sql = _extract_sql(gen["message"]["content"])
    initial_sql = sql

    init_db()
    # Scoped questions run inside a sandbox DB that only holds the allowed rows;
    # unscoped ones run read-only against the full ledger.
    con = _build_scoped_db(scope) if scope else _readonly_connection()
    rows: list[dict] = []
    retried = False
    error_message = None
    try:
        try:
            _validate_sql(sql)
            rows = [dict(r) for r in con.execute(sql).fetchall()]
        except (GuardrailError, sqlite3.Error) as first_err:
            error_message = str(first_err)
            retried = True
            retry_prompt = _SQL_RETRY_PROMPT.format(
                schema=SCHEMA_DESCRIPTION, sql=sql, error=error_message, question=question
            )
            gen2 = _chat(
                model=model,
                messages=[{"role": "user", "content": retry_prompt}],
                options={"temperature": 0},
            )
            sql = _extract_sql(gen2["message"]["content"])
            _validate_sql(sql)
            rows = [dict(r) for r in con.execute(sql).fetchall()]

        # 0-row broadening: a query that filters on a specific receipt id but finds
        # nothing is usually a STALE id (e.g. carried over from earlier in the chat
        # after the ledger changed). Deterministically strip the receipt-id predicate
        # (asking the model to drop it is unreliable — it re-adds it because the
        # question still says "on receipt N") and re-run, matching by the remaining
        # conditions (item description / vendor). Safe in a scoped sandbox too, which
        # only contains the allowed receipts.
        if not rows and not retried and re.search(_RECEIPT_FILTER_PRED, sql, re.IGNORECASE):
            sql_b = _strip_receipt_filter(sql)
            if not re.search(_RECEIPT_FILTER_PRED, sql_b, re.IGNORECASE):
                retried = True
                try:
                    _validate_sql(sql_b)
                    rows_b = [dict(r) for r in con.execute(sql_b).fetchall()]
                    if rows_b:
                        sql, rows = sql_b, rows_b
                except (GuardrailError, sqlite3.Error):
                    pass  # keep the original empty result

        if scope is not None:
            rows = _assert_in_scope(rows, scope)
    finally:
        con.close()

    answer = _generate_answer(question, sql, rows, model)
    return {
        "question": question,
        "sql": sql,
        "initial_sql": initial_sql,
        "rows": rows,
        "answer": answer,
        "retried": retried,
        "first_error": error_message,
    }


def ask_ledger(question: str, model: str = AGENT_MODEL, receipt_ids: list[int] | None = None) -> dict:
    """MLflow-traced wrapper around the SQL agent (a no-op trace when disabled)."""
    with _traced_run(f"sql_agent_{int(time.time())}"):
        _mlog_param("question", question[:250])
        _mlog_param("model", model)
        t0 = time.time()
        try:
            result = _sql_agent_core(question, model, receipt_ids)
            _mlog_param("final_sql", result["sql"][:500])
            if result.get("first_error"):
                _mlog_param("first_error", result["first_error"][:250])
            _mlog_metric("retried", int(result["retried"]))
            _mlog_metric("rows_returned", len(result["rows"]))
            _mlog_metric("latency_seconds", time.time() - t0)
            _mlog_metric("error", 0)
            return {k: result[k] for k in ("question", "sql", "rows", "answer")}
        except Exception as exc:
            _mlog_metric("error", 1)
            _mlog_param("error_message", str(exc)[:250])
            _mlog_metric("latency_seconds", time.time() - t0)
            raise


# --------------------------------------------------------------------------- #
# 7. RAG — semantic retrieval over the receipts
# --------------------------------------------------------------------------- #
# The SQL agent is great at *aggregates* ("how much did I spend at X?"). It is
# poor at *content* questions ("which receipt had the oat-milk latte?", "what did
# I buy at the pharmacy?") where the useful signal is unstructured item text.
# RAG fills that gap: every receipt is turned into a short natural-language
# document, embedded with a local embedding model, and stored alongside a vector.
# A question is embedded the same way and matched by cosine similarity, so the
# same retriever answers whether you're asking about ONE receipt or across MANY.

_EMBED_OK: bool | None = None  # cached availability of the embedding model

# nomic-embed-text is an ASYMMETRIC model: documents and queries must be embedded
# with task-instruction prefixes, or cosine similarity is unreliable (relevant and
# irrelevant receipts end up scoring almost the same). Prefix docs and queries
# differently. Bump _EMBED_VERSION whenever this convention changes so ensure_index
# re-embeds any vectors written under the old scheme (a query embedded with the new
# prefix must never be compared against a doc embedded with the old one).
_EMBED_VERSION = 2
_DOC_PREFIX = "search_document: "
_QUERY_PREFIX = "search_query: "

# Below this cosine similarity a whole-ledger match is treated as "not relevant"
# and dropped, so RAG can honestly answer "I couldn't find that" instead of
# returning unrelated receipts. Not applied when the caller scopes to specific
# receipt ids (there the user has already chosen which receipts to look at).
_VEC_MIN_SCORE = 0.5


def init_rag_db() -> None:
    with _connect() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS receipt_docs (
                receipt_id INTEGER PRIMARY KEY,
                doc TEXT,
                embedding BLOB,
                emb_ver INTEGER,
                FOREIGN KEY (receipt_id) REFERENCES receipts(id)
            )
            """
        )
        # Migration: older DBs have receipt_docs without emb_ver. Add it so stale
        # (prefix-less) embeddings can be detected and re-embedded.
        cols = {r[1] for r in con.execute("PRAGMA table_info(receipt_docs)").fetchall()}
        if "emb_ver" not in cols:
            try:
                con.execute("ALTER TABLE receipt_docs ADD COLUMN emb_ver INTEGER")
            except sqlite3.OperationalError:
                pass
        con.commit()


def _compose_doc(header: dict, items: list[dict]) -> str:
    """Build the short natural-language document that represents a receipt for
    retrieval. Includes vendor, date, every line item, and the money summary, so
    it works for both embedding search and the keyword fallback."""
    rid = header.get("id") or header.get("receipt_id")
    vendor = header.get("vendor_name") or "Unknown merchant"
    cur = header.get("currency") or ""
    parts = [f"Receipt #{rid}." if rid is not None else "Receipt."]
    when = header.get("receipt_date") or (header.get("processed_at") or "")[:10]
    parts.append(f"Merchant: {vendor}" + (f", on {when}" if when else "") + ".")
    if header.get("vendor_address"):
        parts.append(f"Location: {header['vendor_address']}.")
    if header.get("receipt_number"):
        parts.append(f"Receipt number {header['receipt_number']}.")

    item_bits = []
    for it in items or []:
        desc = (it.get("description") or "").strip()
        if not desc:
            continue
        qty, amt = _num(it.get("quantity")), _num(it.get("amount"))
        piece = desc
        if qty:
            piece += f" x{qty:g}"
        if amt is not None:
            piece += f" = {amt:g}"
        item_bits.append(piece)
    if item_bits:
        parts.append("Items: " + "; ".join(item_bits) + ".")

    money = []
    for label, key in (
        ("subtotal", "subtotal"), ("tax", "vat_amount"),
        ("discount", "discount"), ("total", "total_amount"),
    ):
        v = _num(header.get(key))
        if v is not None:
            money.append(f"{label} {v:g}")
    if header.get("discount_type"):
        money.append(f"discount type {header['discount_type']}")
    if money:
        parts.append((f"Amounts ({cur}): " if cur else "Amounts: ") + ", ".join(money) + ".")
    if header.get("source_file"):
        parts.append(f"Source file: {header['source_file']}.")
    return " ".join(parts)


def _embed(text: str) -> list[float] | None:
    """Return an embedding vector for `text`, or None if the embedding model
    isn't available (the retriever then falls back to keyword matching)."""
    global _EMBED_OK
    if ollama is None or not text:
        return None
    try:
        resp = ollama.embeddings(model=EMBED_MODEL, prompt=text)
        vec = resp.get("embedding")
        if vec:
            _EMBED_OK = True
            return list(vec)
    except Exception:  # noqa: BLE001 - model may not be pulled; degrade gracefully
        _EMBED_OK = False
    return None


def _embeddings_available() -> bool:
    global _EMBED_OK
    if _EMBED_OK is None:
        _EMBED_OK = _embed("connectivity probe") is not None
    return bool(_EMBED_OK)


def _emb_to_blob(vec: list[float] | None) -> bytes | None:
    if not vec or np is None:
        return None
    return np.asarray(vec, dtype=np.float32).tobytes()


def index_receipt(receipt_id: int, data, source_file: str) -> None:
    """Embed + store one receipt's document. Called on every save; safe to
    re-run (INSERT OR REPLACE)."""
    init_rag_db()
    header = data.model_dump() if hasattr(data, "model_dump") else dict(data)
    header["id"] = receipt_id
    header["source_file"] = source_file
    doc = _compose_doc(header, header.get("items") or [])
    blob = _emb_to_blob(_embed(_DOC_PREFIX + doc))
    # Record the version only when we actually stored a vector, so a failed embed
    # (NULL blob) is retried by ensure_index once the model becomes available.
    ver = _EMBED_VERSION if blob is not None else None
    with _connect() as con:
        con.execute(
            "INSERT OR REPLACE INTO receipt_docs (receipt_id, doc, embedding, emb_ver) "
            "VALUES (?,?,?,?)",
            (receipt_id, doc, blob, ver),
        )
        con.commit()


def ensure_index() -> None:
    """Backfill documents/embeddings for receipts saved before RAG existed, saved
    with deferred indexing (bulk import), or whose embedding failed because the
    model wasn't pulled yet. Idempotent.

    After a large batch import this can face thousands of un-embedded receipts, so
    the embedding calls run through a bounded thread pool instead of one-at-a-time;
    on the sample the first post-import search is what would otherwise stall. The
    read and write phases bracket the parallel work so no DB connection is held
    open across the (potentially long) embedding step."""
    init_db()
    init_rag_db()

    # --- read phase: collect the docs that still need embedding ---
    with _connect() as con:
        con.row_factory = sqlite3.Row
        pending = list(con.execute(
            """
            SELECT r.* FROM receipts r
            LEFT JOIN receipt_docs d ON d.receipt_id = r.id
            WHERE d.receipt_id IS NULL
            """
        ).fetchall())
        # Also retry rows whose embedding is missing OR was written under an older
        # embedding convention (emb_ver != current) — but only if the model is now
        # reachable, otherwise we'd re-probe on every single search.
        if _embeddings_available():
            pending += con.execute(
                """
                SELECT r.* FROM receipts r
                JOIN receipt_docs d ON d.receipt_id = r.id
                WHERE d.embedding IS NULL OR d.emb_ver IS NULL OR d.emb_ver != ?
                """,
                (_EMBED_VERSION,),
            ).fetchall()

        docs: list[tuple[int, str]] = []
        for row in pending:
            header = dict(row)
            items = [
                dict(x)
                for x in con.execute(
                    "SELECT description, quantity, unit_price, amount "
                    "FROM line_items WHERE receipt_id = ?",
                    (row["id"],),
                ).fetchall()
            ]
            docs.append((row["id"], _compose_doc(header, items)))

    if not docs:
        return

    # --- embed phase: parallelize the (I/O-bound) embedding calls ---
    # Embed the same _DOC_PREFIX + doc convention as index_receipt, and stamp the
    # current _EMBED_VERSION only when a vector was actually produced (a failed
    # embed leaves emb_ver NULL so it is retried next time).
    def _embed_one(item: tuple[int, str]):
        rid, doc = item
        blob = _emb_to_blob(_embed(_DOC_PREFIX + doc))
        ver = _EMBED_VERSION if blob is not None else None
        return rid, doc, blob, ver

    if len(docs) > 1 and OCR_CONCURRENCY > 1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=OCR_CONCURRENCY) as pool:
            embedded = list(pool.map(_embed_one, docs))
    else:
        embedded = [_embed_one(d) for d in docs]

    # --- write phase: persist docs + embeddings in one short transaction ---
    with _connect() as con:
        con.executemany(
            "INSERT OR REPLACE INTO receipt_docs (receipt_id, doc, embedding, emb_ver) "
            "VALUES (?,?,?,?)",
            embedded,
        )
        con.commit()


def _cosine(a, b) -> float:
    if np is None:
        return 0.0
    denom = (np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denom) if denom else 0.0


# "receipt 3", "receipt #2", "receipt no. 5", "receipt id 4", or a bare "#7" all
# refer to a specific receipt by its id. A pattern like "3 receipts" or "top 5" does
# NOT match (the number must follow the word receipt / a #).
_RECEIPT_REF_RE = re.compile(r"(?:receipts?\s*(?:no\.?|number|id|#)?\s*|#)(\d{1,7})", re.IGNORECASE)


def _parse_receipt_refs(text: str) -> list[int]:
    """Receipt ids explicitly named in a question, so retrieval can be pinned to the
    exact receipt instead of guessing by semantic similarity."""
    return [int(m) for m in _RECEIPT_REF_RE.findall(text or "")]


# "my recent receipt", "the latest receipt", "last receipt", "newest grocery receipt",
# "the receipt I just added/uploaded" — a reference to the most recently ADDED receipt.
_RECENT_RECEIPT_RE = re.compile(
    r"\b(?:most\s+recent|recent|latest|last|newest)\s+(?:\w+\s+){0,2}receipt\b"
    r"|\breceipt\s+(?:that\s+)?i\s+(?:just\s+)?(?:added|uploaded|scanned|processed)\b",
    re.IGNORECASE,
)


def semantic_search(query: str, k: int = 4, receipt_ids: list[int] | None = None) -> list[dict]:
    """Return the k most relevant receipts for `query`. Uses vector similarity
    when embeddings are available, otherwise a keyword-overlap fallback so the
    demo still works if `nomic-embed-text` isn't pulled.

    `receipt_ids` scopes the search to a specific set of receipts (e.g. only the
    batch just uploaded) — this is the guardrail that lets the same retriever
    answer a single-receipt question without leaking in the rest of the ledger.
    """
    if not query or not query.strip():
        return []
    scope_list = _normalize_scope(receipt_ids)
    scope = set(scope_list) if scope_list else None
    ensure_index()

    with _connect() as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """
            SELECT d.receipt_id, d.doc, d.embedding,
                   r.vendor_name, r.receipt_date, r.total_amount, r.currency, r.source_file
            FROM receipt_docs d JOIN receipts r ON r.id = d.receipt_id
            """
        ).fetchall()

    # If the question explicitly names a receipt ("receipt #3", "receipt 2"),
    # resolve it to that receipt's id and pin the search there. Semantic similarity
    # alone can't match a bare id, so without this an id-specific question would
    # retrieve whatever is merely closest in content — the wrong receipt.
    if scope is None:
        refs = {i for i in _parse_receipt_refs(query) if any(r["receipt_id"] == i for r in rows)}
        if refs:
            scope = refs

    # Hard filter: out-of-scope receipts are removed before any scoring, so a
    # single-receipt query can only ever surface that receipt.
    candidates = [dict(r) for r in rows if scope is None or r["receipt_id"] in scope]
    if not candidates:
        return []

    qvec = _embed(_QUERY_PREFIX + query)
    scored: list[tuple[float, dict]] = []
    used_vectors = False
    if qvec is not None and np is not None:
        q = np.asarray(qvec, dtype=np.float32)
        for c in candidates:
            if c["embedding"] is None:
                continue
            vec = np.frombuffer(c["embedding"], dtype=np.float32)
            # Guard against a stale vector written by a different embedding model
            # (different dimension) — comparing mismatched shapes would crash.
            if vec.shape[0] != q.shape[0]:
                continue
            scored.append((_cosine(q, vec), c))
        used_vectors = len(scored) > 0

    if not scored:
        # keyword fallback: overlap of query terms with the document text
        terms = [t for t in re.split(r"\W+", query.lower()) if len(t) > 2]
        for c in candidates:
            doc_l = (c["doc"] or "").lower()
            score = sum(doc_l.count(t) for t in terms)
            scored.append((float(score), c))

    # Relevance filter (whole-ledger searches only): drop non-matches so RAG can
    # honestly say "not found" instead of returning arbitrary receipts. When the
    # caller scoped to specific receipts, keep them all — the user chose those.
    if scope is None:
        if used_vectors:
            scored = [(s, c) for s, c in scored if s >= _VEC_MIN_SCORE]
        else:
            scored = [(s, c) for s, c in scored if s > 0]

    scored.sort(key=lambda x: x[0], reverse=True)
    results = []
    for score, c in scored[:k]:
        results.append(
            {
                "receipt_id": c["receipt_id"],
                "doc": c["doc"],
                "score": round(score, 4),
                "vendor_name": c["vendor_name"],
                "receipt_date": c["receipt_date"],
                "total_amount": c["total_amount"],
                "currency": c["currency"],
                "source_file": c["source_file"],
            }
        )
    return results


_RAG_PROMPT = """You answer questions about a user's purchase receipts using ONLY the
retrieved receipts below. Today's date is {today}.

Retrieved receipts:
{context}

Question: {question}

Rules:
- Answer using ONLY the retrieved receipts. If they don't contain the answer, say
  "I couldn't find that in your receipts."
- Cite the receipts you used by their number, e.g. "(Receipt #3)".
- Keep it to 1-4 sentences. Show money amounts with the currency shown, if any.

Answer:"""


def _rag_core(query: str, model: str, k: int = 4, receipt_ids: list[int] | None = None) -> dict:
    hits = semantic_search(query, k=k, receipt_ids=receipt_ids)
    if not hits:
        return {"query": query, "answer": "I couldn't find any matching receipts.", "sources": []}
    context = "\n".join(f"- Receipt #{h['receipt_id']}: {h['doc']}" for h in hits)
    answer = ""
    if ollama is not None:
        try:
            resp = _chat(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": _RAG_PROMPT.format(
                            today=date.today().isoformat(), context=context[:4000], question=query
                        ),
                    }
                ],
                options={"temperature": 0},
            )
            answer = resp["message"]["content"].strip()
        except Exception:  # noqa: BLE001
            answer = ""
    if not answer:
        vendors = ", ".join(sorted({h["vendor_name"] for h in hits if h["vendor_name"]}))
        answer = f"Found {len(hits)} related receipt(s)" + (f" from {vendors}." if vendors else ".")
    return {"query": query, "answer": answer, "sources": hits}


def rag_answer(query: str, model: str = AGENT_MODEL, k: int = 4,
               receipt_ids: list[int] | None = None) -> dict:
    """MLflow-traced RAG question-answering over the receipts (no-op when off)."""
    with _traced_run(f"rag_{int(time.time())}"):
        _mlog_param("query", query[:250])
        _mlog_param("model", model)
        t0 = time.time()
        try:
            result = _rag_core(query, model, k=k, receipt_ids=receipt_ids)
            _mlog_metric("sources_retrieved", len(result["sources"]))
            _mlog_metric("used_embeddings", int(_embeddings_available()))
            _mlog_metric("latency_seconds", time.time() - t0)
            _mlog_metric("error", 0)
            return result
        except Exception as exc:
            _mlog_metric("error", 1)
            _mlog_param("error_message", str(exc)[:250])
            _mlog_metric("latency_seconds", time.time() - t0)
            raise


# --------------------------------------------------------------------------- #
# 8. ReAct Agent — a reasoning + acting loop that routes to the right tool and
#    streams its thinking so the UI can show it live.
# --------------------------------------------------------------------------- #
_MAX_AGENT_STEPS = 3

_REACT_PROMPT = """You are a receipts assistant. You answer the user's question by
thinking step by step and using tools. Today's date is {today}.

You have exactly two tools:
- sql_ledger: for NUMBERS and AGGREGATES across the ledger — totals, sums, counts,
  averages, "how much", "how many", "top vendors", flagged receipts, date ranges.
  Action Input is a natural-language question.
- search_receipts: for CONTENT — finding specific receipts, what items were bought,
  which store sold something, or summarizing what's on a receipt. Action Input is a
  search phrase.

Use this EXACT format, one block at a time:
Thought: <your reasoning about what to do next>
Action: <sql_ledger OR search_receipts>
Action Input: <the input for the tool>

After each Action you will be shown an Observation. When you have enough to answer:
Thought: <brief reasoning>
Final Answer: <a concise, direct answer for the user>

If — and ONLY if — the question is genuinely ambiguous or you lack the context to
answer it, ask the user ONE short clarifying question instead of guessing:
Thought: <why you cannot answer yet>
Clarification: <one concise question for the user>

Ask a Clarification when, for example:
- a reference like "those" / "that receipt" / "it" has nothing in the conversation to
  point to;
- the question names something that could match several different things and the
  choice changes the answer (e.g. an ambiguous vendor, or "this month" with no date);
- the request cannot be mapped to the receipts data at all.

Rules:
- Most questions need only ONE tool call. Take at most {max_steps} actions.
- Call each tool AT MOST ONCE. Never repeat the same Action with the same input.
- As soon as an Observation answers the question, immediately reply with
  "Final Answer:" — do not think further or call another tool.
- Anything about a SPECIFIC receipt named by number ("receipt #2", "receipt 3", "the
  4th receipt") — its line items, subtotal, total, tax, vendor, or date — is
  sql_ledger; pass the receipt number through in the Action Input. search_receipts
  cannot match a bare receipt number and will return the wrong receipt.
- Use search_receipts ONLY for fuzzy content with NO receipt number: "what did I buy
  at the coffee shop", "which receipt had sushi", "find the pharmacy receipt".
- Otherwise use sql_ledger for math/counts and search_receipts for open-ended lookups.
- ANY question about amounts of money is ALWAYS sql_ledger — "how much", "how many",
  "total", "spend", "cost", "price", "how much did X cost", "what did each of those
  cost" — EVEN when it names a vendor, store, item, or category. A named vendor/item
  does NOT make it a content search: "how much have I spent on Pepper Lunch", "what
  did the JUMB BEEF PR cost", "total for groceries" are all sql_ledger (it filters by
  vendor/item with LIKE, or by category). NEVER route a money/cost/count question to
  search_receipts, no matter what it names.
- Prefer to ANSWER whenever you reasonably can — only ask a Clarification when you are
  genuinely stuck or would otherwise have to GUESS. Never clarify something the tools
  can already answer, and ask at most one short question.
- Superlatives about spending are aggregates too — ALWAYS sql_ledger: "what did I
  spend the most/least on", "biggest/highest/largest purchase", "top vendor/category",
  "most expensive receipt". Ask it as a ranking question ("category with the highest
  total spend", "vendor I spent the most at").
- Base the Final Answer ONLY on the Observations you received.
- The Final Answer is shown directly to the user: state it plainly and briefly. Do
  NOT mention tools, SQL, "the ledger", observations, or that a value was "calculated"
  or "confirmed". Do NOT repeat the words "Final Answer:" inside your answer.
- This is a conversation. Use the recent messages below to resolve references —
  "those", "them", "it", "that receipt", "each of those items" — into the concrete
  item names or vendor they point to. NEVER pass a pronoun to a tool: put the actual
  names in the Action Input (e.g. not "cost of those" but "unit price of JUMB BEEF PR
  and SET MEAL A").
- Before asking a Clarification, RE-READ the conversation. If a previous answer (yours
  or the user's) already named the items, receipt, or vendor, USE those — do NOT ask
  the user to repeat what was just said. Example: your last answer said "SHK CHICKEN S
  and SHK FRIES", and the user asks "how much did each of those cost" → look up SHK
  CHICKEN S and SHK FRIES; do not ask which items.
- Receipt numbers mentioned EARLIER in the conversation may be out of date. Do NOT add
  a "receipt N" filter unless THIS question itself names a receipt number — instead
  match by item name and/or vendor, which stays correct even if the ledger changed.
{scope}{history}
Example:
Question: How much did I spend in total?
Thought: This is an aggregate over all receipts, so I should query the ledger.
Action: sql_ledger
Action Input: What is my total spend across all receipts?
Observation: Your total spend is 4,210.00.
Thought: I have the total.
Final Answer: You've spent a total of 4,210.00 across your receipts.

Example:
Question: How much have I spent on Pepper Lunch?
Thought: This is a spend total for a named vendor — an aggregate, so I query the ledger.
Action: sql_ledger
Action Input: total amount spent at Pepper Lunch
Observation: You spent 2,635.00 at Pepper Lunch.
Thought: I have the total.
Final Answer: You've spent 2,635.00 at Pepper Lunch.

Example:
Question: how much did that cost?
Thought: "that" has no referent — nothing earlier in the conversation names an item, vendor, or receipt, so I cannot answer without guessing.
Clarification: Which item or receipt do you mean?

Begin.
Question: {question}
"""

_ACTION_RE = re.compile(r"Action:\s*([a-zA-Z_]+)", re.IGNORECASE)
_ACTION_INPUT_RE = re.compile(r"Action Input:\s*(.+)", re.IGNORECASE)
_FINAL_RE = re.compile(r"Final Answer:\s*(.+)", re.IGNORECASE | re.DOTALL)
# Small models sometimes emit "Final Answer: Final Answer: ..." or a stray "Answer:"
# / "Thought:" prefix; strip any of those leading labels so they don't reach the user.
_LEADING_LABEL_RE = re.compile(r"^\s*(?:final\s*answer|answer|thought)\s*:\s*", re.IGNORECASE)


def _clean_answer(text: str) -> str:
    """Strip leaked ReAct scaffolding (repeated 'Final Answer:' etc.) from an answer
    before it is shown to the user."""
    t = (text or "").strip()
    prev = None
    while prev != t:  # peel repeated leading labels
        prev = t
        t = _LEADING_LABEL_RE.sub("", t).strip()
    # if the model kept going with another Thought/Action after the answer, cut it
    t = re.split(r"\n\s*(?:Thought|Action|Observation)\s*:", t)[0].strip()
    return t


_CLARIFY_RE = re.compile(r"Clarification:\s*(.+)", re.IGNORECASE | re.DOTALL)


def _parse_final(text: str) -> str | None:
    m = _FINAL_RE.search(text)
    return _clean_answer(m.group(1)) if m else None


def _parse_clarification(text: str) -> str | None:
    """A clarifying question the agent asks the user when it's genuinely stuck."""
    m = _CLARIFY_RE.search(text)
    return _clean_answer(m.group(1)) if m else None


def _parse_action(text: str) -> tuple[str | None, str]:
    a = _ACTION_RE.search(text)
    if not a:
        return None, ""
    tool = a.group(1).strip().lower()
    inp = ""
    m = _ACTION_INPUT_RE.search(text, a.end())
    if m:
        # take just the first line of the action input
        inp = m.group(1).strip().splitlines()[0].strip().strip('"').strip()
    return tool, inp


def _run_agent_tool(tool: str, tool_input: str, model: str,
                    receipt_ids: list[int] | None) -> tuple[str, dict]:
    """Execute a tool and return (observation_text_for_the_model, ui_payload)."""
    if tool == "sql_ledger":
        # The SQL agent already retries once on a bad query, but a small model can
        # still emit invalid SQL twice. Surface that as an observation the agent can
        # recover from (e.g. switch to search_receipts) rather than crashing the run.
        try:
            res = _sql_agent_core(tool_input, model, receipt_ids)
        except (GuardrailError, sqlite3.Error) as exc:
            return (
                f"The ledger query failed ({exc}). Try rephrasing, or use "
                f"search_receipts instead.",
                {"kind": "error", "error": str(exc)},
            )
        obs = res["answer"]
        if res["rows"]:
            obs += " | data: " + json.dumps(res["rows"], default=str)[:600]
        return obs, {"kind": "sql", "sql": res["sql"], "rows": res["rows"], "answer": res["answer"]}

    if tool == "search_receipts":
        hits = semantic_search(tool_input, k=4, receipt_ids=receipt_ids)
        if not hits:
            return "No matching receipts were found.", {"kind": "search", "hits": []}
        obs = " || ".join(f"Receipt #{h['receipt_id']}: {h['doc']}" for h in hits)
        return obs[:1400], {"kind": "search", "hits": hits}

    return (
        f"Unknown tool '{tool}'. Valid tools are sql_ledger and search_receipts.",
        {"kind": "error"},
    )


def _force_final(question: str, steps: list[dict], model: str) -> str:
    """If the model never emitted a Final Answer within the step budget, salvage
    one from the observations we gathered."""
    obs = [s["observation"] for s in steps if s.get("observation")]
    if not obs:
        return "I wasn't able to find an answer to that in your receipts."
    if ollama is not None:
        try:
            resp = _chat(
                model=model,
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"Question: {question}\n\nFindings:\n" + "\n".join(obs[-3:])
                            + "\n\nWrite a concise 1-2 sentence answer using only these findings."
                        ),
                    }
                ],
                options={"temperature": 0},
            )
            ans = resp["message"]["content"].strip()
            if ans:
                return ans
        except Exception:  # noqa: BLE001
            pass
    return obs[-1]


# How many past turns of conversation to give the agent as memory, and how much of
# each to keep. A wider window lets it resolve follow-ups like "each of those items"
# from an earlier answer instead of losing the thread.
_HISTORY_TURNS = 10
_HISTORY_CHARS = 600


def _format_history(history) -> str:
    """Turn recent chat messages into a compact block the ReAct model can use to
    resolve follow-up references ("those", "it", "that receipt", "each of those")."""
    if not history:
        return ""
    lines = []
    for m in list(history)[-_HISTORY_TURNS:]:
        role = str(m.get("role") or "").lower()
        who = "User" if role in ("me", "user", "human") else "Assistant"
        text = str(m.get("text") or m.get("content") or "").strip().replace("\n", " ")
        if text:
            lines.append(f"{who}: {text[:_HISTORY_CHARS]}")
    return ("Recent conversation (use it to resolve references):\n" + "\n".join(lines) + "\n") if lines else ""


def agent_stream(question: str, model: str = AGENT_MODEL,
                 receipt_ids: list[int] | None = None, history: list | None = None):
    """Run the ReAct loop, yielding events as they happen so a UI can render the
    agent's reasoning live. Event `type`s:
        start                       — loop started
        token   {text}              — a chunk of the model's current reasoning
        action  {tool, input}       — the agent decided to call a tool
        observation {tool, text, data} — the tool's result
        final   {answer, steps}     — the final answer (last event on success)
        error   {message}           — something failed
    """
    _traced = MLFLOW_ENABLED and MLFLOW_SAMPLE_RATE >= 1.0
    if _traced:
        _fresh_run(f"agent_{int(time.time())}")  # self-healing start
    t0 = time.time()
    tools_used: list[str] = []
    steps: list[dict] = []
    try:
        _mlog_param("question", question[:250])
        _mlog_param("model", model)
        if ollama is None:
            raise RuntimeError("The `ollama` package is not installed.")

        yield {"type": "start"}

        # Disambiguation: "my recent/latest receipt" is ambiguous when several were
        # uploaded together — ask which one instead of guessing. (Skipped when the
        # caller already scoped the request to specific receipts.)
        if receipt_ids is None and _RECENT_RECEIPT_RE.search(question):
            batch = recent_receipts()
            if len(batch) > 1:
                listing = "; ".join(
                    "#{id} {v}{d}{t}".format(
                        id=r["id"],
                        v=r.get("vendor_name") or "Unknown",
                        d=f", {r['receipt_date']}" if r.get("receipt_date") else "",
                        t=f" — {r['total_amount']}" if r.get("total_amount") is not None else "",
                    )
                    for r in batch
                )
                clarification = (
                    f'You recently added {len(batch)} receipts, so "recent receipt" '
                    f"could mean any of them — which one? {listing}"
                )
                steps.append({"clarify": clarification})
                mlflow.log_metric("num_steps", 0)
                mlflow.log_metric("clarified", 1)
                mlflow.log_metric("latency_seconds", time.time() - t0)
                mlflow.log_metric("error", 0)
                yield {"type": "clarify", "question": clarification, "steps": steps}
                return

        scope = ""
        if receipt_ids:
            scope = ("- The user is asking about a specific receipt/batch only; "
                     "the tools are already scoped to it.\n")
        transcript = _REACT_PROMPT.format(
            today=date.today().isoformat(),
            question=question,
            max_steps=_MAX_AGENT_STEPS,
            scope=scope,
            history=_format_history(history),
        )

        final_answer: str | None = None
        clarification: str | None = None
        seen: dict[tuple[str, str], str] = {}  # (tool, input) -> observation, to dedup
        repeats = 0
        for _ in range(_MAX_AGENT_STEPS):
            text = ""
            for chunk in _chat(
                model=model,
                messages=[{"role": "user", "content": transcript}],
                stream=True,
                options={"temperature": 0, "stop": ["Observation:"]},
            ):
                piece = chunk.get("message", {}).get("content", "")
                if piece:
                    text += piece
                    yield {"type": "token", "text": piece}
            text = text.strip()

            final_answer = _parse_final(text)
            if final_answer is not None:
                steps.append({"thought": text})
                break

            # Disambiguation: the agent can ask the user instead of guessing.
            clarification = _parse_clarification(text)
            if clarification is not None:
                steps.append({"thought": text, "clarify": clarification})
                break

            tool, tool_input = _parse_action(text)
            if not tool:
                # No action and no final answer — treat the whole reply as the answer.
                final_answer = _clean_answer(text) or "I'm not sure how to answer that."
                steps.append({"thought": text})
                break

            key = (tool, tool_input.strip().lower())
            if key in seen:
                # The model is looping on a tool it already ran. Don't pay to run it
                # again — reuse the cached result and steer it hard toward answering.
                repeats += 1
                if repeats >= 2:
                    final_answer = _clean_answer(_force_final(question, steps, model))
                    break
                obs_text = (
                    f"You already ran {tool} with that input; the result was: {seen[key]} "
                    "Do NOT call any tool again. Reply now starting with 'Final Answer:'."
                )
                yield {"type": "observation", "tool": tool, "text": obs_text,
                       "data": {"kind": "note"}}
                steps.append({"thought": text, "tool": tool, "input": tool_input,
                              "observation": obs_text, "repeat": True})
                transcript += text + f"\nObservation: {obs_text}\n"
                continue

            yield {"type": "action", "tool": tool, "input": tool_input}
            tools_used.append(tool)
            obs_text, payload = _run_agent_tool(tool, tool_input, model, receipt_ids)
            seen[key] = obs_text
            yield {"type": "observation", "tool": tool, "text": obs_text, "data": payload}
            steps.append(
                {"thought": text, "tool": tool, "input": tool_input, "observation": obs_text}
            )
            transcript += text + f"\nObservation: {obs_text}\n"

        if clarification is None and final_answer is None:
            final_answer = _clean_answer(_force_final(question, steps, model))

        _mlog_metric("num_steps", len(steps))
        _mlog_param("tools_used", ",".join(tools_used) or "none")
        _mlog_metric("latency_seconds", time.time() - t0)
        _mlog_metric("clarified", int(clarification is not None))
        _mlog_metric("error", 0)
        if clarification is not None:
            yield {"type": "clarify", "question": clarification, "steps": steps}
        else:
            yield {"type": "final", "answer": final_answer, "steps": steps}
    except Exception as exc:  # noqa: BLE001
        _mlog_metric("error", 1)
        _mlog_param("error_message", str(exc)[:250])
        _mlog_metric("latency_seconds", time.time() - t0)
        yield {"type": "error", "message": str(exc)}
    finally:
        if _traced and mlflow.active_run() is not None:
            mlflow.end_run()


def agent_run(question: str, model: str = AGENT_MODEL,
              receipt_ids: list[int] | None = None, history: list | None = None) -> dict:
    """Non-streaming convenience wrapper: consume the stream, return the result
    plus the full reasoning trace (for the REST API)."""
    final = ""
    steps: list[dict] = []
    needs_clarification = False
    for ev in agent_stream(question, model, receipt_ids, history):
        if ev["type"] == "final":
            final, steps = ev["answer"], ev["steps"]
        elif ev["type"] == "clarify":
            final, steps, needs_clarification = ev["question"], ev["steps"], True
        elif ev["type"] == "error":
            raise RuntimeError(ev["message"])
    return {"question": question, "answer": final, "steps": steps,
            "needs_clarification": needs_clarification}