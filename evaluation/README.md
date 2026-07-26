# Snag evaluation

Implements the workstreams in `docs/Snag_Agentic_Evaluation_Task_Breakdown.md` that are
not blocked on receipt data. Start with [`REQUIREMENTS_AUDIT.md`](REQUIREMENTS_AUDIT.md)
— it records what the repository actually contains and which blockers gate the rest.

> **Nothing in this directory is a measured evaluation result.** No accuracy figure, pass
> rate, latency, or cost has been produced. What exists is the *instrumentation*: fixtures,
> component tests, and the trajectory harness. Every threshold or sample size mentioned is
> labelled as proposed by the team, per the breakdown's §2 rule.

---

## Commands

| What | Command |
|---|---|
| Python evaluation suite | `./.venv/bin/python -m pytest evaluation/tests -q` |
| Everything (incl. the original 10 tests) | `./.venv/bin/python -m pytest -q` |
| Quick Chat (TypeScript) | `cd web-next && npm test` |
| Rebuild the finance fixture | `./.venv/bin/python evaluation/fixtures/seed_finance.py` |

Evaluation-only dependencies (test runner, notebook runtime, EDA) install from
`evaluation/requirements-eval.txt` — deliberately separate from the root
`requirements.txt`, which builds the API container.

---

## Layout

```
evaluation/
├── REQUIREMENTS_AUDIT.md      W0 — repository audit, blockers, open questions
├── CONFIGURATION.md           W0 — tested-configuration card + per-run capture template
├── trajectory.py              W3 — trajectory collection, comparison, metrics
├── datasets/
│   └── trajectory_cases.json  W3 — 7 pilot ReAct cases
├── fixtures/
│   └── seed_finance.py        W1 — deterministic finance + receipt fixture builder
└── tests/
    ├── conftest.py            DB isolation wiring (read this before adding tests)
    ├── test_w2b_finance.py    W2-B/W2-E — 39 finance component tests
    ├── test_w2d_sql_react.py  W2-D — 62 SQL / scope / ReAct-parsing tests
    └── test_w3_trajectory.py  W3 — 37 tests of the harness itself
```

---

## Coverage against the breakdown

| Workstream | State |
|---|---|
| W0 audit | **Done** — `REQUIREMENTS_AUDIT.md`, `CONFIGURATION.md`. Transcript-dependent items remain open for the team. |
| W1 dataset | **Partial** — finance + receipt fixtures done. Receipt *ground truth* blocked on B1 (one image, no labels). |
| W2-A extraction | **Partial** — guardrails, review reasons, and the 10 pre-existing post-processing tests. Field/line-item accuracy blocked on B1. |
| W2-B finance | **Done** — balances, net worth, transfer rules, templates, recurring, installments, goals/debts/receivables, history consistency. |
| W2-C Quick Chat | **Done** — 64 tests against `parseQuick.ts`, the parser the shipped UI calls. |
| W2-D SQL/ReAct | **Done for the model-free half** — validator, scope sandbox, response parsing, tool dispatch. Routing/execution accuracy needs a live model (W5). |
| W2-E posting & backup | **Done** — posting, idempotency, linkage, backup completeness, restore round trip. |
| W3 trajectory | **Harness done and self-tested.** Awaiting a live run against a reachable Ollama. |
| W4 E2E | Not started — depends on W1 receipt ground truth. |
| W5 SQL/RAG accuracy | Not started — needs a model and relevant-receipt-ID labels. |
| W6 performance | Not started. |
| W7 EDA | Not started — needs results to analyze. |
| W8 notebook | **Unblocked** — `jupyterlab` now installs from `requirements-eval.txt`. Notebook not yet written (needs results). |

---

## Defects found and fixed

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
