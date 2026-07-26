# Snag Agentic-Evaluation Task Breakdown

**Purpose:** Practical handoff for planning and implementing Snag's evaluation work  
**Project:** Snag / STAI_OCR integrated receipt-processing and personal-finance platform  
**Status:** Planning document; proposed tasks and thresholds are not achieved results  
**Source basis:** Updated Snag system report and the July 25 evaluation-session summary  

---

## 1. Instructions for the AI or teammate using this file

Use this document as a starting brief, then inspect the actual repository before changing code.

1. Verify every referenced module, function, route, table, trace, and test against the current repository.
2. Preserve existing working tests and application behavior.
3. Do not assume that Snag uses LangGraph or consists of multiple independent agents. The current report documents SQL, RAG, and ReAct capabilities, but does not establish LangGraph usage.
4. Do not add an authentication requirement to evaluation paths. The current system has no user-account/authentication layer.
5. Do not describe Quick Chat as an LLM feature. It is a deterministic, rule-based parser.
6. Do not claim that the submitted Docker configuration is fully offline. It points to a shared remote Ollama endpoint by default; local/offline operation requires an override.
7. Record the exact model names and environment used for every evaluation run. README, code, and Docker Compose contain different model defaults.
8. Do not invent test counts, repeated-run counts, pass thresholds, savings, accuracy, or customer outcomes.
9. Label any newly selected sample size or threshold as **proposed by the team**, not as an instructor requirement.
10. Keep receipt-level exact match separate from field-level accuracy. A receipt can fail exact match because of one wrong field while most other fields remain correct.

Before implementing anything, produce a short repository-audit note that identifies:

- Actual test framework and test directories
- Actual agent orchestration and routing implementation
- Existing MLflow traces and fields
- Available receipt samples and ground truth
- Existing finance fixtures or seed data
- Whether Ragas, `sqlglot`, or equivalent libraries are already installed
- Commands that currently run the app and tests
- Any mismatch between this breakdown and the current code

---

## 2. What appears established from the class session

The following conclusions are reasonably supported by the meeting summary:

- Evaluation is a non-negotiable, first-class capstone artifact.
- The instructor organized agentic evaluation into:
  1. Unit or component evaluation
  2. Trajectory or observable-pipeline evaluation
  3. End-to-end task evaluation
- A ground-truth or gold-standard evaluation dataset is expected.
- RAG evaluation should examine retrieval quality and grounded answer quality.
- Tool calls, routing, skipped safeguards, retries, loops, and state transitions are useful trajectory evidence.
- EDA is supplementary storytelling for the evaluation dataset, not the primary evaluation.
- Notebook-based reporting, visualizations, versioning, repeated runs, latency/cost tracking, LLM-as-a-judge, and human review were discussed as useful practices.

### Items not yet established

Do not present the following as requirements until confirmed using the transcript or instructor:

- A minimum of 50 test cases
- Exactly 5 or 10 trajectory examples
- Exactly 10 repeated runs
- A 10% human-review sample
- A required 0.80 Ragas threshold
- Any 100% accuracy or success requirement
- Ragas as the only acceptable RAG evaluation tool
- `sqlglot` as the only acceptable SQL evaluation tool
- LangGraph as a required orchestration framework
- A required notebook format
- Any minimum capstone passing score

---

## 3. Current Snag system scope

Snag is an integrated receipt-processing and personal-finance platform sharing one FastAPI backend and SQLite database.

### Receipt-processing layer

- Image, batch, and PDF receipt processing
- Merchant, TIN, address, receipt number, date, tax, payment, and total extraction
- Line-item description, quantity, unit-price, and amount extraction
- Token-logprob-based field confidence
- Deterministic cleanup and payment-field reconciliation
- Receipt arithmetic reconciliation
- Explicit review and disambiguation flags
- Persistent receipt and line-item ledger
- Receipt embedding and semantic search
- Receipt-to-finance posting

### Agent layer

- Read-only text-to-SQL questions
- Receipt-grounded RAG questions with receipt citations
- Streaming ReAct routing between SQL and receipt search
- Pre-loop disambiguation
- Maximum-step and repeated-tool-call guards
- MLflow traces for extraction, SQL, RAG, and ReAct calls

### Personal-finance layer

- Accounts, balances, transfers, and net worth
- Manual expense and income transactions
- Rule-based Quick Chat transaction drafts
- Categories, subcategories, tags, and templates
- Budget plans
- Recurring transactions and installments
- Goals, debts, and receivables
- Transaction history, statistics, and upcoming obligations
- JSON backup and restore

### Known limitations relevant to evaluation

- The personal-finance layer is implemented but not comparatively validated.
- The tested receipt deployment reportedly produced at least one wrong field on every tested receipt. This means 0% **receipt-level exact match for that test set**, not 0% field-level accuracy.
- Historical development-model results must not be attributed to the current deployment automatically.
- Model defaults differ across README, code, and Docker Compose.
- Docker Compose uses a shared remote Ollama endpoint by default.
- There is no authenticated cloud synchronization.
- Finance persistence depends on the documented imported-session/manual JSON backup model; it is not equivalent to mature cloud sync.
- “No API fee” does not mean zero compute, hosting, electricity, storage, maintenance, or correction cost.

---

## 4. Evaluation objective

The evaluation should answer:

> How reliably does Snag transform receipt or manually entered financial information into consistent ledger records and grounded answers, and where in the observable pipeline do failures occur?

This is deliberately narrower and more defensible than claiming:

- Perfect receipt extraction
- Guaranteed financial correctness
- Superior accuracy over competitors
- Proven time or money savings
- Production readiness

---

## 5. Required workstreams at a glance

| ID | Workstream | Main output | Priority | Depends on |
|---|---|---|---|---|
| W0 | Requirements and repository audit | Verified scope and evaluation inventory | First | Current repository |
| W1 | Evaluation dataset and ground truth | Versioned cases, labels, and fixtures | Critical | W0 |
| W2 | Layer 1 component evaluations | Automated unit/component results | Critical | W0–W1 |
| W3 | Layer 2 trajectory evaluation | Observable traces and path checks | Critical | W0–W2 |
| W4 | Layer 3 end-to-end evaluation | User-job completion results | Critical | W1–W3 |
| W5 | RAG, SQL, and question evaluation | Retrieval, execution, grounding results | Critical | W1–W3 |
| W6 | Performance and consistency | Latency, resource/cost units, repeated runs | Recommended | Stable W2–W5 |
| W7 | EDA and failure analysis | Dataset coverage and failure visuals | Recommended | W1 and results |
| W8 | Evaluation notebook and presentation | Submission-ready evidence narrative | Critical | W1–W7 |

---

# Workstream Details

## W0 — Confirm requirements and audit the repository

### Goal

Establish what the instructor actually required and what the current Snag repository actually implements.

### Tasks

- [ ] Recheck the transcript for direct evidence about:
  - The three evaluation layers
  - Ground-truth data
  - Ragas
  - Repeated runs
  - EDA
  - Latency, tokens, and cost
  - Notebook reporting
  - Human evaluation
- [ ] Record timestamps for anything labeled “required.”
- [ ] Inspect the repository and list existing:
  - Tests
  - Fixtures and sample receipts
  - MLflow traces
  - SQL/RAG/ReAct logs
  - Evaluation scripts
  - Installed evaluation libraries
- [ ] Freeze an evaluation configuration:
  - Commit hash
  - Docker image/configuration
  - `OLLAMA_HOST`
  - Vision model
  - Agent model
  - Embedding model
  - Relevant environment variables
- [ ] Identify which historical receipt data includes verified ground truth.

### Deliverables

- `evaluation/REQUIREMENTS_AUDIT.md`
- `evaluation/CONFIGURATION.md`
- Repository inventory table

### Definition of done

- Every supposed instructor requirement has evidence or is relabeled as a team recommendation.
- The exact tested deployment configuration can be reproduced.
- No task depends on an assumed LangGraph or authentication layer.

---

## W1 — Build the evaluation dataset and ground truth

### Goal

Create the answer key used across unit, trajectory, and end-to-end evaluations.

### Important design rule

Ground truth does not always mean a single “perfect written answer.”

Depending on the case, ground truth may be:

- Verified receipt fields
- Verified line-item tuples
- Expected reconciliation status
- Expected review reasons
- Expected transaction draft
- Expected database state
- Expected SQL result
- Allowed SQL structure or constraints
- Relevant receipt IDs
- Expected tool selection
- Required or prohibited trajectory events
- Expected task outcome

### Proposed case families

| Prefix | Case family | Example ground truth |
|---|---|---|
| `REC` | Receipt extraction | Verified headers and line items |
| `REV` | Reconciliation/review | Expected mismatch and review reasons |
| `PST` | Receipt posting | Expected transaction and receipt linkage |
| `QCK` | Quick Chat | Parsed draft fields |
| `FIN` | Finance calculations | Expected balances, budget state, net worth |
| `SQL` | SQL questions | Expected result rows/values and query constraints |
| `RAG` | Receipt search/questions | Relevant receipt IDs and grounded answer facts |
| `RCT` | ReAct routing | Expected tools, order constraints, and final facts |
| `BAK` | Backup/restore | Expected records and relationships after restore |
| `E2E` | Complete user job | Completion criteria and required state |

### Recommended case schema

```json
{
  "case_id": "REC-001",
  "layer": ["unit", "end_to_end"],
  "module": "receipt_extraction",
  "description": "Clean single-page Philippine receipt",
  "input_path": "fixtures/receipts/REC-001.jpg",
  "tags": ["clean", "php", "single_page"],
  "difficulty": "basic",
  "ground_truth": {},
  "expected_tools": [],
  "required_events": [],
  "prohibited_events": [],
  "expected_database_state": {},
  "metrics": [],
  "notes": ""
}
```

### Dataset coverage to consider

#### Receipts

- [ ] Clean and high-resolution
- [ ] Blurry, rotated, crumpled, or partially cropped
- [ ] Long receipts
- [ ] PDF and multipage PDF
- [ ] Batch upload
- [ ] PHP currency
- [ ] Mixed English/Filipino descriptions
- [ ] Discounts, VAT, VAT-exempt, cash, and change
- [ ] Repeated legitimate items
- [ ] Summary lines incorrectly resembling items
- [ ] Arithmetic inconsistencies
- [ ] Missing total or missing items
- [ ] Duplicate receipt attempt
- [ ] Unsupported file or oversized input

#### Quick Chat

- [ ] Standard expense
- [ ] Income using `+`
- [ ] `k` amount shorthand
- [ ] Relative dates
- [ ] Explicit accounts
- [ ] Categories
- [ ] Transfers
- [ ] Ambiguous or incomplete text
- [ ] Invalid amount/date/account

#### SQL/RAG/ReAct questions

- [ ] Simple totals
- [ ] Date-range questions
- [ ] Category/vendor comparisons
- [ ] Questions requiring line-item details
- [ ] Explicit receipt-number questions
- [ ] Ambiguous “recent receipt” questions
- [ ] Questions answerable through SQL
- [ ] Questions answerable through receipt search
- [ ] Out-of-scope questions
- [ ] Empty-ledger questions
- [ ] Questions with no supporting receipt

#### Finance integration

- [ ] Expense/income/transfer effects
- [ ] Transfer cannot target the same account
- [ ] Receipt posting creates one linked transaction
- [ ] Reposting does not create an unintended duplicate
- [ ] Budget and history reflect the same transaction
- [ ] Goal/debt/receivable activity updates linked records
- [ ] Recurring and installment payments create expected transactions
- [ ] Archived or excluded accounts behave correctly
- [ ] Backup and restore retain relationships

### Sample-size rule

The number of cases is **to be decided by the team or confirmed with the instructor**. Do not label `50+`, `10 runs`, or any other number as required without evidence.

Start with a coverage matrix first. Select the final count based on:

- Available verified receipts
- Number of distinct workflows
- Failure modes
- Time available for manual labeling
- Compute and runtime
- Instructor guidance

### Deliverables

- `evaluation/datasets/cases.json` or equivalent
- Receipt fixtures and manually verified labels
- Finance database fixtures
- Dataset schema and labeling guide
- Coverage matrix
- Dataset version/changelog

### Definition of done

- Every case has a unique ID and reproducible input.
- Every metric has the necessary ground truth.
- Development cases are separated from final reporting cases.
- The dataset contains both normal and failure cases.
- No final result is manually edited after viewing the system output.

---

## W2 — Layer 1: component evaluations

### Goal

Test individual functions and tools independently so failures can be localized.

### W2-A Receipt extraction and safeguards

- [ ] Input validation for supported types, file size, and empty files
- [ ] Image preprocessing and PDF page expansion
- [ ] JSON coercion and schema validation
- [ ] Header-field extraction
- [ ] Line-item extraction
- [ ] Numeric-field coercion
- [ ] Summary-line remapping
- [ ] Duplicate-item handling
- [ ] Payment-field repair
- [ ] Reconciliation tolerance behavior
- [ ] Review/disambiguation reasons
- [ ] Field-confidence availability and value-equality gating
- [ ] Receipt save and line-item linkage
- [ ] Per-page failure isolation in batch processing

### W2-B Personal-finance deterministic logic

- [ ] Account balance calculations
- [ ] Net-worth calculation
- [ ] Expense and income creation
- [ ] Transfer validation and effects
- [ ] Budget aggregation and carry-forward
- [ ] Templates
- [ ] Recurring schedule advancement
- [ ] Installment payments
- [ ] Goal activity
- [ ] Debt activity
- [ ] Receivable activity
- [ ] Upcoming-obligation aggregation
- [ ] Transaction history/statistics consistency

### W2-C Rule-based Quick Chat

- [ ] Amount parsing
- [ ] `k` shorthand
- [ ] Expense/income/transfer classification
- [ ] Relative-date parsing
- [ ] Account matching
- [ ] Category matching
- [ ] Missing or ambiguous field handling
- [ ] Server/client parser consistency, if both are in scope

### W2-D SQL, RAG, and ReAct tools

- [ ] SQL validator accepts read-only `SELECT`
- [ ] SQL validator rejects forbidden verbs and multiple statements
- [ ] Generated SQL executes against the intended scoped database
- [ ] SQL execution returns the correct result—not merely similar query text
- [ ] Retrieval returns the relevant receipt IDs
- [ ] Explicit receipt references remain scoped
- [ ] ReAct selects SQL for numeric/aggregate questions
- [ ] ReAct selects receipt search for receipt-content questions
- [ ] Ambiguous recent-receipt questions trigger clarification
- [ ] Repeated tool calls and step limits are handled

### W2-E Receipt posting and backup/restore

- [ ] Posting creates the expected finance transaction
- [ ] Transaction links back to the correct `receipt_id`
- [ ] Amount, date, category, account, and currency are preserved
- [ ] Duplicate posting behavior is tested
- [ ] Backup contains all intended finance records
- [ ] Restore recreates records and relationships
- [ ] Malformed backup behavior is tested
- [ ] Backup/restore does not claim authenticated cloud synchronization

### Core metrics

| Metric | Unit |
|---|---|
| Receipt-level exact match | Correct receipts / receipts tested |
| Field-level accuracy | Correct expected fields / expected fields |
| Line-item accuracy | Correct matched item fields or tuples / expected |
| Review recall | Incorrect/problematic receipts flagged / problematic receipts |
| False-review rate | Correct receipts incorrectly flagged / correct receipts |
| Quick Chat field accuracy | Correct parsed fields / expected parsed fields |
| SQL execution accuracy | Correct result cases / SQL cases |
| Retrieval recall | Relevant receipts retrieved / relevant receipts |
| Backup completeness | Intended records present / intended records |
| Restore success | Successful verified restores / restore attempts |

### Deliverables

- Automated component tests
- Machine-readable result file
- Summary table by module and case category
- Failure log with case IDs

### Definition of done

- Tests can be rerun from a documented command.
- Failures identify the component and case ID.
- Exact match is not confused with field accuracy.
- Proposed thresholds are labeled and approved before use.

---

## W3 — Layer 2: trajectory and observable-pipeline evaluation

### Goal

Verify that Snag follows an acceptable observable path, not merely that it produces a plausible final answer.

### Do not evaluate hidden chain-of-thought

Use observable evidence such as:

- API calls
- Tool names
- MLflow events
- ReAct `action`, `observation`, `clarify`, `error`, and `final` events
- Database writes
- Review flags
- Retry counts
- Step counts
- Retrieved receipt IDs
- Generated and executed SQL

### Trajectories to test

#### Receipt pipeline

`Upload → validate → preprocess/PDF expansion → OCR → post-process → schema validation → confidence → reconcile/review → save/index`

Checks:

- [ ] Invalid input stops before OCR.
- [ ] Failed page does not stop unrelated batch pages.
- [ ] Reconciliation happens before a receipt is treated as verified.
- [ ] Review reasons are emitted when expected.
- [ ] Saved receipt and line items match the accepted extraction.

#### Receipt-to-finance pipeline

`Saved receipt → user review/correction → post → transaction → account/budget/history/statistics`

Checks:

- [ ] Posting occurs only through the actual supported workflow.
- [ ] One receipt maps to the intended finance transaction.
- [ ] The same transaction propagates consistently to dependent modules.
- [ ] The receipt remains traceable from the finance record.

#### Question-answering pipeline

`Question → disambiguation/routing → SQL or receipt search → observation → grounded final answer`

Checks:

- [ ] Correct route selected.
- [ ] Receipt scope respected.
- [ ] No repeated identical tool loop.
- [ ] Maximum-step behavior produces a controlled final/error.
- [ ] Final answer agrees with the tool observation.
- [ ] Receipt-search answers cite the supporting receipt.

#### Quick Chat pipeline

`Text → rule-based parse → draft → user acceptance/correction → transaction → dependent views`

Checks:

- [ ] Quick Chat is recorded as deterministic parsing.
- [ ] The draft is not silently treated as verified user intent.
- [ ] Accepted/corrected values are what enter the ledger.
- [ ] All dependent modules show the same transaction effect.

#### Backup/restore pipeline

`Export → preserve file → import → validation → reconstructed state → consistency check`

Checks:

- [ ] Intended objects and relationship links survive.
- [ ] Malformed input is rejected or handled visibly.
- [ ] Restore behavior is not described as authenticated cloud sync.

### Suggested trajectory-case format

```json
{
  "case_id": "RCT-001",
  "input": "How much did I spend on groceries last month?",
  "allowed_tools": ["sql_ledger"],
  "required_events": ["start", "action", "observation", "final"],
  "prohibited_events": ["clarify", "error"],
  "max_tool_calls": null,
  "expected_result": {
    "type": "numeric",
    "source": "ledger_fixture"
  }
}
```

`max_tool_calls` and other thresholds must be set from the actual design or team proposal, not copied from an unrelated lecture example.

### Metrics

| Metric | Definition |
|---|---|
| Routing accuracy | Cases sent to the expected tool / routing cases |
| Required-step compliance | Cases containing all required observable steps / cases |
| Prohibited-step rate | Cases containing a prohibited event / cases |
| Loop rate | Cases exceeding the approved repeated-call rule / cases |
| Clarification accuracy | Ambiguous cases correctly clarified / ambiguous cases |
| Observation-final consistency | Finals supported by recorded observations / answered cases |
| Trajectory completion | Cases reaching an allowed terminal state / cases |

### Deliverables

- Trace collector/exporter
- Expected-trajectory case definitions
- Actual-versus-expected trace comparison
- One successful and one failed trajectory visualization
- Failure taxonomy

### Definition of done

- Evaluation uses real observable events from Snag.
- No LangGraph-specific artifact is required unless the repository actually uses LangGraph.
- A correct final answer does not hide a prohibited or looping path.

---

## W4 — Layer 3: end-to-end user-job evaluation

### Goal

Measure whether a user can complete Snag's intended jobs with correct final state and manageable review/correction effort.

### E2E jobs

| ID | User job | Completion condition |
|---|---|---|
| `E2E-REC` | Digitize and verify a receipt | Verified record matches ground truth after any measured correction |
| `E2E-PST` | Post a receipt to finance | Correct linked transaction appears once and dependent views agree |
| `E2E-QCK` | Record a transaction through Quick Chat | Intended transaction is accepted/corrected and stored accurately |
| `E2E-MAN` | Record a manual transaction | Correct transaction and dependent balances are produced |
| `E2E-ASK` | Ask a spending question | Correct answer supported by the ledger/receipt evidence |
| `E2E-BUD` | Track a budget or obligation | Correct transaction affects the expected budget/upcoming view |
| `E2E-BAK` | Back up and restore finance data | Intended records and links are recovered consistently |

### Metrics

- Task-completion rate: completed jobs / attempted jobs
- Correction-inclusive time: minutes per verified receipt or transaction
- Correction rate: cases requiring correction / cases attempted
- Receipt-to-finance posting success: correct linked posts / post attempts
- Cross-module consistency: expected dependent values correct / checked dependent values
- Question accuracy: correct answers / evaluated questions
- Backup completeness: recovered intended records / intended records
- Restore success: verified successful restores / restore attempts
- Error-recovery rate: failures ending in a controlled recoverable state / injected failures

### Required reporting units

Use explicit units:

- Seconds per model/tool call
- Minutes per verified receipt
- Minutes per verified transaction
- Tokens per question, when available
- PHP per user per month, PHP per task, or PHP per compute hour when estimating cost
- Receipts per test batch
- Transactions per fixture
- Correct cases / total evaluated cases

Do not convert “no API fee” into zero total cost.

### Deliverables

- E2E runner or documented manual protocol
- Pre/post database snapshots
- Task-level result CSV/JSON
- Correction and timing sheet
- Failure evidence

### Definition of done

- Completion conditions are written before running the test.
- Both successful and failed jobs remain in the results.
- Receipt correction time is included.
- No result is framed as customer time savings without a measured comparison baseline.

---

## W5 — SQL, RAG, ReAct, and question-answering evaluation

### SQL evaluation

Use more than literal SQL-string matching.

Recommended checks:

- [ ] Valid read-only SQL
- [ ] No prohibited operations
- [ ] Correct execution result
- [ ] Correct receipt scope
- [ ] Correct handling of empty results
- [ ] Correct numeric/date/category semantics
- [ ] Structural comparison as supplementary evidence, if useful

Primary metric:

> SQL execution accuracy = cases returning the expected result ÷ SQL cases

### Retrieval evaluation

Define relevant receipt IDs for each retrieval question.

- Context precision: how much retrieved evidence is relevant
- Context recall: how much required relevant evidence was retrieved
- Scope leakage rate: questions retrieving receipts outside the allowed scope

### Answer evaluation

Evaluate:

- Correctness against ledger or receipt ground truth
- Faithfulness to retrieved evidence
- Relevance to the question
- Presence and correctness of receipt citations when applicable

Ragas may be used if it fits the current pipeline and dependency constraints. It does not replace:

- SQL execution checks
- Receipt-field evaluation
- Trajectory checks
- Deterministic database comparisons
- Human examination of ambiguous cases

### Mixed-ledger questions

Include questions spanning:

- OCR-generated receipt transactions
- Manually entered transactions
- Quick Chat transactions
- Transfers
- Goals/debts/receivables

Measure whether SQL/RAG answers remain correct across these sources.

### Deliverables

- Question dataset
- Expected SQL results/relevant receipt IDs
- Generated SQL and execution results
- Retrieved evidence
- Final answers and citations
- Metric table by question type

---

## W6 — Performance, resource use, and repeated-run consistency

### Goal

Determine whether the evaluated configuration is stable and operationally practical.

### Measurements

- End-to-end latency per task
- OCR latency per page
- SQL/RAG/ReAct latency per question
- Token usage, where logged
- Tool-call count
- Retry count
- Error count
- Batch throughput in pages per minute
- Correction time in minutes per verified receipt/transaction
- Compute/hosting/electricity estimate with explicit units

### Repeated runs

The number of repetitions is **to be confirmed or proposed**. Do not automatically use 10 because it appeared in an example.

For nondeterministic components, report:

- Mean
- Median
- Minimum and maximum
- Standard deviation or range
- Success frequency
- Route consistency

For deterministic components such as Quick Chat and finance calculations, repeated identical runs should normally produce identical results; failures should be investigated as state or fixture problems.

### Deliverables

- Performance result table
- Configuration metadata attached to every run
- Consistency summary
- Cost worksheet with explicit units and assumptions

---

## W7 — EDA and failure analysis

### Status

Recommended reporting enhancement, not a substitute for evaluation.

### Useful EDA

Use only charts that explain test coverage:

1. Cases per module/workflow
2. Receipt cases by difficulty or image condition
3. Question cases by expected route: SQL, RAG, ReAct clarification
4. Cases by normal, boundary, ambiguous, and failure category
5. Required fields or line-item counts per receipt
6. Test coverage by finance module
7. If repeated runs are used, repetitions per nondeterministic case

Avoid:

- Pie charts of speculative USD costs before measuring costs
- Latency charts labeled as dataset EDA
- Token-length plots unless answer length is genuinely relevant
- Decorative charts that do not establish coverage or explain failures

### Failure taxonomy

Suggested categories:

- OCR transcription error
- Header-field mapping error
- Line-item omission/addition
- Deterministic repair error
- Reconciliation/review miss
- False review
- Posting/linkage failure
- Quick Chat parse error
- Finance calculation inconsistency
- SQL syntax/semantic/execution error
- Wrong route/tool
- Retrieval miss or scope leak
- Unsupported final answer
- Loop/retry exhaustion
- Backup/restore loss or relationship corruption
- Configuration/environment failure

### Deliverables

- Small EDA section
- Failure counts by category
- Representative case studies with case IDs
- Known limitations and unresolved failures

---

## W8 — Evaluation notebook and capstone evidence

### Recommended notebook structure

1. **Proof point and evaluation questions**
2. **System boundary and tested configuration**
3. **Architecture and observable workflows**
4. **Ground-truth dataset construction**
5. **Dataset coverage/EDA**
6. **Layer 1 component results**
7. **Layer 2 trajectory results**
8. **Layer 3 E2E results**
9. **SQL/RAG/ReAct evaluation**
10. **Latency, resource use, and consistency**
11. **Failure analysis**
12. **Limitations and threats to validity**
13. **Conclusions tied only to measured evidence**

### Minimum visual evidence

- Three-layer evaluation diagram mapped to Snag
- Dataset coverage table
- Component result matrix
- Successful trajectory
- Failed/recovered trajectory
- E2E job result table
- Question accuracy/retrieval table
- Failure distribution
- Tested-configuration card

### Claims to avoid

- “Snag achieves perfect receipt accuracy.”
- “Snag has 0% field accuracy.”
- “Snag is more accurate than competitors.”
- “Snag saves users time or money.”
- “Snag operates fully offline by default.”
- “Quick Chat is powered by an LLM.”
- “Ragas proves that the entire agent is correct.”
- “A correct final answer proves the trajectory was correct.”
- “The historical development result is the current deployment result.”
- “No API fee means no operating cost.”
- “Manual JSON backup is equivalent to authenticated cloud sync.”
- “The personal-finance layer has been validated with users.”

---

# 6. Suggested task allocation

The following allocation follows the module ownership documented in the current system report. Confirm availability and rebalance based on workload.

| Owner/module lane | Suggested evaluation responsibilities |
|---|---|
| Nathaniel — Chat UI, API, Docker | Freeze deployment configuration; API/E2E runner; frontend timing/correction capture; batch/PDF path; backup/restore workflow; environment documentation |
| Clarence — Prompting, structured output, guardrails | Receipt labels; extraction schema; field/line-item metrics; guardrail cases; deterministic post-processing and reconciliation tests; review-reason evaluation |
| Fraser — RAG, memory, tool use, disambiguation | Retrieval ground truth; context precision/recall; citation checks; disambiguation cases; RAG answer evaluation; ambiguous and scope-isolation cases |
| Aaron — SQL, ReAct, MLflow | SQL execution evaluation; trajectory-event extraction; routing/loop checks; mixed-ledger questions; MLflow result export; notebook integration and result synthesis |
| Shared/unassigned finance lane | Quick Chat; accounts/transfers; budgets; goals; debts; receivables; recurring/installments; cross-module consistency; receipt posting; finance fixtures |

### Recommended shared review

- At least one person other than the implementer should verify each ground-truth label.
- Receipt labels should be checked against the image, not copied from model output.
- SQL question answers should be verified directly against a frozen database fixture.
- Backup/restore verification should compare record content and relationships, not just file existence.
- All members should agree on proposed pass thresholds before the final run.

---

# 7. Suggested repository structure

This is a recommendation, not an instructor-mandated structure.

```text
evaluation/
├── README.md
├── REQUIREMENTS_AUDIT.md
├── CONFIGURATION.md
├── datasets/
│   ├── schema.json
│   ├── cases.json
│   ├── labeling_guide.md
│   └── changelog.md
├── fixtures/
│   ├── receipts/
│   ├── finance/
│   └── backups/
├── tests/
│   ├── unit/
│   ├── trajectory/
│   └── e2e/
├── results/
│   ├── raw/
│   ├── processed/
│   └── failures/
├── notebooks/
│   └── snag_evaluation.ipynb
└── reports/
    └── evaluation_summary.md
```

If the repository already has an established test layout, extend it instead of creating a competing structure.

---

# 8. Execution order

## Phase 1 — Establish the baseline

1. Complete W0 repository and requirements audit.
2. Freeze the tested configuration.
3. Inventory available receipt and finance fixtures.
4. Agree on the evaluation questions and evidence needed.

## Phase 2 — Build ground truth

5. Define the dataset schema.
6. Label receipt fields and line items.
7. Build finance database fixtures.
8. Define expected SQL results, relevant receipt IDs, and allowed trajectories.
9. Review labels independently.

## Phase 3 — Implement component evaluation

10. Complete deterministic and receipt Layer 1 tests.
11. Complete Quick Chat and finance Layer 1 tests.
12. Complete SQL, retrieval, and route-selection tests.
13. Save machine-readable results.

## Phase 4 — Add trajectory evidence

14. Export observable MLflow/ReAct/API/database events.
15. Compare actual paths with expected paths.
16. Add loop, retry, clarification, and scope checks.
17. Produce successful and failed trajectory examples.

## Phase 5 — Run E2E evaluation

18. Run complete receipt-to-ledger and receipt-to-finance jobs.
19. Run manual and Quick Chat finance jobs.
20. Run mixed-ledger spending questions.
21. Run backup/restore jobs.
22. Record time, corrections, final state, and failures.

## Phase 6 — Analyze and present

23. Compute metrics without deleting failures.
24. Perform the small coverage EDA.
25. Create failure taxonomy and case studies.
26. Build the notebook and presentation visuals.
27. Audit every conclusion against the recorded evidence.

---

# 9. Immediate next-step checklist

The group can start with these actions:

- [ ] Send this file and the updated system report to the implementing AI.
- [ ] Ask the AI for a repository audit before allowing code changes.
- [ ] Confirm the instructor's actual required artifacts from the transcript.
- [ ] Decide who owns the currently unassigned finance-evaluation lane.
- [ ] Inventory all receipt images and existing labels.
- [ ] Create one frozen SQLite finance fixture.
- [ ] Draft the evaluation-case schema.
- [ ] Choose a small pilot set covering every major workstream.
- [ ] Run the pilot to expose instrumentation and labeling problems.
- [ ] Only then decide final sample sizes, repetitions, and proposed thresholds.

---

# 10. Questions to ask the instructor

1. Is using all three layers required, or is the expected mix determined by the capstone's proof point?
2. Is there a minimum number of evaluation cases?
3. Are repeated runs required, and if so, how many?
4. Is Ragas required for every RAG component, or may equivalent retrieval and grounding metrics be implemented directly?
5. Does the instructor require an evaluation notebook, or is it only recommended?
6. Are latency, token usage, and cost required final metrics?
7. Is EDA expected in the submission or only recommended for presentation?
8. Is LLM-as-a-judge expected, or is deterministic/human ground-truth scoring sufficient?
9. Are there required acceptance thresholds?
10. What evidence must be shown for trajectory evaluation: logs, traces, diagrams, or all three?

---

# 11. Final definition of done

The evaluation work is complete when:

- [ ] The exact tested configuration is recorded and reproducible.
- [ ] Ground truth is independently verified and versioned.
- [ ] Unit, trajectory, and E2E evidence is produced for the selected Snag workflows.
- [ ] Receipt exact match, field accuracy, and line-item accuracy are reported separately.
- [ ] Quick Chat is evaluated as a rule-based parser.
- [ ] SQL answers are checked by execution result.
- [ ] RAG answers are checked for retrieval quality, correctness, faithfulness, and citations.
- [ ] Receipt posting and cross-module finance consistency are evaluated.
- [ ] Backup completeness and restore success are evaluated.
- [ ] Failures remain visible and are categorized.
- [ ] Timing, resource, and cost figures use explicit units.
- [ ] Proposed thresholds are distinguished from achieved results.
- [ ] Historical development results are separated from the tested configuration.
- [ ] No claim exceeds the evidence collected.

