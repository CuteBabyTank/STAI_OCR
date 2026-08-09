"use client";
// Plan > Budgets (PRD §7): grid of category budgets with status, spent, progress
// and limit; add modal supports fixed amount or % of income, per interval.
import { useCallback, useEffect, useState } from "react";
import type { BudgetPlan, TxnCategory } from "../../lib/types";
import { money } from "../../lib/format";
import { listBudgetPlans, createBudgetPlan, deleteBudgetPlan, listCategories } from "../../lib/api";
import { useRefresh } from "../../lib/useRefresh";
import { Modal, Field, TextInput, Select, Button, Progress, FormError } from "../../components/ui";
import EmptyState from "../../components/empty";

export default function BudgetsPage() {
  const [budgets, setBudgets] = useState<BudgetPlan[]>([]);
  const [cats, setCats] = useState<TxnCategory[]>([]);
  const [modal, setModal] = useState(false);

  const load = useCallback(() => {
    listBudgetPlans().then(setBudgets).catch(() => setBudgets([]));
    listCategories().then(setCats).catch(() => setCats([]));
  }, []);
  useEffect(() => load(), [load]);
  useRefresh(load);

  return (
    <>
      <main>
        <header>
          <div>
            <h1>Budgets</h1>
            <p className="subhead">Keep category spending on track</p>
          </div>
          <button className="btn-primary" onClick={() => setModal(true)}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M12 5v14M5 12h14" strokeLinecap="round" /></svg>
            Add budget
          </button>
        </header>

        <div className="card">
          {budgets.length === 0 ? (
            <EmptyState
              glyphs={["gauge", "tag", "coins", "chart"]}
              title="No budgets yet"
              sub="Cap a category and watch it through the month."
            />
          ) : (
            <div className="plan-list">
              {budgets.map((b) => {
                const over = (b.pct ?? 0) > 100;
                return (
                  <div key={b.id} className="plan-row">
                    <span style={{ width: 10, height: 10, borderRadius: "50%", background: b.category_color || "var(--accent)" }} />
                    <div className="plan-main">
                      <div className="plan-title">{b.category_name || "—"}</div>
                      <div className="plan-sub">
                        <span className={"status-pill" + (over ? " warn" : "")}>{over ? "Over budget" : "On track"}</span>
                        {" "}· {b.interval}{b.type === "percent" ? ` · ${b.percent}% of income` : ""}
                      </div>
                      <div className="plan-bar"><Progress pct={b.pct} color={b.category_color || undefined} /></div>
                    </div>
                    <div className="plan-right">
                      <div className="plan-num">{money(b.spent)} <span style={{ color: "var(--ink-3)", fontWeight: 400 }}>/ {money(b.limit)}</span></div>
                      <button className="mini-btn danger" onClick={() => deleteBudgetPlan(b.id).then(load)}>Delete</button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </main>
      {modal && <BudgetModal cats={cats.filter((c) => c.kind === "expense")} onClose={() => setModal(false)} onSaved={load} />}
    </>
  );
}

function BudgetModal({ cats, onClose, onSaved }: { cats: TxnCategory[]; onClose: () => void; onSaved: () => void }) {
  const [categoryId, setCategoryId] = useState(cats[0]?.id ?? 0);
  const [type, setType] = useState<"fixed" | "percent">("fixed");
  const [interval, setInterval] = useState("monthly");
  const [limit, setLimit] = useState("");
  const [percent, setPercent] = useState("");
  const [carry, setCarry] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!categoryId) return setErr("Choose a category");
    setBusy(true);
    setErr(null);
    try {
      await createBudgetPlan({
        category_id: categoryId, type, interval,
        limit_amount: type === "fixed" ? Number(limit) || 0 : 0,
        percent: type === "percent" ? Number(percent) || 0 : 0,
        carry_forward: carry,
      });
      onSaved();
      onClose();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title="Add budget" onClose={onClose}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" onClick={submit} disabled={busy}>Add budget</Button></>}>
      <FormError message={err} />
      <Field label="Category">
        <Select value={categoryId} onChange={(e) => setCategoryId(Number(e.target.value))}>
          {cats.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </Select>
      </Field>
      <div className="field-row">
        <Field label="Type">
          <Select value={type} onChange={(e) => setType(e.target.value as any)}>
            <option value="fixed">Fixed amount</option>
            <option value="percent">% of income</option>
          </Select>
        </Field>
        <Field label="Interval">
          <Select value={interval} onChange={(e) => setInterval(e.target.value)}>
            <option value="daily">Daily</option>
            <option value="weekly">Weekly</option>
            <option value="monthly">Monthly</option>
            <option value="yearly">Yearly</option>
          </Select>
        </Field>
      </div>
      {type === "fixed" ? (
        <Field label="Limit amount">
          <TextInput type="number" min="0" step="0.01" placeholder="0.00" value={limit} onChange={(e) => setLimit(e.target.value)} />
        </Field>
      ) : (
        <Field label="Percent of income" hint="%">
          <TextInput type="number" min="0" max="100" step="1" placeholder="e.g. 20" value={percent} onChange={(e) => setPercent(e.target.value)} />
        </Field>
      )}
      <label className="check-row">
        <input type="checkbox" checked={carry} onChange={(e) => setCarry(e.target.checked)} />
        Carry unused budget forward
      </label>
    </Modal>
  );
}
