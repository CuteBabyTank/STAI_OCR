"use client";
// Add / Edit account (PRD §4). On edit, Type and Currency are locked to avoid
// desynchronizing historical transactions — the backend also rejects changes.
import { useState } from "react";
import type { Account } from "../lib/types";
import { ACCOUNT_TYPES } from "../lib/types";
import { CURRENCIES, acctMeta } from "../lib/format";
import { createAccount, updateAccount } from "../lib/api";
import { Modal, Field, TextInput, Select, Button, FormError } from "./ui";

export default function AccountModal({
  edit,
  onClose,
  onSaved,
}: {
  edit?: Account | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [name, setName] = useState(edit?.name || "");
  const [type, setType] = useState(edit?.type || "debit");
  const [opening, setOpening] = useState(edit ? String(edit.opening_balance) : "0");
  const [currency, setCurrency] = useState(edit?.currency || "PHP");
  const [include, setInclude] = useState(edit ? !!edit.include_in_totals : true);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const editing = !!edit;

  const submit = async () => {
    if (!name.trim()) return setErr("Name is required");
    setBusy(true);
    setErr(null);
    try {
      if (editing) {
        await updateAccount(edit!.id, {
          name: name.trim(),
          opening_balance: Number(opening) || 0,
          include_in_totals: include,
        });
      } else {
        await createAccount({
          name: name.trim(),
          type,
          opening_balance: Number(opening) || 0,
          currency,
          include_in_totals: include,
        });
      }
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
      title={editing ? "Edit account" : "Add account"}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" onClick={submit} disabled={busy}>
            {editing ? "Save changes" : "Add account"}
          </Button>
        </>
      }
    >
      <FormError message={err} />
      <Field label="Name">
        <TextInput autoFocus placeholder="e.g. GCash" value={name} onChange={(e) => setName(e.target.value)} />
      </Field>
      <div className="field-row">
        <Field label="Type" hint={editing ? "Locked" : undefined}>
          <Select value={type} onChange={(e) => setType(e.target.value as any)} disabled={editing}>
            {ACCOUNT_TYPES.map((t) => (
              <option key={t} value={t}>{acctMeta(t).label}</option>
            ))}
          </Select>
        </Field>
        <Field label="Currency" hint={editing ? "Locked" : undefined}>
          <Select value={currency} onChange={(e) => setCurrency(e.target.value)} disabled={editing}>
            {CURRENCIES.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </Select>
        </Field>
      </div>
      <Field label="Opening balance">
        <TextInput type="number" step="0.01" value={opening} onChange={(e) => setOpening(e.target.value)} />
      </Field>
      <label className="check-row">
        <input type="checkbox" checked={include} onChange={(e) => setInclude(e.target.checked)} />
        Include in wallet totals
      </label>
    </Modal>
  );
}
