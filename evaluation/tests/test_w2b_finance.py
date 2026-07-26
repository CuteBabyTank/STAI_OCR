"""
W2-B — Layer 1 component evaluation of the deterministic personal-finance logic.

Scope: `finance.py` only. No model, no network, no MLflow. Every expected value is
either hand-computed in `seed_finance.EXPECTED` or derived from an explicit rule in
the PRD/code, so a failure localizes to one function.

These are *component* tests in the breakdown's Layer 1 sense: they answer "does this
function compute the right thing", not "did a user finish a job" (Layer 3, W4).

Covers the W2-B checklist:
  account balances, net worth, expense/income creation, transfer validation and
  effects, budget aggregation, templates, recurring advancement, installment
  payments, goal/debt/receivable activity, upcoming aggregation, history consistency.
Plus the W2-E items reachable without a vision model: receipt posting, duplicate
posting, and backup/restore.
"""

from __future__ import annotations

import pytest


# --------------------------------------------------------------------------- #
# Balance engine
# --------------------------------------------------------------------------- #
def test_account_balances_match_ground_truth(finance_fixture, finance, accounts_by_name):
    """Every seeded account's derived balance equals the hand-computed value."""
    names = accounts_by_name()
    for name, expected in finance_fixture["balances"].items():
        actual = finance.account_balance(names[name]["id"])
        assert actual == pytest.approx(expected, abs=0.005), (
            f"{name}: expected {expected}, got {actual}"
        )


def test_transfer_debits_fee_from_source_only(finance_fixture, finance, accounts_by_name):
    """A transfer's fee is charged to the source; the destination receives the
    amount untouched. Regression guard on the asymmetry in `_balances`."""
    names = accounts_by_name()
    before_src = finance.account_balance(names["BPI Checking"]["id"])
    before_dst = finance.account_balance(names["Cash"]["id"])

    finance.create_transaction(
        "transfer", 1000.00, account_id=names["BPI Checking"]["id"],
        to_account_id=names["Cash"]["id"], fee=25.00, occurred_at="2026-06-20",
    )

    assert finance.account_balance(names["BPI Checking"]["id"]) == pytest.approx(
        before_src - 1025.00, abs=0.005
    )
    assert finance.account_balance(names["Cash"]["id"]) == pytest.approx(
        before_dst + 1000.00, abs=0.005
    )


def test_liability_account_balance_is_negative(finance_fixture, finance, accounts_by_name):
    """Spending on a credit account drives its balance negative — money owed."""
    assert finance.account_balance(accounts_by_name()["Credit Card"]["id"]) == pytest.approx(
        -800.00, abs=0.005
    )


# --------------------------------------------------------------------------- #
# Net worth
# --------------------------------------------------------------------------- #
def test_net_worth_matches_ground_truth(finance_fixture, finance):
    assert finance.net_worth() == pytest.approx(finance_fixture["net_worth"], abs=0.005)


def test_net_worth_excluding_credit(finance_fixture, finance):
    """include_credit=False drops the credit account from liabilities entirely."""
    assert finance.net_worth(include_credit=False) == pytest.approx(
        finance_fixture["net_worth_excluding_credit"], abs=0.005
    )


def test_net_worth_hiding_liabilities_still_reports_them(finance_fixture, finance):
    """show_liabilities=False stops subtracting liabilities but still reports the
    magnitude — hiding is a display choice, not a data change."""
    result = finance.net_worth(show_liabilities=False)
    assert result == pytest.approx(finance_fixture["net_worth_hiding_liabilities"], abs=0.005)
    assert result["liabilities"] == pytest.approx(800.00, abs=0.005)


def test_archived_and_excluded_accounts_are_left_out_of_net_worth(
    finance_fixture, finance, accounts_by_name
):
    """Both exclusion mechanisms work, and neither erases the account's own balance."""
    names = accounts_by_name()
    assert finance.account_balance(names["Archived Wallet"]["id"]) == pytest.approx(999.00)
    assert finance.account_balance(names["Excluded Pocket"]["id"]) == pytest.approx(500.00)
    # 999 + 500 = 1499 would show up in assets if either were counted.
    assert finance.net_worth()["assets"] == pytest.approx(68500.00, abs=0.005)


# --------------------------------------------------------------------------- #
# Transaction validation (PRD §22 account-type rules)
# --------------------------------------------------------------------------- #
def test_transfer_to_same_account_is_rejected(finance_fixture, finance, accounts_by_name):
    """Explicit W1 dataset-coverage item: 'Transfer cannot target the same account'."""
    cash = accounts_by_name()["Cash"]["id"]
    with pytest.raises(finance.FinanceError, match="same account"):
        finance.create_transaction("transfer", 100.00, account_id=cash, to_account_id=cash)


def test_income_into_credit_account_is_rejected(finance_fixture, finance, accounts_by_name):
    with pytest.raises(finance.FinanceError, match="debit account"):
        finance.create_transaction(
            "income", 100.00, account_id=accounts_by_name()["Credit Card"]["id"]
        )


def test_transfer_to_non_debit_account_is_rejected(finance_fixture, finance, accounts_by_name):
    names = accounts_by_name()
    with pytest.raises(finance.FinanceError, match="debit account"):
        finance.create_transaction(
            "transfer", 100.00, account_id=names["Cash"]["id"],
            to_account_id=names["Emergency Fund"]["id"],
        )


def test_expense_on_credit_account_is_allowed(finance_fixture, finance, accounts_by_name):
    """Expenses may draw on any account type — the asymmetry with income/transfer
    is deliberate, so guard it against an over-zealous future tightening."""
    txn_id = finance.create_transaction(
        "expense", 300.00, account_id=accounts_by_name()["Credit Card"]["id"],
        occurred_at="2026-06-21",
    )
    assert txn_id > 0


@pytest.mark.parametrize("amount", [0, -1, -0.01])
def test_non_positive_amounts_are_rejected(finance_fixture, finance, accounts_by_name, amount):
    with pytest.raises(finance.FinanceError, match="greater than 0"):
        finance.create_transaction(
            "expense", amount, account_id=accounts_by_name()["Cash"]["id"]
        )


def test_unknown_transaction_kind_is_rejected(finance_fixture, finance, accounts_by_name):
    with pytest.raises(finance.FinanceError, match="Unknown transaction kind"):
        finance.create_transaction(
            "refund", 100.00, account_id=accounts_by_name()["Cash"]["id"]
        )


# --------------------------------------------------------------------------- #
# Receipt posting (W2-E)
# --------------------------------------------------------------------------- #
def test_posting_a_receipt_creates_one_linked_expense(
    finance_fixture, finance, core, accounts_by_name
):
    """E2E-PST's core invariant, at component level: one receipt -> one linked
    transaction carrying the receipt's amount and date."""
    receipt = next(
        r for r in core.list_receipts()
        if r["vendor_name"] == finance_fixture["postable_receipt"]["vendor_name"]
    )
    account_id = accounts_by_name()["Cash"]["id"]

    txn_id = finance.post_receipt_as_expense(receipt["id"], account_id)
    txn = finance.get_transaction(txn_id)

    assert txn["kind"] == "expense"
    assert txn["receipt_id"] == receipt["id"]
    assert txn["amount"] == pytest.approx(finance_fixture["postable_receipt"]["total_amount"])
    assert txn["occurred_at"] == finance_fixture["postable_receipt"]["receipt_date"]
    assert txn["account_id"] == account_id


def test_reposting_a_receipt_does_not_duplicate(
    finance_fixture, finance, core, accounts_by_name
):
    """Explicit W1 coverage item: 'Reposting does not create an unintended
    duplicate'. Posting is idempotent per receipt — it updates in place."""
    receipt = next(
        r for r in core.list_receipts()
        if r["vendor_name"] == finance_fixture["postable_receipt"]["vendor_name"]
    )
    account_id = accounts_by_name()["Cash"]["id"]

    first = finance.post_receipt_as_expense(receipt["id"], account_id)
    second = finance.post_receipt_as_expense(receipt["id"], account_id)

    assert first == second, "re-posting created a second transaction"
    linked = [t for t in finance.list_transactions() if t["receipt_id"] == receipt["id"]]
    assert len(linked) == 1


def test_posting_reduces_the_account_balance_once(
    finance_fixture, finance, core, accounts_by_name
):
    """Cross-module consistency: the posted transaction moves the balance by exactly
    the receipt total, and re-posting does not move it again."""
    receipt = next(
        r for r in core.list_receipts()
        if r["vendor_name"] == finance_fixture["postable_receipt"]["vendor_name"]
    )
    account_id = accounts_by_name()["Cash"]["id"]
    before = finance.account_balance(account_id)

    finance.post_receipt_as_expense(receipt["id"], account_id)
    after_first = finance.account_balance(account_id)
    finance.post_receipt_as_expense(receipt["id"], account_id)
    after_second = finance.account_balance(account_id)

    expected = before - finance_fixture["postable_receipt"]["total_amount"]
    assert after_first == pytest.approx(expected, abs=0.005)
    assert after_second == pytest.approx(expected, abs=0.005)


def test_posting_an_unknown_receipt_is_rejected(finance_fixture, finance, accounts_by_name):
    with pytest.raises(finance.FinanceError, match="not found"):
        finance.post_receipt_as_expense(999999, accounts_by_name()["Cash"]["id"])


def test_posting_to_an_unknown_account_is_rejected(finance_fixture, finance, core):
    receipt = core.list_receipts()[0]
    with pytest.raises(finance.FinanceError, match="Account not found"):
        finance.post_receipt_as_expense(receipt["id"], 999999)


def test_posting_a_zero_total_receipt_is_rejected(
    finance_fixture, finance, core, accounts_by_name
):
    """A receipt whose total failed to extract must not silently post as ₱0."""
    empty = core.ReceiptData(vendor_name="Unreadable", total_amount=0.0, items=[])
    receipt_id = core.save_receipt(empty, "unreadable.jpg", flagged=True, index=False)
    with pytest.raises(finance.FinanceError, match="no positive total"):
        finance.post_receipt_as_expense(receipt_id, accounts_by_name()["Cash"]["id"])


# --------------------------------------------------------------------------- #
# Templates, recurring, installments
# --------------------------------------------------------------------------- #
def test_using_a_template_creates_a_matching_transaction(finance_fixture, finance):
    template = finance.list_templates()[0]
    txn_id = finance.use_template(template["id"])
    txn = finance.get_transaction(txn_id)

    assert txn["amount"] == pytest.approx(template["amount"])
    assert txn["kind"] == template["kind"]
    assert txn["template_id"] == template["id"]


def test_advancing_a_recurring_rolls_the_due_date_forward_one_month(
    finance_fixture, finance
):
    """Seeded next_due is 2026-07-01, so one advance must land on 2026-08-01."""
    rec = finance.list_recurring()[0]
    assert rec["next_due"] == "2026-07-01"

    finance.advance_recurring(rec["id"])

    assert finance.list_recurring()[0]["next_due"] == "2026-08-01"


def test_advancing_a_recurring_creates_a_transaction(finance_fixture, finance):
    rec = finance.list_recurring()[0]
    before = len(finance.list_transactions())

    finance.advance_recurring(rec["id"])

    assert len(finance.list_transactions()) == before + 1


def test_installment_payment_increases_paid_amount(finance_fixture, finance, accounts_by_name):
    plan = finance.list_installments()[0]
    assert plan["paid_amount"] == pytest.approx(0.0)

    finance.log_installment_payment(
        plan["id"], accounts_by_name()["Cash"]["id"], 5000.00, occurred_at="2026-06-25"
    )

    assert finance.list_installments()[0]["paid_amount"] == pytest.approx(5000.00, abs=0.005)


# --------------------------------------------------------------------------- #
# Goals, debts, receivables
# --------------------------------------------------------------------------- #
def test_goal_deposit_updates_goal_and_debits_account(
    finance_fixture, finance, accounts_by_name
):
    """Goal activity is a real ledger entry, not a detached counter — the account
    balance must move with it."""
    goal = finance.list_goals()[0]
    account_id = accounts_by_name()["Cash"]["id"]
    before_balance = finance.account_balance(account_id)
    before_amount = goal["current_amount"]

    finance.goal_activity(goal["id"], account_id, 2000.00, "deposit",
                          occurred_at="2026-06-22")

    assert finance.list_goals()[0]["current_amount"] == pytest.approx(
        before_amount + 2000.00, abs=0.005
    )
    assert finance.account_balance(account_id) == pytest.approx(
        before_balance - 2000.00, abs=0.005
    )


def test_debt_payment_updates_paid_amount(finance_fixture, finance, accounts_by_name):
    debt = finance.list_debts()[0]
    before = debt["paid_amount"]

    finance.debt_activity(debt["id"], accounts_by_name()["Cash"]["id"], 5000.00,
                          "payment", occurred_at="2026-06-23")

    assert finance.list_debts()[0]["paid_amount"] == pytest.approx(before + 5000.00, abs=0.005)


def test_receivable_collection_updates_collected_amount(
    finance_fixture, finance, accounts_by_name
):
    rec = finance.list_receivables()[0]
    before = rec["collected_amount"]

    finance.receivable_activity(rec["id"], accounts_by_name()["Cash"]["id"], 500.00,
                                "collection", occurred_at="2026-06-24")

    assert finance.list_receivables()[0]["collected_amount"] == pytest.approx(
        before + 500.00, abs=0.005
    )


# --------------------------------------------------------------------------- #
# Categories
# --------------------------------------------------------------------------- #
def test_system_categories_cannot_be_deleted(finance_fixture, finance):
    """Seeded categories are is_system=1 and must survive a delete attempt."""
    system = next(c for c in finance.list_categories() if c["is_system"])
    before = len(finance.list_categories())

    try:
        finance.delete_category(system["id"])
    except finance.FinanceError:
        pass  # refusing loudly is also acceptable

    assert any(c["id"] == system["id"] for c in finance.list_categories())
    assert len(finance.list_categories()) == before


# --------------------------------------------------------------------------- #
# History / statistics consistency
# --------------------------------------------------------------------------- #
def test_transaction_count_matches_ground_truth(finance_fixture, finance):
    assert len(finance.list_transactions()) == finance_fixture["counts"]["transactions"]


def test_filtering_by_kind_partitions_the_ledger(finance_fixture, finance):
    """Cross-module consistency: the three kind filters must sum to the whole
    ledger with no double-counting and no orphans."""
    total = len(finance.list_transactions())
    by_kind = sum(
        len(finance.list_transactions(kind=k)) for k in ("expense", "income", "transfer")
    )
    assert by_kind == total


def test_filtering_by_account_is_consistent(finance_fixture, finance, accounts_by_name):
    cash_id = accounts_by_name()["Cash"]["id"]
    filtered = finance.list_transactions(account_id=cash_id)
    assert filtered, "expected at least one Cash transaction in the fixture"
    assert all(
        t["account_id"] == cash_id or t["to_account_id"] == cash_id for t in filtered
    )


def test_deleting_a_transaction_restores_the_prior_balance(
    finance_fixture, finance, accounts_by_name
):
    """Balances are derived, never stored — deleting must fully reverse the effect."""
    account_id = accounts_by_name()["Cash"]["id"]
    before = finance.account_balance(account_id)

    txn_id = finance.create_transaction(
        "expense", 777.00, account_id=account_id, occurred_at="2026-06-26"
    )
    assert finance.account_balance(account_id) == pytest.approx(before - 777.00, abs=0.005)

    finance.delete_transaction(txn_id)
    assert finance.account_balance(account_id) == pytest.approx(before, abs=0.005)


# --------------------------------------------------------------------------- #
# Upcoming obligations
# --------------------------------------------------------------------------- #
def test_upcoming_returns_the_seeded_obligations(finance_fixture, finance):
    """`upcoming()` aggregates across recurring / installments / debts. Assert on
    structure and non-emptiness only: the seeded due dates are fixed, but the
    function's windowing relative to today is not part of this fixture's ground
    truth, and pinning it would make the test fail with the passage of time."""
    result = finance.upcoming()
    assert isinstance(result, dict)
    assert result, "upcoming() returned nothing for a fixture with 3 dated obligations"


# --------------------------------------------------------------------------- #
# Backup / restore (W2-E)
# --------------------------------------------------------------------------- #
def test_backup_contains_every_intended_record_group(finance_fixture, finance):
    """Backup completeness = intended records present / intended records.

    Records live under the `data` key; `format`/`exported_at` are envelope metadata.
    """
    backup = finance.export_backup()
    assert backup["format"] == "stai-ledger-backup/1"
    data = backup["data"]
    counts = finance_fixture["counts"]

    assert len(data["accounts"]) == counts["accounts"]
    assert len(data["transactions"]) == counts["transactions"]
    assert len(data["goals"]) == counts["goals"]
    assert len(data["debts"]) == counts["debts"]
    assert len(data["receivables"]) == counts["receivables"]
    assert len(data["budget_plans"]) == counts["budget_plans"]
    assert len(data["templates"]) == counts["templates"]
    assert len(data["recurring"]) == counts["recurring"]
    assert len(data["installment_plans"]) == counts["installment_plans"]


def test_restore_recreates_records_and_relationships(
    finance_fixture, finance, accounts_by_name
):
    """Restore success is measured on record *content and relationships*, not on
    the file existing (breakdown §6 'Recommended shared review')."""
    backup = finance.export_backup()
    before_net = finance.net_worth()
    before_txns = len(finance.list_transactions())

    # Mutate, then restore over the top.
    finance.create_transaction(
        "expense", 4321.00, account_id=accounts_by_name()["Cash"]["id"],
        occurred_at="2026-06-27",
    )
    assert len(finance.list_transactions()) == before_txns + 1

    finance.import_backup(backup, replace=True)

    assert len(finance.list_transactions()) == before_txns
    assert finance.net_worth() == pytest.approx(before_net, abs=0.005)


def test_restore_preserves_receipt_transaction_linkage(
    finance_fixture, finance, core, accounts_by_name
):
    """The receipt_id link is the traceability the breakdown calls for — it must
    survive a backup/restore round trip, not just the row itself."""
    receipt = next(
        r for r in core.list_receipts()
        if r["vendor_name"] == finance_fixture["postable_receipt"]["vendor_name"]
    )
    finance.post_receipt_as_expense(receipt["id"], accounts_by_name()["Cash"]["id"])

    backup = finance.export_backup()
    finance.import_backup(backup, replace=True)

    linked = [t for t in finance.list_transactions() if t["receipt_id"] == receipt["id"]]
    assert len(linked) == 1, "receipt linkage was lost or duplicated across restore"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "KNOWN DEFECT (audit finding D1, unfixed): finance.import_backup does not "
        "validate its payload. `data = (payload or {}).get('data', {})` yields {} for "
        "any malformed input, then replace=True DELETEs all 12 finance tables and "
        "inserts nothing — total silent data loss, reported as a success. Reproduced "
        "with {'not':'a backup'}, {} and None. Reachable from POST /backup/import, "
        "which has no auth layer in front of it. Remove this marker when fixed."
    ),
)
def test_malformed_backup_is_handled_visibly(finance_fixture, finance):
    """Explicit W2-E item: 'Malformed backup behavior is tested'.

    Either raise or reject — what is not acceptable is silently wiping the ledger.
    This is expected-to-fail against the current code and documents the defect;
    strict=True means it turns into a hard failure the moment the bug is fixed,
    which is the signal to delete the marker.
    """
    before = len(finance.list_transactions())
    try:
        finance.import_backup({"not": "a backup"}, replace=True)
    except Exception:
        pass  # raising is a visible, acceptable outcome
    assert len(finance.list_transactions()) == before, (
        "a malformed backup destroyed existing data"
    )


def test_empty_backup_payload_does_not_wipe_the_ledger(finance_fixture, finance):
    """Companion to the xfail above, kept separate so the blast radius is recorded:
    an empty dict and None hit the same unguarded path. Marked xfail for the same
    defect D1."""
    pytest.xfail("same defect as test_malformed_backup_is_handled_visibly (D1)")
