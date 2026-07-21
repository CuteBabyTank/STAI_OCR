"use client";
// Plan > Recurring (PRD §11): scheduled repeating transactions with a Paid/Received
// action that logs the occurrence and advances the schedule by a month.
import { useCallback, useEffect, useState } from "react";
import type { Account, Recurring } from "../../lib/types";
import { money, fmtDate } from "../../lib/format";
import { listRecurring, createRecurring, deleteRecurring, advanceRecurring, listAccounts } from "../../lib/api";
import { useRefresh } from "../../lib/useRefresh";
import { Field, TextInput, Select, Button, FormError } from "../../components/ui";

export default function RecurringPage() {
  const [items, setItems] = useState<Recurring[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [kind, setKind] = useState<"expense" | "income">("expense");
  const [amount, setAmount] = useState("");
  const [name, setName] = useState("");
  const [accountId, setAccountId] = useState(0);
  const [nextDue, setNextDue] = useState(new Date().toISOString().slice(0, 10));
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(() => {
    listRecurring().then(setItems).catch(() => setItems([]));
    listAccounts().then((a) => { setAccounts(a); setAccountId((v) => v || a[0]?.id || 0); }).catch(() => {});
  }, []);
  useEffect(() => load(), [load]);
  useRefresh(load);

  const add = async () => {
    if (!name.trim()) return setErr("Name is required");
    setErr(null);
    try {
      await createRecurring({ kind, amount: Number(amount) || 0, name: name.trim(), account_id: accountId || null, next_due: nextDue });
      setName(""); setAmount("");
      load();
    } catch (e: any) { setErr(e.message); }
  };

  return (
    <>
      <main>
        <header>
          <div>
            <h1>Recurring</h1>
            <p className="subhead">Scheduled repeating transactions</p>
          </div>
        </header>

        <div className="card">
          <p className="section-title">New recurring item</p>
          <FormError message={err} />
          <div className="inline-form">
            <div className="field-row">
              <Field label="Kind">
                <Select value={kind} onChange={(e) => setKind(e.target.value as any)}>
                  <option value="expense">Expense</option>
                  <option value="income">Income</option>
                </Select>
              </Field>
              <Field label="Amount"><TextInput type="number" step="0.01" placeholder="0.00" value={amount} onChange={(e) => setAmount(e.target.value)} /></Field>
            </div>
            <div className="field-row">
              <Field label="Name"><TextInput placeholder="e.g. Netflix" value={name} onChange={(e) => setName(e.target.value)} /></Field>
              <Field label="Account">
                <Select value={accountId} onChange={(e) => setAccountId(Number(e.target.value))}>
                  {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                </Select>
              </Field>
            </div>
            <Field label="Next due date"><TextInput type="date" value={nextDue} onChange={(e) => setNextDue(e.target.value)} /></Field>
            <Button variant="primary" onClick={add}>Add recurring</Button>
          </div>
        </div>

        <div className="card">
          <p className="section-title">Schedule</p>
          {items.length === 0 ? <div className="empty-note">Nothing scheduled.</div> : (
            <div className="plan-list">
              {items.map((r) => (
                <div key={r.id} className="plan-row">
                  <div className="plan-main">
                    <div className="plan-title">{r.name}</div>
                    <div className="plan-sub">{r.kind} · {money(r.amount)} · next {fmtDate(r.next_due)} · {r.account_name || "—"}</div>
                  </div>
                  <div className="acct-actions">
                    <button className="mini-btn" onClick={() => advanceRecurring(r.id).then(load)}>
                      {r.kind === "income" ? "Received" : "Paid"}
                    </button>
                    <button className="mini-btn danger" onClick={() => deleteRecurring(r.id).then(load)}>Delete</button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </main>
    </>
  );
}
