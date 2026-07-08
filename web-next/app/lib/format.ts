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

// Measured OCR confidence (0..1) -> display metadata; null when there is no score.
export function confMeta(p?: number | null) {
  if (p == null || isNaN(p)) return null;
  const level = p >= 0.85 ? "hi" : p >= 0.65 ? "mid" : "lo";
  const label = level === "hi" ? "high" : level === "mid" ? "medium" : "low";
  return { pct: Math.round(p * 100), level, label };
}

// Human labels for the confidence breakdown keys.
export const CONF_FIELD_LABELS: Record<string, string> = {
  vendor_name: "Vendor", vendor_tin: "Tax ID", vendor_address: "Address",
  receipt_number: "Receipt no.", receipt_date: "Date", currency: "Currency",
  category: "Category", subtotal: "Subtotal", vatable_sales: "Taxable sales",
  vat_exempt_sales: "Tax-exempt", zero_rated_sales: "Zero-rated",
  vat_amount: "Tax / VAT", discount: "Discount", discount_type: "Discount type",
  total_amount: "Total", cash: "Cash", change: "Change",
};
