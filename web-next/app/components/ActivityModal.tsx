"use client";
// Generic activity logger for Goals / Debts / Receivables (PRD §14, §16, §18).
// Posts to the given handler, which creates a linked ledger transaction and
// updates the entity aggregate + the debit account balance.
import { useState } from "react";
import type { Account, ActivityType } from "../lib/types";
import { money } from "../lib/format";
import { Modal, Field, TextInput, Select, Button, FormError } from "./ui";

export default function ActivityModal({
  title,
  accounts,
  types,
  onSubmit,
  onClose,
  onSaved,
}: {
  title: string;
  accounts: Account[];
  types: { value: ActivityType; label: string }[];
  onSubmit: (p: { account_id: number; amount: number; type: ActivityType; occurred_at: string }) => Promise<any>;
  onClose: () => void;
  onSaved: () => void;
}) {
  const debit = accounts.filter((a) => a.type === "debit" && !a.archived);
  const [amount, setAmount] = useState("");
  const [type, setType] = useState<ActivityType>(types[0].value);
  const [accountId, setAccountId] = useState(debit[0]?.id ?? 0);
  const [when, setWhen] = useState(new Date().toISOString().slice(0, 10));
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    const amt = Number(amount);
    if (!(amt > 0)) return setErr("Amount must be greater than 0");
    if (!accountId) return setErr("Choose a debit account");
    setBusy(true);
    setErr(null);
    try {
      await onSubmit({ account_id: accountId, amount: amt, type, occurred_at: when });
      onSaved();
      onClose();
    } catch (e: any) {
      setErr(e.message || "Could not save");
    } finally {
      setBusy(false);
    }
  };

  const bal = debit.find((a) => a.id === accountId);

  return (
    <Modal
      title={title}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" onClick={submit} disabled={busy}>Log activity</Button>
        </>
      }
    >
      <FormError message={err} />
      {debit.length === 0 && <div className="empty-note">Add a debit account first.</div>}
      <Field label="Type">
        <Select value={type} onChange={(e) => setType(e.target.value as ActivityType)}>
          {types.map((t) => (
            <option key={t.value} value={t.value}>{t.label}</option>
          ))}
        </Select>
      </Field>
      <Field label="Amount">
        <TextInput type="number" min="0" step="0.01" placeholder="0.00" value={amount}
          autoFocus onChange={(e) => setAmount(e.target.value)} />
      </Field>
      <Field label="Account" hint={bal ? `Balance ${money(bal.balance, bal.currency)}` : "Debit only"}>
        <Select value={accountId} onChange={(e) => setAccountId(Number(e.target.value))}>
          {debit.map((a) => (
            <option key={a.id} value={a.id}>{a.name}</option>
          ))}
        </Select>
      </Field>
      <Field label="Date">
        <TextInput type="date" value={when} onChange={(e) => setWhen(e.target.value)} />
      </Field>
    </Modal>
  );
}
