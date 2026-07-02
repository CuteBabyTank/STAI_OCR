"""
STAI_OCR — Receipt Processor & Ledger Agent
===========================================

Drag-and-drop any receipt image (restaurant, cafe, grocery, retail, pharmacy);
a local vision LLM (Ollama `minicpm-v`) reads it and extracts the useful fields
(merchant, tax ID, line items, price, discount, tax/VAT, totals). Each receipt is
reconciled (line items vs total), shown on an editable ledger, exportable to
CSV / Excel, and indexed for a natural-language ReAct agent ("Ask your receipts").

Setup (run once, in a terminal or notebook cell):
-------------------------------------------------
    %pip install streamlit ollama pandas numpy openpyxl pillow --quiet
    !ollama pull minicpm-v              # vision/OCR model (reads the image)
    !ollama pull nomic-embed-text       # embeddings for semantic search (RAG)

    # NOTE: llama3.2:3b is TEXT-ONLY and cannot read images. `minicpm-v` is a
    # vision model tuned for OCR; in testing it read receipt digits far more
    # accurately than llava. (llama3.2-vision needs a newer Ollama engine than
    # the Homebrew build provides — it fails with "unknown architecture mllama".)

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
DEFAULT_MODEL = "minicpm-v"

HEADER_FIELDS = [
    "vendor_name",
    "vendor_tin",
    "vendor_address",
    "receipt_number",
    "receipt_date",
    "subtotal",
    "vatable_sales",
    "vat_exempt_sales",
    "zero_rated_sales",
    "vat_amount",
    "discount",
    "discount_type",
    "total_amount",
    "cash",
    "change",
    "currency",
]

EXTRACTION_PROMPT = """You are a careful transcription tool reading a purchase
receipt or invoice — the kind you get at a restaurant, cafe, grocery, retail
store, pharmacy, or any other merchant. Receipts come in every layout and from
any country; some print a tax breakdown or a merchant tax ID, many do not. Your
only job is to copy down values that are actually printed on the receipt — you
are transcribing, not interpreting.

STRICT RULES — follow exactly:
1. ONLY record a value if it is clearly printed on the receipt. If a field is not
   printed, missing, or unreadable, return null. Never guess.
2. NEVER calculate, infer, derive, estimate, round, or "fix" a value. Do not add
   numbers up. Do not compute tax or totals yourself. Copy only what is shown.
3. Copy every digit EXACTLY as printed, including the decimal point. "120" stays
   120, "120.00" stays 120.00, "1,250.50" becomes 1250.50. Do not move the decimal
   point or drop/add zeros.
4. If you are unsure whether a number is, say, 120 or 720, return null rather than
   guessing.
5. Match each amount to the correct field by its printed label on the receipt.
6. vendor_tin is the merchant's tax registration number (labeled "TIN",
   "VAT REG TIN", "GST No", "Tax ID", "ABN", "EIN", etc.). Leave it null unless a
   number is explicitly labeled as a tax ID. Never put the receipt/invoice number
   in vendor_tin.
7. For a line item, only fill quantity or unit_price if that line actually prints
   them. If a line shows just a description and one amount, set quantity and
   unit_price to null and put the figure in amount. Never copy a value from one
   line item onto another.
8. vatable_sales and vat_amount capture any printed tax breakdown ("VAT", "GST",
   "Sales Tax", "Tax", "VATable Sales", "12% VAT", etc.). Copy the EXACT numbers
   printed next to those labels. Do NOT compute tax as a percentage of anything.
   Do NOT derive vatable_sales from the total. If the receipt does not print a
   taxable-sales figure, vatable_sales is null. If it prints no tax amount,
   vat_amount is null.
9. "items" is ONLY for purchased products/services. Summary and tax lines —
   Subtotal, Taxable/VATable Sales, Tax-Exempt Sales, Zero-Rated Sales, VAT/Tax,
   Discount, Total, Cash, Change — are NOT items. Put each in its own dedicated
   field and never list it inside "items".
10. Keep payment lines separate. total_amount is the "Total" / "Amount Due" line
    ONLY. The cash the customer handed over ("CASH", "TENDERED", "AMOUNT PAID")
    goes in "cash". The money returned ("CHANGE") goes in "change". Never put the
    cash or the change into total_amount.
11. A tax breakdown is often a small table: a row of headers
    (VATable | Tax | Exempt | Zero-Rated) with a row of numbers directly beneath.
    Read the number UNDER each header into its field: the value under
    "VATable"/"Taxable" -> vatable_sales, under "VAT"/"Tax"/"GST" -> vat_amount,
    under "Exempt" -> vat_exempt_sales, under "Zero-Rated"/"Z-Rated" -> zero_rated_sales.
12. vendor_tin is the seller's tax ID printed in the header block at the top.
    Ignore blank "TIN: ____" form fields and any tax ID printed in the footer of a
    different company.
13. For a line like "Peri-Peri Chicken  2 @ 270.00": description is just the item
    name ("Peri-Peri Chicken"). Do NOT repeat the name and do NOT put the "2 @ 270.00"
    text in the description. Put the line's total amount in "amount", and the
    quantity ("2") in "quantity".
14. List each printed line item exactly once. Do NOT output the same item as two
    separate rows.
15. currency is the currency actually shown on the receipt — read it from the
    symbol or code printed next to the amounts (₱/PHP, $/USD, €/EUR, £/GBP, ¥/JPY,
    ₹/INR, etc.). If no currency is indicated, return null.

Return ONLY a single valid JSON object — no prose, no markdown fences. Use these
exact keys. Use null when a value is not present. Money values are plain numbers
(no currency symbols, no commas).

{
  "vendor_name": string,
  "vendor_tin": string,            // merchant tax ID if labeled (TIN/GST/Tax ID/etc.); else null. NOT the receipt no.
  "vendor_address": string,
  "receipt_number": string,        // receipt / invoice / OR / SI no.
  "receipt_date": string,          // YYYY-MM-DD if possible
  "items": [
    {
      "description": string,       // the item name/description as printed
      "quantity": number,          // only if a quantity is printed for this line; else null
      "unit_price": number,        // only if a unit/per-item price is printed for this line; else null
      "amount": number             // the line total/amount printed for this item
    }
  ],
  "subtotal": number,              // the subtotal / gross amount line, before tax and discounts
  "vatable_sales": number,         // EXACT printed taxable-sales figure; null if not printed. Never derived.
  "vat_exempt_sales": number,      // tax-exempt sales
  "zero_rated_sales": number,      // zero-rated sales
  "vat_amount": number,            // EXACT printed tax/VAT figure; null if not printed. Never computed.
  "discount": number,              // total discount amount
  "discount_type": string,         // e.g. "Promo", "Loyalty", "Senior Citizen", "PWD", "Coupon", or null
  "total_amount": number,          // the "Total" / "Amount Due" line. NOT cash, NOT change.
  "cash": number,                  // cash tendered / amount paid by the customer ("CASH", "TENDERED")
  "change": number,                // change given back to the customer ("CHANGE")
  "currency": string               // currency code/symbol shown, e.g. "PHP", "USD", "EUR"; null if none
}

Remember: transcribe only what is printed. A missing value must be null, never a
guess or a calculation. Return the JSON object only."""


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


def _clean_item_description(desc) -> str | None:
    """Tidy a line-item description: drop the "qty @ price" notation and any
    doubled name. e.g. "Peri-Peri Chicken Peri-Peri Chicken 2 @ ₱270.00" -> "Peri-Peri Chicken".
    """
    if desc is None:
        return None
    s = str(desc).strip()
    # Strip a trailing "qty @ price" / "@ price" / "qty @" / "@" / "x2" notation.
    s = re.sub(r"\s*\d+\s*@\s*[₱P]?\s*[\d.,]+\s*$", "", s)   # "2 @ 270.00"
    s = re.sub(r"\s*@\s*[₱P]?\s*[\d.,]+\s*$", "", s)          # "@ 270.00"
    s = re.sub(r"\s*\d+\s*@\s*$", "", s)                       # "2 @"
    s = re.sub(r"\s*@\s*$", "", s)                             # "@"
    s = re.sub(r"\s*[xX]\s*\d+\s*$", "", s)                    # "x2"
    s = s.strip(" -·•\t")
    # Collapse an exactly doubled phrase ("A B A B" -> "A B").
    words = s.split()
    n = len(words)
    if n >= 2 and n % 2 == 0 and words[: n // 2] == words[n // 2 :]:
        s = " ".join(words[: n // 2])
    s = s.strip()
    return s or (str(desc).strip() or None)


def _clean_items(data: dict) -> dict:
    """Clean every line item's description in place (qty @ price + de-dup)."""
    for item in data.get("items") or []:
        if "description" in item:
            item["description"] = _clean_item_description(item.get("description"))
    return data


def _dedupe_items(data: dict) -> dict:
    """Drop duplicate line items the model emitted for the same product, e.g. one
    "Peri-Peri Chicken ₱540" row plus an empty "Peri-Peri Chicken" row. Items with
    the same description are merged: the row carrying an amount wins, exact repeats
    collapse to one. Two same-name rows with *different* amounts are kept (could be
    genuinely separate lines). Blank descriptions are always kept (e.g. modifiers).
    """
    result: list[dict] = []
    seen: dict[str, int] = {}
    for item in data.get("items") or []:
        key = re.sub(r"[^a-z0-9]", "", str(item.get("description") or "").lower())
        amt = _num(item.get("amount"))
        if not key:
            result.append(item)
            continue
        if key in seen:
            existing = result[seen[key]]
            ex_amt = _num(existing.get("amount"))
            if ex_amt is None and amt is not None:
                result[seen[key]] = item  # replace the empty row with the real one
            elif amt is None or (ex_amt is not None and abs(ex_amt - amt) <= 0.01):
                continue  # amount-less or exact duplicate -> drop
            else:
                result.append(item)  # different amount -> keep as a distinct line
        else:
            seen[key] = len(result)
            result.append(item)
    data["items"] = result
    return data


# Summary/tax lines the model sometimes mis-files as "items". Maps a normalized
# label (lowercased, alphanumerics only) to the field it really belongs in.
_SUMMARY_LABELS = {
    "vatablesales": "vatable_sales",
    "vatable": "vatable_sales",
    "vatsales": "vatable_sales",
    "salesvatable": "vatable_sales",
    "vatexemptsales": "vat_exempt_sales",
    "vatexempt": "vat_exempt_sales",
    "exemptsales": "vat_exempt_sales",
    "zeroratedsales": "zero_rated_sales",
    "zerorated": "zero_rated_sales",
    "vat": "vat_amount",
    "outputvat": "vat_amount",
    "vatamount": "vat_amount",
    "12vat": "vat_amount",
    "vat12": "vat_amount",
    "vatpayable": "vat_amount",
    "subtotal": "subtotal",
    "amountnetofvat": "subtotal",
    "total": "total_amount",
    "totaldue": "total_amount",
    "amountdue": "total_amount",
    "totalamountdue": "total_amount",
    "grandtotal": "total_amount",
    "discount": "discount",
    "lessdiscount": "discount",
    "scdiscount": "discount",
    "pwddiscount": "discount",
    "cash": "cash",
    "cashtendered": "cash",
    "amounttendered": "cash",
    "tendered": "cash",
    "amountpaid": "cash",
    "cashpayment": "cash",
    "change": "change",
    "changedue": "change",
    "amountchange": "change",
}


def _remap_summary_lines(data: dict) -> dict:
    """Move OCR'd summary/tax lines the model mis-filed under "items" into their
    proper fields. This relocates already-transcribed numbers — it never computes
    or invents a value."""
    kept = []
    for item in data.get("items") or []:
        key = re.sub(r"[^a-z0-9]", "", str(item.get("description", "")).lower())
        field = _SUMMARY_LABELS.get(key)
        if field and _num(item.get("amount")) is not None:
            if _num(data.get(field)) is None:  # don't overwrite a real value
                data[field] = item.get("amount")
            continue  # drop this line from items — it's not a product
        kept.append(item)
    data["items"] = kept
    return data


def _fix_payment_fields(data: dict) -> dict:
    """Correct total_amount / cash / change when the model misassigned them.

    Receipts without an explicit "Total" line (only Subtotal / Cash / Change)
    often make the model rotate these three numbers. We re-derive the correct
    label for each *already-OCR'd* number using two facts that are always true:
      • amount due == subtotal − discount
      • cash − change == amount due  (so cash ≥ change)
    We only reassign numbers that were actually read off the receipt; nothing is
    invented. If we can't resolve it cleanly, values are left as-is and the
    reconciliation flag stays on for manual review.
    """
    total = _num(data.get("total_amount"))
    cash = _num(data.get("cash"))
    change = _num(data.get("change"))

    # If the cash-payment identity already holds, the payments are consistent.
    if (
        total is not None and cash is not None and change is not None
        and cash + 0.5 >= change and abs(cash - change - total) <= 0.5
    ):
        return data

    # Anchor the amount due to the subtotal (minus any discount), else item sum.
    subtotal = _num(data.get("subtotal"))
    discount = _num(data.get("discount")) or 0.0
    if subtotal is not None:
        due = round(subtotal - discount, 2)
    else:
        amounts = [a for a in (_num(i.get("amount")) for i in data.get("items") or [])
                   if a is not None]
        due = round(sum(amounts), 2) if amounts else None
    if due is None:
        return data  # no reliable anchor — leave it for manual review

    # Candidate numbers actually OCR'd across the three payment fields.
    candidates = [v for v in (total, cash, change) if v is not None]

    # cash is a candidate >= due whose (cash - due) also matches an OCR'd number
    # (that matching number is the printed change).
    for c in sorted(candidates, reverse=True):
        if c + 0.5 < due:
            continue
        ch = round(c - due, 2)
        if any(abs(ch - v) <= 0.5 for v in candidates):
            data["total_amount"], data["cash"], data["change"] = due, c, ch
            return data

    # Couldn't reassign cleanly; at least trust the subtotal for the amount due.
    if total is None or abs(total - due) > max(1.0, due * 0.02):
        data["total_amount"] = due
    return data


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
        format="json",  # constrain output to valid JSON (avoids rambling/truncation)
        options={"temperature": 0, "num_predict": 1024},
    )
    content = response["message"]["content"]
    try:
        data = _coerce_json(content)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Could not parse model output as JSON.\n\nRaw output:\n{content}"
        ) from exc
    return _fix_payment_fields(
        _dedupe_items(_remap_summary_lines(_clean_items(data)))
    )


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
# Map common currency codes/symbols to a display symbol. Defaults to ₱ (the
# app's original locale) when a receipt doesn't state its currency.
_CURRENCY_SYMBOLS = {
    "PHP": "₱", "₱": "₱", "USD": "$", "$": "$", "EUR": "€", "€": "€",
    "GBP": "£", "£": "£", "JPY": "¥", "¥": "¥", "INR": "₹", "₹": "₹",
    "AUD": "A$", "CAD": "C$", "SGD": "S$", "HKD": "HK$", "CNY": "¥",
    "MYR": "RM", "THB": "฿", "KRW": "₩", "IDR": "Rp", "VND": "₫",
}


def money_symbol(currency) -> str:
    """Best-effort currency symbol for display; falls back to ₱."""
    if not currency:
        return "₱"
    key = str(currency).strip().upper()
    return _CURRENCY_SYMBOLS.get(key, _CURRENCY_SYMBOLS.get(str(currency).strip(), "₱"))


def _peso(value, symbol: str = "₱") -> str:
    n = _num(value)
    return f"{symbol}{n:,.2f}" if n is not None else "—"


def _txt(value) -> str:
    if value is None or str(value).strip() == "":
        return "—"
    return html.escape(str(value))


def receipt_card_html(data: dict, source: str) -> str:
    """Render one extracted receipt as a perforated thermal-receipt card."""
    sym = money_symbol(data.get("currency"))
    # Line items, as printed (description + qty/price hint + amount).
    item_lines = []
    for it in data.get("items") or []:
        qty, unit = _num(it.get("quantity")), _num(it.get("unit_price"))
        hint = f' <span class="rcpt-qty">{qty:g} × {_peso(unit, sym)}</span>' if qty and unit else ""
        item_lines.append(
            f'<div class="rcpt-line"><span>{_txt(it.get("description"))}{hint}</span>'
            f'<span class="fig">{_peso(it.get("amount"), sym)}</span></div>'
        )
    items_html = (
        f'<div class="rcpt-items">{"".join(item_lines)}</div>' if item_lines else ""
    )

    rows = [
        ("Subtotal", _peso(data.get("subtotal"), sym)),
        ("Taxable sales", _peso(data.get("vatable_sales"), sym)),
        ("Tax-exempt sales", _peso(data.get("vat_exempt_sales"), sym)),
        ("Zero-rated sales", _peso(data.get("zero_rated_sales"), sym)),
        ("Tax / VAT", _peso(data.get("vat_amount"), sym)),
    ]
    discount_label = _txt(data.get("discount_type")) if data.get("discount_type") else "Discount"
    rows.append((discount_label, _peso(data.get("discount"), sym)))

    body = items_html + "".join(
        f'<div class="rcpt-line"><span>{label}</span><span class="fig">{value}</span></div>'
        for label, value in rows
    )

    # Payment lines (cash tendered / change) shown under the total, when present.
    pay = []
    if _num(data.get("cash")) is not None:
        pay.append(("Cash", _peso(data.get("cash"), sym)))
    if _num(data.get("change")) is not None:
        pay.append(("Change", _peso(data.get("change"), sym)))
    pay_html = (
        '<div class="rcpt-pay">'
        + "".join(
            f'<div class="rcpt-line"><span>{label}</span><span class="fig">{value}</span></div>'
            for label, value in pay
        )
        + "</div>"
        if pay
        else ""
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
        <div class="rcpt-sub">Tax ID <span class="fig">{_txt(data.get('vendor_tin'))}</span></div>
        <div class="rcpt-sub">{_txt(data.get('vendor_address'))}</div>
      </div>
      <div class="rcpt-meta">
        <span>Receipt <b class="fig">{_txt(data.get('receipt_number'))}</b></span>
        <span class="fig">{_txt(data.get('receipt_date'))}</span>
      </div>
      <div class="rcpt-body">{body}</div>
      <div class="rcpt-total">
        <span>Total due</span><span class="fig">{_peso(data.get('total_amount'), sym)}</span>
      </div>
      {pay_html}
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
.rcpt-line{ display:flex; justify-content:space-between; gap:12px; padding:4px 0; font-size:.92rem; }
.rcpt-line span:first-child{ color:var(--slate); }
.rcpt-items{ padding-bottom:8px; margin-bottom:8px; border-bottom:1px dashed var(--line); }
.rcpt-items .rcpt-line span:first-child{ color:var(--ink); }
.rcpt-qty{ color:var(--slate); font-family:'IBM Plex Mono',monospace; font-size:.78rem; }
.rcpt-pay{ margin-top:8px; padding-top:8px; border-top:1px dashed var(--line); }
.rcpt-pay .rcpt-line span:first-child{ color:var(--slate); }
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

/* the ledger agent's final answer */
.agent-answer{
  background:#fff; border:1px solid var(--line); border-left:4px solid var(--teal);
  border-radius:10px; padding:14px 18px; margin-top:10px; font-size:1.02rem;
  color:var(--ink); box-shadow:0 14px 30px -26px rgba(20,35,58,.5);
}
.agent-answer-label{
  display:block; font-family:'IBM Plex Mono',monospace; font-size:.66rem;
  letter-spacing:.22em; text-transform:uppercase; color:var(--teal); margin-bottom:6px;
}
</style>
"""


def render_hero() -> None:
    st.markdown(
        """
        <div class="hero">
          <div class="hero-eyebrow">Receipts → structured ledger · runs locally</div>
          <h1 class="hero-title">Receipt&nbsp;Ledger</h1>
          <p class="hero-sub">Drop any receipt — restaurant, cafe, grocery, retail.
          A local vision model reads the merchant, line items, discounts, tax and
          totals, reconciles the figures, and hands you a clean ledger you can
          query in plain English.</p>
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
            "- `ollama pull nomic-embed-text` (for the ledger agent)\n"
            "- Receipts as PNG / JPG / WEBP"
        )
        st.caption("Works with any store, restaurant, or retail receipt. "
                   "Reconciliation checks that line items add up to the total.")

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
        from core import extract_receipt_validated, save_receipt, GuardrailError

        summaries: list[dict] = []
        item_frames: list[pd.DataFrame] = []
        session_ids: list[int] = []
        progress = st.progress(0.0)

        for i, upload in enumerate(uploads, start=1):
            with st.spinner(f"Reading {upload.name} ({i}/{len(uploads)})…"):
                image_bytes = upload.getvalue()
                left, right = st.columns([1, 1.4])
                left.image(image_bytes, caption=upload.name)
                try:
                    # Guardrails (input/output validation) + LLMOps (MLflow) +
                    # Structured Outputs (Pydantic) all happen inside this call.
                    validated, review_reasons = extract_receipt_validated(
                        image_bytes, model, content_type=upload.type
                    )
                    data = validated.model_dump()
                except GuardrailError as exc:
                    right.error(f"Rejected {upload.name}: {exc}")
                    progress.progress(i / len(uploads))
                    continue
                except Exception as exc:  # noqa: BLE001 - report any failure in the UI
                    right.error(f"Couldn't read {upload.name}: {exc}")
                    progress.progress(i / len(uploads))
                    continue

                right.markdown(receipt_card_html(data, upload.name), unsafe_allow_html=True)
                with right.expander("Raw extracted JSON"):
                    st.json(data)

                # Disambiguation: surface anything that needs a human decision
                # instead of silently filing it.
                if review_reasons:
                    right.warning(
                        "Needs your review before this is treated as final:\n\n"
                        + "\n".join(f"- {r}" for r in review_reasons)
                    )

                # Memory: persist every processed receipt to the SQLite ledger
                # so it can be queried later (including across sessions). This also
                # indexes the receipt for RAG semantic search.
                rid = save_receipt(validated, upload.name, flagged=bool(review_reasons))
                session_ids.append(rid)

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
        st.session_state["session_receipt_ids"] = session_ids

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

    render_agent_section()


# --------------------------------------------------------------------------- #
# Ledger agent — a ReAct loop that streams its reasoning to the UI
# --------------------------------------------------------------------------- #
def _thought_only(text: str) -> str:
    """Keep just the Thought portion of a ReAct block for display, dropping the
    Action/Action Input lines (they're shown as their own step)."""
    cut = re.split(r"\n?\s*Action\s*:", text, maxsplit=1)[0]
    cut = re.sub(r"^\s*Thought\s*:\s*", "", cut.strip(), flags=re.IGNORECASE)
    return cut.strip()


def _short(s, n: int = 200) -> str:
    """Collapse whitespace and truncate — keeps each trace line to one short line."""
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _obs_summary(ev: dict) -> str:
    """One compact line describing a tool result, for the live reasoning trace."""
    data = ev.get("data") or {}
    kind = data.get("kind")
    if kind == "sql":
        rows = data.get("rows") or []
        sql = _short((data.get("sql") or "").replace("\n", " "), 110)
        n = len(rows)
        return f"ran query · {n} row{'' if n == 1 else 's'} · `{sql}`"
    if kind == "search":
        hits = data.get("hits") or []
        if not hits:
            return "searched receipts · no matches"
        names = ", ".join(f"#{h['receipt_id']} {h.get('vendor_name') or '—'}" for h in hits[:4])
        return f"searched receipts · {len(hits)} found · {names}"
    if kind == "note":
        return "already had that result — answering"
    return _short(ev.get("text", ""), 160)


# --- Scope resolution: which receipt(s) is a question about? -----------------
_SINGLE_NOUNS = ("receipt", "vendor", "store", "merchant", "invoice", "bill",
                 "cashier", "purchase", "order", "transaction")
_SINGLE_PHRASES = ("who is", "who's", "what did i buy", "what was ordered",
                   "what i bought", "this ", "that ", "the total", "the date",
                   "the amount", "the vendor", "the store")
_MULTI_SIGNALS = ("all ", "receipts", "vendors", "how many", "across", "each ",
                  "every", "average", "avg", " top ", "between", "this month",
                  "this year", "per ", "total spend", "most ", "least ", "compare",
                  "sum of", "in total", "how much have i")


def _looks_singular(q: str) -> bool:
    """Heuristic: does the question refer to ONE specific receipt (e.g. 'who is the
    vendor?') rather than the whole ledger ('how many receipts?')."""
    t = f" {q.lower().strip()} "
    if any(sig in t for sig in _MULTI_SIGNALS):
        return False
    if any(p in t for p in _SINGLE_PHRASES):
        return True
    # a singular noun that isn't obviously pluralized
    return any(f"{n} " in t or f"{n}?" in t or f"{n}'" in t for n in _SINGLE_NOUNS)


_ORDINALS = {"first": 0, "1st": 0, "earliest": 0, "oldest": 0,
             "second": 1, "2nd": 1, "third": 2, "3rd": 2, "fourth": 3, "4th": 3}


def _resolve_reference(text: str, candidates: list[dict]) -> int | None:
    """Map a phrase like 'the SM one', '#5', 'the second', 'the latest' to a receipt
    id among the candidates. This is what lets follow-up questions re-pick which
    receipt the conversation is about."""
    if not candidates:
        return None
    t = text.lower()
    ids_sorted = sorted(c["id"] for c in candidates)

    m = (re.search(r"#\s*(\d+)", t) or re.search(r"receipt\s+(?:no\.?\s*|number\s*)?(\d+)", t)
         or re.search(r"\bid\s*(\d+)", t))
    if m and int(m.group(1)) in ids_sorted:
        return int(m.group(1))
    if re.search(r"\b(latest|last|recent|newest|most recent)\b", t):
        return ids_sorted[-1]
    for word, idx in _ORDINALS.items():
        if re.search(rf"\b{word}\b", t) and idx < len(ids_sorted):
            return ids_sorted[idx]
    tokens = set(re.findall(r"[a-z0-9]{3,}", t))
    for c in candidates:
        vtokens = set(re.findall(r"[a-z0-9]{3,}", (c.get("vendor_name") or "").lower()))
        if vtokens and (tokens & vtokens):
            return c["id"]
    return None


def _resolve_scope(question: str, session_ids: list[int]):
    """Decide which receipts a question is about → (receipt_ids | None, note).
    None means the whole ledger."""
    from core import get_latest_receipt_id, get_receipts_by_ids

    candidates = get_receipts_by_ids(session_ids) if session_ids else []

    # An explicit reference ('the Jollibee one', '#3', 'the latest') always wins —
    # this is what makes follow-up disambiguation work.
    ref = _resolve_reference(question, candidates)
    if ref is not None:
        return [ref], f"Scoped to receipt #{ref}."

    if _looks_singular(question):
        if len(session_ids) > 1:
            latest = max(session_ids)
            listing = ", ".join(f"#{c['id']} {c.get('vendor_name') or '—'}" for c in candidates)
            note = (
                f"You uploaded {len(session_ids)} receipts, so I answered about the most "
                f"recent (#{latest}). Ask a follow-up naming another to switch — by vendor, "
                f"“the first one”, or “#id”. Uploaded: {listing}."
            )
            return [latest], note
        if len(session_ids) == 1:
            return [session_ids[0]], None
        latest = get_latest_receipt_id()
        if latest is not None:
            return [latest], f"Scoped to your most recent receipt (#{latest})."

    return None, None


def _stream_agent_into(box, question: str, receipt_ids):
    """Run the ReAct loop, rendering its reasoning into a SINGLE placeholder that is
    replaced (not appended) and capped to a short tail. Because it never grows, the
    most recent activity is always visible — the user never has to scroll down.
    Returns the final answer."""
    from core import agent_stream

    MAX_LINES = 6
    trace: list[str] = []   # completed reasoning lines, oldest → newest
    current = ""            # streaming thought buffer
    step_no = 0
    final_answer = None
    live = box.empty()

    def paint(active: str = "") -> None:
        lines = list(trace)
        if active:
            lines.append(active)
        # tight line breaks (not paragraph gaps) keep the tail inside the box
        live.markdown("  \n".join(lines[-MAX_LINES:]) or "_thinking…_")

    paint("🧠 _thinking…_")
    try:
        for ev in agent_stream(question, receipt_ids=receipt_ids):
            kind = ev["type"]
            if kind == "token":
                current += ev["text"]
                paint(f"🧠 _{_short(_thought_only(current), 160) or '…'}_")
            elif kind == "action":
                if current.strip():
                    trace.append(f"🧠 _{_short(_thought_only(current), 160)}_")
                step_no += 1
                trace.append(f"**Step {step_no} · `{ev['tool']}`** → {_txt(ev['input'])}")
                current = ""
                paint()
            elif kind == "observation":
                trace.append(f"↳ {_obs_summary(ev)}")
                paint()
            elif kind == "final":
                final_answer = ev["answer"]
            elif kind == "error":
                trace.append(f"⚠ {ev['message']}")
                paint()
                return None
    except Exception as exc:  # noqa: BLE001
        live.error(f"Couldn't answer that: {exc}")
        return None
    trace.append(f"**✓ Done · {step_no} tool call(s)**")
    paint()
    return final_answer


def render_agent_section() -> None:
    """A chat over every receipt you've processed. It routes each question to a
    ledger query (numbers) or a semantic search (content), streams its reasoning
    into a scrollable box, and auto-scopes singular questions to your latest upload
    — with follow-ups to switch receipts."""
    st.markdown('<div class="eyebrow">Ask your receipts</div>', unsafe_allow_html=True)
    st.caption(
        "Singular questions (“who’s the vendor?”) default to your latest upload — ask "
        "a follow-up (by vendor, “the first one”, or “#id”) to switch. Aggregate "
        "questions (“how much did I spend?”) search the whole ledger."
    )

    if "agent_chat" not in st.session_state:
        st.session_state["agent_chat"] = []

    session_ids = st.session_state.get("session_receipt_ids") or []
    force_batch = False
    if session_ids:
        force_batch = st.toggle(
            f"Hard-limit every question to the {len(session_ids)} receipt(s) I just uploaded",
            value=False,
            help="On: a sandbox containing ONLY those receipts — others are physically "
                 "unreadable. Off: smart per-question scoping (latest for singular, "
                 "whole ledger for aggregates).",
        )

    # Replay the conversation so far — answers only, so the page stays clean.
    for msg in st.session_state["agent_chat"]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"], unsafe_allow_html=True)

    question = st.chat_input("Ask about your receipts…")
    if not question or not question.strip():
        return

    st.session_state["agent_chat"].append({"role": "user", "content": html.escape(question)})
    with st.chat_message("user"):
        st.markdown(question)

    if force_batch and session_ids:
        receipt_ids, note = session_ids, None
    else:
        receipt_ids, note = _resolve_scope(question, session_ids)

    with st.chat_message("assistant"):
        if note:
            st.caption(note)
        # ChatGPT-style: the reasoning streams inside a fixed-height, scrollable box.
        box = st.container(height=240, border=True)
        final_answer = _stream_agent_into(box, question, receipt_ids)
        if final_answer:
            answer_html = (
                f'<div class="agent-answer"><span class="agent-answer-label">Answer</span>'
                f"{html.escape(final_answer)}</div>"
            )
            st.markdown(answer_html, unsafe_allow_html=True)
            st.session_state["agent_chat"].append({"role": "assistant", "content": answer_html})


if __name__ == "__main__":
    main()
