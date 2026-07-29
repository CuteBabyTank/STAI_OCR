"""
W2-D / W3 — the ReAct loop's control paths, driven through the real `core.agent_stream`.

Closes the partial checklist items "ambiguous recent-receipt questions trigger
clarification" and "repeated tool calls and step limits are handled"
(IMPLEMENTATION_STATUS.md §3.3). Previously only the *detectors* were tested
(`_looks_ambiguous`, `_MAX_AGENT_STEPS` as a constant) and the trajectory harness
evaluated *synthetic* events. Nothing drove the real generator.

What is and is not being measured
---------------------------------
`_chat` is stubbed, so these verify that **the guards fire and the loop terminates in a
controlled state**. They are not a measurement of how often a real model loops — that is
a live-model W3 run and cannot be faked here. The stub plays a deliberately badly behaved
model; the assertions are about Snag's response to it.

The stub answers the SQL sub-prompt with real SQL, so `_run_agent_tool` -> `sql_ledger`
executes genuinely against the fixture database. Only the model is fake.
"""

from __future__ import annotations

import pytest


def _drain(core, question: str, **kwargs) -> list[dict]:
    """Run the generator to exhaustion and return the events."""
    return list(core.agent_stream(question, core.AGENT_MODEL, **kwargs))


def _types(events: list[dict]) -> list[str]:
    """Event types with `token` collapsed out — the trajectory-level view."""
    return [e["type"] for e in events if e["type"] != "token"]


@pytest.fixture
def scripted_model(core, monkeypatch):
    """Stub `_chat` with a scripted reply sequence for the ReAct prompt.

    Replies are consumed one per ReAct step; the last is repeated once exhausted.
    The SQL sub-prompt and the `_force_final` salvage prompt are answered separately
    so the real tool path still runs.
    """

    def _install(*replies: str):
        react_replies = list(replies)
        calls: list[str] = []

        def fake_chat(**kwargs):
            prompt = kwargs["messages"][0]["content"]
            calls.append(prompt)
            if "SQL expert" in prompt:
                text = "SELECT SUM(total_amount) AS total_amount FROM receipts"
            elif "Findings:" in prompt:          # _force_final salvage prompt
                text = "Based on the findings, you spent 1,585.00 PHP."
            else:                                 # the ReAct transcript
                index = min(len([c for c in calls if "SQL expert" not in c
                                 and "Findings:" not in c]) - 1,
                            len(react_replies) - 1)
                text = react_replies[index]
            if kwargs.get("stream"):
                return iter([{"message": {"content": text}}])
            return {"message": {"content": text}}

        monkeypatch.setattr(core, "_chat", fake_chat)
        monkeypatch.setattr(core, "_embed", lambda text: None)
        return calls

    return _install


# --------------------------------------------------------------------------- #
# The healthy path — a baseline the failure cases are read against
# --------------------------------------------------------------------------- #
def test_a_direct_final_answer_terminates_immediately(finance_fixture, core, scripted_model):
    scripted_model("Final Answer: You spent 1,585.00 PHP.")
    events = _drain(core, "How much did I spend?")
    assert _types(events) == ["start", "final"]


def test_one_tool_call_then_an_answer(finance_fixture, core, scripted_model):
    scripted_model(
        "Thought: I need the total.\nAction: sql_ledger\nAction Input: total spend",
        "Final Answer: You spent 1,585.00 PHP.",
    )
    assert _types(_drain(core, "How much did I spend?")) == [
        "start", "action", "observation", "final",
    ]


def test_the_observation_carries_the_real_query_result(finance_fixture, core, scripted_model):
    """`sql_ledger` really executed: the fixture's two receipts total 1,585.00."""
    scripted_model(
        "Thought: I need the total.\nAction: sql_ledger\nAction Input: total spend",
        "Final Answer: done.",
    )
    observation = next(e for e in _drain(core, "How much did I spend?")
                       if e["type"] == "observation")
    assert "1,585.00" in observation["text"]


# --------------------------------------------------------------------------- #
# Loop guard — a model that will not stop calling the same tool
# --------------------------------------------------------------------------- #
_SAME_ACTION = "Thought: Checking.\nAction: sql_ledger\nAction Input: total spend"


def test_a_repeated_tool_call_is_not_executed_twice(finance_fixture, core, scripted_model):
    """The second identical call is served from cache, so only one `action` event is
    emitted. Re-running it would pay the tool cost again for a known answer."""
    scripted_model(_SAME_ACTION)
    events = _drain(core, "How much did I spend?")
    assert len([e for e in events if e["type"] == "action"]) == 1


def test_a_repeated_call_still_reports_an_observation(finance_fixture, core, scripted_model):
    """The model needs to see *something* back, or it has no signal to change course."""
    scripted_model(_SAME_ACTION)
    events = _drain(core, "How much did I spend?")
    # One real observation from the executed call, then one cached-repeat note.
    assert len([e for e in events if e["type"] == "observation"]) == 2


def test_the_repeat_observation_steers_the_model_toward_answering(
    finance_fixture, core, scripted_model
):
    scripted_model(_SAME_ACTION)
    observations = [e for e in _drain(core, "How much did I spend?")
                    if e["type"] == "observation"]
    assert "Final Answer" in observations[-1]["text"]


def test_an_endlessly_looping_model_still_terminates_with_an_answer(
    finance_fixture, core, scripted_model
):
    """The guard's whole purpose: a model that never stops must not hang the request
    or surface as an error. It force-finalizes from what was already observed."""
    scripted_model(_SAME_ACTION)
    events = _drain(core, "How much did I spend?")
    assert _types(events)[-1] == "final"
    assert events[-1]["answer"]


def test_a_loop_is_recorded_in_the_step_trail(finance_fixture, core, scripted_model):
    """The repeat is marked, so trajectory evaluation can see the loop even though
    the final answer looks healthy."""
    scripted_model(_SAME_ACTION)
    steps = _drain(core, "How much did I spend?")[-1]["steps"]
    assert any(s.get("repeat") for s in steps)


def test_different_inputs_to_the_same_tool_are_not_treated_as_a_loop(
    finance_fixture, core, scripted_model
):
    """The guard keys on (tool, input). Two genuinely different questions to the same
    tool are legitimate work, not a loop."""
    scripted_model(
        "Thought: One.\nAction: sql_ledger\nAction Input: total spend",
        "Thought: Two.\nAction: sql_ledger\nAction Input: spend by vendor",
        "Final Answer: done.",
    )
    events = _drain(core, "How much did I spend?")
    assert len([e for e in events if e["type"] == "action"]) == 2


# --------------------------------------------------------------------------- #
# Step budget — a model that never answers
# --------------------------------------------------------------------------- #
def test_the_step_budget_bounds_the_number_of_tool_calls(
    finance_fixture, core, scripted_model
):
    """Distinct inputs each step, so the loop guard never fires and only the step
    budget stops it. Without the bound this would not terminate."""
    scripted_model(
        "Thought: A.\nAction: sql_ledger\nAction Input: query a",
        "Thought: B.\nAction: sql_ledger\nAction Input: query b",
        "Thought: C.\nAction: sql_ledger\nAction Input: query c",
        "Thought: D.\nAction: sql_ledger\nAction Input: query d",
    )
    events = _drain(core, "How much did I spend?")
    assert len([e for e in events if e["type"] == "action"]) == core._MAX_AGENT_STEPS


def test_exhausting_the_budget_produces_a_final_not_an_error(
    finance_fixture, core, scripted_model
):
    """A controlled terminal state. Running out of steps is an expected outcome, and
    the user must get an answer salvaged from the observations rather than a failure."""
    scripted_model(
        "Thought: A.\nAction: sql_ledger\nAction Input: query a",
        "Thought: B.\nAction: sql_ledger\nAction Input: query b",
        "Thought: C.\nAction: sql_ledger\nAction Input: query c",
        "Thought: D.\nAction: sql_ledger\nAction Input: query d",
    )
    events = _drain(core, "How much did I spend?")
    assert _types(events)[-1] == "final"
    assert events[-1]["answer"]


def test_a_reply_with_neither_action_nor_answer_is_treated_as_the_answer(
    finance_fixture, core, scripted_model
):
    """Small models often reply in prose without the scaffolding. Discarding that
    would strand the user with nothing, so the prose is still kept as the answer."""
    scripted_model("I couldn't find anything matching that in your receipts.")
    events = _drain(core, "What did I buy at the moon base?")
    assert _types(events) == ["start", "final"]
    assert "couldn't find" in events[-1]["answer"]
    assert events[-1]["grounded"] is True


def test_prose_that_states_a_figure_without_calling_a_tool_is_blocked(
    finance_fixture, core, scripted_model
):
    """The exception to the test above, and the reason it changed.

    A model that replies "you spent about 1,585 pesos" WITHOUT calling a tool did
    not read that from the ledger — it came from its own weights. Passing it through
    hands the user a fabricated balance that looks exactly like a real one. The
    guardrail replaces it with an honest refusal rather than guessing what was meant.

    Only figures are blocked: prose with no money claim still reaches the user (the
    test above). What is measured here is Snag's response to a fabricating model,
    not how often a real model fabricates — that needs a live run."""
    scripted_model("You spent about 1,585 pesos in total.")
    events = _drain(core, "How much did I spend?")

    answer = events[-1]["answer"]
    assert "1,585" not in answer
    assert events[-1]["grounded"] is False
    assert "receipts and accounts" in answer


def test_an_unknown_tool_does_not_crash_the_run(finance_fixture, core, scripted_model):
    """`_run_agent_tool` returns an observation for an unrecognized name so the agent
    can recover; it must not raise out of the generator."""
    scripted_model(
        "Thought: Trying.\nAction: not_a_real_tool\nAction Input: whatever",
        "Final Answer: Sorry, I could not do that.",
    )
    events = _drain(core, "How much did I spend?")
    assert _types(events)[-1] == "final"
    assert any("Unknown tool" in e.get("text", "")
               for e in events if e["type"] == "observation")


# --------------------------------------------------------------------------- #
# Clarification — the agent asking instead of guessing
# --------------------------------------------------------------------------- #
def test_the_model_can_ask_a_clarifying_question(finance_fixture, core, scripted_model):
    scripted_model("Thought: Too vague.\nClarification: Which month did you mean?")
    events = _drain(core, "How much did I spend?")
    assert _types(events) == ["start", "clarify"]
    assert "Which month" in events[-1]["question"]


def test_a_clarification_is_terminal(finance_fixture, core, scripted_model):
    """No `final` may follow — the run stops and waits for the user."""
    scripted_model("Clarification: Which month did you mean?")
    assert "final" not in _types(_drain(core, "How much did I spend?"))


def test_an_ambiguous_recent_receipt_question_clarifies_before_any_model_call(
    finance_fixture, core, scripted_model
):
    """Pre-loop disambiguation. The fixture holds 2 receipts uploaded together, so
    "my recent receipt" is genuinely ambiguous and must be resolved by asking — not
    by silently picking the newest."""
    calls = scripted_model("Final Answer: should never be reached")
    events = _drain(core, "What was on my recent receipt?")
    assert _types(events) == ["start", "clarify"]
    assert calls == [], "the model was called despite an ambiguous question"


def test_the_clarification_lists_the_candidate_receipts(finance_fixture, core,
                                                        scripted_model):
    """A question the user cannot answer is no better than a guess — the candidates
    must be named."""
    scripted_model("Final Answer: unused")
    events = _drain(core, "What was on my recent receipt?")
    assert "#" in events[-1]["question"]


def test_an_explicit_scope_suppresses_the_recent_receipt_clarification(
    finance_fixture, core, scripted_model
):
    """When the caller already pinned the receipts there is nothing ambiguous, so
    asking would be a false clarification."""
    receipt_id = finance_fixture["counts"]["receipts"]  # any valid id in the fixture
    scripted_model("Final Answer: It was groceries.")
    events = _drain(core, "What was on my recent receipt?", receipt_ids=[receipt_id])
    assert "clarify" not in _types(events)


def test_an_unambiguous_question_does_not_clarify(finance_fixture, core, scripted_model):
    scripted_model("Final Answer: You spent 1,585.00 PHP.")
    assert "clarify" not in _types(_drain(core, "How much did I spend in total?"))


# --------------------------------------------------------------------------- #
# Failure containment
# --------------------------------------------------------------------------- #
def test_a_model_failure_becomes_an_error_event_not_an_exception(
    finance_fixture, core, monkeypatch
):
    """The generator must never raise into the caller: the API streams these events,
    and a raised exception would break the stream mid-response. An `error` event is
    also what lets a failed run still be evaluated as a trajectory."""
    def exploding_chat(**kwargs):
        raise RuntimeError("endpoint unreachable")

    monkeypatch.setattr(core, "_chat", exploding_chat)
    events = _drain(core, "How much did I spend?")
    assert _types(events) == ["start", "error"]
    assert "unreachable" in events[-1]["message"]


def test_an_error_event_is_terminal(finance_fixture, core, monkeypatch):
    def exploding_chat(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(core, "_chat", exploding_chat)
    events = _drain(core, "How much did I spend?")
    assert events[-1]["type"] == "error"


def test_a_failing_tool_does_not_end_the_run(finance_fixture, core, scripted_model,
                                             monkeypatch):
    """A tool error is an observation the agent can recover from, not a crash."""
    scripted_model(
        "Thought: Query.\nAction: sql_ledger\nAction Input: total spend",
        "Final Answer: I could not retrieve that.",
    )
    monkeypatch.setattr(
        core, "_sql_agent_core",
        lambda *a, **k: (_ for _ in ()).throw(core.GuardrailError("bad query")),
    )
    events = _drain(core, "How much did I spend?")
    assert _types(events)[-1] == "final"
