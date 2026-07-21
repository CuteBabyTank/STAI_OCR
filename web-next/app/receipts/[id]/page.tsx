"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import type { LineItem } from "../../lib/types";
import { money } from "../../lib/format";
import { Select } from "../../components/ui";

type Row = Record<string, any>;

// Editable header fields, shown as table rows (top to bottom).
const FIELDS: { key: string; label: string; type: "text" | "number" | "date" | "category" }[] = [
  { key: "vendor_name", label: "Vendor", type: "text" },
  { key: "vendor_tin", label: "Tax ID", type: "text" },
  { key: "vendor_address", label: "Address", type: "text" },
  { key: "receipt_number", label: "Receipt no.", type: "text" },
  { key: "receipt_date", label: "Date", type: "date" },
  { key: "category", label: "Category", type: "category" },
  { key: "currency", label: "Currency", type: "text" },
  { key: "subtotal", label: "Subtotal", type: "number" },
  { key: "vatable_sales", label: "Taxable sales", type: "number" },
  { key: "vat_amount", label: "Tax / VAT", type: "number" },
  { key: "discount", label: "Discount", type: "number" },
  { key: "total_amount", label: "Total", type: "number" },
  { key: "cash", label: "Cash", type: "number" },
  { key: "change", label: "Change", type: "number" },
];
const CATEGORIES = ["Food", "Shopping", "Health", "Other"];

export default function ReceiptDetail() {
  const params = useParams();
  const id = params?.id as string;

  const [receipt, setReceipt] = useState<Row | null>(null);
  const [items, setItems] = useState<LineItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Row>({});
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState("");
  const [savedFlash, setSavedFlash] = useState(false);

  const load = () => {
    setLoading(true);
    fetch(`/api/receipts/${id}`)
      .then(async (r) => { if (!r.ok) throw new Error("not found"); return r.json(); })
      .then((j) => { setReceipt(j.receipt); setItems(j.items || []); })
      .catch(() => setReceipt(null))
      .finally(() => setLoading(false));
  };
  useEffect(() => { if (id) load(); /* eslint-disable-next-line */ }, [id]);

  const startEdit = () => { setDraft({ ...receipt }); setErr(""); setEditing(true); };
  const cancel = () => { setEditing(false); setErr(""); };

  const save = async () => {
    setSaving(true); setErr("");
    try {
      const body: Row = {};
      for (const f of FIELDS) body[f.key] = draft[f.key];
      const res = await fetch(`/api/receipts/${id}`, {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(`Save failed (${res.status})`);
      const j = await res.json();
      setReceipt(j.receipt);
      setEditing(false);
      setSavedFlash(true);
      window.setTimeout(() => setSavedFlash(false), 2000);
    } catch (e: any) {
      setErr(e?.message || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const displayVal = (f: (typeof FIELDS)[number], v: any) => {
    if (v === null || v === undefined || v === "") return "—";
    if (f.type === "number") return money(v, receipt?.currency);
    return String(v);
  };

  return (
    <>
      <main>
        <header>
          <div>
            <Link href="/receipts" className="back-link">← Back to receipts</Link>
            <h1>{receipt?.vendor_name || (loading ? "Loading…" : "Receipt")}</h1>
            <p className="subhead">
              Receipt #{id}
              {receipt?.receipt_date ? ` · ${receipt.receipt_date}` : ""}
              {savedFlash ? " · ✓ saved" : ""}
            </p>
          </div>
          <div className="header-actions">
            {!editing ? (
              <button className="btn-primary" onClick={startEdit} disabled={!receipt}>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M12 20h9" /><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z" /></svg>
                Edit
              </button>
            ) : (
              <>
                <button className="btn-ghost" onClick={cancel} disabled={saving}>Cancel</button>
                <button className="btn-primary" onClick={save} disabled={saving}>
                  {saving ? "Saving…" : "Save changes"}
                </button>
              </>
            )}
          </div>
        </header>

        {loading ? (
          <div className="card"><p className="rl-empty">Loading…</p></div>
        ) : !receipt ? (
          <div className="card"><p className="rl-empty">Receipt not found.</p></div>
        ) : (
          <>
            {err && <div className="edit-err">{err}</div>}

            <div className="card">
              <div className="card-head"><p className="card-title">Values</p></div>
              <table className="val-table">
                <tbody>
                  {FIELDS.map((f) => (
                    <tr key={f.key}>
                      <td className="vt-label">{f.label}</td>
                      <td className="vt-value">
                        {!editing ? (
                          <span className={f.type === "number" ? "num" : ""}>{displayVal(f, receipt[f.key])}</span>
                        ) : f.type === "category" ? (
                          <Select
                            value={draft[f.key] ?? "Other"}
                            onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })}
                          >
                            {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
                          </Select>
                        ) : (
                          <input
                            className="vt-input"
                            type={f.type === "number" ? "number" : "text"}
                            step={f.type === "number" ? "0.01" : undefined}
                            placeholder={f.type === "date" ? "YYYY-MM-DD" : ""}
                            value={draft[f.key] ?? ""}
                            onChange={(e) =>
                              setDraft({ ...draft, [f.key]: e.target.value === "" ? null : e.target.value })
                            }
                          />
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {items.length > 0 && (
              <div className="card">
                <div className="card-head"><p className="card-title">Line items</p></div>
                <table className="val-table items">
                  <thead>
                    <tr>
                      <th>Description</th>
                      <th className="num">Qty</th>
                      <th className="num">Amount</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((it, i) => (
                      <tr key={i}>
                        <td>{it.description || "Item"}</td>
                        <td className="num">{it.quantity ?? ""}</td>
                        <td className="num">{money(it.amount ?? it.unit_price ?? 0, receipt.currency)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </main>
    </>
  );
}
