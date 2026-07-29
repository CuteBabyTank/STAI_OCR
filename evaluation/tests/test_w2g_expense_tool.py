"""
W2-G — the conversational expense-entry tool (`add_expense`) and its resolvers.

Why this file exists
--------------------
`add_expense` is the agent's only tool that MUTATES the ledger. Every other tool can
be wrong and merely give a bad answer; this one can be wrong and leave money recorded
against the wrong account. So the tests are weighted toward what it REFUSES to do.

What is and is not being measured
---------------------------------
The resolver tests are real correctness evidence — no model is involved in
`resolve_account` / `resolve_category` at all, so these measure the actual matching
behaviour a user will hit.

The `agent_stream` tests stub `_chat`, so they verify that **a model choosing
add_expense causes exactly the right write, and that a refusal is recoverable**. They
are not a measurement of how often a real model picks the right tool for "i spent
1000 on food" — that is a live-model W3 routing question and cannot be faked here.
The routing cases are defined in `datasets/trajectory_cases.json` for that run.
"""

from __future__ import annotations

import pytest


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def wallet(finance, finance_fixture):
    """The seeded fixture plus two realistically-named cards, so account matching is
    exercised against names a user would actually type ("the BDO card") rather than
    against the fixture's tidy ones. Returns name -> id."""
    finance.create_account("BDO Credit Card", "credit", 0.0, "PHP")
    finance.create_account("UnionBank Credit", "credit", 0.0, "PHP")
    return {a["name"]: a["id"] for a in finance.list_accounts()}


def _drain(core, question: str, **kwargs) -> list[dict]:
    return list(core.agent_stream(question, core.AGENT_MODEL, **kwargs))


@pytest.fixture
def scripted_model(core, monkeypatch):
    """Stub `_chat` with a scripted ReAct reply sequence. The real tool path still
    runs — only the model is fake."""

    def _install(*replies: str):
        react_replies = list(replies)
        react_calls = 0

        def fake_chat(**kwargs):
            nonlocal react_calls
            prompt = kwargs["messages"][0]["content"]
            if "SQL expert" in prompt:
                text = "SELECT SUM(total_amount) AS total_amount FROM receipts"
            elif "Findings:" in prompt:  # _force_final salvage prompt
                text = "Done."
            else:
                text = react_replies[min(react_calls, len(react_replies) - 1)]
                react_calls += 1
            if kwargs.get("stream"):
                return iter([{"message": {"content": text}}])
            return {"message": {"content": text}}

        monkeypatch.setattr(core, "_chat", fake_chat)
        monkeypatch.setattr(core, "_embed", lambda text: None)

    return _install


# --------------------------------------------------------------------------- #
# resolve_account — the guardrail that matters most
# --------------------------------------------------------------------------- #
def test_a_loose_account_reference_resolves_to_one_account(finance, wallet):
    """"the BDO card" is how a user names an account; "BDO Credit Card" is how the
    database does. The gap between the two is the whole point of the resolver."""
    res = finance.resolve_account("the BDO card")
    assert res["status"] == "ok"
    assert res["account"]["name"] == "BDO Credit Card"


def test_a_possessive_reference_resolves(finance, wallet):
    res = finance.resolve_account("my unionbank card")
    assert res["status"] == "ok"
    assert res["account"]["name"] == "UnionBank Credit"


def test_an_exact_name_wins_over_a_longer_name_containing_it(finance, wallet):
    """"Credit Card" is both an account in its own right and a substring of "BDO
    Credit Card". An exact match must not be reported as ambiguous, or the user could
    never name that account at all."""
    res = finance.resolve_account("Credit Card")
    assert res["status"] == "ok"
    assert res["account"]["name"] == "Credit Card"


def test_a_reference_matching_several_accounts_is_ambiguous_not_a_guess(finance, wallet):
    """"credit" matches three accounts. Picking one would silently charge the wrong
    card — the resolver must hand the decision back."""
    res = finance.resolve_account("credit")
    assert res["status"] == "ambiguous"
    names = {c["name"] for c in res["candidates"]}
    assert names == {"Credit Card", "BDO Credit Card", "UnionBank Credit"}


def test_an_unknown_account_is_not_silently_defaulted(finance, wallet):
    """`parse_quick_text` falls back to `accounts[0]` for the UI draft, which the user
    sees and can correct. The agent has no such confirmation step, so the resolver
    must never do that."""
    res = finance.resolve_account("Metrobank")
    assert res["status"] == "not_found"
    assert res["candidates"], "the caller needs the real names to ask the user with"


def test_an_archived_account_is_not_a_candidate(finance, wallet):
    """The fixture archives 'Archived Wallet'. Archived accounts are out of use, so
    recording against one would hide the expense from the user's own views."""
    res = finance.resolve_account("Archived Wallet")
    assert res["status"] == "not_found"


# --------------------------------------------------------------------------- #
# resolve_category
# --------------------------------------------------------------------------- #
def test_miscellaneous_maps_to_the_other_category(finance, finance_fixture):
    """There is no "Miscellaneous" category — the seeded taxonomy calls it "Other".
    A user saying "put it under miscellaneous" means Other and should not be refused
    on vocabulary."""
    res = finance.resolve_category("miscellaneous")
    assert res["status"] == "ok"
    assert res["category"]["name"] == "Other"


def test_an_alias_inside_a_longer_phrase_resolves(finance, finance_fixture):
    res = finance.resolve_category("put it under misc")
    assert res["status"] == "ok"
    assert res["category"]["name"] == "Other"


def test_a_real_category_name_resolves_exactly(finance, finance_fixture):
    assert finance.resolve_category("Food")["category"]["name"] == "Food"


def test_an_income_category_is_not_reachable_as_an_expense_category(finance, finance_fixture):
    """"Salary" is an income category. Filing an expense under it would corrupt every
    income/expense split downstream."""
    assert finance.resolve_category("Salary", kind="expense")["status"] == "not_found"


def test_an_unknown_category_returns_the_valid_list(finance, finance_fixture):
    res = finance.resolve_category("crypto mining rig")
    assert res["status"] == "not_found"
    assert {c["name"] for c in res["candidates"]} >= {"Food", "Other"}


# --------------------------------------------------------------------------- #
# Action Input parsing — the model drifts between formats, all must land
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw",
    [
        "amount=1000; account=BDO Credit Card; category=Food",
        'amount: 1000; account: BDO Credit Card; category: Food',
        '{"amount": 1000, "account": "BDO Credit Card", "category": "Food"}',
    ],
)
def test_every_action_input_format_parses_to_the_same_fields(core, raw):
    parsed = core._parse_expense_input(raw)
    assert str(parsed["amount"]).strip() in ("1000", "1000.0")
    assert parsed["account"] == "BDO Credit Card"
    assert parsed["category"] == "Food"


def test_free_text_still_yields_an_amount(core):
    """A model that ignores the key=value instruction entirely should not cost the
    user a failed turn when the request is unambiguous."""
    parsed = core._parse_expense_input("1000 on food using the BDO card")
    assert parsed["amount"] is None          # no explicit key...
    assert parsed["raw"] == "1000 on food using the BDO card"  # ...but the raw text carries it


# --------------------------------------------------------------------------- #
# _tool_add_expense — the write path and its refusals
# --------------------------------------------------------------------------- #
def test_recording_an_expense_creates_exactly_one_transaction(core, finance, wallet):
    before = len(finance.list_transactions())
    obs, data = core._tool_add_expense("amount=1000; account=the BDO card; category=Food")

    assert data["kind"] == "txn"
    assert len(finance.list_transactions()) == before + 1

    txn = finance.get_transaction(data["transaction_id"])
    assert txn["kind"] == "expense"
    assert txn["amount"] == 1000.0
    assert txn["account_id"] == wallet["BDO Credit Card"]
    assert "1,000.00" in obs and "BDO Credit Card" in obs


def test_the_recorded_expense_lands_in_the_named_category(core, finance, wallet):
    _obs, data = core._tool_add_expense(
        "amount=500; account=my unionbank card; category=miscellaneous"
    )
    assert data["category"] == "Other"
    txn = finance.get_transaction(data["transaction_id"])
    cats = {c["id"]: c["name"] for c in finance.list_categories()}
    assert cats[txn["category_id"]] == "Other"


def test_the_expense_moves_the_named_accounts_balance(core, finance, wallet):
    """The observation reports a balance; it must be the real post-write balance, not
    a number the model could contradict."""
    before = finance.account_balance(wallet["BDO Credit Card"])
    _obs, data = core._tool_add_expense("amount=250; account=BDO Credit Card")
    after = finance.account_balance(wallet["BDO Credit Card"])
    assert after == pytest.approx(before - 250)
    assert data["balance"] == pytest.approx(after)


def test_an_expense_with_no_category_is_uncategorized_not_defaulted(core, finance, wallet):
    """Filing an unstated category under a guess would corrupt budget totals. Leaving
    it null matches what `post_receipt_as_expense` does with an unmatched category."""
    _obs, data = core._tool_add_expense("amount=99; account=Cash")
    assert data["category"] is None
    assert finance.get_transaction(data["transaction_id"])["category_id"] is None


def test_an_ambiguous_account_records_nothing(core, finance, wallet):
    before = len(finance.list_transactions())
    obs, data = core._tool_add_expense("amount=1000; account=credit")
    assert data["error"] == "ambiguous_account"
    assert len(finance.list_transactions()) == before, "nothing may be written on a refusal"
    assert "BDO Credit Card" in obs, "the agent needs the candidates to ask with"


def test_an_unknown_account_records_nothing_and_lists_the_real_ones(core, finance, wallet):
    before = len(finance.list_transactions())
    obs, data = core._tool_add_expense("amount=1000; account=Metrobank")
    assert data["error"] == "unknown_account"
    assert len(finance.list_transactions()) == before
    assert "Cash" in obs


def test_an_unknown_category_records_nothing(core, finance, wallet):
    """Recording under the wrong bucket silently is worse than one clarifying turn."""
    before = len(finance.list_transactions())
    obs, data = core._tool_add_expense("amount=100; account=Cash; category=Vacations")
    assert data["error"] == "unknown_category"
    assert len(finance.list_transactions()) == before
    assert "Food" in obs, "the valid categories must come back for the retry"


def test_an_expense_with_no_readable_amount_records_nothing(core, finance, wallet):
    before = len(finance.list_transactions())
    _obs, data = core._tool_add_expense("account=Cash; category=Food")
    assert data["error"] == "no_amount"
    assert len(finance.list_transactions()) == before


def test_an_absurd_amount_is_refused_rather_than_recorded(core, finance, wallet):
    """D4 precedent: Quick Chat once read "250 milk" as ₱250,000,000. An amount
    arriving from free text needs a ceiling, and crossing it is a question for the
    user — not a silent ₱250M ledger entry."""
    before = len(finance.list_transactions())
    obs, data = core._tool_add_expense("amount=250000000; account=Cash")
    assert data["error"] == "amount_too_large"
    assert len(finance.list_transactions()) == before
    assert "confirm" in obs.lower()


def test_a_zero_or_negative_amount_is_refused(core, finance, wallet):
    """`finance._parse_amount`'s regex captures digits only and drops the sign, so
    "-50" reaches `create_transaction` as a positive 50 and sails past its
    `amount <= 0` guard. Found by this test: the sign has to be caught at the text,
    before the number is parsed. Same family as D4/D6 — a malformed input the happy
    path never happened to try."""
    for bad in ("amount=0; account=Cash", "amount=-50; account=Cash"):
        before = len(finance.list_transactions())
        _obs, data = core._tool_add_expense(bad)
        assert data.get("error") == "no_amount", bad
        assert len(finance.list_transactions()) == before, bad


def test_a_relative_date_is_honoured(core, finance, wallet):
    from datetime import date, timedelta

    _obs, data = core._tool_add_expense("amount=100; account=Cash; date=yesterday")
    assert data["occurred_at"] == (date.today() - timedelta(days=1)).isoformat()


def test_an_expense_defaults_to_today(core, finance, wallet):
    from datetime import date

    _obs, data = core._tool_add_expense("amount=100; account=Cash")
    assert data["occurred_at"] == date.today().isoformat()


# --------------------------------------------------------------------------- #
# list_accounts — the read-only lookup that precedes a write
# --------------------------------------------------------------------------- #
def test_list_accounts_names_the_real_accounts_and_categories(core, wallet):
    obs, data = core._tool_list_accounts()
    assert data["kind"] == "accounts"
    assert "BDO Credit Card" in obs and "Cash" in obs
    assert "Food" in obs
    assert "Salary" not in obs, "income categories cannot receive an expense"


# --------------------------------------------------------------------------- #
# The real agent_stream loop
# --------------------------------------------------------------------------- #
def test_the_agent_records_an_expense_end_to_end(core, finance, wallet, scripted_model):
    """The user's own phrasing, driven through the real loop: one action, one write,
    one final answer."""
    scripted_model(
        "Thought: A statement of a purchase, so I record it.\n"
        "Action: add_expense\n"
        "Action Input: amount=1000; account=the BDO card; category=Food",
        "Thought: Recorded.\nFinal Answer: Recorded 1,000.00 for Food on your BDO Credit Card.",
    )
    before = len(finance.list_transactions())
    events = _drain(core, "i spent 1000 on food using the BDO card")

    kinds = [e["type"] for e in events if e["type"] != "token"]
    assert kinds == ["start", "action", "observation", "final"]
    assert len(finance.list_transactions()) == before + 1

    obs = next(e for e in events if e["type"] == "observation")
    assert obs["data"]["kind"] == "txn"
    assert obs["data"]["account"] == "BDO Credit Card"
    assert obs["data"]["category"] == "Food"
    assert obs["data"]["amount"] == 1000.0


def test_the_second_worked_example_records_under_other(core, finance, wallet, scripted_model):
    scripted_model(
        "Thought: Record it.\n"
        "Action: add_expense\n"
        "Action Input: amount=500; account=my unionbank card; category=miscellaneous",
        "Thought: Done.\nFinal Answer: Recorded 500.00 on your UnionBank Credit under Other.",
    )
    _drain(core, "i spent 500 using my unionbank card, put it under miscellaneous")

    txns = finance.list_transactions()
    newest = txns[0]
    cats = {c["id"]: c["name"] for c in finance.list_categories()}
    assert newest["amount"] == 500.0
    assert newest["account_id"] == wallet["UnionBank Credit"]
    assert cats[newest["category_id"]] == "Other"


def test_a_refused_account_lets_the_agent_recover_without_writing_twice(
    core, finance, wallet, scripted_model
):
    """The first call is ambiguous, the agent looks the accounts up and retries with a
    specific name. Exactly one transaction may exist at the end.

    The user's question names "BDO" because the account-attribution guardrail
    (W2-K) requires it: the retry resolves to *BDO Credit Card*, and an account the
    user never mentioned is refused no matter how the model phrases the Action
    Input. Previously the question said only "the credit card", which matches three
    accounts — under the current contract that request can only ever end in a
    question to the user, so it could no longer exercise the recovery path."""
    scripted_model(
        "Thought: Record it.\nAction: add_expense\nAction Input: amount=1000; account=credit",
        "Thought: Ambiguous — check the real names.\nAction: list_accounts\nAction Input: -",
        "Thought: They meant the BDO one.\n"
        "Action: add_expense\n"
        "Action Input: amount=1000; account=BDO Credit Card",
        "Thought: Recorded.\nFinal Answer: Recorded 1,000.00 on your BDO Credit Card.",
    )
    before = len(finance.list_transactions())
    events = _drain(core, "i spent 1000 on my BDO credit card")

    assert len(finance.list_transactions()) == before + 1, "the refusal must not have written"
    txn_obs = [e for e in events if e["type"] == "observation"
               and e["data"].get("kind") == "txn"]
    assert len(txn_obs) == 1
    assert txn_obs[0]["data"]["account"] == "BDO Credit Card"


def test_the_agent_can_ask_instead_of_charging_an_unnamed_account(
    core, finance, wallet, scripted_model
):
    """No account named, and which one it hits changes the balances — the loop must be
    able to terminate in a question with nothing written."""
    scripted_model(
        "Thought: They named no account and I must not pick one.\n"
        "Clarification: Which account should I charge the 300 to?"
    )
    before = len(finance.list_transactions())
    events = _drain(core, "i spent 300 on groceries")

    assert [e["type"] for e in events if e["type"] != "token"] == ["start", "clarify"]
    assert len(finance.list_transactions()) == before


def test_a_repeated_add_expense_call_does_not_double_charge(
    core, finance, wallet, scripted_model
):
    """The loop's dedup cache exists to save a redundant read. On the write tool it is
    load-bearing: a model that emits the same Action twice must not bill the user
    twice."""
    same = ("Thought: Record it.\n"
            "Action: add_expense\n"
            "Action Input: amount=1000; account=BDO Credit Card")
    scripted_model(same, same, same, same)
    before = len(finance.list_transactions())
    _drain(core, "i spent 1000 on the bdo card")

    assert len(finance.list_transactions()) == before + 1


def test_a_question_about_spending_still_routes_to_sql(core, finance, wallet, scripted_model):
    """Regression guard on the prompt change: adding a write tool must not make the
    agent record an expense when the user only asked a question."""
    scripted_model(
        "Thought: A question about recorded spending.\n"
        "Action: sql_ledger\nAction Input: total spend across all receipts",
        "Thought: I have it.\nFinal Answer: You've spent 1,585.00.",
    )
    before = len(finance.list_transactions())
    events = _drain(core, "how much did I spend on food?")

    assert len(finance.list_transactions()) == before, "a question must never write"
    assert all(e["data"].get("kind") != "txn"
               for e in events if e["type"] == "observation")


def test_a_finance_error_becomes_a_recoverable_observation(core, finance, wallet, monkeypatch):
    """A validation failure inside finance must not kill the run and lose the rest of
    the conversation."""
    def boom(*a, **k):
        raise finance.FinanceError("Source account not found")

    monkeypatch.setattr(finance, "create_transaction", boom)
    obs, data = core._run_agent_tool(
        "add_expense", "amount=100; account=Cash", core.AGENT_MODEL, None
    )
    assert data["kind"] == "error"
    assert "could not be recorded" in obs


def test_the_tool_dispatcher_knows_all_four_tools(core):
    """The unknown-tool message is what steers a model that hallucinated a tool name,
    so it must stay in sync with the dispatcher."""
    obs, _data = core._run_agent_tool("teleport", "x", core.AGENT_MODEL, None)
    for tool in ("sql_ledger", "search_receipts", "list_accounts", "add_expense"):
        assert tool in obs
