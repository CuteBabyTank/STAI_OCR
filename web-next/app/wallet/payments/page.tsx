"use client";
// Wallet > Payments (PRD §5): three utility forms — credit payment, loan payment,
// and direct balance adjustment. Credit/loan payments are transfers of cash from a
// debit account to pay down a liability, recorded as expenses linked to that card.
import { useCallback, useEffect, useState } from "react";
import type { Account } from "../../lib/types";
import { money } from "../../lib/format";
import { listAccounts, createTransaction, setAccountBalance } from "../../lib/api";
import { useRefresh } from "../../lib/useRefresh";
import { Field, TextInput, Select, Button, FormError } from "../../components/ui";
import EmptyState from "../../components/empty";

export default function PaymentsPage() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const load = useCallback(() => {
    listAccounts().then(setAccounts).catch(() => setAccounts([]));
  }, []);
  useEffect(() => load(), [load]);
  useRefresh(load);

  const debit = accounts.filter((a) => a.type === "debit" && !a.archived);
  const credit = accounts.filter((a) => a.type === "credit" && !a.archived);
  const loans = accounts.filter((a) => a.type === "loans" && !a.archived);

  return (
    <>
      <main>
        <header>
          <div>
            <h1>Payments</h1>
            <p className="subhead">Pay down cards and loans, or reconcile a balance</p>
          </div>
        </header>

        <div className="grid-2">
          <LiabilityPayment title="Credit payment" targets={credit} debit={debit} onSaved={load} label="Credit account" />
          <LiabilityPayment title="Loan payment" targets={loans} debit={debit} onSaved={load} label="Loan account" />
        </div>

        <BalanceAdjust accounts={accounts} onSaved={load} />
      </main>
    </>
  );
}

// Move cash from a debit account to pay a credit/loan account: an income into the
// liability (reduces what's owed) and an expense out of the source.
function LiabilityPayment({ title, targets, debit, onSaved, label }: {
  title: string; targets: Account[]; debit: Account[]; onSaved: () => void; label: string;
}) {
  const [targetId, setTargetId] = useState(0);
  const [sourceId, setSourceId] = useState(0);
  const [amount, setAmount] = useState("");
  const [when, setWhen] = useState(new Date().toISOString().slice(0, 10));
  const [err, setErr] = useState<string | null>(null);
  const [ok, setOk] = useState(false);

  useEffect(() => { setTargetId((v) => v || targets[0]?.id || 0); setSourceId((v) => v || debit[0]?.id || 0); }, [targets, debit]);

  const submit = async () => {
    if (!targetId || !sourceId) return setErr("Choose both accounts");
    if (!(Number(amount) > 0)) return setErr("Amount must be > 0");
    setErr(null);
    try {
      // Cash leaves the debit account…
      await createTransaction({ kind: "expense", amount: Number(amount), account_id: sourceId, note: title, occurred_at: when });
      // …and reduces the liability. We shift the liability's opening balance up.
      const t = targets.find((a) => a.id === targetId)!;
      await setAccountBalance(targetId, t.balance + Number(amount));
      setAmount(""); setOk(true); setTimeout(() => setOk(false), 1500);
      onSaved();
    } catch (e: any) { setErr(e.message); }
  };

  return (
    <div className="card">
      <p className="section-title">{title}</p>
      <FormError message={err} />
      {targets.length === 0 ? (
        <EmptyState
          size="panel"
          glyphs={["card", "coins", "arrows"]}
          title={`No ${label.toLowerCase()}s yet`}
          sub="Add one in Wallet to pay towards it here."
          action={{ label: "Go to wallet", href: "/wallet" }}
        />
      ) : (
        <div className="inline-form">
          <Field label={label}>
            <Select value={targetId} onChange={(e) => setTargetId(Number(e.target.value))}>
              {targets.map((a) => <option key={a.id} value={a.id}>{a.name} ({money(a.balance, a.currency)})</option>)}
            </Select>
          </Field>
          <Field label="Source account">
            <Select value={sourceId} onChange={(e) => setSourceId(Number(e.target.value))}>
              {debit.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </Select>
          </Field>
          <div className="field-row">
            <Field label="Amount"><TextInput type="number" step="0.01" placeholder="0.00" value={amount} onChange={(e) => setAmount(e.target.value)} /></Field>
            <Field label="Date"><TextInput type="date" value={when} onChange={(e) => setWhen(e.target.value)} /></Field>
          </div>
          <Button variant="primary" onClick={submit}>{ok ? "Recorded ✓" : "Record payment"}</Button>
        </div>
      )}
    </div>
  );
}

function BalanceAdjust({ accounts, onSaved }: { accounts: Account[]; onSaved: () => void }) {
  const [accountId, setAccountId] = useState(0);
  const [value, setValue] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [ok, setOk] = useState(false);
  useEffect(() => { setAccountId((v) => v || accounts[0]?.id || 0); }, [accounts]);

  const submit = async () => {
    if (!accountId) return setErr("Choose an account");
    setErr(null);
    try {
      await setAccountBalance(accountId, Number(value) || 0);
      setOk(true); setTimeout(() => setOk(false), 1500);
      onSaved();
    } catch (e: any) { setErr(e.message); }
  };

  return (
    <div className="card">
      <p className="section-title">Balance adjustment</p>
      <p style={{ margin: "0 0 12px", fontSize: 13, color: "var(--ink-2)" }}>
        Overwrite an account's balance directly — handy for reconciling stock/crypto valuations without a fake transaction.
      </p>
      <FormError message={err} />
      <div className="inline-form" style={{ maxWidth: 420 }}>
        <Field label="Account">
          <Select value={accountId} onChange={(e) => { setAccountId(Number(e.target.value)); const a = accounts.find((x) => x.id === Number(e.target.value)); setValue(a ? String(a.balance) : ""); }}>
            {accounts.map((a) => <option key={a.id} value={a.id}>{a.name} ({money(a.balance, a.currency)})</option>)}
          </Select>
        </Field>
        <Field label="New balance"><TextInput type="number" step="0.01" value={value} onChange={(e) => setValue(e.target.value)} /></Field>
        <Button variant="primary" onClick={submit}>{ok ? "Set ✓" : "Set balance"}</Button>
      </div>
    </div>
  );
}
