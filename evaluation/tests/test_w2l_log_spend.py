"""
W2-L — logging spending from chat as a receipt (`log_spend`).

Why this file exists
--------------------
The Spending overview is driven by the `receipts` table; the agent's `add_expense`
writes a `transactions` row. So spending logged in chat could never appear in the
overview, and `add_expense` refuses outright when the user names no account — which
is most of how people actually talk ("i spent 10k on food in TGI Fridays").

`log_spend` closes that gap by recording a receipt instead of a transaction. It
touches no account, so it needs no account, and the receipt-driven panels pick it up
with no changes to them.

What is and is not being measured
---------------------------------
These are real correctness evidence: no model is involved in `log_manual_receipt`,
the guards, or `analytics_summary`. They measure the write and the aggregation a user
will actually hit.

They do NOT measure whether a live model picks `log_spend` over `add_expense` for a
given sentence — that is a routing question, declared in
`datasets/trajectory_cases.json` (ACT-003) and only answerable on a live run.

The last test here is a guard, not a feature: `add_expense` must keep refusing to
guess an account. `log_spend` exists so that refusal never had to be weakened.
"""

from __future__ import annotations

from datetime import date

import pytest


# --------------------------------------------------------------------------- #
# log_manual_receipt — the persistence primitive
# --------------------------------------------------------------------------- #
def test_a_manually_logged_receipt_stores_the_vendor_and_amount(core, finance_fixture):
    receipt_id = core.log_manual_receipt(
        vendor="TGI Fridays", amount=10000.0, category="Food"
    )

    row = core.get_receipt(receipt_id)
    assert row["vendor_name"] == "TGI Fridays"
    assert row["total_amount"] == 10000.0
    assert row["category"] == "Food"


def test_a_manually_logged_receipt_is_marked_as_a_chat_entry(core, finance_fixture):
    receipt_id = core.log_manual_receipt(vendor="TGI Fridays", amount=10000.0)

    assert core.get_receipt(receipt_id)["entry_source"] == "chat"


def test_a_manually_logged_receipt_is_dated_today_by_default(core, finance_fixture):
    receipt_id = core.log_manual_receipt(vendor="TGI Fridays", amount=10000.0)

    assert core.get_receipt(receipt_id)["receipt_date"] == date.today().isoformat()


def test_a_manually_logged_receipt_keeps_an_explicit_date(core, finance_fixture):
    receipt_id = core.log_manual_receipt(
        vendor="TGI Fridays", amount=10000.0, date="2026-03-04"
    )

    assert core.get_receipt(receipt_id)["receipt_date"] == "2026-03-04"


def test_a_manually_logged_receipt_carries_no_account_and_no_confidence(core, finance_fixture):
    """It is not an OCR reading and it has not been charged anywhere, so claiming
    either would be a fabrication: no confidence score, no account."""
    receipt_id = core.log_manual_receipt(vendor="TGI Fridays", amount=10000.0)

    row = core.get_receipt(receipt_id)
    assert row["account_id"] is None
    assert row["confidence"] is None


# --------------------------------------------------------------------------- #
# The point of the feature: it reaches the Spending overview
# --------------------------------------------------------------------------- #
def test_a_chat_logged_receipt_appears_in_the_spending_overview(core, finance_fixture):
    today = date.today()
    before = core.analytics_summary(
        granularity="month", year=today.year, month=today.month
    )

    core.log_manual_receipt(vendor="TGI Fridays", amount=10000.0, category="Food")

    after = core.analytics_summary(
        granularity="month", year=today.year, month=today.month
    )
    assert after["expense_total"] == pytest.approx(before["expense_total"] + 10000.0)
    assert after["receipt_count"] == before["receipt_count"] + 1


def test_a_chat_logged_receipt_counts_against_its_own_category(core, finance_fixture):
    today = date.today()

    core.log_manual_receipt(vendor="TGI Fridays", amount=10000.0, category="Food")

    scoped = core.analytics_summary(
        granularity="month", year=today.year, month=today.month
    )
    assert scoped["by_category"].get("Food", 0.0) >= 10000.0


def test_a_chat_logged_receipt_lands_in_the_month_it_is_dated(core, finance_fixture):
    """Dated into a past month, it must count there and not in the current one."""
    core.log_manual_receipt(vendor="TGI Fridays", amount=10000.0, date="2026-03-04")

    march = core.analytics_summary(granularity="month", year=2026, month=3)
    assert march["expense_total"] == pytest.approx(10000.0)


# --------------------------------------------------------------------------- #
# The agent tool
# --------------------------------------------------------------------------- #
def test_log_spend_records_a_receipt_with_no_accounts_configured(core, finance_fixture, finance):
    """The whole reason this tool exists: a ledger with zero usable accounts must
    still be able to record what the user spent.

    Archived rather than deleted because the seeded accounts carry transactions and
    are delete-protected (PRD §22). Archiving reaches the same state that matters:
    `list_accounts()` is the pool the account guard draws from, and it is now empty
    — exactly the ledger on which `add_expense` reports "there are no accounts"."""
    for account in finance.list_accounts():
        finance.update_account(account["id"], {"archived": True})
    assert finance.list_accounts() == []

    obs, data = core._tool_log_spend("amount=10000; vendor=TGI Fridays; category=Food")

    assert data["kind"] == "receipt"
    assert data["amount"] == 10000.0
    assert data["vendor"] == "TGI Fridays"
    assert core.get_receipt(data["receipt_id"])["total_amount"] == 10000.0


def test_log_spend_reads_a_plain_sentence(core, finance_fixture):
    obs, data = core._tool_log_spend("10000 on food at TGI Fridays")

    assert data["kind"] == "receipt"
    assert data["amount"] == 10000.0


def test_log_spend_refuses_without_an_amount(core, finance_fixture):
    obs, data = core._tool_log_spend("vendor=TGI Fridays")

    assert data["kind"] == "error"
    assert data["error"] == "no_amount"


def test_log_spend_leaves_every_account_balance_untouched(core, finance_fixture, finance):
    before = {a["id"]: a["balance"] for a in finance.list_accounts()}

    core._tool_log_spend("amount=10000; vendor=TGI Fridays; category=Food")

    after = {a["id"]: a["balance"] for a in finance.list_accounts()}
    assert after == before


def test_log_spend_writes_no_transaction(core, finance_fixture, finance):
    before = len(finance.list_transactions(limit=5000))

    core._tool_log_spend("amount=10000; vendor=TGI Fridays")

    assert len(finance.list_transactions(limit=5000)) == before


def test_log_spend_falls_back_to_a_valid_category(core, finance_fixture):
    """An off-taxonomy category must be resolved, not stored raw — the dashboard's
    category panel only understands VALID_CATEGORIES."""
    obs, data = core._tool_log_spend(
        "amount=500; vendor=Mercury Drug; category=Pharmaceuticals"
    )

    assert core.get_receipt(data["receipt_id"])["category"] in core.VALID_CATEGORIES


def test_log_spend_refuses_an_immediate_duplicate(core, finance_fixture):
    """Same duplicate shape the ledger writers use (`_guard_duplicate`): the payload
    points at the row already written this turn rather than reporting an error."""
    first_obs, first = core._tool_log_spend("amount=10000; vendor=TGI Fridays; category=Food")

    obs, data = core._tool_log_spend("amount=10000; vendor=TGI Fridays; category=Food")

    assert data["duplicate"] is True
    assert data["receipt_id"] == first["receipt_id"]


# --------------------------------------------------------------------------- #
# The turn must announce the write, or the dashboard silently goes stale
# --------------------------------------------------------------------------- #
@pytest.fixture
def scripted_model(core, monkeypatch):
    """Stub `_chat` with a scripted ReAct reply. The real tool path still runs —
    only the model is fake."""

    def _install(*replies: str):
        calls = 0

        def fake_chat(**kwargs):
            nonlocal calls
            prompt = kwargs["messages"][0]["content"]
            if "SQL expert" in prompt:
                text = "SELECT SUM(total_amount) AS total_amount FROM receipts"
            elif "Findings:" in prompt:  # _force_final salvage prompt
                text = "Done."
            else:
                text = replies[min(calls, len(replies) - 1)]
                calls += 1
            if kwargs.get("stream"):
                return iter([{"message": {"content": text}}])
            return {"message": {"content": text}}

        monkeypatch.setattr(core, "_chat", fake_chat)
        monkeypatch.setattr(core, "_embed", lambda text: None)

    return _install


def test_a_logged_receipt_is_reported_in_the_turns_writes(core, finance_fixture, scripted_model):
    """`writes` is what the UI watches to know the turn changed data — AgentChat
    calls broadcastRefresh() only when it is non-empty. A logged receipt changes
    every spending panel, so omitting it here would leave the user looking at a
    dashboard that does not yet include what they just logged."""
    scripted_model(
        "Thought: no account named.\nAction: log_spend\n"
        "Action Input: amount=10000; vendor=TGI Fridays; category=Food",
        "Thought: done.\nFinal Answer: Logged 10,000.00 at TGI Fridays.",
    )

    final = [e for e in core.agent_stream("i spent 10k on food in tgi fridays",
                                          core.AGENT_MODEL) if e["type"] == "final"][-1]

    assert [w["kind"] for w in final["writes"]] == ["receipt"]


# --------------------------------------------------------------------------- #
# Guard: the new tool must not erode the old one's refusal
# --------------------------------------------------------------------------- #
def test_add_expense_still_refuses_when_no_account_is_named(core, finance_fixture):
    """`log_spend` exists precisely so this refusal could stay intact. If adding it
    ever makes `add_expense` start guessing an account, that is a regression in the
    one tool that moves real money."""
    obs, data = core._tool_add_expense(
        "amount=1000; category=Food", user_text="i spent 1000 on food"
    )

    assert data["kind"] == "error"
    assert data["error"] in ("account_not_specified", "unknown_account")
