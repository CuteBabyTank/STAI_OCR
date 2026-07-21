"use client";
// Borrowing & Lending > Debt Activity (PRD §16): an append-only LOG of every
// payment/borrowing event — a history, not a live mirror of the Debts page. Each
// logged payment adds a row here; the Debts page tracks current outstanding.
import { useCallback, useEffect, useState } from "react";
import type { Account, Debt, DebtActivityRow } from "../../lib/types";
import { money, fmtDate } from "../../lib/format";
import { listDebts, listDebtActivity, listAccounts, debtActivity } from "../../lib/api";
import { useRefresh } from "../../lib/useRefresh";
import { Modal, Field, Select, TextInput, Button, FormError } from "../../components/ui";

export default function DebtActivityPage() {
  const [log, setLog] = useState<DebtActivityRow[]>([]);
  const [debts, setDebts] = useState<Debt[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [open, setOpen] = useState(false);

  const load = useCallback(() => {
    listDebtActivity().then(setLog).catch(() => setLog([]));
    listDebts().then(setDebts).catch(() => {});
    listAccounts().then(setAccounts).catch(() => {});
  }, []);
  useEffect(() => load(), [load]);
  useRefresh(load);

  return (
    <>
      <main>
        <header>
          <div>
            <h1>Debt activity</h1>
            <p className="subhead">A log of every payment and borrowing</p>
          </div>
          <button className="btn-primary" onClick={() => setOpen(true)} disabled={debts.length === 0}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M12 5v14M5 12h14" strokeLinecap="round" /></svg>
            Log activity
          </button>
        </header>

        <div className="card">
          {log.length === 0 ? (
            <div className="empty-note">
              No activity logged yet.{debts.length === 0 && " Add a debt on the Debts page first."}
            </div>
          ) : (
            <div className="plan-list">
              {log.map((r) => {
                const isPay = r.activity_type === "payment";
                return (
                  <div key={r.id} className="ledger-row">
                    <div className="ledger-icon" style={{
                      background: isPay ? "color-mix(in srgb, var(--positive) 14%, transparent)" : "color-mix(in srgb, var(--negative) 14%, transparent)",
                      color: isPay ? "var(--positive)" : "var(--negative)",
                    }}>{isPay ? "↓" : "↑"}</div>
                    <div className="ledger-main">
                      <div className="ledger-title">{r.debt_name}</div>
                      <div className="ledger-sub">
                        <span className={"status-pill" + (isPay ? "" : " warn")}>{isPay ? "Payment" : "Borrowing"}</span>
                        {" · "}{r.account_name || "—"} · {fmtDate(r.occurred_at?.slice(0, 10))}
                      </div>
                    </div>
                    <div className="ledger-amt num">{money(r.amount, r.currency)}</div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </main>

      {open && <LogDebtModal debts={debts} accounts={accounts} onClose={() => setOpen(false)} onSaved={load} />}
    </>
  );
}

function LogDebtModal({
  debts, accounts, onClose, onSaved,
}: { debts: Debt[]; accounts: Account[]; onClose: () => void; onSaved: () => void }) {
  const debit = accounts.filter((a) => a.type === "debit" && !a.archived);
  const [debtId, setDebtId] = useState(debts[0]?.id ?? 0);
  const [type, setType] = useState<"payment" | "borrowing">("payment");
  const [accountId, setAccountId] = useState(debit[0]?.id ?? 0);
  const [amount, setAmount] = useState("");
  const [when, setWhen] = useState(new Date().toISOString().slice(0, 10));
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!debtId) return setErr("Choose a debt");
    if (!(Number(amount) > 0)) return setErr("Amount must be greater than 0");
    if (!accountId) return setErr("Choose a debit account");
    setBusy(true); setErr(null);
    try {
      await debtActivity(debtId, { account_id: accountId, amount: Number(amount), type, occurred_at: when });
      onSaved(); onClose();
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };

  return (
    <Modal title="Log debt activity" onClose={onClose}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" onClick={submit} disabled={busy}>Log</Button></>}>
      <FormError message={err} />
      <Field label="Debt">
        <Select value={debtId} onChange={(e) => setDebtId(Number(e.target.value))}>
          {debts.map((d) => <option key={d.id} value={d.id}>{d.name} · owes {money(d.outstanding, d.currency)}</option>)}
        </Select>
      </Field>
      <Field label="Type">
        <Select value={type} onChange={(e) => setType(e.target.value as any)}>
          <option value="payment">Payment (reduce what you owe)</option>
          <option value="borrowing">Borrowing (owe more)</option>
        </Select>
      </Field>
      <Field label="Account" hint="Debit only">
        <Select value={accountId} onChange={(e) => setAccountId(Number(e.target.value))}>
          {debit.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
        </Select>
      </Field>
      <div className="field-row">
        <Field label="Amount"><TextInput type="number" min="0" step="0.01" placeholder="0.00" value={amount} autoFocus onChange={(e) => setAmount(e.target.value)} /></Field>
        <Field label="Date"><TextInput type="date" value={when} onChange={(e) => setWhen(e.target.value)} /></Field>
      </div>
    </Modal>
  );
}
