"use client";
// Plan > Goal Activity (PRD §14): log deposits/withdrawals against a goal. Submitting
// updates the goal's current amount and the debit account balance in one step.
import { useCallback, useEffect, useState } from "react";
import type { Account, Goal } from "../../lib/types";
import { money } from "../../lib/format";
import { listGoals, goalActivity, listAccounts } from "../../lib/api";
import { useRefresh } from "../../lib/useRefresh";
import ActivityModal from "../../components/ActivityModal";
import { Progress } from "../../components/ui";
import EmptyState from "../../components/empty";

export default function GoalActivityPage() {
  const [goals, setGoals] = useState<Goal[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [active, setActive] = useState<Goal | null>(null);

  const load = useCallback(() => {
    listGoals().then(setGoals).catch(() => setGoals([]));
    listAccounts().then(setAccounts).catch(() => {});
  }, []);
  useEffect(() => load(), [load]);
  useRefresh(load);

  return (
    <>
      <main>
        <header>
          <div>
            <h1>Goal activity</h1>
            <p className="subhead">Fund or withdraw from a goal</p>
          </div>
        </header>

        <div className="card">
          {goals.length === 0 ? <EmptyState
            glyphs={["target", "coins", "arrows"]}
            title="No goals to show"
            sub="Create a goal and its contributions appear here."
            action={{ label: "Go to goals", href: "/plan/goals" }}
          /> : (
            <div className="plan-list">
              {goals.map((g) => (
                <div key={g.id} className="plan-row">
                  <div className="plan-main">
                    <div className="plan-title">{g.title}</div>
                    <div className="plan-sub">{money(g.current_amount, g.currency)} of {money(g.target_amount, g.currency)}</div>
                    <div className="plan-bar"><Progress pct={g.pct} color="var(--positive)" /></div>
                  </div>
                  <button className="mini-btn" onClick={() => setActive(g)}>Log activity</button>
                </div>
              ))}
            </div>
          )}
        </div>
      </main>

      {active && (
        <ActivityModal
          title={`Goal activity — ${active.title}`}
          accounts={accounts}
          types={[{ value: "deposit", label: "Deposit" }, { value: "withdrawal", label: "Withdrawal" }]}
          onSubmit={(p) => goalActivity(active.id, p)}
          onClose={() => setActive(null)}
          onSaved={load}
        />
      )}
    </>
  );
}
