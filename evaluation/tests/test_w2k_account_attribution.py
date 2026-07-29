"""
W2-K — the account a write lands on must be one the USER named.

The failure this exists to stop
------------------------------
Real session: the user typed *"i paid off 100k off my car loan"* and named no
account. The model filled in `account=BPI Checking` anyway, the tool executed it
faithfully, and ₱100,000 left a real account — overdrawing it to −56,025.

The prompt already said "If the user has not said WHICH account, you must ask. Never
pick one." The model did it regardless. That is the point: an Action Input is written
by the MODEL, so `account=X` proves only that the model picked X. Attribution has to
be checked against what the user actually wrote, deterministically, or the guarantee
is only as good as the model's instruction-following.

What is and is not measured
---------------------------
`_attributable` and `_guard_account` are pure functions of their inputs — these are
real correctness tests. What they cannot measure is how often a given model invents
an account; that is a live-model question. What they establish is that when it does,
nothing is written.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def wallet(finance, finance_fixture):
    finance.create_account("BDO Credit Card", "credit", 0.0, "PHP")
    return {a["name"]: a["id"] for a in finance.list_accounts()}


@pytest.fixture
def plans(finance, wallet):
    return {"debt": finance.create_debt("Car Loan", 200000.0),
            "goal": finance.create_goal("Emergency Fund", 50000.0)}


# --------------------------------------------------------------------------- #
# The reported bug
# --------------------------------------------------------------------------- #
def test_a_debt_payment_with_no_account_named_writes_nothing(core, finance, wallet, plans):
    """The exact reported case. The model supplies an account the user never
    mentioned; the tool must refuse and nothing may move."""
    before = len(finance.list_transactions())
    balance_before = finance.account_balance(wallet["BPI Checking"])

    obs, data = core._tool_record_activity(
        "type=debt; target=Car Loan; action=payment; amount=100000; account=BPI Checking",
        user_text="i paid off 100k off my car loan",
    )

    assert data["error"] == "account_not_specified"
    assert len(finance.list_transactions()) == before
    assert finance.account_balance(wallet["BPI Checking"]) == balance_before
    assert "Clarification" in obs, "the agent must be steered to ask, not to retry"


def test_the_refusal_names_the_options_the_user_can_choose_from(core, wallet, plans):
    obs, _data = core._tool_record_activity(
        "type=debt; target=Car Loan; action=payment; amount=100000; account=BPI Checking",
        user_text="i paid off 100k off my car loan",
    )
    assert "BPI Checking" in obs and "Cash" in obs


def test_an_account_the_user_did_name_is_accepted(core, finance, wallet, plans):
    """The control. Over-refusing would make the agent useless — the guardrail has
    to distinguish an invented account from a stated one."""
    _obs, data = core._tool_record_activity(
        "type=debt; target=Car Loan; action=payment; amount=3000; account=BPI Checking",
        user_text="i paid 3000 on my car loan from BPI Checking",
    )
    assert data.get("error") is None
    assert data["account"] == "BPI Checking"


@pytest.mark.parametrize("said,expected", [
    ("i spent 1000 on food using the BDO card", "BDO Credit Card"),
    ("i paid 500 from BPI", "BPI Checking"),
    ("i paid 200 cash", "Cash"),
    ("charge 300 to my bdo", "BDO Credit Card"),
])
def test_loose_but_genuine_references_are_attributable(core, finance, wallet,
                                                       said, expected):
    """Users name accounts loosely. Attribution matches on the DISTINCTIVE word, so
    "the BDO card" attributes to "BDO Credit Card" without the user having to say
    the full name."""
    _obs, data = core._tool_add_expense(f"amount=100; account={expected}",
                                        user_text=said)
    assert data.get("error") is None, said
    assert data["account"] == expected


def test_a_generic_word_alone_does_not_attribute(core, finance, wallet):
    """"my card" is shared by every card in the wallet. Treating it as naming one
    would put the choice back in the model's hands, which is the bug."""
    _obs, data = core._tool_add_expense(
        "amount=100; account=BDO Credit Card", user_text="i spent 100 on my card")
    assert data["error"] == "account_not_specified"


def test_an_account_named_in_an_earlier_user_message_still_counts(core, finance, wallet):
    """Multi-turn: the user says which account, then follows up. Forgetting across
    the turn would make the agent ask the same question repeatedly."""
    _obs, data = core._tool_add_expense(
        "amount=100; account=BDO Credit Card",
        user_text="i spent 100 more  use my BDO card for everything this week",
    )
    assert data.get("error") is None


def test_the_agents_own_earlier_mention_does_not_count_as_the_user_choosing(core):
    """Only USER messages feed attribution. If the agent's own previous answer
    counted, a single wrong guess would justify itself for the rest of the
    conversation — the error would compound instead of surfacing."""
    import inspect

    src = inspect.getsource(core.agent_stream)
    assert 'in ("me", "user", "human")' in src, (
        "user_text must be built from user messages only")


# --------------------------------------------------------------------------- #
# Applies to every write tool, not just the one that was reported
# --------------------------------------------------------------------------- #
def test_an_expense_with_an_invented_account_writes_nothing(core, finance, wallet):
    before = len(finance.list_transactions())
    _obs, data = core._tool_add_expense(
        "amount=500; account=BPI Checking", user_text="i spent 500 on lunch")
    assert data["error"] == "account_not_specified"
    assert len(finance.list_transactions()) == before


def test_income_into_an_invented_account_writes_nothing(core, finance, wallet):
    before = len(finance.list_transactions())
    _obs, data = core._tool_add_income(
        "amount=30000; account=BPI Checking", user_text="i got my salary")
    assert data["error"] == "account_not_specified"
    assert len(finance.list_transactions()) == before


def test_a_transfer_with_an_invented_side_writes_nothing(core, finance, wallet):
    """Both ends of a transfer are real accounts; inventing either moves money the
    user did not authorize."""
    before = len(finance.list_transactions())
    _obs, data = core._tool_transfer_money(
        "amount=5000; from=BPI Checking; to=Cash", user_text="move 5000 over")
    assert data["error"] == "account_not_specified"
    assert len(finance.list_transactions()) == before


def test_a_goal_deposit_with_an_invented_account_writes_nothing(core, finance, wallet, plans):
    before = len(finance.list_transactions())
    _obs, data = core._tool_record_activity(
        "type=goal; target=Emergency Fund; action=deposit; amount=2000; account=Cash",
        user_text="i put 2000 into my emergency fund",
    )
    assert data["error"] == "account_not_specified"
    assert len(finance.list_transactions()) == before


# --------------------------------------------------------------------------- #
# Not over-strict
# --------------------------------------------------------------------------- #
def test_a_single_account_wallet_does_not_need_naming(core, finance, finance_fixture):
    """With one usable account there is no other choice to get wrong, so demanding
    the user name it would be pedantic rather than protective."""
    # Archive rather than delete: the fixture's accounts carry transactions and
    # `delete_account` correctly refuses those. Archiving is how a real user retires
    # an account, and `list_accounts()` excludes archived ones — the same pool the
    # guardrail sees.
    for a in finance.list_accounts():
        if a["name"] != "Cash":
            finance.update_account(a["id"], {"archived": 1})
    assert len(finance.list_accounts()) == 1

    _obs, data = core._tool_add_expense("amount=100; account=Cash",
                                        user_text="i spent 100 on lunch")
    assert data.get("error") is None


def test_attribution_is_skipped_when_no_user_text_is_available(core, finance, wallet):
    """Direct/API callers that do not go through the chat loop pass no user text.
    They must keep working — the guardrail protects the AGENT path, and silently
    failing every other caller would be a worse bug than the one it fixes."""
    _obs, data = core._tool_add_expense("amount=100; account=Cash")
    assert data.get("error") is None


# --------------------------------------------------------------------------- #
# End to end through the real loop
# --------------------------------------------------------------------------- #
def test_the_loop_refuses_and_can_then_clarify(core, finance, wallet, plans, monkeypatch):
    """The whole point: the run ends in a question with the ledger untouched."""
    replies = iter([
        "Thought: record it.\nAction: record_activity\n"
        "Action Input: type=debt; target=Car Loan; action=payment; amount=100000; account=BPI Checking",
        "Thought: I must not choose for them.\n"
        "Clarification: Which account should I take the 100,000 from?",
    ])

    def fake_chat(**kw):
        text = next(replies, "Thought: done.\nFinal Answer: ok")
        if kw.get("stream"):
            return iter([{"message": {"content": text}}])
        return {"message": {"content": text}}

    monkeypatch.setattr(core, "_chat", fake_chat)
    monkeypatch.setattr(core, "_embed", lambda t: None)

    before = len(finance.list_transactions())
    events = list(core.agent_stream("i paid off 100k off my car loan", core.AGENT_MODEL))

    assert [e["type"] for e in events if e["type"] != "token"][-1] == "clarify"
    assert len(finance.list_transactions()) == before
    assert not (events[-1].get("writes") or [])
