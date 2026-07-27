# Evaluation Data Inventory

**Inventory date:** 2026-07-27  
**Scope:** repository files available at Stage 2 planning time. This inventory
does not inspect or reproduce personal document contents.

## Summary

No bank-statement, credit-card-statement, or transaction CSV source file is
available in the repository. No independently verified receipt-to-statement
ground-truth dataset is available. The repository contains deterministic
synthetic finance fixtures and test assertions useful for development, plus one
unreviewed receipt image and local database artifacts that must be treated as
restricted until provenance, consent, and redaction are confirmed.

## Sources

| Path | Format and quantity | Synthetic / real | PII status | Independently verified | Development use | Final-evaluation use | Missing labels and limitations |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `Receipt.jpg` | JPEG; 1 receipt image | Unknown; do not assume synthetic | Unknown; treat as potentially sensitive | No | Only after owner permission and redacted handling | No, pending consent, redaction, and independent labels | No receipt fields, line items, or match labels; provenance and image quality not assessed in this report. |
| `ledger.db` | SQLite database; 1 local artifact | Mixed/unknown local state | Potential PII; do not inspect or commit | No | Not a controlled source; use only a newly seeded fixture for tests | No | State may be stale or personal; no independent ground truth or source-document linkage. |
| `mlflow.db` | SQLite tracking database; 1 local artifact | Historical run metadata | Potential prompts/outputs or identifiers | No | Audit evidence only when access is authorized | No | Not source financial ground truth; mutable local tracking state. |
| `evaluation/fixtures/seed_finance.py` | Python deterministic fixture; 2 receipt records, 3 receipt items, 5 transactions, 6 accounts per seed | Synthetic | No expected PII | Verified by automated fixture tests, not independent human labeling | Yes | No | Contains structured records, not receipt documents or an independently labeled reconciliation set. |
| `evaluation/fixtures/_test_ledger.db` | Generated SQLite fixture artifact | Synthetic/generated | No expected PII | Derived from fixture code only | Regenerate rather than rely on checked artifact | No | Generated state; no receipt images, statement files, or independent labels. |
| `evaluation/tests/test_w2f_reconciliation.py` | Python tests with inline CSV text and assertions | Synthetic | No expected PII | Verified as automated expected behavior | Yes | No | Inline examples are unit-test fixtures, not a frozen dataset or blinded labels. |
| `evaluation/datasets/quickchat_corpus.json` | JSON parser corpus; synthetic query examples | Synthetic | No expected PII | Test corpus, not independently annotated finance ground truth | Yes, for parser regression | No | Does not contain receipts, statements, transaction IDs, or expected matches. |
| `evaluation/datasets/trajectory_cases.json` | JSON; 7 trajectory pilot cases | Synthetic | No expected PII | Case definitions reviewed as pilot material | Yes, for trajectory development | No | No receipt/statement source package or final reconciliation labels. |
| `evaluation/results/raw/trajectory-20260727T020610Z_stage1-trajectory.json` | JSON; 7 recorded pilot results | Generated pilot output | No source-document PII expected; retain access controls | Raw execution evidence, not ground truth | Yes, for audit and scorer diagnosis | No | Model output is not a label source; includes one retained failure (`RCT-006`). |

## File-type coverage

| Data type | Available sources | Final-ready status |
| --- | --- | --- |
| Receipt images | One unreviewed JPEG (`Receipt.jpg`) | Not ready |
| Receipt PDFs | None found | Absent |
| Bank statements | None found | Absent |
| Credit-card statements | None found | Absent |
| Statement CSV exports | None found | Absent |
| Synthetic structured transactions | Seed fixture and inline unit-test CSV | Development only |
| Receipt labels | None | Absent |
| Statement labels | None | Absent |
| Expected receipt-statement matches | Unit-test assertions only | Development only |
| Independently labeled finance ground truth | None | Absent |

## Handling requirements

- Do not add unredacted financial documents, database exports, or model outputs
  containing personal information to version control.
- Build the final dataset in a restricted location or approved repository path
  using redacted copies, a case manifest, and separate label files.
- Treat all raw real-world documents as unusable for final evaluation until the
  owner confirms permission, PII handling, and independent label verification.
- Record only counts, hashes, and approved redacted metadata in public reports.
