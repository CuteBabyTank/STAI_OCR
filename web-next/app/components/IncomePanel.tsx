"use client";
import { useEffect, useState } from "react";
import type { IncomeEntry } from "../lib/types";
import { money, fmtDate } from "../lib/format";

// Slide-over for money coming IN: a quick-add form (one-off or recurring monthly
// salary) and the list of existing entries.
export default function IncomePanel({
  open, currency, onClose, onChanged, flashToast,
}: {
  open: boolean;
  currency: string | null;
  onClose: () => void;
  onChanged: () => Promise<void>;
  flashToast: (m: string) => void;
}) {
  const [entries, setEntries] = useState<IncomeEntry[]>([]);
  const [source, setSource] = useState("");
  const [amount, setAmount] = useState("");
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [recurring, setRecurring] = useState(false);
  const [saving, setSaving] = useState(false);

  const load = async () => {
    try {
      const j = await fetch("/api/income").then((r) => r.json());
      setEntries(j.income || []);
    } catch { /* backend not ready */ }
  };
  useEffect(() => { if (open) load(); }, [open]);

  const add = async () => {
    const amt = parseFloat(amount);
    if (!source.trim() || isNaN(amt) || saving) return;
    setSaving(true);
    try {
      const res = await fetch("/api/income", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ source: source.trim(), amount: amt, currency, date, recurring }),
      });
      if (!res.ok) throw new Error();
      setSource(""); setAmount(""); setRecurring(false);
      await load();
      await onChanged();
      flashToast(recurring ? "Recurring income saved" : "Income added");
    } catch {
      flashToast("Couldn't save that income");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (id: number) => {
    try {
      await fetch(`/api/income/${id}`, { method: "DELETE" });
      await load();
      await onChanged();
    } catch { flashToast("Couldn't delete that entry"); }
  };

  return (
    <>
      <div className={"scrim" + (open ? " open" : "")} onClick={onClose} />
      <div className={"panel" + (open ? " open" : "")} role="dialog" aria-modal="true" aria-label="Add income">
        <div className="panel-head">
          <h2>Add income</h2>
          <button className="icon-btn" style={{ width: 34, height: 34 }} onClick={onClose} aria-label="Close">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M6 6l12 12M18 6 6 18" /></svg>
          </button>
        </div>
        <p className="panel-desc">Log money coming in — a one-off like a refund or gift, or a recurring monthly salary that fills in every month automatically.</p>

        <div className="panel-scroll">
          <div className="income-form">
            <label className="fld">
              <span>Source</span>
              <input value={source} placeholder="Salary, refund, gift…" onChange={(e) => setSource(e.target.value)} />
            </label>
            <div className="fld-row">
              <label className="fld">
                <span>Amount</span>
                <input className="num" type="number" min={0} value={amount} placeholder="0.00" onChange={(e) => setAmount(e.target.value)} />
              </label>
              <label className="fld">
                <span>Date</span>
                <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
              </label>
            </div>
            <label className="recur-toggle">
              <input type="checkbox" checked={recurring} onChange={(e) => setRecurring(e.target.checked)} />
              <span>Recurring monthly (salary) — repeats every month from this date</span>
            </label>
            <button className="btn-primary income-add" onClick={add} disabled={saving}>
              {saving ? "Saving…" : "Add income"}
            </button>
          </div>

          {entries.length > 0 && (
            <>
              <p className="batch-head">Your income</p>
              <div className="batch-list">
                {entries.map((e) => (
                  <div key={e.id} className="batch-row">
                    <span className="b-emoji">{e.recurring ? "🔁" : "💰"}</span>
                    <div className="b-body">
                      <div className="b-merch">
                        {e.source || "Income"}
                        {e.recurring ? <span className="b-review recur">monthly</span> : null}
                      </div>
                      <div className="b-file">{e.recurring ? `from ${fmtDate(e.income_date)}` : fmtDate(e.income_date)}</div>
                    </div>
                    <span className="b-amt num pos">{money(e.amount, e.currency || currency)}</span>
                    <button className="b-del" title="Delete" onClick={() => remove(e.id)}>
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M6 6l12 12M18 6 6 18" /></svg>
                    </button>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>

        <div className="panel-foot">
          <button className="btn-save" onClick={onClose}>Done</button>
        </div>
      </div>
    </>
  );
}
