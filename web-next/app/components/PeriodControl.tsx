"use client";
import type { Granularity, Period } from "../lib/types";

// Top-of-dashboard period selector: a Month/Year granularity toggle plus ◀ ▶ to
// scroll through periods. Drives the scope of every panel below it.
//
// `monthOnly` drops the granularity toggle and keeps just the ◀ label ▶ nav, for
// callers that scope a single section to one month at a time (the home dashboard's
// Spending overview). The stepping, year-rollover and bounds logic below is shared
// rather than reimplemented there — getting "December → January" wrong in a second
// copy is exactly the kind of bug that hides until New Year.
export default function PeriodControl({
  period, onChange, monthOnly = false,
}: {
  period: Period;
  onChange: (next: { granularity: Granularity; year: number; month: number }) => void;
  monthOnly?: boolean;
}) {
  const { granularity, year, month, label, min_year, max_year } = period;

  // Bounds as absolute month indices so month-mode navigation rolls across years.
  const idx = year * 12 + (month - 1);
  const minIdx = min_year * 12;
  const maxIdx = max_year * 12 + 11;
  const atMin = granularity === "year" ? year <= min_year : idx <= minIdx;
  const atMax = granularity === "year" ? year >= max_year : idx >= maxIdx;

  const step = (dir: 1 | -1) => {
    if (granularity === "year") {
      onChange({ granularity, year: year + dir, month });
    } else {
      const ni = idx + dir;
      onChange({ granularity, year: Math.floor(ni / 12), month: (ni % 12) + 1 });
    }
  };

  const setGran = (g: Granularity) => onChange({ granularity: g, year, month });

  return (
    <div className="period-bar">
      {!monthOnly && (
        <div className="seg">
          <button className={"seg-btn" + (granularity === "all" ? " on" : "")} onClick={() => setGran("all")}>All time</button>
          <button className={"seg-btn" + (granularity === "month" ? " on" : "")} onClick={() => setGran("month")}>Month</button>
          <button className={"seg-btn" + (granularity === "year" ? " on" : "")} onClick={() => setGran("year")}>Year</button>
        </div>
      )}
      <div className="period-nav">
        {granularity === "all" ? (
          // All-time spans everything — nothing to scroll through, just the label.
          <span className="period-label">{label}</span>
        ) : (
          <>
            <button className="pn-btn" onClick={() => step(-1)} disabled={atMin} aria-label="Previous period">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M15 18l-6-6 6-6" /></svg>
            </button>
            <span className="period-label">{label}</span>
            <button className="pn-btn" onClick={() => step(1)} disabled={atMax} aria-label="Next period">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M9 18l6-6-6-6" /></svg>
            </button>
          </>
        )}
      </div>
    </div>
  );
}
