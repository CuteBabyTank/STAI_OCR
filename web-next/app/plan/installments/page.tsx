"use client";
// Plan > Installments (PRD §12): financed-purchase plans plus a "Log payment"
// form that records a payment against an active plan.
import { useCallback, useEffect, useState } from "react";
import type { Account, Installment } from "../../lib/types";
import { money } from "../../lib/format";
import { listInstallments, createInstallment, deleteInstallment, payInstallment, listAccounts } from "../../lib/api";
import { useRefresh } from "../../lib/useRefresh";
import { Field, TextInput, Select, Button, Progress, FormError } from "../../components/ui";
import EmptyState from "../../components/empty";

export default function InstallmentsPage() {
  const [plans, setPlans] = useState<Installment[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  // create form
  const [title, setTitle] = useState("");
  const [total, setTotal] = useState("");
  const [monthly, setMonthly] = useState("");
  const [months, setMonths] = useState("");
  // payment form
  const [planId, setPlanId] = useState(0);
  const [accountId, setAccountId] = useState(0);
  const [payAmt, setPayAmt] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [perr, setPerr] = useState<string | null>(null);

  const load = useCallback(() => {
    listInstallments().then((p) => { setPlans(p); setPlanId((v) => v || p[0]?.id || 0); }).catch(() => setPlans([]));
    listAccounts().then((a) => { setAccounts(a); setAccountId((v) => v || a[0]?.id || 0); }).catch(() => {});
  }, []);
  useEffect(() => load(), [load]);
  useRefresh(load);

  const addPlan = async () => {
    if (!title.trim()) return setErr("Title is required");
    setErr(null);
    try {
      await createInstallment({ title: title.trim(), total: Number(total) || 0, monthly: Number(monthly) || 0, months: Number(months) || 0 });
      setTitle(""); setTotal(""); setMonthly(""); setMonths("");
      load();
    } catch (e: any) { setErr(e.message); }
  };

  const pay = async () => {
    if (!planId) return setPerr("Choose a plan");
    if (!(Number(payAmt) > 0)) return setPerr("Amount must be > 0");
    setPerr(null);
    try {
      await payInstallment(planId, { account_id: accountId, amount: Number(payAmt) });
      setPayAmt("");
      load();
    } catch (e: any) { setPerr(e.message); }
  };

  return (
    <>
      <main>
        <header>
          <div>
            <h1>Installments</h1>
            <p className="subhead">Financed purchases</p>
          </div>
        </header>

        <div className="grid-2">
          <div className="card">
            <p className="section-title">New plan</p>
            <FormError message={err} />
            <div className="inline-form">
              <Field label="Title"><TextInput placeholder="e.g. Laptop 0% plan" value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
              <div className="field-row">
                <Field label="Total"><TextInput type="number" step="0.01" value={total} onChange={(e) => setTotal(e.target.value)} /></Field>
                <Field label="Monthly"><TextInput type="number" step="0.01" value={monthly} onChange={(e) => setMonthly(e.target.value)} /></Field>
              </div>
              <Field label="Months"><TextInput type="number" value={months} onChange={(e) => setMonths(e.target.value)} /></Field>
              <Button variant="primary" onClick={addPlan}>Add plan</Button>
            </div>
          </div>

          <div className="card">
            <p className="section-title">Log payment</p>
            <FormError message={perr} />
            <div className="inline-form">
              <Field label="Plan">
                <Select value={planId} onChange={(e) => setPlanId(Number(e.target.value))}>
                  {plans.map((p) => <option key={p.id} value={p.id}>{p.title}</option>)}
                </Select>
              </Field>
              <Field label="Account">
                <Select value={accountId} onChange={(e) => setAccountId(Number(e.target.value))}>
                  {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                </Select>
              </Field>
              <Field label="Amount"><TextInput type="number" step="0.01" placeholder="0.00" value={payAmt} onChange={(e) => setPayAmt(e.target.value)} /></Field>
              <Button variant="primary" onClick={pay}>Log payment</Button>
            </div>
          </div>
        </div>

        <div className="card">
          <p className="section-title">Active plans</p>
          {plans.length === 0 ? <EmptyState
            glyphs={["calendar", "card", "gauge"]}
            title="No installment plans"
            sub="Split a purchase and track it down to zero."
          /> : (
            <div className="plan-list">
              {plans.map((p) => (
                <div key={p.id} className="plan-row">
                  <div className="plan-main">
                    <div className="plan-title">{p.title}</div>
                    <div className="plan-sub">{money(p.monthly)}/mo · {p.months} months</div>
                    <div className="plan-bar"><Progress pct={p.pct} /></div>
                  </div>
                  <div className="plan-right">
                    <div className="plan-num">{money(p.paid_amount)} <span style={{ color: "var(--ink-3)", fontWeight: 400 }}>/ {money(p.total)}</span></div>
                    <button className="mini-btn danger" onClick={() => deleteInstallment(p.id).then(load)}>Delete</button>
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
