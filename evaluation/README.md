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

Current state: **147 passed, 2 xfailed** (Python) and **64 passed** (TypeScript).
The xfails are known defects, documented below — not flaky tests.

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
| W8 notebook | **Blocked** — `jupyter` is not installed (audit blocker B4). |

---

## Known defects found while building this

Both are pre-existing application bugs surfaced by the new tests. Neither was fixed:
fixing them changes application behaviour and is the team's call. Both are recorded as
expected-to-fail so the suites stay green while the defects stay visible, and both flip
to hard failures the moment they are fixed — which is the signal to remove the marker.

### D1 — `import_backup` destroys the ledger on a malformed payload

**Severity: high (silent data loss).**
`finance.import_backup` does not validate its payload. `data = (payload or {}).get("data", {})`
yields `{}` for any malformed input; with `replace=True` (the default) it then `DELETE`s all
12 finance tables and inserts nothing, returning a success response.

Reproduced with `{"not": "a backup"}`, `{}`, and `None` — each wiped 5 transactions and
6 accounts. Reachable from `POST /backup/import`, which has no auth layer in front of it.

Test: `test_w2b_finance.py::test_malformed_backup_is_handled_visibly` (xfail, strict).
Suggested fix: validate `payload["format"] == "stai-ledger-backup/1"` and require a
non-empty `data` before any `DELETE`.

### D2 — Quick Chat silently mis-dates `"<amount> <note> <day> <month>"`

**Severity: medium (silent wrong data, no warning).**
`parseDate` tries the `"mon d"` pattern first and only falls back to `"d mon"` via `||`
if the first finds nothing. With a note word before the day, the first pattern matches
the note word plus the day number ("lunch 1"), the month lookup fails, and the function
returns the reference date — the `"d mon"` pattern is never tried.

Effect: `"250 lunch 1 apr"` is dated **today**, not 1 April. Confidence still reports
`"high"`. The source comment on `parseDate` advertises `"1 apr"` as supported.
Reproduced with `"250 lunch 1 apr"`, `"250 dinner 5 may"`, `"1000 groceries 3 mar"`,
`"500 taxi 2 feb"`. The `"mon d"` form is unaffected.

Test: `parseQuick.test.ts` → `"parses 'd mon' when a note word precedes the day"`
(`it.fails`), with a companion test recording the actual behaviour.
Suggested fix: run both patterns and take the first that resolves to a real month,
rather than short-circuiting on a regex match that may not contain one.

### Config defects fixed during W0

Three were repaired before the baseline freeze, because each corrupted the record of
what was being tested (see `REQUIREMENTS_AUDIT.md` §4):

- Dead `VISION_MAX_DIM` / `VISION_NUM_CTX` / `_downscale_image` removed from `core.py`,
  and the misleading `VISION_MAX_DIM=0` dropped from `docker-compose.yml`. The live knob
  is `OCR_MAX_IMAGE_DIM=1600`; the compose file previously read as "no downscaling".
- `agent_stream`'s clarify path used unguarded `mlflow.log_metric`, which auto-started a
  run even with `MLFLOW_ENABLED=0` and leaked it open. Now uses `_mlog_metric`.
- README's `OCR_NUM_PREDICT` default corrected from `1024` to `4096`.

**Still open:** the three-way model-default conflict (`REQUIREMENTS_AUDIT.md` §4) was
*not* resolved — it needs a team decision on which model is canonical, and the README
contradicts itself. Always record models at runtime from `GET /health`.

---

## Adding tests

Read `tests/conftest.py` first. The constraint that governs everything:

> `core.DB_PATH` is resolved from `LEDGER_DB_PATH` at import time and bound as a default
> argument in `core._connect()`. It must be set **before** the first `import core`.

So: **never import `core` or `finance` at module scope** in this package. Use the `core`
and `finance` fixtures, which import lazily after the environment is set. The
`finance_fixture` fixture rebuilds a clean database per test, so tests cannot leak into
each other and none of them can touch a developer's real `ledger.db`.
