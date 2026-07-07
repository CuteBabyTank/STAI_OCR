"use client";
import {
  Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import type { Bar as BarPoint } from "../lib/types";
import { moneyCompact, money } from "../lib/format";
import { useThemeColors } from "../lib/useThemeColors";

// Cashflow over time as an overlapping bar chart: each period draws a wide income
// bar (background) with the expense bar nested inside it (foreground, narrower),
// so you read "how much of what came in went back out" at a glance. No line.
// The focused period is highlighted; the rest are dimmed for context.
const INCOME_W = 46;
const EXPENSE_W = 22;

export default function CashflowChart({
  bars, currency, focusKey,
}: { bars: BarPoint[]; currency: string | null; focusKey: string }) {
  const c = useThemeColors();
  if (!c) return <div className="chart-skeleton" />;

  const single = bars.length <= 1; // year mode / one period → no dimming
  const op = (key: string) => (single || key === focusKey ? 1 : 0.32);

  const tooltip = ({ active, payload, label }: any) => {
    if (!active || !payload?.length) return null;
    const row = payload[0].payload as BarPoint;
    const net = row.income - row.expense;
    return (
      <div className="rc-tip">
        <div className="rc-tip-head">{label}</div>
        <div className="rc-tip-row"><span className="rc-swatch" style={{ background: c.positive }} />Income<b>{money(row.income, currency)}</b></div>
        <div className="rc-tip-row"><span className="rc-swatch" style={{ background: c.accent }} />Expense<b>{money(row.expense, currency)}</b></div>
        <div className="rc-tip-row"><span className="rc-swatch" style={{ background: net >= 0 ? c.positive : c.negative }} />Net<b>{money(net, currency)}</b></div>
      </div>
    );
  };

  return (
    <ResponsiveContainer width="100%" height={260}>
      {/* barGap = -(income+expense)/2 centres the narrow expense bar over the wide
          income bar so they overlap concentrically instead of sitting side by side. */}
      <BarChart data={bars} margin={{ top: 8, right: 6, bottom: 0, left: 6 }} barGap={-(INCOME_W + EXPENSE_W) / 2}>
        <CartesianGrid vertical={false} stroke={c.border} strokeDasharray="3 3" />
        <XAxis dataKey="label" tickLine={false} axisLine={{ stroke: c.border }}
          tick={{ fill: c["ink-3"], fontSize: 12 }} />
        <YAxis tickLine={false} axisLine={false} width={48}
          tick={{ fill: c["ink-3"], fontSize: 11 }}
          tickFormatter={(v) => moneyCompact(v, currency)} />
        <Tooltip cursor={{ fill: c.border, opacity: 0.25 }} content={tooltip} />
        <Bar dataKey="income" name="Income" fill={c.positive} radius={[4, 4, 0, 0]} barSize={INCOME_W} isAnimationActive={false}>
          {bars.map((b) => <Cell key={b.key} fillOpacity={op(b.key)} />)}
        </Bar>
        <Bar dataKey="expense" name="Expense" fill={c.accent} radius={[4, 4, 0, 0]} barSize={EXPENSE_W} isAnimationActive={false}>
          {bars.map((b) => <Cell key={b.key} fillOpacity={op(b.key)} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
