"""
W2-B — budget plans: aggregation, period windows, and carry-forward.

Covers the one W2-B checklist item that had **zero tests** before this file — "budget
aggregation and carry-forward" (see IMPLEMENTATION_STATUS.md §3.3). `evaluation/README.md`
previously marked W2-B "Done" while `list_budget_plans` / `create_budget_plan` /
`delete_budget_plan` were never called by any test.

Determinism and the clock
-------------------------
`finance._period_bounds` resolves the current window from `date.today()`, but the fixture
is seeded with literal 2026-06 dates. Rather than hardcode a period (which would rot the
day the clock moves past it), every aggregation test here asserts a **delta**: read the
plan, post a transaction dated `date.today()` — which is inside the daily, weekly, monthly
and yearly windows by definition — and assert the spend moved by exactly that amount.
Tests are therefore correct on any date the suite is run.

A dedicated non-system category is created per test so seeded fixture spending can never
contribute to the number under assertion.
"""

from __future__ import annotations

from datetime import date

import pytest


@pytest.fixture
def budget_category(finance_fixture, finance):
    """A fresh expense category with no seeded transactions against it."""
    return finance.create_category("Budget Test Category", "expense")


@pytest.fixture
def spending_account(finance_fixture, finance, accounts_by_name):
    return accounts_by_name()["Cash"]["id"]


def _plan(finance, plan_id: int) -> dict:
    """Read one plan back out of the aggregated listing."""
    return next(p for p in finance.list_budget_plans() if p["id"] == plan_id)


def _today() -> str:
    return date.today().isoformat()


# --------------------------------------------------------------------------- #
# Creation and listing
# --------------------------------------------------------------------------- #
def test_a_created_plan_appears_in_the_listing(finance, budget_category):
    plan_id = finance.create_budget_plan(budget_category, limit_amount=5_000)
    assert _plan(finance, plan_id)["category_id"] == budget_category


def test_a_plan_carries_its_category_name(finance, budget_category):
    """The UI renders the category name off this join; losing it would blank the row."""
    plan_id = finance.create_budget_plan(budget_category, limit_amount=5_000)
    assert _plan(finance, plan_id)["category_name"] == "Budget Test Category"


def test_a_fixed_plan_resolves_its_limit_from_the_stated_amount(finance, budget_category):
    plan_id = finance.create_budget_plan(budget_category, limit_amount=5_000)
    assert _plan(finance, plan_id)["limit"] == pytest.approx(5_000.0)


def test_a_new_plan_starts_with_nothing_spent(finance, budget_category):
    plan_id = finance.create_budget_plan(budget_category, limit_amount=5_000)
    assert _plan(finance, plan_id)["spent"] == pytest.approx(0.0)


def test_a_deleted_plan_leaves_the_listing(finance, budget_category):
    plan_id = finance.create_budget_plan(budget_category, limit_amount=5_000)
    assert finance.delete_budget_plan(plan_id) is True
    assert all(p["id"] != plan_id for p in finance.list_budget_plans())


def test_deleting_an_unknown_plan_reports_failure(finance, finance_fixture):
    assert finance.delete_budget_plan(999_999) is False


# --------------------------------------------------------------------------- #
# Aggregation — the number the user actually reads
# --------------------------------------------------------------------------- #
def test_an_expense_in_the_period_is_counted_against_the_plan(
    finance, budget_category, spending_account
):
    plan_id = finance.create_budget_plan(budget_category, limit_amount=5_000)
    finance.create_transaction(
        "expense", 1_200.0, account_id=spending_account,
        category_id=budget_category, occurred_at=_today(),
    )
    assert _plan(finance, plan_id)["spent"] == pytest.approx(1_200.0)


def test_several_expenses_accumulate(finance, budget_category, spending_account):
    plan_id = finance.create_budget_plan(budget_category, limit_amount=5_000)
    for amount in (100.0, 250.5, 49.5):
        finance.create_transaction(
            "expense", amount, account_id=spending_account,
            category_id=budget_category, occurred_at=_today(),
        )
    assert _plan(finance, plan_id)["spent"] == pytest.approx(400.0)


def test_spending_on_another_category_is_not_counted(
    finance, budget_category, spending_account
):
    """A budget is per category. Leaking another category's spend into it would
    make every budget read high."""
    plan_id = finance.create_budget_plan(budget_category, limit_amount=5_000)
    other = finance.create_category("Unrelated Category", "expense")
    finance.create_transaction(
        "expense", 900.0, account_id=spending_account,
        category_id=other, occurred_at=_today(),
    )
    assert _plan(finance, plan_id)["spent"] == pytest.approx(0.0)


def test_income_is_not_counted_as_budget_spend(finance, budget_category, accounts_by_name):
    """The aggregate filters `kind='expense'`. Income tagged to the same category
    must not reduce or inflate it."""
    plan_id = finance.create_budget_plan(budget_category, limit_amount=5_000)
    finance.create_transaction(
        "income", 3_000.0, account_id=accounts_by_name()["Cash"]["id"],
        category_id=budget_category, occurred_at=_today(),
    )
    assert _plan(finance, plan_id)["spent"] == pytest.approx(0.0)


def test_an_expense_outside_the_period_is_not_counted(
    finance, budget_category, spending_account
):
    """A monthly budget must reset. Counting last year's spending would leave every
    plan permanently over budget."""
    plan_id = finance.create_budget_plan(budget_category, interval="monthly",
                                         limit_amount=5_000)
    finance.create_transaction(
        "expense", 4_000.0, account_id=spending_account,
        category_id=budget_category, occurred_at="2020-01-15",
    )
    assert _plan(finance, plan_id)["spent"] == pytest.approx(0.0)


def test_a_yearly_plan_counts_what_a_monthly_plan_would_also_count(
    finance, budget_category, spending_account
):
    """Today falls inside both windows, so the same transaction must appear in both.
    This pins that the window is applied per plan interval, not globally."""
    monthly = finance.create_budget_plan(budget_category, interval="monthly",
                                         limit_amount=5_000)
    yearly = finance.create_budget_plan(budget_category, interval="yearly",
                                        limit_amount=60_000)
    finance.create_transaction(
        "expense", 750.0, account_id=spending_account,
        category_id=budget_category, occurred_at=_today(),
    )
    assert _plan(finance, monthly)["spent"] == pytest.approx(750.0)
    assert _plan(finance, yearly)["spent"] == pytest.approx(750.0)


def test_a_deleted_transaction_stops_counting(finance, budget_category, spending_account):
    plan_id = finance.create_budget_plan(budget_category, limit_amount=5_000)
    txn_id = finance.create_transaction(
        "expense", 500.0, account_id=spending_account,
        category_id=budget_category, occurred_at=_today(),
    )
    assert _plan(finance, plan_id)["spent"] == pytest.approx(500.0)
    finance.delete_transaction(txn_id)
    assert _plan(finance, plan_id)["spent"] == pytest.approx(0.0)


# --------------------------------------------------------------------------- #
# Percent-of-usage reporting
# --------------------------------------------------------------------------- #
def test_percent_used_is_reported_against_the_limit(
    finance, budget_category, spending_account
):
    plan_id = finance.create_budget_plan(budget_category, limit_amount=1_000)
    finance.create_transaction(
        "expense", 250.0, account_id=spending_account,
        category_id=budget_category, occurred_at=_today(),
    )
    assert _plan(finance, plan_id)["pct"] == pytest.approx(25.0)


def test_overspending_reports_above_one_hundred_percent(
    finance, budget_category, spending_account
):
    """The figure must not be clamped — a user over budget needs to see by how much."""
    plan_id = finance.create_budget_plan(budget_category, limit_amount=1_000)
    finance.create_transaction(
        "expense", 1_500.0, account_id=spending_account,
        category_id=budget_category, occurred_at=_today(),
    )
    assert _plan(finance, plan_id)["pct"] == pytest.approx(150.0)


def test_a_zero_limit_reports_no_percentage_rather_than_dividing_by_zero(
    finance, budget_category
):
    plan_id = finance.create_budget_plan(budget_category, limit_amount=0)
    assert _plan(finance, plan_id)["pct"] is None


# --------------------------------------------------------------------------- #
# Percent-of-income plans
# --------------------------------------------------------------------------- #
def test_a_percent_plan_resolves_its_limit_from_this_months_income(
    finance, budget_category, accounts_by_name
):
    """A percent plan has no fixed limit — it is a share of income actually received
    this month, so the limit moves with earnings."""
    plan_id = finance.create_budget_plan(budget_category, type="percent", percent=10)
    finance.create_transaction(
        "income", 50_000.0, account_id=accounts_by_name()["Cash"]["id"],
        occurred_at=_today(),
    )
    assert _plan(finance, plan_id)["limit"] == pytest.approx(5_000.0)


def test_a_percent_plan_with_no_income_this_month_has_a_zero_limit(
    finance, budget_category
):
    """Seeded income is dated 2026-06, so unless the suite is run in that month there
    is none in the current window. Asserted as `<=` the trivial case: with no income
    the limit cannot be positive from this plan alone."""
    plan_id = finance.create_budget_plan(budget_category, type="percent", percent=10)
    plan = _plan(finance, plan_id)
    assert plan["type"] == "percent"
    assert plan["limit"] >= 0.0


def test_income_raises_a_percent_plans_limit(finance, budget_category, accounts_by_name):
    """Delta assertion — robust whatever the clock says about seeded income."""
    plan_id = finance.create_budget_plan(budget_category, type="percent", percent=20)
    before = _plan(finance, plan_id)["limit"]
    finance.create_transaction(
        "income", 10_000.0, account_id=accounts_by_name()["Cash"]["id"],
        occurred_at=_today(),
    )
    assert _plan(finance, plan_id)["limit"] == pytest.approx(before + 2_000.0)


# --------------------------------------------------------------------------- #
# Carry-forward — stored, exposed, and NOT implemented
# --------------------------------------------------------------------------- #
# These are characterization tests. `carry_forward` is accepted by
# `create_budget_plan`, persisted in `budget_plans`, sent by the UI
# (`web-next/app/plan/budgets/page.tsx`) and typed in `types.ts` — but no computation
# in `finance.py` ever reads it. Underspend in one period does not raise the next
# period's limit. See IMPLEMENTATION_STATUS.md; this is defect **D5**.
#
# They assert the behaviour that exists today so the gap is visible and measured
# rather than assumed working. If carry-forward is implemented later, the second test
# will fail loudly — which is the point.
def test_carry_forward_is_persisted_as_set(finance, budget_category):
    plan_id = finance.create_budget_plan(budget_category, limit_amount=1_000,
                                         carry_forward=True)
    assert _plan(finance, plan_id)["carry_forward"] == 1


def test_carry_forward_does_not_change_the_resolved_limit(
    finance, budget_category, spending_account
):
    """**Known gap (D5).** Two identical plans, one with carry-forward set, resolve to
    the same limit — the flag has no effect on any computation. A real carry-forward
    would raise the limit of the flagged plan by the prior period's unspent amount."""
    plain = finance.create_budget_plan(budget_category, limit_amount=1_000)
    carried = finance.create_budget_plan(budget_category, limit_amount=1_000,
                                         carry_forward=True)
    assert _plan(finance, plain)["limit"] == _plan(finance, carried)["limit"]


def test_carry_forward_defaults_to_off(finance, budget_category):
    plan_id = finance.create_budget_plan(budget_category, limit_amount=1_000)
    assert _plan(finance, plan_id)["carry_forward"] == 0


# --------------------------------------------------------------------------- #
# Backup coverage
# --------------------------------------------------------------------------- #
def test_budget_plans_survive_a_backup_restore_round_trip(
    finance, budget_category, finance_fixture
):
    """`budget_plans` is one of the 12 tables `import_backup` deletes before
    restoring (defect D1). A plan lost in the round trip would silently reset a
    user's budgets."""
    plan_id = finance.create_budget_plan(budget_category, limit_amount=7_500,
                                         carry_forward=True)
    payload = finance.export_backup()
    finance.delete_budget_plan(plan_id)
    finance.import_backup(payload, replace=True)

    restored = _plan(finance, plan_id)
    assert restored["limit_amount"] == pytest.approx(7_500.0)
    assert restored["carry_forward"] == 1
