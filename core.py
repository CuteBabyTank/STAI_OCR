"""
core.py — shared logic for STAI_OCR, used by both the Streamlit UI
(receipt_processor.py) and the REST API (api.py).

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

import json
import re
import sqlite3
import time
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import mlflow
from pydantic import BaseModel, Field, ValidationError

try:
    import ollama
except ImportError:  # pragma: no cover
    ollama = None

try:
    import numpy as np
except ImportError:  # pragma: no cover - numpy ships with pandas, but stay safe
    np = None

# Re-use the original prompt/cleanup pipeline so behavior doesn't change.
from receipt_processor import (
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
# Config
# --------------------------------------------------------------------------- #
DB_PATH = Path(__file__).parent / "ledger.db"
MAX_IMAGE_BYTES = 8 * 1024 * 1024  # 8 MB
ALLOWED_CONTENT_TYPES = {"image/png", "image/jpeg", "image/webp", "image/bmp"}

# Text-only model used by the SQL agent, the RAG answerer, and the ReAct planner.
AGENT_MODEL = "llama3.2:3b"
# Embedding model used by the RAG retriever. Small (~275 MB), fast, local.
EMBED_MODEL = "nomic-embed-text"

mlflow.set_experiment("stai_ocr_receipts")


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


# --------------------------------------------------------------------------- #
# 2. Guardrails — input + output validation
# --------------------------------------------------------------------------- #
class GuardrailError(ValueError):
    """Raised when an input or output fails a safety/validity check."""


def validate_input(image_bytes: bytes, content_type: str | None) -> None:
    if not image_bytes:
        raise GuardrailError("Empty file.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise GuardrailError(f"Image exceeds the {MAX_IMAGE_BYTES // (1024 * 1024)}MB limit.")
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
def extract_receipt_validated(
    image_bytes: bytes, model: str = DEFAULT_MODEL, content_type: str | None = None
) -> tuple[ReceiptData, list[str]]:
    """Full guarded pipeline: validate input -> call the vision model -> clean
    up -> validate output schema -> check for disambiguation needs. Every call
    is traced to MLflow (latency, success/failure, output size)."""
    with mlflow.start_run(run_name=f"extract_{int(time.time())}"):
        mlflow.log_param("model", model)
        mlflow.log_param("image_bytes", len(image_bytes))
        t0 = time.time()
        try:
            validate_input(image_bytes, content_type)

            if ollama is None:
                raise RuntimeError("The `ollama` package is not installed.")

            response = ollama.chat(
                model=model,
                messages=[{"role": "user", "content": EXTRACTION_PROMPT, "images": [image_bytes]}],
                format="json",
                options={"temperature": 0, "num_predict": 1024},
            )
            content = response["message"]["content"]
            raw = _coerce_json(content)
            raw = _fix_payment_fields(_dedupe_items(_remap_summary_lines(_clean_items(raw))))
            raw = _coerce_numeric_fields(raw)
            data = validate_output(raw)
            reasons = needs_disambiguation(data)

            latency = time.time() - t0
            mlflow.log_metric("latency_seconds", latency)
            # token usage isn't always returned by every Ollama build; log if present
            mlflow.log_metric("prompt_eval_count", response.get("prompt_eval_count", 0))
            mlflow.log_metric("eval_count", response.get("eval_count", 0))
            mlflow.log_metric("items_extracted", len(data.items))
            mlflow.log_metric("needs_disambiguation", int(bool(reasons)))
            mlflow.log_metric("error", 0)
            return data, reasons
        except Exception as exc:
            mlflow.log_metric("error", 1)
            mlflow.log_param("error_message", str(exc)[:250])
            mlflow.log_metric("latency_seconds", time.time() - t0)
            raise


# --------------------------------------------------------------------------- #
# 5. Memory — persistent SQLite ledger
# --------------------------------------------------------------------------- #
def init_db() -> None:
    with sqlite3.connect(DB_PATH) as con:
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
        ]
        
        for col_name, col_type in columns_to_add:
            if col_name not in existing_columns:
                try:
                    con.execute(f"ALTER TABLE receipts ADD COLUMN {col_name} {col_type}")
                except sqlite3.OperationalError:
                    pass  # Column already exists or other error; ignore
        
        con.commit()


def save_receipt(data: ReceiptData, source_file: str, flagged: bool) -> int:
    init_db()
    with sqlite3.connect(DB_PATH) as con:
        cur = con.execute(
            """
            INSERT INTO receipts (source_file, processed_at, vendor_name, vendor_tin,
                vendor_address, receipt_number, receipt_date, subtotal, vatable_sales,
                vat_exempt_sales, zero_rated_sales, vat_amount, discount, discount_type,
                total_amount, cash, change, currency, flagged)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                int(flagged),
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
    try:
        index_receipt(receipt_id, data, source_file)
    except Exception:  # noqa: BLE001
        pass
    return receipt_id


def list_receipts(limit: int = 100) -> list[dict]:
    init_db()
    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT * FROM receipts ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


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
  total_amount, cash, change, currency, flagged)
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

Question: How much VAT did I pay this month?
SQL: SELECT ROUND(SUM(vat_amount), 2) AS total_vat FROM receipts WHERE vat_amount IS NOT NULL AND receipt_date >= date('now', 'start of month')

Question: What are my top 5 vendors by total spend?
SQL: SELECT vendor_name, ROUND(SUM(total_amount), 2) AS total_spend FROM receipts WHERE vendor_name IS NOT NULL AND total_amount IS NOT NULL GROUP BY vendor_name ORDER BY total_spend DESC LIMIT 5

Question: How many items did I buy from Jollibee?
SQL: SELECT COUNT(*) AS item_count FROM line_items li JOIN receipts r ON li.receipt_id = r.id WHERE r.vendor_name LIKE '%Jollibee%'

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

_ANSWER_PROMPT = """You are summarizing SQL query results from a personal receipts ledger for a user.
Today's date is {today}.

Question: {question}
SQL used: {sql}
Result rows (JSON): {rows}

Rules for your answer:
- Write a short, direct, natural-language answer (1-3 sentences).
- Use only the data in the result rows - do not invent numbers.
- For monetary values, use comma separators and 2 decimal places (e.g. "12,345.67"),
  prefixed with the currency symbol if one appears in the rows, otherwise no symbol.
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


def _generate_answer(question: str, sql: str, rows: list[dict], model: str) -> str:
    """Turn raw SQL rows into a natural-language answer."""
    if not rows:
        return "No matching records were found in the ledger for that question."
    
    try:
        if ollama is None:
            raise RuntimeError("ollama not installed")
        
        today = date.today().isoformat()
        resp = ollama.chat(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": _ANSWER_PROMPT.format(
                        question=question,
                        sql=sql,
                        rows=json.dumps(rows, default=str)[:4000],
                        today=today
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
        con = sqlite3.connect(f"file:{Path(DB_PATH).as_posix()}?mode=ro", uri=True)
    except sqlite3.OperationalError:
        con = sqlite3.connect(DB_PATH)
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

    gen = ollama.chat(
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
            gen2 = ollama.chat(
                model=model,
                messages=[{"role": "user", "content": retry_prompt}],
                options={"temperature": 0},
            )
            sql = _extract_sql(gen2["message"]["content"])
            _validate_sql(sql)
            rows = [dict(r) for r in con.execute(sql).fetchall()]
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
    """MLflow-traced wrapper around the SQL agent."""
    with mlflow.start_run(run_name=f"sql_agent_{int(time.time())}"):
        mlflow.log_param("question", question[:250])
        mlflow.log_param("model", model)
        t0 = time.time()
        try:
            result = _sql_agent_core(question, model, receipt_ids)
            mlflow.log_param("final_sql", result["sql"][:500])
            if result.get("first_error"):
                mlflow.log_param("first_error", result["first_error"][:250])
            mlflow.log_metric("retried", int(result["retried"]))
            mlflow.log_metric("rows_returned", len(result["rows"]))
            mlflow.log_metric("latency_seconds", time.time() - t0)
            mlflow.log_metric("error", 0)
            return {k: result[k] for k in ("question", "sql", "rows", "answer")}
        except Exception as exc:
            mlflow.log_metric("error", 1)
            mlflow.log_param("error_message", str(exc)[:250])
            mlflow.log_metric("latency_seconds", time.time() - t0)
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


def init_rag_db() -> None:
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS receipt_docs (
                receipt_id INTEGER PRIMARY KEY,
                doc TEXT,
                embedding BLOB,
                FOREIGN KEY (receipt_id) REFERENCES receipts(id)
            )
            """
        )
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
    blob = _emb_to_blob(_embed(doc))
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            "INSERT OR REPLACE INTO receipt_docs (receipt_id, doc, embedding) VALUES (?,?,?)",
            (receipt_id, doc, blob),
        )
        con.commit()


def ensure_index() -> None:
    """Backfill documents/embeddings for receipts saved before RAG existed (or
    whose embedding failed because the model wasn't pulled yet). Idempotent."""
    init_db()
    init_rag_db()
    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        pending = con.execute(
            """
            SELECT r.* FROM receipts r
            LEFT JOIN receipt_docs d ON d.receipt_id = r.id
            WHERE d.receipt_id IS NULL
            """
        ).fetchall()
        # Also retry rows whose embedding is still NULL, but only if the model
        # is now reachable — otherwise we'd re-probe on every single search.
        if _embeddings_available():
            pending = list(pending) + con.execute(
                """
                SELECT r.* FROM receipts r
                JOIN receipt_docs d ON d.receipt_id = r.id
                WHERE d.embedding IS NULL
                """
            ).fetchall()

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
            doc = _compose_doc(header, items)
            blob = _emb_to_blob(_embed(doc))
            con.execute(
                "INSERT OR REPLACE INTO receipt_docs (receipt_id, doc, embedding) VALUES (?,?,?)",
                (row["id"], doc, blob),
            )
        con.commit()


def _cosine(a, b) -> float:
    if np is None:
        return 0.0
    denom = (np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denom) if denom else 0.0


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

    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """
            SELECT d.receipt_id, d.doc, d.embedding,
                   r.vendor_name, r.receipt_date, r.total_amount, r.currency, r.source_file
            FROM receipt_docs d JOIN receipts r ON r.id = d.receipt_id
            """
        ).fetchall()

    # Hard filter: out-of-scope receipts are removed before any scoring, so a
    # single-receipt query can only ever surface that receipt.
    candidates = [dict(r) for r in rows if scope is None or r["receipt_id"] in scope]
    if not candidates:
        return []

    qvec = _embed(query)
    scored: list[tuple[float, dict]] = []
    if qvec is not None and np is not None:
        q = np.asarray(qvec, dtype=np.float32)
        for c in candidates:
            if c["embedding"] is None:
                continue
            vec = np.frombuffer(c["embedding"], dtype=np.float32)
            scored.append((_cosine(q, vec), c))

    if not scored:
        # keyword fallback: overlap of query terms with the document text
        terms = [t for t in re.split(r"\W+", query.lower()) if len(t) > 2]
        for c in candidates:
            doc_l = (c["doc"] or "").lower()
            score = sum(doc_l.count(t) for t in terms)
            scored.append((float(score), c))

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
            resp = ollama.chat(
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
    """MLflow-traced RAG question-answering over the receipts."""
    with mlflow.start_run(run_name=f"rag_{int(time.time())}"):
        mlflow.log_param("query", query[:250])
        mlflow.log_param("model", model)
        t0 = time.time()
        try:
            result = _rag_core(query, model, k=k, receipt_ids=receipt_ids)
            mlflow.log_metric("sources_retrieved", len(result["sources"]))
            mlflow.log_metric("used_embeddings", int(_embeddings_available()))
            mlflow.log_metric("latency_seconds", time.time() - t0)
            mlflow.log_metric("error", 0)
            return result
        except Exception as exc:
            mlflow.log_metric("error", 1)
            mlflow.log_param("error_message", str(exc)[:250])
            mlflow.log_metric("latency_seconds", time.time() - t0)
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

Rules:
- Most questions need only ONE tool call. Take at most {max_steps} actions.
- Call each tool AT MOST ONCE. Never repeat the same Action with the same input.
- As soon as an Observation answers the question, immediately reply with
  "Final Answer:" — do not think further or call another tool.
- Choose sql_ledger for math/counts; choose search_receipts for item/content lookups.
- Base the Final Answer ONLY on the Observations you received.
{scope}
Example:
Question: How much did I spend in total?
Thought: This is an aggregate over all receipts, so I should query the ledger.
Action: sql_ledger
Action Input: What is my total spend across all receipts?
Observation: Your total spend is 4,210.00.
Thought: I have the total.
Final Answer: You've spent a total of 4,210.00 across your receipts.

Begin.
Question: {question}
"""

_ACTION_RE = re.compile(r"Action:\s*([a-zA-Z_]+)", re.IGNORECASE)
_ACTION_INPUT_RE = re.compile(r"Action Input:\s*(.+)", re.IGNORECASE)
_FINAL_RE = re.compile(r"Final Answer:\s*(.+)", re.IGNORECASE | re.DOTALL)


def _parse_final(text: str) -> str | None:
    m = _FINAL_RE.search(text)
    return m.group(1).strip() if m else None


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
        res = _sql_agent_core(tool_input, model, receipt_ids)
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
            resp = ollama.chat(
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


def agent_stream(question: str, model: str = AGENT_MODEL,
                 receipt_ids: list[int] | None = None):
    """Run the ReAct loop, yielding events as they happen so a UI can render the
    agent's reasoning live. Event `type`s:
        start                       — loop started
        token   {text}              — a chunk of the model's current reasoning
        action  {tool, input}       — the agent decided to call a tool
        observation {tool, text, data} — the tool's result
        final   {answer, steps}     — the final answer (last event on success)
        error   {message}           — something failed
    """
    mlflow.start_run(run_name=f"agent_{int(time.time())}")
    t0 = time.time()
    tools_used: list[str] = []
    steps: list[dict] = []
    try:
        mlflow.log_param("question", question[:250])
        mlflow.log_param("model", model)
        if ollama is None:
            raise RuntimeError("The `ollama` package is not installed.")

        yield {"type": "start"}
        scope = ""
        if receipt_ids:
            scope = ("- The user is asking about a specific receipt/batch only; "
                     "the tools are already scoped to it.\n")
        transcript = _REACT_PROMPT.format(
            today=date.today().isoformat(),
            question=question,
            max_steps=_MAX_AGENT_STEPS,
            scope=scope,
        )

        final_answer: str | None = None
        seen: dict[tuple[str, str], str] = {}  # (tool, input) -> observation, to dedup
        repeats = 0
        for _ in range(_MAX_AGENT_STEPS):
            text = ""
            for chunk in ollama.chat(
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

            tool, tool_input = _parse_action(text)
            if not tool:
                # No action and no final answer — treat the whole reply as the answer.
                final_answer = text or "I'm not sure how to answer that."
                steps.append({"thought": text})
                break

            key = (tool, tool_input.strip().lower())
            if key in seen:
                # The model is looping on a tool it already ran. Don't pay to run it
                # again — reuse the cached result and steer it hard toward answering.
                repeats += 1
                if repeats >= 2:
                    final_answer = _force_final(question, steps, model)
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

        if final_answer is None:
            final_answer = _force_final(question, steps, model)

        mlflow.log_metric("num_steps", len(steps))
        mlflow.log_param("tools_used", ",".join(tools_used) or "none")
        mlflow.log_metric("latency_seconds", time.time() - t0)
        mlflow.log_metric("error", 0)
        yield {"type": "final", "answer": final_answer, "steps": steps}
    except Exception as exc:  # noqa: BLE001
        mlflow.log_metric("error", 1)
        mlflow.log_param("error_message", str(exc)[:250])
        mlflow.log_metric("latency_seconds", time.time() - t0)
        yield {"type": "error", "message": str(exc)}
    finally:
        mlflow.end_run()


def agent_run(question: str, model: str = AGENT_MODEL,
              receipt_ids: list[int] | None = None) -> dict:
    """Non-streaming convenience wrapper: consume the stream, return the result
    plus the full reasoning trace (for the REST API)."""
    final = ""
    steps: list[dict] = []
    for ev in agent_stream(question, model, receipt_ids):
        if ev["type"] == "final":
            final, steps = ev["answer"], ev["steps"]
        elif ev["type"] == "error":
            raise RuntimeError(ev["message"])
    return {"question": question, "answer": final, "steps": steps}