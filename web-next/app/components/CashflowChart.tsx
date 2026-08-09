"use client";
import {
  Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import type { Bar as BarPoint } from "../lib/types";
import { moneyCompact, money } from "../lib/format";
import { useThemeColors } from "../lib/useThemeColors";
import { useIsPhone } from "../lib/useMediaQuery";

// Cashflow over time as an overlapping bar chart: each period draws a wide income
// bar (background) with the expense bar nested inside it (foreground, narrower),
// so you read "how much of what came in went back out" at a glance. No line.
// The focused period is highlighted; the rest are dimmed for context.
//
// Bar widths are fixed pixel values, so on a phone twelve 46px bars want ~550px
// of plot area inside a ~300px card and recharts crushes them into each other.
// The phone variant narrows the bars and the Y axis to keep the same shape at a
// third of the width.
const INCOME_W = 46;
const EXPENSE_W = 22;
const INCOME_W_SM = 18;
const EXPENSE_W_SM = 8;

export default function CashflowChart({
  bars, currency, focusKey,
}: { bars: BarPoint[]; currency: string | null; focusKey: string }) {
  const c = useThemeColors();
  const phone = useIsPhone();
  const incomeW = phone ? INCOME_W_SM : INCOME_W;
  const expenseW = phone ? EXPENSE_W_SM : EXPENSE_W;
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
    <ResponsiveContainer width="100%" height={phone ? 210 : 260}>
      {/* barGap = -(income+expense)/2 centres the narrow expense bar over the wide
          income bar so they overlap concentrically instead of sitting side by side. */}
      <BarChart data={bars} margin={{ top: 8, right: 6, bottom: 0, left: 6 }} barGap={-(incomeW + expenseW) / 2}>
        <CartesianGrid vertical={false} stroke={c.border} strokeDasharray="3 3" />
        {/* Every other label on a phone: twelve month names will not fit across
            300px, and recharts drops them unpredictably if left to decide. */}
        <XAxis dataKey="label" tickLine={false} axisLine={{ stroke: c.border }}
          interval={phone && bars.length > 6 ? 1 : 0}
          tick={{ fill: c["ink-3"], fontSize: phone ? 10 : 12 }} />
        <YAxis tickLine={false} axisLine={false} width={phone ? 36 : 48}
          tick={{ fill: c["ink-3"], fontSize: phone ? 10 : 11 }}
          tickFormatter={(v) => moneyCompact(v, currency)} />
        <Tooltip cursor={{ fill: c.border, opacity: 0.25 }} content={tooltip} />
        <Bar dataKey="income" name="Income" fill={c.positive} radius={[4, 4, 0, 0]} barSize={incomeW} isAnimationActive={false}>
          {bars.map((b) => <Cell key={b.key} fillOpacity={op(b.key)} />)}
        </Bar>
        <Bar dataKey="expense" name="Expense" fill={c.accent} radius={[4, 4, 0, 0]} barSize={expenseW} isAnimationActive={false}>
          {bars.map((b) => <Cell key={b.key} fillOpacity={op(b.key)} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
