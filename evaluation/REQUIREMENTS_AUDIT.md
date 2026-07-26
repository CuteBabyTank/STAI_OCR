# W0 — Repository Audit

**Audited commit:** `9ac15ec9634ad3b42cb26e3da625a9722233dbaa` (`main`, clean tree)
**Audit date:** 2026-07-26
**Scope:** Verification pass required by `docs/Snag_Agentic_Evaluation_Task_Breakdown.md` §1 before any evaluation code is written.
**Method:** Direct inspection of the repository at the commit above. Every claim below is
traceable to a file and line. Nothing here is a measured evaluation result.

> **Status of numbers in this file.** Row counts, run counts, and test counts are
> *inventory facts about the current working tree*, not evaluation outcomes. No pass
> rate, accuracy figure, threshold, or sample size is proposed or implied here.

---

## 1. Verdict on the breakdown document's own assumptions

The breakdown's §1 instructions asked the implementer to confirm or refute a set of
assumptions before building anything. Result:

| # | Assumption to check | Verdict | Evidence |
|---|---|---|---|
| 3 | "Do not assume Snag uses LangGraph or multiple independent agents." | **Confirmed — no LangGraph.** Single hand-written ReAct loop. | `langgraph` absent from `requirements.txt` and from the venv; loop is `core.agent_stream` (`core.py:2856`), a plain `for _ in range(_MAX_AGENT_STEPS)` |
| 4 | "Do not add an authentication requirement to evaluation paths." | **Confirmed — no auth layer exists.** | No auth dependency, middleware, token, or user table anywhere in `api.py` / `core.py` / `finance.py` |
| 5 | "Do not describe Quick Chat as an LLM feature." | **Confirmed — deterministic regex parsing.** | `finance.parse_quick_text` (`finance.py:1456`) and `web-next/app/lib/parseQuick.ts`; no model call in either |
| 6 | "Do not claim the Docker config is fully offline." | **Confirmed — remote by default.** | `docker-compose.yml:36` — `OLLAMA_HOST=${OLLAMA_HOST:-http://103.231.240.155:11434}` |
| 7 | "README, code, and Docker Compose contain different model defaults." | **Confirmed, and worse than stated — a three-way split plus an internally inconsistent README.** | See §4 |
| 10 | "Keep receipt-level exact match separate from field-level accuracy." | **No existing code conflates them** — because no accuracy measurement code exists at all. | §3 |

**One correction to the breakdown document.** §3 lists "Streaming ReAct routing between
SQL and receipt search" under the agent layer and §8 Phase 4 asks to "export observable
MLflow/ReAct/API/database events." MLflow does **not** record per-step events — it records
only run-level aggregates (`num_steps`, `tools_used` as a comma-joined string). Step-level
trajectory data exists **only** in the live `agent_stream` event generator and in the
`steps` list returned by `agent_run`; it is never persisted. W3 must collect trajectories
from the generator, not from `mlflow.db`. See §6.

---

## 2. Repository inventory

Six Python modules, one Next.js frontend, no `tests/` directory.

| Path | Lines | Role | Evaluation relevance |
|---|---|---|---|
| `core.py` | 3019 | Vision/OCR, receipt DB, SQL agent, RAG, ReAct loop, MLflow | W2-A, W2-D, W3, W5 |
| `finance.py` | 1503 | Accounts, transactions, budgets, goals/debts/receivables, backup/restore, `parse_quick_text` | W2-B, W2-C, W2-E |
| `api.py` | 876 | FastAPI surface (~80 routes) | W3, W4 |
| `extraction.py` | 371 | Prompt, JSON coercion, dedupe, summary-line remap, payment repair, `reconcile` | W2-A |
| `demo_memory_rag_tools.py` | 313 | Manual demo script, not a test | none (see §3) |
| `test_extraction.py` | 116 | The entire test suite | W2-A (partial) |
| `web-next/app/lib/parseQuick.ts` | 127 | **The Quick Chat parser the UI actually uses** | W2-C |

### Frozen-configuration artifacts

See `evaluation/CONFIGURATION.md` for the full tested-configuration card required by W0.

---

## 3. Test framework and existing coverage

**Framework:** pytest (installed in `.venv`; not pinned in `requirements.txt`).
**Layout:** one file at repo root. No `tests/` directory, no `conftest.py`, no `pytest.ini`
/ `pyproject.toml` / `setup.cfg` config, no markers, no fixtures.

**Command and verified baseline:**

```
./.venv/bin/python -m pytest -q
```

```
..........                                                               [100%]
10 passed in 0.01s
```

**What the 10 tests cover.** All 10 are pure-function tests of `extraction.py`
post-processing only — `_dedupe_items`, `_fix_payment_fields`, `_remap_summary_lines`.
They construct dicts in memory. **No test touches a model, the database, the API, the
agent, RAG, SQL, or any of `finance.py`.**

**Coverage against the breakdown's W2 checklists** — of ~48 W2 checklist items:

| Sub-workstream | Items | Currently covered |
|---|---|---|
| W2-A receipt extraction & safeguards | 14 | **3** (summary-line remap, duplicate handling, payment repair) |
| W2-B finance deterministic logic | 13 | **0** |
| W2-C Quick Chat | 8 | **0** |
| W2-D SQL / RAG / ReAct | 10 | **0** |
| W2-E posting & backup/restore | 8 | **0** |

`demo_memory_rag_tools.py` is a print-driven manual demo requiring a live Ollama
(`_ollama_ready()`, `demo_memory_rag_tools.py:51`). It asserts nothing and cannot serve as
evaluation evidence.

**Frontend:** no test runner at all — `web-next/package.json` declares no `test` script and
no jest/vitest dependency. Any W2-C evaluation of `parseQuick.ts` requires standing up JS
test infrastructure from zero.

---

## 4. Model-default mismatch (breakdown §1 item 7 — confirmed and expanded)

The breakdown said defaults "differ." They differ **three ways**, and the README
contradicts itself:

| Role | `core.py` / `extraction.py` default | `docker-compose.yml` | README |
|---|---|---|---|
| Vision / OCR | `qwen2.5vl:7b` (`extraction.py:26`) | `gemma4:e4b` (`:37`) | `qwen2.5vl:7b` (§models, install) |
| Agent (SQL/RAG/ReAct) | `qwen2.5:latest` (`core.py:438`) | `gemma4:12b` (`:38`) | **`llama3.2:3b`** (§models, install) — but the notebook section (`README.md:419`) says `ollama pull qwen2.5:latest` |
| Embeddings | `nomic-embed-text` (`core.py:440`) | `nomic-embed-text` | `nomic-embed-text` |

Only the embedding model agrees across all three. **Every evaluation run must record the
resolved model names at runtime**, not cite a default from any one of these sources —
`GET /health` returns the effective `vision_model` (`api.py:153`) and is the right source.

### Additional config defects found during the audit

Items 1–3 were **fixed before the baseline freeze** (team decision), because each one
corrupted the record of what was being tested. Item 4 remains open. The full test suite
was re-run green after each change, and `preprocess_image` was verified to produce an
identical 1600 px result before and after.

1. **`VISION_MAX_DIM` was dead.** ✅ **FIXED.** `core.py` read it into `_VISION_MAX_DIM`
   and defined `_downscale_image` — neither was ever called. The live downscale knob is
   `OCR_MAX_IMAGE_DIM` (default `1600`), applied in `preprocess_image`.
   `docker-compose.yml` set `VISION_MAX_DIM=0` ("no downscaling") which **had no effect** —
   the container still downscaled to 1600 px. Anyone reading the compose file would have
   mis-recorded the tested configuration. The dead names and helper were removed (with an
   explanatory comment left in place), and the compose entries replaced with `OCR_NUM_CTX`.
   Verified: `preprocess_image` still resizes 1080×1920 → 900×1600, unchanged.
2. **README documented a stale `OCR_NUM_PREDICT`.** ✅ **FIXED** — corrected `1024` → `4096`.
3. **`MLFLOW_ENABLED=0` did not fully disable tracing.** ✅ **FIXED.** The clarify
   early-return branch in `agent_stream` called `mlflow.log_metric` directly four times
   instead of the guarded `_mlog_metric` helper. MLflow auto-starts a run on an unguarded
   `log_metric`, and the `finally` block keys off `_traced`, so the stray run also leaked
   open. That would have contaminated exactly the W3 clarification-case metrics. All four
   now use `_mlog_metric`; the only remaining direct calls are inside the guarded helpers.
4. **`MLFLOW_TRACKING_URI` is never set in code.** Only `docker-compose.yml:44` sets it.
   Running `uvicorn` locally per README (`:245`) sends traces to the default `./mlruns`
   file store, **not** to the `mlflow.db` in the repo. The 60 existing runs were therefore
   produced under an env var set outside version control — the run environment is not
   reproducible from the repo alone.

---

## 5. Ground truth and fixtures — the critical gap

| Asset the breakdown assumes | Present? |
|---|---|
| Receipt image fixtures | **One image total.** `Receipt.jpg` at repo root is the only image/PDF in the tree. |
| Verified receipt labels | **None.** No labels file in any format. |
| Finance DB fixture | **None.** |
| Backup fixtures | **None.** |
| `evaluation/datasets/cases.json` | **None** (this audit creates the first `evaluation/` content). |
| PDF / multipage fixtures | **None.** |

**`ledger.db` contents** (the only receipt data that exists):

| Table | Rows |
|---|---|
| `receipts` | 6 |
| `line_items` | 14 |
| `receipt_docs` | 5 |
| `budgets` | 2 |
| `income` | 0 |

Two consequences:

1. **`receipt_docs` (5) < `receipts` (6)** — one saved receipt has no embedding and is
   therefore invisible to `semantic_search`. Any retrieval-recall measurement over the
   current DB starts with a known missing document. This must be resolved or explicitly
   recorded before W5.
2. **The finance tables do not exist in `ledger.db` at all.** `finance.py` shares
   `core._connect` / `DB_PATH` (`finance.py:29`) and creates its schema lazily via
   `init_finance_schema()` (`finance.py:69`); it has never run against this database.
   There is **no finance data, and not even a finance schema**, to evaluate. W2-B, W2-E,
   W4 (`E2E-PST`, `E2E-MAN`, `E2E-BUD`, `E2E-BAK`) and the entire unassigned finance lane
   currently have a zero starting point.

**`ledger.db` and `mlflow.db` are both gitignored** (`.gitignore:12`, `:16`). They are
untracked local state. The breakdown's requirement of a "frozen SQLite finance fixture"
(§9) and "versioned" ground truth (§11) cannot be met while the only data lives in
ignored files. A fixture directory that is *not* ignored is a prerequisite for W1.

---

## 6. Observability actually available for W3

**Good news: the ReAct event vocabulary already matches the breakdown's W3 spec exactly.**
`core.agent_stream` (`core.py:2856`) yields typed events:

| Event | Emitted at | Payload |
|---|---|---|
| `start` | `core.py:2877` | — |
| `token` | `core.py:2933` | `text` |
| `action` | `core.py:2973` | `tool`, `input` |
| `observation` | `core.py:2966`, `:2977` | `tool`, `text`, `data` |
| `clarify` | `core.py:2903`, `:2992` | `question`, `steps` |
| `final` | `core.py:2994` | `answer`, `steps` |
| `error` | `core.py:2999` | `message` |

The breakdown's suggested trajectory-case format
(`required_events: ["start","action","observation","final"]`,
`prohibited_events: ["clarify","error"]`) maps 1:1 onto this with no instrumentation work.
This is the single most evaluation-ready part of the system.

**Real, code-derived values for the breakdown's `max_tool_calls` placeholder** (§W3 warns
against copying a number from an unrelated lecture example):

- `_MAX_AGENT_STEPS = 3` (`core.py:2617`) — the hard loop bound.
- Loop guard: a repeated `(tool, input)` pair is served from cache; on the **2nd** repeat
  (`repeats >= 2`, `core.py:2963`) the loop force-finalizes via `_force_final`.
- Registered tools: exactly two — `sql_ledger` and `search_receipts` (`_run_agent_tool`,
  `core.py:2770`). An unknown tool name returns an observation rather than raising.

**What MLflow gives you (and does not).** 60 runs exist in `mlflow.db`, experiment
`stai_ocr_receipts` (id 1), spanning the recorded `start_time` range in the file; 52
`FINISHED`, 8 `FAILED`. By run-name prefix: `agent` 21, `extract` 20, `sql` 18, `rag` 1.

- Metric keys: `error`, `eval_count`, `failed`, `items_extracted`, `latency_seconds`,
  `needs_disambiguation`, `num_steps`, `pages`, `prompt_eval_count`, `retried`,
  `rows_returned`, `sources_retrieved`, `succeeded`, `used_embeddings`.
- Param keys: `concurrency`, `error_message`, `files`, `final_sql`, `first_error`,
  `image_bytes`, `model`, `pages`, `query`, `question`, `tools_used`.

These are **run-level aggregates only**. There is no per-step record, no ordered event
list, no per-tool timing, and `tools_used` is a lossy comma-joined string. **The 60 runs
are ad-hoc development traces, not evaluation runs**, and per breakdown §3 must not be
attributed to any evaluated configuration.

---

## 7. Evaluation libraries

| Library | Installed | Note |
|---|---|---|
| `pytest` | **yes** | Not in `requirements.txt` |
| `mlflow` 3.14.0 | yes | Pinned |
| `pandas`, `numpy`, `matplotlib` | yes | Sufficient for W7 EDA without new deps |
| `ragas` | **no** | W5 would need it installed **and** an LLM-judge backend configured |
| `sqlglot` | **no** | W5 structural SQL comparison would need it |
| `jupyter` / `notebook` | **no** | **W8's notebook deliverable has no runtime.** Blocking for W8. |
| `datasets`, `deepeval` | no | — |
| `langgraph` | no | Confirms §1 item 3 |

Python 3.12.13 in `.venv`.

Adding `ragas` pulls a large dependency tree and a judge-model requirement; the breakdown
(§2, §W5) already says Ragas is *not* established as required and that equivalent
retrieval/grounding metrics may be implemented directly. Given `numpy` is already present,
context precision/recall can be computed directly against relevant-receipt-ID labels with
no new dependency. **Recommendation: defer Ragas; it is optional, not blocking.**

---

## 8. Run commands (verified present in repo)

| Purpose | Command | Source |
|---|---|---|
| Tests | `./.venv/bin/python -m pytest -q` | verified, §3 |
| API (local) | `uvicorn api:app --host 0.0.0.0 --port 8000` | `README.md:245`, `api.py:5` |
| Ollama (local) | `ollama serve` | `README.md:239` |
| Full stack | `docker compose up --build` | `README.md:262` |
| Frontend | port `8502` → container `3000` | `docker-compose.yml:10` |
| MLflow UI | port `5001` → container `5000` | `docker-compose.yml:70` |

---

## 9. Quick Chat: two parsers, and the UI uses the untested one

W2-C's optional item "server/client parser consistency, if both are in scope" — **both are
in scope, and they are not the same code.**

| | Server | Client |
|---|---|---|
| Location | `finance.parse_quick_text` (`finance.py:1456`) | `web-next/app/lib/parseQuick.ts` |
| Exposed as | `POST /quick` (`api.py:798`) | imported directly by `QuickChatModal.tsx:8` |
| **Used by the shipped UI?** | **No** | **Yes** (`QuickChatModal.tsx:37`) |
| Test infrastructure | pytest available | **none exists** |

`QuickChatModal.tsx:4` comments that parsing is "client-side today ... a server LLM parser
can replace it later." So `POST /quick` is currently reachable but unused by the product.

**This is a scoping decision the team must make, not one to resolve by assumption:**
evaluating only `parse_quick_text` would measure code no user exercises, while evaluating
`parseQuick.ts` requires new JS test infrastructure. Flagging for the owner of the
unassigned finance lane (breakdown §6).

---

## 10. Blockers, in priority order

| # | Blocker | Blocks | Status |
|---|---|---|---|
| B1 | **One receipt image; zero verified labels** | W1, W2-A, W4, W5, W7 | **OPEN — largest blocker.** No answer key can be built without receipt images and human labels. Not resolvable in code. |
| B2 | **Finance schema had never been created; no fixture** | W2-B, W2-E, W4 | ✅ **RESOLVED** — `fixtures/seed_finance.py` builds a deterministic 6-account / 5-transaction / 2-receipt ledger with hand-computed expected balances. |
| B3 | **Ground-truth data would live in gitignored files** | W1, §11 "versioned" | ✅ **RESOLVED** — the versioned artifact is the seeder script, not a binary `.db`. Generated fixtures are gitignored as build artifacts. |
| B4 | **No notebook runtime** | W8 | ✅ **RESOLVED** — `jupyterlab` + `ipykernel` in `requirements-eval.txt`, kept out of the API container. |
| B5 | **`receipt_docs` (5) < `receipts` (6)** | W5 retrieval recall | **OPEN** — in the dev `ledger.db` only. The evaluation fixture is built clean, so it does not affect the harness; still must be resolved or recorded before measuring recall on real data. |
| B6 | **Config defects §4.1–§4.4** | W0 freeze, W6 | ✅ **RESOLVED** — all four fixed (§4). |
| B7 | **Quick Chat scope undecided (§9)** | W2-C | ✅ **RESOLVED** — team chose the shipped TypeScript parser. vitest stood up in `web-next`; both parsers now tested, and the shared defect D2 fixed in both. |

None of B1–B7 were introduced by this audit.

---

## 10b. Application defects surfaced by the new tests

Found after the audit, while implementing W2-B and W2-C. All are **pre-existing
application bugs, not regressions**. All are now **fixed with regression tests**; there
are no remaining xfails in either suite. Full write-ups in [`README.md`](README.md).

| ID | Defect | Severity | Status |
|---|---|---|---|
| **D1** | `finance.import_backup` deleted all 12 finance tables when given a malformed payload (`{"not":"a backup"}`, `{}`, `None`) and reported success. Reachable from `POST /backup/import`, which has no auth in front of it. Column names from the payload were also interpolated unvalidated into the `INSERT`. | **High — silent data loss** | ✅ Fixed — payload validated before any `DELETE`; column names checked against `PRAGMA table_info` |
| **D2** | Quick Chat silently dated `"250 lunch 1 apr"` as *today*. `parseDate` short-circuited on the `"mon d"` regex, which matched the note word plus the day number, so the `"d mon"` branch never ran. Confidence still reported `"high"`. **Present in both the TypeScript and Python parsers.** | **Medium — silent wrong data** | ✅ Fixed in both |
| **D2b** | `finance._parse_date` did `min(day, 28)`, silently turning `"apr 30"` into April 28. Found while fixing D2. | **Medium — silent wrong data** | ✅ Fixed — builds the real date, skips impossible ones |
| **D2c** | The month test was inverted (`token.startsWith(month)`), so `"marketing 5"` parsed as March 5. | **Low** | ✅ Fixed — now `month.startsWith(token)`; also accepts `"sept"` |
| **D4** | Quick Chat's amount regex ended `([km])?` with no word boundary, so the shorthand suffix matched the first letter of the *next* word: `"250 milk"` → ₱250,000,000, `"300 movie tickets"` → ₱300,000,000, `"250 kilo rice"` → ₱250,000, `"80 kape"` → ₱80,000. The note-stripping regex had the same flaw (`"250 milk"` → note `"ilk"`). **Both parsers.** Found by driving the real `POST /parse` endpoint, not by unit tests. | **High — silent wrong data on ordinary input** | ✅ Fixed — `\b` anchors all four regexes |
| **D3** | `core._normalize_scope` let `int(float('inf'))` escape as `OverflowError` → unhandled 500 instead of `GuardrailError`. Not reachable from the API (pydantic types `receipt_ids` as `list[int]`). | **Low — latent** | ✅ Fixed |

These map onto the breakdown's W7 failure taxonomy: D1 is "Backup/restore loss or
relationship corruption"; D2/D2b/D2c/D4 are "Quick Chat parse error"; D3 is
"Configuration/environment failure".

**Method note worth carrying into W4.** D4 was the most severe Quick Chat defect and the
unit tests missed it — every existing case happened to use a note starting with a safe
letter. It surfaced only when the real `POST /parse` endpoint was driven with ordinary
phrases. This is direct evidence for the breakdown's insistence on end-to-end evaluation
as a separate layer: component tests confirm the rules you thought to check, and a
plausible-looking parse can hide a 1,000,000× error.

---

## 11. Open questions — for the team, not resolvable from the repository

Additional to the breakdown's §10 instructor questions; these are answerable only by the
team and each changes what gets built:

1. **B1:** Where do additional receipt images come from, and who labels them? This gates
   everything.
2. **B7:** Evaluate the TypeScript parser (matches the product, needs new JS tooling), the
   Python parser (cheap, measures unused code), or both for consistency?
3. **B2:** Should the finance fixture be generated by a seeding script (reproducible,
   versionable) or captured as a binary `.db` snapshot?
4. **§4 defects:** Fix before or after freezing the baseline? Fixing first makes the
   configuration honest; fixing after keeps the baseline untouched. Recommend fixing
   §4.3 (stray MLflow runs) and §4.1 (misleading dead knob) **before** the freeze, since
   both corrupt the record of what was tested — but this is the team's call.
5. Does the frozen-configuration requirement extend to pinning `pytest` and the vision
   model digest (not just the tag) in `requirements.txt`?

---

## 12. Definition of done — W0 status

| W0 criterion | Status |
|---|---|
| Every supposed instructor requirement has evidence or is relabeled | **Deferred** — requires the transcript, which is not in this repository. No requirement is asserted anywhere in `evaluation/`. |
| The exact tested deployment configuration can be reproduced | **Partial** — recorded in `CONFIGURATION.md`; §4 defects and the untracked `MLFLOW_TRACKING_URI` are documented gaps. |
| No task depends on an assumed LangGraph or authentication layer | **Met** — both confirmed absent (§1). |
| Repository inventory table | **Met** (§2). |

The transcript-dependent items (breakdown §W0 "recheck the transcript", §10) cannot be
completed from the repository and remain open for the team.
