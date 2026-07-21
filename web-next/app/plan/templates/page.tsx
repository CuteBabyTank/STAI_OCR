"use client";
// Plan > Templates (PRD §10): reusable transaction presets, grouped by kind, each
// with a one-click "Use" that materializes it into the ledger.
import { useCallback, useEffect, useState } from "react";
import type { Account, Template } from "../../lib/types";
import { money } from "../../lib/format";
import { listTemplates, createTemplate, deleteTemplate, useTemplate, listAccounts } from "../../lib/api";
import { useRefresh } from "../../lib/useRefresh";
import { Field, TextInput, Select, Button, FormError } from "../../components/ui";

export default function TemplatesPage() {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [title, setTitle] = useState("");
  const [amount, setAmount] = useState("");
  const [kind, setKind] = useState<"expense" | "income">("expense");
  const [accountId, setAccountId] = useState(0);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(() => {
    listTemplates().then(setTemplates).catch(() => setTemplates([]));
    listAccounts().then((a) => { setAccounts(a); setAccountId((v) => v || a[0]?.id || 0); }).catch(() => {});
  }, []);
  useEffect(() => load(), [load]);
  useRefresh(load);

  const add = async () => {
    if (!title.trim()) return setErr("Title is required");
    setErr(null);
    try {
      await createTemplate({ title: title.trim(), amount: Number(amount) || 0, kind, account_id: accountId || null });
      setTitle(""); setAmount("");
      load();
    } catch (e: any) { setErr(e.message); }
  };

  const group = (k: string) => templates.filter((t) => t.kind === k);

  const List = ({ label, k }: { label: string; k: "expense" | "income" }) => (
    <div className="card">
      <p className="section-title">{label}</p>
      {group(k).length === 0 ? <div className="empty-note">None yet.</div> : group(k).map((t) => (
        <div key={t.id} className="plan-row">
          <div className="plan-main">
            <div className="plan-title">{t.title}</div>
            <div className="plan-sub">{money(t.amount)} · {t.account_name || "—"}</div>
          </div>
          <div className="acct-actions">
            <button className="mini-btn" onClick={() => useTemplate(t.id).then(load)}>Use</button>
            <button className="mini-btn danger" onClick={() => deleteTemplate(t.id).then(load)}>Delete</button>
          </div>
        </div>
      ))}
    </div>
  );

  return (
    <>
      <main>
        <header>
          <div>
            <h1>Templates</h1>
            <p className="subhead">Presets for fast repeat entry</p>
          </div>
        </header>

        <div className="card">
          <p className="section-title">New template</p>
          <FormError message={err} />
          <div className="inline-form">
            <div className="field-row">
              <Field label="Title"><TextInput placeholder="e.g. Coffee run" value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
              <Field label="Amount"><TextInput type="number" step="0.01" placeholder="0.00" value={amount} onChange={(e) => setAmount(e.target.value)} /></Field>
            </div>
            <div className="field-row">
              <Field label="Kind">
                <Select value={kind} onChange={(e) => setKind(e.target.value as any)}>
                  <option value="expense">Expense</option>
                  <option value="income">Income</option>
                </Select>
              </Field>
              <Field label="Account">
                <Select value={accountId} onChange={(e) => setAccountId(Number(e.target.value))}>
                  {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                </Select>
              </Field>
            </div>
            <Button variant="primary" onClick={add}>Add template</Button>
          </div>
        </div>

        <div className="grid-2">
          <List label="Expense templates" k="expense" />
          <List label="Income templates" k="income" />
        </div>
      </main>
    </>
  );
}
