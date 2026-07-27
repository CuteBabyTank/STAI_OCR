# Ground-Truth Case Design

## Coverage matrix

Every final case must have source files, a case manifest entry, and independent human labels before either system's final output is viewed. Cases may cover more than one row, but the final manifest should identify a primary challenge.

| ID | Required challenge | Ground-truth decision needed | Pilot / development role | Final-evaluation role |
| --- | --- | --- | --- | --- |
| GT-01 | Exact match | Correct receipt–transaction pair and all key fields | Validate happy-path schema | Include |
| GT-02 | Merchant-name variation | Normalized merchant equivalence | Validate normalization | Include |
| GT-03 | Transaction date versus posting date | Match date and allowed posting lag | Validate date policy | Include |
| GT-04 | Missing receipt | Statement transaction has no eligible receipt | Validate no-match output | Include |
| GT-05 | Statement transaction without receipt | Explicit statement-side absence | Validate review/discrepancy behavior | Include |
| GT-06 | Cash receipt absent from statement | Receipt is legitimate but should not match a statement transaction | Validate receipt-side absence | Include |
| GT-07 | Unmatched receipt | Receipt lacks a valid statement counterpart for another reason | Validate no-match explanation | Include |
| GT-08 | Amount discrepancy | Pair identity plus labeled amount difference and tolerance | Validate discrepancy reporting | Include |
| GT-09 | Duplicate receipt | Duplicate source receipt identity and intended disposition | Validate duplicate handling | Include |
| GT-10 | Duplicate statement transaction | Duplicate transaction identity and intended disposition | Validate duplicate handling | Include |
| GT-11 | Multiple purchases from same merchant | One-to-one assignment among similar candidates | Validate pair selection | Include |
| GT-12 | Refund or negative transaction | Refund linkage and sign treatment | Validate negative amounts | Include |
| GT-13 | Blurry receipt | Readability status and what remains supportable | Validate abstention/review | Include |
| GT-14 | Cropped receipt | Missing field(s) and supported fields | Validate abstention/review | Include |
| GT-15 | Unsupported or unreadable total | Total is unavailable or not supportable | Validate unsupported-total metric | Include |
| GT-16 | Incorrect receipt arithmetic | Source arithmetic and correct treatment | Validate discrepancy/review | Include |
| GT-17 | Multiple plausible receipt matches | Candidate set and required ambiguity status | Validate review recall | Include |
| GT-18 | No valid match | All candidate receipts are invalid | Validate false-match avoidance | Include |

## Proposed case sets

### Pilot / development set

Use synthetic, fully documented cases to exercise every coverage row, validate file packaging, calibrate the fixed prompt, test the schema, and rehearse timing and raw-output collection. These cases are excluded from final metrics even if they are later run through both systems.

### Final evaluation set

Create a separate, frozen set of redacted or synthetic-but-realistically rendered receipt documents plus validated CSV transactions. Include every row above, deliberately include difficult no-match and ambiguity cases, and retain a case manifest with source hashes. Do not tune either system using this set.

### Optional redacted real-world subset

If permissions allow, a separately reported subset may contain redacted, consented personal or business documents. It requires the same independent labeling, source-hash, and freeze rules. Do not merge it with synthetic results unless provenance strata are reported separately.

## Feasible planning options

These are team planning options, not instructor-required sample sizes.

| Option | Proposed development / pilot cases | Proposed final cases | Manual labeling estimate | Execution estimate |
| --- | ---: | ---: | --- | --- |
| Minimum defensible | 12 | 30 | About 11–18 combined person-hours for initial labels plus independent checks, assuming 15–25 minutes per case package | About 3–5 hours per system for submission, export, logging, and allowed technical retries; correction work is measured separately |
| Stronger if time permits | 20 | 60 | About 20–33 combined person-hours under the same 15–25 minute assumption | About 6–10 hours per system for submission, export, logging, and allowed technical retries; correction work is measured separately |

The estimates exclude time spent creating redacted source documents, resolving hard label disagreements, building any new parser, and instructor review. They assume final cases contain manageable receipt/transaction bundles rather than full monthly statements.
