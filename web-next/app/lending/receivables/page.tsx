"use client";
// Plan > Owed to You (PRD §17): money owed to you, mirroring debts. A dashboard of
// awaiting-collection / open receivables / average progress plus per-item activity.
import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import type { Receivable } from "../../lib/types";
import { money, fmtDate, CURRENCIES } from "../../lib/format";
import { listReceivables, createReceivable, deleteReceivable } from "../../lib/api";
import { useRefresh } from "../../lib/useRefresh";
import { Modal, Field, TextInput, Select, Button, Progress, FormError } from "../../components/ui";
import EmptyState from "../../components/empty";

export default function ReceivablesPage() {
  const [items, setItems] = useState<Receivable[]>([]);
  const [adding, setAdding] = useState(false);

  const load = useCallback(() => {
    listReceivables().then(setItems).catch(() => setItems([]));
  }, []);
  useEffect(() => load(), [load]);
  useRefresh(load);

  const stats = useMemo(() => {
    const awaiting = items.reduce((s, r) => s + r.remaining, 0);
    const open = items.filter((r) => r.remaining > 0).length;
    const withPct = items.filter((r) => r.pct != null);
    const avg = withPct.length ? withPct.reduce((s, r) => s + (r.pct || 0), 0) / withPct.length : 0;
    return { awaiting, open, avg };
  }, [items]);

  return (
    <>
      <main>
        <header>
          <div>
            <h1>Owed to you</h1>
            <p className="subhead">Money coming back to you — record collections in Receivable activity</p>
          </div>
          <button className="btn-primary" onClick={() => setAdding(true)}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M12 5v14M5 12h14" strokeLinecap="round" /></svg>
            Add receivable
          </button>
        </header>

        <div className="stat-grid">
          <div className="card"><p className="stat-label">Awaiting collection</p><div className="tile-num">{money(stats.awaiting)}</div></div>
          <div className="card"><p className="stat-label">Open receivables</p><div className="tile-num">{stats.open}</div></div>
          <div className="card"><p className="stat-label">Average progress</p><div className="tile-num">{Math.round(stats.avg)}%</div></div>
        </div>

        <div className="card">
          {items.length === 0 ? <EmptyState
            glyphs={["handshake", "coins", "clock"]}
            title="Nobody owes you yet"
            sub="Track money lent out and when it is due back."
          /> : (
            <div className="plan-list">
              {items.map((r) => (
                <div key={r.id} className="plan-row">
                  <div className="plan-main">
                    <div className="plan-title">{r.name}</div>
                    <div className="plan-sub">Collected {money(r.collected_amount, r.currency)} of {money(r.total_amount, r.currency)}{r.due_date ? ` · due ${fmtDate(r.due_date)}` : ""}</div>
                    <div className="plan-bar"><Progress pct={r.pct} color="var(--positive)" /></div>
                  </div>
                  <div className="plan-right">
                    <div className="plan-num">{money(r.remaining, r.currency)}</div>
                    <div className="acct-actions">
                      <Link href="/lending/receivable-activity" className="mini-btn">Log</Link>
                      <button className="mini-btn danger" onClick={() => deleteReceivable(r.id).then(load)}>Delete</button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </main>

      {adding && <ReceivableModal onClose={() => setAdding(false)} onSaved={load} />}
    </>
  );
}

function ReceivableModal({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState("");
  const [total, setTotal] = useState("");
  const [collected, setCollected] = useState("0");
  const [currency, setCurrency] = useState("PHP");
  const [due, setDue] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!name.trim()) return setErr("Name is required");
    setBusy(true); setErr(null);
    try {
      await createReceivable({ name: name.trim(), total_amount: Number(total) || 0, collected_amount: Number(collected) || 0, currency, due_date: due || null });
      onSaved(); onClose();
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  };

  return (
    <Modal title="Add receivable" onClose={onClose}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" onClick={submit} disabled={busy}>Add receivable</Button></>}>
      <FormError message={err} />
      <Field label="Name"><TextInput autoFocus placeholder="e.g. Bea owes me" value={name} onChange={(e) => setName(e.target.value)} /></Field>
      <div className="field-row">
        <Field label="Total amount"><TextInput type="number" step="0.01" value={total} onChange={(e) => setTotal(e.target.value)} /></Field>
        <Field label="Collected amount"><TextInput type="number" step="0.01" value={collected} onChange={(e) => setCollected(e.target.value)} /></Field>
      </div>
      <div className="field-row">
        <Field label="Currency">
          <Select value={currency} onChange={(e) => setCurrency(e.target.value)}>
            {CURRENCIES.map((c) => <option key={c} value={c}>{c}</option>)}
          </Select>
        </Field>
        <Field label="Due date"><TextInput type="date" value={due} onChange={(e) => setDue(e.target.value)} /></Field>
      </div>
    </Modal>
  );
}
