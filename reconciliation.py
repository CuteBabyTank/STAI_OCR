"""
reconciliation.py — receipt-to-statement reconciliation.

Snag already reconciles a receipt against *itself* (`extraction.reconcile`: do the line
items add up to the stated total?). This module adds the second, different kind the
consultation proof point names: reconciling receipts against an **external bank or
credit-card statement** — what the bank says was actually charged.

The two are not interchangeable and must never be conflated:

  1. Receipt-internal arithmetic  — "does this receipt add up?"        `extraction.reconcile`
  2. Receipt-to-statement         — "was this receipt actually charged, once, for
                                     this amount?"                      this module

Design decisions, and why
-------------------------
* **Deterministic, no model.** Matching is arithmetic and string normalization. This
  keeps it reproducible, cheap, evaluable without an endpoint, and auditable — a user
  disputing a discrepancy can be shown exactly why two rows were or were not matched.
  It also means every threshold below is a *number the team can defend*, not a model's
  opinion.
* **CSV ingestion is the primary path.** Bank exports are CSV/Excel; a PDF statement
  would need the vision model, which is a separate (and currently unreachable)
  dependency. `parse_statement_csv` is the seam — a future PDF path only has to produce
  the same normalized rows.
* **Signed amounts, negative = money out.** Statements disagree wildly on convention
  (single signed column, separate debit/credit columns, parenthesised negatives), so
  ingestion normalizes once and everything downstream reads one convention.
* **Matching is one-to-one.** A charge is consumed by at most one receipt and vice
  versa. Without this, one receipt could "explain" three identical charges and a
  duplicate-billing error would vanish from the report — the exact failure the report
  exists to catch.
* **Two-pass matching.** An exact pass first, then a discrepancy pass over what is
  left. A ₱500 receipt against a ₱550 charge is *not* two unrelated problems ("missing
  receipt" plus "unmatched receipt"); it is one amount discrepancy, which is far more
  actionable.
* **Every threshold is a parameter with a documented default**, labelled *proposed by
  the team*. None is an instructor requirement and none is derived from measurement,
  because no labelled statement data exists yet.

Nothing here has been validated against real bank exports. The defaults are reasoned,
not measured.
"""

from __future__ import annotations

import csv
import io
import re
import sqlite3
from datetime import date, datetime, timedelta

from core import _connect

# --------------------------------------------------------------------------- #
# Defaults — proposed by the team, not measured, not required by anyone
# --------------------------------------------------------------------------- #
#: A card charge posts after the purchase. 5 days covers a weekend plus a holiday,
#: which is the common worst case for Philippine card settlement. Widening it raises
#: false matches; narrowing it turns ordinary settlement lag into false discrepancies.
DEFAULT_MAX_POSTING_LAG_DAYS = 5

#: A receipt may also predate nothing at all — but clock skew and timezone rollover on
#: a late-night purchase can make a statement post *before* the receipt date by a day.
DEFAULT_MAX_LEAD_DAYS = 1

#: Amounts must agree to the centavo to count as an exact match.
DEFAULT_AMOUNT_TOLERANCE = 0.01

#: How far apart two amounts may be and still be considered "the same purchase with a
#: discrepancy" rather than two unrelated rows. Beyond this they are not related.
#: Expressed as the wider of an absolute floor and a share of the receipt total, the
#: same shape as `extraction.reconcile`'s tolerance.
DEFAULT_DISCREPANCY_ABS = 50.0
DEFAULT_DISCREPANCY_PCT = 0.10

#: Merchant-name agreement required to pair rows whose amounts differ. Names on a
#: statement are mangled ("SM SUPERMARKET MAKATI 0412"), so this is deliberately
#: forgiving — but it is the only thing preventing an amount-discrepancy pairing
#: between two entirely unrelated purchases.
DEFAULT_MIN_MERCHANT_SIMILARITY = 0.34


class ReconciliationError(ValueError):
    """Raised for bad statement input or an unknown statement/receipt."""


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #
def init_reconciliation_schema() -> None:
    """Create the statement tables if absent. Idempotent, mirrors init_finance_schema."""
    with _connect() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS statements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_file TEXT,
                account_id INTEGER,
                kind TEXT,                 -- 'bank' | 'credit_card'
                currency TEXT,
                period_start TEXT,
                period_end TEXT,
                imported_at TEXT,
                FOREIGN KEY (account_id) REFERENCES accounts(id)
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS statement_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                statement_id INTEGER NOT NULL,
                posted_date TEXT,          -- when the bank posted it
                transaction_date TEXT,     -- when the purchase happened, if given
                description TEXT,
                merchant TEXT,             -- normalized description
                -- Signed; NEGATIVE = money out. NULLable on purpose: a row whose
                -- amount could not be read is kept so it appears in the report as
                -- unreadable. Dropping it would remove a charge from the user's view
                -- entirely, which is worse than reporting it as unknown.
                amount REAL,
                row_number INTEGER,
                raw TEXT,
                FOREIGN KEY (statement_id) REFERENCES statements(id)
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS statement_matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                statement_line_id INTEGER NOT NULL,
                receipt_id INTEGER NOT NULL,
                status TEXT NOT NULL,      -- 'matched' | 'amount_mismatch' | 'date_outside_window'
                score REAL,
                amount_delta REAL,         -- receipt total - |charge|
                date_delta_days INTEGER,   -- posted_date - receipt_date
                merchant_similarity REAL,
                matched_at TEXT,
                FOREIGN KEY (statement_line_id) REFERENCES statement_lines(id),
                FOREIGN KEY (receipt_id) REFERENCES receipts(id)
            )
            """
        )
        con.execute("CREATE INDEX IF NOT EXISTS idx_lines_statement "
                    "ON statement_lines(statement_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_matches_line "
                    "ON statement_matches(statement_line_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_matches_receipt "
                    "ON statement_matches(receipt_id)")
        con.commit()


# --------------------------------------------------------------------------- #
# Value parsing
# --------------------------------------------------------------------------- #
_DATE_FORMATS = (
    "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%m-%d-%Y",
    "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y", "%d-%b-%Y", "%d-%b-%y",
    "%Y/%m/%d", "%m/%d/%y", "%d/%m/%y",
)


def parse_statement_date(value) -> str | None:
    """Parse a statement date into ISO `YYYY-MM-DD`, or None.

    Banks export in whatever their locale does. Ambiguous `03/04/2026` is read as
    **day/month** first (Philippine convention); an unparseable value returns None
    rather than today, so a missing date can never masquerade as a real one.
    """
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if not text:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def parse_statement_amount(value) -> float | None:
    """Parse a statement amount into a float, or None if unreadable.

    Handles currency symbols, thousands separators, trailing/leading signs, and
    accounting parentheses (`(1,234.56)` = -1234.56). Returns None rather than 0.0 for
    an unreadable value: a charge silently read as zero would reconcile against nothing
    and disappear from the report.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None

    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative, text = True, text[1:-1]
    if text.endswith("-"):            # trailing-minus convention
        negative, text = True, text[:-1]

    cleaned = re.sub(r"[^\d.\-]", "", text)
    if cleaned.count("-") > 1 or (("-" in cleaned) and not cleaned.startswith("-")):
        cleaned = "-" + cleaned.replace("-", "")
    if cleaned in ("", "-", ".", "-."):
        return None
    try:
        amount = float(cleaned)
    except ValueError:
        return None
    return -abs(amount) if negative else amount


# --------------------------------------------------------------------------- #
# Merchant normalization
# --------------------------------------------------------------------------- #
#: Payment-network and channel noise that carries no merchant identity.
_MERCHANT_NOISE = {
    "pos", "purchase", "payment", "debit", "credit", "card", "visa", "mastercard",
    "transaction", "txn", "ref", "reference", "auth", "authorization", "online",
    "web", "recurring", "the", "inc", "corp", "corporation", "co", "ltd", "llc",
    "philippines", "ph", "pty", "intl", "international", "store", "branch",
}

_CITY_NOISE = {
    "makati", "manila", "quezon", "qc", "taguig", "pasig", "bgc", "cebu", "davao",
    "mandaluyong", "paranaque", "pasay", "alabang", "ortigas", "cubao",
}


def normalize_merchant(text: str | None) -> str:
    """Reduce a raw statement description to comparable merchant tokens.

    `"POS PURCHASE SM SUPERMARKET MAKATI 0412 REF#88213"` -> `"sm supermarket"`.

    Statement descriptors carry the merchant name buried in channel prefixes, branch
    numbers, city names and reference ids. Comparing raw strings would match almost
    nothing; this is what makes merchant-name *variation* tolerable rather than fatal.
    """
    if not text:
        return ""
    lowered = str(text).lower()
    lowered = re.sub(r"[^a-z0-9\s]", " ", lowered)
    tokens = []
    for token in lowered.split():
        if token.isdigit():           # branch/reference/terminal numbers
            continue
        if re.fullmatch(r"[a-z]?\d+[a-z]?", token):
            continue
        if token in _MERCHANT_NOISE or token in _CITY_NOISE:
            continue
        if len(token) <= 1:
            continue
        tokens.append(token)
    return " ".join(tokens)


def merchant_similarity(a: str | None, b: str | None) -> float:
    """Token-set similarity in [0, 1] between two merchant strings.

    Uses containment (overlap / smaller set) rather than plain Jaccard: a statement
    descriptor is routinely a superset of a receipt's vendor name, and Jaccard would
    punish that extra context even when the receipt name appears verbatim.
    """
    tokens_a = set(normalize_merchant(a).split())
    tokens_b = set(normalize_merchant(b).split())
    if not tokens_a or not tokens_b:
        return 0.0
    overlap = len(tokens_a & tokens_b)
    if overlap:
        return overlap / min(len(tokens_a), len(tokens_b))
    # No exact token overlap — fall back to prefix agreement so "supermkt" still
    # resembles "supermarket". Deliberately capped low: this is a weak signal.
    for token_a in tokens_a:
        for token_b in tokens_b:
            shared = min(len(token_a), len(token_b))
            if shared >= 4 and token_a[:shared] == token_b[:shared]:
                return 0.5 / min(len(tokens_a), len(tokens_b))
    return 0.0


# --------------------------------------------------------------------------- #
# CSV ingestion
# --------------------------------------------------------------------------- #
_COLUMN_ALIASES = {
    "posted_date": ("posting date", "posted date", "post date", "date posted",
                    "posted", "date", "transaction date", "txn date"),
    "transaction_date": ("transaction date", "txn date", "purchase date",
                         "trans date", "value date"),
    "description": ("description", "details", "particulars", "narrative",
                    "merchant", "payee", "transaction details", "remarks"),
    "amount": ("amount", "transaction amount", "value"),
    "debit": ("debit", "withdrawal", "withdrawals", "money out", "charge", "debit amount"),
    "credit": ("credit", "deposit", "deposits", "money in", "payment", "credit amount"),
}


def _resolve_columns(fieldnames: list[str]) -> dict[str, str]:
    """Map our canonical field names onto this file's actual headers."""
    lowered = {(name or "").strip().lower(): name for name in fieldnames}
    resolved: dict[str, str] = {}
    for canonical, aliases in _COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in lowered:
                resolved[canonical] = lowered[alias]
                break
    return resolved


def parse_statement_csv(text: str, *, charges_are_negative: bool = True) -> list[dict]:
    """Parse a bank/card CSV export into normalized rows.

    Supports both layouts banks actually emit:
      * one signed `amount` column, and
      * separate `debit` / `credit` columns.

    `charges_are_negative` describes the *input* file's convention for a single signed
    amount column. Some card issuers export charges as positive numbers; setting this
    False flips them. The **output** is always normalized to negative-is-money-out, so
    nothing downstream has to care.

    Rows whose amount cannot be read are returned with `amount=None` and an `error`,
    never dropped — a silently skipped line is a charge that vanishes from the report.
    """
    if not (text or "").strip():
        raise ReconciliationError("Statement file is empty")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ReconciliationError("Statement file has no header row")

    columns = _resolve_columns(list(reader.fieldnames))
    if "description" not in columns:
        raise ReconciliationError(
            "Statement needs a description column (tried: "
            + ", ".join(_COLUMN_ALIASES["description"]) + ")"
        )
    if not ({"amount", "debit", "credit"} & set(columns)):
        raise ReconciliationError(
            "Statement needs an amount column, or debit/credit columns"
        )

    rows: list[dict] = []
    for index, record in enumerate(reader, start=1):
        description = (record.get(columns.get("description", ""), "") or "").strip()

        amount = None
        error = None
        if "amount" in columns:
            amount = parse_statement_amount(record.get(columns["amount"]))
            if amount is not None and not charges_are_negative:
                amount = -amount
        if amount is None and ("debit" in columns or "credit" in columns):
            debit = parse_statement_amount(record.get(columns.get("debit", "")))
            credit = parse_statement_amount(record.get(columns.get("credit", "")))
            if debit:
                amount = -abs(debit)
            elif credit:
                amount = abs(credit)
        if amount is None:
            error = "amount could not be read"

        posted = parse_statement_date(record.get(columns.get("posted_date", "")))
        transaction = parse_statement_date(record.get(columns.get("transaction_date", "")))
        # A file with only a transaction-date column still needs a posting date.
        posted = posted or transaction

        rows.append({
            "row_number": index,
            "posted_date": posted,
            "transaction_date": transaction,
            "description": description,
            "merchant": normalize_merchant(description),
            "amount": amount,
            "error": error,
            "raw": ",".join(f"{k}={v}" for k, v in record.items() if v)[:500],
        })

    if not rows:
        raise ReconciliationError("Statement file contains no data rows")
    return rows


def import_statement(text: str, source_file: str, *, account_id: int | None = None,
                     kind: str = "credit_card", currency: str = "PHP",
                     charges_are_negative: bool = True) -> dict:
    """Parse and persist a statement. Returns the statement header plus its rows."""
    init_reconciliation_schema()
    rows = parse_statement_csv(text, charges_are_negative=charges_are_negative)

    dates = sorted(r["posted_date"] for r in rows if r["posted_date"])
    with _connect() as con:
        cur = con.execute(
            "INSERT INTO statements (source_file, account_id, kind, currency, "
            "period_start, period_end, imported_at) VALUES (?,?,?,?,?,?,?)",
            (source_file, account_id, kind, currency,
             dates[0] if dates else None, dates[-1] if dates else None,
             datetime.now().isoformat(timespec="seconds")),
        )
        statement_id = cur.lastrowid
        for row in rows:
            con.execute(
                "INSERT INTO statement_lines (statement_id, posted_date, "
                "transaction_date, description, merchant, amount, row_number, raw) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (statement_id, row["posted_date"], row["transaction_date"],
                 row["description"], row["merchant"], row["amount"],
                 row["row_number"], row["raw"]),
            )
        con.commit()

    return {
        "statement_id": statement_id,
        "source_file": source_file,
        "rows": len(rows),
        "unreadable_rows": sum(1 for r in rows if r["error"]),
        "period_start": dates[0] if dates else None,
        "period_end": dates[-1] if dates else None,
    }


def list_statements() -> list[dict]:
    init_reconciliation_schema()
    with _connect() as con:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute(
            "SELECT s.*, (SELECT COUNT(*) FROM statement_lines l "
            "WHERE l.statement_id = s.id) AS line_count "
            "FROM statements s ORDER BY s.id DESC"
        )]


def get_statement(statement_id: int) -> dict | None:
    init_reconciliation_schema()
    with _connect() as con:
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT * FROM statements WHERE id = ?",
                          (statement_id,)).fetchone()
        return dict(row) if row else None


def statement_lines(statement_id: int) -> list[dict]:
    init_reconciliation_schema()
    with _connect() as con:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute(
            "SELECT * FROM statement_lines WHERE statement_id = ? "
            "ORDER BY row_number", (statement_id,)
        )]


def delete_statement(statement_id: int) -> bool:
    """Remove a statement, its lines, and any matches derived from them."""
    init_reconciliation_schema()
    with _connect() as con:
        con.execute(
            "DELETE FROM statement_matches WHERE statement_line_id IN "
            "(SELECT id FROM statement_lines WHERE statement_id = ?)", (statement_id,)
        )
        con.execute("DELETE FROM statement_lines WHERE statement_id = ?", (statement_id,))
        cur = con.execute("DELETE FROM statements WHERE id = ?", (statement_id,))
        con.commit()
        return cur.rowcount > 0


# --------------------------------------------------------------------------- #
# Matching
# --------------------------------------------------------------------------- #
def _date_delta_days(posted: str | None, receipt_date: str | None) -> int | None:
    if not posted or not receipt_date:
        return None
    try:
        return (date.fromisoformat(posted[:10]) - date.fromisoformat(receipt_date[:10])).days
    except ValueError:
        return None


def _candidate_receipts(receipt_ids: list[int] | None) -> list[dict]:
    with _connect() as con:
        con.row_factory = sqlite3.Row
        query = ("SELECT id, vendor_name, receipt_date, total_amount, currency "
                 "FROM receipts WHERE total_amount IS NOT NULL AND total_amount > 0")
        params: tuple = ()
        if receipt_ids:
            placeholders = ",".join("?" * len(receipt_ids))
            query += f" AND id IN ({placeholders})"
            params = tuple(receipt_ids)
        return [dict(r) for r in con.execute(query + " ORDER BY id", params)]


def _score(amount_delta: float, date_delta: int | None, similarity: float,
           max_lag: int) -> float:
    """Rank candidate pairings. Higher is better.

    Amount agreement dominates (it is the strongest evidence a charge and a receipt are
    the same purchase), then merchant, then date proximity as a tie-breaker.
    """
    amount_score = 1.0 / (1.0 + abs(amount_delta))
    if date_delta is None:
        date_score = 0.0
    else:
        date_score = max(0.0, 1.0 - abs(date_delta) / max(1, max_lag + 1))
    return 0.6 * amount_score + 0.25 * similarity + 0.15 * date_score


def match_statement(
    statement_id: int, *,
    receipt_ids: list[int] | None = None,
    max_posting_lag_days: int = DEFAULT_MAX_POSTING_LAG_DAYS,
    max_lead_days: int = DEFAULT_MAX_LEAD_DAYS,
    amount_tolerance: float = DEFAULT_AMOUNT_TOLERANCE,
    discrepancy_abs: float = DEFAULT_DISCREPANCY_ABS,
    discrepancy_pct: float = DEFAULT_DISCREPANCY_PCT,
    min_merchant_similarity: float = DEFAULT_MIN_MERCHANT_SIMILARITY,
    persist: bool = True,
) -> dict:
    """Match a statement's charges against saved receipts.

    Two passes:

    1. **Exact** — amounts agree within `amount_tolerance` and the posting date falls
       inside the settlement window. Ranked by score, assigned greedily one-to-one.
    2. **Discrepancy** — over what is left, pair rows that clearly refer to the same
       purchase (merchant agrees, date plausible) but whose amounts differ. Reported as
       an `amount_mismatch` rather than as two unrelated problems, because "you were
       charged ₱550 for a ₱500 receipt" is the actionable statement.

    Credits (positive amounts) are never matched to receipts — a refund is not a
    purchase. They are reported separately.

    Returns the full match set; also persists it unless `persist=False`.
    """
    init_reconciliation_schema()
    if get_statement(statement_id) is None:
        raise ReconciliationError(f"Statement {statement_id} not found")

    lines = statement_lines(statement_id)
    charges = [l for l in lines if l["amount"] is not None and l["amount"] < 0]
    receipts = _candidate_receipts(receipt_ids)

    pairs = []
    for line in charges:
        charge = abs(line["amount"])
        for receipt in receipts:
            total = float(receipt["total_amount"])
            delta = total - charge
            date_delta = _date_delta_days(line["posted_date"], receipt["receipt_date"])
            similarity = merchant_similarity(line["description"], receipt["vendor_name"])

            # A receipt cannot be settled long before it was issued, and a charge that
            # posts weeks later is a different purchase.
            in_window = date_delta is None or (
                -max_lead_days <= date_delta <= max_posting_lag_days
            )
            exact_amount = abs(delta) <= amount_tolerance
            near_amount = abs(delta) <= max(discrepancy_abs, total * discrepancy_pct)

            if exact_amount and in_window:
                status = "matched"
            elif exact_amount and not in_window:
                status = "date_outside_window"
            elif near_amount and in_window and similarity >= min_merchant_similarity:
                status = "amount_mismatch"
            else:
                continue

            pairs.append({
                "statement_line_id": line["id"],
                "receipt_id": receipt["id"],
                "status": status,
                "score": _score(delta, date_delta, similarity, max_posting_lag_days),
                "amount_delta": round(delta, 2),
                "date_delta_days": date_delta,
                "merchant_similarity": round(similarity, 3),
            })

    # Greedy one-to-one assignment. Exact matches outrank discrepancy pairings, then
    # score. One-to-one is what keeps duplicate billing visible: a single receipt must
    # not be able to explain two identical charges.
    rank = {"matched": 0, "amount_mismatch": 1, "date_outside_window": 2}
    pairs.sort(key=lambda p: (rank[p["status"]], -p["score"]))

    used_lines: set[int] = set()
    used_receipts: set[int] = set()
    assigned: list[dict] = []
    for pair in pairs:
        if pair["statement_line_id"] in used_lines or pair["receipt_id"] in used_receipts:
            continue
        used_lines.add(pair["statement_line_id"])
        used_receipts.add(pair["receipt_id"])
        assigned.append(pair)

    if persist:
        with _connect() as con:
            con.execute(
                "DELETE FROM statement_matches WHERE statement_line_id IN "
                "(SELECT id FROM statement_lines WHERE statement_id = ?)", (statement_id,)
            )
            now = datetime.now().isoformat(timespec="seconds")
            for pair in assigned:
                con.execute(
                    "INSERT INTO statement_matches (statement_line_id, receipt_id, "
                    "status, score, amount_delta, date_delta_days, merchant_similarity, "
                    "matched_at) VALUES (?,?,?,?,?,?,?,?)",
                    (pair["statement_line_id"], pair["receipt_id"], pair["status"],
                     pair["score"], pair["amount_delta"], pair["date_delta_days"],
                     pair["merchant_similarity"], now),
                )
            con.commit()

    return {
        "statement_id": statement_id,
        "charges": len(charges),
        "receipts_considered": len(receipts),
        "matches": assigned,
        "matched_line_ids": sorted(used_lines),
        "matched_receipt_ids": sorted(used_receipts),
    }


# --------------------------------------------------------------------------- #
# Duplicate detection
# --------------------------------------------------------------------------- #
def find_duplicate_charges(statement_id: int) -> list[dict]:
    """Statement lines that look like the same charge billed more than once.

    Same merchant, same amount, same posting date. Legitimate repeats exist (two
    identical coffees on one day), so these are **candidates for review**, never
    automatic corrections.
    """
    groups: dict[tuple, list[dict]] = {}
    for line in statement_lines(statement_id):
        if line["amount"] is None or line["amount"] >= 0:
            continue
        key = (line["merchant"], round(line["amount"], 2), line["posted_date"])
        groups.setdefault(key, []).append(line)

    return [
        {
            "merchant": merchant,
            "amount": amount,
            "posted_date": posted,
            "count": len(rows),
            "statement_line_ids": [r["id"] for r in rows],
            "descriptions": sorted({r["description"] for r in rows}),
        }
        for (merchant, amount, posted), rows in groups.items() if len(rows) > 1
    ]


def find_duplicate_receipts(receipt_ids: list[int] | None = None) -> list[dict]:
    """Receipts that look like the same purchase captured twice — e.g. the same paper
    receipt photographed and uploaded on two occasions."""
    groups: dict[tuple, list[dict]] = {}
    for receipt in _candidate_receipts(receipt_ids):
        key = (normalize_merchant(receipt["vendor_name"]),
               round(float(receipt["total_amount"]), 2),
               receipt["receipt_date"])
        groups.setdefault(key, []).append(receipt)

    return [
        {
            "merchant": merchant,
            "total_amount": amount,
            "receipt_date": receipt_date,
            "count": len(rows),
            "receipt_ids": [r["id"] for r in rows],
        }
        for (merchant, amount, receipt_date), rows in groups.items() if len(rows) > 1
    ]


# --------------------------------------------------------------------------- #
# The discrepancy report
# --------------------------------------------------------------------------- #
def discrepancy_report(statement_id: int, *, receipt_ids: list[int] | None = None,
                       **match_kwargs) -> dict:
    """The user-facing answer: what does the bank say that the receipts do not?

    Every category is reported with its count and its members, and the totals are
    reconciled explicitly — `charges = matched + amount_mismatch + date_outside_window
    + missing_receipt` — so a category cannot silently swallow rows.
    """
    statement = get_statement(statement_id)
    if statement is None:
        raise ReconciliationError(f"Statement {statement_id} not found")

    lines = statement_lines(statement_id)
    outcome = match_statement(statement_id, receipt_ids=receipt_ids, **match_kwargs)

    lines_by_id = {l["id"]: l for l in lines}
    receipts = {r["id"]: r for r in _candidate_receipts(receipt_ids)}

    buckets: dict[str, list[dict]] = {
        "matched": [], "amount_mismatch": [], "date_outside_window": [],
    }
    for match in outcome["matches"]:
        line = lines_by_id[match["statement_line_id"]]
        receipt = receipts[match["receipt_id"]]
        buckets[match["status"]].append({
            **match,
            "posted_date": line["posted_date"],
            "description": line["description"],
            "charge_amount": abs(line["amount"]),
            "receipt_vendor": receipt["vendor_name"],
            "receipt_date": receipt["receipt_date"],
            "receipt_total": receipt["total_amount"],
        })

    matched_lines = set(outcome["matched_line_ids"])
    matched_receipts = set(outcome["matched_receipt_ids"])

    charges = [l for l in lines if l["amount"] is not None and l["amount"] < 0]
    missing_receipt = [
        {"statement_line_id": l["id"], "posted_date": l["posted_date"],
         "description": l["description"], "amount": abs(l["amount"])}
        for l in charges if l["id"] not in matched_lines
    ]
    unmatched_receipts = [
        {"receipt_id": r["id"], "vendor_name": r["vendor_name"],
         "receipt_date": r["receipt_date"], "total_amount": r["total_amount"]}
        for r in receipts.values() if r["id"] not in matched_receipts
    ]
    refunds = [
        {"statement_line_id": l["id"], "posted_date": l["posted_date"],
         "description": l["description"], "amount": l["amount"]}
        for l in lines if l["amount"] is not None and l["amount"] > 0
    ]
    unreadable = [
        {"statement_line_id": l["id"], "row_number": l["row_number"],
         "description": l["description"], "raw": l["raw"]}
        for l in lines if l["amount"] is None
    ]

    charge_total = round(sum(abs(l["amount"]) for l in charges), 2)
    matched_total = round(sum(m["charge_amount"] for m in buckets["matched"]), 2)
    discrepancy_total = round(
        sum(abs(m["amount_delta"]) for m in buckets["amount_mismatch"]), 2
    )

    report = {
        "statement_id": statement_id,
        "source_file": statement["source_file"],
        "period_start": statement["period_start"],
        "period_end": statement["period_end"],
        "currency": statement["currency"],
        "totals": {
            "statement_lines": len(lines),
            "charges": len(charges),
            "charge_total": charge_total,
            "matched_total": matched_total,
            "unexplained_total": round(
                sum(m["amount"] for m in missing_receipt), 2
            ),
            "amount_discrepancy_total": discrepancy_total,
        },
        "matched": buckets["matched"],
        "amount_mismatch": buckets["amount_mismatch"],
        "date_outside_window": buckets["date_outside_window"],
        "missing_receipt": missing_receipt,
        "unmatched_receipts": unmatched_receipts,
        "refunds": refunds,
        "unreadable_lines": unreadable,
        "duplicate_charges": find_duplicate_charges(statement_id),
        "duplicate_receipts": find_duplicate_receipts(receipt_ids),
        "receipts_considered": outcome["receipts_considered"],
    }
    report["counts"] = {key: len(report[key]) for key in (
        "matched", "amount_mismatch", "date_outside_window", "missing_receipt",
        "unmatched_receipts", "refunds", "unreadable_lines", "duplicate_charges",
        "duplicate_receipts",
    )}
    # Every charge lands in exactly one bucket. Asserted in the report itself so a
    # future change cannot quietly drop rows from the user's view.
    report["accounted_for"] = (
        report["counts"]["matched"] + report["counts"]["amount_mismatch"]
        + report["counts"]["date_outside_window"] + report["counts"]["missing_receipt"]
        == len(charges)
    )
    report["needs_review"] = bool(
        report["counts"]["missing_receipt"] or report["counts"]["amount_mismatch"]
        or report["counts"]["duplicate_charges"] or report["counts"]["unreadable_lines"]
        or report["counts"]["date_outside_window"]
    )
    return report


def format_discrepancy_report(report: dict) -> str:
    """Render a report as plain text for a human reviewer or a CLI."""
    lines = [
        f"Statement #{report['statement_id']} — {report['source_file'] or 'unnamed'}",
        f"Period: {report['period_start'] or '?'} to {report['period_end'] or '?'}"
        f"  ({report['currency'] or ''})",
        "",
        f"{report['totals']['charges']} charges totalling "
        f"{report['totals']['charge_total']:,.2f}",
        f"  matched to receipts        {report['counts']['matched']:>4}"
        f"   ({report['totals']['matched_total']:,.2f})",
        f"  amount discrepancies       {report['counts']['amount_mismatch']:>4}"
        f"   ({report['totals']['amount_discrepancy_total']:,.2f} total difference)",
        f"  posted outside the window  {report['counts']['date_outside_window']:>4}",
        f"  no receipt found           {report['counts']['missing_receipt']:>4}"
        f"   ({report['totals']['unexplained_total']:,.2f} unexplained)",
        "",
        f"  receipts with no charge    {report['counts']['unmatched_receipts']:>4}",
        f"  refunds / credits          {report['counts']['refunds']:>4}",
        f"  possible duplicate charges {report['counts']['duplicate_charges']:>4}",
        f"  possible duplicate receipts{report['counts']['duplicate_receipts']:>4}",
        f"  unreadable statement rows  {report['counts']['unreadable_lines']:>4}",
    ]

    if report["amount_mismatch"]:
        lines += ["", "Amount discrepancies:"]
        for item in report["amount_mismatch"]:
            lines.append(
                f"  {item['posted_date']}  {item['description'][:40]:<40} "
                f"charged {item['charge_amount']:,.2f} vs receipt "
                f"{item['receipt_total']:,.2f} "
                f"(difference {item['amount_delta']:+,.2f})"
            )

    if report["missing_receipt"]:
        lines += ["", "Charges with no receipt:"]
        for item in report["missing_receipt"]:
            lines.append(
                f"  {item['posted_date']}  {item['description'][:40]:<40} "
                f"{item['amount']:,.2f}"
            )

    lines += ["", "This report is produced by deterministic matching. Duplicates and "
                  "discrepancies are candidates for human review, not corrections."]
    return "\n".join(lines)
