# Dashboard analytics + income + budgets — design

**Date:** 2026-07-07
**Status:** approved (build-all authorized by user)

## Goal

Turn the receipt-OCR dashboard from a "what I spent by category" view into a
personal **cashflow** view: money in → money out → net saved, with trends,
comparisons, budgets, and drilldown. Personal-finance framing.

## Scope (all approved this round)

1. **Spend-/cashflow-over-time trend** — monthly chart.
2. **Month-over-month deltas** — on the headline stat tiles.
3. **Budgets + progress** — monthly limit per category, progress bars, over-budget alert.
4. **Top vendors** — "where my money goes" bar list.
5. **Receipt drilldown** — expand a transaction to its line items (endpoint already exists).
6. **Income tracking** — one-off quick-add **and** a recurring monthly salary.

## Charting

Use **Recharts** (user choice). Feed it the app's existing CSS-variable palette so
it stays theme-aware. Validated color decisions (via dataviz `validate_palette.js`):
- Cashflow: **income = `--positive` green**, **expense = `--accent` indigo**, **net = ink line**. Passes all checks. Single currency axis only (no dual-axis).
- Donut keeps the app's existing category colors; its labeled legend supplies the
  secondary encoding the validator asks for.

## Backend (core.py + api.py)

New tables (idempotent `init_db()`-style, matching existing migration pattern):

```sql
CREATE TABLE IF NOT EXISTS income (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT, amount REAL, currency TEXT,
  income_date TEXT,          -- ISO date; for recurring = start month anchor
  recurring INTEGER DEFAULT 0,  -- 1 = monthly salary template
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS budgets (
  category TEXT PRIMARY KEY,
  monthly_limit REAL,
  currency TEXT
);
```

Recurring income is stored as a single `recurring=1` template row and **expanded**
across months (from its anchor month → the latest active month) at aggregation
time — no duplicate rows.

New/updated endpoints:
- `GET /income` / `POST /income` {source, amount, currency, date, recurring} / `DELETE /income/{id}`
- `GET /budgets` / `PUT /budgets` {category, monthly_limit, currency}  (upsert)
- `GET /analytics` — one payload for the new visuals:
  ```
  { months: [{month, expense, income, net}],
    mom: {expense:{current,prev,pct}, income:{...}, net:{...}, label},
    top_vendors: [{vendor, total, count}],
    budgets: [{category, limit, spent, pct, currency}],   // latest active month
    income_total, expense_total, net_total, currency }
  ```
  MoM anchors to the **latest month with activity** vs the prior month (robust to
  sparse data), not literal today, and returns a `label` (e.g. "vs May").

Existing `/summary`, `/receipts`, `/receipts/{id}/items`, `/extract`, `/ask` unchanged.

## Frontend (web-next)

Add `recharts` dep. Refactor `page.tsx` (already ~590 lines) by extracting shared
helpers and each new visual into its own client component so the page stays an
orchestrator:

- `app/lib/format.ts` — money/date/category helpers (moved out of page.tsx).
- `app/components/StatTiles.tsx` — Net / Income / Expenses / Receipts, each with MoM arrow.
- `app/components/CashflowChart.tsx` — Recharts monthly income vs expense bars + net line.
- `app/components/CategoryDonut.tsx` — existing donut, extracted.
- `app/components/TopVendors.tsx` — Recharts horizontal bars.
- `app/components/BudgetsCard.tsx` — progress bars + inline edit of limits.
- `app/components/IncomePanel.tsx` — quick-add form + recurring-salary setting.
- `app/components/TxnRow.tsx` — transaction row with click-to-expand line items.

New sidebar action + "＋ Income" affordance beside "Add". Budgets and income both
call the new endpoints and then `refresh()` (which now also refetches `/analytics`).

## Non-goals

- OCR of income/payslip documents.
- Multi-currency conversion (still surface a mixed-currency warning as today).
- Editing OCR'd receipt fields.

## Testing / verification

- Backend: hit new endpoints with curl; confirm tables created, recurring income
  expands across months, budgets upsert, `/analytics` shape.
- Frontend: build + run, add income (one-off + recurring), set a budget, confirm
  charts render in light & dark, expand a receipt's line items.
