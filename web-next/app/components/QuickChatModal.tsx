"use client";
// Quick chat (PRD §2.2): a natural-language box that parses free text into a
// draft transaction, previews it for confirmation, then posts it. Parsing runs
// client-side today (lib/parseQuick); a server LLM parser can replace it later.
import { useMemo, useState } from "react";
import type { Account, TxnCategory } from "../lib/types";
import { money } from "../lib/format";
import { parseQuick } from "../lib/parseQuick";
import { createTransaction } from "../lib/api";
import { Modal, TextInput, Button, FormError } from "./ui";

const SUGGESTIONS = [
  "1.2k groceries",
  "+5000 salary",
  "₱350 coffee yesterday",
  "800 dinner apr 1",
  "transfer 2000 to savings",
  "120 transport",
];

export default function QuickChatModal({
  accounts,
  categories,
  onClose,
  onSaved,
}: {
  accounts: Account[];
  categories: TxnCategory[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [text, setText] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const draft = useMemo(
    () => (text.trim() ? parseQuick(text, accounts, categories) : null),
    [text, accounts, categories]
  );

  const acctName = (id: number | null) => accounts.find((a) => a.id === id)?.name ?? "—";
  const catName = (id: number | null) => categories.find((c) => c.id === id)?.name ?? "Uncategorized";

  const submit = async () => {
    if (!draft) return setErr("Could not read an amount from that. Try “1.2k lunch”.");
    if (!draft.accountId) return setErr("No account matched — add an account first.");
    if (draft.kind === "transfer" && !draft.toAccountId)
      return setErr("Need a second debit account for a transfer.");
    setBusy(true);
    setErr(null);
    try {
      await createTransaction({
        kind: draft.kind,
        amount: draft.amount,
        account_id: draft.accountId,
        to_account_id: draft.toAccountId,
        category_id: draft.kind === "expense" ? draft.categoryId : null,
        note: draft.note || null,
        occurred_at: draft.occurredAt,
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
      title="Quick chat"
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" onClick={submit} disabled={busy || !draft}>Add</Button>
        </>
      }
    >
      <FormError message={err} />
      <TextInput
        autoFocus
        placeholder="Describe the transaction…  e.g. 1.2k groceries yesterday"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && submit()}
      />
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {SUGGESTIONS.map((s) => (
          <button key={s} className="cat-pill" style={{ cursor: "pointer", border: "1px solid var(--border)" }}
            onClick={() => setText(s)}>
            {s}
          </button>
        ))}
      </div>
      {draft && (
        <div className="card" style={{ padding: 14, display: "grid", gap: 6 }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontSize: 13.5 }}>
            <span style={{ color: "var(--ink-2)", textTransform: "capitalize" }}>{draft.kind}</span>
            <strong style={{ color: draft.kind === "income" ? "var(--positive)" : draft.kind === "expense" ? "var(--negative)" : "var(--ink)" }}>
              {money(draft.amount)}
            </strong>
          </div>
          <div style={{ fontSize: 12.5, color: "var(--ink-2)" }}>
            {draft.note || "(no note)"} · {catName(draft.categoryId)}
          </div>
          <div style={{ fontSize: 12.5, color: "var(--ink-3)" }}>
            {draft.kind === "transfer"
              ? `${acctName(draft.accountId)} → ${acctName(draft.toAccountId)}`
              : acctName(draft.accountId)}{" "}
            · {draft.occurredAt.slice(0, 10)}
          </div>
        </div>
      )}
    </Modal>
  );
}
