"""
STAI_OCR — Philippine Receipt Processor
=======================================

Drag-and-drop a receipt image; a local vision LLM (Ollama `llama3.2-vision`)
reads it and extracts the fields needed for Philippine accounting/BIR
bookkeeping (TIN, line items, price, discount, VAT, totals). Each receipt is
reconciled (12% VAT vs VATable sales, line items vs total), shown on an
editable ledger, and exportable to CSV / Excel.

Setup (run once, in a terminal or notebook cell):
-------------------------------------------------
    %pip install streamlit ollama pandas openpyxl pillow --quiet
    !ollama pull llama3.2-vision        # vision model (reads the image)

    # NOTE: llama3.2:3b is TEXT-ONLY and cannot read images. This app uses
    # the vision variant `llama3.2-vision` to read the receipt directly.

Run the app:
------------
    streamlit run receipt_processor.py

Make sure the Ollama server is running (`ollama serve`) before processing.
"""

from __future__ import annotations

import html
import io
import json
import re
from datetime import date

import pandas as pd
import streamlit as st

try:
    import ollama
except ImportError:  # pragma: no cover - surfaced in the UI instead
    ollama = None


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
DEFAULT_MODEL = "llama3.2-vision"
PH_VAT_RATE = 0.12  # 12% standard VAT in the Philippines

HEADER_FIELDS = [
    "vendor_name",
    "vendor_tin",
    "vendor_address",
    "receipt_number",
    "receipt_date",
    "vatable_sales",
    "vat_exempt_sales",
    "zero_rated_sales",
    "vat_amount",
    "discount",
    "discount_type",
    "total_amount",
    "currency",
]

EXTRACTION_PROMPT = """You are an expert Philippine bookkeeping assistant reading a sales
receipt or official receipt (OR) / sales invoice (SI).

Extract the data and return ONLY a single valid JSON object — no prose, no
markdown fences. Use these exact keys. Use null when a value is not present.
All money values must be plain numbers (no currency symbols, no commas).

{
  "vendor_name": string,
  "vendor_tin": string,            // Taxpayer Identification Number, format like 000-000-000-000
  "vendor_address": string,
  "receipt_number": string,        // OR / SI / receipt no.
  "receipt_date": string,          // YYYY-MM-DD if possible
  "items": [
    {
      "description": string,
      "quantity": number,
      "unit_price": number,
      "amount": number
    }
  ],
  "vatable_sales": number,         // VATable sales (net of VAT)
  "vat_exempt_sales": number,      // VAT-exempt sales
  "zero_rated_sales": number,      // Zero-rated sales
  "vat_amount": number,            // 12% output VAT
  "discount": number,              // total discount amount (e.g. Senior Citizen / PWD)
  "discount_type": string,         // e.g. "Senior Citizen", "PWD", "Promo", or null
  "total_amount": number,          // total amount due / amount paid
  "currency": string               // e.g. "PHP"
}

Read carefully. If the receipt shows a VAT amount, copy it exactly. Do not
invent values. Return the JSON object only."""


# --------------------------------------------------------------------------- #
# Core extraction
# --------------------------------------------------------------------------- #
def _coerce_json(text: str) -> dict:
    """Pull a JSON object out of a model response that may include fences/prose."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start : end + 1]
    return json.loads(text)


def extract_receipt(image_bytes: bytes, model: str) -> dict:
    """Send the image to the local vision LLM and return parsed receipt data."""
    if ollama is None:
        raise RuntimeError(
            "The `ollama` Python package is not installed. Run: pip install ollama"
        )

    response = ollama.chat(
        model=model,
        messages=[
            {
                "role": "user",
                "content": EXTRACTION_PROMPT,
                "images": [image_bytes],
            }
        ],
        options={"temperature": 0},
    )
    content = response["message"]["content"]
    try:
        return _coerce_json(content)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Could not parse model output as JSON.\n\nRaw output:\n{content}"
        ) from exc


# --------------------------------------------------------------------------- #
# Numbers, reconciliation, and shaping
# --------------------------------------------------------------------------- #
def _num(value) -> float | None:
    """Best-effort convert a model value (maybe a string with ₱/commas) to float."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = re.sub(r"[^\d.\-]", "", str(value))
    try:
        return float(cleaned) if cleaned not in ("", "-", ".") else None
    except ValueError:
        return None


def reconcile(data: dict) -> list[str]:
    """Return human-readable warnings when the receipt's math doesn't add up."""
    warnings: list[str] = []

    vat = _num(data.get("vat_amount"))
    vatable = _num(data.get("vatable_sales"))
    if vat is not None and vatable and vatable > 0:
        expected = round(vatable * PH_VAT_RATE, 2)
        if abs(expected - vat) > 0.5:
            warnings.append(
                f"VAT check: 12% of VATable sales is ₱{expected:,.2f}, "
                f"but the receipt states ₱{vat:,.2f}."
            )

    items = data.get("items") or []
    amounts = [a for a in (_num(i.get("amount")) for i in items) if a is not None]
    total = _num(data.get("total_amount"))
    if amounts and total and total > 0:
        items_sum = round(sum(amounts), 2)
        discount = _num(data.get("discount")) or 0.0
        tol = max(1.0, total * 0.02)
        if abs(items_sum - total) > tol and abs(items_sum - discount - total) > tol:
            warnings.append(
                f"Totals check: line items add up to ₱{items_sum:,.2f}, "
                f"which doesn't reconcile to the total of ₱{total:,.2f}."
            )
    return warnings


def header_row(data: dict, source: str) -> dict:
    row = {"source_file": source}
    for key in HEADER_FIELDS:
        row[key] = data.get(key)
    row["flags"] = len(reconcile(data))
    return row


def items_frame(data: dict, source: str) -> pd.DataFrame:
    items = data.get("items") or []
    cols = ["source_file", "description", "quantity", "unit_price", "amount"]
    if not items:
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame(items)
    df.insert(0, "source_file", source)
    for col in cols:
        if col not in df.columns:
            df[col] = None
    return df[cols]


def to_excel_bytes(summary: pd.DataFrame, items: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="Receipts", index=False)
        items.to_excel(writer, sheet_name="Line Items", index=False)
    return buffer.getvalue()


# --------------------------------------------------------------------------- #
# Presentation
# --------------------------------------------------------------------------- #
def _peso(value) -> str:
    n = _num(value)
    return f"₱{n:,.2f}" if n is not None else "—"


def _txt(value) -> str:
    if value is None or str(value).strip() == "":
        return "—"
    return html.escape(str(value))


def receipt_card_html(data: dict, source: str) -> str:
    """Render one extracted receipt as a perforated thermal-receipt card."""
    rows = [
        ("VATable sales", _peso(data.get("vatable_sales"))),
        ("VAT-exempt sales", _peso(data.get("vat_exempt_sales"))),
        ("Zero-rated sales", _peso(data.get("zero_rated_sales"))),
        (f"Output VAT ({PH_VAT_RATE:.0%})", _peso(data.get("vat_amount"))),
    ]
    discount_label = _txt(data.get("discount_type")) if data.get("discount_type") else "Discount"
    rows.append((discount_label, _peso(data.get("discount"))))

    body = "".join(
        f'<div class="rcpt-line"><span>{label}</span><span class="fig">{value}</span></div>'
        for label, value in rows
    )

    warnings = reconcile(data)
    if warnings:
        items = "".join(f"<li>{html.escape(w)}</li>" for w in warnings)
        flag = f'<div class="rcpt-flag">⚠ Needs review<ul>{items}</ul></div>'
    else:
        flag = '<div class="rcpt-ok">✓ Figures reconcile</div>'

    return f"""
    <div class="rcpt">
      <div class="rcpt-head">
        <div class="rcpt-vendor">{_txt(data.get('vendor_name'))}</div>
        <div class="rcpt-sub">TIN <span class="fig">{_txt(data.get('vendor_tin'))}</span></div>
        <div class="rcpt-sub">{_txt(data.get('vendor_address'))}</div>
      </div>
      <div class="rcpt-meta">
        <span>OR/SI <b class="fig">{_txt(data.get('receipt_number'))}</b></span>
        <span class="fig">{_txt(data.get('receipt_date'))}</span>
      </div>
      <div class="rcpt-body">{body}</div>
      <div class="rcpt-total">
        <span>Total due</span><span class="fig">{_peso(data.get('total_amount'))}</span>
      </div>
      {flag}
      <div class="rcpt-src">{_txt(source)}</div>
    </div>
    """


THEME_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=Inter:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

:root{
  --ink:#14233A; --teal:#0E7C7B; --gold:#E8B23A;
  --paper:#FBF7EF; --slate:#6B7A8D; --line:#E4DBC8;
}

/* page canvas */
[data-testid="stAppViewContainer"]{ background:var(--paper); }
[data-testid="stHeader"]{ background:transparent; }
.block-container{ padding-top:2.2rem; max-width:1180px; }
html, body, [class*="css"]{ font-family:'Inter',sans-serif; color:var(--ink); }
.fig{ font-family:'IBM Plex Mono',monospace; font-feature-settings:"tnum"; letter-spacing:-.2px; }

/* hero */
.hero{
  background:linear-gradient(135deg,#14233A 0%,#0E7C7B 100%);
  border-radius:18px; padding:30px 34px; color:#fff;
  box-shadow:0 24px 50px -28px rgba(20,35,58,.6); position:relative; overflow:hidden;
}
.hero::after{ /* faux receipt edge stripe */
  content:""; position:absolute; right:-40px; top:-40px; width:220px; height:220px;
  background:repeating-linear-gradient(90deg,rgba(232,178,58,.16) 0 8px,transparent 8px 16px);
  transform:rotate(18deg);
}
.hero-eyebrow{
  font-family:'IBM Plex Mono',monospace; font-size:.72rem; letter-spacing:.28em;
  text-transform:uppercase; color:var(--gold); margin-bottom:10px;
}
.hero-title{ font-family:'Space Grotesk',sans-serif; font-weight:700; font-size:2.5rem; line-height:1.02; margin:0; }
.hero-sub{ color:#D7E2E2; max-width:46ch; margin-top:12px; font-size:1.0rem; }

/* section labels */
.eyebrow{
  font-family:'IBM Plex Mono',monospace; font-size:.72rem; letter-spacing:.24em;
  text-transform:uppercase; color:var(--teal); margin:8px 0 2px;
}

/* file dropzone -> "feed a receipt" slot */
[data-testid="stFileUploaderDropzone"]{
  background:#fff; border:2px dashed var(--teal); border-radius:14px; padding:30px;
}
[data-testid="stFileUploaderDropzone"]:hover{ border-color:var(--gold); }

/* buttons */
.stButton>button, .stDownloadButton>button{
  font-family:'Space Grotesk',sans-serif; font-weight:600; border-radius:10px;
  border:1px solid transparent; padding:.55rem 1.1rem;
}
.stButton>button[kind="primary"]{ background:var(--teal); color:#fff; }
.stButton>button[kind="primary"]:hover{ background:#0a5f5e; }
.stDownloadButton>button{ background:#fff; color:var(--ink); border:1px solid var(--line); }
.stDownloadButton>button:hover{ border-color:var(--gold); color:var(--teal); }

/* the signature: perforated thermal-receipt card */
.rcpt{
  position:relative; background:#fff; border-radius:12px 12px 0 0;
  padding:20px 22px 24px; margin-bottom:24px;
  box-shadow:0 18px 38px -26px rgba(20,35,58,.55);
}
.rcpt::after{
  content:""; position:absolute; left:0; right:0; bottom:-11px; height:13px;
  background-image:radial-gradient(circle at 7px -3px,transparent 6.5px,#fff 7px);
  background-size:14px 14px; background-repeat:repeat-x;
  filter:drop-shadow(0 10px 10px -10px rgba(20,35,58,.5));
}
.rcpt-vendor{ font-family:'Space Grotesk',sans-serif; font-weight:600; font-size:1.12rem; }
.rcpt-sub{ color:var(--slate); font-size:.84rem; }
.rcpt-meta{
  display:flex; justify-content:space-between; font-size:.82rem; color:var(--ink);
  border-top:1px dashed var(--line); border-bottom:1px dashed var(--line);
  padding:9px 0; margin:12px 0;
}
.rcpt-line{ display:flex; justify-content:space-between; padding:4px 0; font-size:.92rem; }
.rcpt-line span:first-child{ color:var(--slate); }
.rcpt-total{
  display:flex; justify-content:space-between; align-items:baseline;
  margin-top:12px; padding-top:12px; border-top:2px solid var(--ink);
  font-family:'Space Grotesk',sans-serif; font-weight:700; font-size:1.15rem;
}
.rcpt-total .fig{ font-size:1.3rem; color:var(--teal); }
.rcpt-ok{ margin-top:12px; color:var(--teal); font-weight:600; font-size:.85rem; }
.rcpt-flag{
  margin-top:12px; background:#FCF3E2; border-left:3px solid var(--gold);
  border-radius:6px; padding:8px 10px; font-size:.8rem; color:#7a5a12;
}
.rcpt-flag ul{ margin:6px 0 0; padding-left:18px; }
.rcpt-src{
  margin-top:14px; font-family:'IBM Plex Mono',monospace; font-size:.7rem;
  color:var(--slate); text-align:center; letter-spacing:.05em;
}
</style>
"""


def render_hero() -> None:
    st.markdown(
        """
        <div class="hero">
          <div class="hero-eyebrow">BIR-ready bookkeeping · Philippines</div>
          <h1 class="hero-title">Receipt&nbsp;Ledger</h1>
          <p class="hero-sub">Drop a receipt. A local vision model reads the TIN,
          line items, discounts and 12% VAT, reconciles the math, and hands you a
          clean ledger to export.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


# --------------------------------------------------------------------------- #
# Streamlit app
# --------------------------------------------------------------------------- #
def main() -> None:
    st.set_page_config(page_title="Receipt Ledger — STAI_OCR", page_icon="🧾", layout="wide")
    st.markdown(THEME_CSS, unsafe_allow_html=True)
    render_hero()

    with st.sidebar:
        st.markdown('<div class="eyebrow">Settings</div>', unsafe_allow_html=True)
        model = st.text_input("Ollama vision model", value=DEFAULT_MODEL)
        st.markdown(
            "**Before you start**\n"
            "- `ollama serve` is running\n"
            f"- `ollama pull {DEFAULT_MODEL}` done\n"
            "- Receipts as PNG / JPG / WEBP"
        )
        st.caption(f"Reconciliation uses the {PH_VAT_RATE:.0%} standard VAT rate.")

    st.markdown('<div class="eyebrow">Feed a receipt</div>', unsafe_allow_html=True)
    uploads = st.file_uploader(
        "Drag receipt images here, or browse",
        type=["png", "jpg", "jpeg", "webp", "bmp"],
        accept_multiple_files=True,
    )

    if not uploads:
        st.info("Drag one or more receipt images into the box above to begin.")
        return

    if st.button("Process receipts", type="primary"):
        summaries: list[dict] = []
        item_frames: list[pd.DataFrame] = []
        progress = st.progress(0.0)

        for i, upload in enumerate(uploads, start=1):
            with st.spinner(f"Reading {upload.name} ({i}/{len(uploads)})…"):
                image_bytes = upload.getvalue()
                left, right = st.columns([1, 1.4])
                left.image(image_bytes, caption=upload.name, use_container_width=True)
                try:
                    data = extract_receipt(image_bytes, model)
                except Exception as exc:  # noqa: BLE001 - report any failure in the UI
                    right.error(f"Couldn't read {upload.name}: {exc}")
                    progress.progress(i / len(uploads))
                    continue

                right.markdown(receipt_card_html(data, upload.name), unsafe_allow_html=True)
                with right.expander("Raw extracted JSON"):
                    st.json(data)
                summaries.append(header_row(data, upload.name))
                item_frames.append(items_frame(data, upload.name))
            progress.progress(i / len(uploads))

        if not summaries:
            st.warning("No receipts were successfully processed.")
            return

        st.session_state["summary_df"] = pd.DataFrame(summaries)
        st.session_state["items_df"] = (
            pd.concat(item_frames, ignore_index=True) if item_frames else pd.DataFrame()
        )

    if "summary_df" in st.session_state:
        st.markdown('<div class="eyebrow">Receipt ledger · editable</div>', unsafe_allow_html=True)
        summary_df = st.data_editor(
            st.session_state["summary_df"], num_rows="dynamic", use_container_width=True
        )

        st.markdown('<div class="eyebrow">Line items · editable</div>', unsafe_allow_html=True)
        items_df = st.data_editor(
            st.session_state["items_df"], num_rows="dynamic", use_container_width=True
        )

        stamp = date.today().isoformat()
        c1, c2, c3 = st.columns(3)
        c1.download_button(
            "Summary CSV",
            summary_df.to_csv(index=False).encode("utf-8"),
            file_name=f"receipts_summary_{stamp}.csv",
            mime="text/csv",
        )
        c2.download_button(
            "Line items CSV",
            items_df.to_csv(index=False).encode("utf-8"),
            file_name=f"receipts_items_{stamp}.csv",
            mime="text/csv",
        )
        c3.download_button(
            "Excel (both sheets)",
            to_excel_bytes(summary_df, items_df),
            file_name=f"receipts_{stamp}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


if __name__ == "__main__":
    main()
