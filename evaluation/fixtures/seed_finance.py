"""
seed_finance.py — deterministic finance + receipt fixture builder (W1 / breakdown §9
"Create one frozen SQLite finance fixture").

Why a script and not a committed .db
------------------------------------
`.gitignore` excludes `ledger.db` by basename, so a committed binary fixture would be
silently ignored (audit blocker B3). A script is version-controlled, reviewable in a
diff, and regenerates byte-comparable state on any machine — which is what "frozen
fixture" actually needs to mean here.

Determinism
-----------
Every amount, date and name below is a literal. Nothing derives from `date.today()`,
`utcnow()`, randomness, or the developer's machine. The two places the app itself
stamps wall-clock time (`created_at`, `processed_at`) are not part of any expected
value in `EXPECTED`.

No model is required: receipts are saved with `index=False`, so no embedding call is
made and the seeder runs fully offline.

Usage
-----
    python evaluation/fixtures/seed_finance.py [path/to/fixture.db]

Default output is `evaluation/fixtures/finance_fixture.db`. The file is rebuilt from
scratch on every run.

From tests, prefer the pytest `finance_fixture` fixture in `evaluation/tests/conftest.py`,
which handles the import-order requirement described below.

IMPORTANT — import order
------------------------
`core.DB_PATH` is read from `LEDGER_DB_PATH` at import time, and `core._connect()` binds
that path as a default argument. So the environment variable MUST be set before `core`
is first imported. `build()` asserts this rather than silently writing to the wrong
database — the failure mode it prevents is overwriting a developer's real `ledger.db`.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = Path(__file__).parent / "finance_fixture.db"

# Importable when run directly as a script from evaluation/fixtures/.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# --------------------------------------------------------------------------- #
# Expected state — the answer key.
#
# Hand-computed from the balance rules in `finance._balances()`:
#   balance = opening + income - expenses - (transfers out + fee) + transfers in
# These are ground truth for W2-B. They are NOT measured outputs: if a test fails
# against them, verify the arithmetic here by hand before changing either side.
# --------------------------------------------------------------------------- #
EXPECTED = {
    "balances": {
        # Cash: 5000 - 250 expense + 5000 transfer in
        "Cash": 9750.00,
        # BPI: 20000 - 1200 expense + 30000 income - (5000 transfer + 50 fee)
        "BPI Checking": 43750.00,
        # Credit Card (liability): 0 - 800 expense
        "Credit Card": -800.00,
        "Emergency Fund": 15000.00,
        # Present but excluded from net worth (archived / not included in totals)
        "Archived Wallet": 999.00,
        "Excluded Pocket": 500.00,
    },
    # net_worth() counts only archived = 0 AND include_in_totals = 1.
    # assets = Cash 9750 + BPI 43750 + Emergency Fund 15000
    "net_worth": {
        "assets": 68500.00,
        "liabilities": 800.00,  # positive magnitude owed on the credit account
        "net": 67700.00,
    },
    # include_credit=False drops the credit account from liabilities entirely.
    "net_worth_excluding_credit": {
        "assets": 68500.00,
        "liabilities": 0.00,
        "net": 68500.00,
    },
    # show_liabilities=False reports liabilities but does not subtract them.
    "net_worth_hiding_liabilities": {
        "assets": 68500.00,
        "liabilities": 800.00,
        "net": 68500.00,
    },
    "counts": {
        "accounts": 6,
        "transactions": 5,
        "receipts": 2,
        "line_items": 3,
        "goals": 1,
        "debts": 1,
        "receivables": 1,
        "budget_plans": 1,
        "templates": 1,
        "recurring": 1,
        "installment_plans": 1,
    },
    # The receipt reserved for posting tests (E2E-PST / W2-E). Not yet posted by
    # the seeder, so `post_receipt_as_expense` starts from a clean state.
    "postable_receipt": {
        "vendor_name": "SM Supermarket",
        "total_amount": 1500.00,
        "receipt_date": "2026-06-10",
    },
}


def build(db_path: Path | str = FIXTURE_PATH) -> dict:
    """Build the fixture database at `db_path` and return `EXPECTED`.

    Deletes and recreates the file, so the result never depends on prior runs.
    """
    db_path = Path(db_path).resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    os.environ["LEDGER_DB_PATH"] = str(db_path)

    # Rebuild from scratch. Done before importing core so no connection is open.
    for suffix in ("", "-journal", "-wal", "-shm"):
        p = Path(str(db_path) + suffix)
        if p.exists():
            p.unlink()

    import core
    import finance

    # Guard against the import-order trap documented in the module docstring. If
    # `core` was imported earlier with a different LEDGER_DB_PATH, its DB_PATH is
    # already bound and we would seed the wrong database.
    if Path(core.DB_PATH).resolve() != db_path:
        raise RuntimeError(
            f"core.DB_PATH is {core.DB_PATH!r}, expected {str(db_path)!r}. "
            "`core` was imported before LEDGER_DB_PATH was set; seeding would write "
            "to the wrong database. Set LEDGER_DB_PATH before importing core."
        )

    core.init_db()
    finance.init_finance_schema()

    # ---------------- Accounts ---------------------------------------------- #
    # (name, type, opening_balance, currency, include_in_totals, archived)
    accounts = {}
    for name, atype, opening in [
        ("Cash", "debit", 5000.00),
        ("BPI Checking", "debit", 20000.00),
        ("Credit Card", "credit", 0.00),
        ("Emergency Fund", "assets", 15000.00),
        ("Archived Wallet", "debit", 999.00),
        ("Excluded Pocket", "debit", 500.00),
    ]:
        accounts[name] = finance.create_account(name, atype, opening, "PHP")

    # Boundary cases for net worth: archived accounts and include_in_totals=0 must
    # both be excluded from the totals but keep their own balance.
    finance.update_account(accounts["Archived Wallet"], {"archived": 1})
    finance.update_account(accounts["Excluded Pocket"], {"include_in_totals": 0})

    # ---------------- Categories (seeded by init_finance_schema) ------------- #
    cats = {c["name"]: c["id"] for c in finance.list_categories()}

    # ---------------- Transactions ------------------------------------------ #
    finance.create_transaction(
        "expense", 250.00, account_id=accounts["Cash"],
        category_id=cats["Food"], note="Jollibee lunch", occurred_at="2026-06-01",
    )
    finance.create_transaction(
        "expense", 1200.00, account_id=accounts["BPI Checking"],
        category_id=cats["Bills"], note="Meralco", occurred_at="2026-06-02",
    )
    # Expense on a credit account is allowed (PRD §22); income/transfer are not.
    finance.create_transaction(
        "expense", 800.00, account_id=accounts["Credit Card"],
        category_id=cats["Shopping"], note="Uniqlo", occurred_at="2026-06-03",
    )
    finance.create_transaction(
        "income", 30000.00, account_id=accounts["BPI Checking"],
        category_id=cats["Salary"], note="June salary", occurred_at="2026-06-05",
    )
    # Transfer carries a fee, which is debited from the source only.
    finance.create_transaction(
        "transfer", 5000.00, account_id=accounts["BPI Checking"],
        to_account_id=accounts["Cash"], fee=50.00,
        note="ATM withdrawal", occurred_at="2026-06-06",
    )

    # ---------------- Plans, goals, debts, receivables ----------------------- #
    finance.create_budget_plan(cats["Food"], type="fixed", interval="monthly",
                               limit_amount=3000.00)
    finance.create_template("Morning coffee", 150.00, "expense",
                            accounts["Cash"], cats["Food"])
    # Signature is (kind, amount, name, account_id, next_due, category_id).
    # next_due is passed explicitly: omitting it defaults to date.today(), which
    # would make the fixture non-deterministic.
    finance.create_recurring("expense", 549.00, "Streaming subscription",
                             accounts["BPI Checking"], "2026-07-01",
                             category_id=cats["Entertainment"])
    finance.create_installment("Laptop", 60000.00, 5000.00, 12)
    finance.create_goal("Japan Trip", 100000.00, 10000.00, "PHP", "2027-03-01")
    finance.create_debt("Student Loan", 50000.00, 10000.00, "PHP", "2027-01-15")
    finance.create_receivable("Loan to Ana", 3000.00, 1000.00, "PHP", "2026-09-01")

    # ---------------- Receipts ----------------------------------------------- #
    # index=False keeps this offline: no embedding call, so no Ollama dependency.
    posted = core.ReceiptData(
        vendor_name="SM Supermarket",
        receipt_date="2026-06-10",
        subtotal=1339.29,
        vat_amount=160.71,
        total_amount=1500.00,
        currency="PHP",
        items=[
            core.LineItem(description="Rice 5kg", quantity=1, unit_price=350.00,
                          amount=350.00),
            core.LineItem(description="Cooking oil 1L", quantity=2, unit_price=175.00,
                          amount=350.00),
            core.LineItem(description="Chicken 1kg", quantity=1, unit_price=800.00,
                          amount=800.00),
        ],
    )
    core.save_receipt(posted, "fixture_sm_supermarket.jpg", flagged=False, index=False)

    # A second receipt flagged for review, so review-path tests have a subject.
    flagged = core.ReceiptData(
        vendor_name="7-Eleven",
        receipt_date="2026-06-11",
        total_amount=85.00,
        currency="PHP",
        items=[],
    )
    core.save_receipt(flagged, "fixture_7eleven.jpg", flagged=True, index=False)

    return EXPECTED


def verify(db_path: Path | str = FIXTURE_PATH) -> list[str]:
    """Re-open the built fixture and check it against EXPECTED.

    Returns a list of mismatch strings; empty means the fixture matches its own
    answer key. This is a self-check on the seeder, not an evaluation of Snag.
    """
    import finance

    problems: list[str] = []
    by_name = {a["name"]: a for a in finance.list_accounts(include_archived=True)}

    for name, expected_balance in EXPECTED["balances"].items():
        if name not in by_name:
            problems.append(f"account {name!r} missing")
            continue
        actual = finance.account_balance(by_name[name]["id"])
        if abs(actual - expected_balance) > 0.005:
            problems.append(f"balance {name}: expected {expected_balance}, got {actual}")

    checks = [
        ("net_worth", finance.net_worth()),
        ("net_worth_excluding_credit", finance.net_worth(include_credit=False)),
        ("net_worth_hiding_liabilities", finance.net_worth(show_liabilities=False)),
    ]
    for key, actual in checks:
        for field, expected_value in EXPECTED[key].items():
            if abs(actual[field] - expected_value) > 0.005:
                problems.append(
                    f"{key}.{field}: expected {expected_value}, got {actual[field]}"
                )

    return problems


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else FIXTURE_PATH
    build(target)
    problems = verify(target)
    if problems:
        print(f"FIXTURE MISMATCH ({len(problems)}):")
        for p in problems:
            print("  -", p)
        return 1
    print(f"Fixture built and verified: {target}")
    print(f"  accounts     {EXPECTED['counts']['accounts']}")
    print(f"  transactions {EXPECTED['counts']['transactions']}")
    print(f"  receipts     {EXPECTED['counts']['receipts']}")
    print(f"  net worth    {EXPECTED['net_worth']['net']:,.2f} "
          f"(assets {EXPECTED['net_worth']['assets']:,.2f} / "
          f"liabilities {EXPECTED['net_worth']['liabilities']:,.2f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
