# Stage 1 Execution Log

Date: 2026-07-27 (Asia/Manila). This log preserves the commands, outcomes, and failure
classification for Stage 1. The live trajectory's complete machine-readable output is
`trajectory-20260727T020610Z_stage1-trajectory.json` in this same directory.

## Dependency setup

| Command | Result |
|---|---|
| `python -m pip install -r evaluation/requirements-eval.txt` | Installed pytest `9.1.1`, JupyterLab `4.6.2`, ipykernel `7.3.0`; existing pandas/matplotlib retained. |
| `npm ci` in `web-next` | Installed 160 packages from lockfile v3; Vitest `2.1.9` became available. npm reported 7 dependency vulnerabilities; no upgrade was attempted in Stage 1. |
| `python -m pip install -r requirements.txt` | Installed declared `ollama 0.6.2` and `pypdfium2 4.30.0`; no manifest changed. |

## Test and runner outcomes

| Command scope | Outcome | Model required | Classification / notes |
|---|---|---|---|
| Preprocessing, coercion, `test_extraction.py` | `72 passed` | No | Component fixtures. |
| Initial persistence run | `9 passed, 9 errors` | No | Fixture infrastructure defect: unclosed SQLite context-manager connections blocked rebuild on Windows. |
| Fixture regressions + persistence after repair | `21 passed` | No | Verifies per-process temp fixture and closing connections. |
| Statement reconciliation + API | `104 passed` | No | CSV/synthetic fixture behavior only; not matching accuracy. |
| Retrieval + SQL safety | `84 passed` | No | Stubbed/synthetic retrieval and SQL-safety behavior. |
| Performance invariants | `25 passed` | No | Structural call-count/configuration checks, not latency results. |
| Trajectory dry run | 7 cases loaded | No | Validates case schema only. |
| Live trajectory pilot | `6/7` passed | Yes, remote Ollama | `RCT-006` failed `final_supported_by_observation`; raw artifact retained. |
| Initial full Python suite | `652 passed, 19 failed` | No | Missing declared `pypdfium2`; Windows default-encoding reads; docs correctly stale after live artifact. |
| PDF + parser-agreement after repair | `96 passed` | No | `pypdfium2` and UTF-8 reader fixes verified. |
| Web Vitest suite | `160 passed` | No | Two test files passed. |
| Final full Python suite | `671 passed, 1 warning` in 120.80s | No | Complete Stage 1 regression pass. |
| Final full web suite | `160 passed` in 616ms | No | Complete Stage 1 web regression pass. |

## Failure classifications

- **Missing dependency:** `pypdfium2` was declared in `requirements.txt` but absent from the
  root virtual environment; PDF tests could not execute until root requirements were installed.
- **Test/infrastructure defect:** native SQLite connection context managers commit/rollback but
  do not close. The fixture rebuilt a fixed database path between tests, causing Windows lock
  errors. `_ClosingConnection` and focused regressions now enforce the required lifecycle.
- **Test/platform defect:** UTF-8 evaluation assets were read with the Windows default code page,
  corrupting text and raising decode errors. Explicit UTF-8 reads now make those assets portable.
- **Evidence-document drift:** the first live result invalidated the previous blanket
  “nothing measured” disclaimer and the newly added fixture test was undocumented. Both were
  updated before the final full-suite rerun.

No receipt-level, field-level, line-item, statement-match, or Cowork accuracy result is
claimed by this log.
