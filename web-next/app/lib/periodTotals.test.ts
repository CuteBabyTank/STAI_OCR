/**
 * The dashboard's "This month/year out/in" tiles must reflect the same spend the
 * Spending overview below it shows. That overview is driven by the `receipts`
 * table (OCR'd and chat-logged entries); the tiles were driven only by the
 * `transactions` table. A receipt that hasn't been posted into a transaction
 * (e.g. a chat-logged `log_spend` receipt, which never gets posted) was invisible
 * up top even though it's counted in "Expenses" right below.
 *
 * `computePeriodTotals` merges both stores without double-counting: a receipt
 * that HAS been posted (there exists a transaction with `receipt_id` pointing at
 * it) is skipped, because its amount is already present via that transaction.
 */
import { describe, expect, it } from "vitest";

import { computePeriodTotals } from "./periodTotals";
import type { Receipt, Transaction } from "./types";

const now = new Date(2026, 7, 6); // 6 Aug 2026 local

function txn(overrides: Partial<Transaction>): Transaction {
  return {
    id: 1,
    kind: "expense",
    amount: 0,
    account_id: null,
    account_name: null,
    to_account_id: null,
    category_id: null,
    category_name: null,
    note: null,
    occurred_at: null,
    fee: 0,
    receipt_id: null,
    created_at: null,
    ...overrides,
  } as Transaction;
}

function receipt(overrides: Partial<Receipt>): Receipt {
  return {
    id: 1,
    vendor_name: null,
    category: null,
    total_amount: 0,
    currency: null,
    receipt_date: null,
    source_file: null,
    ...overrides,
  } as Receipt;
}

describe("computePeriodTotals", () => {
  it("sums expense and income transactions within the current month", () => {
    const txns = [
      txn({ id: 1, kind: "expense", amount: 100, occurred_at: "2026-08-06T00:00:00" }),
      txn({ id: 2, kind: "income", amount: 40, occurred_at: "2026-08-01T00:00:00" }),
      txn({ id: 3, kind: "expense", amount: 999, occurred_at: "2026-07-31T00:00:00" }), // outside month
    ];
    const totals = computePeriodTotals(txns, [], "month", now);
    expect(totals).toEqual({ inn: 40, out: 100 });
  });

  it("adds an unposted receipt's total into out", () => {
    const receipts = [
      receipt({ id: 10, total_amount: 2500, receipt_date: "2026-08-06" }),
    ];
    const totals = computePeriodTotals([], receipts, "month", now);
    expect(totals.out).toBe(2500);
  });

  it("does not double-count a receipt that has already been posted as a transaction", () => {
    const txns = [
      txn({ id: 1, kind: "expense", amount: 10000, occurred_at: "2026-08-06T00:00:00", receipt_id: 9 }),
    ];
    const receipts = [
      receipt({ id: 9, total_amount: 10000, receipt_date: "2026-08-06" }),
    ];
    const totals = computePeriodTotals(txns, receipts, "month", now);
    expect(totals.out).toBe(10000);
  });

  it("excludes receipts dated outside the selected period", () => {
    const receipts = [
      receipt({ id: 10, total_amount: 2500, receipt_date: "2026-07-06" }),
    ];
    const totals = computePeriodTotals([], receipts, "month", now);
    expect(totals.out).toBe(0);
  });

  it("scopes to the whole year when granularity is year", () => {
    const receipts = [
      receipt({ id: 10, total_amount: 2500, receipt_date: "2026-03-04" }),
      receipt({ id: 11, total_amount: 500, receipt_date: "2025-12-31" }), // outside year
    ];
    const totals = computePeriodTotals([], receipts, "year", now);
    expect(totals.out).toBe(2500);
  });
});
