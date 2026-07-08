"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import type { Receipt } from "../lib/types";
import { catMeta, fmtDate, money } from "../lib/format";
import Sidebar from "../components/Sidebar";
import ConfidenceBadge from "../components/ConfidenceBadge";

export default function ReceiptsPage() {
  const [receipts, setReceipts] = useState<Receipt[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/api/receipts?limit=1000")
      .then((r) => r.json())
      .then((j) => setReceipts(j.receipts || []))
      .catch(() => setReceipts([]))
      .finally(() => setLoading(false));
  }, []);

  // Most-recent to oldest by receipt_date (undated last); tiebreak by id.
  const sorted = [...receipts].sort((a, b) => {
    const da = a.receipt_date || "";
    const db = b.receipt_date || "";
    if (da && db && da !== db) return db.localeCompare(da);
    if (da && !db) return -1;
    if (!da && db) return 1;
    return (b.id || 0) - (a.id || 0);
  });

  return (
    <div className="shell">
      <Sidebar />
      <main>
        <header>
          <div>
            <h1>Receipts</h1>
            <p className="subhead">
              {receipts.length} receipt{receipts.length === 1 ? "" : "s"} · most recent first
            </p>
          </div>
        </header>

        <div className="card">
          {loading ? (
            <p className="rl-empty">Loading…</p>
          ) : sorted.length === 0 ? (
            <p className="rl-empty">No receipts yet — scan one from the dashboard.</p>
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
    </div>
  );
}
