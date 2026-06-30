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
    currency: Optional[str] = "PHP"


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
        return receipt_id


def list_receipts(limit: int = 100) -> list[dict]:
    init_db()
    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT * FROM receipts ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
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
  - vendor_name: name of the store/vendor (e.g. "SM Supermarket", "Jollibee")
  - vendor_tin: Tax Identification Number of the vendor (Philippine format)
  - vendor_address: address of the vendor/store location
  - receipt_number: OR/SI number printed on the receipt
  - receipt_date: date of transaction (YYYY-MM-DD format when possible)
  - subtotal: amount before VAT and discounts
  - vatable_sales: amount subject to 12% VAT (Philippine tax system)
  - vat_exempt_sales: amount exempt from VAT (Philippine tax system)
  - zero_rated_sales: amount with zero VAT rate (Philippine tax system)
  - vat_amount: 12% VAT amount (Philippine standard rate)
  - discount: total discount amount (e.g. Senior Citizen, PWD)
  - discount_type: type of discount applied (e.g. "Senior Citizen", "PWD")
  - total_amount: final amount due/total paid
  - cash: amount of cash tendered by customer
  - change: change given back to customer
  - currency: always "PHP" for Philippine Peso
  - flagged: 1 if receipt needs manual review, 0 otherwise

Table line_items(id, receipt_id, description, quantity, unit_price, amount)
  - id: unique identifier for each line item
  - receipt_id: foreign key to receipts.id
  - description: product/service name
  - quantity: number of units (may be NULL)
  - unit_price: price per unit (may be NULL)
  - amount: total amount for this line item
"""

_SQL_AGENT_PROMPT = """You are a SQL expert for a Philippine receipts ledger database.
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

_ANSWER_PROMPT = """You are summarizing SQL query results from a Philippine receipts ledger for a user.
Today's date is {today}.

Question: {question}
SQL used: {sql}
Result rows (JSON): {rows}

Rules for your answer:
- Write a short, direct, natural-language answer (1-3 sentences).
- Use only the data in the result rows - do not invent numbers.
- For monetary values, format as "₱X,XXX.XX" (Philippine Peso with comma separators and 2 decimal places).
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


def ask_ledger(question: str, model: str = "llama3.2:3b") -> dict:
    """Plan -> generate SQL -> execute (retrying once on error) -> summarize."""
    with mlflow.start_run(run_name=f"sql_agent_{int(time.time())}"):
        mlflow.log_param("question", question[:250])
        mlflow.log_param("model", model)
        t0 = time.time()
        
        try:
            if ollama is None:
                raise RuntimeError("The `ollama` package is not installed.")

            today = date.today().isoformat()
            prompt = _SQL_AGENT_PROMPT.format(
                schema=SCHEMA_DESCRIPTION,
                question=question,
                today=today
            )
            
            # Generate SQL
            gen = ollama.chat(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                options={"temperature": 0},
            )
            sql = _extract_sql(gen["message"]["content"])
            mlflow.log_param("initial_sql", sql[:500])

            init_db()
            rows: list[dict] = []
            retried = False
            error_message = None
            
            try:
                _validate_sql(sql)
                with sqlite3.connect(DB_PATH) as con:
                    con.row_factory = sqlite3.Row
                    rows = [dict(r) for r in con.execute(sql).fetchall()]
            except (GuardrailError, sqlite3.Error) as first_err:
                error_message = str(first_err)
                mlflow.log_param("first_error", error_message[:250])
                
                # Retry with error feedback
                retried = True
                retry_prompt = _SQL_RETRY_PROMPT.format(
                    schema=SCHEMA_DESCRIPTION,
                    sql=sql,
                    error=error_message,
                    question=question
                )
                gen2 = ollama.chat(
                    model=model,
                    messages=[{"role": "user", "content": retry_prompt}],
                    options={"temperature": 0},
                )
                sql = _extract_sql(gen2["message"]["content"])
                mlflow.log_param("retry_sql", sql[:500])
                
                _validate_sql(sql)
                with sqlite3.connect(DB_PATH) as con:
                    con.row_factory = sqlite3.Row
                    rows = [dict(r) for r in con.execute(sql).fetchall()]

            # Generate natural language answer
            answer = _generate_answer(question, sql, rows, model)

            mlflow.log_param("final_sql", sql[:500])
            mlflow.log_metric("retried", int(retried))
            mlflow.log_metric("rows_returned", len(rows))
            mlflow.log_metric("latency_seconds", time.time() - t0)
            mlflow.log_metric("error", 0)
            
            return {
                "question": question,
                "sql": sql,
                "rows": rows,
                "answer": answer
            }
            
        except Exception as exc:
            mlflow.log_metric("error", 1)
            mlflow.log_param("error_message", str(exc)[:250])
            mlflow.log_metric("latency_seconds", time.time() - t0)
            raise