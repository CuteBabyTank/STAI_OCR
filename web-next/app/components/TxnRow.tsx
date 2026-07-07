"use client";
import { useState } from "react";
import type { LineItem, Receipt } from "../lib/types";
import { catMeta, fmtDate, money } from "../lib/format";

// A transaction row that expands to show its OCR'd line items (fetched lazily from
// the receipt-items endpoint that already exists).
export default function TxnRow({
  r, isNew, onDelete,
}: { r: Receipt; isNew: boolean; onDelete: (id: number) => void }) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<LineItem[] | null>(null);
  const [loading, setLoading] = useState(false);

  const toggle = async () => {
    const next = !open;
    setOpen(next);
    if (next && items === null) {
      setLoading(true);
      try {
        const j = await fetch(`/api/receipts/${r.id}/items`).then((x) => x.json());
        setItems(j.items || []);
      } catch {
        setItems([]);
      } finally {
        setLoading(false);
      }
    }
  };

  return (
    <li className={"txn expandable" + (isNew ? " new" : "") + (open ? " open" : "")}>
      <div className="txn-main" onClick={toggle} role="button" aria-expanded={open}>
        <div className="txn-icon">{catMeta(r.category).emoji}</div>
        <div className="txn-body">
          <div className="txn-merchant">{r.vendor_name || "Unknown merchant"}</div>
          <div className="txn-meta">{r.category || "Other"} · {fmtDate(r.receipt_date)}</div>
        </div>
        <span className="txn-amt num">{money(r.total_amount, r.currency)}</span>
        <svg className="txn-chev" viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M6 9l6 6 6-6" /></svg>
        <button className="txn-del" title="Delete" onClick={(e) => { e.stopPropagation(); onDelete(r.id); }}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M6 6l12 12M18 6 6 18" /></svg>
        </button>
      </div>
      {open && (
        <div className="txn-items">
          {loading ? (
            <div className="items-loading">Reading items…</div>
          ) : items && items.length > 0 ? (
            <table className="items-table">
              <tbody>
                {items.map((it, i) => (
                  <tr key={i}>
                    <td className="it-desc">{it.description || "Item"}</td>
                    <td className="it-qty num">{it.quantity ? `×${it.quantity}` : ""}</td>
                    <td className="it-amt num">{money(it.amount ?? (it.unit_price ?? 0), r.currency)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="items-loading">No itemized detail for this receipt.</div>
          )}
        </div>
      )}
    </li>
  );
}
