// Formatting + category helpers shared across the dashboard.
import type { Category } from "./types";

export const CAT_ORDER: Category[] = ["Food", "Shopping", "Health", "Other"];

export const CAT_META: Record<string, { color: string; emoji: string }> = {
  Food: { color: "var(--cat-food)", emoji: "🍜" },
  Shopping: { color: "var(--cat-shopping)", emoji: "🛍️" },
  Health: { color: "var(--cat-health)", emoji: "💊" },
  Other: { color: "var(--cat-other)", emoji: "•" },
};
export const catMeta = (c?: string | null) => CAT_META[c || "Other"] || CAT_META.Other;

const SYMBOLS: Record<string, string> = {
  PHP: "₱", USD: "$", EUR: "€", GBP: "£", JPY: "¥", INR: "₹",
};
export const sym = (cur?: string | null) =>
  (cur && SYMBOLS[cur]) || (cur ? cur + " " : "₱");

export const money = (n: number | null | undefined, cur?: string | null, dp = 2) =>
  sym(cur) +
  Number(n || 0).toLocaleString(undefined, { minimumFractionDigits: dp, maximumFractionDigits: dp });

// Compact money for chart axes / tight labels: ₱1.2k, ₱3.4M.
export function moneyCompact(n: number | null | undefined, cur?: string | null) {
  const v = Number(n || 0);
  const a = Math.abs(v);
  const s = sym(cur);
  if (a >= 1_000_000) return s + (v / 1_000_000).toFixed(1).replace(/\.0$/, "") + "M";
  if (a >= 1_000) return s + (v / 1_000).toFixed(1).replace(/\.0$/, "") + "k";
  return s + v.toLocaleString(undefined, { maximumFractionDigits: 0 });
}

export function fmtDate(iso?: string | null) {
  if (!iso) return "Undated";
  const d = new Date(iso + "T00:00:00");
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export const monthKey = (iso?: string | null) =>
  iso && iso.length >= 7 && /^\d{4}/.test(iso) ? iso.slice(0, 7) : "Unknown";

export function monthLabel(key: string) {
  if (key === "Unknown") return "Undated";
  const d = new Date(key + "-01T00:00:00");
  return isNaN(d.getTime())
    ? key
    : d.toLocaleDateString(undefined, { month: "long", year: "numeric" });
}

// Short month label for chart axes: "2026-06" -> "Jun".
export function monthShort(key: string) {
  const d = new Date(key + "-01T00:00:00");
  return isNaN(d.getTime()) ? key : d.toLocaleDateString(undefined, { month: "short" });
}
