# Snag Evaluation — Implementation Status Audit

**Audited commit:** `41b8fa1b7b15a8c2aaaffd5e78fc9b9e6a9c5160` (`main`, 2026-07-26 16:07 +0800)
**Working tree at audit:** clean except untracked `docs/FOLLOWup.md`
**Audit date:** 2026-07-26
**Method:** direct execution and inspection at the commit above. Every "Implemented and
verified" row names a file, a symbol, a command that was run, and the result observed.
**Scope:** required by `docs/FOLLOWup.md` Phases 1–4. Phase 5 lives in
[`IMPLEMENTATION_BACKLOG.md`](IMPLEMENTATION_BACKLOG.md).

> **No production behaviour was modified by this audit.** The only writes were this file,
> the backlog file, and corrections to three stale statements in existing evaluation docs
> (listed in §1.4). Application code is untouched.

> **Nothing in this repository is a measured evaluation result.** No accuracy figure, pass
> rate, receipt-level exact match, retrieval recall, or real request latency exists. What
> exists is instrumentation plus two offline microbenchmarks.

---

## 0. Executive summary

| | Count | Share |
|---|---|---|
| Audit units (W0–W8 checklist items, metrics, and named deliverables) | **195** | 100% |
| Implemented and verified | **46** | **23.6%** |
| Partially implemented | **29** | 14.9% |
| Missing / documented-but-not-implemented / blocked | **120** | 61.5% |

Tests executed during this audit — **all pass, nothing broken**:

| Suite | Command | Result |
|---|---|---|
| Evaluation (Python) | `./.venv/bin/python -m pytest evaluation/tests -q` | **244 passed** in 2.38 s |
| Pre-existing extraction | `./.venv/bin/python -m pytest test_extraction.py -q` | **10 passed** |
| Quick Chat (TypeScript) | `cd web-next && npx vitest run` | **78 passed** (1 file) |
| Retrieval microbenchmark | `./.venv/bin/python evaluation/bench_retrieval.py` | ran, reproduced |
| Fixture seeder | `./.venv/bin/python evaluation/fixtures/seed_finance.py` | ran, self-verified |
| **Total** | | **332 tests, 0 failures, 0 skips, 0 xfails** |

The headline: **the harness is real and the component layer is genuinely strong; the
evaluation itself has not been run.** Every metric in the breakdown's own metric tables is
uncomputed. The system has never been executed against a model as part of an evaluation.

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

#### W2-A Receipt extraction and safeguards (14) — 4 ✅ / 4 🟡 / 6 ❌

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | Input validation: types, size, empty | ✅ Verified | `test_w2d_sql_react.py`: `test_empty_upload_is_rejected`, `test_oversized_upload_is_rejected`, `test_unsupported_content_type_is_rejected`, `test_supported_content_types_are_accepted` (parametrized png/jpeg/pdf). Executed, pass. *(Misfiled — these are W2-A items living in the W2-D file.)* |
| 2 | Image preprocessing **and PDF page expansion** | 🟡 Partial | Preprocessing: 15 tests in `test_w2a_preprocess.py`, all pass. **PDF page expansion has zero tests** — `pypdfium2` rendering, `OCR_PDF_RENDER_SCALE`, and `OCR_PDF_MAX_PAGES` are entirely unexercised. No PDF fixture exists. |
| 3 | JSON coercion and schema validation | 🟡 Partial | Schema: `test_schema_validation_rejects_junk_output` (1 test) covers `core.validate_output`. **`extraction._coerce_json` has no test** — the function that salvages model output wrapped in prose/fences. |
| 4 | Header-field extraction | ❌ Missing 🔒 | Requires a live model **and** labelled receipts. No test, no metric. |
| 5 | Line-item extraction | ❌ Missing 🔒 | Same. |
| 6 | Numeric-field coercion | ❌ Missing | `extraction._num` has no direct test. |
| 7 | Summary-line remapping | ✅ Verified | `test_extraction.py` → `_remap_summary_lines`. 10 root tests pass. |
| 8 | Duplicate-item handling | ✅ Verified | `test_extraction.py` → `_dedupe_items`. |
| 9 | Payment-field repair | ✅ Verified | `test_extraction.py` → `_fix_payment_fields`. |
| 10 | Reconciliation tolerance behaviour | ❌ Missing | **`extraction.reconcile` has zero tests.** Grepped: no test file references `reconcile` or `tolerance`. Its `tol = max(1.0, total * 0.02)` boundary — the thing that decides whether a receipt is flagged — is unverified. This is a notable gap given reconciliation is the project's central claim. |
| 11 | Review / disambiguation reasons | 🟡 Partial | 3 tests on `core.needs_disambiguation` (missing total, missing line items, clean receipt not flagged). The reason vocabulary is otherwise unexercised, and reasons derived from `reconcile` are untested (see #10). |
| 12 | Field-confidence availability and value-equality gating | ❌ Missing | The logprob machinery (`core._logprob_token_spans` and the value-equality gate) has **zero tests**. Grepped: no test references `confidence` or `logprob`. |
| 13 | Receipt save and line-item linkage | 🟡 Partial | `core.save_receipt` is exercised by `seed_finance.py` (with `index=False`) and its output consumed by posting/linkage tests. **No test directly asserts that line items are written and linked** to the parent receipt. |
| 14 | Per-page failure isolation in batch | ❌ Missing | No batch test exists. Grepped: `batch` appears in no test file. |

#### W2-B Personal-finance deterministic logic (13) — 11 ✅ / 1 🟡 / 1 ❌

All verified rows are from `test_w2b_finance.py` (52 tests, executed, all pass) against the
deterministic fixture with hand-computed expectations.

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | Account balance calculations | ✅ | `test_account_balances_match_ground_truth`, `test_transfer_debits_fee_from_source_only`, `test_liability_account_balance_is_negative` |
| 2 | Net-worth calculation | ✅ | 4 tests incl. excluded/archived/hidden-liability variants |
| 3 | Expense and income creation | ✅ | `finance.create_transaction` via validation suite + fixture |
| 4 | Transfer validation and effects | ✅ | `test_transfer_to_same_account_is_rejected`, `..._to_non_debit_account_is_rejected`, fee debit test |
| 5 | **Budget aggregation and carry-forward** | ❌ **Missing** | **Zero tests.** `finance.list_budget_plans` / `create_budget_plan` / `delete_budget_plan` are never called by any test; `budget_plans` appears once, only as a row count inside a backup assertion. No aggregation and no carry-forward logic is verified. `evaluation/README.md` marks W2-B "Done" — that claim is wrong. |
| 6 | Templates | ✅ | `test_using_a_template_creates_a_matching_transaction` |
| 7 | Recurring schedule advancement | ✅ | 2 tests (date rolls forward one month; transaction created) |
| 8 | Installment payments | ✅ | `test_installment_payment_increases_paid_amount` |
| 9 | Goal activity | ✅ | `test_goal_deposit_updates_goal_and_debits_account` |
| 10 | Debt activity | ✅ | `test_debt_payment_updates_paid_amount` |
| 11 | Receivable activity | ✅ | `test_receivable_collection_updates_collected_amount` |
| 12 | Upcoming-obligation aggregation | ✅ | `test_upcoming_returns_the_seeded_obligations` |
| 13 | Transaction history / statistics consistency | 🟡 Partial | History verified (count, kind partition, account filter, delete-restores-balance). **"Statistics" is not covered** — no aggregate/statistics function is called by any test. |

#### W2-C Rule-based Quick Chat (8) — 7 ✅ / 1 🟡

`parseQuick.test.ts` (78 tests, executed via `npx vitest run`, all pass) plus
`test_w2c_quick_python.py` (31 tests, pass).

| # | Item | Status | Evidence |
|---|---|---|---|
| 1–4 | Amount parsing, `k` shorthand, kind classification, relative dates | ✅ | `describe` blocks of the same names; Python mirrors for D2/D4 regressions |
| 5 | Account matching | ✅ | `describe("account matching")` |
| 6 | Category matching | ✅ | `describe("category matching")` |
| 7 | Missing / ambiguous field handling | ✅ | `describe("invalid input")`, `describe("note extraction")` |
| 8 | Server/client parser consistency | 🟡 Partial | **Both parsers are tested; neither is tested *against the other*.** There is no shared corpus and no differential test. `test_w2c_quick_python.py` states outright that it mirrors selected regressions only. Divergence outside the D2/D4 cases would not be caught. |

`test_quick_chat_uses_no_model` ✅ verifies the breakdown's §1.5 constraint that Quick Chat
is deterministic — good, and correctly framed.

#### W2-D SQL, RAG, ReAct tools (10) — 3 ✅ / 4 🟡 / 3 ❌

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
| 9 | Ambiguous recent-receipt questions trigger clarification | 🟡 Partial | The **detector** is verified (`test_recent_receipt_questions_are_detected_as_ambiguous`, `test_unambiguous_questions_do_not_trigger_clarification`). The end-to-end clarify emission through `agent_stream` is unexercised. |
| 10 | Repeated tool calls and step limits handled | 🟡 Partial | `test_agent_step_budget_is_a_small_positive_integer` pins `_MAX_AGENT_STEPS = 3`; the harness detects loops in synthetic traces. The **real** guard (`repeats >= 2` → `_force_final`, `core.py:3107`) is never driven. |

#### W2-E Receipt posting and backup/restore (8) — 7 ✅ / 1 🟡

| # | Item | Status | Evidence |
|---|---|---|---|
| 1 | Posting creates the expected finance transaction | ✅ | `test_posting_a_receipt_creates_one_linked_expense` |
| 2 | Transaction links back to the correct `receipt_id` | ✅ | same + `test_restore_preserves_receipt_transaction_linkage` |
| 3 | Amount, date, category, account, currency preserved | 🟡 Partial | Amount and account verified (`test_posting_reduces_the_account_balance_once`); **currency and category preservation are not separately asserted**. |
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
| Machine-readable result file | ❌ Missing — **no `evaluation/results/` directory exists**; no run writes JSON/CSV |
| Summary table by module and case category | 🟡 Partial — `evaluation/README.md` has one, with stale counts (§1.3) |
| Failure log with case IDs | ❌ Missing |

**W2 totals: 32 ✅ / 12 🟡 / 23 ❌ across 67 units.**

### 3.4 W3 — Layer 2 trajectory evaluation (22 checks + 5 deliverables)

The harness (`evaluation/trajectory.py`, 457 lines) is the strongest single artifact in the
directory: 37 self-tests, all pass. It projects events into a `Trajectory`, evaluates a
case against 8 independent checks without short-circuiting, aggregates metrics that return
`None` (not 0 or 1) when no case applies, and builds a failure taxonomy. It also holds a
**contract test against the real generator** (`test_agent_stream_event_contract`,
`test_known_tools_match_the_real_dispatcher`) — so it cannot silently drift from `core`.

**But `collect_trajectory()` and `run_cases()` have never been executed.** They require a
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
| Trace collector / exporter | ✅ Implemented, 37 self-tests pass — but the **exporter half is missing**: nothing writes a trajectory to disk |
| Expected-trajectory case definitions | 🟡 Partial — 7 cases, 1 of 5 pipelines |
| Actual-vs-expected trace comparison | ⏸ Unexecuted — `evaluate_case` is fully tested against **synthetic** events; never run on a real one |
| One successful and one failed trajectory visualization | ❌ Missing |
| Failure taxonomy | 🟡 Partial — `failure_taxonomy()` implemented and tested; no data to populate it |

**W3 totals: 8 ✅ / 11 🟡 / 8 ❌ across 27 units.** The DoD criterion "evaluation uses real
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
| 1 | Requirements and configuration audit | 🟡 Partial — exists, stale by 2 commits, no run frozen | **P0** | none (self-fixable) |
| 2 | Versioned ground-truth dataset | 🟡 Partial — finance fixture ✅; 1 of 10 case families; no coverage matrix, no labeling guide | **P0** | B1 for receipts |
| 3 | Receipt header-field accuracy | ❌ Missing | **P0** | **B1** + live model |
| 4 | Receipt line-item accuracy | ❌ Missing | **P0** | **B1** + live model |
| 5 | Receipt-level exact match | ❌ Missing | **P0** | **B1** + live model |
| 6 | Hallucinated / unsupported-total detection | ❌ Missing — `extraction.reconcile` itself has **zero tests** | **P0** | none for the unit test; B1 for the rate |
| 7 | Review-flag recall and false-review rate | ❌ Missing — 3 behavioural tests exist, no rate | **P0** | **B1** |
| 8 | SQL execution correctness | ❌ Missing | **P0** | live model + expected-result labels |
| 9 | Retrieval relevance ground truth | ❌ Missing | **P0** | manual labelling (cheap — ledger is small) |
| 10 | RAG correctness, faithfulness, citations | ❌ Missing | **P0** | live model + #9 |
| 11 | ReAct routing / observable trajectory evaluation | ⏸ Harness ready, never executed | **P0** | **live model only** — highest value per unit of work |
| 12 | Loop, retry, clarification behaviour | 🟡 Detectors tested; real paths never driven | **P1** | live model (or a stubbed agent run) |
| 13 | Receipt-to-finance posting | ✅ **Verified** | — | — |
| 14 | Quick Chat deterministic parsing | ✅ **Verified** (109 tests; confirmed model-free) | — | — |
| 15 | Core finance consistency | 🟡 11/13 verified; **budget aggregation untested**; statistics untested | **P1** | none |
| 16 | End-to-end user-job evaluation | ❌ Missing entirely | **P0** | live model; partly runnable without one (`E2E-MAN`, `E2E-QCK`, `E2E-BAK`) |
| 17 | Correction-inclusive timing | ❌ Missing — no protocol, no sheet | **P1** | manual protocol + B1 |
| 18 | Live-model latency | ❌ Missing | **P1** | **endpoint unreachable** |
| 19 | Configuration and model capture | 🟡 Template exists, never filled | **P0** | none — must accompany the first real run |
| 20 | Raw machine-readable result artifacts | ❌ Missing — no `results/` dir, nothing writes one | **P0** | none (self-fixable) |
| 21 | Failure taxonomy and case studies | 🟡 Function exists, no data; D1–D4 mapped | **P1** | depends on results |
| 22 | Evaluation notebook / report | ❌ Missing; runtime unblocked | **P0** | depends on results |

**Reading of the table:** of the 22 named items, **2 are verified complete** (13, 14),
**6 are partial**, and **14 are missing**. Eleven are P0. Of those eleven, **four are
self-fixable today with no model and no labelling** (#1 refresh, #19 capture, #20 results
writer, and the reconcile unit tests inside #6) — everything else waits on either a
reachable endpoint or human labelling.

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

**Claiming the second because the first exists would be false.** Item-by-item:

| Capability the proof point implies | Present? | Evidence |
|---|---|---|
| Bank-statement ingestion | ❌ No | No statement parser, no upload path, no route. `api.py` has no statement endpoint. |
| Credit-card-statement ingestion | ❌ No | Same. |
| Statement transaction extraction | ❌ No | The OCR prompt (`extraction.py`) targets a receipt schema — vendor, TIN, items, VAT, total. No statement schema exists. |
| Receipt-to-statement matching | ❌ No | No matching function, no candidate scoring, no match table. |
| Missing-receipt detection (charge with no receipt) | ❌ No | Requires a statement side. |
| Unmatched-receipt detection (receipt with no charge) | ❌ No | Same. |
| Amount discrepancy detection | 🟡 **Within a receipt only** | `reconcile()` compares items↔total. It cannot compare a receipt to a charge. |
| Date vs posting-date differences | ❌ No | Only `receipt_date` is stored. There is no posting-date concept; `transactions.occurred_at` is the user's date, not a bank posting date. |
| Merchant-name variation handling | ❌ No | `vendor_name` is stored verbatim. No normalization, no fuzzy matching, no alias table. |
| Duplicate detection | ❌ No | Two `_dedupe_items` behaviours exist for *line items within one receipt*. There is **no duplicate-receipt detection**; the breakdown's own W1 list includes "duplicate receipt attempt" as an untested case. |
| Refund / negative transactions | ❌ No | `finance.create_transaction` rejects non-positive amounts (`test_non_positive_amounts_are_rejected` ✅). Refunds are **architecturally excluded** today. |
| Unsupported / hallucinated-total handling | 🟡 Partial | `needs_disambiguation` flags a missing total ✅; `reconcile` flags an unsupported total but is **untested**. Rate never measured. |
| Human-review flags | ✅ Yes | `receipts.flagged` column; `needs_review` + `review_reasons` in the extract response; 3 tests incl. a false-review guard. **Recall and false-review rate are unmeasured.** |
| Discrepancy-report generation | ❌ No | No report generator, no export, no UI surface. |

**Conclusion for Phase 3:** the repository supports **receipt-internal arithmetic
reconciliation with human-review flagging**, and nothing else on this list. The
consultation proof point as written is **not currently answerable** — not because the
evaluation is incomplete, but because roughly half the capability it describes
(the statement side) does not exist in the product. This is the single most consequential
finding in this audit, and it is a **scope decision for the team, not an evaluation gap**:
either narrow the proof point to receipt-internal verification, or build statement
ingestion and matching as a feature before evaluating it.

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
