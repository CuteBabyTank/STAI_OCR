// Client-side natural-language parser for Quick chat (PRD §2.2).
// Maps free text like "1.2k lunch yesterday" or "+5000 salary" into a draft
// transaction. Deliberately lightweight and dependency-free; the server-side
// LLM parser (Phase 4) can supersede it, but this keeps Quick entry working now.
import type { Account, TxnCategory, TxnKind } from "./types";

export interface QuickDraft {
  kind: TxnKind;
  amount: number;
  note: string;
  categoryId: number | null;
  accountId: number | null;
  toAccountId: number | null;
  occurredAt: string; // "YYYY-MM-DDTHH:mm"
  confidence: "high" | "low";
}

const pad = (n: number) => String(n).padStart(2, "0");
function toLocal(d: Date) {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

const MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];

// Resolve a relative/absolute date phrase to a Date, defaulting to now.
function parseDate(text: string, ref: Date): Date {
  const t = text.toLowerCase();
  if (/\byesterday\b/.test(t)) {
    const d = new Date(ref);
    d.setDate(d.getDate() - 1);
    return d;
  }
  if (/\btoday\b/.test(t)) return new Date(ref);
  if (/\btomorrow\b/.test(t)) {
    const d = new Date(ref);
    d.setDate(d.getDate() + 1);
    return d;
  }
  // "apr 1", "april 1", "1 apr"
  const m = t.match(/\b([a-z]{3,9})\s+(\d{1,2})\b/) || t.match(/\b(\d{1,2})\s+([a-z]{3,9})\b/);
  if (m) {
    const a = m[1], b = m[2];
    const monTok = isNaN(Number(a)) ? a : b;
    const dayTok = isNaN(Number(a)) ? b : a;
    const mi = MONTHS.findIndex((mm) => monTok.startsWith(mm));
    const day = Number(dayTok);
    if (mi >= 0 && day >= 1 && day <= 31) {
      const d = new Date(ref.getFullYear(), mi, day, ref.getHours(), ref.getMinutes());
      // If that date is in the future by >6 months, assume last year.
      if (d.getTime() - ref.getTime() > 1000 * 60 * 60 * 24 * 183) d.setFullYear(d.getFullYear() - 1);
      return d;
    }
  }
  return new Date(ref);
}

// "1.2k" -> 1200, "₱3,400.50" -> 3400.5, "2m" -> 2_000_000.
function parseAmount(text: string): number | null {
  const m = text.match(/(?:₱|php|\$)?\s*([\d,]+(?:\.\d+)?)\s*([km])?/i);
  if (!m) return null;
  let n = parseFloat(m[1].replace(/,/g, ""));
  if (isNaN(n)) return null;
  const suf = (m[2] || "").toLowerCase();
  if (suf === "k") n *= 1_000;
  else if (suf === "m") n *= 1_000_000;
  return n;
}

const INCOME_WORDS = /\b(salary|income|paid|received|refund|bonus|deposit|gift)\b/i;
const TRANSFER_WORDS = /\b(transfer|move|send to|moved)\b/i;

export function parseQuick(
  raw: string,
  accounts: Account[],
  categories: TxnCategory[],
  ref: Date = new Date()
): QuickDraft | null {
  const text = raw.trim();
  if (!text) return null;
  const amount = parseAmount(text);
  if (amount == null || amount <= 0) return null;

  // Kind: explicit +/₱ prefix or keywords.
  const startsPlus = /^\s*\+/.test(text);
  let kind: TxnKind = "expense";
  if (TRANSFER_WORDS.test(text)) kind = "transfer";
  else if (startsPlus || INCOME_WORDS.test(text)) kind = "income";

  // Category by name match (expense side).
  let categoryId: number | null = null;
  const lower = text.toLowerCase();
  for (const c of categories) {
    if (c.kind === "expense" && lower.includes(c.name.toLowerCase())) {
      categoryId = c.id;
      break;
    }
  }

  // Account by name match; default to first debit for income/transfer, first usable otherwise.
  const debit = accounts.filter((a) => a.type === "debit" && !a.archived);
  const usable = accounts.filter((a) => !a.archived);
  const matchAccount = (pool: Account[]) =>
    pool.find((a) => lower.includes(a.name.toLowerCase()))?.id ?? null;

  let accountId: number | null;
  let toAccountId: number | null = null;
  if (kind === "income" || kind === "transfer") {
    accountId = matchAccount(debit) ?? debit[0]?.id ?? null;
  } else {
    accountId = matchAccount(usable) ?? usable[0]?.id ?? null;
  }
  if (kind === "transfer") {
    toAccountId = debit.find((a) => a.id !== accountId)?.id ?? null;
  }

  // Note: strip the amount token and standalone keywords for a cleaner label.
  const note = text
    .replace(/(?:₱|php|\$)?\s*[\d,]+(?:\.\d+)?\s*[km]?/i, "")
    .replace(/^\s*[+\-]\s*/, "")
    .replace(/\b(yesterday|today|tomorrow)\b/gi, "")
    .trim();

  const occurredAt = toLocal(parseDate(text, ref));
  const confidence: "high" | "low" = accountId != null ? "high" : "low";

  return { kind, amount, note, categoryId, accountId, toAccountId, occurredAt, confidence };
}
