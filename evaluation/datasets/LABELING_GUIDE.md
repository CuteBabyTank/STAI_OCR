# Reconciliation Ground-Truth Labeling Guide

## Eligibility and independence

- A primary labeler may be a trained project member who understands the source
  documents, reconciliation terminology, and this guide.
- Every final case requires an independent check by another eligible person who
  did not create the primary label. The checker may see source documents and
  case instructions, but not Snag or Cowork output.
- An adjudicator resolves disagreements and records the decision and rationale.
  If agreement cannot be reached from the source evidence, label the relevant
  field unreadable or the match ambiguous rather than guessing.
- Labels must be created and frozen before final system runs. Never copy a
  value, match, confidence, or explanation from Snag or Cowork into ground
  truth.

## Required ground-truth record

Each case manifest and label record must include:

- `case_id`, source-document identifiers/hashes, and approved PII handling
  classification;
- statement transaction ID, transaction date, posting date when present,
  merchant, signed amount, and currency;
- receipt ID, receipt date, merchant, total, line items when legible, and source
  readability state;
- intended receipt-to-transaction pair(s), including explicit unmatched items;
- `match_status`, `discrepancy_type`, `requires_review`, and rationale/evidence
  references;
- normalization decisions, amount tolerance, timezone/date rule, labeler IDs or
  roles, independent-check status, and adjudication record when required.

Use `null` only when a field is genuinely unavailable in the source. Use a
separate unreadability reason rather than converting an unreadable value into a
plausible estimated value.

## Match-status definitions

| Status | Meaning |
| --- | --- |
| `exact_match` | One eligible receipt and one statement transaction agree after frozen normalization and allowed amount/date rules. |
| `merchant_variation_match` | The pair is valid, but source merchant strings differ in a documented normalized form. |
| `date_lag_match` | The pair is valid only when the frozen transaction-date versus posting-date rule is applied. |
| `amount_discrepancy` | The intended pair is known, but the amount differs outside the frozen tolerance. |
| `missing_receipt` | A statement transaction has no eligible receipt. |
| `unmatched_receipt` | A receipt has no eligible statement transaction for a non-cash/non-refund reason. |
| `cash_unmatched_receipt` | A valid receipt was paid in cash or another non-statement method. |
| `duplicate_receipt` | A receipt duplicates another source receipt and must not create another expense. |
| `duplicate_statement_transaction` | A transaction duplicates another statement transaction and must not create another purchase match. |
| `refund_or_negative` | A negative/refund transaction is the relevant financial event and requires the documented refund linkage or no-match outcome. |
| `ambiguous_review` | Source evidence leaves more than one plausible match; review is required. |
| `no_valid_match` | Candidate documents exist but none satisfies the frozen rules. |

## Discrepancies and special source conditions

Use `none` only for a valid clean match. Use `amount`, `date`, `merchant`,
`duplicate_receipt`, `duplicate_statement_transaction`, `missing_receipt`,
`cash_receipt`, `refund`, `unreadable_total`, `incorrect_receipt_arithmetic`,
`ambiguous_match`, `unsupported_total`, or `other` as applicable. Multiple
issues should be recorded as primary discrepancy plus evidence/rationale rather
than silently collapsing them into a clean match.

- **Unreadable fields:** retain the field as `null`, state the affected field and
  cause (for example blur, crop, or absent total), and mark review when a
  financial decision cannot be supported.
- **Dates:** record receipt date exactly as shown; record statement transaction
  date and posting date separately. Apply only the frozen case-set date-window
  rule, and identify which date supported a `date_lag_match`.
- **Merchant variants:** preserve raw source text and label a normalized merchant
  form using a published, case-set normalization rule. Do not normalize based on
  a system's suggestion.
- **Refunds and duplicates:** preserve sign, source IDs, and linkages. A refund
  is not relabeled as a positive expense; a duplicate is not counted as an
  independent purchase.
- **Incorrect arithmetic:** label printed line items, taxes, discounts, and
  stated total as observed; separately label the verified arithmetic outcome.

## Quality control and freeze

The independent checker verifies source hashes, required fields, pair identity,
status, and discrepancy decision. Resolve disagreements by source review, then
document the adjudication. Freeze labels, label-guide version, normalization
rules, and case manifest before final runs. Later corrections require a new
dated label version; do not overwrite the original ground truth.
