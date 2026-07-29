"""
W2-H — the agent's remaining write tools: income, transfers, goals, debts, and
money owed to the user (receivables), plus editing and deleting them.

Scope of the evidence
---------------------
The tool functions are driven directly against the real fixture database, so the
guardrails, the resolution, and the ledger effects are genuinely measured. Where a
test drives `agent_stream`, `_chat` is stubbed: that measures Snag's response to a
given model transcript, NOT how often a real model picks the right tool. Routing
accuracy for these tools is a live-model W3 question; the cases are defined in
`datasets/trajectory_cases.json`.

The weighting is deliberate. `record_activity` and `update_plan` are the two tools
that can move money against the wrong obligation or delete a record outright, so
most of what follows is about what they REFUSE to do.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def wallet(finance, finance_fixture):
    """The seeded fixture plus two realistically-named cards."""
    finance.create_account("BDO Credit Card", "credit", 0.0, "PHP")
    finance.create_account("UnionBank Credit", "credit", 0.0, "PHP")
    return {a["name"]: a["id"] for a in finance.list_accounts()}


@pytest.fixture
def plans(finance, wallet):
    """One of each plan kind, named the way a user would name them."""
    return {
        "goal": finance.create_goal("Emergency Fund", 50000.0),
        "debt": finance.create_debt("Car Loan", 200000.0),
        "receivable": finance.create_receivable("Mark", 1500.0),
    }


def _drain(core, question: str, **kwargs) -> list[dict]:
    return list(core.agent_stream(question, core.AGENT_MODEL, **kwargs))


@pytest.fixture
def scripted_model(core, monkeypatch):
    def _install(*replies: str):
        react_replies = list(replies)
        n = 0

        def fake_chat(**kwargs):
            nonlocal n
            prompt = kwargs["messages"][0]["content"]
            if "SQL expert" in prompt:
                text = "SELECT SUM(total_amount) AS total_amount FROM receipts"
            elif "Findings:" in prompt:
                text = "Done."
            else:
                text = react_replies[min(n, len(react_replies) - 1)]
                n += 1
            if kwargs.get("stream"):
                return iter([{"message": {"content": text}}])
            return {"message": {"content": text}}

        monkeypatch.setattr(core, "_chat", fake_chat)
        monkeypatch.setattr(core, "_embed", lambda text: None)

    return _install


# --------------------------------------------------------------------------- #
# add_income
# --------------------------------------------------------------------------- #
def test_income_credits_the_named_account(core, finance, wallet):
    before = finance.account_balance(wallet["BPI Checking"])
    _obs, data = core._tool_add_income(
        "amount=30000; account=BPI; category=Salary; note=June pay")
    assert data["action"] == "income"
    assert finance.account_balance(wallet["BPI Checking"]) == pytest.approx(before + 30000)
    txn = finance.get_transaction(data["transaction_id"])
    assert txn["kind"] == "income"


def test_income_into_a_credit_card_is_refused_before_the_write(core, finance, wallet):
    """PRD §22: income may only land in a debit account. `create_transaction` would
    raise, but the agent needs a message it can act on, and the refusal must name
    the accounts that WOULD work."""
    before = len(finance.list_transactions())
    obs, data = core._tool_add_income("amount=5000; account=BDO Credit Card")
    assert data["error"] == "unknown_account"
    assert len(finance.list_transactions()) == before
    assert "BPI Checking" in obs


def test_income_resolves_income_categories_not_expense_ones(core, finance, wallet):
    """"Food" is an expense category. Filing income under it would corrupt every
    income/expense split downstream."""
    _obs, data = core._tool_add_income("amount=1000; account=Cash; category=Food")
    assert data["error"] == "unknown_category"


# --------------------------------------------------------------------------- #
# transfer_money
# --------------------------------------------------------------------------- #
def test_a_transfer_moves_money_between_the_users_own_accounts(core, finance, wallet):
    src = finance.account_balance(wallet["BPI Checking"])
    dst = finance.account_balance(wallet["Cash"])
    _obs, data = core._tool_transfer_money("amount=5000; from=BPI; to=Cash")

    assert data["action"] == "transfer"
    assert finance.account_balance(wallet["BPI Checking"]) == pytest.approx(src - 5000)
    assert finance.account_balance(wallet["Cash"]) == pytest.approx(dst + 5000)


def test_a_transfer_is_not_recorded_as_an_expense(core, finance, wallet):
    """Moving your own money is not spending it. Recording it as an expense would
    inflate every spend total and every budget."""
    _obs, data = core._tool_transfer_money("amount=5000; from=BPI; to=Cash")
    assert finance.get_transaction(data["transaction_id"])["kind"] == "transfer"


def test_a_transfer_fee_is_debited_from_the_source_only(core, finance, wallet):
    src = finance.account_balance(wallet["BPI Checking"])
    dst = finance.account_balance(wallet["Cash"])
    core._tool_transfer_money("amount=5000; from=BPI; to=Cash; fee=25")
    assert finance.account_balance(wallet["BPI Checking"]) == pytest.approx(src - 5025)
    assert finance.account_balance(wallet["Cash"]) == pytest.approx(dst + 5000)


def test_a_transfer_to_the_same_account_is_refused(core, finance, wallet):
    before = len(finance.list_transactions())
    _obs, data = core._tool_transfer_money("amount=1000; from=Cash; to=Cash")
    assert data["error"] == "same_account"
    assert len(finance.list_transactions()) == before


def test_a_transfer_naming_only_one_side_is_refused(core, finance, wallet):
    """Guessing the other side would move real money between real accounts."""
    _obs, data = core._tool_transfer_money("amount=1000; from=BPI")
    assert data["error"] == "unknown_account"


# --------------------------------------------------------------------------- #
# record_activity — goals, debts, receivables
# --------------------------------------------------------------------------- #
def test_a_goal_deposit_moves_money_and_advances_the_goal(core, finance, wallet, plans):
    before = finance.account_balance(wallet["Cash"])
    obs, data = core._tool_record_activity(
        "type=goal; target=Emergency Fund; action=deposit; amount=2000; account=Cash")

    assert data["plan_kind"] == "goal"
    goal = next(g for g in finance.list_goals() if g["id"] == plans["goal"])
    assert goal["current_amount"] == pytest.approx(2000)
    assert finance.account_balance(wallet["Cash"]) == pytest.approx(before - 2000)
    assert "2,000.00 of 50,000.00 saved" in obs


def test_a_debt_payment_reduces_what_is_owed(core, finance, wallet, plans):
    _obs, data = core._tool_record_activity(
        "type=debt; target=Car Loan; action=payment; amount=3000; account=BPI")
    debt = next(d for d in finance.list_debts() if d["id"] == plans["debt"])
    assert debt["paid_amount"] == pytest.approx(3000)
    assert "paid off" in data["progress"]


def test_collecting_money_someone_owes_credits_the_account(core, finance, wallet, plans):
    before = finance.account_balance(wallet["Cash"])
    core._tool_record_activity(
        "type=receivable; target=Mark; action=collection; amount=500; account=Cash")
    rec = next(r for r in finance.list_receivables() if r["id"] == plans["receivable"])
    assert rec["collected_amount"] == pytest.approx(500)
    assert finance.account_balance(wallet["Cash"]) == pytest.approx(before + 500)


@pytest.mark.parametrize("said,expected", [
    ("pay", "debt_payment"), ("repay", "debt_payment"),
])
def test_everyday_words_map_to_the_finance_verb(core, finance, wallet, plans,
                                                said, expected):
    """A user says "pay"; the finance layer wants "payment". Making the model learn
    the internal vocabulary is a routing error waiting to happen."""
    _obs, data = core._tool_record_activity(
        f"type=debt; target=Car Loan; action={said}; amount=100; account=BPI")
    assert data["action"] == expected


def test_an_action_that_does_not_exist_for_the_kind_is_refused(core, finance, wallet, plans):
    """A goal cannot take a "payment". Silently mapping it to "deposit" would move
    money on a guess."""
    before = len(finance.list_transactions())
    obs, data = core._tool_record_activity(
        "type=goal; target=Emergency Fund; action=payment; amount=100; account=Cash")
    assert data["error"] == "unknown_plan_action"
    assert len(finance.list_transactions()) == before
    assert "deposit" in obs


def test_an_unknown_plan_is_refused_and_the_real_ones_are_named(core, finance, wallet, plans):
    before = len(finance.list_transactions())
    obs, data = core._tool_record_activity(
        "type=debt; target=Mortgage; action=payment; amount=100; account=BPI")
    assert data["error"] == "unknown_debt"
    assert len(finance.list_transactions()) == before
    assert "Car Loan" in obs


def test_an_ambiguous_plan_is_a_question_not_a_guess(core, finance, wallet, plans):
    """Two loans, "loan" names both. Paying the wrong one is a real financial error
    that the user may not notice for months."""
    finance.create_debt("Student Loan", 80000.0)
    before = len(finance.list_transactions())
    obs, data = core._tool_record_activity(
        "type=debt; target=loan; action=payment; amount=100; account=BPI")
    assert data["error"] == "ambiguous_debt"
    assert len(finance.list_transactions()) == before
    assert "Car Loan" in obs and "Student Loan" in obs


def test_a_missing_type_is_refused(core, finance, wallet, plans):
    _obs, data = core._tool_record_activity("target=Car Loan; amount=100; account=BPI")
    assert data["error"] == "unknown_plan_kind"


def test_plan_activity_respects_the_single_entry_ceiling(core, finance, wallet, plans):
    _obs, data = core._tool_record_activity(
        "type=goal; target=Emergency Fund; action=deposit; amount=99000000; account=Cash")
    assert data["error"] == "amount_too_large"


def test_a_repeated_plan_payment_does_not_pay_twice(core, finance, wallet, plans):
    """Same guard as expenses: the same payment phrased two ways must land once."""
    core._tool_record_activity(
        "type=debt; target=Car Loan; action=payment; amount=3000; account=BPI")
    _obs, data = core._tool_record_activity(
        "account=BPI; amount=3000; action=payment; target=Car Loan; type=debt")
    assert data.get("duplicate") is True
    debt = next(d for d in finance.list_debts() if d["id"] == plans["debt"])
    assert debt["paid_amount"] == pytest.approx(3000)


# --------------------------------------------------------------------------- #
# create_plan
# --------------------------------------------------------------------------- #
def test_creating_a_goal_moves_no_money(core, finance, wallet):
    """Setting up a 50,000 goal must not debit 50,000. The record and the money are
    separate events."""
    before = len(finance.list_transactions())
    obs, data = core._tool_create_plan("type=goal; name=New Laptop; amount=50000")
    assert data["plan_kind"] == "goal"
    assert len(finance.list_transactions()) == before
    assert "No money has moved" in obs


def test_creating_a_debt_records_what_is_owed(core, finance, wallet):
    _obs, data = core._tool_create_plan("type=debt; name=Tuition Balance; amount=200000")
    assert any(d["name"] == "Tuition Balance" for d in finance.list_debts())
    assert data["amount"] == 200000.0


def test_creating_a_receivable_records_money_owed_to_the_user(core, finance, wallet):
    core._tool_create_plan("type=receivable; name=Jean; amount=1200")
    assert any(r["name"] == "Jean" for r in finance.list_receivables())


def test_a_duplicate_plan_name_is_refused(core, finance, wallet, plans):
    """Two goals called "Emergency Fund" would be permanently ambiguous — every
    later deposit would need a clarifying question."""
    before = len(finance.list_goals())
    obs, data = core._tool_create_plan("type=goal; name=Emergency Fund; amount=10000")
    assert data["error"] == "duplicate_plan"
    assert "record_activity" in obs
    assert len(finance.list_goals()) == before


def test_a_merely_similar_name_is_not_treated_as_a_duplicate(core, finance, wallet, plans):
    """"Housing Loan" shares the word "loan" with the existing "Car Loan". The
    duplicate check is an EXACT name comparison, not the fuzzy resolver — reusing
    the resolver here refused every legitimately new debt whose name happened to
    share a common word with an existing one."""
    before = len(finance.list_debts())
    _obs, data = core._tool_create_plan("type=debt; name=Housing Loan; amount=200000")
    assert data.get("error") is None
    assert len(finance.list_debts()) == before + 1


def test_the_duplicate_check_ignores_case(core, finance, wallet, plans):
    _obs, data = core._tool_create_plan("type=goal; name=emergency fund; amount=1")
    assert data["error"] == "duplicate_plan"


def test_a_plan_without_a_name_is_refused(core, finance, wallet):
    _obs, data = core._tool_create_plan("type=goal; amount=10000")
    assert data["error"] == "missing_name"


def test_a_plan_due_date_is_stored(core, finance, wallet):
    _obs, data = core._tool_create_plan(
        "type=debt; name=Tuition; amount=40000; due=2026-12-31")
    assert data["due"] == "2026-12-31"


# --------------------------------------------------------------------------- #
# update_plan — editing and deleting
# --------------------------------------------------------------------------- #
def test_a_goal_target_can_be_corrected(core, finance, wallet, plans):
    core._tool_update_plan("type=goal; target=Emergency Fund; amount=80000")
    goal = next(g for g in finance.list_goals() if g["id"] == plans["goal"])
    assert goal["target_amount"] == pytest.approx(80000)


def test_a_debt_amount_can_be_corrected(core, finance, wallet, plans):
    """Debts and receivables had no updater at all before this — the agent could
    create and delete them but never fix a typo'd amount."""
    core._tool_update_plan("type=debt; target=Car Loan; amount=180000")
    debt = next(d for d in finance.list_debts() if d["id"] == plans["debt"])
    assert debt["total_amount"] == pytest.approx(180000)


def test_a_plan_can_be_renamed(core, finance, wallet, plans):
    core._tool_update_plan("type=receivable; target=Mark; name=Mark Santos")
    assert any(r["name"] == "Mark Santos" for r in finance.list_receivables())


def test_an_edit_moves_no_money(core, finance, wallet, plans):
    before = len(finance.list_transactions())
    core._tool_update_plan("type=goal; target=Emergency Fund; amount=80000")
    assert len(finance.list_transactions()) == before


def test_an_update_that_changes_nothing_is_refused(core, finance, wallet, plans):
    """A no-op that reported success would let the agent tell the user it fixed
    something it did not touch."""
    _obs, data = core._tool_update_plan("type=goal; target=Emergency Fund")
    assert data["error"] == "empty_update"


def test_deleting_requires_an_explicit_flag(core, finance, wallet, plans):
    """Deletion must never be a side effect of an edit. Without `delete=true` the
    same input is an empty update, not a removal."""
    core._tool_update_plan("type=debt; target=Car Loan")
    assert any(d["id"] == plans["debt"] for d in finance.list_debts())


def test_a_plan_can_be_deleted_when_asked_explicitly(core, finance, wallet, plans):
    obs, data = core._tool_update_plan("type=debt; target=Car Loan; delete=true")
    assert data["deleted"] is True
    assert not any(d["id"] == plans["debt"] for d in finance.list_debts())
    assert "transactions stay in the ledger" in obs


def test_an_ambiguous_delete_target_deletes_nothing(core, finance, wallet, plans):
    """The most dangerous combination: a destructive verb and a name matching two
    rows. It must resolve to exactly one or do nothing at all."""
    finance.create_debt("Student Loan", 80000.0)
    before = len(finance.list_debts())
    _obs, data = core._tool_update_plan("type=debt; target=loan; delete=true")
    assert data["error"] == "ambiguous_debt"
    assert len(finance.list_debts()) == before


def test_an_edit_cannot_inject_a_column_name(core, finance, wallet, plans):
    """`update_plan_fields` builds SQL from a fixed allow-list, never from caller
    keys — the payload originates in model-parsed text."""
    finance.update_plan_fields("debts", plans["debt"], {"id = 1; DROP TABLE debts --": 1})
    assert finance.list_debts(), "the table is intact"


def test_an_unknown_table_cannot_be_updated(core, finance, plans):
    with pytest.raises(finance.FinanceError):
        finance.update_plan_fields("accounts", 1, {"name": "hacked"})


# --------------------------------------------------------------------------- #
# list_plans
# --------------------------------------------------------------------------- #
def test_list_plans_names_the_real_plans_with_progress(core, wallet, plans):
    obs, data = core._tool_list_plans("-")
    assert "Emergency Fund" in obs and "Car Loan" in obs and "Mark" in obs
    assert data["kind"] == "plans"
    assert {"goals", "debts", "receivables"} <= set(data)


def test_list_plans_can_be_filtered(core, wallet, plans):
    obs, data = core._tool_list_plans("goals")
    assert "Emergency Fund" in obs
    assert "Car Loan" not in obs


def test_list_plans_is_readable_when_nothing_exists(core, finance, finance_fixture):
    """An empty state must read as "none", not as a crash or a blank observation the
    model will fill in from imagination."""
    for goal in finance.list_goals():
        finance.delete_goal(goal["id"])
    obs, _data = core._tool_list_plans("goals")
    assert "none" in obs.lower()


# --------------------------------------------------------------------------- #
# End to end through the real loop
# --------------------------------------------------------------------------- #
def test_the_agent_pays_a_debt_end_to_end(core, finance, wallet, plans, scripted_model):
    scripted_model(
        "Thought: A payment against a named debt.\n"
        "Action: record_activity\n"
        "Action Input: type=debt; target=Car Loan; action=payment; amount=3000; account=BPI",
        "Thought: Done.\nFinal Answer: Recorded 3,000.00 against your Car Loan.",
    )
    events = _drain(core, "i paid 3000 on my car loan from BPI")
    assert [e["type"] for e in events if e["type"] != "token"] == [
        "start", "action", "observation", "final"]
    debt = next(d for d in finance.list_debts() if d["id"] == plans["debt"])
    assert debt["paid_amount"] == pytest.approx(3000)


def test_a_write_tool_refusal_leaves_the_ledger_untouched_end_to_end(
    core, finance, wallet, plans, scripted_model
):
    finance.create_debt("Student Loan", 80000.0)
    scripted_model(
        "Thought: Pay it.\nAction: record_activity\n"
        "Action Input: type=debt; target=loan; action=payment; amount=3000; account=BPI",
        "Thought: Ambiguous.\nClarification: Which loan — the Car Loan or the Student Loan?",
    )
    before = len(finance.list_transactions())
    events = _drain(core, "i paid 3000 on my loan")

    assert [e["type"] for e in events if e["type"] != "token"][-1] == "clarify"
    assert len(finance.list_transactions()) == before
