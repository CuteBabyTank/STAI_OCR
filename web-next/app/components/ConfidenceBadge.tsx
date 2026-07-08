"use client";
import { confMeta } from "../lib/format";

// A color-coded pill showing MEASURED OCR confidence for a value (0..1).
// The score is the vision model's average token probability for the field(s) —
// a real read of its output distribution, not a number the model made up.
// Renders nothing when there is no score (e.g. receipts saved before this existed).
export default function ConfidenceBadge({
  value,
  size = "sm",
  showLabel = false,
}: {
  value?: number | null;
  size?: "sm" | "md";
  showLabel?: boolean;
}) {
  const m = confMeta(value);
  if (!m) return null;
  return (
    <span
      className={`conf-badge ${m.level} ${size}`}
      title={
        `Measured OCR confidence: ${m.pct}% (${m.label}). Average token probability ` +
        `the vision model assigned while reading this — a real read of its output ` +
        `distribution, not a self-rating.`
      }
    >
      <span className="conf-dot" />
      {m.pct}%{showLabel ? ` · ${m.label}` : ""}
    </span>
  );
}
