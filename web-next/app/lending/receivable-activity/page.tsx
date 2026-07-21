"use client";
// Borrowing & Lending > Receivable Activity (PRD §18): an append-only LOG of every
// collection/advance — a history, not a live mirror of the Owed-to-you page.
import { useCallback, useEffect, useState } from "react";
import type { Account, Receivable, ReceivableActivityRow } from "../../lib/types";
import { money, fmtDate } from "../../lib/format";
import { listReceivables, listReceivableActivity, listAccounts, receivableActivity } from "../../lib/api";
import { useRefresh } from "../../lib/useRefresh";
import { Modal, Field, Select, TextInput, Button, FormError } from "../../components/ui";

export default function ReceivableActivityPage() {
  const [log, setLog] = useState<ReceivableActivityRow[]>([]);
  const [items, setItems] = useState<Receivable[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [open, setOpen] = useState(false);

  const load = useCallback(() => {
    listReceivableActivity().then(setLog).catch(() => setLog([]));
    listReceivables().then(setItems).catch(() => {});
    listAccounts().then(setAccounts).catch(() => {});
  }, []);
  useEffect(() => load(), [load]);
  useRefresh(load);

  return (
    <>
      <main>
        <header>
          <div>
            <h1>Receivable activity</h1>
            <p className="subhead">A log of every collection and advance</p>
          </div>
          <button className="btn-primary" onClick={() => setOpen(true)} disabled={items.length === 0}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M12 5v14M5 12h14" strokeLinecap="round" /></svg>
            Log activity
          </button>
        </header>

        <div className="card">
          {log.length === 0 ? (
            <div className="empty-note">
              No activity logged yet.{items.length === 0 && " Add a receivable on the Owed-to-you page first."}
            </div>
          ) : (
            <div className="plan-list">
              {log.map((r) => {
                const isCollect = r.activity_type === "collection";
                return (
                  <div key={r.id} className="ledger-row">
                    <div className="ledger-icon" style={{
                      background: isCollect ? "color-mix(in srgb, var(--positive) 14%, transparent)" : "color-mix(in srgb, var(--negative) 14%, transparent)",
                      color: isCollect ? "var(--positive)" : "var(--negative)",
                    }}>{isCollect ? "↓" : "↑"}</div>
                    <div className="ledger-main">
                      <div className="ledger-title">{r.receivable_name}</div>
                      <div className="ledger-sub">
                        <span className={"status-pill" + (isCollect ? "" : " warn")}>{isCollect ? "Collection" : "Advance"}</span>
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

      {open && <LogReceivableModal items={items} accounts={accounts} onClose={() => setOpen(false)} onSaved={load} />}
    </>
  );
}

function LogReceivableModal({
  items, accounts, onClose, onSaved,
}: { items: Receivable[]; accounts: Account[]; onClose: () => void; onSaved: () => void }) {
  const debit = accounts.filter((a) => a.type === "debit" && !a.archived);
  const [recId, setRecId] = useState(items[0]?.id ?? 0);
  const [type, setType] = useState<"collection" | "advance">("collection");
  const [accountId, setAccountId] = useState(debit[0]?.id ?? 0);
  const [amount, setAmount] = useState("");
  const [when, setWhen] = useState(new Date().toISOString().slice(0, 10));
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!recId) return setErr("Choose a receivable");
    if (!(Number(amount) > 0)) return setErr("Amount must be greater than 0");
    if (!accountId) return setErr("Choose a debit account");
    setBusy(true); setErr(null);
    try {
      await receivableActivity(recId, { account_id: accountId, amount: Number(amount), type, occurred_at: when });
      onSaved(); onClose();
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };

  return (
    <Modal title="Log receivable activity" onClose={onClose}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" onClick={submit} disabled={busy}>Log</Button></>}>
      <FormError message={err} />
      <Field label="Receivable">
        <Select value={recId} onChange={(e) => setRecId(Number(e.target.value))}>
          {items.map((r) => <option key={r.id} value={r.id}>{r.name} · {money(r.remaining, r.currency)} left</option>)}
        </Select>
      </Field>
      <Field label="Type">
        <Select value={type} onChange={(e) => setType(e.target.value as any)}>
          <option value="collection">Collection (they paid you)</option>
          <option value="advance">Advance (you gave more)</option>
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
