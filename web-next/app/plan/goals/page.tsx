"use client";
// Plan > Goals (PRD §13): savings goals with progress. Funding/withdrawing is done
// via the activity modal (money moves between a debit account and the goal).
import { useCallback, useEffect, useState } from "react";
import type { Account, Goal } from "../../lib/types";
import { money, fmtDate } from "../../lib/format";
import { listGoals, createGoal, updateGoal, deleteGoal, goalActivity, listAccounts } from "../../lib/api";
import { CURRENCIES } from "../../lib/format";
import { useRefresh } from "../../lib/useRefresh";
import ActivityModal from "../../components/ActivityModal";
import { Modal, Field, TextInput, Select, Button, Progress, FormError } from "../../components/ui";
import EmptyState from "../../components/empty";

export default function GoalsPage() {
  const [goals, setGoals] = useState<Goal[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [modal, setModal] = useState<{ mode: "add" | "edit" | "activity"; goal?: Goal } | null>(null);

  const load = useCallback(() => {
    listGoals().then(setGoals).catch(() => setGoals([]));
    listAccounts().then(setAccounts).catch(() => {});
  }, []);
  useEffect(() => load(), [load]);
  useRefresh(load);

  return (
    <>
      <main>
        <header>
          <div>
            <h1>Goals</h1>
            <p className="subhead">Save toward what matters</p>
          </div>
          <button className="btn-primary" onClick={() => setModal({ mode: "add" })}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M12 5v14M5 12h14" strokeLinecap="round" /></svg>
            Add goal
          </button>
        </header>

        <div className="card">
          {goals.length === 0 ? <EmptyState
            glyphs={["target", "coins", "chart", "calendar"]}
            title="No goals yet"
            sub="Set a target and track what you put aside."
          /> : (
            <div className="plan-list">
              {goals.map((g) => (
                <div key={g.id} className="plan-row">
                  <div className="plan-main">
                    <div className="plan-title">{g.title}</div>
                    <div className="plan-sub">{money(g.current_amount, g.currency)} of {money(g.target_amount, g.currency)}{g.target_date ? ` · by ${fmtDate(g.target_date)}` : ""}</div>
                    <div className="plan-bar"><Progress pct={g.pct} color="var(--positive)" /></div>
                  </div>
                  <div className="plan-right">
                    <div className="plan-num">{g.pct != null ? `${Math.round(g.pct)}%` : "—"}</div>
                    <div className="acct-actions">
                      <button className="mini-btn" onClick={() => setModal({ mode: "activity", goal: g })}>Fund</button>
                      <button className="mini-btn" onClick={() => setModal({ mode: "edit", goal: g })}>Edit</button>
                      <button className="mini-btn danger" onClick={() => deleteGoal(g.id).then(load)}>Delete</button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </main>

      {(modal?.mode === "add" || modal?.mode === "edit") && (
        <GoalModal goal={modal.goal} onClose={() => setModal(null)} onSaved={load} />
      )}
      {modal?.mode === "activity" && modal.goal && (
        <ActivityModal
          title={`Fund goal — ${modal.goal.title}`}
          accounts={accounts}
          types={[{ value: "deposit", label: "Deposit" }, { value: "withdrawal", label: "Withdrawal" }]}
          onSubmit={(p) => goalActivity(modal.goal!.id, p)}
          onClose={() => setModal(null)}
          onSaved={load}
        />
      )}
    </>
  );
}

function GoalModal({ goal, onClose, onSaved }: { goal?: Goal; onClose: () => void; onSaved: () => void }) {
  const [title, setTitle] = useState(goal?.title || "");
  const [target, setTarget] = useState(goal ? String(goal.target_amount) : "");
  const [current, setCurrent] = useState(goal ? String(goal.current_amount) : "0");
  const [currency, setCurrency] = useState(goal?.currency || "PHP");
  const [targetDate, setTargetDate] = useState(goal?.target_date?.slice(0, 10) || "");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!title.trim()) return setErr("Title is required");
    setBusy(true); setErr(null);
    try {
      const payload = { title: title.trim(), target_amount: Number(target) || 0, current_amount: Number(current) || 0, currency, target_date: targetDate || null };
      if (goal) await updateGoal(goal.id, payload);
      else await createGoal(payload);
      onSaved(); onClose();
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };

  return (
    <Modal title={goal ? "Edit goal" : "Add goal"} onClose={onClose}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" onClick={submit} disabled={busy}>{goal ? "Save" : "Add goal"}</Button></>}>
      <FormError message={err} />
      <Field label="Title"><TextInput autoFocus placeholder="e.g. Emergency fund" value={title} onChange={(e) => setTitle(e.target.value)} /></Field>
      <div className="field-row">
        <Field label="Target amount"><TextInput type="number" step="0.01" value={target} onChange={(e) => setTarget(e.target.value)} /></Field>
        <Field label="Current amount"><TextInput type="number" step="0.01" value={current} onChange={(e) => setCurrent(e.target.value)} /></Field>
      </div>
      <div className="field-row">
        <Field label="Currency">
          <Select value={currency} onChange={(e) => setCurrency(e.target.value)}>
            {CURRENCIES.map((c) => <option key={c} value={c}>{c}</option>)}
          </Select>
        </Field>
        <Field label="Target date"><TextInput type="date" value={targetDate} onChange={(e) => setTargetDate(e.target.value)} /></Field>
      </div>
    </Modal>
  );
}
