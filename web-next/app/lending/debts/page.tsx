"use client";
// Plan > Debts (PRD §15): money you owe. Payments reduce the outstanding balance
// and debit an account; borrowings increase it and credit an account.
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import type { Debt } from "../../lib/types";
import { money, fmtDate, CURRENCIES } from "../../lib/format";
import { listDebts, createDebt, deleteDebt } from "../../lib/api";
import { useRefresh } from "../../lib/useRefresh";
import { Modal, Field, TextInput, Select, Button, Progress, FormError } from "../../components/ui";

export default function DebtsPage() {
  const [debts, setDebts] = useState<Debt[]>([]);
  const [adding, setAdding] = useState(false);

  const load = useCallback(() => {
    listDebts().then(setDebts).catch(() => setDebts([]));
  }, []);
  useEffect(() => load(), [load]);
  useRefresh(load);

  return (
    <>
      <main>
        <header>
          <div>
            <h1>Debts</h1>
            <p className="subhead">What you owe — record payments in Debt activity</p>
          </div>
          <button className="btn-primary" onClick={() => setAdding(true)}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M12 5v14M5 12h14" strokeLinecap="round" /></svg>
            Add debt
          </button>
        </header>

        <div className="card">
          {debts.length === 0 ? <div className="empty-note">No debts tracked.</div> : (
            <div className="plan-list">
              {debts.map((d) => (
                <div key={d.id} className="plan-row">
                  <div className="plan-main">
                    <div className="plan-title">{d.name}</div>
                    <div className="plan-sub">Outstanding {money(d.outstanding, d.currency)} of {money(d.total_amount, d.currency)}{d.due_date ? ` · due ${fmtDate(d.due_date)}` : ""}</div>
                    <div className="plan-bar"><Progress pct={d.pct} /></div>
                  </div>
                  <div className="plan-right">
                    <div className="plan-num">{money(d.outstanding, d.currency)}</div>
                    <div className="acct-actions">
                      <Link href="/lending/debt-activity" className="mini-btn">Log</Link>
                      <button className="mini-btn danger" onClick={() => deleteDebt(d.id).then(load)}>Delete</button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </main>

      {adding && <DebtModal onClose={() => setAdding(false)} onSaved={load} />}
    </>
  );
}

function DebtModal({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState("");
  const [total, setTotal] = useState("");
  const [paid, setPaid] = useState("0");
  const [currency, setCurrency] = useState("PHP");
  const [due, setDue] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!name.trim()) return setErr("Name is required");
    setBusy(true); setErr(null);
    try {
      await createDebt({ name: name.trim(), total_amount: Number(total) || 0, paid_amount: Number(paid) || 0, currency, due_date: due || null });
      onSaved(); onClose();
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };

  return (
    <Modal title="Add debt" onClose={onClose}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" onClick={submit} disabled={busy}>Add debt</Button></>}>
      <FormError message={err} />
      <Field label="Debt name"><TextInput autoFocus placeholder="e.g. Loan from Ana" value={name} onChange={(e) => setName(e.target.value)} /></Field>
      <div className="field-row">
        <Field label="Total amount"><TextInput type="number" step="0.01" value={total} onChange={(e) => setTotal(e.target.value)} /></Field>
        <Field label="Paid amount"><TextInput type="number" step="0.01" value={paid} onChange={(e) => setPaid(e.target.value)} /></Field>
      </div>
      <div className="field-row">
        <Field label="Currency">
          <Select value={currency} onChange={(e) => setCurrency(e.target.value)}>
            {CURRENCIES.map((c) => <option key={c} value={c}>{c}</option>)}
          </Select>
        </Field>
        <Field label="Due date"><TextInput type="date" value={due} onChange={(e) => setDue(e.target.value)} /></Field>
      </div>
    </Modal>
  );
}
