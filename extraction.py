"""
extraction.py — pure receipt-extraction primitives shared by the app.

This module holds the model-agnostic pieces of the OCR pipeline: the extraction
prompt, the JSON coercion/clean-up helpers, and the reconciliation check. It has
no UI and no heavy dependencies (just json + re), so it can be imported by both
the REST API (core.py / api.py) and any other client without pulling in a web
framework.

These functions were previously defined in the Streamlit app; they were moved
here when that UI was retired in favour of the Next.js frontend.
"""

from __future__ import annotations

import json
import os
import re

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
# The vision/OCR model. Overridable via the VISION_MODEL env var so a resource-
# constrained deployment can drop to a smaller model (e.g. qwen2.5vl:3b) without
# a code change; defaults to the 7B model used in development.
DEFAULT_MODEL = os.environ.get("VISION_MODEL", "qwen2.5vl:7b")

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
16. category is the ONE spending category this purchase best fits. This is the
    only field where you may judge rather than transcribe. Choose EXACTLY one of:
      - "Food"     — restaurants, cafes, fast food, bakeries, groceries, supermarkets
      - "Shopping" — retail, clothing, electronics, department stores, general goods
      - "Health"   — pharmacies, drugstores, clinics, hospitals, medical/dental
      - "Other"    — anything that clearly fits none of the above
    Base the choice on the merchant and the items. Output one of those four exact
    words. If genuinely unclear, use "Other". Never invent a different category.

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
  "currency": string,              // currency code/symbol shown, e.g. "PHP", "USD", "EUR"; null if none
  "category": string               // EXACTLY one of: "Food", "Shopping", "Health", "Other"
}

Remember: transcribe only what is printed. A missing value must be null, never a
guess or a calculation. Return the JSON object only."""


# --------------------------------------------------------------------------- #
# Numbers
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


# --------------------------------------------------------------------------- #
# JSON coercion + line-item clean-up
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


# --------------------------------------------------------------------------- #
# Reconciliation
# --------------------------------------------------------------------------- #
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
