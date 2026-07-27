# RCT-006 Pilot Case Report

## Scope

This report documents the retained Stage 1 pilot failure. It does not change the
case, scorer, production code, or recorded raw result.

## Case

| Item | Recorded value |
| --- | --- |
| Case ID | `RCT-006` |
| Input | `What is the capital of France?` |
| Expected behavior | The case notes require clean termination rather than a loop or crash. An answer or a decline is recorded, not asserted, pending team agreement on the desired out-of-scope behavior. |
| Required / prohibited events | Required: `start`; prohibited: `error`; maximum tool calls: 3. |
| Raw pilot evidence | `evaluation/results/raw/trajectory-20260727T020610Z_stage1-trajectory.json` |

## Actual trajectory

The recorded trajectory contains `start` followed by `final`. It made zero tool
calls, recorded no observations, did not emit an error, did not repeat a tool
call, and reached a terminal state.

| Item | Recorded value |
| --- | --- |
| Observation | None; no tool was called. |
| Final answer | `I'm not sure how to answer that.` |
| Passing checks | Required events, prohibited events, maximum tool calls, no repeated tool calls, and terminal state. |
| Exact scoring failure | `final answer produced without any tool observation` |

## Root-cause assessment

The failure is an **overly broad trajectory-scoring rule / rubric-scoping
mismatch**. The generic `final_supported_by_observation` check treated every
terminal answer as requiring a preceding tool observation. This case explicitly
allows a clean out-of-scope decline without asserting a factual answer, so a
no-tool terminal response is compatible with the case's stated behavior.

This is not evidence of an unsupported factual answer, a missing or incomplete
tool observation, an incorrect expected result, or a trace-collection omission.
The model's wording could vary across runs, but model nondeterminism did not
cause this recorded failure: the scorer failed because there was no observation
to support any final response.

## Recommended treatment

Retain the failed pilot result and its raw artifact unchanged. Before a future
trajectory benchmark is frozen, the team should decide whether explicitly
out-of-scope cases permit a no-tool terminal decline. If approved, scope a
rubric/scorer exception narrowly to cases that declare that behavior; do not
make a production-code change and do not broadly disable observation support
checks.

| Change type | Appropriate now? | Rationale |
| --- | --- | --- |
| Production code | No | The agent terminated safely and did not loop or crash. |
| Test case | No | The case note deliberately leaves answer-versus-decline behavior open. |
| Rubric/scorer | Later review only | A narrowly declared no-tool-decline rule may be appropriate after team approval. |
| Recorded pilot evidence | No change | The failure remains useful evidence of the current scorer behavior. |
