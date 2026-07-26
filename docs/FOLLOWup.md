# Snag Evaluation Follow-Up

## Purpose

This follow-up must be used only after inspecting the current repository state.

The repository has received evaluation-related commits since the original
`Snag_Agentic_Evaluation_Task_Breakdown.md` was issued. Do not assume that the
original plan is complete, and do not assume that every task remains missing.

The first task is an evidence-based implementation audit.

---

## Phase 1 — Audit Before Further Implementation

Inspect the current repository HEAD and compare it against every workstream,
task, deliverable, and definition of done in:

`Snag_Agentic_Evaluation_Task_Breakdown.md`

Create:

`evaluation/IMPLEMENTATION_STATUS.md`

For every W0–W8 task, assign exactly one status:

- Implemented and verified
- Partially implemented
- Documented but not implemented
- Test exists but has not been executed successfully
- Missing
- Blocked by environment/model/data
- Not applicable to the actual architecture

### Evidence required

An item may only be classified as “Implemented and verified” when the audit
provides:

- Exact file path
- Relevant class, function, test, or command
- What behavior is tested
- Whether the test was executed
- Actual result
- Output artifact, if applicable
- Known limitations

Do not mark an entire workstream complete because one related test exists.

Do not infer completion from:

- Commit messages
- README claims
- Planned checklists
- Test filenames alone
- Historical results
- Mock-only performance tests

### Specifically inspect the recent additions

Determine the exact coverage and limitations of:

- `PERFORMANCE.md`
- `bench_retrieval.py`
- `test_w2a_preprocess.py`
- `test_w5_retrieval.py`
- `test_w6_performance.py`
- Related README changes

Clarify whether these provide:

- Correctness evidence
- Structural performance evidence
- Real end-to-end latency
- Live-model performance
- Retrieval relevance ground truth
- Only isolated or mocked measurements

Do not describe a microbenchmark as end-to-end performance.

---

## Phase 2 — Required Gap Summary

After completing the audit, produce a prioritized gap table.

| Priority | Meaning |
|---|---|
| P0 | Necessary for a defensible evaluation submission |
| P1 | Necessary supporting evidence |
| P2 | Useful additional coverage |
| P3 | Stretch or regression work |

At minimum, explicitly report the status of:

1. Requirements and configuration audit
2. Versioned ground-truth dataset
3. Receipt header-field accuracy
4. Receipt line-item accuracy
5. Receipt-level exact match
6. Hallucinated or unsupported-total detection
7. Review-flag recall and false-review rate
8. SQL execution correctness
9. Retrieval relevance ground truth
10. RAG correctness, faithfulness, and citations
11. ReAct routing and observable trajectory evaluation
12. Loop, retry, and clarification behavior
13. Receipt-to-finance posting
14. Quick Chat deterministic parsing
15. Core finance consistency
16. End-to-end user-job evaluation
17. Correction-inclusive timing
18. Live-model latency
19. Configuration and model capture
20. Raw machine-readable result artifacts
21. Failure taxonomy and case studies
22. Evaluation notebook/report

---

## Phase 3 — Proof-Point Alignment

The original plan primarily evaluates Snag internally. It must also be checked
against the project-specific consultation direction.

The intended proof point is:

> How reliably can Snag extract, verify, and reconcile receipt-based financial
> information, and how does its performance compare with Claude Cowork on the
> same finance-verification task?

Audit whether the repository or evaluation materials currently support:

- Bank-statement or credit-card-statement ingestion
- Statement transaction extraction
- Receipt-to-statement matching
- Missing-receipt detection
- Unmatched-receipt detection
- Amount discrepancy detection
- Date and posting-date differences
- Merchant-name variations
- Duplicate detection
- Refund or negative transactions
- Unsupported or hallucinated-total handling
- Human-review flags
- Discrepancy-report generation

Clearly distinguish:

1. Receipt-internal arithmetic reconciliation
2. Receipt-to-bank/credit-statement reconciliation

Do not claim that the second exists merely because the first exists.

---

## Phase 4 — Cowork Benchmark Readiness

This phase is primarily an evaluation-artifact task. Do not implement an
unnecessary Cowork integration into Snag.

Report whether the project has:

- A fixed Claude Cowork benchmark prompt
- A common input dataset
- The same task definition for Snag and Cowork
- A common output schema
- Shared ground truth
- Fixed retry and clarification rules
- Raw-output storage
- Correction-inclusive timing protocol
- Accuracy and discrepancy metrics
- Severe-error definitions
- Cost comparison
- Build-versus-buy retrospective

Claude Cowork should be evaluated externally at the task/output level. Do not
claim access to its internal trajectory.

Tarsi may remain Philippine market context and does not need to be treated as
an equivalent experimental system.

---

## Phase 5 — Implementation Plan

Do not begin Phase 5 until Phases 1–4 are documented.

Produce a new implementation backlog containing only verified gaps.

For each proposed task, specify:

- Priority
- Files expected to change
- Tests or artifacts to add
- Dependency
- Definition of done
- Execution command
- Whether a live model is required
- Whether manual data labeling is required
- Estimated difficulty
- Risks or blockers

Preserve existing working tests and features.

Do not:

- Introduce LangGraph unless the repository already uses it
- Add authentication solely for evaluation
- Treat Quick Chat as an LLM feature
- Add SQL transaction execution
- Invent sample sizes or thresholds
- Claim historical results as current results
- Claim microbenchmarks as real request latency
- Claim “no API fee” means zero operating cost

---

## Required Final Response

At the end of the audit, report:

1. Overall percentage or count of original tasks verified complete
2. Workstreams fully complete
3. Workstreams only partially complete
4. Highest-risk missing evaluation evidence
5. Five immediate next actions
6. Tasks that should be deferred
7. Tests that currently pass
8. Tests that fail or cannot run
9. Data or model access still required
10. Whether the repository is ready for the final evaluation run

Do not modify production behavior during the audit.