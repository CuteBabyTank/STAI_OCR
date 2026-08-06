"use client";
// Expense / Income / Transfer entry modals (PRD §2.3–2.5). Each is self-contained:
// it takes the shared accounts + categories collections, validates client-side,
// posts to the API, and calls onSaved so the caller can refresh.
import { useMemo, useState } from "react";
import type { Account, TxnCategory, Transaction } from "../lib/types";
import { money } from "../lib/format";
import { createTransaction, updateTransaction } from "../lib/api";
import { Modal, Field, TextInput, Select, Button, FormError } from "./ui";

const nowLocal = () => {
  // datetime-local wants "YYYY-MM-DDTHH:mm" in local time.
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

function debitOnly(accounts: Account[]) {
  return accounts.filter((a) => a.type === "debit" && !a.archived);
}

function defaultAccountId(accounts: Account[]) {
  const cash = accounts.find((a) => a.name.toLowerCase() === "cash" && !a.archived);
  if (cash) return cash.id;
  return accounts.find((a) => !a.archived)?.id ?? 0;
}

// --------------------------------------------------------------------------- //
// Expense
// --------------------------------------------------------------------------- //
export function ExpenseModal({
  accounts,
  categories,
  edit,
  onClose,
  onSaved,
}: {
  accounts: Account[];
  categories: TxnCategory[];
  edit?: Transaction | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const usable = accounts.filter((a) => !a.archived);
  const expenseCats = categories.filter((c) => c.kind === "expense");
  const [amount, setAmount] = useState(edit ? String(edit.amount) : "");
  const [accountId, setAccountId] = useState(edit?.account_id ?? defaultAccountId(usable));
  const [categoryId, setCategoryId] = useState(edit?.category_id ?? expenseCats[0]?.id ?? 0);
  const [when, setWhen] = useState(edit?.occurred_at?.slice(0, 16) || nowLocal());
  const [note, setNote] = useState(edit?.note || "");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    const amt = Number(amount);
    if (!(amt > 0)) return setErr("Amount must be greater than 0");
    if (!accountId) return setErr("Choose an account");
    setBusy(true);
    setErr(null);
    try {
      const payload = {
        amount: amt,
        account_id: accountId,
        category_id: categoryId || null,
        occurred_at: when,
        note: note || null,
      };
      if (edit) await updateTransaction(edit.id, payload);
      else await createTransaction({ kind: "expense", ...payload });
      onSaved();
      onClose();
    } catch (e: any) {
      setErr(e.message || "Could not save");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title={edit ? "Edit expense" : "Add expense"}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" onClick={submit} disabled={busy}>
            {edit ? "Save changes" : "Save expense"}
          </Button>
        </>
      }
    >
      <FormError message={err} />
      <Field label="Amount">
        <TextInput type="number" min="0" step="0.01" placeholder="0.00" value={amount}
          autoFocus onChange={(e) => setAmount(e.target.value)} />
      </Field>
      <Field label="Account">
        <Select value={accountId} onChange={(e) => setAccountId(Number(e.target.value))}>
          {usable.map((a) => (
            <option key={a.id} value={a.id}>{a.name}</option>
          ))}
        </Select>
      </Field>
      <Field label="Category">
        <Select value={categoryId} onChange={(e) => setCategoryId(Number(e.target.value))}>
          <option value={0}>Uncategorized</option>
          {expenseCats.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </Select>
      </Field>
      <Field label="Date and time">
        <TextInput type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} />
      </Field>
      <Field label="Note">
        <TextInput placeholder="Optional" value={note} onChange={(e) => setNote(e.target.value)} />
      </Field>
    </Modal>
  );
}

// --------------------------------------------------------------------------- //
// Income (debit accounts only, no category — PRD §2.4)
// --------------------------------------------------------------------------- //
export function IncomeModal({
  accounts,
  edit,
  onClose,
  onSaved,
}: {
  accounts: Account[];
  edit?: Transaction | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const debit = debitOnly(accounts);
  const [amount, setAmount] = useState(edit ? String(edit.amount) : "");
  const [accountId, setAccountId] = useState(edit?.account_id ?? defaultAccountId(debit));
  const [when, setWhen] = useState(edit?.occurred_at?.slice(0, 16) || nowLocal());
  const [note, setNote] = useState(edit?.note || "");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    const amt = Number(amount);
    if (!(amt > 0)) return setErr("Amount must be greater than 0");
    if (!accountId) return setErr("Choose a debit account");
    setBusy(true);
    setErr(null);
    try {
      const payload = { amount: amt, account_id: accountId, occurred_at: when, note: note || null };
      if (edit) await updateTransaction(edit.id, payload);
      else await createTransaction({ kind: "income", ...payload });
      onSaved();
      onClose();
    } catch (e: any) {
      setErr(e.message || "Could not save");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title={edit ? "Edit income" : "Add income"}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" onClick={submit} disabled={busy}>
            {edit ? "Save changes" : "Save income"}
          </Button>
        </>
      }
    >
      <FormError message={err} />
      {debit.length === 0 && <div className="empty-note">Add a debit account first.</div>}
      <Field label="Amount">
        <TextInput type="number" min="0" step="0.01" placeholder="0.00" value={amount}
          autoFocus onChange={(e) => setAmount(e.target.value)} />
      </Field>
      <Field label="Account" hint="Debit accounts only">
        <Select value={accountId} onChange={(e) => setAccountId(Number(e.target.value))}>
          {debit.map((a) => (
            <option key={a.id} value={a.id}>{a.name}</option>
          ))}
        </Select>
      </Field>
      <Field label="Note">
        <TextInput placeholder="Optional" value={note} onChange={(e) => setNote(e.target.value)} />
      </Field>
      <Field label="Date and time">
        <TextInput type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} />
      </Field>
    </Modal>
  );
}

// --------------------------------------------------------------------------- //
// Transfer (debit -> debit, with optional fee — PRD §2.5)
// --------------------------------------------------------------------------- //
export function TransferModal({
  accounts,
  onClose,
  onSaved,
}: {
  accounts: Account[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const debit = debitOnly(accounts);
  const [amount, setAmount] = useState("");
  const [fromId, setFromId] = useState(defaultAccountId(debit));
  const [toId, setToId] = useState(
    () => debit.find((a) => a.id !== defaultAccountId(debit))?.id ?? 0
  );
  const [fee, setFee] = useState("");
  const [when, setWhen] = useState(nowLocal());
  const [note, setNote] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Selecting a "From" account removes it from the "To" list (PRD §2.5).
  const toOptions = useMemo(() => debit.filter((a) => a.id !== fromId), [debit, fromId]);
  const fromBalance = debit.find((a) => a.id === fromId)?.balance ?? 0;
  const fromCurrency = debit.find((a) => a.id === fromId)?.currency;

  const submit = async () => {
    const amt = Number(amount);
    if (!(amt > 0)) return setErr("Amount must be greater than 0");
    if (!fromId || !toId) return setErr("Choose both accounts");
    if (fromId === toId) return setErr("Choose two different accounts");
    setBusy(true);
    setErr(null);
    try {
      await createTransaction({
        kind: "transfer",
        amount: amt,
        account_id: fromId,
        to_account_id: toId,
        fee: Number(fee) || 0,
        occurred_at: when,
        note: note || null,
      });
      onSaved();
      onClose();
    } catch (e: any) {
      setErr(e.message || "Could not save");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title="Add transfer"
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" onClick={submit} disabled={busy}>Save transfer</Button>
        </>
      }
    >
      <FormError message={err} />
      {debit.length < 2 && <div className="empty-note">You need at least two debit accounts.</div>}
      <div className="field-row">
        <Field label="From">
          <Select value={fromId} onChange={(e) => {
            const v = Number(e.target.value);
            setFromId(v);
            if (v === toId) setToId(debit.find((a) => a.id !== v)?.id ?? 0);
          }}>
            {debit.map((a) => (
              <option key={a.id} value={a.id}>{a.name}</option>
            ))}
          </Select>
        </Field>
        <Field label="To">
          <Select value={toId} onChange={(e) => setToId(Number(e.target.value))}>
            {toOptions.map((a) => (
              <option key={a.id} value={a.id}>{a.name}</option>
            ))}
          </Select>
        </Field>
      </div>
      <Field label="Amount" hint={`Available ${money(fromBalance, fromCurrency)}`}>
        <TextInput type="number" min="0" step="0.01" placeholder="0.00" value={amount}
          autoFocus onChange={(e) => setAmount(e.target.value)} />
      </Field>
      <Field label="Transfer fee" hint="Optional · deducted from source">
        <TextInput type="number" min="0" step="0.01" placeholder="0.00" value={fee}
          onChange={(e) => setFee(e.target.value)} />
      </Field>
      <Field label="Note">
        <TextInput placeholder="Optional" value={note} onChange={(e) => setNote(e.target.value)} />
      </Field>
      <Field label="Date and time">
        <TextInput type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} />
      </Field>
    </Modal>
  );
}
