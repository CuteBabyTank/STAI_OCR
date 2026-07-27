# Reconciliation Benchmark Scoring Specification

This specification defines planned metrics only. It does not report or imply
final Snag or Cowork results. Score raw outputs against the frozen labels; score
human-corrected outputs separately where stated.

## Common conventions

- The unit is a frozen case and its labeled receipt/transaction entities.
- Normalize strings, currencies, dates, and monetary precision using rules
  frozen with the case set. Monetary equality uses the declared tolerance; do
  not choose a tolerance after viewing results.
- A predicted pair is correct only when its statement transaction ID and receipt
  ID equal the labeled pair. A correctly labeled no-match is not a positive pair
  but is scored in status/discrepancy metrics.
- Mark invalid schema, timeout, blank output, and unhandled exception as failure
  observations; do not silently omit them from denominators.

## Metrics

| Metric | Definition |
| --- | --- |
| Receipt-level exact match | Percentage of labeled receipts for which all required readable header fields, required line items, and labeled reconciliation status are correct under frozen normalization. Fields explicitly labeled unreadable are excluded from the required-readable set. |
| Field-level accuracy | Correct scored fields divided by all scored fields, reported per field and as micro- and macro-averages. A field is correct only if it equals the ground truth after frozen normalization. |
| Line-item accuracy | Maximum one-to-one matching of predicted and labeled readable line items using frozen description, quantity, and amount rules; report matched labeled items divided by labeled items, with precision and recall if extra predicted items occur. |
| Unsupported-total rate | Count of outputs that state a concrete receipt total unsupported by source evidence divided by receipts whose total is labeled unreadable, absent, or arithmetically unsupported. |
| Match precision | Correct predicted positive receipt–transaction pairs divided by all predicted positive pairs. |
| Match recall | Correct predicted positive pairs divided by all labeled positive pairs. |
| Match F1 | Harmonic mean of match precision and recall; report `0` when both are `0`. |
| Discrepancy-detection precision | Correctly predicted labeled discrepancy events divided by predicted discrepancy events. |
| Discrepancy-detection recall | Correctly predicted labeled discrepancy events divided by labeled discrepancy events. |
| Incorrect confident-match rate | Incorrect predicted positive pairs with confidence at or above the frozen threshold, or an equivalent explicit no-review assertion, divided by all predicted positive pairs. Freeze the threshold before final runs. |
| Review recall | Labeled cases requiring review that are predicted with `requires_review=true` divided by all labeled review-required cases. |
| False-review rate | Cases not labeled review-required that are predicted with `requires_review=true` divided by all labeled non-review cases. |
| Severe financial error count | Count of severe financial errors as defined below, reported by system and case. |
| Task-completion rate | Cases with a schema-valid observable output covering all required case transactions divided by all submitted cases. Technical failures and invalid output count as not completed. |
| Correction rate | Completed cases needing one or more human corrections divided by completed cases; report correction actions separately. |
| Correction-inclusive time | Elapsed time from submission through documented human acceptance of a corrected record, including active correction work; report separately from raw system time. |
| System-error rate | Cases with a terminal technical failure, timeout, unhandled error, or invalid export divided by all submitted cases. |

## Severe financial error

A severe financial error is any raw result that could materially misstate the
ledger by: (1) confidently matching a transaction to the wrong receipt and
marking it as not requiring review; (2) treating an amount discrepancy outside
the frozen tolerance as a clean match; (3) treating a refund/negative
transaction as a new positive expense; or (4) counting a labeled duplicate
receipt or duplicate statement transaction as a separate clean purchase. Count
each affected transaction once per system run, while retaining all applicable
error categories in evidence.

## Reporting rules

Report numerators and denominators with every percentage, plus case-level error
lists for severe errors and system failures. Stratify results by synthetic versus
redacted-real provenance and by primary challenge when samples permit. Do not
calculate, tune, or publish final metrics until the contract, labels, case
manifest, prompt, and scoring version are reviewed and frozen.
