"use client";
import { useMemo, useState } from "react";
import type { FieldConfidence, LineItem, Receipt } from "../lib/types";
import { catMeta, CONF_FIELD_LABELS, confMeta, fmtDate, money } from "../lib/format";
import ConfidenceBadge from "./ConfidenceBadge";

// A transaction row that expands to show its OCR'd line items (fetched lazily from
// the receipt-items endpoint that already exists) and a per-field confidence breakdown.
export default function TxnRow({
  r, isNew, onDelete,
}: { r: Receipt; isNew: boolean; onDelete: (id: number) => void }) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<LineItem[] | null>(null);
  const [loading, setLoading] = useState(false);

  // Parse the stored confidence breakdown (fields + per-item), if present.
  const fc = useMemo<FieldConfidence | null>(() => {
    try {
      return r.field_confidence ? JSON.parse(r.field_confidence) : null;
    } catch {
      return null;
    }
  }, [r.field_confidence]);

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

  const fieldEntries = fc?.fields ? Object.entries(fc.fields) : [];

  return (
    <li className={"txn expandable" + (isNew ? " new" : "") + (open ? " open" : "")}>
      <div className="txn-main" onClick={toggle} role="button" aria-expanded={open}>
        <div className="txn-icon">{catMeta(r.category).emoji}</div>
        <div className="txn-body">
          <div className="txn-merchant">{r.vendor_name || "Unknown merchant"}</div>
          <div className="txn-meta">
            {r.category || "Other"} · {fmtDate(r.receipt_date)}
            <ConfidenceBadge value={r.confidence} />
          </div>
        </div>
        <span className="txn-amt num">{money(r.total_amount, r.currency)}</span>
        <svg className="txn-chev" viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M6 9l6 6 6-6" /></svg>
        <button className="txn-del" title="Delete" onClick={(e) => { e.stopPropagation(); onDelete(r.id); }}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M6 6l12 12M18 6 6 18" /></svg>
        </button>
      </div>
      {open && (
        <div className="txn-items">
          {/* Measured read-confidence breakdown, straight from token logprobs. */}
          {fc && fc.overall != null && (
            <div className="conf-panel">
              <div className="conf-panel-head">
                <span>Read confidence</span>
                <ConfidenceBadge value={fc.overall} size="md" showLabel />
              </div>
              {fieldEntries.length > 0 && (
                <div className="conf-grid">
                  {fieldEntries.map(([k, v]) => (
                    <div key={k} className="conf-field">
                      <span className="cf-k">{CONF_FIELD_LABELS[k] || k}</span>
                      <ConfidenceBadge value={v} />
                    </div>
                  ))}
                </div>
              )}
              <p className="conf-note">
                Each score is the vision model’s average token probability for that value —
                a measured read of its own output, not a self-rating.
              </p>
            </div>
          )}

          {loading ? (
            <div className="items-loading">Reading items…</div>
          ) : items && items.length > 0 ? (
            <table className="items-table">
              <tbody>
                {items.map((it, i) => {
                  const itemConf = fc?.items?.[i]?.amount;
                  return (
                    <tr key={i}>
                      <td className="it-desc">
                        {it.description || "Item"}
                        {confMeta(itemConf) && <ConfidenceBadge value={itemConf} />}
                      </td>
                      <td className="it-qty num">{it.quantity ? `×${it.quantity}` : ""}</td>
                      <td className="it-amt num">{money(it.amount ?? (it.unit_price ?? 0), r.currency)}</td>
                    </tr>
                  );
                })}
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
