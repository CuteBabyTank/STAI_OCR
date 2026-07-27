# Snag Evaluation Follow-up

## Baseline

This follow-up begins at commit `c816198f34bf0b3d281a76adb7bc662c4e50cb78` on `main`.
The original W0–W8 evaluation plan is not complete. The repository contains substantial
test instrumentation and a receipt-to-statement reconciliation module, but it has no
verified receipt ground truth, no final evaluation result set, and no final notebook.

The prior audit found a dedicated Python evaluation dependency file
(`evaluation/requirements-eval.txt`), an npm/Vitest web project (`web-next/package.json`),
and empty versioned result directories. The checked-in virtual environment lacked `pytest`
and the web dependency installation was absent. The offline trajectory validator did pass
for seven declared cases; that validates case loading only and is not a live-model result.

## Stage 1 Authorization

Stage 1 only repairs and executes the existing evaluation infrastructure. It will:

1. use the existing Python requirements file and npm lockfile rather than add a second
   dependency system;
2. run narrow suites before broad Python and web suites;
3. preserve every command's raw output under `evaluation/results/raw/`;
4. classify failures without changing unrelated production behavior;
5. freeze the actually tested configuration; and
6. update implementation status using execution evidence.

Stage 1 will not add Ragas/sqlglot, PDF/image statement parsing, Cowork integration,
new finance features, a final benchmark, or unsupported accuracy claims.

## Current Statement Scope

`reconciliation.py` currently ingests structured CSV statements through
`parse_statement_csv()` and `import_statement()`. It does not implement PDF statement
text/table extraction or image-based statement OCR. CSV may be sufficient for a scoped
proof of concept only if the team and instructor accept structured statement exports;
otherwise an additional parser or an explicit limitation is required. This decision is
outside Stage 1.

## Benchmark Priority After Stage 1

The Snag/Cowork benchmark contract is P0 preparation, not P3: shared cases, independently
verified ground truth, a common output schema, fixed prompt, retry/timing/scoring rules,
and raw-output preservation must be designed before either system’s final comparison.
Running the external Cowork comparison remains P1, after Snag evaluation is stable.

## Evidence Rules

“Test exists”, “test executes”, “test passes”, “uses synthetic fixtures”, and
“measures real correctness” are separate claims. Passing structural or mocked tests do
not establish OCR, matching, SQL/RAG, or end-to-end accuracy metrics.
