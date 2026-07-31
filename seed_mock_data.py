"""
seed_mock_data.py — additive, reversible demo data for the app's real ledger.

Why this exists
---------------
Testing the app by hand needs a populated ledger: accounts with balances, a few
months of transactions so the cashflow chart has bars, budgets that are partly
spent, goals/debts/receivables with activity, and receipts for the OCR views.
Typing that in through the UI every time is the bottleneck this removes.

How it differs from `evaluation/fixtures/seed_finance.py`
--------------------------------------------------------
That script builds a *frozen, disposable* fixture DB for the evaluation suite —
it deletes its output file and rebuilds from scratch. This script writes to the
*live* `ledger.db`, so it is strictly additive:

* It never drops, truncates, or rebuilds a table. Schema creation goes through
  the app's own idempotent `init_finance_schema()` / `init_db()`.
* Preexisting records are never touched. An account whose name already exists is
  reused, not duplicated, and is *not* recorded as ours — so `--purge` leaves it
  alone.
* Every row it inserts is recorded by id in a `settings` marker row
  (`mock_seed`). `--purge` deletes exactly those ids and nothing else, which is
  what makes the seed reversible without risking real data.
* Re-running without `--reseed` is a no-op: the marker is detected and the script
  exits without writing.

Data set
--------
Philippine accounts and merchants, PHP throughout: BDO, BPI, UnionBank and a
GCash wallet, plus a BDO Mastercard (credit) and a BPI Auto Loan (liability) so
the credit / net-worth paths have something to show.

Note the app has two aggregation paths and this seeds both, deliberately:
`analytics_summary()` (dashboard, statistics) reads expenses from `receipts` and
income from the `income` table, while the wallet/budget pages read the
`transactions` ledger. They are separate views, not double counting.

Usage
-----
    python seed_mock_data.py                   # seed ledger.db
    python seed_mock_data.py --status          # what is seeded, if anything
    python seed_mock_data.py --purge           # remove only seeded rows
    python seed_mock_data.py --reseed          # purge, then seed again
    python seed_mock_data.py --db path/to.db   # target another database
    python seed_mock_data.py --anchor 2026-07-30   # pin dates (default: today)

Dates are anchored to today by default so the current-period views have data.
Pass `--anchor` for a reproducible run.

IMPORTANT — import order
------------------------
`core.DB_PATH` is read from `LEDGER_DB_PATH` at import time and `core._connect()`
binds it as a default argument, so `--db` must be applied to the environment
before `core` is first imported. `main()` does that; the module-level code here
imports nothing from the app.
"""

from __future__ import annotations

import argparse
import calendar
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent

# Bound late by _load_app_modules(), after LEDGER_DB_PATH is settled.
core = None
finance = None

# --------------------------------------------------------------------------- #
# Marker — the record of what this script created.
#
# Stored as JSON in settings['mock_seed']. Purge trusts nothing else: a row is
# only ever deleted if its id appears here. Bump SEED_VERSION when the data set
# below changes so `--status` can flag a stale seed.
# --------------------------------------------------------------------------- #
MARKER_KEY = "mock_seed"
SEED_VERSION = 1

# Tables purged by id, in FK-safe order: transactions reference accounts,
# receipts, and the plan entities, so they go first; accounts go last.
# Receipts, budgets and settings are keyed differently and handled separately.
_PURGE_BY_ID = (
    "transactions",
    "budget_plans",
    "templates",
    "recurring",
    "installment_plans",
    "goals",
    "debts",
    "receivables",
    "tags",
    "income",
    "accounts",
)

# --------------------------------------------------------------------------- #
# The data set. Literals only — amounts are hand-picked so balances stay
# plausible (no debit account is driven negative) and every category on the
# dashboard has spend. Dates are (months_back, day_of_month) pairs resolved
# against the anchor; see _day().
# --------------------------------------------------------------------------- #
CURRENCY = "PHP"

# key -> (display name, account type, opening balance)
ACCOUNTS = {
    "bdo":   ("BDO Savings",        "debit",  95000.0),
    "bpi":   ("BPI Checking",       "debit",  28500.0),
    "ub":    ("UnionBank Personal", "debit",  12000.0),
    "gcash": ("GCash Wallet",       "debit",   2500.0),
    # Negative balance on a liability account means money owed (see finance._balances).
    # The card carries a running balance from the expenses posted to it below; the
    # auto loan carries its remaining principal.
    "mc":    ("BDO Mastercard",     "credit",      0.0),
    "loan":  ("BPI Auto Loan",      "loans",  -85000.0),
}

# (months_back, day, account key, category name, amount, note)
INCOME_TXNS = [
    (2, 15, "bdo",   "Salary",   32000.0, "Payroll — ACME Corp (BDO payroll)"),
    (1, 15, "bdo",   "Salary",   32000.0, "Payroll — ACME Corp (BDO payroll)"),
    (0, 15, "bdo",   "Salary",   32000.0, "Payroll — ACME Corp (BDO payroll)"),
    (1, 22, "ub",    "Business",  8500.0, "Freelance web design — client deposit"),
    (0, 20, "ub",    "Business",  6000.0, "Freelance retainer — client deposit"),
    (0,  8, "gcash", "Gift",      1000.0, "Gift from Ninang (GCash transfer)"),
]

# (months_back, day, account key, category name, amount, note)
EXPENSE_TXNS = [
    # ---- two months back ----
    (2,  3, "bpi",   "Bills",         2840.55, "Meralco electricity bill"),
    (2,  5, "bdo",   "Groceries",     3420.00, "SM Supermarket — weekly groceries"),
    (2,  9, "gcash", "Food",           185.00, "Jollibee — Chickenjoy solo"),
    (2, 12, "bdo",   "Transport",     1200.00, "Petron — fuel"),
    (2, 16, "mc",    "Shopping",      2450.00, "Shopee — household items"),
    (2, 19, "gcash", "Transport",      240.00, "Grab — ride to office"),
    (2, 23, "bdo",   "Health",        1180.00, "Mercury Drug — maintenance meds"),
    (2, 26, "bpi",   "Bills",         1499.00, "Globe Postpaid — monthly plan"),
    (2, 28, "bdo",   "Entertainment",  549.00, "Netflix — standard plan"),
    # ---- last month ----
    (1,  2, "bpi",   "Bills",         2610.40, "Meralco electricity bill"),
    (1,  4, "bpi",   "Bills",          648.00, "Maynilad water bill"),
    (1,  6, "bdo",   "Groceries",     4180.75, "Puregold — monthly stock-up"),
    (1,  8, "gcash", "Food",           320.00, "Mang Inasal — family meal"),
    (1, 11, "bdo",   "Transport",     1350.00, "Shell — fuel"),
    (1, 13, "gcash", "Transport",      150.00, "Beep card load — MRT"),
    (1, 14, "mc",    "Shopping",      3890.00, "Lazada — desk chair"),
    (1, 17, "bdo",   "Food",          1240.00, "Vikings Buffet — birthday dinner"),
    (1, 21, "bdo",   "Health",         820.00, "Watsons — vitamins"),
    (1, 24, "gcash", "Entertainment",  194.00, "Spotify Premium"),
    (1, 25, "bpi",   "Bills",         1499.00, "Globe Postpaid — monthly plan"),
    (1, 27, "bdo",   "Other",          950.00, "National Book Store — school supplies"),
    (1, 29, "mc",    "Entertainment", 1850.00, "Cinema + dinner — mall date"),
    # ---- current month ----
    (0,  2, "bpi",   "Bills",         2975.20, "Meralco electricity bill"),
    (0,  3, "bpi",   "Bills",          672.50, "Maynilad water bill"),
    (0,  5, "bdo",   "Groceries",     3960.00, "SM Supermarket — weekly groceries"),
    (0,  6, "gcash", "Food",           215.00, "7-Eleven — snacks and coffee"),
    (0,  7, "gcash", "Transport",      280.00, "Angkas — ride home"),
    (0,  9, "bdo",   "Transport",     1420.00, "Petron — fuel"),
    (0, 11, "mc",    "Shopping",      4250.00, "Uniqlo — work clothes"),
    (0, 12, "gcash", "Food",           390.00, "Chowking — lunch with team"),
    (0, 14, "bdo",   "Health",        2350.00, "Healthway Clinic — annual check-up"),
    (0, 16, "bdo",   "Food",           680.00, "Starbucks — coffee runs"),
    (0, 18, "bpi",   "Bills",         1499.00, "Globe Postpaid — monthly plan"),
    (0, 19, "gcash", "Entertainment",  549.00, "Netflix — standard plan"),
    (0, 21, "bdo",   "Other",         1100.00, "Barangay clearance + notary fees"),
    (0, 23, "gcash", "Groceries",      845.00, "Ministop — top-up groceries"),
]

# (months_back, day, from key, to key, amount, fee, note)
# The monthly BDO -> BPI transfer is the bills/loan allotment: BPI Checking is
# where the utilities and the auto-loan amortization are paid from, so it has to
# be funded each month or its balance would run negative.
TRANSFER_TXNS = [
    (2, 16, "bdo", "bpi",   10000.0, 25.0, "Monthly allotment — bills + tuition"),
    (2, 20, "bdo", "gcash",  2500.0,  0.0, "Cash-in to GCash (BDO app, free)"),
    (1, 10, "bpi", "ub",     5000.0, 25.0, "InstaPay — BPI to UnionBank savings"),
    (1, 16, "bdo", "bpi",   10000.0, 25.0, "Monthly allotment — bills + tuition"),
    (1, 18, "bdo", "gcash",  3000.0,  0.0, "Cash-in to GCash (BDO app, free)"),
    (0, 10, "bdo", "gcash",  2000.0, 15.0, "Cash-in to GCash (InstaPay fee)"),
    (0, 16, "bdo", "bpi",   10000.0, 25.0, "Monthly allotment — bills + tuition"),
    (0, 17, "bdo", "ub",     4000.0, 25.0, "InstaPay — BDO to UnionBank savings"),
]

# Dashboard income (core.income table). The recurring row is expanded across
# months at aggregation time, so one row covers the salary series.
# (source, amount, months_back, day, recurring)
INCOME_ROWS = [
    ("Payroll — ACME Corp (BDO)",        32000.0, 2, 15, True),
    ("Freelance web design (UnionBank)",  8500.0, 1, 22, False),
    ("Freelance retainer (UnionBank)",    6000.0, 0, 20, False),
    ("Gift from Ninang (GCash)",          1000.0, 0,  8, False),
]

# Dashboard budgets (core.budgets — keyed by the receipt category taxonomy,
# core.VALID_CATEGORIES). (category, monthly limit)
RECEIPT_BUDGETS = [
    ("Food",     8000.0),
    ("Shopping", 6000.0),
    ("Health",   4000.0),
    ("Other",    3000.0),
]

# Wallet budget plans (finance.budget_plans — keyed by the richer category set).
# (category name, type, interval, limit_amount, percent, carry_forward)
BUDGET_PLANS = [
    ("Food",          "fixed",   "monthly", 6000.0,  0.0, False),
    ("Groceries",     "fixed",   "monthly", 9000.0,  0.0, True),
    ("Bills",         "fixed",   "monthly", 7000.0,  0.0, False),
    ("Transport",     "fixed",   "monthly", 3500.0,  0.0, False),
    ("Shopping",      "fixed",   "monthly", 5000.0,  0.0, True),
    ("Entertainment", "percent", "monthly",    0.0,  5.0, False),
    ("Health",        "fixed",   "yearly", 40000.0,  0.0, False),
]

# (title, target amount, target date months ahead, [(months_back, day, account, amount)])
GOALS = [
    ("Emergency Fund (3 months)", 150000.0, 12,
     [(2, 16, "bdo", 8000.0), (1, 16, "bdo", 8000.0), (0, 16, "bdo", 8000.0)]),
    ("Japan trip 2027", 120000.0, 10,
     [(1, 23, "ub", 5000.0), (0, 21, "ub", 5000.0)]),
    ("New laptop", 65000.0, 5,
     [(2, 25, "bdo", 6000.0), (1, 25, "bdo", 6000.0)]),
]

# (name, total owed, due months ahead, [(months_back, day, account, amount)] payments)
# Each obligation is represented exactly once across the app. The auto loan is the
# `loans` account above, the iPhone is an installment plan below, and the card is a
# credit account — so none of them appear here. Listing an obligation in two
# subsystems would double-count both the balance owed and every payment.
DEBTS = [
    ("SSS salary loan", 24000.0, 8,
     [(1, 20, "bdo", 2000.0), (0, 20, "bdo", 2000.0)]),
    ("Personal loan from Kuya Jun", 15000.0, 3,
     [(1, 28, "bdo", 5000.0)]),
    ("Tuition balance — St. Scholastica", 18000.0, 4,
     [(2, 10, "bpi", 6000.0), (1, 10, "bpi", 6000.0)]),
]

# (name, total lent, due months ahead, [(months_back, day, account, amount)] collections)
RECEIVABLES = [
    ("Ana (officemate) — lunch fund", 2500.0, 1,
     [(0, 22, "gcash", 1000.0)]),
    ("Sister — GCash padala advance", 5000.0, 2,
     [(1, 26, "gcash", 2000.0)]),
]

# (kind, amount, name, account key, category, next due months ahead, day)
RECURRING = [
    ("expense", 2900.00, "Meralco electricity",   "bpi",   "Bills",         1,  2),
    ("expense",  650.00, "Maynilad water",        "bpi",   "Bills",         1,  4),
    ("expense", 1499.00, "Globe Postpaid plan",   "bpi",   "Bills",         1, 18),
    ("expense",  549.00, "Netflix subscription",  "gcash", "Entertainment", 1, 19),
    ("expense",  194.00, "Spotify Premium",       "gcash", "Entertainment", 1, 24),
    ("income", 32000.00, "Payroll — ACME Corp",   "bdo",   "Salary",        1, 15),
]

# (title, amount, kind, account key, category)
TEMPLATES = [
    ("Jollibee lunch",      185.0, "expense", "gcash", "Food"),
    ("Grab to office",      240.0, "expense", "gcash", "Transport"),
    ("SM Supermarket run", 3500.0, "expense", "bdo",   "Groceries"),
    ("Meralco bill",       2900.0, "expense", "bpi",   "Bills"),
    ("Monthly payroll",   32000.0, "income",  "bdo",   "Salary"),
]

# (title, total, monthly, months, [(months_back, day, account, amount)] payments)
INSTALLMENTS = [
    ("iPhone 16 — Home Credit 12 mo", 42000.0, 3500.0, 12,
     [(1, 12, "gcash", 3500.0), (0, 12, "gcash", 3500.0)]),
    ("Laptop — BPI 0% 6 mo", 65000.0, 10833.33, 6,
     [(0, 6, "bpi", 10833.33)]),
]

TAGS = [
    ("Work",         "Custom", "#0EA5E9"),
    ("Family",       "Custom", "#F97316"),
    ("Reimbursable", "Custom", "#22C55E"),
    ("Vacation",     "Custom", "#A855F7"),
    ("Emergency",    "Custom", "#EF4444"),
]

# Receipts for the OCR views. `category` must be one of core.VALID_CATEGORIES.
# `post_to` posts the receipt into the transactions ledger as a linked expense
# (finance.post_receipt_as_expense); None leaves it unposted, which is the
# realistic "extracted but not yet filed" state.
RECEIPTS = [
    {
        "vendor": "SM Supermarket — Manila", "tin": "000-123-456-00001",
        "address": "SM City Manila, Concepcion St, Ermita, Manila",
        "number": "OR-884213", "months_back": 2, "day": 5, "category": "Food",
        "post_to": "bdo", "flagged": False, "confidence": 0.96,
        "items": [
            ("Sinandomeng Rice 5kg",      1, 320.00),
            ("Magnolia Fresh Eggs (dz)",  2,  98.00),
            ("Del Monte Spaghetti Sauce", 3,  62.50),
            ("Alaska Evap Milk 370ml",    4,  38.75),
            ("Purefoods Hotdog 1kg",      1, 285.00),
        ],
    },
    {
        "vendor": "Jollibee — Taft Avenue", "tin": "000-456-789-00002",
        "address": "2452 Taft Ave, Malate, Manila",
        "number": "OR-102934", "months_back": 2, "day": 9, "category": "Food",
        "post_to": "gcash", "flagged": False, "confidence": 0.94,
        "items": [
            ("Chickenjoy 1pc w/ Rice", 1, 105.00),
            ("Jolly Spaghetti",        1,  62.00),
            ("Regular Fries",          1,  45.00),
        ],
    },
    {
        "vendor": "Mercury Drug — Quiapo", "tin": "000-789-123-00003",
        "address": "Quezon Blvd cor Carriedo St, Quiapo, Manila",
        "number": "OR-556201", "months_back": 2, "day": 23, "category": "Health",
        "post_to": "bdo", "flagged": False, "confidence": 0.92,
        "items": [
            ("Losartan 50mg (30 tabs)",  2, 385.00),
            ("Biogesic 500mg (20 tabs)", 1, 112.00),
            ("Alcohol 70% 500ml",        1, 118.00),
        ],
    },
    {
        "vendor": "Ace Hardware — SM Manila", "tin": "000-321-654-00010",
        "address": "SM City Manila, Ermita, Manila",
        "number": "OR-118742", "months_back": 2, "day": 16, "category": "Shopping",
        "post_to": "mc", "flagged": False, "confidence": 0.93,
        "items": [
            ("Extension Cord 3m",     1, 385.00),
            ("LED Bulb 9W (2 pack)",  2, 249.00),
            ("Screwdriver Set",       1, 320.00),
        ],
    },
    {
        "vendor": "SM Bills Payment Center", "tin": "000-123-456-00011",
        "address": "SM City Manila, Ermita, Manila",
        "number": "OR-905517", "months_back": 2, "day": 3, "category": "Other",
        "post_to": None, "flagged": False, "confidence": 0.87,
        "items": [
            ("Meralco bill payment — service fee", 1, 20.00),
            ("Maynilad bill payment — service fee", 1, 20.00),
        ],
    },
    {
        "vendor": "Puregold Price Club", "tin": "000-234-567-00004",
        "address": "Aurora Blvd, Cubao, Quezon City",
        "number": "OR-773410", "months_back": 1, "day": 6, "category": "Food",
        "post_to": "bdo", "flagged": False, "confidence": 0.95,
        "items": [
            ("Nescafe Classic 100g",      2, 168.00),
            ("Century Tuna Flakes 180g",  6,  42.25),
            ("Lucky Me Pancit Canton",   10,  14.50),
            ("Tide Powder 1.2kg",         1, 265.00),
            ("Coke 1.5L",                 3,  78.00),
        ],
    },
    {
        "vendor": "Lazada Philippines", "tin": "000-345-678-00005",
        "address": "Bonifacio Global City, Taguig",
        "number": "INV-2026-44812", "months_back": 1, "day": 14, "category": "Shopping",
        "post_to": "mc", "flagged": False, "confidence": 0.90,
        "items": [
            ("Ergonomic Desk Chair", 1, 3450.00),
            ("Monitor Riser Stand",  1,  440.00),
        ],
    },
    {
        "vendor": "Watsons — Robinsons Place", "tin": "000-567-890-00006",
        "address": "Robinsons Place Manila, Pedro Gil, Ermita",
        "number": "OR-231118", "months_back": 1, "day": 21, "category": "Health",
        "post_to": None, "flagged": False, "confidence": 0.93,
        "items": [
            ("Centrum Adults (30 tabs)", 1, 512.00),
            ("Vitamin C 500mg (100)",    1, 288.00),
        ],
    },
    {
        "vendor": "National Book Store", "tin": "000-678-901-00007",
        "address": "SM North EDSA, Quezon City",
        "number": "OR-990122", "months_back": 1, "day": 27, "category": "Other",
        "post_to": "bdo", "flagged": False, "confidence": 0.91,
        "items": [
            ("Intermediate Pad (10)",  2, 175.00),
            ("Ballpen Black (box)",    1, 240.00),
            ("Notebook Spiral A5",     3,  85.00),
        ],
    },
    {
        "vendor": "7-Eleven — Malate", "tin": "000-890-123-00008",
        "address": "1234 Adriatico St, Malate, Manila",
        "number": "OR-448190", "months_back": 0, "day": 6, "category": "Food",
        "post_to": "gcash", "flagged": False, "confidence": 0.89,
        "items": [
            ("City Blends Coffee 12oz", 2,  55.00),
            ("Siomai Rice",             1,  79.00),
            ("Bottled Water 500ml",     1,  25.00),
        ],
    },
    {
        "vendor": "Uniqlo — Mall of Asia", "tin": "000-901-234-00009",
        "address": "SM Mall of Asia, Pasay City",
        "number": "OR-661204", "months_back": 0, "day": 11, "category": "Shopping",
        "post_to": "mc", "flagged": False, "confidence": 0.88,
        "items": [
            ("Airism Polo Shirt",  2, 990.00),
            ("Smart Ankle Pants",  2, 1290.00),
        ],
    },
    {
        "vendor": "Mercury Drug — Ermita", "tin": "000-789-123-00012",
        "address": "M.H. del Pilar St, Ermita, Manila",
        "number": "OR-563318", "months_back": 0, "day": 14, "category": "Health",
        "post_to": "bdo", "flagged": False, "confidence": 0.94,
        "items": [
            ("Annual check-up lab package", 1, 1850.00),
            ("Cetirizine 10mg (10 tabs)",   1,  148.00),
            ("Band-Aid assorted",           1,   95.00),
        ],
    },
    {
        "vendor": "SM Supermarket — Ermita", "tin": "000-123-456-00013",
        "address": "SM City Manila, Concepcion St, Ermita, Manila",
        "number": "OR-889902", "months_back": 0, "day": 24, "category": "Food",
        "post_to": "bdo", "flagged": False, "confidence": 0.95,
        "items": [
            ("Sinandomeng Rice 5kg",     1, 335.00),
            ("Bangus (per kg)",          2, 220.00),
            ("Baguio Beans (per kg)",    1, 145.00),
            ("Nestle Fresh Milk 1L",     2, 118.00),
            ("Bear Brand Powdered 900g", 1, 452.00),
        ],
    },
    {
        # Deliberately low confidence + flagged: exercises the review/flagged UI.
        "vendor": "Sari-sari Store (handwritten)", "tin": None,
        "address": "Blk 7 Lot 12, Barangay 720, Manila",
        "number": None, "months_back": 0, "day": 20, "category": "Other",
        "post_to": None, "flagged": True, "confidence": 0.41,
        "items": [
            ("Load — Globe", 1, 100.00),
            ("Ice, 2 bags",  2,  25.00),
        ],
    },
]


# --------------------------------------------------------------------------- #
# Bootstrap
# --------------------------------------------------------------------------- #
def _load_app_modules() -> None:
    """Import core + finance after LEDGER_DB_PATH is settled (see module docstring)."""
    global core, finance
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    import core as _core
    import finance as _finance
    core, finance = _core, _finance


# --------------------------------------------------------------------------- #
# Date helpers
# --------------------------------------------------------------------------- #
def _day(anchor: date, months_back: int, day: int) -> str:
    """Resolve a (months_back, day) pair to an ISO date relative to `anchor`.

    The day is clamped to the target month's length, and — for the current month
    only — to the anchor's own day, so a seeded "current month" row can never be
    dated in the future (which would drop it out of period-to-date views).
    """
    year, month = anchor.year, anchor.month
    month -= months_back
    while month < 1:
        month += 12
        year -= 1
    day = min(day, calendar.monthrange(year, month)[1])
    if months_back == 0:
        day = min(day, anchor.day)
    return f"{year:04d}-{month:02d}-{day:02d}"


def _months_ahead(anchor: date, months: int, day: int | None = None) -> str:
    year, month = anchor.year, anchor.month + months
    year += (month - 1) // 12
    month = (month - 1) % 12 + 1
    d = min(day or anchor.day, calendar.monthrange(year, month)[1])
    return f"{year:04d}-{month:02d}-{d:02d}"


# --------------------------------------------------------------------------- #
# Marker read/write
# --------------------------------------------------------------------------- #
def read_marker() -> dict | None:
    marker = finance.get_settings().get(MARKER_KEY)
    if not marker:
        return None
    try:
        return json.loads(marker)
    except (TypeError, ValueError):
        # A corrupt marker must not license a blind purge — surface it instead.
        raise SystemExit(
            f"settings['{MARKER_KEY}'] is not valid JSON. Inspect it manually; "
            "refusing to guess which rows are mock data."
        )


def write_marker(marker: dict) -> None:
    finance.set_settings({MARKER_KEY: json.dumps(marker)})


def _new_marker(anchor: date) -> dict:
    return {
        "version": SEED_VERSION,
        "seeded_at": datetime.now(timezone.utc).replace(tzinfo=None)
                             .isoformat(timespec="seconds"),
        "anchor": anchor.isoformat(),
        "created": {t: [] for t in _PURGE_BY_ID},
        # Non-id-keyed inserts, tracked so purge can be equally precise.
        "created_receipts": [],
        "created_budgets": [],
        "created_settings": [],
        "reused_accounts": {},  # name -> id for accounts that already existed
    }


# --------------------------------------------------------------------------- #
# Lookup helpers — reuse, never duplicate
# --------------------------------------------------------------------------- #
def _category_ids() -> dict[str, int]:
    """Category name -> id. Categories are seeded by init_finance_schema(); this
    only reads them, so a user's renamed/custom categories are respected."""
    return {c["name"]: c["id"] for c in finance.list_categories()}


def _ensure_accounts(marker: dict) -> dict[str, int]:
    """Create the demo accounts, reusing any that already exist by name.

    A reused account is recorded under `reused_accounts` rather than `created`,
    so `--purge` will not delete an account the user made themselves.
    """
    existing = {a["name"]: a["id"] for a in finance.list_accounts(include_archived=True)}
    ids: dict[str, int] = {}
    for key, (name, atype, opening) in ACCOUNTS.items():
        if name in existing:
            ids[key] = existing[name]
            marker["reused_accounts"][name] = existing[name]
            print(f"  · account already exists, reusing: {name} (id {existing[name]})")
            continue
        aid = finance.create_account(name, atype, opening_balance=opening,
                                    currency=CURRENCY, include_in_totals=True)
        marker["created"]["accounts"].append(aid)
        ids[key] = aid
    return ids


# --------------------------------------------------------------------------- #
# Seed
# --------------------------------------------------------------------------- #
def seed(anchor: date) -> dict:
    """Insert the demo data set. Additive: nothing preexisting is modified or
    removed. Returns the marker describing exactly what was created."""
    finance.init_finance_schema()  # idempotent; creates tables + default categories
    core.init_db()

    marker = _new_marker(anchor)
    cats = _category_ids()

    def cat(name: str) -> int | None:
        cid = cats.get(name)
        if cid is None:
            print(f"  ! category {name!r} not found; row will be uncategorized")
        return cid

    print("Accounts")
    acct = _ensure_accounts(marker)

    print("Transactions")
    for months_back, day, key, category, amount, note in INCOME_TXNS:
        tid = finance.create_transaction(
            "income", amount, account_id=acct[key], category_id=cat(category),
            note=note, occurred_at=_day(anchor, months_back, day),
        )
        marker["created"]["transactions"].append(tid)

    for months_back, day, key, category, amount, note in EXPENSE_TXNS:
        tid = finance.create_transaction(
            "expense", amount, account_id=acct[key], category_id=cat(category),
            note=note, occurred_at=_day(anchor, months_back, day),
        )
        marker["created"]["transactions"].append(tid)

    for months_back, day, src, dst, amount, fee, note in TRANSFER_TXNS:
        tid = finance.create_transaction(
            "transfer", amount, account_id=acct[src], to_account_id=acct[dst],
            note=note, occurred_at=_day(anchor, months_back, day), fee=fee,
        )
        marker["created"]["transactions"].append(tid)

    print("Income (dashboard)")
    for source, amount, months_back, day, recurring in INCOME_ROWS:
        iid = core.add_income(source, amount, CURRENCY,
                              _day(anchor, months_back, day), recurring)
        marker["created"]["income"].append(iid)

    print("Budgets")
    existing_budgets = {b["category"] for b in core.list_budgets()}
    for category, limit in RECEIPT_BUDGETS:
        if category in existing_budgets:
            print(f"  · budget for {category} already set, leaving as is")
            continue
        core.set_budget(category, limit, CURRENCY)
        marker["created_budgets"].append(category)

    for category, ptype, interval, limit_amount, percent, carry in BUDGET_PLANS:
        cid = cat(category)
        if cid is None:
            continue
        pid = finance.create_budget_plan(cid, type=ptype, interval=interval,
                                        limit_amount=limit_amount, percent=percent,
                                        carry_forward=carry)
        marker["created"]["budget_plans"].append(pid)

    print("Goals")
    for title, target, months_ahead, deposits in GOALS:
        # current_amount starts at 0 and is driven up by the deposits below, so the
        # goal total and its activity rows agree.
        gid = finance.create_goal(title, target, 0.0, CURRENCY,
                                  _months_ahead(anchor, months_ahead, 15))
        marker["created"]["goals"].append(gid)
        for months_back, day, key, amount in deposits:
            tid = finance.goal_activity(gid, acct[key], amount, "deposit",
                                       _day(anchor, months_back, day))
            marker["created"]["transactions"].append(tid)

    print("Debts")
    for name, total, months_ahead, payments in DEBTS:
        did = finance.create_debt(name, total, 0.0, CURRENCY,
                                  _months_ahead(anchor, months_ahead, 5))
        marker["created"]["debts"].append(did)
        for months_back, day, key, amount in payments:
            tid = finance.debt_activity(did, acct[key], amount, "payment",
                                        _day(anchor, months_back, day))
            marker["created"]["transactions"].append(tid)

    print("Receivables")
    for name, total, months_ahead, collections in RECEIVABLES:
        rid = finance.create_receivable(name, total, 0.0, CURRENCY,
                                        _months_ahead(anchor, months_ahead, 15))
        marker["created"]["receivables"].append(rid)
        for months_back, day, key, amount in collections:
            tid = finance.receivable_activity(rid, acct[key], amount, "collection",
                                              _day(anchor, months_back, day))
            marker["created"]["transactions"].append(tid)

    print("Recurring")
    for kind, amount, name, key, category, months_ahead, day in RECURRING:
        rid = finance.create_recurring(kind, amount, name, acct[key],
                                       _months_ahead(anchor, months_ahead, day),
                                       category_id=cat(category))
        marker["created"]["recurring"].append(rid)

    print("Templates")
    for title, amount, kind, key, category in TEMPLATES:
        tid = finance.create_template(title, amount, kind, acct[key],
                                      category_id=cat(category))
        marker["created"]["templates"].append(tid)

    print("Installments")
    for title, total, monthly, months, payments in INSTALLMENTS:
        pid = finance.create_installment(title, total, monthly, months)
        marker["created"]["installment_plans"].append(pid)
        for months_back, day, key, amount in payments:
            tid = finance.log_installment_payment(pid, acct[key], amount,
                                                  _day(anchor, months_back, day))
            marker["created"]["transactions"].append(tid)

    print("Tags")
    existing_tags = {t["name"] for t in finance.list_tags()}
    for name, kind, color in TAGS:
        if name in existing_tags:
            continue
        marker["created"]["tags"].append(finance.create_tag(name, kind, color))

    print("Receipts")
    for spec in RECEIPTS:
        rid = _save_receipt(spec, anchor)
        marker["created_receipts"].append(rid)
        if spec["post_to"]:
            tid = finance.post_receipt_as_expense(rid, acct[spec["post_to"]])
            marker["created"]["transactions"].append(tid)

    print("Settings")
    current = finance.get_settings()
    defaults = {"currency": CURRENCY, "profile_name": "Juan Dela Cruz"}
    to_set = {k: v for k, v in defaults.items() if k not in current}
    if to_set:
        finance.set_settings(to_set)
        marker["created_settings"].extend(to_set)

    write_marker(marker)
    return marker


def _save_receipt(spec: dict, anchor: date) -> int:
    """Build a ReceiptData from a literal spec and persist it.

    Totals are derived from the line items and the VAT split is computed
    VAT-inclusive at 12% (the PH rate), matching what a real BIR receipt shows,
    so downstream VAT math in the UI has something consistent to display.
    `index=False` skips the embedding call, keeping the seeder fully offline.
    """
    items = [
        core.LineItem(description=desc, quantity=float(qty), unit_price=unit,
                      amount=round(qty * unit, 2))
        for desc, qty, unit in spec["items"]
    ]
    total = round(sum(i.amount for i in items), 2)
    vatable = round(total / 1.12, 2)
    vat = round(total - vatable, 2)

    data = core.ReceiptData(
        vendor_name=spec["vendor"],
        vendor_tin=spec["tin"],
        vendor_address=spec["address"],
        receipt_number=spec["number"],
        receipt_date=_day(anchor, spec["months_back"], spec["day"]),
        items=items,
        subtotal=total,
        vatable_sales=vatable,
        vat_exempt_sales=0.0,
        zero_rated_sales=0.0,
        vat_amount=vat,
        discount=0.0,
        discount_type=None,
        total_amount=total,
        cash=float(int(total / 100) * 100 + 100),  # a plausible round cash tender
        change=round(float(int(total / 100) * 100 + 100) - total, 2),
        currency=CURRENCY,
        category=spec["category"],
    )
    overall = spec["confidence"]
    confidence = {
        "overall": overall,
        "fields": {
            "vendor_name": overall, "receipt_date": overall,
            "total_amount": overall, "vat_amount": round(max(overall - 0.05, 0.0), 2),
            "receipt_number": round(max(overall - 0.03, 0.0), 2),
        },
        "items": [{"description": overall, "amount": overall} for _ in items],
    }
    return core.save_receipt(
        data,
        source_file=f"mock/{spec['vendor'].split(' —')[0].lower().replace(' ', '_')}"
                    f"_{spec['months_back']}m{spec['day']:02d}.jpg",
        flagged=spec["flagged"],
        confidence=confidence,
        index=False,
    )


# --------------------------------------------------------------------------- #
# Purge — deletes only what the marker recorded
# --------------------------------------------------------------------------- #
def purge(marker: dict) -> dict[str, int]:
    """Delete exactly the rows listed in `marker`, in FK-safe order.

    Ids, not names or date ranges: a row the user created is never in the marker,
    so it cannot be reached from here. Rows the user already deleted by hand are
    simply absent and count as 0.
    """
    counts: dict[str, int] = {}

    # Receipts first (their linked transactions are removed with the ledger rows
    # below, and core.delete_receipt also clears line_items + receipt_docs).
    with core._connect() as con:
        for table in _PURGE_BY_ID:
            ids = [int(i) for i in marker.get("created", {}).get(table, [])]
            if not ids:
                continue
            if table == "accounts":
                continue  # deleted after the ledger rows, below
            ph = ",".join("?" for _ in ids)
            cur = con.execute(f"DELETE FROM {table} WHERE id IN ({ph})", ids)
            counts[table] = cur.rowcount
        con.commit()

    removed_receipts = 0
    for rid in marker.get("created_receipts", []):
        if core.delete_receipt(int(rid)):
            removed_receipts += 1
    if removed_receipts:
        counts["receipts"] = removed_receipts

    # Accounts last: finance.delete_account refuses while transactions reference
    # them, which is the safety net if a user added their own rows on a mock
    # account — that account is then left in place, with a note.
    kept = []
    removed_accounts = 0
    for aid in marker.get("created", {}).get("accounts", []):
        try:
            if finance.delete_account(int(aid)):
                removed_accounts += 1
        except finance.FinanceError:
            kept.append(int(aid))
    if removed_accounts:
        counts["accounts"] = removed_accounts
    for aid in kept:
        a = finance.get_account(aid)
        name = a["name"] if a else f"id {aid}"
        print(f"  · kept account {name}: it has transactions that are not mock data")

    budgets = marker.get("created_budgets", [])
    if budgets:
        with core._connect() as con:
            ph = ",".join("?" for _ in budgets)
            cur = con.execute(f"DELETE FROM budgets WHERE category IN ({ph})", budgets)
            counts["budgets"] = cur.rowcount
            con.commit()

    keys = list(marker.get("created_settings", [])) + [MARKER_KEY]
    with core._connect() as con:
        ph = ",".join("?" for _ in keys)
        con.execute(f"DELETE FROM settings WHERE key IN ({ph})", keys)
        con.commit()

    return counts


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
def _print_summary() -> None:
    nw = finance.net_worth()
    print("\nLedger now holds:")
    for a in finance.list_accounts():
        print(f"  {a['name']:<22} {a['type']:<7} {a['currency'] or '':<4}"
              f" {a['balance']:>12,.2f}")
    print(f"  {'':<22} {'assets':<7} {'':<4} {nw['assets']:>12,.2f}")
    print(f"  {'':<22} {'liabs':<7} {'':<4} {nw['liabilities']:>12,.2f}")
    print(f"  {'':<22} {'NET':<7} {'':<4} {nw['net']:>12,.2f}")

    with core._connect() as con:
        counts = {
            t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("transactions", "receipts", "line_items", "income", "budgets",
                      "budget_plans", "goals", "debts", "receivables", "recurring",
                      "templates", "installment_plans", "tags")
        }
    print("\nRow counts: " + ", ".join(f"{k}={v}" for k, v in counts.items()))


def _print_status(marker: dict | None) -> None:
    if marker is None:
        print("No mock data seeded (no settings['mock_seed'] marker).")
        return
    created = marker.get("created", {})
    total = sum(len(v) for v in created.values()) + len(marker.get("created_receipts", []))
    print(f"Mock data seeded: version {marker.get('version')}, "
          f"anchor {marker.get('anchor')}, at {marker.get('seeded_at')}Z")
    if marker.get("version") != SEED_VERSION:
        print(f"  ! marker version differs from this script's ({SEED_VERSION}); "
              "run --reseed to refresh")
    print(f"  {total} tracked rows")
    for table, ids in sorted(created.items()):
        if ids:
            print(f"    {table:<20} {len(ids)}")
    if marker.get("created_receipts"):
        print(f"    {'receipts':<20} {len(marker['created_receipts'])}")
    if marker.get("reused_accounts"):
        print("  reused (not owned by the seed, never purged): "
              + ", ".join(marker["reused_accounts"]))


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Seed additive, reversible mock data into the app's ledger.",
    )
    ap.add_argument("--db", help="target database (default: ledger.db, "
                                 "or $LEDGER_DB_PATH)")
    ap.add_argument("--anchor", help="anchor date YYYY-MM-DD (default: today). "
                                     "Pin it for a reproducible seed.")
    ap.add_argument("--status", action="store_true", help="report what is seeded")
    ap.add_argument("--purge", action="store_true",
                    help="remove only the rows this script created")
    ap.add_argument("--reseed", action="store_true", help="purge, then seed again")
    args = ap.parse_args(argv)

    if args.db:  # must precede the core import — see module docstring
        os.environ["LEDGER_DB_PATH"] = str(Path(args.db).expanduser().resolve())
    _load_app_modules()
    print(f"Database: {core.DB_PATH}")

    anchor = date.today()
    if args.anchor:
        try:
            anchor = date.fromisoformat(args.anchor)
        except ValueError:
            print(f"Invalid --anchor {args.anchor!r}; expected YYYY-MM-DD",
                  file=sys.stderr)
            return 2

    marker = read_marker()

    if args.status:
        _print_status(marker)
        return 0

    if args.purge or args.reseed:
        if marker is None:
            print("Nothing to purge: no mock-seed marker in this database.")
            if not args.reseed:
                return 0
        else:
            print("Purging previously seeded rows…")
            counts = purge(marker)
            print("  removed: " + (", ".join(f"{k}={v}" for k, v in counts.items())
                                   or "nothing"))
            marker = None
        if not args.reseed:
            _print_summary()
            return 0

    if marker is not None:
        print("Mock data is already seeded — not writing again.\n"
              "Use --reseed to replace it, --purge to remove it, --status for details.")
        return 0

    print(f"Seeding mock data (anchor {anchor.isoformat()})…")
    marker = seed(anchor)
    tracked = (sum(len(v) for v in marker["created"].values())
               + len(marker["created_receipts"]))
    print(f"\nDone. {tracked} rows created and tracked in settings['{MARKER_KEY}'].")
    print("Preexisting records were left untouched; `--purge` removes only these.")
    _print_summary()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
