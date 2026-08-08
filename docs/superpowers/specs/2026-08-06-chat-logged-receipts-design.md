# Chat-logged receipts + month navigation on the spending overview

**Date:** 2026-08-06
**Status:** approved, ready to implement

## Problem

Two things are broken from the user's point of view.

**1. Chat-logged spending never reaches the Spending overview.** The app keeps two
stores with a deliberate one-way bridge:

- `receipts` (OCR'd) feeds *Spending overview*, `/summary`, `/analytics`
- `transactions` (finance ledger) feeds balances, net worth, *This month out/in*, History
- `POST /receipts/{id}/post` turns a receipt **into** a transaction

The assistant's `add_expense` writes a **transaction only**, so it can never appear in
the receipt-driven Spending overview.

**2. `add_expense` refuses the user's natural phrasing.** It hard-requires an account
(`core.py:4180`) because *"picking one would move real money out of an account they did
not choose."* So `"i spent 10k on food in TGI Fridays"` — no account named — is refused
outright. On a ledger with zero accounts it refuses regardless of phrasing.

**3. The Spending overview is stuck on one period.** `page.tsx:47` calls
`/api/analytics` with no parameters, so it always renders the default period. The
endpoint already accepts `granularity`/`year`/`month`, and a `PeriodControl` component
with ◀ ▶ arrows already exists and is used on `/scan`.

## Decisions

| Question | Decision |
|---|---|
| What does chat logging write? | A **temp receipt only** — no account, no balance change |
| How permanent is "temp"? | **Permanent**, marked as manually logged. "Temp" means "not from a scan", not "expires" |
| Which panels do the arrows drive? | **Spending overview block only** — stat tiles, Cashflow, Top vendors |
| How is it implemented? | **New `log_spend` tool**; `add_expense` is not modified |

Rejected: folding a temp-receipt fallback into `add_expense`. It would convert a
deliberate refusal into a silent write and require rewriting ~10 safety tests that
assert nothing is written (`test_an_unknown_account_is_not_silently_defaulted`,
`test_an_unknown_account_records_nothing_and_lists_the_real_ones`).

## Data model

One new column on `receipts`, via the existing additive-migration list at `core.py:1753`:

```
("entry_source", "TEXT")   # "chat" = logged via the assistant; NULL = scanned
```

A temp receipt is an **ordinary receipt row**. That is the core of the design: it means
`analytics_summary`, `expense_summary`, `/receipts` and semantic search pick it up with
no changes to any of them.

From `"i spent 10k on food in TGI Fridays"`:

| field | value |
|---|---|
| `vendor_name` | `TGI Fridays` |
| `total_amount`, `subtotal` | `10000.0` |
| `category` | `Food` (validated through `categorize()`'s taxonomy) |
| `receipt_date` | today, or a parsed relative date |
| `entry_source` | `chat` |
| `account_id` | `NULL` — touches no balance |
| `confidence` | `NULL` — no OCR, so no confidence badge |
| `source_file` | `NULL` |

`confidence: NULL` already renders correctly — receipts 3 and 7 in the current ledger
have no badge.

## Backend

**`core.log_manual_receipt(vendor, amount, category, date, currency)`** builds a
`ReceiptData` and delegates to the existing `save_receipt()`. No new persistence path.

**`_tool_log_spend`** reuses `_guard_amount`, `_guard_category` and `_guard_duplicate`,
and adds a `vendor=` key to `_parse_expense_input`. It deliberately has **no account
guard** — that is what makes the user's phrasing work. Registered in the tool table
(`core.py:4836`) and added to `_WRITE_TOOLS` (`core.py:4052`) so existing
write-confirmation machinery covers it.

**Router rule** in the ReAct prompt: *user named an account → `add_expense`; no account
named → `log_spend`*, plus few-shot examples beside those at `core.py:3765`.

`add_expense` is **not modified**.

## Frontend

`PeriodControl` gains a `monthOnly` prop that hides the All-time/Month/Year segment and
keeps the ◀ label ▶ nav. Reused rather than reimplemented so the year-rollover and
min/max bounds logic (`PeriodControl.tsx:14-28`) is not duplicated.

`page.tsx` gains `period` state, renders the control in the Spending overview
`card-head`, and refetches `/api/analytics?granularity=month&year=…&month=…`. No API
change. The top "This month out/in" cards and Recent transactions are untouched so
their labels stay accurate.

## Testing

- `evaluation/tests/test_w2l_log_spend.py`: amount-required guard; works with **zero
  accounts**; duplicate guard; category resolution; and the test that proves the
  feature — a receipt logged via `log_spend` appears in `analytics_summary()` for its
  month.
- A regression test that `add_expense` **still refuses** without an account, so the new
  tool cannot quietly erode that guarantee.
- Update `ACT-003` in `trajectory_cases.json` from "expect no write tool" to "expect
  `log_spend`", and note the change in the evaluation docs. This is a deliberate spec
  change: the assistant will ask "which account?" noticeably less often.
- Web: `npm test`, plus a live check of the arrows against the running stack.

## Out of scope

No manual-entry UI form, no editing a temp receipt into a scanned one, no auto-expiry.
Attaching a temp receipt to an account later via the existing post-to-ledger bridge
behaves exactly as a scanned receipt does today — counted once in receipt views, once
in ledger views. No new double-counting.
