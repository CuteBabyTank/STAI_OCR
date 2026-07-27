# Snag Evaluation — Implementation Status Audit

## Stage 1 re-verification — 2026-07-27

This addendum records executed evidence after the original repository audit. It does not
declare the original W0–W8 plan complete.

- **Infrastructure repair:** the root `.venv` now has the dependencies declared in both
  `requirements.txt` and `evaluation/requirements-eval.txt`; `web-next` was restored with
  `npm ci`. No dependency manifest or lockfile changed.
- **Fixture repair:** SQLite connections used as context managers now close on exit, and the
  evaluation fixture uses a per-process temporary database. This fixes Windows fixture
  rebuild locks without touching a developer's `ledger.db`.
- **Executed suites:** preprocessing/extraction `72 passed`; persistence plus fixture
  regressions `21 passed`; statement reconciliation/API `104 passed`; retrieval plus SQL
  safety `84 passed`; performance invariants `25 passed`; PDF/parser-agreement `96 passed`;
  web Vitest `160 passed`. All are component/structural or synthetic-fixture evidence, not
  receipt or statement accuracy metrics.
- **Trajectory evidence:** dry-run validated seven cases. A remote-model pilot retained all
  seven trajectories in `results/raw/trajectory-20260727T020610Z_stage1-trajectory.json`:
  six passed and `RCT-006` failed `final_supported_by_observation`. This is a single pilot,
  not a final rate or benchmark result.
- **Final regression verification:** complete Python suite `671 passed, 1 warning` in 120.80s;
  complete web Vitest suite `160 passed` in 616ms. The warning is Pydantic's existing
  `PromptModelConfig.model_name` protected-namespace warning and does not fail a test.
- **Known execution caveat:** the first full Python attempt produced `652 passed, 19 failed`.
  The failures were classified as missing declared `pypdfium2`, Windows default-encoding test
  defects, and evidence-document drift after the live artifact was created. The focused fixes
  above were rerun successfully; the final full-suite rerun is recorded in the Stage 1 log.

### Current W0–W8 execution status

| Workstream | Status after Stage 1 | Evidence boundary |
|---|---|---|
| W0 | Partially implemented | Runtime card and commands are recorded; final benchmark configuration remains unfrozen. |
| W1 | Partially implemented | Deterministic fixtures/corpora execute; independently verified receipt and statement labels remain missing. |
| W2 | Implemented and verified for covered component tests | Passing synthetic/component tests do not measure extraction or matching accuracy. |
| W3 | Partially implemented | Dry-run plus one live seven-case synthetic pilot; no final trajectory dataset. |
| W4 | Missing | No final E2E reconciliation evaluation. |
| W5 | Partially implemented | Retrieval/SQL safety mechanisms execute; no labeled question-answer accuracy evaluation. |
| W6 | Partially implemented | Structural invariants execute; no final repeated live latency/cost study. |
| W7 | Missing | No final EDA or failure-distribution analysis. |
| W8 | Partially implemented | Configuration and raw pilot evidence exist; no evaluation notebook/report. |

**Audited commit:** `41b8fa1b7b15a8c2aaaffd5e78fc9b9e6a9c5160` (`main`, 2026-07-26 16:07 +0800)
**Working tree at audit:** clean except untracked `docs/FOLLOWup.md`
**Audit date:** 2026-07-26
**Method:** direct execution and inspection at the commit above. Every "Implemented and
verified" row names a file, a symbol, a command that was run, and the result observed.
**Scope:** required by `docs/FOLLOWup.md` Phases 1–4. Phase 5 lives in
[`IMPLEMENTATION_BACKLOG.md`](IMPLEMENTATION_BACKLOG.md).

> **Nothing in this repository is a measured evaluation result.** No accuracy figure, pass
> rate, receipt-level exact match, retrieval recall, or real request latency exists. What
> exists is instrumentation plus two offline microbenchmarks.

> **Production code changes.** The audit itself (Phases 1–4) modified no application code.
> The subsequent remediation pass (§0.1) made **one** production change: a two-line guard in
> `extraction._num` fixing defect **D6**, found by a new test. It is described in §9 and
> carries regression tests. Everything else added is tests, evaluation tooling, or docs.

---

## 0. Executive summary

| | At audit (`41b8fa1`) | After remediation | Share now |
|---|---|---|---|
| Audit units (W0–W8 checklist items, metrics, and named deliverables) | 195 | **195** | 100% |
| Implemented and verified | 46 | **63** | **32.3%** |
| Partially implemented | 29 | **24** | 12.3% |
| Missing / documented-but-not-implemented / blocked | 120 | **108** | 55.4% |

Tests executed — **all pass, nothing broken**:

| Suite | Command | At audit | Now |
|---|---|---|---|
| Evaluation (Python) | `./.venv/bin/python -m pytest evaluation/tests -q` | 244 | **658** |
| Pre-existing extraction | `./.venv/bin/python -m pytest test_extraction.py -q` | 10 | **10** |
| Quick Chat (TypeScript) | `cd web-next && npx vitest run` | 78 | **160** (2 files) |
| Retrieval microbenchmark | `./.venv/bin/python evaluation/bench_retrieval.py` | ran | ran |
| Fixture seeder | `./.venv/bin/python evaluation/fixtures/seed_finance.py` | ran | ran |
| Trajectory runner | `./.venv/bin/python -m evaluation.trajectory --dry-run` | — | ran |
| Configuration capture | `./.venv/bin/python -m evaluation.report config` | — | ran |
| **Total** | | **332** | **828 tests, 0 failures, 0 skips, 0 xfails** |

The headline: **the component layer is near-complete, the harness is wired end to end, the
missing product capability the proof point named has been built — and the evaluation itself
still has not been run.** Every metric in the breakdown's own metric tables remains uncomputed, and the
system has still never been executed against a model as part of an evaluation. What
changed is that the remaining gaps are now almost entirely gated on two external inputs —
a reachable Ollama endpoint and labelled receipts — rather than on unwritten code.

### 0.1 What the remediation pass closed

Everything below was gated on neither a model nor labelling, so it was implementable.
Two pre-existing product defects surfaced in the process (**D5**, **D6** — §9).

| Area | Was | Now | What closed it |
|---|---|---|---|
| Receipt reconciliation (`extraction.reconcile`) | ❌ zero tests | ✅ 34 tests | `test_w2a_reconcile.py` — tolerance floor, relative band, discount path, and the wiring into `needs_disambiguation` |
| JSON / numeric coercion | 🟡 | ✅ 47 tests | `test_w2a_coercion.py` — found and fixed **D6** |
| Field confidence + value-equality gating | ❌ zero tests | ✅ 23 tests | `test_w2a_confidence.py` |
| PDF page expansion, batch failure isolation | ❌ zero tests | ✅ 24 tests | `test_w2a_pdf_batch.py` — synthesised PDFs, no fixture committed |
| Receipt save / line-item linkage, posting fidelity | 🟡 indirect | ✅ 18 tests | `test_w2e_persistence.py` |
| Budget aggregation | ❌ zero tests | ✅ 23 tests | `test_w2b_budgets.py` — found **D5** (carry-forward is inert) |
| ReAct loop guard, step budget, clarification | 🟡 detectors only | ✅ 22 tests | `test_w2d_agent_paths.py` — drives the **real** `agent_stream` |
| Two Quick Chat parsers agreeing | 🟡 tested separately | ✅ 72 + 82 tests | Shared corpus `datasets/quickchat_corpus.json` read by both suites |
| Machine-readable results | ❌ no directory, no writer | ✅ implemented + 32 tests | `evaluation/report.py`, `results/` |
| Trajectory runner (live) | ⏸ no entry point | ⏸ CLI wired, **still unexecuted** | `python -m evaluation.trajectory` — blocked only on an endpoint |
| Docs drifting from code | ❌ caused 3 stale claims | ✅ 15 tests | `test_docs_match_code.py` |
| **Receipt-to-statement reconciliation** | ❌ **absent from the product** — 11 of 13 proof-point capabilities missing | ✅ built, 104 tests | `reconciliation.py` + 6 API routes. See §5 |

**Deliberately not done**, and why:

- **Receipt accuracy metrics** (header/line-item/exact match/review recall) — blocked on
  **B1**: one unlabelled image. Not resolvable in code.
- **SQL execution accuracy, retrieval relevance, RAG answer evaluation, live latency,
  the live trajectory run** — all require a reachable Ollama; both endpoints were
  unreachable throughout.
- **E2E runner, EDA, notebook** — depend on the above producing results first.
- **Measuring** the reconciliation that was built — matching precision/recall needs a real
  bank export and labelled receipts (**B1**). The capability exists; its accuracy does not.
- **A UI for statements** — backend and API only; `web-next` is untouched.
- **Refunds in the ledger** — `finance.create_transaction` still rejects non-positive
  amounts. Statement-side credits are handled; making the ledger represent a refund is a
  separate schema and semantics change.

---

## 1. Status of the recent additions (FOLLOWup §Phase 1 "specifically inspect")

The follow-up asks exactly what these six artifacts do and do not provide. Answered
literally, per artifact.

### 1.1 What each provides

| Artifact | Correctness evidence | Structural perf. evidence | Real E2E latency | Live-model perf. | Retrieval relevance ground truth | Mocked / isolated only |
|---|---|---|---|---|---|---|
| `PERFORMANCE.md` | indirect | **yes** | **no** | **no** | no | mostly |
| `bench_retrieval.py` | no | **yes** | **no** | **no** | no | **yes — synthetic vectors** |
| `test_w2a_preprocess.py` | **yes** (image transforms) | no | no | no | no | offline, synthetic images |
| `test_w5_retrieval.py` | **yes** (ranking, scope isolation) | no | no | no | **no** | **yes — synthetic vectors, stubbed `_embed`** |
| `test_w6_performance.py` | **yes** (deterministic SQL answers) | **yes** (round-trip count) | **no** | **no** | no | **yes — `ollama` and `_chat` stubbed** |
| README changes | none | none | none | none | none | n/a |

### 1.2 Precise limitations

**`PERFORMANCE.md`** — its own opening paragraph is accurate and does not overclaim: it
states plainly that neither Ollama endpoint was reachable and that no end-to-end latency
was measured. Verified independently: `curl` to `http://localhost:11434/api/tags` and to
`http://103.231.240.155:11434/api/tags` both returned nothing during this audit. Three
further limitations that the file does not spell out:

- The `~6,000 ms` / `~20,000 ms` vision figures are labelled "recorded previously" — they
  are **historical development observations, not measurements of the audited commit**, and
  per breakdown §3 must not be attributed to any evaluated configuration.
- The "before" columns in its two benchmark tables (§4 retrieval, §3 index) **cannot be
  reproduced from this tree**: the pre-optimization code no longer exists. They are
  single-session historical records.
- Re-running `bench_retrieval.py` during this audit gave 11.66 ms at 5,000 receipts against
  the documented 14.58 ms — same order, different machine state. The benchmark is not
  pinned to a fixed environment, so its absolute numbers are not comparable across runs.

**`bench_retrieval.py`** — a **microbenchmark, not end-to-end performance**. It builds a
synthetic corpus of random vectors and times `core.semantic_search` with `_embed` bypassed.
It measures DB load + NumPy scoring only. No model call, no HTTP, no API layer, no real
embeddings. Its output cannot be presented as the latency of any user-facing operation.

**`test_w2a_preprocess.py`** (15 tests) — real correctness evidence for
`core.preprocess_image`: EXIF orientation, downscale ceiling, aspect ratio, format/mode
normalization, byte-identical fast path, and pass-through of undecodable bytes. Images are
synthesised with Pillow; one test uses the real `Receipt.jpg`. **It is not an accuracy
test** — it verifies what pixels reach the model, not what the model reads from them.

**`test_w5_retrieval.py`** (19 tests) — real correctness evidence for the *mechanism* of
`core.semantic_search`: top-k ordering, the relevance floor, stale/NULL vector handling,
keyword fallback, and — most valuable — **scope isolation**, the guardrail preventing a
single-receipt question from reading the rest of the ledger. **It is not retrieval
relevance evaluation.** Embeddings are hand-chosen orthogonal unit vectors written directly
into `receipt_docs`, and `_embed` is monkeypatched. There is **no relevant-receipt-ID
ground truth anywhere in the repository**, so context precision, context recall, and
retrieval recall are all uncomputed. A test asserting that a vector of `[1,0,0]` ranks
above `[0,1,0]` tells you nothing about whether `nomic-embed-text` puts the right receipt
first for a real question.

**`test_w6_performance.py`** (25 tests) — **contains no timing assertion of any kind.**
Confirmed by reading all 190 lines: no `time`, `perf_counter`, or duration threshold
appears. What it does verify, with the `ollama` module and `core._chat` stubbed:

- generation defaults are passed (`keep_alive`, `num_ctx`, `num_predict`, `temperature=0`)
  and that an explicit caller argument is not clobbered — a **structural** latency property;
- `core._deterministic_answer` formats scalar SQL results without a model call — genuine
  correctness evidence;
- **round-trip count**: `ask_ledger` costs 1 `_chat` call, `agent_run` costs 3. This is the
  single most useful performance test in the repo and it is still structural — it counts
  calls against a fake model. It says nothing about how long a call takes.

**Verdict required by FOLLOWup:** none of these six artifacts provides real end-to-end
latency, live-model performance, or retrieval relevance ground truth. Describing
`bench_retrieval.py` or `test_w6_performance.py` as end-to-end performance evidence would
be false.

### 1.3 README / doc changes

`evaluation/README.md` gained a coverage table and defect write-ups. Two problems found:

- **Its test counts are stale and understate reality**: it claims 39 finance tests (actual
  **52**), 62 SQL/ReAct tests (actual **65**), and 64 Quick Chat tests (actual **78** TS +
  **31** Python). Per FOLLOWup, counts must not be inferred from documentation — they were
  re-derived per file by executing pytest.
- Its `Layout` block omits `test_w2a_preprocess.py`, `test_w5_retrieval.py`,
  `test_w6_performance.py`, `PERFORMANCE.md`, and `requirements-eval.txt` entirely.
- Its coverage table marks **W2-B "Done"**. §3.3 below shows one W2-B checklist item
  (budget aggregation and carry-forward) has **zero tests**. This is exactly the
  "workstream marked complete because related tests exist" failure the follow-up warns
  against.

### 1.4 Staleness in the W0 freeze artifacts — corrected during this audit

`REQUIREMENTS_AUDIT.md` and `CONFIGURATION.md` were both written against commit
`9ac15ec`, which is **two commits behind HEAD**. Three statements were verified false at
HEAD and have been corrected in place (documentation only, no code touched):

| Stale statement | Verified state at HEAD `41b8fa1` |
|---|---|
| `CONFIGURATION.md`: "`MLFLOW_TRACKING_URI` — No — read by `mlflow`" (not set in code) | **Set in code.** `core.py:461` calls `mlflow.set_tracking_uri(...)` defaulting to the repo's `mlflow.db`. |
| `CONFIGURATION.md`: "`MLFLOW_ENABLED=0` caveat: the clarify path calls `mlflow.log_metric` directly" | **Fixed.** The only surviving direct `mlflow.log_metric` call is inside the guarded helper `core._mlog_metric` (`core.py:493`). |
| Both files: commit `9ac15ec`, `core.py` 3019 lines, `finance.py` 1503 lines | HEAD is `41b8fa1`; `core.py` is **3167** lines, `finance.py` **1602**. |

**Every line-number citation in both documents has drifted** (e.g. `agent_stream`
2856→2997, `_MAX_AGENT_STEPS` 2617→2760, `_run_agent_tool` 2770→2913,
`parse_quick_text` 1456→1554, `AGENT_MODEL` 438→450). Rather than re-pin numbers that will
drift again, a header note now pins both documents to their audited commit and directs
readers to symbol names. This document cites symbols, not lines.

---

## 2. Status legend

| Status | Meaning in this audit |
|---|---|
| **✅ Verified** | Implemented and verified — file, symbol, executed test, observed result all recorded |
| **🟡 Partial** | Partially implemented — some sub-behaviour covered, named gap remains |
| **📄 Doc-only** | Documented but not implemented |
| **⏸ Unexecuted** | Test/code exists but has never been executed successfully |
| **❌ Missing** | Missing |
| **🔒 Blocked** | Blocked by environment / model / data |
| **➖ N/A** | Not applicable to the actual architecture |

---

## 3. Per-workstream audit

### 3.1 W0 — Requirements and repository audit (5 tasks)

| # | Task | Status | Evidence |
|---|---|---|---|
| 1 | Recheck transcript for the three layers, ground truth, Ragas, repeated runs, EDA, latency/cost, notebook, human eval | 🔒 Blocked | No transcript in the repository. `REQUIREMENTS_AUDIT.md` §12 records this as deferred. Not resolvable in code. |
| 2 | Record timestamps for anything labelled "required" | 🔒 Blocked | Same — depends on the transcript. |
| 3 | Inspect repo; list tests, fixtures, MLflow traces, SQL/RAG/ReAct logs, eval scripts, installed libraries | ✅ Verified | `REQUIREMENTS_AUDIT.md` §2/§3/§6/§7. Re-verified: `mlflow.db` holds **60** runs (52 FINISHED, 8 FAILED); `ragas`/`sqlglot`/`langgraph` absent; `jupyterlab` now present via `requirements-eval.txt`. |
| 4 | Freeze an evaluation configuration (commit, image, `OLLAMA_HOST`, models, env) | 🟡 Partial | `CONFIGURATION.md` exists and is thorough, but (a) pins the wrong commit, (b) carried two statements false at HEAD (§1.4), (c) **no run has been frozen** — the per-run capture template has never been filled in. Model digests are still unpinned; `:latest` is mutable. |
| 5 | Identify which historical receipt data includes verified ground truth | ✅ Verified | Answer: **none**. Re-verified: `ledger.db` = 6 receipts / 14 line items / 5 `receipt_docs`; `Receipt.jpg` is the only image in the tree; no labels file in any format. |

**W0: 2 verified, 1 partial, 2 blocked.** The DoD criterion "the exact tested deployment
configuration can be reproduced" is **not met** — no deployment has been tested.

### 3.2 W1 — Dataset and ground truth (6 deliverables + 43 coverage items)

| Deliverable | Status | Evidence |
|---|---|---|
| `datasets/cases.json` or equivalent | 🟡 Partial | Only `datasets/trajectory_cases.json`: **7 cases, all `RCT` (ReAct routing)**. The breakdown proposes **10** case families (`REC`, `REV`, `PST`, `QCK`, `FIN`, `SQL`, `RAG`, `RCT`, `BAK`, `E2E`). **1 of 10 exists.** Every case's `expected_answer_contains` is deliberately empty — honest, but it means no case can currently fail on answer content. |
| Receipt fixtures + manually verified labels | ❌ Missing 🔒 | One unlabelled image. Blocker **B1**, unchanged. |
| Finance database fixtures | ✅ Verified | `fixtures/seed_finance.py` executed during this audit: builds 6 accounts / 5 transactions / 2 receipts / 3 line items, self-verifies net worth 67,700.00 (assets 68,500.00, liabilities 800.00) against hand-computed constants, exit 0. Reproducible and versioned as a script (the `.db` is correctly gitignored as a build artifact). |
| Dataset schema + labeling guide | 🟡 Partial | Schema exists as **executable validation** — `trajectory.TrajectoryCase` / `load_cases()` reject duplicate IDs, unknown tools, unknown events, contradictory cases, and unknown fields (8 tests in `test_w3_trajectory.py`). Stronger than a `schema.json`. **No labeling guide exists**, and the schema covers only the `RCT` family. |
| Coverage matrix | ❌ Missing | The breakdown's §W1 sample-size rule says "start with a coverage matrix first". None exists in any form. |
| Dataset version / changelog | 🟡 Partial | `trajectory_cases.json` carries `"version": "0.1.0"` and a status line. No `changelog.md`. |

**Dataset coverage (43 proposed items), by family:**

| Family | Items | State |
|---|---|---|
| Receipts (clean, blurry, rotated, long, PDF, multipage, batch, PHP, mixed-language, VAT/discount, repeated items, summary-lines, arithmetic errors, missing total, duplicate, unsupported file) | 14 | **0 present as dataset cases.** Guardrail behaviours for *unsupported file*/*oversized*/*empty* are unit-tested (`test_w2d_sql_react.py`), but no receipt case record exists. 🔒 B1 |
| Quick Chat (standard, income `+`, `k` shorthand, relative dates, accounts, categories, transfers, ambiguous, invalid) | 9 | **9 covered as unit-test cases** in `parseQuick.test.ts` (`describe` blocks: amount parsing, kind classification, relative date parsing, account matching, category matching, note extraction, invalid input, draft shape, worked examples). 🟡 — they exist as tests, **not as versioned dataset records with case IDs**, so they cannot feed a metric table. |
| SQL / RAG / ReAct questions | 11 | 🟡 2 partially represented (`RCT-001..007` cover simple totals and ambiguous-recent routing). No expected results, no out-of-scope set, no empty-ledger set, no no-supporting-receipt set. |
| Finance integration | 9 | 🟡 8 covered as unit tests in `test_w2b_finance.py`; **budget aggregation is not tested at all**. Again: tests, not dataset records. |

**W1: 1 verified, 3 partial, 2 missing.** DoD criterion "every metric has the necessary
ground truth" is **not met for any accuracy metric**.

### 3.3 W2 — Layer 1 component evaluation (53 checklist + 10 metrics + 4 deliverables)

#### W2-A Receipt extraction and safeguards (14) — 12 ✅ / 0 🟡 / 2 ❌ *(was 4 / 4 / 6)*

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | Input validation: types, size, empty | ✅ Verified | `test_w2d_sql_react.py`: `test_empty_upload_is_rejected`, `test_oversized_upload_is_rejected`, `test_unsupported_content_type_is_rejected`, `test_supported_content_types_are_accepted` (parametrized png/jpeg/pdf). *(Misfiled — W2-A items living in the W2-D file.)* |
| 2 | Image preprocessing **and PDF page expansion** | ✅ Verified | Preprocessing: 15 tests (`test_w2a_preprocess.py`). PDF expansion: 12 tests (`test_w2a_pdf_batch.py`) — magic-byte detection, one image per page, pages preprocessed to the 1600 px ceiling, `PDF_MAX_PAGES` bound, `PDF_RENDER_SCALE` proven live (not dead config), corrupt PDF raises rather than returning zero pages. PDFs are synthesised with Pillow, so no binary fixture is committed. |
| 3 | JSON coercion and schema validation | ✅ Verified | `test_w2a_coercion.py` (13 tests on `_coerce_json`): fenced, prose-wrapped both sides, nested objects, fence-beats-braces. Failure is **visible** — truncated/empty/malformed output raises rather than yielding `{}`, which would have saved a blank receipt that reconciles vacuously. Plus `test_schema_validation_rejects_junk_output`. |
| 4 | Header-field extraction | ❌ Missing 🔒 | Requires a live model **and** labelled receipts (**B1**). |
| 5 | Line-item extraction | ❌ Missing 🔒 | Same. |
| 6 | Numeric-field coercion | ✅ Verified | `test_w2a_coercion.py` — peso signs, thousands separators, whitespace, negatives; unreadable values become `None` **not 0.0**; booleans rejected. Found **D6**: containers were stringified into fabricated numbers (`[1, 2]` → `12.0`). |
| 7 | Summary-line remapping | ✅ Verified | `test_extraction.py` → `_remap_summary_lines`. |
| 8 | Duplicate-item handling | ✅ Verified | `test_extraction.py` → `_dedupe_items`. |
| 9 | Payment-field repair | ✅ Verified | `test_extraction.py` → `_fix_payment_fields`. |
| 10 | Reconciliation tolerance behaviour | ✅ Verified | `test_w2a_reconcile.py` (34 tests). The ₱1.00 absolute floor and the 2% relative band are asserted **on both sides of the boundary**, from the receipt semantics rather than by reading the constant back. Covers the discount allowance (both conventions), symmetry (extra items are as much a defect as missing ones), and the cases where reconciliation must stay silent (no items, no total, zero/negative total, unreadable amounts). |
| 11 | Review / disambiguation reasons | ✅ Verified | The 3 `needs_disambiguation` tests plus the reconcile→review wiring: `test_an_unreconciled_receipt_is_sent_for_human_review` and `test_a_reconciling_receipt_is_not_sent_for_review` (false-review guard). |
| 12 | Field-confidence availability and value-equality gating | ✅ Verified | `test_w2a_confidence.py` (23 tests). Span reconstruction is exact; a numeric field **changed by post-processing is left unscored** rather than inheriting a probability describing a different number; item confidence follows an item through de-duplication rather than by index; absent logprobs yield `None`, never a default that reads as certainty. |
| 13 | Receipt save and line-item linkage | ✅ Verified | `test_w2e_persistence.py` — items written, linked to their own receipt, field values and printed order preserved, header round trip, review flag and source file persisted. |
| 14 | Per-page failure isolation in batch | ✅ Verified | `test_w2a_pdf_batch.py` — one failing page of four leaves the other three succeeding and persisted; the failure reports its error and saves no partial row; an invalid file among valid ones does not stop them; progress reaches 100% even with failures; nothing is dropped under concurrency. |

#### W2-B Personal-finance deterministic logic (13) — 11 ✅ / 2 🟡 / 0 ❌ *(was 11 / 1 / 1)*

All verified rows are from `test_w2b_finance.py` (52 tests, executed, all pass) against the
deterministic fixture with hand-computed expectations.

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | Account balance calculations | ✅ | `test_account_balances_match_ground_truth`, `test_transfer_debits_fee_from_source_only`, `test_liability_account_balance_is_negative` |
| 2 | Net-worth calculation | ✅ | 4 tests incl. excluded/archived/hidden-liability variants |
| 3 | Expense and income creation | ✅ | `finance.create_transaction` via validation suite + fixture |
| 4 | Transfer validation and effects | ✅ | `test_transfer_to_same_account_is_rejected`, `..._to_non_debit_account_is_rejected`, fee debit test |
| 5 | **Budget aggregation and carry-forward** | 🟡 Partial | **Aggregation ✅** — `test_w2b_budgets.py` (23 tests): expenses in-period counted, other categories and income excluded, out-of-period spending excluded, per-interval windows, deletion reverses the total, percent-of-income limits, over-100% not clamped, zero limit yields `None` instead of dividing by zero, and a backup/restore round trip. Assertions are written as **deltas against `date.today()`**, so they do not rot as the clock moves. **Carry-forward ❌ — it does not exist (defect D5).** The flag is accepted, persisted, sent by the UI and typed in `types.ts`, but no computation in `finance.py` ever reads it; two otherwise identical plans resolve to the same limit. Characterized by test so the gap is measured, not assumed working. |
| 6 | Templates | ✅ | `test_using_a_template_creates_a_matching_transaction` |
| 7 | Recurring schedule advancement | ✅ | 2 tests (date rolls forward one month; transaction created) |
| 8 | Installment payments | ✅ | `test_installment_payment_increases_paid_amount` |
| 9 | Goal activity | ✅ | `test_goal_deposit_updates_goal_and_debits_account` |
| 10 | Debt activity | ✅ | `test_debt_payment_updates_paid_amount` |
| 11 | Receivable activity | ✅ | `test_receivable_collection_updates_collected_amount` |
| 12 | Upcoming-obligation aggregation | ✅ | `test_upcoming_returns_the_seeded_obligations` |
| 13 | Transaction history / statistics consistency | 🟡 Partial | History verified (count, kind partition, account filter, delete-restores-balance). **"Statistics" is not covered** — no aggregate/statistics function is called by any test. |

#### W2-C Rule-based Quick Chat (8) — 8 ✅ / 0 🟡 *(was 7 / 1)*

`parseQuick.test.ts` (78 tests, executed via `npx vitest run`, all pass) plus
`test_w2c_quick_python.py` (31 tests, pass).

| # | Item | Status | Evidence |
|---|---|---|---|
| 1–4 | Amount parsing, `k` shorthand, kind classification, relative dates | ✅ | `describe` blocks of the same names; Python mirrors for D2/D4 regressions |
| 5 | Account matching | ✅ | `describe("account matching")` |
| 6 | Category matching | ✅ | `describe("category matching")` |
| 7 | Missing / ambiguous field handling | ✅ | `describe("invalid input")`, `describe("note extraction")` |
| 8 | Server/client parser consistency | ✅ Verified | **A shared corpus now drives both suites**: `datasets/quickchat_corpus.json` (15 accepted + 4 rejected cases) is read by `test_w2c_parser_agreement.py` (72 tests) and `web-next/app/lib/parseQuick.corpus.test.ts` (82 tests), so a divergence fails on exactly one side and is immediately localizable. Compared: kind, amount, note, resolved date — account/category ids are excluded on purpose, since the TS parser is *given* accounts while the Python one reads them from the database, so a mismatch there would reflect different inputs rather than different parsing. A Python-side test asserts the TS file still reads the corpus, so the two cannot silently decouple. **Result: the two parsers agree on every case**, and `_INCOME_WORDS` / `INCOME_WORDS` were verified to list identical keywords. |

`test_quick_chat_uses_no_model` ✅ verifies the breakdown's §1.5 constraint that Quick Chat
is deterministic — good, and correctly framed.

#### W2-D SQL, RAG, ReAct tools (10) — 5 ✅ / 2 🟡 / 3 ❌ *(was 3 / 4 / 3)*

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | Validator accepts read-only `SELECT` | ✅ | `test_validator_accepts_read_only_selects` |
| 2 | Rejects forbidden verbs / multiple statements | ✅ | 5 tests incl. verb-hidden-after-select and non-SELECT leading keywords |
| 3 | Generated SQL executes against the intended scoped DB | 🟡 Partial | The **sandbox** is verified (`test_scoped_db_contains_only_the_requested_receipts`, line-item restriction, read-only connection refuses writes). The **generation** half needs a live model. |
| 4 | SQL execution returns the correct result — not similar query text | ❌ Missing | **No SQL question set with expected results exists.** The one apparent exception, `test_the_sql_answer_is_the_exact_computed_number`, feeds hardcoded SQL from a stubbed model — it tests the deterministic formatter, not SQL generation accuracy. **SQL execution accuracy is uncomputed.** |
| 5 | Retrieval returns the relevant receipt IDs | 🟡 Partial | Mechanism verified on synthetic vectors (§1.2). **No relevance ground truth**, so recall/precision are uncomputed. |
| 6 | Explicit receipt references remain scoped | ✅ | 5 scope-isolation tests incl. `test_explicit_scope_argument_beats_an_inline_reference` |
| 7 | ReAct selects SQL for numeric/aggregate questions | ❌ Missing 🔒 | Requires a live model. Cases defined (`RCT-001..007`), never run. |
| 8 | ReAct selects receipt search for receipt-content questions | ❌ Missing 🔒 | Same. |
| 9 | Ambiguous recent-receipt questions trigger clarification | ✅ Verified | The detector tests, plus the **real path through `agent_stream`** (`test_w2d_agent_paths.py`): an ambiguous "my recent receipt" question emits `clarify` **before the model is called at all** (asserted by capturing the call list), the clarification names the candidate receipts, `clarify` is terminal, an explicit `receipt_ids` scope correctly suppresses it, and an unambiguous question does not clarify. |
| 10 | Repeated tool calls and step limits handled | ✅ Verified | `test_w2d_agent_paths.py` drives the real guard with a scripted model that never stops: the repeated call is served from cache (exactly 1 `action`, 2 `observation` events), the repeat is marked in the step trail so a loop stays visible behind a healthy-looking answer, and the run force-finalizes with an answer instead of hanging or erroring. Separately, a model that never answers is bounded at exactly `_MAX_AGENT_STEPS` actions and terminates in `final`, not `error`. Distinct inputs to the same tool are correctly **not** treated as a loop. |

#### W2-E Receipt posting and backup/restore (8) — 8 ✅ / 0 🟡 *(was 7 / 1)*

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | Posting creates the expected finance transaction | ✅ | `test_posting_a_receipt_creates_one_linked_expense` |
| 2 | Transaction links back to the correct `receipt_id` | ✅ | same + `test_restore_preserves_receipt_transaction_linkage` |
| 3 | Amount, date, category, account, currency preserved | ✅ Verified / ➖ currency N/A | `test_w2e_persistence.py` asserts amount, receipt date (so it lands in the right budget period), target account, vendor→note, and category mapping through `_category_id_for_name` — including that an unmatched category leaves the transaction uncategorized rather than blocking the post. **Currency is architecturally N/A**: the `transactions` table has no currency column, so a USD receipt posts as a bare number indistinguishable from PHP. Characterized by `test_a_posted_transaction_carries_no_currency_of_its_own` and recorded as a limitation rather than dropped from the checklist. |
| 4 | Duplicate posting behaviour | ✅ | `test_reposting_a_receipt_does_not_duplicate` |
| 5 | Backup contains all intended finance records | ✅ | `test_backup_contains_every_intended_record_group` |
| 6 | Restore recreates records and relationships | ✅ | `test_restore_recreates_records_and_relationships` |
| 7 | Malformed backup behaviour | ✅ | `test_malformed_backup_is_handled_visibly`, `test_no_malformed_payload_can_destroy_the_ledger` (12 payload shapes), `test_backup_with_an_injected_column_name_is_refused`, `test_a_genuinely_empty_backup_still_restores` |
| 8 | Does not claim authenticated cloud sync | ✅ | Documentation constraint; honoured throughout `evaluation/`. |

Defect **D1** (malformed backup wiping all 12 finance tables, reachable from an unauthenticated
`POST /backup/import`) was found here and fixed with regression tests — the most valuable
concrete outcome of the evaluation work so far.

#### W2 core metrics (10) — 0 computed

| Metric | Status |
|---|---|
| Receipt-level exact match | ❌ Missing 🔒 B1 |
| Field-level accuracy | ❌ Missing 🔒 B1 |
| Line-item accuracy | ❌ Missing 🔒 B1 |
| Review recall | ❌ Missing 🔒 B1 |
| False-review rate | ❌ Missing 🔒 B1 |
| Quick Chat field accuracy | ❌ Missing — 109 tests pass, but pass/fail is not a field-accuracy ratio over a labelled case set |
| SQL execution accuracy | ❌ Missing 🔒 |
| Retrieval recall | ❌ Missing 🔒 |
| Backup completeness | ❌ Missing — behaviour verified, ratio not reported |
| Restore success | ❌ Missing — same |

#### W2 deliverables (4)

| Deliverable | Status |
|---|---|
| Automated component tests | ✅ Verified — 332 tests, executed, all pass |
| Machine-readable result file | 🟡 Partial — **writer implemented and tested, no run has produced one.** `evaluation/report.py` (32 tests) writes `results/{raw,processed,failures}/` with the runtime configuration capture and its `configuration_gaps` attached to every file. `rate()` returns `None` for an empty denominator so an unmeasured metric can never be reported as 0% or 100%. The remaining gap is a live run, not code. |
| Summary table by module and case category | 🟡 Partial — `evaluation/README.md` has one, with stale counts (§1.3) |
| Failure log with case IDs | 🟡 Partial — `report.summarize()` retains `failed_case_ids` and a per-check breakdown naming the cases that failed it; `trajectory.main()` writes a taxonomy block. No data yet — needs a run. |

**W2 totals: 45 ✅ / 7 🟡 / 15 ❌ across 67 units** *(was 32 / 12 / 23)*. The 15 remaining are the 10 uncomputed core metrics plus 5 checklist items, **all** gated on a live model or on B1 labelling.

### 3.4 W3 — Layer 2 trajectory evaluation (22 checks + 5 deliverables)

The harness (`evaluation/trajectory.py`, 457 lines) is the strongest single artifact in the
directory: 37 self-tests, all pass. It projects events into a `Trajectory`, evaluates a
case against 8 independent checks without short-circuiting, aggregates metrics that return
`None` (not 0 or 1) when no case applies, and builds a failure taxonomy. It also holds a
**contract test against the real generator** (`test_agent_stream_event_contract`,
`test_known_tools_match_the_real_dispatcher`) — so it cannot silently drift from `core`.

**But `collect_trajectory()` and `run_cases()` have still never been executed.** A CLI entry
point now exists (`python -m evaluation.trajectory`, verified via `--dry-run`, which loads and
validates all 7 cases and prints the plan without calling a model) and it writes results
through `report.write_result` with the configuration attached. Execution requires a
reachable Ollama; both endpoints were unreachable during this audit. **⏸ Unexecuted.**
There is no stored trajectory, no results file, and no visualization.

| Pipeline | Checks | Status |
|---|---|---|
| Receipt pipeline | 5 | 🟡 2 partial (invalid input stops before OCR — verified at unit level, not as a trajectory; review reasons emitted — 3 unit tests). ❌ 3 missing: failed page doesn't stop the batch, reconciliation-before-verified ordering, saved receipt matches accepted extraction. |
| Receipt-to-finance | 4 | ✅ 2 (one receipt → one transaction; receipt traceable from the finance record). 🟡 2 (posting only via supported workflow; propagation — account balance verified, budget/history/statistics not). |
| Question-answering | 6 | ✅ 1 (receipt scope respected — unit level). 🟡 3 (no repeated loop, max-step controlled final, observation↔final consistency — all implemented as harness checks, **never run against a real trajectory**). ❌ 2 (correct route selected; receipt-search answers cite the supporting receipt). 🔒 live model. |
| Quick Chat | 4 | ✅ 1 (recorded as deterministic parsing). 🟡 1 (dependent modules show the same effect). ❌ 2 (draft not silently treated as verified intent; accepted/corrected values are what enter the ledger) — both are UI-level and untested. |
| Backup/restore | 3 | ✅ 3 (objects and links survive; malformed input handled visibly; not described as cloud sync). |

| Deliverable | Status |
|---|---|
| Trace collector / exporter | ✅ Verified — 37 self-tests, and the **exporter half now exists**: `trajectory.main()` writes every raw trajectory (including collection failures, which are recorded as results rather than dropped) to `results/raw/` |
| Expected-trajectory case definitions | 🟡 Partial — 7 cases, 1 of 5 pipelines |
| Actual-vs-expected trace comparison | ⏸ Unexecuted — `evaluate_case` is fully tested against **synthetic** events and now reachable from the CLI; still never run on a real trajectory. **This is the single highest-value remaining action** and is blocked only on an endpoint |
| One successful and one failed trajectory visualization | ❌ Missing |
| Failure taxonomy | 🟡 Partial — `failure_taxonomy()` implemented and tested, and `trajectory.main()` emits a taxonomy block grouping case ids by failed check; no data to populate it |

**W3 totals: 13 ✅ / 7 🟡 / 7 ❌/⏸ across 27 units** *(was 8 / 11 / 8)*. The DoD criterion "evaluation uses real
observable events from Snag" is **not met** — every event evaluated so far is synthetic.

### 3.5 W4 — Layer 3 end-to-end evaluation (7 jobs + 9 metrics + 5 deliverables)

**Entirely missing. 0 of 21 units.** No E2E runner, no manual protocol document, no
pre/post database snapshots, no task-level result file, no correction/timing sheet, no
failure evidence. None of `E2E-REC`, `E2E-PST`, `E2E-QCK`, `E2E-MAN`, `E2E-ASK`, `E2E-BUD`,
`E2E-BAK` exists in any form. Correction-inclusive time — the metric the follow-up asks
about specifically — has never been measured, and no protocol for measuring it is written.

One relevant precedent is recorded in `REQUIREMENTS_AUDIT.md` §10b: defect **D4** (Quick
Chat inflating `250 milk` to ₱250,000,000) was found by driving the real `POST /parse`
endpoint, **not** by the unit tests, which all happened to use notes starting with safe
letters. That is direct evidence from this repository that the component layer cannot
substitute for W4.

### 3.6 W5 — SQL, RAG, ReAct, question-answering evaluation (21 units)

| Group | Item | Status |
|---|---|---|
| SQL (7) | Valid read-only SQL | ✅ (validator) |
| | No prohibited operations | ✅ (validator) |
| | Correct execution result | ❌ Missing — no question set, no expected results |
| | Correct receipt scope | 🟡 sandbox verified; not measured over questions |
| | Correct handling of empty results | 🟡 `_deterministic_answer([])` → "no records" is tested; not measured over questions |
| | Correct numeric/date/category semantics | ❌ Missing |
| | Structural comparison (supplementary) | ❌ Missing (`sqlglot` not installed — correctly optional) |
| Retrieval (3) | Context precision | ❌ Missing 🔒 no relevant-ID labels |
| | Context recall | ❌ Missing 🔒 |
| | Scope leakage rate | 🟡 isolation verified as behaviour; **rate never computed over a question set** |
| Answer (4) | Correctness / faithfulness / relevance / citations | ❌ Missing 🔒 all four. No RAG answer has been evaluated. Ragas absent (correctly optional per breakdown §2). |
| Mixed-ledger (1) | Questions spanning OCR / manual / Quick Chat / transfers / goals | ❌ Missing |
| Deliverables (6) | Question dataset, expected results, generated SQL, retrieved evidence, answers+citations, metric table | ❌ Missing — all six |

**W5: 2 ✅ / 4 🟡 / 15 ❌.** Note B5 remains open: in the dev `ledger.db`, `receipt_docs`
(5) < `receipts` (6), so one saved receipt is invisible to `semantic_search`. Any recall
measurement on real data starts with a known missing document.

### 3.7 W6 — Performance and consistency (15 units)

| Measurement | Status |
|---|---|
| End-to-end latency per task | ❌ Missing 🔒 endpoint unreachable |
| OCR latency per page | ❌ Missing 🔒 |
| SQL/RAG/ReAct latency per question | ❌ Missing 🔒 |
| Token usage | ❌ Missing — MLflow logs `prompt_eval_count`/`eval_count`, but only in 60 **ad-hoc dev runs**, not evaluation runs |
| Tool-call count | 🟡 Partial — round-trip count verified **structurally** against a stubbed model |
| Retry count | ❌ Missing |
| Error count | ❌ Missing |
| Batch throughput (pages/min) | ❌ Missing |
| Correction time (min/receipt) | ❌ Missing |
| Compute/hosting/electricity estimate | ❌ Missing |
| Repeated runs (mean/median/min/max/sd/success freq/route consistency) | ❌ Missing — no repetition has been run; number of repetitions correctly left unproposed |
| **Deliverable:** performance result table | 🟡 Partial — `PERFORMANCE.md` has microbenchmark tables, honestly scoped; not a latency table |
| **Deliverable:** configuration metadata attached to every run | ❌ Missing — template only, never filled |
| **Deliverable:** consistency summary | ❌ Missing |
| **Deliverable:** cost worksheet with units | ❌ Missing — and the breakdown's "no API fee ≠ zero cost" rule is honoured in prose only |

**W6: 0 ✅ / 2 🟡 / 13 ❌.**

### 3.8 W7 — EDA and failure analysis (11 units)

**Entirely missing. 0 of 11.** No EDA of any kind: no cases-per-module chart, no receipt
difficulty distribution, no route distribution, no category breakdown, no coverage plot.
No failure counts by category, no case studies with IDs.

The failure **taxonomy vocabulary** is defined in the breakdown and a grouping function
exists (`trajectory.failure_taxonomy`), and `REQUIREMENTS_AUDIT.md` §10b does map the six
found defects (D1–D4) onto three taxonomy categories — that is the only failure analysis
present, and it covers implementation defects, not evaluation failures.

### 3.9 W8 — Notebook and capstone evidence (22 units)

**Entirely missing. 0 of 22.** No `.ipynb` exists anywhere in the tree (`find` confirmed).
No `evaluation/notebooks/` or `evaluation/reports/` directory. None of the 13 recommended
sections and none of the 9 minimum visual-evidence items exist.

The **runtime is unblocked** — `jupyterlab>=4.3` and `ipykernel>=6.29` install from
`requirements-eval.txt`, and 15 jupyter executables are present in `.venv`. Blocker B4 is
correctly closed; the deliverable simply has not been written, and cannot be until results
exist.

---

## 4. Phase 2 — Prioritized gap summary

Priorities: **P0** necessary for a defensible submission · **P1** necessary supporting
evidence · **P2** useful additional coverage · **P3** stretch/regression.

| # | Item (as named in FOLLOWup) | Status | Priority | Blocker |
|---|---|---|---|---|
| 1 | Requirements and configuration audit | 🟡 Partial — docs re-pinned and corrected; `report.capture_configuration()` + `configuration_gaps()` now capture and validate a run. **No run frozen yet** | **P0** | endpoint (digests) |
| 2 | Versioned ground-truth dataset | 🟡 Partial — finance fixture ✅; 1 of 10 case families; no coverage matrix, no labeling guide | **P0** | B1 for receipts |
| 3 | Receipt header-field accuracy | ❌ Missing | **P0** | **B1** + live model |
| 4 | Receipt line-item accuracy | ❌ Missing | **P0** | **B1** + live model |
| 5 | Receipt-level exact match | ❌ Missing | **P0** | **B1** + live model |
| 6 | Hallucinated / unsupported-total detection | 🟡 **Unit behaviour now verified** (34 tests incl. both tolerance boundaries and the review wiring). The detection *rate* on real receipts is still unmeasured | **P1** | **B1** for the rate |
| 7 | Review-flag recall and false-review rate | ❌ Missing — 3 behavioural tests exist, no rate | **P0** | **B1** |
| 8 | SQL execution correctness | ❌ Missing | **P0** | live model + expected-result labels |
| 9 | Retrieval relevance ground truth | ❌ Missing | **P0** | manual labelling (cheap — ledger is small) |
| 10 | RAG correctness, faithfulness, citations | ❌ Missing | **P0** | live model + #9 |
| 11 | ReAct routing / observable trajectory evaluation | ⏸ Harness ready **and CLI wired**, never executed | **P0** | **live model only** — still the highest value per unit of work |
| 12 | Loop, retry, clarification behaviour | ✅ **Verified** — the real `agent_stream` guards are driven end to end (22 tests). Rates on a real model remain a live-run question | — |
| 13 | Receipt-to-finance posting | ✅ **Verified** | — | — |
| 14 | Quick Chat deterministic parsing | ✅ **Verified** (185 tests; confirmed model-free; **both parsers now proven to agree** on a shared corpus) | — | — |
| 15 | Core finance consistency | 🟡 **Budget aggregation now verified** (23 tests). Remaining: "statistics" consistency untested, and carry-forward **does not exist** (D5) | **P2** | none |
| 16 | End-to-end user-job evaluation | ❌ Missing entirely | **P0** | live model; partly runnable without one (`E2E-MAN`, `E2E-QCK`, `E2E-BAK`) |
| 17 | Correction-inclusive timing | ❌ Missing — no protocol, no sheet | **P1** | manual protocol + B1 |
| 18 | Live-model latency | ❌ Missing | **P1** | **endpoint unreachable** |
| 19 | Configuration and model capture | ✅ **Implemented** — resolved at runtime, attached to every result file, with gaps reported rather than silently absent. Must still accompany the first real run | — |
| 20 | Raw machine-readable result artifacts | 🟡 **Writer implemented** (`evaluation/report.py`, 32 tests) with `results/{raw,processed,failures}/`. No run has produced a file | **P0** | endpoint |
| 21 | Failure taxonomy and case studies | 🟡 Function exists, no data; D1–D4 mapped | **P1** | depends on results |
| 22 | Evaluation notebook / report | ❌ Missing; runtime unblocked | **P0** | depends on results |

**Reading of the table, after remediation:** of the 22 named items, **4 are verified
complete** (12, 13, 14, 19 — up from 2), **7 are partial**, and **11 are missing**. Every
self-fixable P0 identified in the original audit has been closed. **Of the P0 items that
remain, not one is blocked on unwritten code**: they are blocked on a reachable Ollama
endpoint (#11 trajectory run, #8 SQL accuracy, #10 RAG, #16 E2E, #20 producing a file) or
on human receipt labelling (#3, #4, #5, #7, #2), or they depend on those producing results
first (#22 notebook).

---

## 5. Phase 3 — Proof-point alignment

The consultation proof point is:

> How reliably can Snag extract, verify, and **reconcile** receipt-based financial
> information, and how does its performance compare with Claude Cowork on the same
> finance-verification task?

**The word "reconcile" carries two different meanings, and the repository implements only
the first.**

| | 1. Receipt-internal arithmetic reconciliation | 2. Receipt-to-bank/credit-statement reconciliation |
|---|---|---|
| What it does | Checks a receipt's line items sum to its own stated total | Matches receipts against an external statement of what was actually charged |
| In the repo? | **Yes** — `extraction.reconcile()` | **No — nothing whatsoever** |
| Evidence | Returns a warning when `abs(items_sum − total) > max(1.0, total × 0.02)`, allowing for a discount; feeds `flagged` / `needs_review` | Grep across all `.py`/`.ts`/`.tsx`/`.md` for bank-statement, card-statement, and discrepancy terms returns only this same function, unrelated *balance adjustment* UI copy, and the planning docs |
| Tested? | **No** — zero tests (§3.3 W2-A #10) | n/a |

**Claiming the second because the first exists would be false.** That was the state at
audit. `reconciliation.py` has since been built to close it; the table below now records
both.

| Capability the proof point implies | At audit | Now | Evidence |
|---|---|---|---|
| Bank-statement ingestion | ❌ | ✅ | `parse_statement_csv` / `import_statement` — signed-amount **and** debit/credit layouts, flexible header aliases, BOM-tolerant over HTTP |
| Credit-card-statement ingestion | ❌ | ✅ | Same path; `kind` distinguishes them. `charges_are_negative` flips issuers that export charges as positive |
| Statement transaction extraction | ❌ | ✅ | Rows normalized to `(posted_date, transaction_date, description, merchant, signed amount)`. Unreadable rows are **kept** with an error, never dropped |
| Receipt-to-statement matching | ❌ | ✅ | `match_statement` — two-pass, one-to-one assignment, ranked by amount → merchant → date |
| Missing-receipt detection (charge, no receipt) | ❌ | ✅ | `missing_receipt` bucket + `unexplained_total` |
| Unmatched-receipt detection (receipt, no charge) | ❌ | ✅ | `unmatched_receipts` bucket |
| Amount discrepancy detection | 🟡 within a receipt only | ✅ | Second matching pass pairs same-purchase rows whose amounts differ, so ₱500 vs ₱550 is **one** overcharge rather than two unrelated problems |
| Date vs posting-date differences | ❌ | ✅ | Settlement window (`max_posting_lag_days`, default 5, **proposed by the team**); outside it → `date_outside_window`, not a silent match |
| Merchant-name variations | ❌ | ✅ | `normalize_merchant` strips channel/network noise, branch and reference numbers, city and corporate suffixes; `merchant_similarity` uses containment, since a descriptor is normally a superset of the vendor name |
| Duplicate detection | ❌ | ✅ | `find_duplicate_charges` and `find_duplicate_receipts`. One-to-one matching is what keeps a double billing visible — one receipt cannot explain two charges |
| Refund / negative transactions | ❌ architecturally excluded | ✅ **on the statement side** | Credits are parsed, reported in `refunds`, and never matched to a receipt. **`finance.create_transaction` still rejects non-positive amounts**, so refunds remain unrepresentable in the *ledger* — unchanged and still a gap |
| Unsupported / hallucinated-total handling | 🟡 | ✅ | `extraction.reconcile` now has 34 tests; kept deliberately separate from this module |
| Human-review flags | ✅ | ✅ | `needs_review` on the report; nothing is auto-corrected |
| Discrepancy-report generation | ❌ | ✅ | `discrepancy_report` + `format_discrepancy_report`; `POST /statements/{id}/report` and `GET .../report.txt` |

**Coverage: 13 of 13 present, 1 partially** (refunds, ledger side). 104 tests
(`test_w2f_reconciliation.py` 80, `test_w2f_reconciliation_api.py` 24).

### 5.1 What this does and does not establish

It is a **capability**, not a measurement. Specifically:

- **No accuracy has been measured.** Matching precision/recall against a labelled
  statement is unknown, because no real bank export and no labelled receipt set exists
  (**B1**). Every test above asserts *designed behaviour on constructed data*.
- **Every threshold is reasoned, not measured** — settlement window, discrepancy band,
  merchant-similarity floor. All are documented parameters overridable per call and per
  HTTP request, labelled *proposed by the team*, because there is no data to tune against.
- **CSV only.** PDF statements would need the vision model. `parse_statement_csv` is the
  seam a PDF path would feed.
- **No UI.** Backend and API only; `web-next` is untouched.
- **Deterministic by design** — no model, so it is reproducible, auditable, and evaluable
  without an endpoint. A user disputing a match can be shown exactly why two rows paired.

**Conclusion for Phase 3:** the repository now supports **both** kinds of reconciliation,
and keeps them distinct — `test_statement_reconciliation_does_not_touch_receipt_internal_arithmetic`
asserts that an internally inconsistent receipt can still match its charge exactly, with
both facts remaining visible. The proof point is now *answerable in principle*. It is not
yet *answered*: answering it requires a labelled receipt set and a real statement to
measure matching accuracy against.

---

## 6. Phase 4 — Cowork benchmark readiness

**Nothing exists.** Grep for `cowork` across the repository returns zero hits outside
`docs/FOLLOWup.md` itself.

| Required artifact | Present? | Note |
|---|---|---|
| A fixed Claude Cowork benchmark prompt | ❌ No | Not drafted anywhere |
| A common input dataset | ❌ No | Blocked on B1 — there is one unlabelled receipt |
| The same task definition for Snag and Cowork | ❌ No | Not written |
| A common output schema | ❌ No | Snag's `ReceiptData` could serve as the basis; not adapted |
| Shared ground truth | ❌ No | Blocked on B1 |
| Fixed retry and clarification rules | ❌ No | Snag's own rules are code-derived (`_MAX_AGENT_STEPS = 3`, force-final at `repeats >= 2`); no equivalent protocol is defined for a Cowork run |
| Raw-output storage | ❌ No | No `results/` directory exists for either system |
| Correction-inclusive timing protocol | ❌ No | Not defined for either system (see W4) |
| Accuracy and discrepancy metrics | ❌ No | Uncomputed for Snag, so no comparison basis |
| Severe-error definitions | ❌ No | Not defined. Precedent exists to draw on: D4's 1,000,000× amount error is a natural "severe" archetype |
| Cost comparison | ❌ No | No cost worksheet for Snag; no Cowork pricing recorded |
| Build-versus-buy retrospective | ❌ No | Not written |

**Readiness: 0 of 12.** Two structural observations, kept within the follow-up's
constraints:

- A Cowork comparison is **gated on the same B1 blocker** as everything else. Without a
  shared labelled dataset there is no comparison, only two sets of unverified outputs.
- The follow-up's own rule applies: Cowork must be evaluated **externally, at the
  task/output level**. Snag's trajectory evidence (`action`/`observation`/`final` events)
  has **no Cowork counterpart** and must not be presented as one. The comparison can cover
  final output accuracy, discrepancy detection, correction-inclusive time, and cost —
  not internal path. Correspondingly, **no Cowork integration should be built into Snag**;
  this is an evaluation-artifact task.

---

## 7. Environment and access still required

| Requirement | State at audit | Blocks |
|---|---|---|
| Reachable Ollama endpoint | **Neither reachable.** `curl` to `localhost:11434` and `103.231.240.155:11434` both returned nothing | W3 live run, W4, W5, W6 latency — 11 of 22 Phase-2 items |
| Labelled receipt images (**B1**) | 1 unlabelled image (`Receipt.jpg`) | W1 receipts, W2-A accuracy, W4, W5 relevance, W7 — the largest blocker, **not resolvable in code** |
| Relevant-receipt-ID labels | None | W5 retrieval metrics — cheap to produce (small ledger), needs a human pass |
| Model digests | Unpinned; tags (`:latest`) are mutable | Reproducibility of any frozen run |
| `receipt_docs` gap (**B5**) | 5 docs vs 6 receipts in dev `ledger.db` | Recall measurement on real data |
| Transcript of the evaluation session | Not in the repository | W0 items 1–2 |

---

## 8. Corrections applied to existing evaluation documents

Documentation only; no application code touched, no test changed, no production behaviour
modified. Full test suite re-run green afterwards (§0).

| File | Change |
|---|---|
| `CONFIGURATION.md` | Re-pinned to commit `41b8fa1`; removed the false "`MLFLOW_TRACKING_URI` is not set in code" row and the stale `MLFLOW_ENABLED=0` clarify-path caveat (both fixed in `core.py`); added a staleness note directing readers to symbol names rather than line numbers |
| `REQUIREMENTS_AUDIT.md` | Added a header note recording that it was audited at `9ac15ec`, that HEAD is `41b8fa1`, that its line citations have drifted, and that §4.4 and the §4.3 caveat are now resolved |
| `README.md` | Corrected the three stale test counts (39→52, 62→65, 64→78+31); added the five missing files to the layout block; downgraded W2-B from "Done" to partial with the budget gap named; added `IMPLEMENTATION_STATUS.md` to the entry points |

---

## 9. Defects surfaced by the remediation pass

Both are **pre-existing product defects**, not regressions, found by writing tests for code
that previously had none. They join D1–D4 in `REQUIREMENTS_AUDIT.md` §10b.

### D5 — Budget carry-forward is accepted, stored, and never used

**Severity: medium (a user-facing control that silently does nothing).**
`carry_forward` is a parameter of `finance.create_budget_plan`, a column in `budget_plans`,
a field in the `POST /budgets` request model (`api.py`), a toggle in the budgets UI
(`web-next/app/plan/budgets/page.tsx`) and a typed field in `types.ts`. **No computation in
`finance.py` ever reads it.** `list_budget_plans` resolves a plan's limit from
`limit_amount` or from percent-of-income and never consults the flag, so underspend in one
period does not raise the next period's limit. Two otherwise identical plans — one with
carry-forward on — resolve to exactly the same limit.

**Not fixed.** Implementing carry-forward means choosing semantics (does unspent budget roll
over indefinitely? does overspend roll forward as a debt? which period boundary?), and that
is a product decision, not a defect repair. Characterized by test instead, so the gap is
measured rather than assumed working:
`test_carry_forward_does_not_change_the_resolved_limit` will fail the moment real
carry-forward is implemented — which is the intended signal.

### D6 — `_num` fabricated numbers from containers ✅ FIXED

**Severity: medium (silent wrong data on malformed model output).**
`extraction._num` fell through to a string path for any non-scalar value: `str([1, 2])` →
strip everything but digits → `"12"` → **12.0**. `{"amount": 1}` became `1.0`. The figure
appears nowhere on the receipt.

Reachable: `_num` runs on the **unvalidated** model dict — `core.py`'s post-processing chain
(`_fix_payment_fields(_dedupe_items(_remap_summary_lines(_clean_items(raw))))`) executes
before pydantic validation, and `_fix_payment_fields` writes derived values back into the
dict. A model emitting a nested object where an amount belongs would therefore produce a
number that passed schema validation looking entirely legitimate, and would then feed
reconciliation and the ledger.

**Fix:** two lines in `extraction._num` returning `None` for `list`/`tuple`/`set`/`dict`,
with a comment recording why. A wrong shape is not a misformatted number. Same family as
D4 — an input the unit tests never happened to try.

Tests: `test_a_list_does_not_become_a_fabricated_number`,
`test_a_dict_does_not_become_a_fabricated_number`,
`test_a_nested_amount_object_is_rejected_rather_than_flattened`. The 10 pre-existing
`test_extraction.py` tests still pass unchanged.

### Also recorded as an architectural limitation (not a defect)

**Posting loses currency.** The `transactions` table has no currency column, so
`post_receipt_as_expense` carries a receipt's total across as a bare number: a USD receipt
becomes a transaction indistinguishable from a PHP one. The ledger is single-currency by
construction. Characterized by `test_a_posted_transaction_carries_no_currency_of_its_own`
so the W2-E checklist item is answered honestly rather than dropped.
