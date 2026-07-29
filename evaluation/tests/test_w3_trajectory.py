"""
W3 — tests for the trajectory harness itself.

These validate the measuring instrument, not Snag. They run offline against
synthetic event lists so the comparator, the metrics and the failure taxonomy are
known-correct before any GPU time is spent — a red W3 result should be the agent's
fault, never the harness's.

The one exception is `test_agent_stream_event_contract`, which reads the real
`core.agent_stream` source to confirm the event vocabulary this harness depends on
has not drifted.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evaluation.trajectory import (
    EVENT_TYPES,
    KNOWN_TOOLS,
    CaseResult,
    CheckResult,
    Trajectory,
    TrajectoryCase,
    aggregate_metrics,
    evaluate_case,
    failure_taxonomy,
    load_cases,
)

CASES_PATH = Path(__file__).resolve().parents[1] / "datasets" / "trajectory_cases.json"


# --------------------------------------------------------------------------- #
# Synthetic event builders
# --------------------------------------------------------------------------- #
def sql_run(answer="You spent 2250.00 pesos.", tool="sql_ledger", question="q"):
    """A healthy single-tool run: start -> action -> observation -> final."""
    return [
        {"type": "start"},
        {"type": "token", "text": "Thought: "},
        {"type": "token", "text": "I should query."},
        {"type": "action", "tool": tool, "input": question},
        {"type": "observation", "tool": tool, "text": "total: 2250.00", "data": {"kind": "sql"}},
        {"type": "final", "answer": answer, "steps": []},
    ]


def clarify_run(question="Which receipt?"):
    return [{"type": "start"}, {"type": "clarify", "question": question, "steps": []}]


def error_run(message="boom"):
    return [{"type": "start"}, {"type": "error", "message": message}]


def looping_run(tool="sql_ledger", inp="same"):
    return [
        {"type": "start"},
        {"type": "action", "tool": tool, "input": inp},
        {"type": "observation", "tool": tool, "text": "x", "data": {}},
        {"type": "action", "tool": tool, "input": inp},
        {"type": "observation", "tool": tool, "text": "x", "data": {}},
        {"type": "final", "answer": "eventually", "steps": []},
    ]


# --------------------------------------------------------------------------- #
# Trajectory projections
# --------------------------------------------------------------------------- #
def test_token_events_are_collapsed_out_of_event_types():
    """Token chunks are streaming noise — keeping them would make every trajectory
    unique and every comparison meaningless."""
    t = Trajectory.from_events(sql_run())
    assert t.event_types == ["start", "action", "observation", "final"]
    assert t.token_count == 2


def test_tools_called_preserves_call_order():
    events = [
        {"type": "start"},
        {"type": "action", "tool": "sql_ledger", "input": "a"},
        {"type": "observation", "tool": "sql_ledger", "text": "x"},
        {"type": "action", "tool": "search_receipts", "input": "b"},
        {"type": "observation", "tool": "search_receipts", "text": "y"},
        {"type": "final", "answer": "z"},
    ]
    assert Trajectory.from_events(events).tools_called == ["sql_ledger", "search_receipts"]


def test_tool_call_inputs_are_normalized_for_loop_detection():
    """Case and surrounding whitespace must not make one call look like two."""
    events = [
        {"type": "action", "tool": "sql_ledger", "input": "  Total Spend  "},
        {"type": "action", "tool": "sql_ledger", "input": "total spend"},
    ]
    t = Trajectory.from_events(events)
    assert t.tool_calls == [("sql_ledger", "total spend"), ("sql_ledger", "total spend")]
    assert t.repeated_tool_calls == 1


def test_repeated_tool_calls_counts_only_repeats():
    assert Trajectory.from_events(sql_run()).repeated_tool_calls == 0
    assert Trajectory.from_events(looping_run()).repeated_tool_calls == 1


def test_different_inputs_to_the_same_tool_are_not_a_loop():
    events = [
        {"type": "action", "tool": "sql_ledger", "input": "groceries"},
        {"type": "action", "tool": "sql_ledger", "input": "transport"},
    ]
    assert Trajectory.from_events(events).repeated_tool_calls == 0


@pytest.mark.parametrize(
    "events,expected",
    [(sql_run(), "final"), (clarify_run(), "clarify"), (error_run(), "error")],
)
def test_terminal_event_is_identified(events, expected):
    assert Trajectory.from_events(events).terminal_event == expected


def test_incomplete_run_has_no_terminal_event():
    events = [{"type": "start"}, {"type": "action", "tool": "sql_ledger", "input": "x"}]
    assert Trajectory.from_events(events).terminal_event is None


def test_final_answer_and_clarification_are_extracted():
    assert Trajectory.from_events(sql_run("42")).final_answer == "42"
    assert Trajectory.from_events(clarify_run("Which one?")).clarification == "Which one?"
    assert Trajectory.from_events(error_run("boom")).error == "boom"


# --------------------------------------------------------------------------- #
# Case evaluation
# --------------------------------------------------------------------------- #
def test_healthy_sql_run_passes_a_matching_case():
    case = TrajectoryCase(
        case_id="T-1", input="q",
        expected_tools=["sql_ledger"], allowed_tools=["sql_ledger"],
        required_events=["start", "action", "observation", "final"],
        prohibited_events=["clarify", "error"], max_tool_calls=3,
    )
    result = evaluate_case(case, Trajectory.from_events(sql_run()))
    assert result.passed, [c.detail for c in result.failures]


def test_wrong_route_fails_expected_tools():
    case = TrajectoryCase(case_id="T-2", input="q", expected_tools=["sql_ledger"])
    result = evaluate_case(case, Trajectory.from_events(sql_run(tool="search_receipts")))
    assert not result.passed
    assert any(c.name == "expected_tools" for c in result.failures)


def test_disallowed_tool_fails_the_allowlist():
    case = TrajectoryCase(case_id="T-3", input="q", allowed_tools=["sql_ledger"])
    result = evaluate_case(case, Trajectory.from_events(sql_run(tool="search_receipts")))
    assert any(c.name == "allowed_tools" for c in result.failures)


def test_missing_required_event_fails():
    case = TrajectoryCase(
        case_id="T-4", input="q",
        required_events=["start", "action", "observation", "final"],
    )
    result = evaluate_case(case, Trajectory.from_events(clarify_run()))
    failure = next(c for c in result.failures if c.name == "required_events")
    assert "action" in failure.detail


def test_prohibited_event_fails():
    case = TrajectoryCase(case_id="T-5", input="q", prohibited_events=["error"])
    result = evaluate_case(case, Trajectory.from_events(error_run()))
    assert any(c.name == "prohibited_events" for c in result.failures)


def test_exceeding_the_step_budget_fails():
    case = TrajectoryCase(case_id="T-6", input="q", max_tool_calls=1)
    result = evaluate_case(case, Trajectory.from_events(looping_run()))
    assert any(c.name == "max_tool_calls" for c in result.failures)


def test_a_loop_fails_even_when_the_final_answer_arrives():
    """The breakdown's core W3 requirement: 'a correct final answer does not hide a
    prohibited or looping path'."""
    case = TrajectoryCase(case_id="T-7", input="q")
    result = evaluate_case(case, Trajectory.from_events(looping_run()))
    assert not result.passed
    assert any(c.name == "no_repeated_tool_calls" for c in result.failures)


def test_answer_produced_without_any_observation_is_flagged_unsupported():
    """An answer with no tool observation behind it is ungrounded, however plausible."""
    events = [{"type": "start"}, {"type": "final", "answer": "You spent 500 pesos."}]
    result = evaluate_case(TrajectoryCase(case_id="T-8", input="q"),
                           Trajectory.from_events(events))
    assert any(c.name == "final_supported_by_observation" for c in result.failures)


def test_incomplete_run_fails_terminal_state():
    events = [{"type": "start"}, {"type": "action", "tool": "sql_ledger", "input": "x"}]
    result = evaluate_case(TrajectoryCase(case_id="T-9", input="q"),
                           Trajectory.from_events(events))
    assert any(c.name == "reached_terminal_state" for c in result.failures)


def test_answer_content_check():
    case = TrajectoryCase(case_id="T-10", input="q", expected_answer_contains=["2250"])
    assert evaluate_case(case, Trajectory.from_events(sql_run())).passed

    case_bad = TrajectoryCase(case_id="T-11", input="q", expected_answer_contains=["9999"])
    assert not evaluate_case(case_bad, Trajectory.from_events(sql_run())).passed


def test_all_checks_are_reported_not_short_circuited():
    """A failure log must localize every problem, not just the first one."""
    case = TrajectoryCase(
        case_id="T-12", input="q",
        expected_tools=["search_receipts"], allowed_tools=["search_receipts"],
        required_events=["clarify"], prohibited_events=["final"], max_tool_calls=0,
    )
    result = evaluate_case(case, Trajectory.from_events(sql_run()))
    failed = {c.name for c in result.failures}
    assert {"expected_tools", "allowed_tools", "required_events",
            "prohibited_events", "max_tool_calls"} <= failed


# --------------------------------------------------------------------------- #
# Aggregate metrics
# --------------------------------------------------------------------------- #
def test_metrics_report_counts_alongside_rates():
    """A rate without its denominator invites overclaiming on a tiny sample."""
    case = TrajectoryCase(case_id="M-1", input="q", expected_tools=["sql_ledger"])
    results = [
        evaluate_case(case, Trajectory.from_events(sql_run())),
        evaluate_case(case, Trajectory.from_events(sql_run(tool="search_receipts"))),
    ]
    metrics = aggregate_metrics(results)
    assert metrics["routing_accuracy"] == {"passed": 1, "applicable": 2, "rate": 0.5}
    assert metrics["cases_evaluated"] == 2


def test_metric_with_no_applicable_cases_is_none_not_zero_or_one():
    """Reporting 0.0 or 1.0 for an unmeasured metric would be a fabricated result."""
    results = [evaluate_case(TrajectoryCase(case_id="M-2", input="q"),
                             Trajectory.from_events(sql_run()))]
    metrics = aggregate_metrics(results)
    assert metrics["routing_accuracy"]["applicable"] == 0
    assert metrics["routing_accuracy"]["rate"] is None


def test_aggregate_metrics_on_empty_results_does_not_divide_by_zero():
    metrics = aggregate_metrics([])
    assert metrics["cases_evaluated"] == 0
    assert metrics["overall_case_pass"]["rate"] is None


def test_failure_taxonomy_groups_case_ids_by_failed_check():
    case = TrajectoryCase(case_id="F-1", input="q", expected_tools=["sql_ledger"])
    bad = evaluate_case(case, Trajectory.from_events(sql_run(tool="search_receipts")))
    taxonomy = failure_taxonomy([bad])
    assert taxonomy["expected_tools"] == ["F-1"]


def test_failure_taxonomy_is_empty_when_everything_passes():
    case = TrajectoryCase(case_id="F-2", input="q", expected_tools=["sql_ledger"])
    assert failure_taxonomy([evaluate_case(case, Trajectory.from_events(sql_run()))]) == {}


# --------------------------------------------------------------------------- #
# Case file loading and validation
# --------------------------------------------------------------------------- #
def test_the_shipped_case_file_loads_and_validates():
    """Every case belongs to a declared family. `RCT-` is ReAct routing over
    read-only tools; `ACT-` is the write path (`add_expense`), which needs its own
    prefix because a failing ACT case can leave data behind and a failing RCT case
    cannot. A new prefix must be added here deliberately, not by accident."""
    cases = load_cases(CASES_PATH)
    assert cases, "case file is empty"
    families = {c.case_id.split("-")[0] for c in cases}
    assert families == {"RCT", "ACT", "SEC"}, f"undeclared case family in {families}"


def test_the_write_family_is_the_only_one_allowed_to_use_a_write_tool():
    """Write tools mutate the ledger. If one ever appears in an `allowed_tools`
    outside the ACT family, a routing or security case could silently start
    writing — and a SEC case that writes is a failed guardrail passing as a run."""
    from evaluation.trajectory import WRITE_TOOLS

    for case in load_cases(CASES_PATH):
        used = WRITE_TOOLS & set(case.allowed_tools or [])
        if used:
            assert case.case_id.startswith("ACT-"), f"{case.case_id} allows {used}"


def test_the_security_family_permits_no_writes_at_all():
    """The SEC cases exist to prove the agent does NOT act on an off-topic or
    hostile input. Allowing a write tool would make them unfalsifiable."""
    from evaluation.trajectory import WRITE_TOOLS

    for case in load_cases(CASES_PATH):
        if case.case_id.startswith("SEC-"):
            assert not (WRITE_TOOLS & set(case.allowed_tools or [])), case.case_id


def test_the_write_refusal_case_forbids_writing():
    """ACT-003 is the safety case: an amount with no account named must end in a
    question, not a charge. If `add_expense` were ever added to its allowed_tools the
    case would pass while the agent guessed an account — the exact failure it exists
    to catch."""
    case = next(c for c in load_cases(CASES_PATH) if c.case_id == "ACT-003")
    assert "add_expense" not in (case.allowed_tools or [])
    assert "clarify" in case.required_events


def test_shipped_cases_respect_the_real_step_budget():
    """Guards against the breakdown's own warning about copying max_tool_calls from
    an unrelated example. The bound is read from the code, never hardcoded here."""
    import core

    for case in load_cases(CASES_PATH):
        if case.max_tool_calls is not None:
            assert case.max_tool_calls <= core._MAX_AGENT_STEPS, case.case_id


def test_shipped_cases_do_not_assert_invented_answer_content():
    """expected_answer_contains must stay empty until a frozen ledger and a
    recorded run exist. Filling it in beforehand would be fabricating ground truth."""
    for case in load_cases(CASES_PATH):
        assert case.expected_answer_contains == [], (
            f"{case.case_id} asserts answer content before any run was recorded"
        )


def test_duplicate_case_ids_are_rejected(tmp_path):
    """A silently overwritten case would corrupt every metric denominator."""
    p = tmp_path / "dup.json"
    p.write_text(json.dumps({"cases": [
        {"case_id": "X-1", "input": "a"},
        {"case_id": "X-1", "input": "b"},
    ]}))
    with pytest.raises(ValueError, match="duplicate case_id"):
        load_cases(p)


def test_unknown_tool_in_a_case_is_rejected(tmp_path):
    p = tmp_path / "bad_tool.json"
    p.write_text(json.dumps({"cases": [
        {"case_id": "X-1", "input": "a", "expected_tools": ["web_search"]},
    ]}))
    with pytest.raises(ValueError, match="unknown tool"):
        load_cases(p)


def test_unknown_event_in_a_case_is_rejected(tmp_path):
    p = tmp_path / "bad_event.json"
    p.write_text(json.dumps({"cases": [
        {"case_id": "X-1", "input": "a", "required_events": ["thinking"]},
    ]}))
    with pytest.raises(ValueError, match="unknown event"):
        load_cases(p)


def test_contradictory_case_is_rejected(tmp_path):
    """An event that is both required and prohibited can never pass — catch it at
    load time rather than reporting a mysterious permanent failure."""
    p = tmp_path / "contradiction.json"
    p.write_text(json.dumps({"cases": [
        {"case_id": "X-1", "input": "a",
         "required_events": ["final"], "prohibited_events": ["final"]},
    ]}))
    with pytest.raises(ValueError, match="both required and prohibited"):
        load_cases(p)


def test_unknown_field_in_a_case_is_rejected(tmp_path):
    """A typo'd field name would otherwise be silently ignored, making a case look
    stricter than it is."""
    p = tmp_path / "typo.json"
    p.write_text(json.dumps({"cases": [
        {"case_id": "X-1", "input": "a", "expected_tool": ["sql_ledger"]},
    ]}))
    with pytest.raises(ValueError, match="unknown field"):
        load_cases(p)


# --------------------------------------------------------------------------- #
# Contract with the real generator
# --------------------------------------------------------------------------- #
def test_agent_stream_event_contract(core):
    """The harness is coupled to core.agent_stream's event vocabulary. If the
    generator gains or renames an event type, this fails loudly rather than
    silently mismeasuring."""
    import inspect

    source = inspect.getsource(core.agent_stream)
    for event_type in ("start", "token", "action", "observation", "clarify", "final", "error"):
        assert f'"type": "{event_type}"' in source, (
            f"core.agent_stream no longer emits {event_type!r}; update EVENT_TYPES"
        )


def test_known_tools_match_the_real_dispatcher(core):
    """KNOWN_TOOLS must track the real tool registry, or case validation would
    reject a legitimate tool or accept a nonexistent one.

    Compared against `core.KNOWN_TOOLS` rather than by grepping
    `_run_agent_tool`'s source: the write tools now dispatch through a registry
    dict, so their names no longer appear as literals in that function and a source
    scan would silently pass while checking nothing."""
    assert KNOWN_TOOLS == core.KNOWN_TOOLS


def test_the_write_tool_list_is_a_subset_of_the_known_tools():
    """`WRITE_TOOLS` decides which cases can change data. A name in it that no
    longer exists would silently stop protecting anything."""
    from evaluation.trajectory import WRITE_TOOLS

    assert WRITE_TOOLS < KNOWN_TOOLS


def test_every_write_tool_has_a_canonical_dedup_key(core):
    """`_canonical_tool_key` keys writes on their PARSED fields so a re-phrased
    duplicate collapses to one entry. A write tool missing from that list would fall
    back to raw-string keying — the exact hole that allowed a double charge."""
    from evaluation.trajectory import WRITE_TOOLS

    assert WRITE_TOOLS == core._WRITE_TOOL_NAMES
    assert set(core._WRITE_TOOLS) == core._WRITE_TOOL_NAMES


def test_event_types_constant_covers_the_documented_vocabulary():
    assert EVENT_TYPES == {
        "start", "token", "action", "observation", "clarify", "final", "error"
    }
