# Snag evaluation

Implements the workstreams in `docs/Snag_Agentic_Evaluation_Task_Breakdown.md` that are
not blocked on receipt data.

- **[`IMPLEMENTATION_STATUS.md`](IMPLEMENTATION_STATUS.md)** — start here. Evidence-based
  status of every W0–W8 task at HEAD, the prioritized gap table, proof-point alignment, and
  Cowork readiness.
- **[`IMPLEMENTATION_BACKLOG.md`](IMPLEMENTATION_BACKLOG.md)** — the verified-gaps backlog
  derived from it.
- [`REQUIREMENTS_AUDIT.md`](REQUIREMENTS_AUDIT.md) — the original W0 repository audit and
  the blockers that gate the rest.

> **A single live trajectory pilot has been recorded.** Its raw artifact is retained under
> `results/raw/`; it covers seven synthetic pilot cases on the recorded configuration and
> is not a final accuracy, latency, or cost result. Receipt extraction and statement-matching
> accuracy remain unmeasured because independently verified ground truth is still absent.

---

## Commands

| What | Command |
|---|---|
| Python evaluation suite | `./.venv/bin/python -m pytest evaluation/tests -q` |
| Everything (incl. the original 10 tests) | `./.venv/bin/python -m pytest -q` |
| Quick Chat (TypeScript) | `cd web-next && npm test` |
| Rebuild the finance fixture | `./.venv/bin/python evaluation/fixtures/seed_finance.py` |
| Retrieval microbenchmark | `./.venv/bin/python evaluation/bench_retrieval.py` |
| Tested-configuration capture | `./.venv/bin/python -m evaluation.report config` |
| Validate trajectory cases (offline) | `./.venv/bin/python -m evaluation.trajectory --dry-run` |
| Trajectory run (needs Ollama) | `./.venv/bin/python -m evaluation.trajectory` |

Performance work is written up separately in [`PERFORMANCE.md`](PERFORMANCE.md) — what was
changed, what was measured, and what was deliberately left alone.

Evaluation-only dependencies (test runner, notebook runtime, EDA) install from
`evaluation/requirements-eval.txt` — deliberately separate from the root
`requirements.txt`, which builds the API container.

---

## Layout

```
evaluation/
├── IMPLEMENTATION_STATUS.md   Audit of every W0–W8 task + gap table (start here)
├── IMPLEMENTATION_BACKLOG.md  Verified-gaps backlog (P0–P3)
├── REQUIREMENTS_AUDIT.md      W0 — repository audit, blockers, open questions
├── CONFIGURATION.md           W0 — tested-configuration card + per-run capture template
├── PERFORMANCE.md             W6 — what was changed, what was measured (no live latency)
├── requirements-eval.txt      Evaluation-only deps (pytest, jupyterlab, pandas, matplotlib)
├── trajectory.py              W3 — trajectory collection, comparison, metrics + runner CLI
├── report.py                  Configuration capture + machine-readable result writer
├── bench_retrieval.py         W6 — retrieval microbenchmark (synthetic, no model)
├── datasets/
│   ├── trajectory_cases.json  W3 — 7 pilot ReAct cases (1 of 10 proposed case families)
│   └── quickchat_corpus.json  W2-C — shared corpus read by BOTH parser suites
├── fixtures/
│   └── seed_finance.py        W1 — deterministic finance + receipt fixture builder
├── results/                   Run artifacts (empty until a run is executed)
└── tests/
    ├── conftest.py                  DB isolation wiring (read this before adding tests)
    ├── test_w2a_preprocess.py       W2-A — image preprocessing
    ├── test_w2a_reconcile.py        W2-A — receipt arithmetic reconciliation + tolerance
    ├── test_w2a_coercion.py         W2-A — JSON / numeric coercion, description cleanup
    ├── test_w2a_confidence.py       W2-A — field confidence + value-equality gating
    ├── test_w2a_pdf_batch.py        W2-A — PDF page expansion, batch failure isolation
    ├── test_w2a_audit.py            W2-A — post-extraction arithmetic audit
    │                                    (items vs SUBTOTAL, VAT, payment, line math)
    ├── test_w2a_recovery.py         W2-A — the second-pass re-read of empty fields
    │                                    and half-read item blocks (may only ADD)
    ├── test_w2a_recheck.py          W2-A — the check-driven re-read: a failed sum
    │                                    sends the OCR back to that part of the paper
    ├── test_w2b_finance.py          W2-B/W2-E — finance components
    ├── test_w2b_budgets.py          W2-B — budget aggregation, periods, carry-forward
    ├── test_w2c_quick_python.py     W2-C — Python Quick Chat parser
    ├── test_w2c_parser_agreement.py W2-C — the two parsers must agree (shared corpus)
    ├── test_w2d_sql_react.py        W2-D — SQL / scope / ReAct parsing
    ├── test_w2d_agent_paths.py      W2-D/W3 — loop guard, step budget, clarification
    ├── test_w2e_persistence.py      W2-A/W2-E — receipt save, linkage, posting fidelity
    ├── test_w2f_reconciliation.py   W2-F — receipt-to-STATEMENT reconciliation
    ├── test_w2f_reconciliation_api.py  W2-F — the same, over the real HTTP routes
    ├── test_w2g_expense_tool.py     W2-G — the agent's WRITE tool + name resolvers
    ├── test_w2g_expense_adversarial.py  W2-G — adversarial attacks on the same write
    │                                    path (double-charge, wrong-account, clarify)
    ├── test_w2h_finance_tools.py    W2-H — income, transfers, goals, debts,
    │                                    receivables; create / edit / delete
    ├── test_w2i_agent_security.py   W2-I — prompt injection through data,
    │                                    fabrication, scope, tool-registry integrity
    ├── test_w2j_history_window.py   W2-J — conversation window: budget, recency,
    │                                    prompt placement, context arithmetic,
    │                                    resuming a clarified request
    ├── test_w2k_account_attribution.py  W2-K — a write may only land on an account
    │                                    the USER named, not one the model invented
    ├── test_w2l_log_spend.py        W2-L — logging spending from chat as a receipt
    │                                    when no account was named; reaches the
    │                                    spending overview, moves no balance
    ├── test_w3_trajectory.py        W3 — the harness itself
    ├── test_w5_retrieval.py         W5 — retrieval mechanism (synthetic vectors)
    ├── test_w6_performance.py       W6 — structural only (no timing assertions)
    ├── test_fixture_isolation.py    Test infrastructure — SQLite fixture lifecycle
    ├── test_report.py               Result writer + configuration capture
    └── test_docs_match_code.py      Guard against docs drifting from the code
```

Plus `web-next/app/lib/parseQuick.test.ts` and `parseQuick.corpus.test.ts` (vitest) and
the pre-existing `test_extraction.py` at the repo root. Run the suites for current counts
— `test_docs_match_code.py` keeps this layout honest, but counts are deliberately not
duplicated here after they went stale once.

---

## Coverage against the breakdown

| Workstream | State |
|---|---|
| W0 audit | **Done** — `REQUIREMENTS_AUDIT.md`, `CONFIGURATION.md`. Transcript-dependent items remain open for the team. |
| W1 dataset | **Partial** — finance + receipt fixtures done. Receipt *ground truth* blocked on B1 (one image, no labels). |
| W2-A extraction | **Partial (12 of 14 checklist items)** — guardrails, review reasons, preprocessing, reconciliation + tolerance, JSON/numeric coercion, field confidence + gating, PDF page expansion, batch failure isolation, save/linkage. The 2 remaining (header-field and line-item **accuracy**) are blocked on B1. |
| W2-B finance | **Partial (11 of 13)** — balances, net worth, transfer rules, templates, recurring, installments, goals/debts/receivables, history, **and budget aggregation**. Remaining: "statistics" consistency untested, and budget **carry-forward does not exist** (defect D5). |
| W2-C Quick Chat | **Done** — `parseQuick.ts` (the parser the shipped UI calls) + the Python mirror, **plus a shared corpus proving the two agree** (`datasets/quickchat_corpus.json`, read by both suites). |
| W2-D SQL/ReAct | **Done for the model-free half** — validator, scope sandbox, response parsing, tool dispatch, **and the real agent control paths** (loop guard, step budget, clarification, error containment) driven through `agent_stream`. Routing/execution *accuracy* needs a live model (W5). |
| W2-E posting & backup | **Done** — posting, idempotency, linkage, backup completeness, restore round trip. |
| W2-F receipt-to-statement | **Built and tested (104 tests), accuracy unmeasured.** `reconciliation.py` — CSV statement ingestion, merchant normalization, two-pass one-to-one matching, duplicate/refund/discrepancy detection, report generation, 6 API routes. Matching *accuracy* needs a real bank export + labelled receipts (B1). |
| W3 trajectory | **Harness done, self-tested, and CLI-wired — still never executed.** `python -m evaluation.trajectory --dry-run` validates the cases offline; a real run needs a reachable Ollama. Every event evaluated so far is synthetic. Cases exist for 1 of 5 pipelines. |
| W4 E2E | Not started — depends on W1 receipt ground truth. `E2E-MAN`/`E2E-QCK`/`E2E-BAK` are runnable without a model. |
| W5 SQL/RAG accuracy | **Partial** — 19 retrieval-*mechanism* tests (synthetic vectors, stubbed `_embed`) incl. scope isolation. **No relevance ground truth, no SQL question set, no answer evaluation** — every W5 metric is uncomputed. |
| W6 performance | **Partial, structural only** — round-trip counts and generation defaults verified against a stubbed model; retrieval/index microbenchmarks measured. **No real request latency, no live-model timing, no repeated runs, no cost worksheet.** See `PERFORMANCE.md`. |
| W7 EDA | Not started — needs results to analyze. |
| W8 notebook | **Unblocked** — `jupyterlab` now installs from `requirements-eval.txt`. Notebook not yet written (needs results). |

---

## Defects found and fixed

### D6 — `_num` fabricated numbers from containers ✅ FIXED

**Severity: medium (silent wrong data).** `extraction._num` fell through to its string
path for any non-scalar: `str([1, 2])` → strip non-digits → **12.0**; `{"amount": 1}` →
**1.0**. Neither figure appears on the receipt. It is reachable because `_num` runs on the
**unvalidated** model dict — `core.py`'s post-processing chain executes before pydantic —
so the fabricated number would pass schema validation looking legitimate and feed
reconciliation and the ledger. Same family as D4: an input no existing test happened to try.

**Fix:** `_num` returns `None` for `list`/`tuple`/`set`/`dict`. A wrong shape is not a
misformatted number. Tests in `test_w2a_coercion.py`.

### D5 — Budget carry-forward is stored and never used ⚠️ NOT FIXED

**Severity: medium (a user-facing control that does nothing).** `carry_forward` is a
parameter, a column, an API field, a UI toggle and a TypeScript type — and **no computation
in `finance.py` reads it**. Two identical plans, one with carry-forward on, resolve to the
same limit.

Deliberately **not** fixed: implementing it requires choosing semantics (roll over
indefinitely? does overspend carry as debt? which boundary?), which is a product decision,
not a defect repair. Characterized by test instead
(`test_carry_forward_does_not_change_the_resolved_limit`), so the gap is measured and the
test will fail the moment real carry-forward lands.

### Known architectural limitation — posting loses currency

`transactions` has no currency column, so `post_receipt_as_expense` carries a total across
as a bare number: a USD receipt becomes indistinguishable from a PHP one. Single-currency
by construction. Characterized by
`test_a_posted_transaction_carries_no_currency_of_its_own` rather than dropped from the
W2-E checklist.


All were pre-existing application bugs surfaced by the new tests. Each now has a
regression test; there are no remaining xfails in either suite.

### D1 — `import_backup` destroyed the ledger on a malformed payload ✅ FIXED

**Severity: high (silent data loss).**
`finance.import_backup` did not validate its payload. `data = (payload or {}).get("data", {})`
yielded `{}` for any malformed input; with `replace=True` (the default) it then `DELETE`d
all 12 finance tables and inserted nothing, returning a success response. Reproduced with
`{"not": "a backup"}`, `{}`, and `None` — each wiped 5 transactions and 6 accounts.
Reachable from `POST /backup/import`, which has no auth layer in front of it.

**Fix:** `_validate_backup()` checks the format marker, the `data` object, table names,
and row shapes **before** any `DELETE`. A second pass validates every column name against
`PRAGMA table_info` — column names cannot be parameterized and were being interpolated
straight into the `INSERT`, so an uploaded file could also smuggle SQL through a key.
A backup of a genuinely empty ledger still restores: emptiness was never the problem,
an unrecognized shape was.

Tests: `test_no_malformed_payload_can_destroy_the_ledger` (12 payload shapes),
`test_backup_with_an_injected_column_name_is_refused`,
`test_a_genuinely_empty_backup_still_restores`.

### D2 — Quick Chat silently mis-dated `"<amount> <note> <day> <month>"` ✅ FIXED

**Severity: medium (silent wrong data, no warning).**
`parseDate` tried the `"mon d"` pattern first and only fell back to `"d mon"` via `||`
if the first found nothing. With a note word before the day, the first pattern matched
the note word plus the day number ("lunch 1"), the month lookup failed, and the function
returned the reference date — the `"d mon"` pattern was never tried. `"250 lunch 1 apr"`
was dated **today**, not 1 April, with confidence still reporting `"high"`.

**Present in both parsers.** Fixed in `parseQuick.ts` *and* `finance._parse_date`, which
had the identical `or`-short-circuit.

**Fix:** collect candidates from both orderings, take the first that resolves to a real
month. The month test was also inverted — it asked whether the token starts with a month
abbreviation, so `"marketing 5"` parsed as March 5. It now asks whether a real month name
starts with the token, which rejects `"marketing"` and additionally accepts `"sept"`.

**Third bug found in the Python parser while fixing it:** `_parse_date` did
`min(day, 28)`, silently turning `"apr 30"` into April 28. Now builds the real date and
skips impossible ones (`"feb 30"`) so a later candidate can still match.

Tests: `parseQuick.test.ts` (70) and `test_w2c_quick_python.py` (24).

### D4 — Quick Chat inflated everyday amounts by 1,000× / 1,000,000× ✅ FIXED

**Severity: high (silent wrong data on ordinary input).** Found by driving the real
`POST /parse` endpoint during end-to-end verification, not by the unit tests — the
existing cases all happened to use notes starting with safe letters.

The amount regex ended `([km])?` with no word boundary, so the optional shorthand suffix
matched the **first letter of the following word**:

| Input | Parsed as | Should be |
|---|---|---|
| `250 milk` | ₱250,000,000 | ₱250 |
| `300 movie tickets` | ₱300,000,000 | ₱300 |
| `250 kilo rice` | ₱250,000 | ₱250 |
| `80 kape` | ₱80,000 | ₱80 |

The note-stripping regex had the same flaw, so `"250 milk"` also stripped `"250 m"` and
left the note as `"ilk"`. **Present in both parsers.**

**Fix:** anchor the suffix with `\b` in all four regexes. A suffix must now end a word,
so `"1.2k lunch"` and `"2m bonus"` still expand while `"250 milk"` is ₱250.

Tests: 6 parametrized cases plus note-integrity checks in each suite.

### D3 — `_normalize_scope` let infinity escape as a 500 ✅ FIXED

**Severity: low (latent).** `int(float('inf'))` raises `OverflowError`, which the
`except (TypeError, ValueError)` did not catch, so it escaped as an unhandled 500 instead
of a `GuardrailError`. Not reachable from the API — `receipt_ids` is typed `list[int]` and
pydantic rejects it first — but the function is documented as protecting the sandbox
builder from hostile input. `OverflowError` is now caught alongside the others; `inf`,
`-inf` and `nan` are covered by the test.

### Config defects fixed during W0

Three were repaired before the baseline freeze, because each corrupted the record of
what was being tested (see `REQUIREMENTS_AUDIT.md` §4):

- Dead `VISION_MAX_DIM` / `VISION_NUM_CTX` / `_downscale_image` removed from `core.py`,
  and the misleading `VISION_MAX_DIM=0` dropped from `docker-compose.yml`. The live knob
  is `OCR_MAX_IMAGE_DIM=1600`; the compose file previously read as "no downscaling".
- `agent_stream`'s clarify path used unguarded `mlflow.log_metric`, which auto-started a
  run even with `MLFLOW_ENABLED=0` and leaked it open. Now uses `_mlog_metric`.
- README's `OCR_NUM_PREDICT` default corrected from `1024` to `4096`.
- **`MLFLOW_TRACKING_URI` is now set explicitly in `core.py`.** Only docker-compose set
  it before, so a local `uvicorn api:app` run logged to a `./mlruns` file store while the
  container logged to `mlflow.db` — the same code produced traces in two different places
  depending on how it was launched, making a recorded run impossible to reproduce. It now
  defaults to the repo's `mlflow.db`, matching the container; the env var still wins.
- **README model table corrected.** It listed `llama3.2:3b` as the agent model in the
  models table and install steps while claiming `qwen2.5:latest` in the notebook section,
  and the code says `qwen2.5:latest`. The README now matches the code, documents the env
  var for each role, and states plainly that compose overrides two of the three — so the
  model in use depends on how the app was launched, and must be read from `GET /health`.

---

## Adding tests

Read `tests/conftest.py` first. The constraint that governs everything:

> `core.DB_PATH` is resolved from `LEDGER_DB_PATH` at import time and bound as a default
> argument in `core._connect()`. It must be set **before** the first `import core`.

So: **never import `core` or `finance` at module scope** in this package. Use the `core`
and `finance` fixtures, which import lazily after the environment is set. The
`finance_fixture` fixture rebuilds a clean database per test, so tests cannot leak into
each other and none of them can touch a developer's real `ledger.db`.
