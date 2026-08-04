"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import type { Account, LineItem } from "../../lib/types";
import { money } from "../../lib/format";
import { Select } from "../../components/ui";

type Row = Record<string, any>;

// Editable header fields, shown as table rows (top to bottom).
const FIELDS: {
  key: string;
  label: string;
  type: "text" | "number" | "date" | "category" | "account";
}[] = [
  { key: "vendor_name", label: "Vendor", type: "text" },
  { key: "vendor_tin", label: "Tax ID", type: "text" },
  { key: "vendor_address", label: "Address", type: "text" },
  { key: "receipt_number", label: "Receipt no.", type: "text" },
  { key: "receipt_date", label: "Date", type: "date" },
  { key: "category", label: "Category", type: "category" },
  { key: "account_id", label: "Charged to", type: "account" },
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
  const [accounts, setAccounts] = useState<Account[]>([]);
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

  // Accounts populate the "Charged to" picker. Loaded once, independently of the
  // receipt: a failure here must not blank the page, it just leaves the picker
  // empty (and the stored account_id still renders as a plain id).
  useEffect(() => {
    fetch("/api/accounts")
      .then((r) => r.json())
      .then((j) => setAccounts(j.accounts || []))
      .catch(() => setAccounts([]));
  }, []);

  // The stored verdict on how completely the item block was transcribed
  // (receipts.items_status, written by extraction.assess_item_coverage). Null on
  // receipts saved before that column existed, which render as they always did.
  const coverage = (() => {
    const status = receipt?.items_status as string | undefined;
    if (!status) return null;
    const printed = receipt?.items_printed_count as number | null | undefined;
    const counted = typeof printed === "number" ? ` of ${printed} printed` : "";
    switch (status) {
      case "complete":
        return { tone: "", label: "All lines captured",
                 hint: `${items.length} line${items.length === 1 ? "" : "s"}${counted}, and they account for the receipt's own total.` };
      case "incomplete":
        return { tone: "warn", label: "Lines may be missing",
                 hint: `Only ${items.length} line${items.length === 1 ? "" : "s"}${counted} were read, or they don't add up to the printed total. Check the receipt image before trusting this list.` };
      case "empty":
        return { tone: "warn", label: "No lines captured",
                 hint: "The item block was not read at all." };
      default:
        return { tone: "muted", label: "Not verified",
                 hint: "The receipt printed no subtotal or total to check these lines against, so we can't confirm they are all here." };
    }
  })();

  const accountName = (accountId: any) => {
    if (accountId === null || accountId === undefined || accountId === "") return null;
    const a = accounts.find((x) => String(x.id) === String(accountId));
    return a ? a.name : `Account #${accountId}`;
  };

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
      if (!res.ok) {
        // The API explains *why* a save was rejected (e.g. an account that no
        // longer exists); showing "Save failed (422)" instead would hide it.
        const body = await res.json().catch(() => null);
        throw new Error(body?.detail || `Save failed (${res.status})`);
      }
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
    // Checked before the empty-value guard: an unassigned account reads better as
    // "Not assigned" than as a bare em dash.
    if (f.type === "account") return accountName(v) ?? "Not assigned";
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
                        ) : f.type === "account" ? (
                          <Select
                            value={draft[f.key] ?? ""}
                            onChange={(e) =>
                              setDraft({
                                ...draft,
                                // "" is the "Not assigned" option — send null so the
                                // backend clears the link rather than rejecting "".
                                [f.key]: e.target.value === "" ? null : Number(e.target.value),
                              })
                            }
                          >
                            <option value="">Not assigned</option>
                            {accounts.map((a) => (
                              <option key={a.id} value={String(a.id)}>{a.name}</option>
                            ))}
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

            {(items.length > 0 || coverage) && (
              <div className="card">
                <div className="card-head">
                  <p className="card-title">Line items</p>
                  {/* Whether the item block was read end to end, decided at
                      extraction time (extraction.assess_item_coverage). Without
                      it a half-read receipt looks exactly like a short one. */}
                  {coverage && (
                    <span className={`status-pill ${coverage.tone}`} title={coverage.hint}>
                      {coverage.label}
                    </span>
                  )}
                </div>
                {items.length > 0 ? (
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
                ) : (
                  <p className="empty-note">No line items were read from this receipt.</p>
                )}
                {coverage?.tone === "warn" && (
                  <p className="items-coverage-note">{coverage.hint}</p>
                )}
              </div>
            )}
          </>
        )}
      </main>
    </>
  );
}
