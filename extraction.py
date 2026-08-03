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
# The vision/OCR model, served by the shared Ollama endpoint (see core.OLLAMA_HOST).
# Overridable via the VISION_MODEL env var so a deployment can run a local model
# (e.g. qwen2.5vl:7b) without a code change.
#
# gemma4:e4b is the production choice and now matches docker-compose.yml, which had
# been overriding a qwen2.5vl:7b default here — so the same code read receipts with
# a different model depending only on how it was launched.
#
# Note gemma4 encodes an image to a FIXED ~256 tokens regardless of resolution, so
# resolution/crop tuning does not reduce its prompt cost the way it does on
# qwen2.5vl (~2,100 image tokens, scaling with pixels). See evaluation/PERFORMANCE.md.
DEFAULT_MODEL = os.environ.get("VISION_MODEL", "gemma4:e4b")

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
7b. NUMBERS INSIDE A PRODUCT NAME ARE PART OF THE NAME — NEVER A PRICE, NEVER A
   QUANTITY. Product names routinely contain digits: "Mineral Water 500ml",
   "Coke 1.5L", "Pancit Canton 60g", "Eggs 12s", "SPF 50 Sunblock", "Chanel No. 5",
   "iPhone 15", "Size 32 Jeans", "2pc Chicken", "Tide 3-in-1". A number that is
   attached to a unit of measure (ml, L, li, g, kg, mg, oz, lb, pc, pcs, pk, pack,
   ct, s, cm, mm, in, %, W, GB) or that reads as part of the product's name stays
   in "description". Examples of the ONLY correct reading:
     "Mineral Water 500ml        25.00"  -> description "Mineral Water 500ml",
        quantity null, unit_price null, amount 25.00   (NOT amount 500, NOT qty 500)
     "Coke 1.5L                  85.00"  -> description "Coke 1.5L", amount 85.00
     "2pc Chicken Meal          189.00"  -> description "2pc Chicken Meal",
        quantity null, amount 189.00   ("2pc" is the product's name, not a quantity)
7c. HOW TO TELL WHICH NUMBER ON A LINE IS THE PRICE: the price is the number in the
   receipt's right-hand money column — the LAST number on the line, vertically
   aligned with the prices on every other line, normally printed with two decimal
   places and/or a currency symbol. A number sitting inside the text, or one with no
   decimals while all the prices on this receipt have decimals, is part of the
   description. If a line's only trailing number is a size ("Bottled Water 350ml")
   because the price column was cut off or unreadable, set amount to null — do not
   promote the size to the price.
7d. quantity is only a count printed in the receipt's own quantity position: a
   "QTY" column, a leading standalone integer in that column, or the notation
   "2 x" / "2 @" / "x2". Anything else — including a number welded to a unit —
   is not a quantity.
8. TAX (VAT / GST / sales tax): COPY the printed money figure; never compute it,
   and never take a percentage of anything.
   a. vat_amount must be a MONEY figure printed beside a tax label. "12%",
      "VAT 12%", "TAX RATE 12%", "V" and "(V)" line markers are RATES or FLAGS,
      not amounts. NEVER put 12 (or any bare percentage) into vat_amount.
   b. "VAT (12%)  58.39" -> vat_amount is 58.39. "VAT (12%)" printed with no money
      figure beside or beneath it -> vat_amount is null.
   c. NEVER calculate the tax as 12% of the subtotal, the total, or the vatable
      sales, and never back it out of an inclusive price. If the tax amount is not
      printed, the correct answer is null. A computed figure is a WRONG answer.
   d. vatable_sales is the figure printed beside "VATable Sales" / "Taxable Sales"
      / "Amount Net of VAT" — normally SMALLER than the total. Never copy the
      subtotal or the total into it and never derive it from them.
   e. A printed 0.00 is a real value: "VAT-Exempt Sales 0.00" -> 0.00, not null.
   f. Never put a tax figure into "discount". A senior-citizen "Less VAT" line is
      a VAT deduction, not a discount — if the label says VAT, it is not a discount.
8b. DISCOUNT: only a printed, labeled deduction, copied as a money amount.
   a. discount is the MONEY figure on a line labeled "Discount", "Less Discount",
      "SC Disc", "PWD Discount", "Promo", "Coupon", "Less". Copy that figure.
   b. "20%", "SC 20%", "Disc 5%" is a RATE. NEVER put 20 or 5 into discount. If the
      receipt prints only the rate and no money amount, discount is null.
   c. A deduction printed as "-50.00" or "(50.00)" is a POSITIVE 50.00 in discount.
   d. If NO discount line is printed, discount and discount_type are BOTH null.
      Never invent a discount, and never add one to make the numbers balance.
   e. discount_type is the WORD printed on that line ("Senior Citizen", "PWD",
      "Promo", "Loyalty", "Employee", "Coupon") — never a number or a percentage.
9. "items" is ONLY for purchased products/services. Summary and tax lines —
   Subtotal, Taxable/VATable Sales, Tax-Exempt Sales, Zero-Rated Sales, VAT/Tax,
   Discount, Total, Cash, Change — are NOT items. Put each in its own dedicated
   field and never list it inside "items".
10. Keep payment lines separate. total_amount is the "Total" / "Amount Due" line
    ONLY. The cash the customer handed over ("CASH", "TENDERED", "AMOUNT PAID")
    goes in "cash". The money returned ("CHANGE") goes in "change". Never put the
    cash or the change into total_amount.
10b. A tax breakdown does NOT get added to anything. On a VAT-inclusive receipt
    (the usual layout in the Philippines and most of Asia/Europe) the "VATable
    486.61 / 12% VAT 58.39" table is a BREAKDOWN of the 545.00 already charged —
    486.61 + 58.39 = 545.00 — not a tax to add on top. NEVER produce a total by
    adding vat_amount to the subtotal, and never recompute change from it.
    total_amount is the FINAL amount the customer was charged — the bottom line,
    the figure they actually paid. When the receipt prints no "Total" / "Amount
    Due" line, that final amount is still on the receipt: it is the last summary
    figure before the payment lines, normally the SUBTOTAL. Copy that figure into
    total_amount exactly as printed. On the Pepper Lunch example above the answer
    is 545.00 — not 603.39 (that is 545.00 with the VAT wrongly added back on) and
    not null. Copy it; never build it by arithmetic. The one exception: if a
    DISCOUNT line is printed, the final amount charged is the figure AFTER the
    discount — use the discounted figure the receipt prints, and if the receipt
    only prints the pre-discount subtotal, leave total_amount null so it is not
    overstated. Copy the printed CHANGE figure as printed — never work it out as
    cash minus a total.
10c. CHANGE is ONLY the money figure printed beside "CHANGE" / "CHANGE DUE" /
    "SUKLI". Copy that figure exactly, digit for digit. NEVER compute it, NEVER
    derive it from cash minus the total, and NEVER adjust it to make the receipt
    balance. If the receipt prints CHANGE 455.00, the answer is 455.00 even when
    your own arithmetic says otherwise — your arithmetic is not evidence, the
    printed figure is. A printed "CHANGE 0.00" is 0.00, not null.
10d. If no CHANGE line is printed, change is null. If no CASH / TENDERED line is
    printed, cash is null. Card, GCash, Maya and other cashless receipts usually
    print neither — leave both null rather than copying the total into cash or
    putting 0 into change.
10e. Never let one payment figure overwrite another: the number beside "CASH" goes
    only in cash, the number beside "CHANGE" goes only in change, and neither ever
    lands in total_amount.
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
14. Transcribe EVERY printed line item, top to bottom, including the ones that
    repeat. If the same product at the same price is printed on three separate
    lines, output three separate rows — do not merge them into one row and do not
    add up their quantities. The only rows to leave out are echoes of a line you
    have already recorded (the same line printed once but wrapped onto a
    continuation line).
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
17. receipt_date is the date the PURCHASE was made — the transaction date — and
    nothing else.
    a. It is the date printed in the header block, beside the receipt/OR/invoice
       number, or on the same line as the time of sale ("06/14/2026 14:32").
       The date printed next to the transaction time is almost always the one.
    b. IGNORE every other date on the paper. These are NOT the receipt date:
       "Valid until" / "Valid from", ATP / PTU / permit / BIR accreditation dates
       ("ATP No. ... issued 01/02/2024", "Accred. Date", "Serial No. ... valid
       until 2027"), warranty, return-policy and exchange deadlines, expiry or
       best-before dates, birth dates in a senior-citizen/PWD block, membership
       expiry, and anything printed in the small-print footer.
    c. Output YYYY-MM-DD. Work out the field order from the receipt itself:
       - A component greater than 12 MUST be the day: "25/06/2026" -> 2026-06-25.
       - A spelled or abbreviated month is decisive: "14 JUN 2026" -> 2026-06-14,
         "JUN 14, 2026" -> 2026-06-14, "2026-JUN-14" -> 2026-06-14.
       - A 4-digit component is the year. A 2-digit year "26" means 2026.
       - Only if the order is still ambiguous (all numeric, both components 12 or
         under) read it as MONTH/DAY/YEAR — the convention on Philippine and US
         receipts: "03/08/2026" -> 2026-03-08.
    d. Copy the digits as printed. Do not shift, swap, correct or "modernise" the
       year, and never substitute today's date. If the transaction date is not
       printed or not legible, receipt_date is null.
    e. Put only the date in receipt_date — no time, no day name.

Return ONLY a single valid JSON object — no prose, no markdown fences. Use these
exact keys. Use null when a value is not present. Money values are plain numbers
(no currency symbols, no commas).

{
  "vendor_name": string,
  "vendor_tin": string,            // merchant tax ID if labeled (TIN/GST/Tax ID/etc.); else null. NOT the receipt no.
  "vendor_address": string,
  "receipt_number": string,        // receipt / invoice / OR / SI no.
  "receipt_date": string,          // TRANSACTION date only, YYYY-MM-DD (rule 17). Not a
                                   // permit/ATP/valid-until/expiry date. null if not printed.
  "items": [
    {
      "description": string,       // item name as printed, INCLUDING sizes like "500ml", "1.5L"
      "quantity": number,          // only a printed count ("2 x", "QTY 2"); a size is not a quantity
      "unit_price": number,        // only if a unit/per-item price is printed for this line; else null
      "amount": number             // the price from the right-hand money column; never a size/volume
    }
  ],
  "subtotal": number,              // the subtotal / gross amount line, before tax and discounts
  "vatable_sales": number,         // EXACT printed taxable-sales figure; null if not printed. Never derived.
  "vat_exempt_sales": number,      // tax-exempt sales
  "zero_rated_sales": number,      // zero-rated sales
  "vat_amount": number,            // EXACT printed tax/VAT MONEY figure; never a % rate, never computed
  "discount": number,              // printed discount MONEY amount, always positive; never a % rate
  "discount_type": string,         // the word on the discount line: "Promo", "Loyalty", "Senior Citizen",
                                   // "PWD", "Coupon"; null when no discount line is printed
  "total_amount": number,          // FINAL amount charged: the "Total"/"Amount Due" line, else the
                                   // printed subtotal. Never subtotal+VAT. NOT cash, NOT change.
  "cash": number,                  // cash tendered / amount paid by the customer ("CASH", "TENDERED")
  "change": number,                // the figure printed beside "CHANGE" — copied, never cash minus total
  "currency": string,              // currency code/symbol shown, e.g. "PHP", "USD", "EUR"; null if none
  "category": string               // EXACTLY one of: "Food", "Shopping", "Health", "Other"
}

Before you answer, check these five — they are where this task usually goes wrong:
  1. Every item amount came from the right-hand price column. No size or volume
     from a product name ("500ml", "1.5L", "60g", "2pc") was used as an amount,
     a unit_price or a quantity.
  2. vat_amount is a printed money figure, not a percentage and not something you
     worked out. If no tax amount was printed, it is null.
  3. discount is a printed money figure, not a percentage, and it is null if no
     discount line was printed.
  4. change is exactly the number printed beside "CHANGE" — not cash minus total.
  5. receipt_date is the transaction date, not a permit / valid-until / expiry
     date, and its day and month are the right way round.

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
    # A container is not a misformatted number, it is a wrong shape. Falling through
    # to the string path would stringify it and strip the punctuation out, so
    # `[1, 2]` became 12.0 and `{"amount": 1}` became 1.0 — a fabricated figure with
    # no basis on the receipt. These run on the *unvalidated* model dict (core.py's
    # post-processing chain), so the number would reach pydantic looking legitimate.
    if isinstance(value, (list, tuple, set, dict)):
        return None
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
    """Drop the echo rows the model emits for a single printed line, e.g. one
    "Peri-Peri Chicken ₱540" row plus a bare "Peri-Peri Chicken" row with no
    amount. Only amount-less echoes are removed: the priced row wins and the
    echo is discarded.

    Rows that carry an amount are ALWAYS kept, even when a same-named row with
    the same amount is already present. Receipts genuinely print the same
    product at the same price on consecutive lines (Bench Boutique prints
    "Kiss & Tell Deo Body Spray 128.00" three times), and collapsing those
    silently deletes money from the ledger. If the model really did double up a
    line, reconcile() flags the mismatch for review rather than us guessing.
    Blank descriptions are always kept (e.g. modifiers).
    """
    result: list[dict] = []
    unpriced: dict[str, int] = {}  # key -> index of an amount-less row awaiting a price
    priced: set[str] = set()
    for item in data.get("items") or []:
        key = re.sub(r"[^a-z0-9]", "", str(item.get("description") or "").lower())
        amt = _num(item.get("amount"))
        if not key:
            result.append(item)
            continue
        if amt is None:
            if key in priced or key in unpriced:
                continue  # echo of a row we already have -> drop
            unpriced[key] = len(result)
            result.append(item)
        else:
            if key in unpriced:
                result[unpriced.pop(key)] = item  # fill the echo row in place
            else:
                result.append(item)
            priced.add(key)
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


def _gross_anchor(data: dict) -> float | None:
    """The receipt's own gross figure before payment: the printed subtotal, or the
    line items' sum when no subtotal was printed. None when neither is available."""
    subtotal = _num(data.get("subtotal"))
    if subtotal is not None:
        return subtotal
    amounts = [a for a in (_num(i.get("amount")) for i in data.get("items") or [])
               if a is not None]
    return round(sum(amounts), 2) if amounts else None


def vat_is_inside_subtotal(data: dict) -> bool:
    """True when the printed tax breakdown decomposes the subtotal instead of
    sitting on top of it — i.e. the receipt is VAT-inclusive.

    The tell is arithmetic, printed on the receipt itself: on a VAT-inclusive
    receipt the taxable-sales figure is the amount NET of tax, so
    `vatable + exempt + zero-rated + vat == subtotal` (Pepper Lunch:
    486.61 + 58.39 = 545.00). On a tax-exclusive receipt the breakdown lines add
    up to the subtotal on their own and the tax is charged on top. We only return
    True when the inclusive reading holds and the exclusive one does not, so an
    ambiguous receipt (zero VAT, no breakdown printed) is never claimed either way.
    """
    gross = _gross_anchor(data)
    vat = _num(data.get("vat_amount"))
    if gross is None or gross <= 0 or not vat or vat <= 0:
        return False
    parts = [p for p in (_num(data.get("vatable_sales")),
                         _num(data.get("vat_exempt_sales")),
                         _num(data.get("zero_rated_sales"))) if p is not None]
    if not parts:
        return False
    parts_sum = round(sum(parts), 2)
    return abs(parts_sum + vat - gross) <= 0.5 and abs(parts_sum - gross) > 0.5


def undo_vat_added_to_total(data: dict) -> dict:
    """Undo a total the model built by adding a VAT-inclusive tax figure back on.

    This is the Pepper Lunch failure: the receipt prints SUBTOTAL 545.00, CASH
    1,000.00, CHANGE 455.00 and a "VATable 486.61 / 12% VAT 58.39" table, and no
    Total line at all. The model transcribed every figure correctly, then did the
    arithmetic it is told not to do — total 545.00 + 58.39 = 603.39, and change
    1,000.00 − 603.39 = 396.61. Both invented numbers, and the receipt was charged
    ₱58.39 more than it cost.

    `_fix_payment_fields` could not catch it: its cash − change == total identity
    HOLDS on the invented pair, because the model derived one from the other. So we
    check against the receipt's own breakdown instead, and only act on direct
    evidence: the VAT is demonstrably inside the subtotal AND the total is exactly
    the subtotal plus that VAT. A genuinely tax-exclusive receipt fails the first
    test, and a printed total that agrees with the subtotal fails the second, so
    neither is touched.

    The Bench Boutique lesson — a partly-captured item list must never rewrite a
    printed total — holds here even when the anchor falls back to the item sum:
    that fallback is only reached when the printed breakdown adds up to it exactly
    (`vatable + VAT == the anchor`), which a partial item list does not do.
    """
    if not vat_is_inside_subtotal(data):
        return data
    gross = _gross_anchor(data)
    total = _num(data.get("total_amount"))
    vat = _num(data.get("vat_amount"))
    if gross is None or total is None:
        return data

    due = round(gross - (_num(data.get("discount")) or 0.0), 2)
    inflated = round(due + vat, 2)
    # Only when the total IS the inflated figure and is not already the right one.
    if abs(total - inflated) > 0.5 or abs(total - due) <= 0.5:
        return data
    data["total_amount"] = due

    # The change was computed off the inflated total, so it is inflated's mirror
    # image, not a figure read off the paper — re-derive it from the corrected due.
    cash = _num(data.get("cash"))
    change = _num(data.get("change"))
    if cash is not None and change is not None and abs(cash - change - inflated) <= 0.5:
        data["change"] = round(cash - due, 2)
    return data


def undo_discount_omitted_from_total(data: dict) -> dict:
    """Undo a total copied from the subtotal on a receipt that also printed a discount.

    Rule 10b now tells the model that when no "Total" / "Amount Due" line is
    printed, the final amount charged is the printed subtotal — which is right on
    the common VAT-inclusive receipt, and is what stops totals coming back null.
    But on a receipt that prints SUBTOTAL 500.00 / DISCOUNT 50.00 and no total, a
    literal reading of that instruction copies 500.00, overstating the charge by
    the discount.

    `_fix_payment_fields` cannot correct it: it deliberately never replaces a total
    the model transcribed (the Bench Boutique lesson — a partly-captured item list
    once rewrote a correctly read "TOTAL SALE 972.00" down to 256.00), and by then
    this total looks transcribed.

    So we act only on arithmetic the receipt itself prints: the payment lines have
    to independently confirm the discounted figure (cash − change == subtotal −
    discount). A receipt whose total genuinely equals its subtotal fails that test,
    because its own cash/change agree with the undiscounted amount. Without both
    payment figures there is no evidence, and nothing is touched.
    """
    subtotal = _num(data.get("subtotal"))
    total = _num(data.get("total_amount"))
    discount = _num(data.get("discount")) or 0.0
    cash = _num(data.get("cash"))
    change = _num(data.get("change"))
    if subtotal is None or total is None or discount <= 0:
        return data
    if cash is None or change is None:
        return data  # no independent check available — leave it for review
    if abs(total - subtotal) > 0.5:
        return data  # the total isn't a copy of the subtotal; not our case
    due = round(subtotal - discount, 2)
    if abs(cash - change - due) <= 0.5:
        data["total_amount"] = due
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

    Runs `undo_vat_added_to_total` first: a total the model produced as
    subtotal + VAT satisfies the cash − change == total identity below (the model
    derived the change from it), so it has to be undone before that identity is
    allowed to certify the payments as consistent.
    """
    data = undo_vat_added_to_total(data)
    # Then the discount case, for the same reason: a total copied off the subtotal
    # on a discounted receipt also satisfies cash − change == total only if it is
    # already right, so it must be settled before that identity is trusted below.
    data = undo_discount_omitted_from_total(data)

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

    # Couldn't reassign cleanly. Only fill in a total we never read; NEVER
    # replace one the model transcribed off the receipt. `due` is anchored to
    # subtotal-or-item-sum, and both go wrong on a long receipt whose lines were
    # only partly captured — on the Bench Boutique receipt that turned a
    # correctly read "TOTAL SALE 972.00" into 256.00. A total that disagrees with
    # the anchor is left alone for reconcile() to flag for human review.
    if total is None:
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


# --------------------------------------------------------------------------- #
# Arithmetic audit — runs once, immediately after the model has read a receipt
#
# `reconcile()` above answers ONE question: do the line items add up to the printed
# total? That is the check the ledger has always run, and it stays exactly as it was
# because the review wiring and 34 tests depend on it.
#
# `audit_receipt()` is the wider sweep, and the *subtotal* check is the reason it
# exists: items summing to the total tells you the receipt is internally consistent
# AFTER tax and discounts, which can hide a misread line — a dropped ₱120 item and a
# ₱120 discount the model invented cancel out and reconcile() stays silent. Items
# against the SUBTOTAL is the check that catches a line the OCR got wrong, because
# the subtotal is the one printed figure that is supposed to be exactly the sum of
# the lines above it, before anything is added or taken away.
#
# Every finding is structured (code / severity / the two numbers and their gap) so
# the API and UI can render it, and so a future eval can count findings by code
# rather than grepping prose. Nothing here CORRECTS anything — the whole pipeline's
# rule is "transcribe, then repair, never compute", and an audit that silently fixed
# the subtotal would be computing.
# --------------------------------------------------------------------------- #

# Philippine VAT. Only used to sanity-check a printed VAT figure against printed
# vatable sales — never to derive one that wasn't on the receipt.
VAT_RATE = 0.12

# Absolute floor and relative band, matching reconcile(): OCR noise and genuine
# per-line rounding on a long receipt both scale with the amount, so a flat
# tolerance either screams on big receipts or misses real errors on small ones.
AUDIT_ABS_TOLERANCE = 1.0
AUDIT_REL_TOLERANCE = 0.02


def _tolerance(base: float) -> float:
    return max(AUDIT_ABS_TOLERANCE, abs(base) * AUDIT_REL_TOLERANCE)


def _finding(code: str, severity: str, message: str,
             expected=None, found=None) -> dict:
    diff = None
    if expected is not None and found is not None:
        diff = round(found - expected, 2)
    return {"code": code, "severity": severity, "message": message,
            "expected": expected, "found": found, "difference": diff}


def audit_receipt(data: dict) -> list[dict]:
    """Audit an extracted receipt's arithmetic and return structured findings.

    Call this once per receipt, immediately after the model's output has been
    cleaned and schema-validated (`core._run_vision_model` does). It reads only
    values already transcribed from the receipt and never writes any back.

    Severity:
      * `error`   — the receipt does not add up; a human should confirm it before
                    it is trusted. These become human-review reasons.
      * `warning` — worth showing next to the receipt, but not on its own a reason
                    to block: the figure may simply not have been printed, or the
                    receipt may follow a different tax convention.

    Returns `[]` for a receipt whose math is consistent, and for one too sparse to
    check — an absent figure is not a failed check, and reporting it as one would
    flag every receipt that omits a subtotal.
    """
    findings: list[dict] = []

    items = data.get("items") or []
    amounts = [a for a in (_num(i.get("amount")) for i in items) if a is not None]
    items_sum = round(sum(amounts), 2) if amounts else None

    subtotal = _num(data.get("subtotal"))
    total = _num(data.get("total_amount"))
    discount = _num(data.get("discount")) or 0.0
    vat = _num(data.get("vat_amount"))
    vatable = _num(data.get("vatable_sales"))
    exempt = _num(data.get("vat_exempt_sales"))
    zero_rated = _num(data.get("zero_rated_sales"))
    cash = _num(data.get("cash"))
    change = _num(data.get("change"))
    cur = _symbol(data.get("currency"))

    # ---- 1. line items vs the printed SUBTOTAL --------------------------- #
    # The headline check. The subtotal is the receipt's own claim about what the
    # lines above it add up to, so a mismatch means a line was misread, dropped, or
    # invented — regardless of whether the total happens to work out.
    if items_sum is not None and subtotal is not None and subtotal > 0:
        if abs(items_sum - subtotal) > _tolerance(subtotal):
            missing = round(subtotal - items_sum, 2)
            direction = ("short by" if missing > 0 else "over by")
            findings.append(_finding(
                "items_vs_subtotal", "error",
                f"The {len(amounts)} line items add up to {cur}{items_sum:,.2f}, "
                f"but the printed subtotal is {cur}{subtotal:,.2f} — "
                f"{direction} {cur}{abs(missing):,.2f}. A line was probably misread "
                f"or missed.",
                expected=subtotal, found=items_sum,
            ))

    # ---- 2. line items vs the printed TOTAL ------------------------------ #
    # Delegated to reconcile() so the two can never drift apart.
    for message in reconcile(data):
        findings.append(_finding(
            "items_vs_total", "error", message,
            expected=total, found=items_sum,
        ))

    # ---- 3. the sales breakdown vs the subtotal --------------------------- #
    parts = [p for p in (vatable, exempt, zero_rated) if p is not None]
    if parts and subtotal is not None and subtotal > 0:
        parts_sum = round(sum(parts), 2)
        # Only meaningful when the breakdown is VAT-inclusive like the subtotal;
        # try the exclusive reading too before reporting anything.
        if (abs(parts_sum - subtotal) > _tolerance(subtotal)
                and abs(parts_sum + (vat or 0.0) - subtotal) > _tolerance(subtotal)):
            findings.append(_finding(
                "sales_breakdown_vs_subtotal", "warning",
                f"The vatable / exempt / zero-rated figures add up to "
                f"{cur}{parts_sum:,.2f}, which doesn't match the subtotal of "
                f"{cur}{subtotal:,.2f}.",
                expected=subtotal, found=parts_sum,
            ))

    # ---- 4. VAT against the vatable sales -------------------------------- #
    if vat is not None and vatable is not None and vatable > 0:
        # Both conventions: VAT-inclusive (vatable already contains the tax) and
        # VAT-exclusive (tax sits on top). Only complain when NEITHER holds.
        inclusive = vatable - (vatable / (1 + VAT_RATE))
        exclusive = vatable * VAT_RATE
        tol = _tolerance(max(inclusive, exclusive))
        if abs(vat - inclusive) > tol and abs(vat - exclusive) > tol:
            findings.append(_finding(
                "vat_rate", "warning",
                f"VAT of {cur}{vat:,.2f} doesn't match {VAT_RATE:.0%} of the "
                f"{cur}{vatable:,.2f} vatable sales "
                f"({cur}{inclusive:,.2f} VAT-inclusive / "
                f"{cur}{exclusive:,.2f} VAT-exclusive).",
                expected=round(inclusive, 2), found=vat,
            ))

    # ---- 5. subtotal and discount against the total ---------------------- #
    if subtotal is not None and total is not None and total > 0:
        inclusive_due = round(subtotal - discount, 2)          # PH receipts usually
        exclusive_due = round(subtotal - discount + (vat or 0.0), 2)  # tax added on
        tol = _tolerance(total)
        if abs(inclusive_due - total) > tol:
            # The exclusive reading is only a legitimate excuse when the receipt
            # actually charges tax on top. When its own breakdown shows the VAT is
            # already inside the subtotal, "total == subtotal + VAT" is the tax
            # counted twice — an error, not an alternative convention.
            if abs(exclusive_due - total) <= tol and vat_is_inside_subtotal(data):
                findings.append(_finding(
                    "vat_added_to_total", "error",
                    f"The total of {cur}{total:,.2f} is the {cur}{inclusive_due:,.2f} "
                    f"due plus the {cur}{vat:,.2f} VAT — but that VAT is already "
                    f"inside the subtotal ({cur}{(vatable or 0.0):,.2f} vatable + "
                    f"{cur}{vat:,.2f} VAT = {cur}{subtotal:,.2f}), so it has been "
                    f"charged twice.",
                    expected=inclusive_due, found=total,
                ))
            elif abs(exclusive_due - total) > tol:
                findings.append(_finding(
                    "subtotal_vs_total", "warning",
                    f"Subtotal {cur}{subtotal:,.2f} less a {cur}{discount:,.2f} discount "
                    f"comes to {cur}{inclusive_due:,.2f}, but the printed total is "
                    f"{cur}{total:,.2f}.",
                    expected=total, found=inclusive_due,
                ))

    # ---- 6. cash and change against the total ---------------------------- #
    if cash is not None and change is not None and total is not None and total > 0:
        paid = round(cash - change, 2)
        if abs(paid - total) > _tolerance(total):
            findings.append(_finding(
                "payment_vs_total", "warning",
                f"Cash {cur}{cash:,.2f} less change {cur}{change:,.2f} is "
                f"{cur}{paid:,.2f}, which doesn't match the total of "
                f"{cur}{total:,.2f}.",
                expected=total, found=paid,
            ))

    # ---- 7. per-line quantity x unit price ------------------------------- #
    for idx, item in enumerate(items):
        qty = _num(item.get("quantity"))
        unit = _num(item.get("unit_price"))
        amount = _num(item.get("amount"))
        if qty is None or unit is None or amount is None or qty <= 0:
            continue
        expected = round(qty * unit, 2)
        if abs(expected - amount) > _tolerance(expected):
            name = (item.get("description") or f"line {idx + 1}").strip()
            findings.append(_finding(
                "line_item_math", "warning",
                f"\"{name}\": {qty:g} x {cur}{unit:,.2f} is {cur}{expected:,.2f}, "
                f"but the line reads {cur}{amount:,.2f}.",
                expected=expected, found=amount,
            ))

    # ---- 8. values that cannot be right ---------------------------------- #
    # A negative total or line amount is not a tolerance question; it means a minus
    # sign or a refund line was read as a purchase.
    if total is not None and total < 0:
        findings.append(_finding(
            "negative_total", "error",
            f"The total reads {cur}{total:,.2f}. A purchase total cannot be negative.",
            found=total,
        ))
    for idx, item in enumerate(items):
        amount = _num(item.get("amount"))
        if amount is not None and amount < 0:
            name = (item.get("description") or f"line {idx + 1}").strip()
            findings.append(_finding(
                "negative_line_item", "warning",
                f"\"{name}\" reads {cur}{amount:,.2f} — a negative line item.",
                found=amount,
            ))

    return findings


def audit_messages(findings: list[dict], severity: str | None = None) -> list[str]:
    """The human-readable half of `audit_receipt`, optionally filtered to one
    severity. Kept separate so callers that need the numbers aren't handed prose."""
    return [f["message"] for f in findings
            if severity is None or f["severity"] == severity]


_CURRENCY_SYMBOLS = {
    "PHP": "₱", "USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥",
    "CNY": "¥", "KRW": "₩", "INR": "₹", "THB": "฿", "VND": "₫",
    "SGD": "S$", "AUD": "A$", "CAD": "C$", "HKD": "HK$", "TWD": "NT$",
    "MYR": "RM", "IDR": "Rp",
}


def _symbol(currency) -> str:
    """Format money in the currency actually printed on the receipt. `reconcile()`
    hardcodes ₱ for backwards compatibility; new findings should not."""
    code = str(currency or "PHP").strip().upper()
    return _CURRENCY_SYMBOLS.get(code, "₱" if not code else f"{code} ")
