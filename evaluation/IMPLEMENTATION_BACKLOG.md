# Evaluation Implementation Backlog (Phase 5)

**Derived from:** [`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md), audited at commit
`41b8fa1`.
**Rule observed:** this backlog contains **only verified gaps**. Nothing already verified
complete (receipt-to-finance posting, Quick Chat parsing, backup/restore, the trajectory
harness itself) appears here as work to redo.

> ## Status after the remediation pass
>
> **Completed and struck from this backlog** — everything that needed neither a model nor
> labelling: **P0-2** (results dir + writer), **P0-3** (reconcile tests), **P1-1** (budget
> aggregation), **P1-2** (real loop/step/clarify paths), **P1-3** (PDF + batch isolation),
> **P2-1** (field confidence), **P2-2** (parser differential), **P2-3** (coercion),
> **P2-5** (line-item linkage), **P2-6** (posting fidelity), **P3-2** (doc-drift guard).
> **P0-1** and **P0-4** are wired but cannot complete without an endpoint.
>
> **Everything still open below is blocked on one of exactly three things:**
> a reachable Ollama endpoint · labelled receipts (**B1**) · results from the first two.
> No open item is waiting on code that could be written today.
>
> Two product defects surfaced while closing the above: **D5** (budget carry-forward is
> inert) and **D6** (`_num` fabricated numbers from containers, now fixed). See
> `IMPLEMENTATION_STATUS.md` §9.

### Constraints carried from `docs/FOLLOWup.md` §Phase 5 — do not violate

- Do **not** introduce LangGraph (confirmed absent; the ReAct loop is hand-written).
- Do **not** add authentication for evaluation purposes.
- Do **not** treat Quick Chat as an LLM feature.
- Do **not** add SQL transaction execution — the validator is read-only `SELECT` by design.
- Do **not** invent sample sizes or thresholds. Every count below is either code-derived or
  explicitly labelled **proposed by the team**.
- Do **not** claim historical results as current, microbenchmarks as request latency, or
  "no API fee" as zero operating cost.
- **Preserve existing working tests and features.** 724 tests pass (564 Python + 160
  vitest); every task below must leave that green.

### Sizing legend

**Difficulty:** S ≈ under a day · M ≈ 1–3 days · L ≈ a week+
**Live model:** whether a reachable Ollama endpoint is required.
**Labeling:** whether a human must produce ground truth.

---

## Tier P0 — necessary for a defensible submission

### 🟡 P0-1 · Refresh the W0 configuration freeze and capture a real run — **capture tool built; run still pending**

| | |
|---|---|
| **Priority** | P0 |
| **Files** | `evaluation/CONFIGURATION.md`, new `evaluation/results/runs/<run_id>.json` |
| **Artifacts** | One filled-in per-run capture record (the template already exists) |
| **Dependency** | Reachable endpoint for the model-digest fields; the rest is unblocked |
| **Definition of done** | The card names HEAD; every **RECORD AT RUNTIME** field is filled from the live system, not from defaults; `ollama list` digests recorded; `git_dirty` recorded |
| **Command** | `curl -s localhost:8001/health`, `ollama list`, `git rev-parse HEAD` |
| **Live model** | Partly — digests need the serving host |
| **Labeling** | No |
| **Difficulty** | S |
| **Risks** | The card drifts again on the next commit. Mitigation: cite symbols, not line numbers, and re-pin the commit as the first step of any evaluation run. |

### ✅ P0-2 · Results directory and a machine-readable writer — **DONE**

| | |
|---|---|
| **Priority** | P0 — gates every metric table downstream |
| **Files** | new `evaluation/results/{raw,processed,failures}/` (with `.gitkeep`), new `evaluation/report.py` |
| **Artifacts** | JSON/CSV writer that stamps every result file with the P0-1 configuration record |
| **Dependency** | P0-1 for the config schema |
| **Definition of done** | `trajectory.run_cases` output can be written and re-read; every result file carries `run_id`, commit, resolved model names, and `OLLAMA_HOST`; results are gitignored **only if** the seeder/writer is versioned instead |
| **Command** | `./.venv/bin/python -m evaluation.report config` · `... report gaps` (exits non-zero while the capture is incomplete) |
| **Live model** | No |
| **Labeling** | No |
| **Difficulty** | S |
| **Risks** | Deciding to commit result files vs gitignore them — the breakdown requires versioned evidence, so results should be **tracked**, unlike the fixture `.db` files. |

### ✅ P0-3 · Unit-test `extraction.reconcile` (unsupported/hallucinated total) — **DONE**

| | |
|---|---|
| **Priority** | P0 — this is the project's central verification claim and it has **zero tests** |
| **Files** | new `evaluation/tests/test_w2a_reconcile.py` |
| **Artifacts** | Tests for: items sum matches total; mismatch beyond tolerance flags; the `max(1.0, total × 0.02)` boundary on both sides; the discount allowance path; zero/None/negative total; empty items; and that a flagged reason reaches `needs_review` |
| **Dependency** | None |
| **Definition of done** | Every branch of `reconcile()` is exercised; the tolerance boundary is asserted at `tol`, `tol ± ε`; no existing test changes |
| **Command** | `./.venv/bin/python -m pytest evaluation/tests/test_w2a_reconcile.py -q` |
| **Live model** | No |
| **Labeling** | No |
| **Difficulty** | S |
| **Risks** | Writing tests that merely restate the implementation. Derive the expected boundary from the receipt semantics (a ₱1 rounding floor, 2% relative), not by reading the constant back. |

### 🟡 P0-4 · Execute the trajectory harness against a live model — **CLI wired; execution blocked on an endpoint**

| | |
|---|---|
| **Priority** | P0 — **highest value per unit of work in the whole backlog.** The harness is written, self-tested, and contract-checked against `core`; it has simply never been run. |
| **Files** | `evaluation/trajectory.py` (add a `__main__` runner), `evaluation/datasets/trajectory_cases.json` |
| **Artifacts** | Raw event logs per case; `CaseResult` set; aggregate metrics; failure taxonomy populated; **one successful and one failed trajectory visualization** (W3 deliverable) |
| **Dependency** | Reachable Ollama; P0-2 for the writer; the finance fixture (already built) |
| **Definition of done** | All 7 pilot cases collected and evaluated against real `agent_stream` events; routing accuracy, required-step compliance, prohibited-step rate, loop rate, clarification accuracy, observation↔final consistency, and trajectory completion all reported **with their denominators**; failures retained, not deleted |
| **Command** | `./.venv/bin/python -m evaluation.trajectory` (add `--dry-run` to validate cases without a model; `--cases`, `--model`, `--name` override the defaults). Results land in `evaluation/results/raw/`. |
| **Live model** | **Yes** |
| **Labeling** | No |
| **Difficulty** | S–M (the harness exists; this is wiring plus a run) |
| **Risks** | 7 cases is a pilot, correctly labelled as such — do not report its rates as final. Expect the pilot to expose instrumentation problems; that is its purpose. `expected_answer_contains` is empty on every case, so answer content cannot fail — fill it in **only after** a frozen ledger and a recorded run, never before. |

### P0-5 · Retrieval relevance ground truth and metrics

| | |
|---|---|
| **Priority** | P0 |
| **Files** | new `evaluation/datasets/retrieval_cases.json`, new `evaluation/tests/test_w5_relevance.py` or a runner |
| **Artifacts** | Per-question relevant-receipt-ID sets; computed context precision, context recall, scope-leakage rate |
| **Dependency** | The finance fixture's 2 receipts are too few — needs the B1 receipt set, or a purpose-built fixture corpus with real embeddings |
| **Definition of done** | Every question has a human-assigned relevant-ID set, reviewed by someone other than the author (breakdown §6); metrics computed with NumPy — **no Ragas dependency required** |
| **Command** | `./.venv/bin/python -m evaluation.report retrieval` |
| **Live model** | **Yes** — real embeddings, not the synthetic vectors `test_w5_retrieval.py` uses |
| **Labeling** | **Yes** — small; the ledger is tiny |
| **Difficulty** | M |
| **Risks** | **B5**: `receipt_docs` (5) < `receipts` (6) in the dev ledger — one receipt is invisible to search. Resolve or record explicitly before measuring recall, or the denominator is wrong. |

### P0-6 · SQL question set with expected execution results

| | |
|---|---|
| **Priority** | P0 |
| **Files** | new `evaluation/datasets/sql_cases.json`, new runner in `evaluation/report.py` |
| **Artifacts** | Questions + expected result rows verified **directly against the frozen fixture**, not against model output; generated SQL and execution results stored per case |
| **Dependency** | The finance fixture (built); P0-2 |
| **Definition of done** | SQL execution accuracy reported as *cases returning the expected result ÷ SQL cases*, with the denominator stated; validator rejections and empty results counted separately from wrong answers |
| **Command** | `./.venv/bin/python -m evaluation.report sql` |
| **Live model** | **Yes** |
| **Labeling** | **Yes** — expected values computed by hand from the fixture |
| **Difficulty** | M |
| **Risks** | Do **not** score by SQL string similarity — the breakdown is explicit that execution result is the primary metric. Do **not** add transaction execution. |

### P0-7 · Receipt ground-truth dataset (unblocks the accuracy metrics)

| | |
|---|---|
| **Priority** | P0 — the root blocker (**B1**) |
| **Files** | new `evaluation/fixtures/receipts/`, new `evaluation/datasets/receipt_cases.json`, new `evaluation/datasets/labeling_guide.md`, new `evaluation/datasets/coverage_matrix.md` |
| **Artifacts** | Receipt images; verified header fields and line-item tuples per receipt; expected reconciliation status; expected review reasons |
| **Dependency** | **Human-supplied receipt images.** Not resolvable in code. |
| **Definition of done** | Every case has a unique ID and reproducible input; labels are checked **against the image**, not copied from model output; a second person verifies each label; development cases separated from final reporting cases; both normal and failure cases present; sample size chosen **after** a pilot and labelled *proposed by the team* |
| **Command** | n/a (data task) |
| **Live model** | No (labelling); yes to score against |
| **Labeling** | **Yes — this is the labelling task** |
| **Difficulty** | L |
| **Risks** | The dominant schedule risk. Labelling line items is slow. Start with the coverage matrix and a small pilot to expose labelling problems before committing to a count. Do not let model output seed labels. |

### P0-8 · Receipt accuracy metrics (three, reported separately)

| | |
|---|---|
| **Priority** | P0 |
| **Files** | new `evaluation/scoring.py`, `evaluation/tests/test_scoring.py` |
| **Artifacts** | Receipt-level exact match, field-level accuracy, line-item accuracy — **three separate numbers**; review recall and false-review rate |
| **Dependency** | **P0-7** |
| **Definition of done** | Exact match is never presented as field accuracy (breakdown §1.10); the scorer itself is unit-tested against synthetic gold/predicted pairs so its arithmetic is trustworthy before real data flows through it; line-item matching rule (order-insensitive? tuple-exact?) is written down before scoring |
| **Command** | `./.venv/bin/python -m evaluation.report receipts` |
| **Live model** | **Yes** to produce predictions |
| **Labeling** | Consumes P0-7 |
| **Difficulty** | M |
| **Risks** | The known historical observation — "at least one wrong field on every tested receipt" — is a **0% receipt-level exact match on that historical set**, not 0% field accuracy, and not a current-deployment result. It must not be restated as either. |

### P0-9 · End-to-end user-job evaluation

| | |
|---|---|
| **Priority** | P0 |
| **Files** | new `evaluation/e2e/runner.py` (or a documented manual protocol), `evaluation/e2e/protocol.md` |
| **Artifacts** | Pre/post DB snapshots; task-level result CSV/JSON; correction and timing sheet; failure evidence |
| **Dependency** | P0-2; live model for `E2E-REC`/`E2E-ASK`; **`E2E-MAN`, `E2E-QCK`, `E2E-BAK` are runnable today without a model** |
| **Definition of done** | Completion conditions written **before** running; both successful and failed jobs retained; receipt correction time included; no result framed as user time savings without a measured baseline |
| **Command** | `./.venv/bin/python -m evaluation.e2e.runner --jobs E2E-MAN,E2E-QCK,E2E-BAK` |
| **Live model** | Partly — start with the three that don't need one |
| **Labeling** | Yes for the receipt jobs |
| **Difficulty** | L |
| **Risks** | Precedent from this repo: defect D4 (a 1,000,000× amount error) was invisible to 100+ passing unit tests and surfaced only when the real endpoint was driven. Budget for E2E finding things the component layer cannot. |

### P0-10 · Evaluation notebook

| | |
|---|---|
| **Priority** | P0 |
| **Files** | new `evaluation/notebooks/snag_evaluation.ipynb`, `evaluation/reports/evaluation_summary.md` |
| **Artifacts** | The 13 recommended sections; the 9 minimum visual-evidence items |
| **Dependency** | Every P0 above — a notebook with no results is a template, not evidence |
| **Definition of done** | Every conclusion traceable to a recorded result file; none of the breakdown §W8 "claims to avoid" appears; thresholds distinguished from achieved results |
| **Command** | `./.venv/bin/jupyter lab` (runtime already installed via `requirements-eval.txt`) |
| **Live model** | No |
| **Labeling** | No |
| **Difficulty** | M |
| **Risks** | Writing the narrative before the results exist, then bending results to fit it. Write it last. |

---

## Tier P1 — necessary supporting evidence

### ✅ P1-1 · Budget aggregation tests — **DONE** (carry-forward found inert: defect D5)

| | |
|---|---|
| **Files** | `evaluation/tests/test_w2b_finance.py` (extend), `evaluation/fixtures/seed_finance.py` (add budget rows) |
| **Artifacts** | Tests for `list_budget_plans` / `create_budget_plan` / `delete_budget_plan`, aggregation against seeded transactions, and carry-forward behaviour |
| **Dependency** | None |
| **Definition of done** | The one uncovered W2-B checklist item is covered; `evaluation/README.md`'s W2-B row becomes honestly "Done"; existing 52 finance tests still pass |
| **Command** | `./.venv/bin/python -m pytest evaluation/tests/test_w2b_finance.py -q` |
| **Live model** | No · **Labeling** No · **Difficulty** S |
| **Risks** | Fixture change must keep every existing hand-computed expectation valid — the seeder self-verifies net worth, so a mistake fails loudly. |

### ✅ P1-2 · Drive the real loop guard, clarify path, and step limit — **DONE**

| | |
|---|---|
| **Files** | new `evaluation/tests/test_w2d_agent_paths.py` |
| **Artifacts** | Tests driving `core.agent_stream` with a stubbed `_chat` that (a) repeats a tool call until `repeats >= 2` forces `_force_final`, (b) exhausts `_MAX_AGENT_STEPS`, (c) emits a `clarify` event for an ambiguous recent-receipt question |
| **Dependency** | None — the stubbed-model pattern already exists in `test_w6_performance.py::counting_agent` |
| **Definition of done** | The three real code paths currently only detected by the harness are exercised in `core` itself |
| **Command** | `./.venv/bin/python -m pytest evaluation/tests/test_w2d_agent_paths.py -q` |
| **Live model** | No · **Labeling** No · **Difficulty** S–M |
| **Risks** | Stubbed-model tests verify the guard, not the model's tendency to loop. Do not report these as loop-rate measurements. |

### ✅ P1-3 · PDF page expansion and batch failure isolation — **DONE**

| | |
|---|---|
| **Files** | new `evaluation/fixtures/receipts/*.pdf` (synthesisable with Pillow + pypdfium2), new tests in `test_w2a_preprocess.py` |
| **Artifacts** | Tests for single-page PDF, multipage expansion, `OCR_PDF_MAX_PAGES` ceiling, `OCR_PDF_RENDER_SCALE`, and that one failing page does not abort sibling pages in a batch |
| **Dependency** | None — a synthetic PDF needs no labelling |
| **Definition of done** | Two W2-A items and one W3 receipt-pipeline check move from Missing to Verified |
| **Command** | `./.venv/bin/python -m pytest evaluation/tests/test_w2a_preprocess.py -q` |
| **Live model** | No (stub the vision call) · **Labeling** No · **Difficulty** M |
| **Risks** | Batch isolation may need `OCR_CONCURRENCY` pinned to 1 for determinism. |

### P1-4 · Live-model latency and repeated-run consistency

| | |
|---|---|
| **Files** | new `evaluation/bench_live.py` |
| **Artifacts** | Cold vs warm first-call latency; per-endpoint latency (`/extract`, `/ask`, `/search`, `/agent`); batch throughput in pages/minute; token counts from MLflow `prompt_eval_count`/`eval_count`; mean/median/min/max/sd and route consistency across repetitions |
| **Dependency** | **Reachable endpoint**; P0-1 config capture attached to every run |
| **Definition of done** | Every figure carries explicit units and the configuration record; repetition count **proposed by the team**, not assumed to be 10; microbenchmarks are never relabelled as request latency |
| **Command** | `./.venv/bin/python evaluation/bench_live.py` |
| **Live model** | **Yes** · **Labeling** No · **Difficulty** M |
| **Risks** | Do not exceed the endpoint's `OLLAMA_NUM_PARALLEL`; concurrency 2 is known to OOM two local 7B vision models on 16 GB. Shared-endpoint contention will add variance that must be reported, not averaged away. |

### P1-5 · Correction-inclusive timing protocol

| | |
|---|---|
| **Files** | `evaluation/e2e/protocol.md`, `evaluation/results/processed/timing.csv` |
| **Artifacts** | A written protocol defining when the clock starts and stops, what counts as a correction, and who performs it; a timing sheet |
| **Dependency** | P0-9 |
| **Definition of done** | Minutes per verified receipt and per verified transaction, with correction time **included**; no comparison to a baseline that was not measured |
| **Live model** | Yes for receipt jobs · **Labeling** Manual observation · **Difficulty** M |
| **Risks** | Self-timing by the implementer biases results. Note the limitation explicitly. |

### P1-6 · Failure taxonomy populated with case studies

| | |
|---|---|
| **Files** | `evaluation/reports/failures.md`, `evaluation/results/failures/` |
| **Artifacts** | Failure counts by the breakdown's 16 categories; representative case studies with case IDs |
| **Dependency** | Results from P0-4, P0-6, P0-8, P0-9 |
| **Definition of done** | Failures are retained and categorized, never deleted to improve a rate; `trajectory.failure_taxonomy()` output is included rather than hand-tallied |
| **Live model** | No · **Labeling** No · **Difficulty** S |

### P1-7 · Cost worksheet with explicit units

| | |
|---|---|
| **Files** | `evaluation/reports/cost.md` |
| **Artifacts** | PHP per compute hour, per task, or per user per month, with every assumption stated |
| **Dependency** | P1-4 for the compute-time input |
| **Definition of done** | The worksheet states plainly that **"no API fee" is not zero operating cost** — compute, hosting, electricity, storage, maintenance, and correction labour are itemized even where an estimate is unavailable |
| **Live model** | No · **Labeling** No · **Difficulty** S |
| **Risks** | Speculative USD/PHP figures presented as measurements. Mark every unmeasured line as an estimate with its basis. |

---

## Tier P2 — useful additional coverage

| ID | Task | Files | DoD | Live model | Difficulty |
|---|---|---|---|---|---|
| ✅ **P2-1** *(done)* | Field-confidence and value-equality gating tests | new `evaluation/tests/test_w2a_confidence.py` | `core._logprob_token_spans` and the value-equality gate exercised with synthetic logprobs; currently zero coverage | No | M |
| ✅ **P2-2** *(done)* | Quick Chat differential test (server vs client) | new shared corpus JSON read by both `parseQuick.test.ts` and `test_w2c_quick_python.py` | Both parsers produce identical drafts over one shared corpus; divergence fails a test in both suites | No | S |
| ✅ **P2-3** *(done, found D6)* | `extraction._coerce_json` and `_num` tests | `evaluation/tests/` | Fence-wrapped, prose-wrapped, and truncated model output; numeric strings with ₱, commas, parentheses | No | S |
| **P2-4** | Trajectory cases for the four non-ReAct pipelines | `evaluation/datasets/` | Receipt, receipt-to-finance, Quick Chat, and backup/restore pipelines get case definitions, not just the `RCT` family | Partly | M |
| ✅ **P2-5** *(done)* | Direct `save_receipt` line-item linkage test | `evaluation/tests/` | Asserts line items are written and linked to the parent receipt; currently only exercised indirectly via the seeder | No | S |
| ✅ **P2-6** *(done; currency is architecturally N/A)* | Category preservation on posting | `evaluation/tests/test_w2b_finance.py` | The one partial W2-E item closed | No | S |
| **P2-7** | Coverage EDA (W7) | `evaluation/notebooks/` | Cases per module, per difficulty, per expected route, per category — coverage only, no speculative cost pie charts, no latency charts mislabelled as EDA | No | S |
| **P2-8** | Resolve or record B5 (`receipt_docs` 5 < `receipts` 6) | dev `ledger.db` / `ensure_index()` | Either re-embed the missing receipt or record it explicitly as a known denominator gap | Yes | S |

---

## Tier P3 — stretch / regression

| ID | Task | Note |
|---|---|---|
| **P3-1** | Pin `pytest` and model digests in the dependency set | Open question 5 from `REQUIREMENTS_AUDIT.md` §11; `:latest` is mutable, which undermines any frozen run |
| ✅ **P3-2** *(done)* | Regression guard for doc/code drift | A test asserting `evaluation/README.md`'s test counts match collected counts would have caught the 39-vs-52 staleness |
| **P3-3** | Cowork benchmark artifacts (Phase 4) | Fixed prompt, shared task definition, common output schema, severe-error definitions, build-vs-buy retrospective. **Gated on P0-7.** Evaluate Cowork externally at task/output level only — no internal-trajectory claims, and **no Cowork integration inside Snag** |
| **P3-4** | Ragas / `sqlglot` as supplementary evidence | Explicitly optional per breakdown §2. Direct NumPy metrics (P0-5) satisfy the requirement without the dependency tree or a judge model |

---

## Scope decision — RESOLVED: the statement side was built

`IMPLEMENTATION_STATUS.md` §5 recorded that the repository implemented only
**receipt-internal arithmetic** reconciliation, while the consultation proof point names
**receipt-to-statement** reconciliation. Two options were put to the team: narrow the proof
point, or build the statement side.

**Decision taken: build it.** `reconciliation.py` now provides statement ingestion,
transaction extraction, receipt-to-statement matching, missing/unmatched-receipt detection,
amount-discrepancy detection, posting-date handling, merchant-name normalization, duplicate
detection, refund handling, and discrepancy-report generation — with 104 tests and 6 API
routes. All 13 proof-point capabilities are now present (refunds partially: the *ledger*
still cannot represent one).

**What this changes for the backlog:** the proof point is now answerable *in principle*.
It is not answered. Two new items follow, and both are gated on the same **B1** blocker as
everything else.

### P0-11 · Measure matching accuracy against a labelled statement

| | |
|---|---|
| **Priority** | P0 — the capability exists; its accuracy is unknown |
| **Files** | new `evaluation/datasets/statement_cases.json`, new `evaluation/fixtures/statements/` |
| **Artifacts** | A real (anonymized) bank/card export + the receipts covering it, with each charge↔receipt pairing labelled by hand |
| **Dependency** | **B1** plus a real statement export |
| **Definition of done** | Matching precision and recall reported with denominators; false-pair rate reported separately from miss rate; the settlement window, discrepancy band and merchant-similarity floor **re-derived from the data** instead of remaining reasoned defaults |
| **Live model** | No — matching is deterministic |
| **Labeling** | **Yes** — the pairings are the ground truth |
| **Difficulty** | M |
| **Risks** | Anonymizing a real statement without destroying the merchant-name variation that makes the test meaningful. Do not tune thresholds on the same data used to report accuracy. |

### P1-8 · Refunds in the ledger

| | |
|---|---|
| **Priority** | P1 |
| **Files** | `finance.py` (`create_transaction`), schema |
| **Artifacts** | A representable refund/credit transaction linked to the original expense |
| **Dependency** | None technically; needs a semantics decision (negative expense? separate kind? link to the original?) |
| **Definition of done** | A statement credit can be posted to the ledger and reconciled; balances and budgets treat it correctly |
| **Live model** | No · **Labeling** No · **Difficulty** M |
| **Risks** | `test_non_positive_amounts_are_rejected` currently passes and encodes the present rule — changing it is a deliberate behaviour change, not a bug fix. |

---

## Original scope note (retained for the record)

