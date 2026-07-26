"""
W6 — performance invariants that can be checked without a model.

Latency in seconds cannot be measured here: it needs a reachable Ollama endpoint and
belongs in a live W6 run. What CAN be pinned offline is the *structure* that determines
latency on a remote endpoint:

  * how many model round trips a question costs,
  * whether the model is asked to stay resident between them,
  * whether the context window is large enough to hold the transcript.

Those are the things that actually dominate: one round trip to a shared endpoint is
seconds, while the entire retrieval path is ~15 ms at 5,000 receipts (see
evaluation/bench_retrieval.py). A regression that adds one model call back is worth far
more than any amount of Python micro-optimisation, so it gets a test.
"""

from __future__ import annotations

import pytest


# --------------------------------------------------------------------------- #
# Generation defaults — model residency and context budget
# --------------------------------------------------------------------------- #
@pytest.fixture
def captured_ollama(core, monkeypatch):
    """Stub `ollama` one level below `_chat` so `_chat`'s own defaults still run."""
    seen: list[dict] = []

    class FakeOllama:
        @staticmethod
        def chat(**kwargs):
            seen.append(kwargs)
            return {"message": {"content": "ok"}}

        @staticmethod
        def embeddings(**kwargs):
            return {"embedding": [0.1] * 8}

    monkeypatch.setattr(core, "ollama", FakeOllama)
    return seen


def test_text_calls_ask_the_model_to_stay_resident(core, captured_ollama):
    """Without keep_alive the text model falls back to Ollama's short default and is
    evicted on a shared endpoint, so every agent turn pays a cold model load — which
    costs far more than the inference itself."""
    core._chat(model="m", messages=[], options={"temperature": 0})
    assert captured_ollama[-1]["keep_alive"] == core.OLLAMA_KEEP_ALIVE


def test_text_calls_get_an_explicit_context_window(core, captured_ollama):
    """Some Ollama builds default num_ctx to 2048. A ReAct transcript carrying the
    schema plus observations can exceed that and is SILENTLY truncated — the model
    loses the observation it should answer from. That surfaces as a wrong answer or a
    repeated tool call, never as an error, so it must be set explicitly."""
    core._chat(model="m", messages=[], options={"temperature": 0})
    assert captured_ollama[-1]["options"]["num_ctx"] == core.AGENT_NUM_CTX
    assert core.AGENT_NUM_CTX >= 8192


def test_text_calls_bound_their_output(core, captured_ollama):
    core._chat(model="m", messages=[], options={"temperature": 0})
    assert captured_ollama[-1]["options"]["num_predict"] == core.AGENT_NUM_PREDICT


def test_a_caller_with_explicit_options_is_not_overridden(core, captured_ollama):
    """The vision path sets its own, much larger, output budget. setdefault must not
    clobber it — capping OCR output at the agent's 512 would truncate the JSON for a
    receipt with many line items and fail the whole extraction."""
    core._chat(
        model="v", messages=[],
        options={"temperature": 0, "num_ctx": core.OCR_NUM_CTX,
                 "num_predict": core.OCR_NUM_PREDICT},
        keep_alive="99m",
    )
    sent = captured_ollama[-1]
    assert sent["keep_alive"] == "99m"
    assert sent["options"]["num_predict"] == core.OCR_NUM_PREDICT
    assert core.OCR_NUM_PREDICT > core.AGENT_NUM_PREDICT


def test_temperature_zero_is_preserved(core, captured_ollama):
    """Determinism matters for evaluation reproducibility."""
    core._chat(model="m", messages=[], options={"temperature": 0})
    assert captured_ollama[-1]["options"]["temperature"] == 0


# --------------------------------------------------------------------------- #
# Deterministic SQL answers
# --------------------------------------------------------------------------- #
def test_scalar_money_result_is_formatted_without_a_model(core):
    assert core._deterministic_answer([{"total_amount": 1585.0}]) is not None


def test_scalar_money_result_preserves_the_exact_number(core):
    """The whole point: the number reaches the user as SQLite computed it, instead of
    being re-typed by a model that was observed garbling amounts."""
    answer = core._deterministic_answer([{"total_spent": 1234.56}])
    assert "1,234.56" in answer


def test_scalar_count_is_returned_plainly(core):
    assert core._deterministic_answer([{"n": 7}]) == "7"


def test_null_aggregate_reads_as_no_records(core):
    """SUM over zero matching rows returns a single NULL. That is "nothing found",
    not "the answer is None"."""
    assert core._deterministic_answer([{"total_amount": None}]) == core._NO_ROWS_ANSWER


def test_no_rows_reads_as_no_records(core):
    assert core._deterministic_answer([]) == core._NO_ROWS_ANSWER


def test_single_row_with_several_columns_is_formatted(core):
    answer = core._deterministic_answer([{"vendor_name": "SM", "total_amount": 1500.0}])
    assert "SM" in answer and "1,500.00" in answer


def test_multi_row_results_defer_to_the_model(core):
    """Prose genuinely helps for a list, so those still cost a round trip."""
    rows = [{"vendor_name": "SM", "total": 1.0}, {"vendor_name": "7-Eleven", "total": 2.0}]
    assert core._deterministic_answer(rows) is None


@pytest.mark.parametrize(
    "key", ["total_amount", "sum_spent", "avg_price", "vat_amount", "discount", "cost"]
)
def test_money_column_names_are_recognized(core, key):
    assert core._is_money_key(key)


@pytest.mark.parametrize("key", ["vendor_name", "receipt_date", "category", "n"])
def test_non_money_column_names_are_not_formatted_as_money(core, key):
    assert not core._is_money_key(key)


# --------------------------------------------------------------------------- #
# Round-trip budget — the number that actually drives latency
# --------------------------------------------------------------------------- #
@pytest.fixture
def counting_agent(core, monkeypatch):
    """Count calls into `_chat` while returning plausible replies for each prompt."""
    calls: list[str] = []

    def fake_chat(**kwargs):
        prompt = kwargs["messages"][0]["content"]
        calls.append(prompt[:40])
        if "Thought" in prompt or "Action" in prompt:
            text = (
                "Thought: I need numbers.\nAction: sql_ledger\nAction Input: total spend"
                if len(calls) == 1
                else "Final Answer: You spent 1,585.00 PHP."
            )
        elif "SQL expert" in prompt:
            text = "SELECT SUM(total_amount) AS total_amount FROM receipts"
        else:
            text = "some prose"
        if kwargs.get("stream"):
            return iter([{"message": {"content": text}}])
        return {"message": {"content": text}}

    monkeypatch.setattr(core, "_chat", fake_chat)
    monkeypatch.setattr(core, "_embed", lambda text: None)
    return calls


def test_a_scalar_sql_question_costs_one_model_call(finance_fixture, core, counting_agent):
    """Was two: one to write the SQL, one to phrase the result. The phrasing call is
    gone for simple shapes. Regression guard — adding it back doubles the latency of
    every SQL question."""
    core.ask_ledger("How much did I spend in total?")
    assert len(counting_agent) == 1, counting_agent


def test_a_react_question_costs_three_model_calls(finance_fixture, core, counting_agent):
    """Was four: plan -> write SQL -> phrase SQL result -> final answer. The third is
    gone. On a shared endpoint at ~6 s per call that is ~6 s saved per question."""
    core.agent_run("How much did I spend in total?")
    assert len(counting_agent) == 3, counting_agent


def test_the_sql_answer_is_the_exact_computed_number(finance_fixture, core, counting_agent):
    """End-to-end shape of the deterministic path: the fixture's two receipts total
    1,585.00, and that is what comes back — not a model's retyping of it."""
    result = core.ask_ledger("How much did I spend in total?")
    assert "1,585.00" in result["answer"]
