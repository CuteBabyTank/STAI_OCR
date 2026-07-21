"use client";
// History (PRD §19): the full ledger with text search, a Kind segmented filter,
// a category dropdown, summary tiles that recompute on the active filter, and
// per-row edit / delete via a kebab menu.
import { useCallback, useEffect, useMemo, useState } from "react";
import type { Account, Transaction, TxnCategory, TxnKind } from "../lib/types";
import { money, signedMoney, fmtDate } from "../lib/format";
import { listTransactions, listAccounts, listCategories, deleteTransaction } from "../lib/api";
import { useRefresh } from "../lib/useRefresh";
import { ExpenseModal, IncomeModal } from "../components/TransactionModals";
import { Segmented, Select, TextInput } from "../components/ui";

type KindFilter = "all" | TxnKind;

export default function HistoryPage() {
  const [txns, setTxns] = useState<Transaction[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [categories, setCategories] = useState<TxnCategory[]>([]);
  const [kind, setKind] = useState<KindFilter>("all");
  const [catId, setCatId] = useState(0);
  const [search, setSearch] = useState("");
  const [menuId, setMenuId] = useState<number | null>(null);
  const [edit, setEdit] = useState<Transaction | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    Promise.all([listTransactions({ limit: 2000 }), listAccounts(true), listCategories()])
      .then(([t, a, c]) => {
        setTxns(t);
        setAccounts(a);
        setCategories(c);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => load(), [load]);
  useRefresh(load);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return txns.filter((t) => {
      if (kind !== "all" && t.kind !== kind) return false;
      if (catId && t.category_id !== catId) return false;
      if (q) {
        const hay = `${t.note || ""} ${t.category_name || ""} ${t.account_name || ""}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [txns, kind, catId, search]);

  const totals = useMemo(() => {
    let income = 0, expense = 0;
    for (const t of filtered) {
      if (t.kind === "income") income += t.amount;
      else if (t.kind === "expense") expense += t.amount;
    }
    return { income, expense };
  }, [filtered]);

  const remove = async (t: Transaction) => {
    setMenuId(null);
    if (!confirm("Delete this transaction?")) return;
    await deleteTransaction(t.id);
    load();
  };

  const rowMeta = (t: Transaction) => {
    if (t.kind === "income") return { sign: "+" as const, cls: "amt-pos", color: "var(--positive)", glyph: "+", bg: "color-mix(in srgb, var(--positive) 14%, transparent)" };
    if (t.kind === "expense") return { sign: "-" as const, cls: "amt-neg", color: "var(--negative)", glyph: "−", bg: "color-mix(in srgb, var(--negative) 14%, transparent)" };
    return { sign: undefined, cls: "", color: "var(--ink-2)", glyph: "⇄", bg: "var(--sunken)" };
  };

  return (
    <>
      <main>
        <header>
          <div>
            <h1>History</h1>
            <p className="subhead">{filtered.length} of {txns.length} transactions</p>
          </div>
        </header>

        {/* Summary tiles (recompute on filters) */}
        <div className="stat-grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
          <div className="card">
            <p className="stat-label">Income</p>
            <div className="stat-value" style={{ color: "var(--positive)" }}>{money(totals.income)}</div>
          </div>
          <div className="card">
            <p className="stat-label">Expense</p>
            <div className="stat-value" style={{ color: "var(--negative)" }}>{money(totals.expense)}</div>
          </div>
        </div>

        {/* Toolbar */}
        <div className="ledger-toolbar">
          <TextInput placeholder="Search notes, categories, accounts…" value={search} onChange={(e) => setSearch(e.target.value)} />
          <Segmented<KindFilter>
            value={kind}
            onChange={setKind}
            options={[
              { value: "all", label: "All" },
              { value: "expense", label: "Expense" },
              { value: "income", label: "Income" },
            ]}
          />
          <div style={{ minWidth: 180 }}>
            <Select value={catId} onChange={(e) => setCatId(Number(e.target.value))}>
              <option value={0}>All categories</option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </Select>
          </div>
        </div>

        {/* Ledger */}
        <div className="card">
          {loading ? (
            <div className="empty-note">Loading…</div>
          ) : filtered.length === 0 ? (
            <div className="empty-note">No transactions match these filters.</div>
          ) : (
            filtered.map((t) => {
              const m = rowMeta(t);
              return (
                <div key={t.id} className="ledger-row">
                  <div className="ledger-icon" style={{ background: m.bg, color: m.color }}>{m.glyph}</div>
                  <div className="ledger-main">
                    <div className="ledger-title">
                      {t.note || t.category_name || (t.kind === "transfer" ? "Transfer" : "Transaction")}
                    </div>
                    <div className="ledger-sub">
                      {t.kind === "transfer"
                        ? `${t.account_name || "—"} → ${t.to_account_name || "—"}`
                        : t.account_name || "—"}
                      {t.category_name && ` · ${t.category_name}`} · {fmtDate(t.occurred_at?.slice(0, 10))}
                    </div>
                  </div>
                  <div className={"ledger-amt " + m.cls}>
                    {t.kind === "transfer" ? money(t.amount, null) : signedMoney(t.amount, null, m.sign)}
                  </div>
                  <button className="kebab" onClick={() => setMenuId(menuId === t.id ? null : t.id)} aria-label="Actions">
                    <svg viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="5" r="1.6" /><circle cx="12" cy="12" r="1.6" /><circle cx="12" cy="19" r="1.6" /></svg>
                    {menuId === t.id && (
                      <div className="kebab-menu" onClick={(e) => e.stopPropagation()}>
                        {t.kind !== "transfer" && (
                          <button onClick={() => { setMenuId(null); setEdit(t); }}>Edit</button>
                        )}
                        <button className="danger" onClick={() => remove(t)}>Delete</button>
                      </div>
                    )}
                  </button>
                </div>
              );
            })
          )}
        </div>
      </main>

      {edit?.kind === "expense" && (
        <ExpenseModal accounts={accounts} categories={categories} edit={edit} onClose={() => setEdit(null)} onSaved={load} />
      )}
      {edit?.kind === "income" && (
        <IncomeModal accounts={accounts} edit={edit} onClose={() => setEdit(null)} onSaved={load} />
      )}
    </>
  );
}
