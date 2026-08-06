import type { Receipt, Transaction } from "./types";
import { periodKey, type TopGranularity } from "./periodKey";

// Merges the transactions and receipts stores into one in/out total for the
// dashboard's top tiles, without double-counting a receipt that has already
// been posted into a transaction (transactions.receipt_id -> receipts.id).
export function computePeriodTotals(
  transactions: Transaction[],
  receipts: Receipt[],
  granularity: TopGranularity,
  now: Date = new Date()
): { inn: number; out: number } {
  const key = periodKey(granularity, now);
  const keyLen = key.length;

  const postedReceiptIds = new Set<number>();
  let inn = 0;
  let out = 0;
  for (const t of transactions) {
    if (t.receipt_id != null) postedReceiptIds.add(t.receipt_id);
    if (!t.occurred_at || t.occurred_at.slice(0, keyLen) !== key) continue;
    if (t.kind === "income") inn += t.amount;
    else if (t.kind === "expense") out += t.amount;
  }

  for (const r of receipts) {
    if (postedReceiptIds.has(r.id)) continue;
    if (!r.receipt_date || r.receipt_date.slice(0, keyLen) !== key) continue;
    out += r.total_amount || 0;
  }

  return { inn, out };
}
