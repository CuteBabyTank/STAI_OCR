"""
trajectory.py — W3 Layer 2 trajectory collection and expected-vs-actual comparison.

Design: collection is separated from evaluation.

  collect_trajectory()  needs a live model — it drains `core.agent_stream`.
  Trajectory.from_events() / evaluate_case()  are pure functions over an event list.

That split is deliberate. The comparator, the metrics, and the failure taxonomy are
all testable offline against synthetic event lists, so W3's logic can be validated and
reviewed before anyone spends GPU time — and a red result later is unambiguously the
agent's behaviour, not a bug in the measuring instrument.

Why not MLflow
--------------
Per the W0 audit: MLflow stores only run-level aggregates (`num_steps`, and
`tools_used` as a lossy comma-joined string). There is no ordered per-step record. The
breakdown's Phase 4 instruction to "export observable MLflow events" cannot be
satisfied from `mlflow.db`. The `agent_stream` generator is the only source of
step-level truth, so this module consumes it directly.

Observable evidence only
------------------------
Nothing here inspects hidden reasoning. `token` events (the model's streamed
chain-of-thought) are counted but never asserted on — the breakdown is explicit that
hidden chain-of-thought is not to be evaluated. Checks run against tool names, event
types and order, tool inputs, and the final answer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator

# Event types emitted by core.agent_stream. Kept here as the contract this harness
# depends on; test_w3_trajectory.py asserts the real generator still matches.
EVENT_TYPES = frozenset({"start", "token", "action", "observation", "clarify", "final", "error"})

# Events that legitimately end a run.
TERMINAL_EVENTS = frozenset({"final", "clarify", "error"})

# The tools the agent may call (core._run_agent_tool).
KNOWN_TOOLS = frozenset({"sql_ledger", "search_receipts"})


# --------------------------------------------------------------------------- #
# Trajectory record
# --------------------------------------------------------------------------- #
@dataclass
class Trajectory:
    """A normalized, comparable record of one agent run."""

    events: list[dict] = field(default_factory=list)

    @classmethod
    def from_events(cls, events: Iterable[dict]) -> "Trajectory":
        return cls(events=[dict(e) for e in events])

    # -- observable projections --------------------------------------------- #
    @property
    def event_types(self) -> list[str]:
        """Ordered event types with `token` collapsed out.

        Token events are per-chunk streaming noise: a single run emits hundreds,
        and their count depends on the model and sampling, not on the path taken.
        Keeping them would make every trajectory unique and every comparison
        meaningless.
        """
        return [e["type"] for e in self.events if e.get("type") != "token"]

    @property
    def tools_called(self) -> list[str]:
        """Tool names in call order — this is what routing accuracy is measured on."""
        return [e["tool"] for e in self.events if e.get("type") == "action"]

    @property
    def tool_calls(self) -> list[tuple[str, str]]:
        """(tool, input) pairs in call order, for loop detection."""
        return [
            (e["tool"], (e.get("input") or "").strip().lower())
            for e in self.events
            if e.get("type") == "action"
        ]

    @property
    def observations(self) -> list[str]:
        return [e.get("text", "") for e in self.events if e.get("type") == "observation"]

    @property
    def final_answer(self) -> str | None:
        for e in reversed(self.events):
            if e.get("type") == "final":
                return e.get("answer")
        return None

    @property
    def clarification(self) -> str | None:
        for e in reversed(self.events):
            if e.get("type") == "clarify":
                return e.get("question")
        return None

    @property
    def error(self) -> str | None:
        for e in reversed(self.events):
            if e.get("type") == "error":
                return e.get("message")
        return None

    @property
    def terminal_event(self) -> str | None:
        for t in reversed(self.event_types):
            if t in TERMINAL_EVENTS:
                return t
        return None

    @property
    def token_count(self) -> int:
        """Streaming chunk count. Reported for W6 latency context, never asserted on."""
        return sum(1 for e in self.events if e.get("type") == "token")

    @property
    def repeated_tool_calls(self) -> int:
        """How many times the agent called a (tool, input) pair it had already run.

        This is the breakdown's 'loop rate' signal. `core.agent_stream` caches the
        first repeat and force-finalizes on the second, so a healthy run scores 0.
        """
        seen: set[tuple[str, str]] = set()
        repeats = 0
        for pair in self.tool_calls:
            if pair in seen:
                repeats += 1
            seen.add(pair)
        return repeats

    def to_dict(self) -> dict:
        return {
            "event_types": self.event_types,
            "tools_called": self.tools_called,
            "tool_calls": [list(p) for p in self.tool_calls],
            "terminal_event": self.terminal_event,
            "final_answer": self.final_answer,
            "clarification": self.clarification,
            "error": self.error,
            "repeated_tool_calls": self.repeated_tool_calls,
            "token_count": self.token_count,
        }


# --------------------------------------------------------------------------- #
# Case definition — the breakdown's W3 suggested format
# --------------------------------------------------------------------------- #
@dataclass
class TrajectoryCase:
    case_id: str
    input: str
    allowed_tools: list[str] | None = None
    expected_tools: list[str] | None = None
    required_events: list[str] = field(default_factory=list)
    prohibited_events: list[str] = field(default_factory=list)
    max_tool_calls: int | None = None
    expected_answer_contains: list[str] = field(default_factory=list)
    receipt_ids: list[int] | None = None
    notes: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "TrajectoryCase":
        known = {f for f in cls.__dataclass_fields__}
        unknown = set(d) - known
        if unknown:
            raise ValueError(
                f"case {d.get('case_id', '?')}: unknown field(s) {sorted(unknown)}. "
                f"Known fields: {sorted(known)}"
            )
        return cls(**d)


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class CaseResult:
    case_id: str
    checks: list[CheckResult]
    trajectory: dict

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def failures(self) -> list[CheckResult]:
        return [c for c in self.checks if not c.passed]

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "passed": self.passed,
            "checks": [
                {"name": c.name, "passed": c.passed, "detail": c.detail} for c in self.checks
            ],
            "trajectory": self.trajectory,
        }


# --------------------------------------------------------------------------- #
# Evaluation
# --------------------------------------------------------------------------- #
def evaluate_case(case: TrajectoryCase, trajectory: Trajectory) -> CaseResult:
    """Compare one actual trajectory against its expected shape.

    Every check is reported, pass or fail — no short-circuiting — so a failure log
    localizes the problem instead of just saying the case failed.
    """
    checks: list[CheckResult] = []

    # --- required events ---------------------------------------------------- #
    if case.required_events:
        present = set(trajectory.event_types)
        missing = [e for e in case.required_events if e not in present]
        checks.append(
            CheckResult(
                "required_events",
                not missing,
                "all present" if not missing else f"missing {missing}",
            )
        )

    # --- prohibited events -------------------------------------------------- #
    if case.prohibited_events:
        present = set(trajectory.event_types)
        found = [e for e in case.prohibited_events if e in present]
        checks.append(
            CheckResult(
                "prohibited_events",
                not found,
                "none present" if not found else f"found {found}",
            )
        )

    # --- routing: only allowed tools were used ------------------------------ #
    if case.allowed_tools is not None:
        allowed = set(case.allowed_tools)
        used = [t for t in trajectory.tools_called if t not in allowed]
        checks.append(
            CheckResult(
                "allowed_tools",
                not used,
                "within allowlist" if not used else f"called disallowed {sorted(set(used))}",
            )
        )

    # --- routing: the expected tools were actually used --------------------- #
    if case.expected_tools is not None:
        expected = set(case.expected_tools)
        actual = set(trajectory.tools_called)
        checks.append(
            CheckResult(
                "expected_tools",
                expected <= actual,
                "matched" if expected <= actual else f"expected {sorted(expected)}, "
                f"got {sorted(actual)}",
            )
        )

    # --- step budget -------------------------------------------------------- #
    if case.max_tool_calls is not None:
        n = len(trajectory.tools_called)
        checks.append(
            CheckResult(
                "max_tool_calls",
                n <= case.max_tool_calls,
                f"{n} <= {case.max_tool_calls}" if n <= case.max_tool_calls
                else f"{n} tool calls exceeds budget {case.max_tool_calls}",
            )
        )

    # --- loop guard --------------------------------------------------------- #
    repeats = trajectory.repeated_tool_calls
    checks.append(
        CheckResult(
            "no_repeated_tool_calls",
            repeats == 0,
            "no repeats" if repeats == 0 else f"{repeats} repeated (tool, input) call(s)",
        )
    )

    # --- terminal state ----------------------------------------------------- #
    terminal = trajectory.terminal_event
    checks.append(
        CheckResult(
            "reached_terminal_state",
            terminal in TERMINAL_EVENTS,
            f"terminal={terminal}" if terminal else "no terminal event — run did not finish",
        )
    )

    # --- answer content ----------------------------------------------------- #
    if case.expected_answer_contains:
        answer = (trajectory.final_answer or "").lower()
        missing = [s for s in case.expected_answer_contains if s.lower() not in answer]
        checks.append(
            CheckResult(
                "answer_contains",
                not missing,
                "all present" if not missing else f"answer missing {missing}",
            )
        )

    # --- observation/final consistency -------------------------------------- #
    # The breakdown's "a correct final answer does not prove a correct trajectory".
    # An answer produced with no observation at all is unsupported by evidence.
    if trajectory.final_answer is not None:
        supported = bool(trajectory.observations)
        checks.append(
            CheckResult(
                "final_supported_by_observation",
                supported,
                "has observations" if supported
                else "final answer produced without any tool observation",
            )
        )

    return CaseResult(case.case_id, checks, trajectory.to_dict())


# --------------------------------------------------------------------------- #
# Aggregate metrics — the breakdown's W3 metric table
# --------------------------------------------------------------------------- #
def aggregate_metrics(results: list[CaseResult]) -> dict:
    """Compute the W3 metrics as explicit numerator/denominator pairs.

    Ratios are reported alongside their counts so a rate is never mistaken for a
    measurement on a larger sample than was actually run. Metrics whose denominator
    is zero are reported as None, never as 0.0 or 1.0.
    """

    def ratio(num: int, den: int) -> float | None:
        return round(num / den, 4) if den else None

    def check_stats(name: str) -> tuple[int, int]:
        applicable = [r for r in results if any(c.name == name for c in r.checks)]
        passed = [
            r for r in applicable
            if all(c.passed for c in r.checks if c.name == name)
        ]
        return len(passed), len(applicable)

    metrics: dict[str, Any] = {"cases_evaluated": len(results)}

    for metric_name, check_name in [
        ("routing_accuracy", "expected_tools"),
        ("allowed_tool_compliance", "allowed_tools"),
        ("required_step_compliance", "required_events"),
        ("prohibited_step_compliance", "prohibited_events"),
        ("step_budget_compliance", "max_tool_calls"),
        ("loop_free_rate", "no_repeated_tool_calls"),
        ("trajectory_completion", "reached_terminal_state"),
        ("answer_content_accuracy", "answer_contains"),
        ("observation_final_consistency", "final_supported_by_observation"),
    ]:
        num, den = check_stats(check_name)
        metrics[metric_name] = {"passed": num, "applicable": den, "rate": ratio(num, den)}

    passed_cases = sum(1 for r in results if r.passed)
    metrics["overall_case_pass"] = {
        "passed": passed_cases,
        "applicable": len(results),
        "rate": ratio(passed_cases, len(results)),
    }
    return metrics


def failure_taxonomy(results: list[CaseResult]) -> dict[str, list[str]]:
    """Group failing case IDs by the check they failed.

    Maps onto the breakdown's W7 failure taxonomy: `expected_tools` failures are
    "wrong route/tool", `no_repeated_tool_calls` is "loop/retry exhaustion",
    `final_supported_by_observation` is "unsupported final answer", and so on.
    """
    taxonomy: dict[str, list[str]] = {}
    for r in results:
        for c in r.failures:
            taxonomy.setdefault(c.name, []).append(r.case_id)
    return taxonomy


# --------------------------------------------------------------------------- #
# Case loading
# --------------------------------------------------------------------------- #
def load_cases(path: Path | str) -> list[TrajectoryCase]:
    """Load and validate trajectory cases, failing loudly on a malformed file.

    Duplicate case IDs are rejected: silently overwriting a case would corrupt the
    denominator of every metric computed from the set.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = [TrajectoryCase.from_dict(d) for d in raw["cases"]]

    seen: set[str] = set()
    for c in cases:
        if c.case_id in seen:
            raise ValueError(f"duplicate case_id: {c.case_id}")
        seen.add(c.case_id)

    for c in cases:
        for tool in (c.allowed_tools or []) + (c.expected_tools or []):
            if tool not in KNOWN_TOOLS:
                raise ValueError(
                    f"case {c.case_id}: unknown tool {tool!r}; known tools are "
                    f"{sorted(KNOWN_TOOLS)}"
                )
        for ev in c.required_events + c.prohibited_events:
            if ev not in EVENT_TYPES:
                raise ValueError(
                    f"case {c.case_id}: unknown event {ev!r}; known events are "
                    f"{sorted(EVENT_TYPES)}"
                )
        overlap = set(c.required_events) & set(c.prohibited_events)
        if overlap:
            raise ValueError(
                f"case {c.case_id}: event(s) {sorted(overlap)} are both required and prohibited"
            )
    return cases


# --------------------------------------------------------------------------- #
# Live collection — the only part that needs a model
# --------------------------------------------------------------------------- #
def collect_trajectory(question: str, receipt_ids: list[int] | None = None,
                       model: str | None = None, history: list | None = None) -> Trajectory:
    """Drain `core.agent_stream` into a Trajectory. Requires a reachable Ollama.

    Errors are captured as `error` events by the generator itself rather than
    raised, so a failed run still produces an evaluable trajectory — a failure that
    disappears from the results would bias every metric.
    """
    import core

    events = list(
        core.agent_stream(question, model or core.AGENT_MODEL, receipt_ids, history)
    )
    return Trajectory.from_events(events)


def run_cases(cases: list[TrajectoryCase], model: str | None = None) -> Iterator[CaseResult]:
    """Collect and evaluate each case in turn. Requires a reachable Ollama."""
    for case in cases:
        trajectory = collect_trajectory(case.input, case.receipt_ids, model)
        yield evaluate_case(case, trajectory)


# --------------------------------------------------------------------------- #
# CLI — the entry point that turns a live run into a stored artifact
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    """Run the case file against a live model and write the results to disk.

    Every raw trajectory is kept, including failed and errored ones: a failure that
    disappears from the results biases every metric computed from them.
    """
    import argparse

    from evaluation import report

    parser = argparse.ArgumentParser(
        prog="python -m evaluation.trajectory",
        description="Collect and evaluate ReAct trajectories against a case file.",
    )
    parser.add_argument("--cases", default=str(Path(__file__).parent / "datasets"
                                               / "trajectory_cases.json"))
    parser.add_argument("--model", default=None,
                        help="Override the agent model; defaults to core.AGENT_MODEL.")
    parser.add_argument("--name", default="trajectory",
                        help="Result file name stem.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Validate the case file and print the plan without "
                             "calling a model.")
    args = parser.parse_args(argv)

    cases = load_cases(args.cases)
    print(f"Loaded {len(cases)} cases from {args.cases}")

    if args.dry_run:
        for case in cases:
            print(f"  {case.case_id}: {case.input!r} -> expected {case.expected_tools}")
        print("\nDry run — no model was called and no results were written.")
        return 0

    identifier = report.run_id("trajectory")
    config = report.capture_configuration()
    for gap in report.configuration_gaps(config):
        print(f"  configuration gap: {gap}")

    results, errors = [], 0
    for case in cases:
        try:
            trajectory = collect_trajectory(case.input, case.receipt_ids, args.model)
        except Exception as exc:  # noqa: BLE001 — a collection failure is a result
            errors += 1
            print(f"  {case.case_id}: COLLECTION FAILED — {exc}")
            results.append({"case_id": case.case_id, "passed": False,
                            "checks": {"collected": False},
                            "error": str(exc)[:500]})
            continue
        outcome = evaluate_case(case, trajectory)
        results.append({
            **outcome.to_dict(),
            "checks": {c.name: c.passed for c in outcome.checks},
            "check_details": [{"name": c.name, "passed": c.passed, "detail": c.detail}
                              for c in outcome.checks],
        })
        print(f"  {case.case_id}: {'PASS' if outcome.passed else 'FAIL'}"
              + ("" if outcome.passed
                 else " — " + ", ".join(c.name for c in outcome.failures)))

    summary = report.summarize(results)
    payload = {
        "summary": summary,
        "collection_errors": errors,
        "taxonomy": {name: [r["case_id"] for r in results
                            if not (r.get("checks") or {}).get(name, True)]
                     for name in {n for r in results for n in (r.get("checks") or {})}},
        "cases": results,
    }
    path = report.write_result(args.name, payload, kind="raw",
                               config=config, identifier=identifier)

    pass_rate = summary["pass_rate"]
    rate_text = "n/a (no cases)" if pass_rate is None else f"{pass_rate:.0%}"
    print(f"\n{summary['passed']}/{summary['cases']} cases passed ({rate_text})")
    print(f"Results written to {path}")
    print("\nThis is a PILOT case set. Its rates are not a final evaluation result.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
