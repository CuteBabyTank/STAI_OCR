"use client";
// Statistics (PRD §20): configurable analytics — Period / Measure / Trend style /
// Focus filters over a trend chart, a category breakdown donut, an accounts bar,
// and lightweight rules-based insights. All computed client-side from the ledger.
import { useEffect, useMemo, useState } from "react";
import {
  ResponsiveContainer, AreaChart, Area, BarChart, Bar, LineChart, Line,
  XAxis, YAxis, Tooltip, CartesianGrid,
} from "recharts";
import type { Account, Transaction } from "../lib/types";
import { money, moneyCompact } from "../lib/format";
import { listTransactions, listAccounts } from "../lib/api";
import { Segmented } from "../components/ui";
import EmptyState from "../components/empty";

type Period = "30d" | "90d" | "12m" | "all";
type Measure = "amount" | "count";
type Style = "area" | "bar" | "line";
type Focus = "all" | "expense" | "income";

const DONUT = ["#6366F1", "#0EA5E9", "#22C55E", "#EAB308", "#EC4899", "#F97316", "#94A3B8"];

export default function StatisticsPage() {
  const [txns, setTxns] = useState<Transaction[]>([]);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [period, setPeriod] = useState<Period>("90d");
  const [measure, setMeasure] = useState<Measure>("amount");
  const [style, setStyle] = useState<Style>("area");
  const [focus, setFocus] = useState<Focus>("all");

  useEffect(() => {
    listTransactions({ limit: 5000 }).then(setTxns).catch(() => setTxns([]));
    listAccounts(true).then(setAccounts).catch(() => {});
  }, []);

  const since = useMemo(() => {
    if (period === "all") return "0000-00-00";
    const d = new Date();
    if (period === "30d") d.setDate(d.getDate() - 30);
    else if (period === "90d") d.setDate(d.getDate() - 90);
    else d.setMonth(d.getMonth() - 12);
    return d.toISOString().slice(0, 10);
  }, [period]);

  const scoped = useMemo(
    () =>
      txns.filter((t) => {
        if (t.kind === "transfer") return false;
        if (focus !== "all" && t.kind !== focus) return false;
        const d = (t.occurred_at || "").slice(0, 10);
        return d >= since;
      }),
    [txns, focus, since]
  );

  // Trend: bucket by month for 12m/all, else by day.
  const trend = useMemo(() => {
    const byDay = period === "30d" || period === "90d";
    const buckets = new Map<string, { expense: number; income: number; count: number }>();
    for (const t of scoped) {
      const d = (t.occurred_at || "").slice(0, byDay ? 10 : 7);
      if (!d) continue;
      const b = buckets.get(d) || { expense: 0, income: 0, count: 0 };
      if (t.kind === "expense") b.expense += t.amount;
      else if (t.kind === "income") b.income += t.amount;
      b.count += 1;
      buckets.set(d, b);
    }
    return [...buckets.entries()]
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([k, v]) => ({
        key: k,
        value: measure === "count" ? v.count : focus === "income" ? v.income : focus === "expense" ? v.expense : v.income - v.expense,
      }));
  }, [scoped, period, measure, focus]);

  // Breakdown by category (expense-focused).
  const breakdown = useMemo(() => {
    const by = new Map<string, number>();
    for (const t of scoped) {
      if (focus === "income" ? t.kind !== "income" : t.kind !== "expense") continue;
      const key = t.category_name || "Uncategorized";
      by.set(key, (by.get(key) || 0) + (measure === "count" ? 1 : t.amount));
    }
    const rows = [...by.entries()].sort((a, b) => b[1] - a[1]);
    const total = rows.reduce((s, r) => s + r[1], 0);
    const top = rows.slice(0, 6);
    const other = rows.slice(6).reduce((s, r) => s + r[1], 0);
    if (other > 0) top.push(["Other", other]);
    return { rows: top, total };
  }, [scoped, focus, measure]);

  // Accounts totals (by activity in the period).
  const acctBars = useMemo(() => {
    const by = new Map<number, number>();
    for (const t of scoped) {
      if (t.account_id == null) continue;
      by.set(t.account_id, (by.get(t.account_id) || 0) + (measure === "count" ? 1 : t.amount));
    }
    return accounts
      .map((a) => ({ name: a.name, value: by.get(a.id) || 0 }))
      .filter((x) => x.value > 0)
      .sort((a, b) => b.value - a.value)
      .slice(0, 8);
  }, [scoped, accounts, measure]);

  const insights = useMemo(() => {
    const out: string[] = [];
    const inc = scoped.filter((t) => t.kind === "income").reduce((s, t) => s + t.amount, 0);
    const exp = scoped.filter((t) => t.kind === "expense").reduce((s, t) => s + t.amount, 0);
    if (inc || exp) {
      const net = inc - exp;
      out.push(`Net ${net >= 0 ? "positive" : "negative"} of ${money(Math.abs(net))} — income ${money(inc)} vs expense ${money(exp)}.`);
    }
    if (breakdown.rows.length) {
      const [name, val] = breakdown.rows[0];
      const pct = breakdown.total ? Math.round((val / breakdown.total) * 100) : 0;
      out.push(`Top bucket is ${name}, ${pct}% of the total.`);
    }
    if (exp && inc) {
      const rate = Math.round((1 - exp / inc) * 100);
      out.push(rate >= 0 ? `You saved about ${rate}% of income this period.` : `Spending exceeded income by ${Math.abs(rate)}%.`);
    }
    if (!out.length) out.push("No activity in this period yet.");
    return out;
  }, [scoped, breakdown]);

  const fmtVal = (v: number) => (measure === "count" ? String(v) : moneyCompact(v));
  const label = (k: string) => (k.length === 7 ? k : k.slice(5));

  return (
    <>
      <main>
        <header>
          <div>
            <h1>Statistics</h1>
            <p className="subhead">Understand your money over time</p>
          </div>
        </header>

        <div className="ledger-toolbar">
          <Segmented<Period> value={period} onChange={setPeriod} options={[
            { value: "30d", label: "30D" }, { value: "90d", label: "90D" }, { value: "12m", label: "12M" }, { value: "all", label: "All" }]} />
          <Segmented<Focus> value={focus} onChange={setFocus} options={[
            { value: "all", label: "All" }, { value: "expense", label: "Expense" }, { value: "income", label: "Income" }]} />
          <Segmented<Measure> value={measure} onChange={setMeasure} options={[
            { value: "amount", label: "Amount" }, { value: "count", label: "Count" }]} />
          <Segmented<Style> value={style} onChange={setStyle} options={[
            { value: "area", label: "Area" }, { value: "bar", label: "Bar" }, { value: "line", label: "Line" }]} />
        </div>

        {/* Trend */}
        <div className="card">
          <p className="section-title">Trend</p>
          <div style={{ width: "100%", height: 260 }}>
            <ResponsiveContainer>
              {style === "bar" ? (
                <BarChart data={trend}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis dataKey="key" tickFormatter={label} fontSize={11} stroke="var(--ink-3)" />
                  <YAxis tickFormatter={fmtVal} fontSize={11} stroke="var(--ink-3)" width={54} />
                  <Tooltip formatter={(v: number) => fmtVal(v)} />
                  <Bar dataKey="value" fill="#6366F1" radius={[4, 4, 0, 0]} />
                </BarChart>
              ) : style === "line" ? (
                <LineChart data={trend}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis dataKey="key" tickFormatter={label} fontSize={11} stroke="var(--ink-3)" />
                  <YAxis tickFormatter={fmtVal} fontSize={11} stroke="var(--ink-3)" width={54} />
                  <Tooltip formatter={(v: number) => fmtVal(v)} />
                  <Line dataKey="value" stroke="#6366F1" strokeWidth={2} dot={false} />
                </LineChart>
              ) : (
                <AreaChart data={trend}>
                  <defs>
                    <linearGradient id="g" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#6366F1" stopOpacity={0.35} />
                      <stop offset="100%" stopColor="#6366F1" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis dataKey="key" tickFormatter={label} fontSize={11} stroke="var(--ink-3)" />
                  <YAxis tickFormatter={fmtVal} fontSize={11} stroke="var(--ink-3)" width={54} />
                  <Tooltip formatter={(v: number) => fmtVal(v)} />
                  <Area dataKey="value" stroke="#6366F1" strokeWidth={2} fill="url(#g)" />
                </AreaChart>
              )}
            </ResponsiveContainer>
          </div>
        </div>

        <div className="grid-2">
          {/* Breakdown donut */}
          <div className="card">
            <p className="section-title">Breakdown</p>
            {breakdown.rows.length === 0 ? (
              <EmptyState
                size="panel"
                glyphs={["chart", "tag", "coins"]}
                title="Nothing to break down"
                sub="No spending in this period yet."
              />
            ) : (
              <div style={{ display: "flex", gap: 20, alignItems: "center", flexWrap: "wrap" }}>
                <div style={{
                  width: 140, height: 140, borderRadius: "50%", flexShrink: 0,
                  background: `conic-gradient(${breakdown.rows.map((r, i) => {
                    const start = breakdown.rows.slice(0, i).reduce((s, x) => s + x[1], 0) / breakdown.total * 100;
                    const end = start + r[1] / breakdown.total * 100;
                    return `${DONUT[i % DONUT.length]} ${start}% ${end}%`;
                  }).join(", ")})`,
                  display: "grid", placeItems: "center",
                }}>
                  <div style={{ width: 92, height: 92, borderRadius: "50%", background: "var(--surface)", display: "grid", placeItems: "center", textAlign: "center" }}>
                    <div>
                      <div style={{ fontSize: 11, color: "var(--ink-3)" }}>Total</div>
                      <div style={{ fontSize: 14, fontWeight: 620 }}>{fmtVal(breakdown.total)}</div>
                    </div>
                  </div>
                </div>
                <div className="legend" style={{ flex: 1, minWidth: 160 }}>
                  {breakdown.rows.map((r, i) => (
                    <div key={r[0]} className="legend-row">
                      <span className="legend-dot" style={{ background: DONUT[i % DONUT.length] }} />
                      <span className="legend-name">{r[0]}</span>
                      <span className="legend-val">{fmtVal(r[1])}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Accounts bar */}
          <div className="card">
            <p className="section-title">Accounts</p>
            {acctBars.length === 0 ? (
              <EmptyState
                size="panel"
                glyphs={["card", "chart", "arrows"]}
                title="No account activity"
                sub="Movements across accounts show up here."
              />
            ) : (
              <div style={{ width: "100%", height: 220 }}>
                <ResponsiveContainer>
                  <BarChart data={acctBars} layout="vertical" margin={{ left: 8 }}>
                    <XAxis type="number" tickFormatter={fmtVal} fontSize={11} stroke="var(--ink-3)" />
                    <YAxis type="category" dataKey="name" width={90} fontSize={11} stroke="var(--ink-3)" />
                    <Tooltip formatter={(v: number) => fmtVal(v)} />
                    <Bar dataKey="value" fill="#0EA5E9" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>
        </div>

        {/* Insights */}
        <div className="card">
          <p className="section-title">Insights</p>
          {insights.map((s, i) => (
            <div key={i} className="insight">
              <svg className="ico" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M12 2a7 7 0 0 0-4 12.7V17h8v-2.3A7 7 0 0 0 12 2zM9 21h6M10 17v4M14 17v4" strokeLinecap="round" strokeLinejoin="round" /></svg>
              {s}
            </div>
          ))}
        </div>
      </main>
    </>
  );
}
