"""
W2-G adversarial — attacks on the `add_expense` write tool, its resolvers, and the
clarification paths around it.

Why this file exists
--------------------
`test_w2g_expense_tool.py` walks the happy path and the refusals the tool was designed
to make. This file goes the other way: it assumes the tool is wrong and tries to make
it move money it should not, or move the right money to the wrong place. Each test
below states, in its docstring, what a user loses in pesos if it fails.

What is and is not being measured
---------------------------------
The resolver and parser tests involve no model at all — they are real correctness
evidence for the code a user's phrasing actually hits.

The `agent_stream` tests stub `_chat` with a scripted ReAct transcript. That measures
**what the loop does when a model behaves a given way** — the dedup cache, the step
budget, the clarify/write interaction, the event stream. It is NOT a measurement of how
often a real model behaves that way; every script below is a transcript a small local
model can plausibly emit (re-ordered key=value pairs, a copied thousands separator, a
second-guess after a write), but the frequency question needs a live model (W3).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def wallet(finance, finance_fixture):
    """Same two realistically-named cards as the happy-path suite, so findings here
    are directly comparable with the ones there. Returns name -> id."""
    finance.create_account("BDO Credit Card", "credit", 0.0, "PHP")
    finance.create_account("UnionBank Credit", "credit", 0.0, "PHP")
    return {a["name"]: a["id"] for a in finance.list_accounts()}


def _drain(core, question: str, **kwargs) -> list[dict]:
    return list(core.agent_stream(question, core.AGENT_MODEL, **kwargs))


def _no_tokens(events: list[dict]) -> list[str]:
    return [e["type"] for e in events if e["type"] != "token"]


@pytest.fixture
def scripted_model(core, monkeypatch):
    """Stub `_chat` with a scripted ReAct reply sequence. The real tool path still
    runs — only the model is fake.

    `salvage` controls what the `_force_final` rescue prompt gets: a string to answer
    with, or an exception instance to raise (Ollama unreachable mid-run, which is the
    normal reason the loop never got a Final Answer in the first place).
    """

    def _install(*replies: str, salvage="Done."):
        react_replies = list(replies)
        state = {"calls": 0, "salvage_calls": 0}

        def fake_chat(**kwargs):
            prompt = kwargs["messages"][0]["content"]
            if "SQL expert" in prompt:
                text = "SELECT SUM(total_amount) AS total_amount FROM receipts"
            elif "Findings:" in prompt:  # _force_final salvage prompt
                state["salvage_calls"] += 1
                if isinstance(salvage, BaseException):
                    raise salvage
                text = salvage
            else:
                text = react_replies[min(state["calls"], len(react_replies) - 1)]
                state["calls"] += 1
            if kwargs.get("stream"):
                return iter([{"message": {"content": text}}])
            return {"message": {"content": text}}

        monkeypatch.setattr(core, "_chat", fake_chat)
        monkeypatch.setattr(core, "_embed", lambda text: None)
        return state

    return _install


# --------------------------------------------------------------------------- #
# Double-charge: the dedup cache is keyed on the literal Action Input
# --------------------------------------------------------------------------- #
def test_a_reordered_action_input_does_not_double_charge(
    core, finance, wallet, scripted_model
):
    """The loop dedups on `(tool, input.strip().lower())`. Two Action Inputs that
    describe the SAME expense but list the keys in a different order are different
    strings, so both run and both write.

    A model that re-emits its action in a normalised order — very common when it
    "double-checks" itself — bills the user twice for one purchase. Nothing downstream
    catches it: there is no idempotency key, no same-run write counter, and the Final
    Answer confirms a single expense."""
    scripted_model(
        "Thought: Record it.\nAction: add_expense\nAction Input: amount=1000; account=Cash",
        "Thought: Let me confirm the fields are right.\n"
        "Action: add_expense\nAction Input: account=Cash; amount=1000",
        "Thought: Recorded.\nFinal Answer: Recorded 1,000.00 on your Cash account.",
    )
    before = len(finance.list_transactions())
    _drain(core, "i spent 1000 using cash")

    assert len(finance.list_transactions()) == before + 1, (
        "one purchase must produce one transaction, however the model re-phrased the "
        "Action Input"
    )


def test_a_whitespace_variant_of_the_same_write_does_not_double_charge(
    core, finance, wallet, scripted_model
):
    """Same defect, cheaper trigger: only the spacing around the separator differs.
    `.strip().lower()` normalises case and the ends of the string, but nothing inside
    it, so `amount=1000;account=Cash` and `amount=1000; account=Cash` are two keys and
    two writes — ₱2,000 charged for a ₱1,000 lunch."""
    scripted_model(
        "Thought: Record it.\nAction: add_expense\nAction Input: amount=1000; account=Cash",
        "Thought: Retry with tighter formatting.\n"
        "Action: add_expense\nAction Input: amount=1000;account=Cash",
        "Thought: Recorded.\nFinal Answer: Recorded 1,000.00 on Cash.",
    )
    before = len(finance.list_transactions())
    _drain(core, "i spent 1000 using cash")

    assert len(finance.list_transactions()) == before + 1


def test_an_identical_repeat_is_still_deduped(core, finance, wallet, scripted_model):
    """Control for the two tests above: the cache does work on an exact repeat, so the
    defect is specifically the key's sensitivity to formatting, not a missing cache."""
    same = ("Thought: Record it.\n"
            "Action: add_expense\nAction Input: amount=1000; account=Cash")
    scripted_model(same, same, same, same)
    before = len(finance.list_transactions())
    _drain(core, "i spent 1000 using cash")

    assert len(finance.list_transactions()) == before + 1


# --------------------------------------------------------------------------- #
# Amount parsing
# --------------------------------------------------------------------------- #
def test_a_thousands_separator_in_the_amount_is_not_truncated(core, finance, wallet):
    """`_KV_RE`'s value group is `[^;,]+` — it stops at a comma. So `amount=1,000.50`
    parses to the string "1" and ₱1.00 is recorded instead of ₱1,000.50.

    This is not a hypothetical format: the tool's OWN observation prints amounts with
    `{:,.2f}` ("Recorded expense #41: 1,000.00 on ..."), and the ReAct prompt shows
    that observation to the model. A model that retries after a refusal by copying the
    number it just saw writes a comma — and under-records the expense by 99.9%."""
    _obs, data = core._tool_add_expense("amount=1,000.50; account=Cash; category=Food")
    assert data.get("kind") == "txn", data
    assert data["amount"] == pytest.approx(1000.50), (
        f"recorded {data['amount']} for an expense of 1,000.50"
    )


def test_the_json_form_of_the_same_amount_is_parsed_correctly(core, finance, wallet):
    """Control: the JSON branch does not go through `_KV_RE`, so the identical amount
    survives there. The bug is in the key=value parser the prompt actually asks for."""
    _obs, data = core._tool_add_expense('{"amount": "1,000.50", "account": "Cash"}')
    assert data["amount"] == pytest.approx(1000.50)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("amount=1.2k; account=Cash", 1200.0),
        ("amount=₱1000; account=Cash", 1000.0),   # unicode peso sign
        ("amount= 250 ; account=Cash", 250.0),
    ],
)
def test_amount_shorthands_survive(core, finance, wallet, raw, expected):
    """Probes, not accusations: these three shorthands round-trip correctly today."""
    _obs, data = core._tool_add_expense(raw)
    assert data["amount"] == pytest.approx(expected)


@pytest.mark.parametrize("raw", ["", "   ", "-", "account=Cash; category=Food"])
def test_an_unparseable_input_writes_nothing(core, finance, wallet, raw):
    before = len(finance.list_transactions())
    _obs, data = core._tool_add_expense(raw)
    assert data.get("kind") != "txn", raw
    assert len(finance.list_transactions()) == before, raw


def test_a_free_text_expense_containing_a_hyphenated_date_is_not_called_negative(
    core, finance, wallet
):
    """`_NEGATIVE_AMOUNT_RE` is applied to the WHOLE raw string whenever no explicit
    `amount=` key was given. An ISO date anywhere in that string ("2026-06-01") looks
    like `-0` to it, so a perfectly valid free-text expense is refused as a refund and
    the user is asked a pointless question."""
    _obs, data = core._tool_add_expense("spent 500 at cash on 2026-06-01")
    assert not data.get("negative"), (
        "an ISO date is not a minus sign; the refusal message tells the user their "
        "amount was negative when it was 500"
    )


def test_a_real_negative_amount_is_still_refused(core, finance, wallet):
    """Control for the test above — the guard itself is correct and must stay."""
    _obs, data = core._tool_add_expense("amount=-50; account=Cash")
    assert data.get("error") == "no_amount"


# --------------------------------------------------------------------------- #
# Account resolution — a confidently WRONG single match is worse than ambiguity
# --------------------------------------------------------------------------- #
def test_the_bdo_card_is_not_charged_to_a_plain_bdo_account(core, finance, wallet):
    """The driving use case, against a realistic wallet: a BDO savings account AND a
    BDO credit card.

    `_match_by_name`'s `tier_substring` tests `name in query`, so the SHORT name "BDO"
    matches the phrase "the BDO card" while the long name "BDO Credit Card" does not.
    Only one row is in that tier, so `resolve_account` reports `ok` — a confident wrong
    answer, not an ambiguity the user gets asked about. ₱1,000 lands on the savings
    account the user never mentioned, and the card they used shows nothing."""
    finance.create_account("BDO", "debit", 0.0, "PHP")
    res = finance.resolve_account("the BDO card")
    assert not (res["status"] == "ok" and res["account"]["name"] == "BDO"), (
        "'the BDO card' resolved confidently to the debit account 'BDO'"
    )


def test_the_write_tool_does_not_record_the_bdo_card_against_plain_bdo(
    core, finance, wallet
):
    """The same defect at the point where it costs money."""
    finance.create_account("BDO", "debit", 0.0, "PHP")
    _obs, data = core._tool_add_expense(
        "amount=1000; account=the BDO card; category=Food"
    )
    assert data.get("account") != "BDO", (
        f"recorded 1,000.00 on {data.get('account')!r} when the user said "
        "'the BDO card'"
    )


def test_an_account_literally_named_card_does_not_swallow_every_card_reference(
    core, finance, wallet
):
    """Degenerate but legal name. "card" is in `_ACCOUNT_NOISE`, but noise words are
    only dropped when building `meaningful` — `tier_substring` runs BEFORE that tier
    and uses the raw query, so an account named "Card" matches every phrase containing
    the word "card" and wins outright."""
    finance.create_account("Card", "credit", 0.0, "PHP")
    res = finance.resolve_account("the BDO card")
    assert not (res["status"] == "ok" and res["account"]["name"] == "Card")


def test_two_similar_long_names_are_reported_as_ambiguous(core, finance, wallet):
    """Probe that passes: when NO short name is a substring of the phrase, the tiering
    does the right thing and hands the choice back to the user. This is what makes the
    two failures above a tiering bug rather than a general matching weakness."""
    finance.create_account("BDO Savings", "debit", 0.0, "PHP")
    assert finance.resolve_account("the BDO card")["status"] == "ambiguous"


def test_the_raw_fallback_does_not_take_an_account_name_out_of_the_note(
    core, finance, wallet
):
    """When `account=` fails to resolve, `_tool_add_expense` retries
    `resolve_account(raw, accounts)` over the ENTIRE Action Input — keys, category and
    note included. "note=paid cash" then substring-matches the "Cash" account.

    Result: the user said Metrobank, the tool cannot find Metrobank, and instead of
    refusing (which is what the guardrail exists for) it silently debits ₱100 from
    Cash. The observation reads like a success, so the agent confirms it."""
    before = len(finance.list_transactions())
    _obs, data = core._tool_add_expense("amount=100; account=Metrobank; note=paid cash")
    assert data.get("account") != "Cash", (
        "the unresolvable account was rescued by a word in the note"
    )
    assert len(finance.list_transactions()) == before


def test_the_raw_fallback_does_not_match_an_account_on_the_amount_digits(
    core, finance, wallet
):
    """People name accounts after the last digits of the card ("BPI 1000", "GCash 09").
    `tier_any_token` — the loosest tier — matches ANY token, and the raw fallback
    string contains the amount, so "amount=1000" selects "BPI 1000".

    The user named Metrobank, which does not exist; ₱1,000 is booked to BPI 1000
    because the number happened to appear twice in one string."""
    finance.create_account("BPI 1000", "debit", 0.0, "PHP")
    before = len(finance.list_transactions())
    _obs, data = core._tool_add_expense("amount=1000; account=Metrobank")
    assert data.get("account") != "BPI 1000", (
        "an account was chosen by matching the amount against its name"
    )
    assert len(finance.list_transactions()) == before


def test_an_unknown_account_with_a_plain_note_still_refuses(core, finance, wallet):
    """Control: with no account name hiding in the note, the raw fallback correctly
    finds nothing and the tool refuses. So the two failures above are the fallback
    over-reaching, not the refusal path being broken."""
    _obs, data = core._tool_add_expense("amount=100; account=Metrobank; note=lunch")
    assert data.get("error") == "unknown_account"


def test_an_archived_account_cannot_be_reached_through_the_raw_fallback(
    core, finance, wallet
):
    """Probe: `list_accounts()` excludes archived accounts on both the explicit and the
    fallback lookup, so 'Archived Wallet' stays unreachable from either."""
    _obs, data = core._tool_add_expense("amount=100; account=Archived Wallet")
    assert data.get("kind") != "txn"


# --------------------------------------------------------------------------- #
# Category
# --------------------------------------------------------------------------- #
def test_an_income_category_cannot_receive_an_expense_through_the_tool(
    core, finance, wallet
):
    """Probe: end-to-end version of the resolver test. An expense filed under "Salary"
    would corrupt every income/expense split downstream."""
    before = len(finance.list_transactions())
    _obs, data = core._tool_add_expense("amount=100; account=Cash; category=Salary")
    assert data.get("error") == "unknown_category"
    assert len(finance.list_transactions()) == before


def test_a_category_sharing_a_name_with_an_account_does_not_cross_over(
    core, finance, wallet
):
    """Probe: with an account also called "Food", the category resolver and the account
    resolver stay in their own pools."""
    finance.create_account("Food", "debit", 0.0, "PHP")
    _obs, data = core._tool_add_expense("amount=100; account=Cash; category=Food")
    assert data["account"] == "Cash" and data["category"] == "Food"


# --------------------------------------------------------------------------- #
# Date — the wrong date puts the expense in the wrong budget period
# --------------------------------------------------------------------------- #
def test_an_explicit_iso_date_is_honoured(core, finance, wallet):
    """`finance._parse_date` understands "yesterday" and "Jun 3" but has no ISO branch
    at all, and falls through to `date.today()`. A model asked for a date will
    overwhelmingly emit `date=2026-06-01`, and the expense is silently stamped today —
    landing in the wrong month's budget with no refusal and no warning."""
    _obs, data = core._tool_add_expense("amount=100; account=Cash; date=2026-06-01")
    assert data["occurred_at"] == "2026-06-01", (
        f"asked for 2026-06-01, recorded {data['occurred_at']}"
    )


def test_a_date_that_names_a_past_year_is_not_moved_into_the_future(
    core, finance, wallet
):
    """`_KV_RE` stops the value at the comma, so `date=Dec 20, 2025` reaches
    `_parse_date` as "Dec 20" with the year thrown away. `_parse_date` then assumes the
    CURRENT year and only rolls back when the result is >183 days ahead — so a December
    expense entered in July is filed in December of *this* year: a future-dated
    transaction the user never made yet."""
    _obs, data = core._tool_add_expense("amount=100; account=Cash; date=Dec 20, 2025")
    assert data["occurred_at"] <= date.today().isoformat(), (
        f"an expense the user already paid was dated {data['occurred_at']}, in the "
        "future"
    )


def test_a_note_is_not_scanned_for_a_date_when_no_date_was_given(
    core, finance, wallet
):
    """`_parse_date(parsed["date"] or raw)` runs the date scanner over the WHOLE Action
    Input when the model gave no `date=`. Any `<word> <number>` pair in the note whose
    word prefixes a month name becomes the transaction date — and "Marc" prefixes
    "March", so "dinner with marc 3 pax" is read as 3 March.

    The user recorded today's expense; it silently lands five months back, out of the
    current budget period and out of "this month's spend". The observation reports the
    backdated date, but the user only sees the agent's confirmation."""
    _obs, data = core._tool_add_expense(
        "amount=100; account=Cash; note=dinner with marc 3 pax"
    )
    assert data["occurred_at"] == date.today().isoformat(), (
        f"a note backdated the expense to {data['occurred_at']}"
    )


def test_relative_dates_still_work(core, finance, wallet):
    """Control: the date handling that does exist is intact."""
    _obs, data = core._tool_add_expense("amount=100; account=Cash; date=yesterday")
    assert data["occurred_at"] == (date.today() - timedelta(days=1)).isoformat()


# --------------------------------------------------------------------------- #
# Currency
# --------------------------------------------------------------------------- #
def test_a_foreign_currency_account_is_not_silently_treated_as_pesos(
    core, finance, wallet
):
    """`accounts` has a currency column; `transactions` does not. An expense recorded
    against a USD account is stored as a bare number and subtracted from a PHP net
    worth at 1:1.

    This test asserts the minimum honest behaviour: either refuse, or say the currency
    in the observation so the agent's confirmation can. Today it does neither — the
    user is told "Recorded 1,000.00 on US Wallet" and their net worth drops by ₱1,000
    for a $1,000 charge."""
    finance.create_account("US Wallet", "debit", 0.0, "USD")
    obs, data = core._tool_add_expense("amount=1000; account=US Wallet")
    assert data.get("kind") != "txn" or "USD" in obs, (
        "a non-PHP account was written to with no currency anywhere in the "
        "observation the user's confirmation is built from"
    )


# --------------------------------------------------------------------------- #
# Clarification path 1 — the pre-loop deterministic disambiguation
# --------------------------------------------------------------------------- #
def test_the_recent_receipt_disambiguation_still_fires_before_any_model_call(
    core, finance, wallet, monkeypatch
):
    """Regression guard for the write tool's arrival: `_RECENT_RECEIPT_RE` short-
    circuits the loop entirely when "recent receipt" is ambiguous. If a refactor ever
    moved it after the first `_chat`, an ambiguous question would start costing a model
    call — and with a write tool in the box, a model call is now a write risk."""
    def explode(**kwargs):
        raise AssertionError("the model must not be called on the pre-loop clarify path")

    monkeypatch.setattr(core, "_chat", explode)
    before = len(finance.list_transactions())
    events = _drain(core, "what's on my recent receipt?")

    assert _no_tokens(events) == ["start", "clarify"]
    assert len(finance.list_transactions()) == before
    assert events[-1]["steps"] == [{"clarify": events[-1]["question"]}]


def test_a_recording_request_naming_the_recent_receipt_writes_nothing(
    core, finance, wallet, monkeypatch
):
    """Interaction between the two features: a *statement* that also says "recent
    receipt" is caught by the pre-loop guard, so the deterministic clarify wins and
    nothing is written. That is the safe ordering and it must stay that way."""
    monkeypatch.setattr(core, "_chat", lambda **kw: (_ for _ in ()).throw(
        AssertionError("model called")))
    before = len(finance.list_transactions())
    events = _drain(core, "add the total from my recent receipt as an expense on Cash")

    assert _no_tokens(events) == ["start", "clarify"]
    assert len(finance.list_transactions()) == before


def test_the_pre_loop_clarify_leaves_no_open_mlflow_run(
    core, finance, wallet, monkeypatch
):
    """A documented past bug: an unguarded `mlflow.log_metric` auto-starts a run that
    the `finally` block (which keys off `_traced`) never closes, leaking one run per
    clarification. `_mlog_metric`/`_mlog_param` are the guarded helpers that fix it."""
    import mlflow

    monkeypatch.setattr(core, "_chat", lambda **kw: (_ for _ in ()).throw(
        AssertionError("model called")))
    _drain(core, "what's on my recent receipt?")
    assert mlflow.active_run() is None


# --------------------------------------------------------------------------- #
# Clarification path 2 — the agent-emitted `Clarification:`
# --------------------------------------------------------------------------- #
def test_a_recording_request_with_no_account_ends_in_a_question_and_no_write(
    core, finance, wallet, scripted_model
):
    """The PRD case. Nothing may be written and the run must end as a question, not as
    an answer, so the client renders a prompt rather than a confirmation."""
    scripted_model(
        "Thought: No account named and I must not pick one.\n"
        "Clarification: Which account should I charge the 300 to?"
    )
    before = len(finance.list_transactions())
    events = _drain(core, "i spent 300 on groceries")

    assert _no_tokens(events) == ["start", "clarify"]
    assert len(finance.list_transactions()) == before


def test_an_ambiguous_account_refusal_is_actionable_and_the_clarify_writes_nothing(
    core, finance, wallet, scripted_model
):
    """The refusal observation has to carry the candidate names, or the agent's follow-
    up question cannot list the options and the user is asked "which account?" with no
    idea what the choices are."""
    scripted_model(
        "Thought: Record it.\nAction: add_expense\nAction Input: amount=1000; account=credit",
        "Thought: Three cards match; I must ask.\n"
        "Clarification: Which card — BDO Credit Card, UnionBank Credit or Credit Card?",
    )
    before = len(finance.list_transactions())
    events = _drain(core, "i spent 1000 on the credit card")

    assert _no_tokens(events) == ["start", "action", "observation", "clarify"]
    obs = next(e for e in events if e["type"] == "observation")
    assert obs["data"]["error"] == "ambiguous_account"
    assert {c["name"] for c in obs["data"]["candidates"]} == {
        "Credit Card", "BDO Credit Card", "UnionBank Credit"
    }
    assert len(finance.list_transactions()) == before


def test_a_clarification_after_a_successful_write_discloses_the_transaction(
    core, finance, wallet, scripted_model
):
    """`Clarification:` is checked on every iteration, not only before the first tool
    call, so a model that writes and THEN second-guesses itself ends the run in the
    clarify branch. The `final` event never fires; the user is shown a bare question.

    The ₱1,000 is already in the ledger. The user is asked "did you mean the BDO card
    instead?", answers, and the follow-up turn records a second expense — while the
    first one sits there unmentioned.

    The observation text IS inside `steps`, so the collapsed reasoning trace in
    AgentChat.tsx does contain it. But the chat bubble the user reads is `ev.question`
    alone, tagged "❓ Quick question". The clarify payload must surface the write in
    the part a user actually sees."""
    scripted_model(
        "Thought: Record it.\nAction: add_expense\nAction Input: amount=1000; account=Cash",
        "Thought: Actually, they may have meant a card.\n"
        "Clarification: Did you mean the BDO card instead?",
    )
    before = len(finance.list_transactions())
    events = _drain(core, "i spent 1000 on cash")

    assert len(finance.list_transactions()) == before + 1, "the write did happen"
    clarify = events[-1]
    assert clarify["type"] == "clarify"
    assert "1,000" in clarify["question"] or "already" in clarify["question"].lower(), (
        "the user is asked a question with no hint that ₱1,000 was just recorded: "
        f"{clarify['question']!r}"
    )


def test_agent_run_reports_a_write_that_happened_under_a_clarification(
    core, finance, wallet, scripted_model
):
    """The REST wrapper flattens the stream to `{answer, steps, needs_clarification}`.
    On the write-then-clarify path it returns `needs_clarification=True` with the
    question as the answer and no field of any kind saying a transaction was created.

    A client rendering `answer` (the web chat does exactly that) shows only the
    question. The user has been charged and the API response never says so."""
    scripted_model(
        "Thought: Record it.\nAction: add_expense\nAction Input: amount=1000; account=Cash",
        "Thought: Second thoughts.\nClarification: Did you mean the BDO card instead?",
    )
    before = len(finance.list_transactions())
    result = core.agent_run("i spent 1000 on cash")

    wrote = len(finance.list_transactions()) == before + 1
    assert wrote, "precondition: the run did write"
    assert not result["needs_clarification"] or "1,000" in result["answer"], (
        "agent_run returned needs_clarification=True and an answer that never "
        f"mentions the transaction it created: {result['answer']!r}"
    )


def test_a_clarify_run_that_wrote_leaves_no_open_mlflow_run(
    core, finance, wallet, scripted_model
):
    """Probe: the guarded metric helpers hold on the mixed write+clarify path too."""
    import mlflow

    scripted_model(
        "Thought: Record it.\nAction: add_expense\nAction Input: amount=1000; account=Cash",
        "Thought: Second thoughts.\nClarification: Did you mean the BDO card instead?",
    )
    _drain(core, "i spent 1000 on cash")
    assert mlflow.active_run() is None


# --------------------------------------------------------------------------- #
# Multi-turn: clarify, then the user answers
# --------------------------------------------------------------------------- #
def test_the_turn_after_a_clarification_records_exactly_once(
    core, finance, wallet, scripted_model
):
    """The full PRD conversation: "i spent 300 on groceries" -> the agent asks which
    account -> "the BDO card". The amount lives only in the history block, so this is
    where a lost amount or a double charge would surface."""
    scripted_model(
        "Thought: No account named.\n"
        "Clarification: Which account should I charge the 300 to?"
    )
    before = len(finance.list_transactions())
    turn1 = _drain(core, "i spent 300 on groceries")
    assert _no_tokens(turn1) == ["start", "clarify"]
    assert len(finance.list_transactions()) == before

    history = [
        {"role": "user", "text": "i spent 300 on groceries"},
        {"role": "assistant", "text": "Which account should I charge the 300 to?"},
    ]
    scripted_model(
        "Thought: The history says 300 on groceries; they have now named the account.\n"
        "Action: add_expense\n"
        "Action Input: amount=300; account=the BDO card; category=Groceries",
        "Thought: Recorded.\nFinal Answer: Recorded 300.00 on your BDO Credit Card.",
    )
    _drain(core, "the BDO card", history=history)

    txns = finance.list_transactions()
    assert len(txns) == before + 1, "the follow-up turn must record exactly once"
    newest = txns[0]
    assert newest["amount"] == 300.0
    assert newest["account_id"] == wallet["BDO Credit Card"]


def test_the_history_block_carries_the_amount_into_the_follow_up_prompt(
    core, finance, wallet, monkeypatch
):
    """`_format_history` is the only channel by which the second turn can know the
    amount. If it dropped or truncated the earlier turn, the follow-up would have to
    guess — so assert the number actually reaches the prompt."""
    seen = {}

    def capture(**kwargs):
        seen["prompt"] = kwargs["messages"][0]["content"]
        text = "Thought: ok\nFinal Answer: done"
        return iter([{"message": {"content": text}}]) if kwargs.get("stream") else \
            {"message": {"content": text}}

    monkeypatch.setattr(core, "_chat", capture)
    _drain(core, "the BDO card", history=[
        {"role": "user", "text": "i spent 300 on groceries"},
        {"role": "assistant", "text": "Which account should I charge the 300 to?"},
    ])
    assert "i spent 300 on groceries" in seen["prompt"]


# --------------------------------------------------------------------------- #
# Step budget and the forced final answer
# --------------------------------------------------------------------------- #
def test_the_salvage_prompt_is_given_observations_and_not_loop_control_text(
    core, finance, wallet, monkeypatch
):
    """`_force_final` builds its "Findings:" block from `steps[*]["observation"]` — but
    the loop also writes its own dedup steering into that same field ("You already ran
    add_expense ... Do NOT call any tool again. Reply now starting with 'Final
    Answer:'"). So the summariser is handed loop-control instructions as if they were
    evidence about the user's money.

    Concretely, on a run that only ever refused, two of the three findings are the
    loop talking to itself. That is what the last-chance answer about a possible
    expense is grounded in."""
    captured = {}

    def fake_chat(**kwargs):
        prompt = kwargs["messages"][0]["content"]
        if "Findings:" in prompt:
            captured["findings"] = prompt.split("Findings:")[1]
            text = "Nothing was recorded."
        else:
            text = ("Thought: Record it.\nAction: add_expense\n"
                    "Action Input: amount=1000; account=credit")
        return iter([{"message": {"content": text}}]) if kwargs.get("stream") else \
            {"message": {"content": text}}

    monkeypatch.setattr(core, "_chat", fake_chat)
    before = len(finance.list_transactions())
    _drain(core, "i spent 1000 on the credit card")

    assert len(finance.list_transactions()) == before, "nothing was written"
    assert "Reply now starting with" not in captured["findings"], (
        "the loop's own steering text was passed to the summariser as a finding: "
        f"{captured['findings']!r}"
    )


def test_the_loop_gives_force_final_no_record_of_what_it_wrote(core):
    """Not a failure — a documented gap. `_force_final(question, steps, model)` gets
    the observation TEXT and nothing else: no list of transaction payloads, no
    write counter. So the loop cannot tell whether a salvaged answer that says "I
    recorded 1,000.00" matches reality, and it does not try.

    Whether a small model actually fabricates that confirmation from three refusal
    observations is a live-model question; scripting the lie into the stub would only
    prove the stub said it. This test just pins the structural fact that no
    cross-check exists to catch it."""
    import inspect

    params = list(inspect.signature(core._force_final).parameters)
    assert params == ["question", "steps", "model"]


def test_a_forced_final_never_shows_the_user_raw_tool_instructions(
    core, finance, wallet, scripted_model
):
    """When the salvage `_chat` itself fails — the normal reason the loop ran out of
    steps in the first place is that the model/endpoint is misbehaving — `_force_final`
    falls back to `obs[-1]`, the tool observation verbatim.

    The write tool's observations are written FOR THE MODEL: "Re-call add_expense with
    an explicit amount, e.g. amount=1000; account=BDO", "Ask the user which one — do
    NOT pick for them". Those are emitted as the `final` answer, i.e. straight into the
    chat bubble, contradicting the prompt's own rule never to mention tools."""
    scripted_model(
        "Thought: Record it.\nAction: add_expense\nAction Input: account=Cash; category=Food",
        salvage=RuntimeError("ollama unreachable"),
    )
    events = _drain(core, "i spent some money on food")

    final = events[-1]
    assert final["type"] == "final"
    lowered = final["answer"].lower()
    assert "add_expense" not in lowered and "re-call" not in lowered, (
        f"internal tool instructions were shown to the user: {final['answer']!r}"
    )


def test_the_step_budget_still_allows_lookup_then_write_then_answer(
    core, finance, wallet, scripted_model
):
    """Probe: four steps is exactly enough for the intended recovery — refusal,
    list_accounts, retry, answer. One step fewer and the PRD flow would truncate into
    a forced final.

    The question names "BDO" so the account-attribution guardrail (W2-K) accepts the
    retry; this test is about the step BUDGET, not about attribution, and leaving it
    unnamed would make it fail for the other reason."""
    scripted_model(
        "Thought: Record it.\nAction: add_expense\nAction Input: amount=1000; account=credit",
        "Thought: Look up the real names.\nAction: list_accounts\nAction Input: -",
        "Thought: They meant BDO.\n"
        "Action: add_expense\nAction Input: amount=1000; account=BDO Credit Card",
        "Thought: Recorded.\nFinal Answer: Recorded 1,000.00 on your BDO Credit Card.",
    )
    before = len(finance.list_transactions())
    events = _drain(core, "i spent 1000 on my BDO credit card")

    assert events[-1]["type"] == "final"
    assert len(finance.list_transactions()) == before + 1


def test_a_question_never_reaches_the_write_tool_through_the_dispatcher(
    core, finance, wallet, scripted_model
):
    """Probe: regression guard that adding a write tool did not change read routing."""
    scripted_model(
        "Thought: A question.\nAction: sql_ledger\nAction Input: total spend",
        "Thought: Got it.\nFinal Answer: You've spent 1,585.00.",
    )
    before = len(finance.list_transactions())
    _drain(core, "how much did I spend on food?")
    assert len(finance.list_transactions()) == before
