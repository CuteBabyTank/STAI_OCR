"""
finance.py — budget-tracker data model layered on the receipt ledger.

The original app is a receipt-OCR ledger (see core.py). This module adds the
personal-budget-tracker abstractions the PRD calls for — Accounts, a unified
Transactions ledger (expense / income / transfer), Categories, and Tags — and
the balance / net-worth engine that ties them together.

It reuses core's SQLite connection (`_connect`, `DB_PATH`) so everything lives
in the same `ledger.db`. core.py never imports this module, so there is no
import cycle; api.py imports from both.

Design notes
------------
* One `transactions` table holds all three kinds. `account_id` is the money's
  source (debited for expense/transfer, credited for income); `to_account_id`
  is the transfer target. Receipts created by OCR link back via `receipt_id`.
* `income` and `transfer` are restricted to *debit* accounts at write time
  (PRD §22); `expense` may draw from any account type, including credit.
* Balances are derived, never stored: opening_balance ± the ledger. A stored
  balance would drift out of sync with edits/deletes.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from core import _connect, init_finance_tables  # reuse the same ledger.db + income/budgets

# --------------------------------------------------------------------------- #
# Domain constants
# --------------------------------------------------------------------------- #
ACCOUNT_TYPES = ("debit", "credit", "loans", "assets", "stocks", "crypto")
# Assets count positively toward net worth; liabilities are money you owe.
ASSET_TYPES = ("debit", "assets", "stocks", "crypto")
LIABILITY_TYPES = ("credit", "loans")
# Income and transfers may only touch spendable cash accounts.
DEBIT_TYPES = ("debit",)

TXN_KINDS = ("expense", "income", "transfer")

# Seeded on first run; is_system rows cannot be deleted (PRD §8).
DEFAULT_CATEGORIES = [
    # (name, kind, color)
    ("Food", "expense", "#F97316"),
    ("Bills", "expense", "#0EA5E9"),
    ("Groceries", "expense", "#22C55E"),
    ("Shopping", "expense", "#A855F7"),
    ("Transport", "expense", "#EAB308"),
    ("Health", "expense", "#EF4444"),
    ("Entertainment", "expense", "#EC4899"),
    ("Other", "expense", "#6B7280"),
    ("Salary", "income", "#16A34A"),
    ("Business", "income", "#059669"),
    ("Gift", "income", "#14B8A6"),
    ("Other income", "income", "#64748B"),
]


class FinanceError(ValueError):
    """Raised for referential-integrity / validation failures. api.py maps this
    to a 422 so the client can show the message inline."""


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #
def init_finance_schema() -> None:
    """Create the budget-tracker tables if absent and seed default categories.
    Idempotent; safe to call on every request (mirrors core.init_db)."""
    init_finance_tables()  # ensure income/budgets exist too (shared layer)
    with _connect() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                opening_balance REAL DEFAULT 0,
                currency TEXT,
                include_in_totals INTEGER DEFAULT 1,
                archived INTEGER DEFAULT 0,
                created_at TEXT
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                kind TEXT NOT NULL,
                color TEXT,
                parent_id INTEGER,
                is_system INTEGER DEFAULT 0,
                FOREIGN KEY (parent_id) REFERENCES categories(id)
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS tags (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                kind TEXT DEFAULT 'Custom',
                color TEXT
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                amount REAL NOT NULL,
                account_id INTEGER,
                to_account_id INTEGER,
                category_id INTEGER,
                note TEXT,
                occurred_at TEXT,
                fee REAL DEFAULT 0,
                receipt_id INTEGER,
                template_id INTEGER,
                created_at TEXT,
                FOREIGN KEY (account_id) REFERENCES accounts(id),
                FOREIGN KEY (to_account_id) REFERENCES accounts(id),
                FOREIGN KEY (category_id) REFERENCES categories(id),
                FOREIGN KEY (receipt_id) REFERENCES receipts(id)
            )
            """
        )
        con.execute("CREATE INDEX IF NOT EXISTS idx_txn_account ON transactions(account_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_txn_to_account ON transactions(to_account_id)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_txn_occurred ON transactions(occurred_at)")

        # --- Plan definition tables (Phase 2-3) --------------------------- #
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS budget_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id INTEGER,
                type TEXT DEFAULT 'fixed',        -- fixed | percent
                interval TEXT DEFAULT 'monthly',  -- daily | weekly | monthly | yearly
                limit_amount REAL DEFAULT 0,
                percent REAL DEFAULT 0,
                carry_forward INTEGER DEFAULT 0,
                created_at TEXT
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                amount REAL DEFAULT 0,
                kind TEXT DEFAULT 'expense',      -- expense | income
                account_id INTEGER,
                category_id INTEGER,
                created_at TEXT
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS recurring (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT DEFAULT 'expense',      -- expense | income
                amount REAL DEFAULT 0,
                name TEXT,
                account_id INTEGER,
                category_id INTEGER,
                next_due TEXT,
                created_at TEXT
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS installment_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                total REAL DEFAULT 0,
                monthly REAL DEFAULT 0,
                months INTEGER DEFAULT 0,
                paid_amount REAL DEFAULT 0,
                created_at TEXT
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                target_amount REAL DEFAULT 0,
                current_amount REAL DEFAULT 0,
                currency TEXT,
                target_date TEXT,
                created_at TEXT
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS debts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                total_amount REAL DEFAULT 0,
                paid_amount REAL DEFAULT 0,
                currency TEXT,
                due_date TEXT,
                created_at TEXT
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS receivables (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                total_amount REAL DEFAULT 0,
                collected_amount REAL DEFAULT 0,
                currency TEXT,
                due_date TEXT,
                created_at TEXT
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )

        # Migration: link columns on transactions so activity rows (goal deposit,
        # debt payment, etc.) are just ledger entries tied back to their entity.
        cols = {r[1] for r in con.execute("PRAGMA table_info(transactions)")}
        for col in ("goal_id", "debt_id", "receivable_id", "installment_id", "recurring_id"):
            if col not in cols:
                con.execute(f"ALTER TABLE transactions ADD COLUMN {col} INTEGER")

        # Seed default categories exactly once (keyed on an empty table).
        existing = con.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
        if not existing:
            con.executemany(
                "INSERT INTO categories (name, kind, color, parent_id, is_system) "
                "VALUES (?,?,?,NULL,1)",
                DEFAULT_CATEGORIES,
            )
        con.commit()


def _now() -> str:
    return datetime.utcnow().isoformat()


# --------------------------------------------------------------------------- #
# Balance engine
# --------------------------------------------------------------------------- #
def _balances() -> dict[int, float]:
    """Derive every account's current balance in one pass over the ledger.

    balance = opening_balance
              + income into the account
              - expenses out of the account
              - transfers out (amount + fee)
              + transfers in (amount)

    For liability accounts (credit/loans) a negative balance means money owed.
    """
    with _connect() as con:
        bal: dict[int, float] = {}
        for aid, opening in con.execute("SELECT id, opening_balance FROM accounts"):
            bal[aid] = opening or 0.0

        rows = con.execute(
            "SELECT kind, amount, account_id, to_account_id, fee FROM transactions"
        ).fetchall()
    for kind, amount, account_id, to_account_id, fee in rows:
        amount = amount or 0.0
        fee = fee or 0.0
        if kind == "income":
            if account_id in bal:
                bal[account_id] += amount
        elif kind == "expense":
            if account_id in bal:
                bal[account_id] -= amount
        elif kind == "transfer":
            if account_id in bal:
                bal[account_id] -= amount + fee
            if to_account_id in bal:
                bal[to_account_id] += amount
    return bal


def account_balance(account_id: int) -> float:
    return round(_balances().get(account_id, 0.0), 2)


def net_worth(include_credit: bool = True, show_liabilities: bool = True) -> dict:
    """Aggregate the net-worth headline plus the Assets / Liabilities split that
    backs the segmented control on Wallet > Accounts (PRD §4)."""
    bal = _balances()
    with _connect() as con:
        con.row_factory = None
        rows = con.execute(
            "SELECT id, type, include_in_totals FROM accounts WHERE archived = 0"
        ).fetchall()

    assets = 0.0
    liabilities = 0.0  # stored as a positive magnitude of what is owed
    for aid, atype, include in rows:
        if not include:
            continue
        b = bal.get(aid, 0.0)
        if atype in ASSET_TYPES:
            assets += b
        elif atype in LIABILITY_TYPES:
            if atype == "credit" and not include_credit:
                continue
            liabilities += -b  # negative balance -> positive owed

    net = assets - (liabilities if show_liabilities else 0.0)
    return {
        "assets": round(assets, 2),
        "liabilities": round(liabilities, 2),
        "net": round(net, 2),
    }


# --------------------------------------------------------------------------- #
# Accounts CRUD
# --------------------------------------------------------------------------- #
def list_accounts(include_archived: bool = False) -> list[dict]:
    init_finance_schema()
    bal = _balances()

    with _connect() as con:
        con.row_factory = sqlite3.Row
        sql = "SELECT * FROM accounts"
        if not include_archived:
            sql += " WHERE archived = 0"
        sql += " ORDER BY id"
        rows = con.execute(sql).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["balance"] = round(bal.get(d["id"], 0.0), 2)
        out.append(d)
    return out


def get_account(account_id: int) -> dict | None:

    with _connect() as con:
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["balance"] = account_balance(account_id)
    return d


def create_account(name: str, type: str, opening_balance: float = 0.0,
                   currency: str | None = None, include_in_totals: bool = True) -> int:
    init_finance_schema()
    if type not in ACCOUNT_TYPES:
        raise FinanceError(f"Unknown account type: {type!r}")
    if not (name or "").strip():
        raise FinanceError("Account name is required")
    with _connect() as con:
        cur = con.execute(
            "INSERT INTO accounts (name, type, opening_balance, currency, "
            "include_in_totals, archived, created_at) VALUES (?,?,?,?,?,0,?)",
            (name.strip(), type, opening_balance or 0.0, currency,
             int(bool(include_in_totals)), _now()),
        )
        con.commit()
        return cur.lastrowid


def update_account(account_id: int, payload: dict) -> dict | None:
    """Update an account's editable fields. Type and currency are read-only after
    creation (PRD §4) to avoid desynchronizing historical transactions — attempts
    to change them are rejected rather than silently ignored."""
    current = get_account(account_id)
    if current is None:
        return None
    if "type" in payload and payload["type"] != current["type"]:
        raise FinanceError("Account type cannot be changed after creation")
    if "currency" in payload and payload["currency"] != current["currency"]:
        raise FinanceError("Account currency cannot be changed after creation")

    editable = {}
    if "name" in payload:
        if not (payload["name"] or "").strip():
            raise FinanceError("Account name is required")
        editable["name"] = payload["name"].strip()
    if "opening_balance" in payload:
        editable["opening_balance"] = payload["opening_balance"] or 0.0
    if "include_in_totals" in payload:
        editable["include_in_totals"] = int(bool(payload["include_in_totals"]))
    if "archived" in payload:
        editable["archived"] = int(bool(payload["archived"]))
    if not editable:
        return current

    sets = ", ".join(f"{k} = ?" for k in editable)
    with _connect() as con:
        con.execute(f"UPDATE accounts SET {sets} WHERE id = ?",
                    (*editable.values(), account_id))
        con.commit()
    return get_account(account_id)


def set_account_balance(account_id: int, target_balance: float) -> dict | None:
    """Balance adjustment (PRD §5.3): overwrite an account's balance without a fake
    transaction, by shifting opening_balance to close the gap to `target_balance`.
    Handy for reconciling stock/crypto valuations."""
    current = get_account(account_id)
    if current is None:
        return None
    delta = target_balance - current["balance"]
    new_opening = (current["opening_balance"] or 0.0) + delta
    with _connect() as con:
        con.execute("UPDATE accounts SET opening_balance = ? WHERE id = ?",
                    (new_opening, account_id))
        con.commit()
    return get_account(account_id)


def delete_account(account_id: int) -> bool:
    """Delete an account only if nothing references it. Accounts tied to
    transactions are archived-protected (PRD §22 referential integrity): the
    caller should archive instead."""
    with _connect() as con:
        used = con.execute(
            "SELECT COUNT(*) FROM transactions WHERE account_id = ? OR to_account_id = ?",
            (account_id, account_id),
        ).fetchone()[0]
        if used:
            raise FinanceError(
                "Account has transactions and cannot be deleted; archive it instead"
            )
        cur = con.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        con.commit()
        return cur.rowcount > 0


# --------------------------------------------------------------------------- #
# Transactions CRUD (unified expense / income / transfer ledger)
# --------------------------------------------------------------------------- #
def _account_type(con, account_id: int | None) -> str | None:
    if account_id is None:
        return None
    row = con.execute("SELECT type FROM accounts WHERE id = ?", (account_id,)).fetchone()
    return row[0] if row else None


def _category_id_for_name(con, name: str | None) -> int | None:
    """Best-effort map a receipt's category string to an expense category id, so an
    OCR'd receipt lands in the right bucket on the budget-tracker side."""
    if not name:
        return None
    row = con.execute(
        "SELECT id FROM categories WHERE kind = 'expense' AND lower(name) = lower(?) "
        "ORDER BY is_system DESC LIMIT 1",
        (name,),
    ).fetchone()
    return row[0] if row else None


def post_receipt_as_expense(receipt_id: int, account_id: int) -> int:
    """Bridge: turn an OCR'd receipt into an expense transaction against `account_id`
    (PRD integration). The transaction links back via receipt_id so the two views
    stay in sync, and it inherits the receipt's amount, date, vendor and category.
    Idempotent per receipt: re-posting updates the existing linked transaction."""
    init_finance_schema()
    with _connect() as con:
        con.row_factory = sqlite3.Row
        r = con.execute(
            "SELECT vendor_name, total_amount, receipt_date, category "
            "FROM receipts WHERE id = ?",
            (receipt_id,),
        ).fetchone()
        if r is None:
            raise FinanceError(f"Receipt {receipt_id} not found")
        if _account_type(con, account_id) is None:
            raise FinanceError("Account not found")
        amount = r["total_amount"] or 0.0
        if amount <= 0:
            raise FinanceError("Receipt has no positive total to post")
        cat_id = _category_id_for_name(con, r["category"])
        existing = con.execute(
            "SELECT id FROM transactions WHERE receipt_id = ?", (receipt_id,)
        ).fetchone()
        if existing:
            con.execute(
                "UPDATE transactions SET amount=?, account_id=?, category_id=?, "
                "note=?, occurred_at=? WHERE id=?",
                (amount, account_id, cat_id, r["vendor_name"],
                 r["receipt_date"], existing["id"]),
            )
            con.commit()
            return existing["id"]
        cur = con.execute(
            "INSERT INTO transactions (kind, amount, account_id, category_id, note, "
            "occurred_at, fee, receipt_id, created_at) "
            "VALUES ('expense',?,?,?,?,?,0,?,?)",
            (amount, account_id, cat_id, r["vendor_name"], r["receipt_date"],
             receipt_id, _now()),
        )
        con.commit()
        return cur.lastrowid


def create_transaction(
    kind: str,
    amount: float,
    account_id: int | None = None,
    to_account_id: int | None = None,
    category_id: int | None = None,
    note: str | None = None,
    occurred_at: str | None = None,
    fee: float = 0.0,
    receipt_id: int | None = None,
    template_id: int | None = None,
) -> int:
    """Insert a ledger entry, enforcing the account-type rules from PRD §22:
    income and transfers may only touch debit accounts; expenses may use any."""
    init_finance_schema()
    if kind not in TXN_KINDS:
        raise FinanceError(f"Unknown transaction kind: {kind!r}")
    if amount is None or amount <= 0:
        raise FinanceError("Amount must be greater than 0")

    with _connect() as con:
        src_type = _account_type(con, account_id)
        if kind in ("expense", "transfer") and account_id is not None and src_type is None:
            raise FinanceError("Source account not found")

        if kind == "income":
            if src_type not in DEBIT_TYPES:
                raise FinanceError("Income can only be added to a debit account")
            to_account_id = None
        elif kind == "transfer":
            if src_type not in DEBIT_TYPES:
                raise FinanceError("Transfers can only be made from a debit account")
            if _account_type(con, to_account_id) not in DEBIT_TYPES:
                raise FinanceError("Transfers can only be made to a debit account")
            if account_id == to_account_id:
                raise FinanceError("Cannot transfer to the same account")
        else:  # expense
            to_account_id = None

        cur = con.execute(
            "INSERT INTO transactions (kind, amount, account_id, to_account_id, "
            "category_id, note, occurred_at, fee, receipt_id, template_id, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (kind, amount, account_id, to_account_id, category_id, note,
             occurred_at or datetime.utcnow().isoformat(), fee or 0.0,
             receipt_id, template_id, _now()),
        )
        con.commit()
        return cur.lastrowid


def list_transactions(
    limit: int = 1000,
    kind: str | None = None,
    account_id: int | None = None,
    category_id: int | None = None,
    search: str | None = None,
) -> list[dict]:
    """Ledger rows joined to account + category display fields, newest first.
    Optional filters back the History page (PRD §19)."""
    init_finance_schema()

    clauses = []
    params: list = []
    if kind in TXN_KINDS:
        clauses.append("t.kind = ?")
        params.append(kind)
    if account_id is not None:
        clauses.append("(t.account_id = ? OR t.to_account_id = ?)")
        params.extend([account_id, account_id])
    if category_id is not None:
        clauses.append("t.category_id = ?")
        params.append(category_id)
    if search:
        clauses.append("(t.note LIKE ? OR c.name LIKE ? OR a.name LIKE ?)")
        like = f"%{search}%"
        params.extend([like, like, like])
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    with _connect() as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            f"""
            SELECT t.*,
                   a.name  AS account_name,
                   a.type  AS account_type,
                   d.name  AS to_account_name,
                   c.name  AS category_name,
                   c.color AS category_color
            FROM transactions t
            LEFT JOIN accounts   a ON t.account_id    = a.id
            LEFT JOIN accounts   d ON t.to_account_id = d.id
            LEFT JOIN categories c ON t.category_id   = c.id
            {where}
            ORDER BY COALESCE(t.occurred_at, t.created_at) DESC, t.id DESC
            LIMIT ?
            """,
            (*params, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_transaction(txn_id: int) -> dict | None:

    with _connect() as con:
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT * FROM transactions WHERE id = ?", (txn_id,)).fetchone()
    return dict(row) if row else None


def update_transaction(txn_id: int, payload: dict) -> dict | None:
    """Update an existing ledger entry's editable fields (amount, category, note,
    date, account). Re-validates account-type rules when the account changes."""
    current = get_transaction(txn_id)
    if current is None:
        return None
    kind = payload.get("kind", current["kind"])
    fields = {"amount", "account_id", "to_account_id", "category_id", "note",
              "occurred_at", "fee"}
    merged = dict(current)
    for k in fields:
        if k in payload:
            merged[k] = payload[k]

    if merged.get("amount") is None or merged["amount"] <= 0:
        raise FinanceError("Amount must be greater than 0")

    with _connect() as con:
        if kind == "income" and _account_type(con, merged["account_id"]) not in DEBIT_TYPES:
            raise FinanceError("Income can only be added to a debit account")
        if kind == "transfer":
            if _account_type(con, merged["account_id"]) not in DEBIT_TYPES:
                raise FinanceError("Transfers can only be made from a debit account")
            if _account_type(con, merged["to_account_id"]) not in DEBIT_TYPES:
                raise FinanceError("Transfers can only be made to a debit account")
        con.execute(
            "UPDATE transactions SET amount=?, account_id=?, to_account_id=?, "
            "category_id=?, note=?, occurred_at=?, fee=? WHERE id=?",
            (merged["amount"], merged["account_id"], merged["to_account_id"],
             merged["category_id"], merged["note"], merged["occurred_at"],
             merged.get("fee") or 0.0, txn_id),
        )
        con.commit()
    return get_transaction(txn_id)


def delete_transaction(txn_id: int) -> bool:
    with _connect() as con:
        cur = con.execute("DELETE FROM transactions WHERE id = ?", (txn_id,))
        con.commit()
        return cur.rowcount > 0


# --------------------------------------------------------------------------- #
# Categories & subcategories
# --------------------------------------------------------------------------- #
def list_categories() -> list[dict]:
    init_finance_schema()

    with _connect() as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT * FROM categories ORDER BY (parent_id IS NOT NULL), kind, name"
        ).fetchall()
    return [dict(r) for r in rows]


def create_category(name: str, kind: str, color: str | None = None,
                    parent_id: int | None = None) -> int:
    init_finance_schema()
    if kind not in ("expense", "income"):
        raise FinanceError("Category kind must be expense or income")
    if not (name or "").strip():
        raise FinanceError("Category name is required")
    with _connect() as con:
        cur = con.execute(
            "INSERT INTO categories (name, kind, color, parent_id, is_system) "
            "VALUES (?,?,?,?,0)",
            (name.strip(), kind, color, parent_id),
        )
        con.commit()
        return cur.lastrowid


def delete_category(category_id: int) -> bool:
    """Only custom categories are removable; system defaults are protected
    (PRD §8). Categories in use by transactions are also protected."""
    with _connect() as con:
        row = con.execute(
            "SELECT is_system FROM categories WHERE id = ?", (category_id,)
        ).fetchone()
        if row is None:
            return False
        if row[0]:
            raise FinanceError("System categories cannot be deleted")
        used = con.execute(
            "SELECT COUNT(*) FROM transactions WHERE category_id = ?", (category_id,)
        ).fetchone()[0]
        if used:
            raise FinanceError("Category is used by transactions and cannot be deleted")
        con.execute("DELETE FROM categories WHERE parent_id = ?", (category_id,))
        con.execute("DELETE FROM categories WHERE id = ?", (category_id,))
        con.commit()
        return True


# --------------------------------------------------------------------------- #
# Tags
# --------------------------------------------------------------------------- #
def list_tags() -> list[dict]:
    init_finance_schema()

    with _connect() as con:
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT * FROM tags ORDER BY name").fetchall()
    return [dict(r) for r in rows]


def create_tag(name: str, kind: str = "Custom", color: str | None = None) -> int:
    init_finance_schema()
    if not (name or "").strip():
        raise FinanceError("Tag name is required")
    with _connect() as con:
        cur = con.execute(
            "INSERT INTO tags (name, kind, color) VALUES (?,?,?)",
            (name.strip(), kind or "Custom", color),
        )
        con.commit()
        return cur.lastrowid


def delete_tag(tag_id: int) -> bool:
    with _connect() as con:
        cur = con.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
        con.commit()
        return cur.rowcount > 0


# --------------------------------------------------------------------------- #
# Period helpers for budgets
# --------------------------------------------------------------------------- #
from datetime import date, timedelta


def _period_bounds(interval: str, today: date | None = None) -> tuple[str, str]:
    """Inclusive [start, end] ISO dates for the current budget period."""
    today = today or date.today()
    if interval == "daily":
        start = end = today
    elif interval == "weekly":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
    elif interval == "yearly":
        start = date(today.year, 1, 1)
        end = date(today.year, 12, 31)
    else:  # monthly (default)
        start = date(today.year, today.month, 1)
        if today.month == 12:
            end = date(today.year, 12, 31)
        else:
            end = date(today.year, today.month + 1, 1) - timedelta(days=1)
    return start.isoformat(), end.isoformat()


def _add_month(iso: str | None) -> str:
    """Advance a YYYY-MM-DD date by one month (clamps day to 28 for safety)."""
    d = date.fromisoformat((iso or date.today().isoformat())[:10])
    y, m = d.year, d.month + 1
    if m > 12:
        m, y = 1, y + 1
    return date(y, m, min(d.day, 28)).isoformat()


def _insert_activity_txn(con, kind: str, amount: float, account_id: int, note: str,
                         occurred_at: str | None, **links) -> int:
    """Insert a ledger row for an entity activity (goal deposit, debt payment, …).
    The link kwargs (goal_id/debt_id/…) tie it back so History can show it and the
    balance engine adjusts the account automatically."""
    if _account_type(con, account_id) is None:
        raise FinanceError("Account not found")
    cols = ["kind", "amount", "account_id", "note", "occurred_at", "created_at"]
    vals = [kind, amount, account_id, note, occurred_at or date.today().isoformat(), _now()]
    for k, v in links.items():
        cols.append(k)
        vals.append(v)
    ph = ",".join("?" for _ in cols)
    cur = con.execute(f"INSERT INTO transactions ({','.join(cols)}) VALUES ({ph})", vals)
    return cur.lastrowid


# --------------------------------------------------------------------------- #
# Budgets (upgraded model: fixed / % of income, per interval)
# --------------------------------------------------------------------------- #
def list_budget_plans() -> list[dict]:
    """Budget rows with the amount spent in the current period computed from the
    ledger, plus the resolved limit (fixed, or % of this month's income)."""
    init_finance_schema()
    with _connect() as con:
        con.row_factory = sqlite3.Row
        plans = con.execute(
            "SELECT b.*, c.name AS category_name, c.color AS category_color "
            "FROM budget_plans b LEFT JOIN categories c ON b.category_id = c.id "
            "ORDER BY b.id"
        ).fetchall()
        out = []
        # This month's income backs percent-of-income budgets.
        month_start, month_end = _period_bounds("monthly")
        income_row = con.execute(
            "SELECT COALESCE(SUM(amount),0) FROM transactions "
            "WHERE kind='income' AND substr(occurred_at,1,10) BETWEEN ? AND ?",
            (month_start, month_end),
        ).fetchone()
        month_income = income_row[0] or 0.0

        for p in plans:
            d = dict(p)
            start, end = _period_bounds(d["interval"])
            spent = con.execute(
                "SELECT COALESCE(SUM(amount),0) FROM transactions "
                "WHERE kind='expense' AND category_id = ? "
                "AND substr(occurred_at,1,10) BETWEEN ? AND ?",
                (d["category_id"], start, end),
            ).fetchone()[0] or 0.0
            limit = (d["percent"] / 100.0 * month_income) if d["type"] == "percent" else d["limit_amount"]
            d["spent"] = round(spent, 2)
            d["limit"] = round(limit or 0.0, 2)
            d["pct"] = round(spent / limit * 100, 1) if limit else None
            out.append(d)
        return out


def create_budget_plan(category_id: int, type: str = "fixed", interval: str = "monthly",
                       limit_amount: float = 0, percent: float = 0,
                       carry_forward: bool = False) -> int:
    init_finance_schema()
    with _connect() as con:
        cur = con.execute(
            "INSERT INTO budget_plans (category_id, type, interval, limit_amount, percent, "
            "carry_forward, created_at) VALUES (?,?,?,?,?,?,?)",
            (category_id, type, interval, limit_amount or 0, percent or 0,
             int(bool(carry_forward)), _now()),
        )
        con.commit()
        return cur.lastrowid


def delete_budget_plan(plan_id: int) -> bool:
    with _connect() as con:
        cur = con.execute("DELETE FROM budget_plans WHERE id = ?", (plan_id,))
        con.commit()
        return cur.rowcount > 0


# --------------------------------------------------------------------------- #
# Templates
# --------------------------------------------------------------------------- #
def list_templates() -> list[dict]:
    init_finance_schema()
    with _connect() as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT t.*, a.name AS account_name FROM templates t "
            "LEFT JOIN accounts a ON t.account_id = a.id ORDER BY t.id"
        ).fetchall()
        return [dict(r) for r in rows]


def create_template(title: str, amount: float, kind: str, account_id: int | None,
                    category_id: int | None = None) -> int:
    init_finance_schema()
    if not (title or "").strip():
        raise FinanceError("Title is required")
    with _connect() as con:
        cur = con.execute(
            "INSERT INTO templates (title, amount, kind, account_id, category_id, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (title.strip(), amount or 0, kind, account_id, category_id, _now()),
        )
        con.commit()
        return cur.lastrowid


def delete_template(template_id: int) -> bool:
    with _connect() as con:
        cur = con.execute("DELETE FROM templates WHERE id = ?", (template_id,))
        con.commit()
        return cur.rowcount > 0


def use_template(template_id: int) -> int:
    """Materialize a template into a ledger transaction (PRD §10)."""
    with _connect() as con:
        con.row_factory = sqlite3.Row
        t = con.execute("SELECT * FROM templates WHERE id = ?", (template_id,)).fetchone()
        if t is None:
            raise FinanceError("Template not found")
    return create_transaction(
        t["kind"], t["amount"], account_id=t["account_id"],
        category_id=t["category_id"], note=t["title"], template_id=template_id,
    )


# --------------------------------------------------------------------------- #
# Recurring
# --------------------------------------------------------------------------- #
def list_recurring() -> list[dict]:
    init_finance_schema()
    with _connect() as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT r.*, a.name AS account_name FROM recurring r "
            "LEFT JOIN accounts a ON r.account_id = a.id ORDER BY r.next_due"
        ).fetchall()
        return [dict(r) for r in rows]


def create_recurring(kind: str, amount: float, name: str, account_id: int | None,
                     next_due: str | None, category_id: int | None = None) -> int:
    init_finance_schema()
    with _connect() as con:
        cur = con.execute(
            "INSERT INTO recurring (kind, amount, name, account_id, category_id, next_due, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (kind, amount or 0, name, account_id, category_id,
             next_due or date.today().isoformat(), _now()),
        )
        con.commit()
        return cur.lastrowid


def delete_recurring(rec_id: int) -> bool:
    with _connect() as con:
        cur = con.execute("DELETE FROM recurring WHERE id = ?", (rec_id,))
        con.commit()
        return cur.rowcount > 0


def advance_recurring(rec_id: int) -> dict:
    """Log the occurrence (create a ledger txn) and roll next_due forward a month
    (PRD §11 Paid/Received)."""
    with _connect() as con:
        con.row_factory = sqlite3.Row
        r = con.execute("SELECT * FROM recurring WHERE id = ?", (rec_id,)).fetchone()
        if r is None:
            raise FinanceError("Recurring item not found")
        _insert_activity_txn(
            con, r["kind"], r["amount"], r["account_id"],
            r["name"] or "Recurring", r["next_due"], recurring_id=rec_id,
            category_id=r["category_id"],
        )
        new_due = _add_month(r["next_due"])
        con.execute("UPDATE recurring SET next_due = ? WHERE id = ?", (new_due, rec_id))
        con.commit()
    return {"id": rec_id, "next_due": new_due}


# --------------------------------------------------------------------------- #
# Installments
# --------------------------------------------------------------------------- #
def list_installments() -> list[dict]:
    init_finance_schema()
    with _connect() as con:
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT * FROM installment_plans ORDER BY id").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["remaining"] = round((d["total"] or 0) - (d["paid_amount"] or 0), 2)
            d["pct"] = round((d["paid_amount"] or 0) / d["total"] * 100, 1) if d["total"] else None
            out.append(d)
        return out


def create_installment(title: str, total: float, monthly: float, months: int) -> int:
    init_finance_schema()
    if not (title or "").strip():
        raise FinanceError("Title is required")
    with _connect() as con:
        cur = con.execute(
            "INSERT INTO installment_plans (title, total, monthly, months, paid_amount, created_at) "
            "VALUES (?,?,?,?,0,?)",
            (title.strip(), total or 0, monthly or 0, months or 0, _now()),
        )
        con.commit()
        return cur.lastrowid


def delete_installment(plan_id: int) -> bool:
    with _connect() as con:
        cur = con.execute("DELETE FROM installment_plans WHERE id = ?", (plan_id,))
        con.commit()
        return cur.rowcount > 0


def log_installment_payment(plan_id: int, account_id: int, amount: float,
                            occurred_at: str | None = None) -> int:
    if amount is None or amount <= 0:
        raise FinanceError("Amount must be greater than 0")
    with _connect() as con:
        con.row_factory = sqlite3.Row
        p = con.execute("SELECT * FROM installment_plans WHERE id = ?", (plan_id,)).fetchone()
        if p is None:
            raise FinanceError("Installment plan not found")
        txn = _insert_activity_txn(
            con, "expense", amount, account_id,
            f"Installment: {p['title']}", occurred_at, installment_id=plan_id,
        )
        con.execute(
            "UPDATE installment_plans SET paid_amount = paid_amount + ? WHERE id = ?",
            (amount, plan_id),
        )
        con.commit()
        return txn


# --------------------------------------------------------------------------- #
# Goals + Goal activity
# --------------------------------------------------------------------------- #
def list_goals() -> list[dict]:
    init_finance_schema()
    with _connect() as con:
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT * FROM goals ORDER BY id").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["pct"] = round((d["current_amount"] or 0) / d["target_amount"] * 100, 1) if d["target_amount"] else None
            out.append(d)
        return out


def create_goal(title: str, target_amount: float, current_amount: float = 0,
                currency: str | None = None, target_date: str | None = None) -> int:
    init_finance_schema()
    if not (title or "").strip():
        raise FinanceError("Title is required")
    with _connect() as con:
        cur = con.execute(
            "INSERT INTO goals (title, target_amount, current_amount, currency, target_date, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (title.strip(), target_amount or 0, current_amount or 0, currency, target_date, _now()),
        )
        con.commit()
        return cur.lastrowid


def update_goal(goal_id: int, payload: dict) -> bool:
    fields = {k: payload[k] for k in ("title", "target_amount", "current_amount", "currency", "target_date") if k in payload}
    if not fields:
        return False
    sets = ", ".join(f"{k} = ?" for k in fields)
    with _connect() as con:
        cur = con.execute(f"UPDATE goals SET {sets} WHERE id = ?", (*fields.values(), goal_id))
        con.commit()
        return cur.rowcount > 0


def delete_goal(goal_id: int) -> bool:
    with _connect() as con:
        cur = con.execute("DELETE FROM goals WHERE id = ?", (goal_id,))
        con.commit()
        return cur.rowcount > 0


def goal_activity(goal_id: int, account_id: int, amount: float, type: str,
                  occurred_at: str | None = None) -> int:
    """Deposit (debit account -> goal) or Withdrawal (goal -> debit account),
    updating both the goal's current amount and the account balance (PRD §14)."""
    if amount is None or amount <= 0:
        raise FinanceError("Amount must be greater than 0")
    if _account_type_global(account_id) not in DEBIT_TYPES:
        raise FinanceError("Goal activity uses a debit account")
    with _connect() as con:
        con.row_factory = sqlite3.Row
        g = con.execute("SELECT * FROM goals WHERE id = ?", (goal_id,)).fetchone()
        if g is None:
            raise FinanceError("Goal not found")
        if type == "deposit":
            txn = _insert_activity_txn(con, "expense", amount, account_id,
                                       f"Goal deposit: {g['title']}", occurred_at, goal_id=goal_id)
            con.execute("UPDATE goals SET current_amount = current_amount + ? WHERE id = ?", (amount, goal_id))
        elif type == "withdrawal":
            txn = _insert_activity_txn(con, "income", amount, account_id,
                                       f"Goal withdrawal: {g['title']}", occurred_at, goal_id=goal_id)
            con.execute("UPDATE goals SET current_amount = MAX(0, current_amount - ?) WHERE id = ?", (amount, goal_id))
        else:
            raise FinanceError("type must be deposit or withdrawal")
        con.commit()
        return txn


# --------------------------------------------------------------------------- #
# Debts + Debt activity
# --------------------------------------------------------------------------- #
def list_debts() -> list[dict]:
    init_finance_schema()
    with _connect() as con:
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT * FROM debts ORDER BY id").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["outstanding"] = round((d["total_amount"] or 0) - (d["paid_amount"] or 0), 2)
            d["pct"] = round((d["paid_amount"] or 0) / d["total_amount"] * 100, 1) if d["total_amount"] else None
            out.append(d)
        return out


def create_debt(name: str, total_amount: float, paid_amount: float = 0,
                currency: str | None = None, due_date: str | None = None) -> int:
    init_finance_schema()
    if not (name or "").strip():
        raise FinanceError("Name is required")
    with _connect() as con:
        cur = con.execute(
            "INSERT INTO debts (name, total_amount, paid_amount, currency, due_date, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (name.strip(), total_amount or 0, paid_amount or 0, currency, due_date, _now()),
        )
        con.commit()
        return cur.lastrowid


def delete_debt(debt_id: int) -> bool:
    with _connect() as con:
        cur = con.execute("DELETE FROM debts WHERE id = ?", (debt_id,))
        con.commit()
        return cur.rowcount > 0


def debt_activity(debt_id: int, account_id: int, amount: float, type: str,
                  occurred_at: str | None = None) -> int:
    """Payment reduces outstanding & debits the account; Borrowing increases the
    outstanding total & credits the account (PRD §16)."""
    if amount is None or amount <= 0:
        raise FinanceError("Amount must be greater than 0")
    with _connect() as con:
        con.row_factory = sqlite3.Row
        d = con.execute("SELECT * FROM debts WHERE id = ?", (debt_id,)).fetchone()
        if d is None:
            raise FinanceError("Debt not found")
        if type == "payment":
            txn = _insert_activity_txn(con, "expense", amount, account_id,
                                       f"Debt payment: {d['name']}", occurred_at, debt_id=debt_id)
            con.execute("UPDATE debts SET paid_amount = paid_amount + ? WHERE id = ?", (amount, debt_id))
        elif type == "borrowing":
            txn = _insert_activity_txn(con, "income", amount, account_id,
                                       f"Borrowing: {d['name']}", occurred_at, debt_id=debt_id)
            con.execute("UPDATE debts SET total_amount = total_amount + ? WHERE id = ?", (amount, debt_id))
        else:
            raise FinanceError("type must be payment or borrowing")
        con.commit()
        return txn


# --------------------------------------------------------------------------- #
# Receivables + Receivable activity
# --------------------------------------------------------------------------- #
def list_receivables() -> list[dict]:
    init_finance_schema()
    with _connect() as con:
        con.row_factory = sqlite3.Row
        rows = con.execute("SELECT * FROM receivables ORDER BY id").fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["remaining"] = round((d["total_amount"] or 0) - (d["collected_amount"] or 0), 2)
            d["pct"] = round((d["collected_amount"] or 0) / d["total_amount"] * 100, 1) if d["total_amount"] else None
            out.append(d)
        return out


def create_receivable(name: str, total_amount: float, collected_amount: float = 0,
                      currency: str | None = None, due_date: str | None = None) -> int:
    init_finance_schema()
    if not (name or "").strip():
        raise FinanceError("Name is required")
    with _connect() as con:
        cur = con.execute(
            "INSERT INTO receivables (name, total_amount, collected_amount, currency, due_date, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (name.strip(), total_amount or 0, collected_amount or 0, currency, due_date, _now()),
        )
        con.commit()
        return cur.lastrowid


def delete_receivable(rec_id: int) -> bool:
    with _connect() as con:
        cur = con.execute("DELETE FROM receivables WHERE id = ?", (rec_id,))
        con.commit()
        return cur.rowcount > 0


def receivable_activity(rec_id: int, account_id: int, amount: float, type: str,
                        occurred_at: str | None = None) -> int:
    """Collection increases the collected amount & credits the account; Advance
    increases the total owed & debits the account (PRD §18)."""
    if amount is None or amount <= 0:
        raise FinanceError("Amount must be greater than 0")
    with _connect() as con:
        con.row_factory = sqlite3.Row
        r = con.execute("SELECT * FROM receivables WHERE id = ?", (rec_id,)).fetchone()
        if r is None:
            raise FinanceError("Receivable not found")
        if type == "collection":
            txn = _insert_activity_txn(con, "income", amount, account_id,
                                       f"Collection: {r['name']}", occurred_at, receivable_id=rec_id)
            con.execute("UPDATE receivables SET collected_amount = collected_amount + ? WHERE id = ?", (amount, rec_id))
        elif type == "advance":
            txn = _insert_activity_txn(con, "expense", amount, account_id,
                                       f"Advance: {r['name']}", occurred_at, receivable_id=rec_id)
            con.execute("UPDATE receivables SET total_amount = total_amount + ? WHERE id = ?", (amount, rec_id))
        else:
            raise FinanceError("type must be collection or advance")
        con.commit()
        return txn


# --------------------------------------------------------------------------- #
# Activity logs — append-only history of debt / receivable movements (PRD §16/18)
# --------------------------------------------------------------------------- #
def list_debt_activity(limit: int = 500) -> list[dict]:
    """Chronological log of every payment/borrowing ever recorded against a debt.
    This is a history of individual events — distinct from the debts page, which
    shows current outstanding balances."""
    init_finance_schema()
    with _connect() as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """
            SELECT t.id, t.kind, t.amount, t.occurred_at, t.note, t.debt_id,
                   d.name AS debt_name, d.currency AS currency, a.name AS account_name
            FROM transactions t
            JOIN debts d ON t.debt_id = d.id
            LEFT JOIN accounts a ON t.account_id = a.id
            WHERE t.debt_id IS NOT NULL
            ORDER BY COALESCE(t.occurred_at, t.created_at) DESC, t.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        # expense = you paid down the debt; income = you borrowed more.
        d["activity_type"] = "payment" if d["kind"] == "expense" else "borrowing"
        out.append(d)
    return out


def list_receivable_activity(limit: int = 500) -> list[dict]:
    """Chronological log of collections/advances against receivables (PRD §18)."""
    init_finance_schema()
    with _connect() as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            """
            SELECT t.id, t.kind, t.amount, t.occurred_at, t.note, t.receivable_id,
                   r.name AS receivable_name, r.currency AS currency, a.name AS account_name
            FROM transactions t
            JOIN receivables r ON t.receivable_id = r.id
            LEFT JOIN accounts a ON t.account_id = a.id
            WHERE t.receivable_id IS NOT NULL
            ORDER BY COALESCE(t.occurred_at, t.created_at) DESC, t.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        # income = they paid you (collection); expense = you gave more (advance).
        d["activity_type"] = "collection" if d["kind"] == "income" else "advance"
        out.append(d)
    return out


# --------------------------------------------------------------------------- #
# Upcoming (aggregation of due items — PRD §6)
# --------------------------------------------------------------------------- #
def upcoming() -> dict:
    """Read-only aggregation of action items: recurring expenses, recurring income,
    debt/receivable due dates and installment plans, each with a days-to-due delta."""
    init_finance_schema()
    today = date.today()

    def days(d: str | None):
        if not d:
            return None
        try:
            return (date.fromisoformat(d[:10]) - today).days
        except ValueError:
            return None

    rec = list_recurring()
    return {
        "recurring_expenses": [
            {**r, "days_to_due": days(r["next_due"])} for r in rec if r["kind"] == "expense"
        ],
        "recurring_income": [
            {**r, "days_to_due": days(r["next_due"])} for r in rec if r["kind"] == "income"
        ],
        "debts": [
            {**d, "days_to_due": days(d["due_date"])} for d in list_debts() if d["outstanding"] > 0
        ],
    }


def _account_type_global(account_id: int | None) -> str | None:
    with _connect() as con:
        return _account_type(con, account_id)


# --------------------------------------------------------------------------- #
# Settings (key/value; persisted in the ledger so backups carry preferences)
# --------------------------------------------------------------------------- #
def get_settings() -> dict:
    init_finance_schema()
    with _connect() as con:
        rows = con.execute("SELECT key, value FROM settings").fetchall()
    return {k: v for k, v in rows}


def set_settings(values: dict) -> dict:
    init_finance_schema()
    with _connect() as con:
        for k, v in values.items():
            con.execute(
                "INSERT INTO settings (key, value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (k, str(v)),
            )
        con.commit()
    return get_settings()


# --------------------------------------------------------------------------- #
# JSON backup export / import (PRD §21 imported-session model)
# --------------------------------------------------------------------------- #
_BACKUP_TABLES = [
    "accounts", "transactions", "categories", "tags", "budget_plans", "templates",
    "recurring", "installment_plans", "goals", "debts", "receivables", "settings",
]

BACKUP_FORMAT = "stai-ledger-backup/1"


def export_backup() -> dict:
    init_finance_schema()
    out: dict = {"format": BACKUP_FORMAT, "exported_at": _now(), "data": {}}
    with _connect() as con:
        con.row_factory = sqlite3.Row
        for t in _BACKUP_TABLES:
            rows = con.execute(f"SELECT * FROM {t}").fetchall()
            out["data"][t] = [dict(r) for r in rows]
    return out


def _validate_backup(payload) -> dict:
    """Check a backup payload before it is allowed anywhere near the ledger.

    This runs BEFORE any DELETE. Previously `import_backup` did
    `data = (payload or {}).get("data", {})`, so a malformed payload silently
    yielded `{}` and, with replace=True, wiped all twelve finance tables and
    inserted nothing — reported as a success. Validating up front turns that into
    a refusal.

    A backup of an genuinely empty ledger is still valid and restorable: emptiness
    is not the thing being rejected, an unrecognized *shape* is.
    """
    if not isinstance(payload, dict):
        raise FinanceError("Backup must be a JSON object.")

    fmt = payload.get("format")
    if fmt != BACKUP_FORMAT:
        raise FinanceError(
            f"Unrecognized backup format {fmt!r}; expected {BACKUP_FORMAT!r}."
        )

    data = payload.get("data")
    if not isinstance(data, dict):
        raise FinanceError("Backup is missing its 'data' object.")

    unknown = sorted(set(data) - set(_BACKUP_TABLES))
    if unknown:
        raise FinanceError(f"Backup contains unknown table(s): {unknown}")

    for table, rows in data.items():
        if not isinstance(rows, list):
            raise FinanceError(f"Backup table {table!r} must be a list of rows.")
        for row in rows:
            if not isinstance(row, dict):
                raise FinanceError(f"Backup table {table!r} contains a non-object row.")
    return data


def import_backup(payload: dict, replace: bool = True) -> dict:
    """Restore a backup into the ledger. With replace=True the finance tables are
    cleared first (the imported session becomes the state).

    The payload is fully validated before anything is deleted, and the whole
    restore runs in one transaction — so a bad backup leaves the existing ledger
    exactly as it was, rather than half-erased.
    """
    init_finance_schema()
    data = _validate_backup(payload)
    counts = {}
    with _connect() as con:
        # Column names cannot be parameterized, so they are interpolated into the
        # INSERT. Check every one against the real schema first: unvalidated keys
        # from an uploaded file would otherwise be a SQL injection vector as well
        # as a crash.
        table_columns = {
            t: {r[1] for r in con.execute(f"PRAGMA table_info({t})")}
            for t in _BACKUP_TABLES
        }
        for table, rows in data.items():
            for row in rows:
                bad = sorted(set(row) - table_columns[table])
                if bad:
                    raise FinanceError(f"Backup table {table!r} has unknown column(s): {bad}")

        if replace:
            for t in _BACKUP_TABLES:
                con.execute(f"DELETE FROM {t}")
        for t in _BACKUP_TABLES:
            rows = data.get(t, [])
            counts[t] = len(rows)
            for row in rows:
                keys = list(row.keys())
                if not keys:
                    continue
                ph = ",".join("?" for _ in keys)
                cols = ",".join(f'"{k}"' for k in keys)
                con.execute(
                    f"INSERT INTO {t} ({cols}) VALUES ({ph})",
                    [row[k] for k in keys],
                )
        con.commit()
    return {"imported": counts}


# --------------------------------------------------------------------------- #
# Quick-chat NLP (server-side rule parser — PRD §2.2)
# --------------------------------------------------------------------------- #
import re as _re

_INCOME_WORDS = _re.compile(r"\b(salary|income|paid|received|refund|bonus|deposit|gift)\b", _re.I)
_TRANSFER_WORDS = _re.compile(r"\b(transfer|move|send to|moved)\b", _re.I)
_MONTHS_FULL = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]


# The trailing \b is load-bearing. Without it the optional [km] suffix matched the
# first letter of the FOLLOWING word: "250 milk" parsed as 250 x 1,000,000 = ₱250M,
# "300 movie tickets" as ₱300M, "250 kilo rice" as ₱250,000. With \b, a suffix must
# end a word, so "1.2k lunch" and "2m bonus" still work while "250 milk" is ₱250.
_AMOUNT_RE = _re.compile(r"(?:₱|php|\$)?\s*([\d,]+(?:\.\d+)?)\s*([km])?\b", _re.I)


def _parse_amount(text: str):
    m = _AMOUNT_RE.search(text)
    if not m:
        return None
    try:
        n = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    suf = (m.group(2) or "").lower()
    if suf == "k":
        n *= 1_000
    elif suf == "m":
        n *= 1_000_000
    return n


def _parse_date(text: str):
    t = text.lower()
    today = date.today()
    if "yesterday" in t:
        return (today - timedelta(days=1)).isoformat()
    if "tomorrow" in t:
        return (today + timedelta(days=1)).isoformat()
    if "today" in t:
        return today.isoformat()
    # Collect month/day candidates from BOTH orderings and take the first that
    # resolves to a real month, ordered by position in the text.
    #
    # These two patterns used to be joined with `or`, so if the "mon d" pattern
    # matched anything the "d mon" pattern was never tried: in "250 lunch 1 apr"
    # the first pattern matched the note word plus the day ("lunch 1"), the month
    # lookup failed, and the function fell through to today's date. Mirrors the
    # same fix in web-next/app/lib/parseQuick.ts.
    candidates: list[tuple[int, str, str]] = []
    for m in _re.finditer(r"\b([a-z]{3,9})\s+(\d{1,2})\b", t):
        candidates.append((m.start(), m.group(1), m.group(2)))
    for m in _re.finditer(r"\b(\d{1,2})\s+([a-z]{3,9})\b", t):
        candidates.append((m.start(), m.group(2), m.group(1)))
    candidates.sort(key=lambda c: c[0])

    for _pos, mon_tok, day_tok in candidates:
        # The token must be a prefix of a real month name, not the other way round:
        # a note word like "marketing" starts with "mar" but is not March.
        mi = next(
            (i for i, mm in enumerate(_MONTHS_FULL)
             if len(mon_tok) >= 3 and mm.startswith(mon_tok)),
            -1,
        )
        if mi < 0 or not day_tok.isdigit():
            continue
        day = int(day_tok)
        year = today.year
        # Build the real date rather than clamping to day 28, which silently turned
        # "apr 30" into April 28. An impossible day (e.g. "feb 30") is skipped so a
        # later candidate can still match.
        try:
            cand = date(year, mi + 1, day)
        except ValueError:
            continue
        if (cand - today).days > 183:
            try:
                cand = date(year - 1, mi + 1, day)
            except ValueError:
                continue
        return cand.isoformat()
    return today.isoformat()


def parse_quick_text(text: str) -> dict:
    """Parse free text into a draft transaction (amount, kind, category, account,
    date). Rule-based and dependency-free so it works without the LLM; the vision
    agent could be swapped in later behind the same contract."""
    init_finance_schema()
    raw = (text or "").strip()
    amount = _parse_amount(raw)
    if amount is None or amount <= 0:
        return {"ok": False, "reason": "No amount found"}

    kind = "expense"
    if _TRANSFER_WORDS.search(raw):
        kind = "transfer"
    elif raw.lstrip().startswith("+") or _INCOME_WORDS.search(raw):
        kind = "income"

    lower = raw.lower()
    accounts = list_accounts()
    debit = [a for a in accounts if a["type"] == "debit"]
    cats = [c for c in list_categories() if c["kind"] == "expense"]

    category_id = next((c["id"] for c in cats if c["name"].lower() in lower), None)

    def match(pool):
        return next((a["id"] for a in pool if a["name"].lower() in lower), None)

    if kind in ("income", "transfer"):
        account_id = match(debit) or (debit[0]["id"] if debit else None)
    else:
        account_id = match(accounts) or (accounts[0]["id"] if accounts else None)
    to_account_id = None
    if kind == "transfer":
        to_account_id = next((a["id"] for a in debit if a["id"] != account_id), None)

    # Same \b as _AMOUNT_RE: without it "250 milk" stripped "250 m" and left "ilk".
    note = _re.sub(r"(?:₱|php|\$)?\s*[\d,]+(?:\.\d+)?\s*[km]?\b", "", raw, count=1, flags=_re.I)
    note = _re.sub(r"^\s*[+\-]\s*", "", note)
    note = _re.sub(r"\b(yesterday|today|tomorrow)\b", "", note, flags=_re.I).strip()

    return {
        "ok": True,
        "kind": kind,
        "amount": round(amount, 2),
        "note": note,
        "category_id": category_id if kind == "expense" else None,
        "account_id": account_id,
        "to_account_id": to_account_id,
        "occurred_at": _parse_date(raw),
    }
