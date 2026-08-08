/**
 * "Recent transactions" on the dashboard only ever read the `transactions` table,
 * so a receipt logged from chat (via `log_spend`, which deliberately touches no
 * account — see periodTotals.test.ts) never showed up there, even though the
 * Spending overview and the top out/in tiles both already count it.
 *
 * `mergeRecentActivity` folds unposted receipts into the same feed as read-only
 * entries, without duplicating one that has already been posted into a real
 * transaction (transactions.receipt_id -> receipts.id) — that spend is already
 * represented by the transaction row.
 */
import { describe, expect, it } from "vitest";

import { mergeRecentActivity } from "./recentActivity";
import type { Receipt, Transaction } from "./types";

function txn(overrides: Partial<Transaction>): Transaction {
  return {
    id: 1,
    kind: "expense",
    amount: 0,
    account_id: null,
    to_account_id: null,
    category_id: null,
    note: null,
    occurred_at: null,
    fee: 0,
    receipt_id: null,
    template_id: null,
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

describe("mergeRecentActivity", () => {
  it("includes both a transaction and an unposted receipt, most recent first", () => {
    const txns = [
      txn({ id: 1, note: "TGI fridays", account_name: "BDO", amount: 10000, occurred_at: "2026-08-01" }),
    ];
    const receipts = [
      receipt({ id: 13, vendor_name: "uniqlo", total_amount: 2500, receipt_date: "2026-08-06" }),
    ];

    const entries = mergeRecentActivity(txns, receipts);

    expect(entries.map((e) => e.title)).toEqual(["uniqlo", "TGI fridays"]);
  });

  it("marks a receipt-only entry so it can be distinguished from a real transaction", () => {
    const receipts = [receipt({ id: 13, vendor_name: "uniqlo", total_amount: 2500, receipt_date: "2026-08-06" })];

    const [entry] = mergeRecentActivity([], receipts);

    expect(entry.isReceiptOnly).toBe(true);
    expect(entry.kind).toBe("expense");
  });

  it("excludes a receipt that has already been posted into a transaction", () => {
    const txns = [
      txn({ id: 5, note: "TGI Fridays", amount: 10000, occurred_at: "2026-08-06", receipt_id: 12 }),
    ];
    const receipts = [
      receipt({ id: 12, vendor_name: "TGI Fridays", total_amount: 10000, receipt_date: "2026-08-06" }),
    ];

    const entries = mergeRecentActivity(txns, receipts);

    expect(entries).toHaveLength(1);
    expect(entries[0].id).toBe("txn-5");
  });

  it("limits the result to the requested count", () => {
    const txns = Array.from({ length: 10 }, (_, i) =>
      txn({ id: i, occurred_at: `2026-08-${String(i + 1).padStart(2, "0")}` })
    );

    expect(mergeRecentActivity(txns, [], 3)).toHaveLength(3);
  });
});

const now = new Date(2026, 7, 6); // 6 Aug 2026 local

describe("mergeRecentActivity period filter", () => {
  it("month mode keeps only current-month rows", () => {
    const txns = [
      txn({ id: 1, note: "TGI fridays", account_name: "BDO", amount: 10000, occurred_at: "2026-08-01" }),
      txn({ id: 2, note: "old", account_name: "BDO", amount: 100, occurred_at: "2026-06-15" }),
    ];
    const receipts = [
      receipt({ id: 13, vendor_name: "uniqlo", total_amount: 2500, receipt_date: "2026-08-06" }),
      receipt({ id: 14, vendor_name: "Pepper Lunch", total_amount: 545, receipt_date: "2026-06-26" }),
    ];

    const entries = mergeRecentActivity(txns, receipts, 8, "month", now);

    expect(entries.map((e) => e.title)).toEqual(["uniqlo", "TGI fridays"]);
  });

  it("year mode keeps all months of the current year", () => {
    const txns = [
      txn({ id: 1, note: "Aug", occurred_at: "2026-08-01" }),
      txn({ id: 2, note: "Jun", occurred_at: "2026-06-15" }),
      txn({ id: 3, note: "last year", occurred_at: "2025-12-01" }),
    ];

    const entries = mergeRecentActivity(txns, [], 8, "year", now);

    expect(entries.map((e) => e.title)).toEqual(["Aug", "Jun"]);
  });

  it("applies limit after filtering", () => {
    const txns = Array.from({ length: 10 }, (_, i) =>
      txn({
        id: i,
        note: `d${i}`,
        occurred_at: `2026-08-${String(i + 1).padStart(2, "0")}`,
      })
    );
    // one out-of-period row that would otherwise compete for the limit
    txns.push(txn({ id: 99, note: "jun", occurred_at: "2026-06-01" }));

    const entries = mergeRecentActivity(txns, [], 3, "month", now);

    expect(entries).toHaveLength(3);
    expect(entries.every((e) => (e.date || "").startsWith("2026-08"))).toBe(true);
    expect(entries.map((e) => e.title)).not.toContain("jun");
  });

  it("returns empty when nothing matches the period", () => {
    const txns = [txn({ id: 1, note: "jun", occurred_at: "2026-06-01" })];
    expect(mergeRecentActivity(txns, [], 8, "month", now)).toEqual([]);
  });
});
