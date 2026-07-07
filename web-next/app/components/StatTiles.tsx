"use client";
import type { Analytics, MoMField } from "../lib/types";
import { money } from "../lib/format";

// Headline tiles: Net / Income / Expenses / Receipts. Income + Expenses + Net each
// carry a month-over-month delta. Delta color follows *meaning* (more income good,
// more expense bad), never the raw direction — and always ships an arrow glyph so
// it's not color-alone.
function Delta({ mom, goodWhen, label }: { mom: MoMField; goodWhen: "up" | "down"; label: string | null }) {
  // pct is undefined when the prior period had nothing to compare against.
  if (mom.pct == null || !label) {
    if (mom.prev === 0 && mom.current > 0 && label) {
      const good = goodWhen === "up";
      return <p className={"stat-delta " + (good ? "good" : "bad")}><span className="arrow">▲</span>new <span className="delta-label">vs {label}</span></p>;
    }
    return <p className="stat-sub">no comparison yet</p>;
  }
  const up = mom.pct > 0;
  const flat = mom.pct === 0;
  const good = flat ? null : (up ? goodWhen === "up" : goodWhen === "down");
  const cls = good == null ? "flat" : good ? "good" : "bad";
  const arrow = flat ? "→" : up ? "▲" : "▼";
  return (
    <p className={"stat-delta " + cls}>
      <span className="arrow">{arrow}</span>
      {Math.abs(mom.pct)}% <span className="delta-label">vs {label}</span>
    </p>
  );
}

export default function StatTiles({ a }: { a: Analytics | null }) {
  const cur = a?.currency;
  const net = a?.net_total ?? 0;
  return (
    <section className="stat-grid four">
      <div className={"card accent" + (net < 0 ? " danger" : "")}>
        <p className="stat-label">Net saved</p>
        <p className="stat-value num">{money(net, cur)}</p>
        {a ? <Delta mom={a.mom.net} goodWhen="up" label={a.mom.label} /> : <p className="stat-sub">income − expenses</p>}
      </div>
      <div className="card">
        <p className="stat-label">Income</p>
        <p className="stat-value num pos">{money(a?.income_total, cur)}</p>
        {a ? <Delta mom={a.mom.income} goodWhen="up" label={a.mom.label} /> : <p className="stat-sub">money in</p>}
      </div>
      <div className="card">
        <p className="stat-label">Expenses</p>
        <p className="stat-value num">{money(a?.expense_total, cur)}</p>
        {a ? <Delta mom={a.mom.expense} goodWhen="down" label={a.mom.label} /> : <p className="stat-sub">money out</p>}
      </div>
      <div className="card">
        <p className="stat-label">Receipts</p>
        <p className="stat-value num">{a?.receipt_count ?? 0}</p>
        <p className="stat-sub">{a?.mixed_currency ? "⚠ multiple currencies" : "this period"}</p>
      </div>
    </section>
  );
}
