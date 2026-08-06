import type { Receipt, Transaction, TxnKind } from "./types";

export interface ActivityEntry {
  id: string;
  kind: TxnKind;
  title: string;
  subtitle: string;
  amount: number;
  date: string | null;
  // True for a chat-logged receipt with no linked transaction: it has no
  // account, so it's shown but can't be treated as a real ledger movement.
  isReceiptOnly: boolean;
}

// Folds unposted receipts into the transactions feed so a receipt logged from
// chat (log_spend, which touches no account) still shows up in "Recent
// transactions" — skipping any receipt already posted into a transaction
// (transactions.receipt_id -> receipts.id) so it isn't shown twice.
export function mergeRecentActivity(
  transactions: Transaction[],
  receipts: Receipt[],
  limit = 8
): ActivityEntry[] {
  const postedReceiptIds = new Set<number>();
  for (const t of transactions) {
    if (t.receipt_id != null) postedReceiptIds.add(t.receipt_id);
  }

  const fromTxns: ActivityEntry[] = transactions.map((t) => ({
    id: `txn-${t.id}`,
    kind: t.kind,
    title: t.note || t.category_name || (t.kind === "transfer" ? "Transfer" : "Transaction"),
    subtitle: t.account_name || "—",
    amount: t.amount,
    date: t.occurred_at,
    isReceiptOnly: false,
  }));

  const fromReceipts: ActivityEntry[] = receipts
    .filter((r) => !postedReceiptIds.has(r.id))
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
