"use client";
// Combined Receipts module: browse receipts and add new ones (upload or camera)
// from the same screen. The "Add receipts" button opens the OCR upload flow.
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import type { Receipt } from "../lib/types";
import { catMeta, fmtDate, money } from "../lib/format";
import ConfidenceBadge from "../components/ConfidenceBadge";
import ReceiptUpload from "../components/ReceiptUpload";
import { useRefresh } from "../lib/useRefresh";
import { Select } from "../components/ui";

// Sort options for the list. Each comparator returns the usual -1/0/1.
//
// Two rules every comparator honours, so the list never looks arbitrary:
//   * a missing value always sorts LAST, whichever direction is chosen — an
//     undated or unpriced receipt is not "the smallest", it is unknown;
//   * ties break by id descending, so equal rows keep a stable, newest-first
//     order instead of shuffling between renders.
type SortKey =
  | "date_desc" | "date_asc"
  | "amount_desc" | "amount_asc"
  | "vendor_asc" | "category_asc"
  | "confidence_asc" | "added_desc";

const SORTS: { key: SortKey; label: string }[] = [
  { key: "date_desc", label: "Date (newest first)" },
  { key: "date_asc", label: "Date (oldest first)" },
  { key: "amount_desc", label: "Amount (high to low)" },
  { key: "amount_asc", label: "Amount (low to high)" },
  { key: "vendor_asc", label: "Vendor (A–Z)" },
  { key: "category_asc", label: "Category (A–Z)" },
  { key: "confidence_asc", label: "Confidence (lowest first)" },
  { key: "added_desc", label: "Recently added" },
];

const byId = (a: Receipt, b: Receipt) => (b.id || 0) - (a.id || 0);

/** Compare two possibly-missing values, always sinking blanks to the bottom. */
function nullsLast<T>(
  a: T | null | undefined,
  b: T | null | undefined,
  cmp: (x: T, y: T) => number,
): number | null {
  const aMissing = a === null || a === undefined || a === "";
  const bMissing = b === null || b === undefined || b === "";
  if (aMissing && bMissing) return null;   // both blank -> fall through to tiebreak
  if (aMissing) return 1;
  if (bMissing) return -1;
  return cmp(a as T, b as T);
}

const COMPARATORS: Record<SortKey, (a: Receipt, b: Receipt) => number> = {
  date_desc: (a, b) => nullsLast(a.receipt_date, b.receipt_date, (x, y) => y.localeCompare(x)) ?? byId(a, b),
  date_asc: (a, b) => nullsLast(a.receipt_date, b.receipt_date, (x, y) => x.localeCompare(y)) ?? byId(a, b),
  amount_desc: (a, b) => nullsLast(a.total_amount, b.total_amount, (x, y) => y - x) ?? byId(a, b),
  amount_asc: (a, b) => nullsLast(a.total_amount, b.total_amount, (x, y) => x - y) ?? byId(a, b),
  vendor_asc: (a, b) =>
    nullsLast(a.vendor_name, b.vendor_name, (x, y) =>
      x.localeCompare(y, undefined, { sensitivity: "base" })) ?? byId(a, b),
  category_asc: (a, b) =>
    nullsLast(a.category, b.category, (x, y) => x.localeCompare(y)) ?? byId(a, b),
  // Lowest-confidence first: this is the "what should I check?" view, so the
  // reads the model was least sure about belong at the top.
  confidence_asc: (a, b) => nullsLast(a.confidence, b.confidence, (x, y) => x - y) ?? byId(a, b),
  added_desc: byId,
};

export default function ReceiptsPage() {
  const [receipts, setReceipts] = useState<Receipt[]>([]);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [sortKey, setSortKey] = useState<SortKey>("date_desc");

  const load = useCallback(() => {
    fetch("/api/receipts?limit=1000")
      .then((r) => r.json())
      .then((j) => setReceipts(j.receipts || []))
      .catch(() => setReceipts([]))
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => load(), [load]);
  // A background OCR run broadcasts "ledger:refresh" when it files receipts. That
  // can land long after the upload modal was closed, so the list has to pick it up
  // on its own rather than through an onDone callback that closed with the modal.
  useRefresh(load);

  const sorted = [...receipts].sort(COMPARATORS[sortKey]);

  return (
    <>
      <main>
        <header>
          <div>
            <h1>Receipts</h1>
            <p className="subhead">
              {receipts.length} receipt{receipts.length === 1 ? "" : "s"}
            </p>
          </div>
          <div className="header-actions rl-toolbar">
            <label className="rl-sort">
              <span className="rl-sort-label">Sort by</span>
              <Select
                value={sortKey}
                onChange={(e) => setSortKey(e.target.value as SortKey)}
              >
                {SORTS.map((s) => (
                  <option key={s.key} value={s.key}>{s.label}</option>
                ))}
              </Select>
            </label>
            <button className="btn-primary" onClick={() => setAdding(true)}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M12 5v14M5 12h14" strokeLinecap="round" /></svg>
              Add receipts
            </button>
          </div>
        </header>

        <div className="card">
          {loading ? (
            <p className="rl-empty">Loading…</p>
          ) : sorted.length === 0 ? (
            <p className="rl-empty">
              No receipts yet — click <strong>Add receipts</strong> to scan or photograph one.
            </p>
          ) : (
            <ul className="rl-list">
              {sorted.map((r) => (
                <li key={r.id}>
                  <Link href={`/receipts/${r.id}`} className="rl-row">
                    <div className="rl-icon">{catMeta(r.category).emoji}</div>
                    <div className="rl-body">
                      <div className="rl-merch">{r.vendor_name || "Unknown merchant"}</div>
                      <div className="rl-meta">
                        {r.category || "Other"} · {fmtDate(r.receipt_date)}
                        <ConfidenceBadge value={r.confidence} />
                      </div>
                    </div>
                    <div className="rl-amt num">{money(r.total_amount, r.currency)}</div>
                    <svg className="rl-chev" viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M9 6l6 6-6 6" /></svg>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      </main>

      {adding && <ReceiptUpload onClose={() => setAdding(false)} />}
    </>
  );
}
