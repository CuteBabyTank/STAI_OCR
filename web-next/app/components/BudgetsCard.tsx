"use client";
import { useState } from "react";
import type { BudgetRow } from "../lib/types";
import { CAT_ORDER, catMeta, money } from "../lib/format";

// Per-category monthly budgets with progress bars. Status colors (good/over) are
// reserved and always paired with a label, never color-alone.
export default function BudgetsCard({
  budgets, currency, monthLabel, onSave,
}: {
  budgets: BudgetRow[];
  currency: string | null;
  monthLabel: string;
  onSave: (category: string, limit: number) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const byCat = new Map(budgets.map((b) => [b.category, b]));

  return (
    <div className="card">
      <div className="card-head">
        <p className="card-title">Budgets · {monthLabel}</p>
        <button className="link" onClick={() => setEditing((e) => !e)}>
          {editing ? "Done" : "Edit"}
        </button>
      </div>
      <ul className="budget-list">
        {CAT_ORDER.map((cat) => {
          const b = byCat.get(cat);
          const limit = b?.limit ?? 0;
          const spent = b?.spent ?? 0;
          const pct = limit > 0 ? Math.min((spent / limit) * 100, 100) : 0;
          const over = limit > 0 && spent > limit;
          const meta = catMeta(cat);
          return (
            <li key={cat} className="budget-row">
              <div className="budget-top">
                <span className="budget-cat">
                  <span className="dot" style={{ background: meta.color }} />{cat}
                </span>
                {editing ? (
                  <BudgetInput
                    initial={limit}
                    onCommit={(v) => onSave(cat, v)}
                  />
                ) : limit > 0 ? (
                  <span className="budget-nums num">
                    {money(spent, currency, 0)} <span className="budget-of">/ {money(limit, currency, 0)}</span>
                  </span>
                ) : (
                  <span className="budget-unset">not set</span>
                )}
              </div>
              {limit > 0 && !editing && (
                <>
                  <div className="budget-track">
                    <div
                      className={"budget-fill" + (over ? " over" : "")}
                      style={{ width: `${pct}%`, background: over ? "var(--negative)" : meta.color }}
                    />
                  </div>
                  <div className={"budget-status" + (over ? " over" : "")}>
                    {over
                      ? `⚠ ${money(spent - limit, currency, 0)} over`
                      : `${money(limit - spent, currency, 0)} left`}
                  </div>
                </>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function BudgetInput({ initial, onCommit }: { initial: number; onCommit: (v: number) => void }) {
  const [val, setVal] = useState(initial ? String(initial) : "");
  const commit = () => {
    const n = parseFloat(val);
    if (!isNaN(n) && n !== initial) onCommit(n);
  };
  return (
    <input
      className="budget-input num"
      type="number"
      min={0}
      value={val}
      placeholder="0"
      onChange={(e) => setVal(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
    />
  );
}
