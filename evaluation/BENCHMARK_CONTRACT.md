# Snag–Cowork Reconciliation Benchmark Contract

## Research question

> How accurately and efficiently can Snag reconcile receipt-derived expenses against bank or credit-card statement transactions compared with Claude Cowork?

This is a neutral comparison. It does not assume that either system will outperform the other.

## Scope

| Item | Contract |
| --- | --- |
| Primary use case | A person reconciles receipt-derived expenses with bank or credit-card transactions and identifies matches, discrepancies, and items requiring review. |
| Optional business use case | A small business reconciles employee or operating-expense receipts with a controlled card or bank export. This is a separate stratum and must not be pooled with personal cases without reporting it separately. |
| Systems | Snag at a recorded repository revision and model configuration; Claude Cowork at a recorded product/version/date configuration. |
| Unit of evaluation | One frozen case package containing receipt document(s), a structured statement transaction set, and case metadata. |
| Statement scope for this stage | UTF-8 CSV transaction ingestion. PDF text/table extraction and statement-image OCR are out of scope unless separately implemented and validated before the final experiment. |
| Output | One schema-valid result per case using `evaluation/datasets/reconciliation_output.schema.json`. |

## Experimental design

| Element | Definition |
| --- | --- |
| Independent variable | System used to produce the reconciliation output (Snag or Claude Cowork). A declared repeated run is a secondary factor, not a substitute for another case. |
| Controlled conditions | Frozen case manifest and labels, identical input files, identical schema, fixed Cowork prompt, recorded Snag configuration, common timezone/currency rules, clean system/session state where feasible, and identical retry/correction rules. |
| Dependent variables | Exact match and field accuracy, line-item accuracy, total support, match and discrepancy metrics, review behavior, severe errors, completion, correction, time, and system errors as defined in `evaluation/SCORING_SPEC.md`. |
| Ground truth | Human-created labels produced before final-system outputs are reviewed and independently checked by a second eligible person. |

## Dataset lifecycle

- **Development cases** may be used to refine prompts, parsing, schemas, and rubrics. Their outputs and labels cannot enter final aggregate metrics.
- **Pilot cases** may test instructions, timing, and collection procedures. The retained Stage 1 trajectory pilot, including `RCT-006`, is pilot evidence only and is not a reconciliation final test.
- **Final cases** must be frozen before either final Snag or Cowork run. Freeze the case manifest, file hashes, ground-truth labels, scoring version, prompt, and declared configuration in a dated release record.
- A case discovered to be mislabeled after freeze is not silently edited. Keep the original release, document the defect, and publish a versioned corrected analysis only if the instructor/team approves it.

## Inputs and outputs

Each case package must identify a `case_id` and contain only the approved receipt documents and statement representation for that case. Both systems receive the same package, including currency and timezone assumptions. Snag may use its normal receipt extraction pipeline; Cowork may inspect the same source files, but neither receives hidden labels or another system's output.

The common result is a JSON document conforming to `evaluation/datasets/reconciliation_output.schema.json`. A result can state that data is unreadable, ambiguous, unmatched, or failed; it must not invent a match to satisfy the schema.

## Run rules

### Retries

- Record every attempt separately.
- Permit at most one retry for a documented technical failure (for example, an upload error, service outage, or malformed platform export) using the exact same frozen inputs and instructions.
- Do not retry merely because an answer is low quality, incomplete, or unfavorable. Score the first completed observable output.
- If a retry is permitted, report the first attempt, retry reason, and the protocol-selected scored attempt.

### Corrections

- Preserve the raw system output before any person edits it.
- Score the raw output first. Human corrections are a separate recorded phase, never a replacement for raw-system metrics.
- Record each correction in the output's `manual_corrections` array, including actor role, reason, time, and affected field. Do not use corrections to alter a system's raw score.

### Timing

- Start the system timer immediately after the complete frozen case package is submitted or the automated run is invoked.
- Stop when the system first returns an exportable, schema-valid output, a terminal failure, or the declared timeout. File preparation, label creation, and post-run scoring are outside this timer.
- Measure correction-inclusive time separately from submission until the human accepts the corrected record, including active correction work.
- Use the same timeout, clock source, and rounding convention for both systems.

### Failures and raw evidence

- Preserve errors, blank responses, invalid JSON, clarification requests, and timeouts as observable results. Do not replace them with inferred answers.
- Store raw inputs by approved reference or hash and raw outputs verbatim in a restricted evidence location. Use stable names containing the case-set version, system, run ID, attempt, and timestamp.
- Record product/model identifiers, code revision, configuration, endpoint or deployment class, prompt version, date/time, locale, and operator role for every run. Do not record secrets.

## Validity safeguards

Known threats include small or unrepresentative samples, synthetic-data bias, receipt and statement provenance, labeler error, changing hosted-model versions, unequal interface automation, differing OCR capabilities, file upload friction, context persistence, timing instrumentation, and correction effort that varies by operator. Report these limits with results rather than treating a single benchmark as a universal product ranking.

The protocol prohibits post-hoc edits to final cases, labels, prompts, scoring rules, retry criteria, or aggregate inclusion rules to improve either system's reported result. Any necessary amendment creates a new, dated benchmark version with the original retained.
