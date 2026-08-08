import type { Receipt, Transaction, TxnKind } from "./types";
import { periodKey, type TopGranularity } from "./periodKey";

export interface ActivityEntry {
  id: string;
  kind: TxnKind;
  title: string;
  subtitle: string;
  amount: number;
  date: string | null;
  isReceiptOnly: boolean;
}

export function mergeRecentActivity(
  transactions: Transaction[],
  receipts: Receipt[],
  limit = 8,
  granularity?: TopGranularity,
  now: Date = new Date()
): ActivityEntry[] {
  const key = granularity ? periodKey(granularity, now) : null;
  const keyLen = key ? key.length : 0;
  const inPeriod = (date: string | null | undefined) =>
    !key || (!!date && date.slice(0, keyLen) === key);

  const postedReceiptIds = new Set<number>();
  for (const t of transactions) {
    if (t.receipt_id != null) postedReceiptIds.add(t.receipt_id);
  }

  const fromTxns: ActivityEntry[] = transactions
    .filter((t) => inPeriod(t.occurred_at))
    .map((t) => ({
      id: `txn-${t.id}`,
      kind: t.kind,
      title: t.note || t.category_name || (t.kind === "transfer" ? "Transfer" : "Transaction"),
      subtitle: t.account_name || "—",
      amount: t.amount,
      date: t.occurred_at,
      isReceiptOnly: false,
    }));

  const fromReceipts: ActivityEntry[] = receipts
    .filter((r) => !postedReceiptIds.has(r.id) && inPeriod(r.receipt_date))
    .map((r) => ({
      id: `receipt-${r.id}`,
      kind: "expense" as const,
      title: r.vendor_name || "Receipt",
      subtitle: "Logged · no account",
      amount: r.total_amount || 0,
      date: r.receipt_date,
      isReceiptOnly: true,
    }));

  return [...fromTxns, ...fromReceipts]
    .sort((a, b) => (b.date || "").localeCompare(a.date || ""))
    .slice(0, limit);
}
