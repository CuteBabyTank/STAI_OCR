"use client";
// Wallet > Accounts (PRD §4): net-worth summary with privacy mask + Assets /
// Liabilities segmented control, and a responsive accounts grid colored by type.
import { useCallback, useEffect, useState } from "react";
import type { Account, NetWorth } from "../lib/types";
import { LIABILITY_TYPES } from "../lib/types";
import { money, acctMeta } from "../lib/format";
import { listAccounts, getNetWorth, deleteAccount, setAccountBalance } from "../lib/api";
import { useRefresh, broadcastRefresh } from "../lib/useRefresh";
import AccountModal from "../components/AccountModal";
import { Modal, Field, TextInput, Button, Segmented, FormError } from "../components/ui";

type Scope = "all" | "assets" | "liabilities";

export default function WalletPage() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [nw, setNw] = useState<NetWorth | null>(null);
  const [scope, setScope] = useState<Scope>("all");
  const [masked, setMasked] = useState(false);
  const [modal, setModal] = useState<{ mode: "add" | "edit" | "adjust"; acct?: Account } | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    Promise.all([listAccounts(), getNetWorth()])
      .then(([a, n]) => {
        setAccounts(a);
        setNw(n);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => load(), [load]);
  useRefresh(load);

  const show = (v: number, cur?: string | null) => (masked ? "••••••" : money(v, cur));
  const headline = nw ? (scope === "assets" ? nw.assets : scope === "liabilities" ? nw.liabilities : nw.net) : 0;

  const shown = accounts.filter((a) => {
    if (scope === "all") return true;
    const isLiab = LIABILITY_TYPES.includes(a.type);
    return scope === "liabilities" ? isLiab : !isLiab;
  });

  const remove = async (a: Account) => {
    if (!confirm(`Delete “${a.name}”? This cannot be undone.`)) return;
    try {
      await deleteAccount(a.id);
      broadcastRefresh(); // reloads this page *and* the global FAB's account list
    } catch (e: any) {
      alert(e.message);
    }
  };

  return (
    <>
      <main>
        <header>
          <div>
            <h1>Accounts</h1>
            <p className="subhead">Your cash, cards, and investments in one place</p>
          </div>
          <button className="btn-primary" onClick={() => setModal({ mode: "add" })}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M12 5v14M5 12h14" strokeLinecap="round" /></svg>
            Add account
          </button>
        </header>

        {/* Net worth summary */}
        <div className="card nw-card">
          <div className="nw-top">
            <div>
              <p className="stat-label">Net worth</p>
              <div className={"nw-figure" + (masked ? " masked" : "")}>{show(headline)}</div>
              {nw && !masked && (
                <p className="stat-sub">
                  Assets {money(nw.assets)} · Liabilities {money(nw.liabilities)}
                </p>
              )}
            </div>
            <button className="eye-btn" onClick={() => setMasked((m) => !m)} aria-label="Toggle privacy">
              {masked ? (
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M17.94 17.94A10 10 0 0 1 12 20C5 20 1 12 1 12a18 18 0 0 1 5.06-5.94M9.9 4.24A9 9 0 0 1 12 4c7 0 11 8 11 8a18 18 0 0 1-2.16 3.19M1 1l22 22M9.5 9.5a3 3 0 0 0 4 4" strokeLinecap="round" /></svg>
              ) : (
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" /><circle cx="12" cy="12" r="3" /></svg>
              )}
            </button>
          </div>
          <Segmented<Scope>
            value={scope}
            onChange={setScope}
            options={[
              { value: "all", label: "All" },
              { value: "assets", label: "Assets" },
              { value: "liabilities", label: "Liabilities" },
            ]}
          />
        </div>

        {/* Accounts grid */}
        {loading ? (
          <div className="empty-note">Loading…</div>
        ) : shown.length === 0 ? (
          <div className="card empty-note">
            No accounts yet. Click <strong>Add account</strong> to create your first one.
          </div>
        ) : (
          <div className="acct-grid">
            {shown.map((a) => {
              const meta = acctMeta(a.type);
              const neg = a.balance < 0;
              const isDefaultCash = a.name.trim().toLowerCase() === "cash" && a.type === "debit";
              return (
                <div key={a.id} className="acct-card" style={{ ["--acct-c" as any]: meta.color }}>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
                    <span className="acct-type-pill" style={{ background: meta.color }}>{meta.label}</span>
                    {isDefaultCash && (
                      <span className="acct-type-pill" style={{ background: "var(--ink-3)" }}>Default</span>
                    )}
                  </div>
                  <div>
                    <p className="acct-name">{a.name}</p>
                    <div className="acct-bal" style={{ color: neg ? "var(--negative)" : "var(--ink)" }}>
                      {masked ? "••••" : money(a.balance, a.currency)}
                    </div>
                    <div style={{ fontSize: 12, color: "var(--ink-3)", marginTop: 2 }}>
                      {a.currency || "PHP"}
                      {isDefaultCash && " · default for receipts with no account"}
                      {!a.include_in_totals && " · excluded from totals"}
                    </div>
                  </div>
                  <div className="acct-actions">
                    <button className="mini-btn" onClick={() => setModal({ mode: "edit", acct: a })}>Edit</button>
                    <button className="mini-btn" onClick={() => setModal({ mode: "adjust", acct: a })}>Adjust</button>
                    <button className="mini-btn danger" onClick={() => remove(a)}>Delete</button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </main>

      {modal?.mode === "add" && <AccountModal onClose={() => setModal(null)} onSaved={broadcastRefresh} />}
      {modal?.mode === "edit" && <AccountModal edit={modal.acct} onClose={() => setModal(null)} onSaved={broadcastRefresh} />}
      {modal?.mode === "adjust" && modal.acct && (
        <BalanceAdjustModal acct={modal.acct} onClose={() => setModal(null)} onSaved={broadcastRefresh} />
      )}
    </>
  );
}

function BalanceAdjustModal({ acct, onClose, onSaved }: { acct: Account; onClose: () => void; onSaved: () => void }) {
  const [value, setValue] = useState(String(acct.balance));
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    setErr(null);
    try {
      await setAccountBalance(acct.id, Number(value) || 0);
      onSaved();
      onClose();
    } catch (e: any) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      title={`Adjust balance — ${acct.name}`}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" onClick={submit} disabled={busy}>Set balance</Button>
        </>
      }
    >
      <FormError message={err} />
      <p style={{ margin: 0, fontSize: 13, color: "var(--ink-2)" }}>
        Overwrites the balance directly, without logging a transaction. Useful for reconciling stock/crypto values.
      </p>
      <Field label="New balance">
        <TextInput type="number" step="0.01" autoFocus value={value} onChange={(e) => setValue(e.target.value)} />
      </Field>
    </Modal>
  );
}
