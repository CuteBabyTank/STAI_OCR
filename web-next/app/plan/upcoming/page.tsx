"use client";
// Plan > Upcoming (PRD §6): read-only aggregation of action items — recurring
// expenses, recurring income, and debt dues — each with an overdue/countdown badge.
import { useEffect, useState } from "react";
import type { Upcoming } from "../../lib/types";
import { money, fmtDate } from "../../lib/format";
import { getUpcoming } from "../../lib/api";
import { DueBadge } from "../../components/ui";

export default function UpcomingPage() {
  const [data, setData] = useState<Upcoming | null>(null);
  useEffect(() => { getUpcoming().then(setData).catch(() => setData(null)); }, []);

  const Card = ({ title, rows }: { title: string; rows: { id: number; label: string; amount: number; due: string | null; days: number | null | undefined }[] }) => (
    <div className="card">
      <p className="section-title">{title}</p>
      {rows.length === 0 ? <div className="empty-note">Nothing upcoming.</div> : (
        <div className="plan-list">
          {rows.map((r) => (
            <div key={r.id} className="plan-row">
              <div className="plan-main">
                <div className="plan-title">{r.label}</div>
                <div className="plan-sub">{fmtDate(r.due)}</div>
              </div>
              <div className="plan-right">
                <div className="plan-num">{money(r.amount)}</div>
                <DueBadge days={r.days} />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );

  return (
    <>
      <main>
        <header>
          <div>
            <h1>Upcoming</h1>
            <p className="subhead">Dues and recurring items on the horizon</p>
          </div>
        </header>

        <Card title="Credit dues & debts" rows={(data?.debts || []).map((d) => ({ id: d.id, label: d.name, amount: d.outstanding, due: d.due_date, days: d.days_to_due }))} />
        <Card title="Recurring expenses" rows={(data?.recurring_expenses || []).map((r) => ({ id: r.id, label: r.name || "Recurring", amount: r.amount, due: r.next_due, days: r.days_to_due }))} />
        <Card title="Recurring income" rows={(data?.recurring_income || []).map((r) => ({ id: r.id, label: r.name || "Recurring", amount: r.amount, due: r.next_due, days: r.days_to_due }))} />
      </main>
    </>
  );
}
