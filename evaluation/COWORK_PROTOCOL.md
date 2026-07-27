# Claude Cowork Evaluation Protocol

## Purpose

This protocol collects Claude Cowork's observable reconciliation output under
the same frozen case package and common schema used for Snag. It does not inspect
or score Cowork's private reasoning trajectory.

## Fixed prompt

Use this prompt without content changes after the final set is frozen:

```text
You are reconciling receipt-derived expenses against the provided bank or credit-card statement transactions. Use only the supplied case files and metadata. For each statement transaction and relevant receipt, return one JSON object that conforms exactly to the attached reconciliation output schema. Preserve unknown or unreadable values as null, identify ambiguity with requires_review, and do not invent unsupported totals, merchants, dates, or matches. Do not use information from outside the case package. Return JSON only.
```

Attach the frozen schema file, case metadata, receipt document(s), and the same
validated CSV statement representation supplied to Snag. Do not attach ground
truth labels, another system's result, or developer/pilot examples that reveal a
case answer.

## Session and run procedure

- Use a new Cowork project/session for each declared benchmark run so prior-case
  context cannot influence a later run. Record the project/session identifier
  only if it does not disclose personal information.
- Record Cowork product name, accessible version/build information, plan if
  relevant, date/time/timezone, browser/client, operator role, fixed-prompt
  version, attached-file hashes, and any available model identifier. Record
  unavailable fields as unavailable rather than inferring them.
- Start timing immediately after all frozen files and the fixed prompt are
  submitted. Stop at the first exportable schema-valid response, terminal error,
  or benchmark timeout.
- Export or copy the observable response verbatim before validation or human
  correction. Preserve attachments by approved hash/reference, not by copying
  unredacted documents into public reports.

## Clarifications, retries, and intervention

- Do not answer Cowork clarification questions or add explanatory prompts during
  a scored run. Preserve the request as output; it is scored under the frozen
  completion and review rules.
- Allow one retry only for a documented technical problem such as a failed upload
  or platform outage. Use the same session policy, files, and prompt; retain both
  attempts and the retry reason.
- Do not retry an incomplete, unfavorable, or low-confidence answer.
- Do not edit raw Cowork output. Any required human correction is a separately
  timed, logged record using the common schema's `manual_corrections` field.

## Evidence naming and failures

Name raw outputs using:

```text
cowork_<case-set-version>_<run-id>_attempt-<n>_<timestamp>_raw.json
```

If Cowork returns prose, malformed JSON, no response, an error, or a timeout,
preserve it verbatim with a companion metadata record. Do not reconstruct a
successful result. Store raw evidence in the approved restricted location.

## Repeated-run policy

Proposed policy for review: conduct one primary run per final case and, if time
permits, three independent fresh-session runs per system on the same frozen final
set. Report each run and a predeclared aggregate; do not choose the best run.
The team must freeze whether repeated runs are feasible before Stage 3.

## Fairness limitations

Cowork may have different file-upload flows, OCR capabilities, session behavior,
automation options, product updates, and observable timing overhead than Snag.
These differences are part of the practical comparison but limit causal claims
about an individual model. The evaluation assesses task outputs only, not hidden
reasoning, tokens, tools, or private trajectories.
