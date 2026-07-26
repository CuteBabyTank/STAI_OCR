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

const MONTHS_FULL = [
  "january", "february", "march", "april", "may", "june",
  "july", "august", "september", "october", "november", "december",
];

// Month index for a token, or -1. The token must be a prefix of a real month name
// ("apr"/"april"/"sept" all resolve), which is stricter than the reverse test: a
// note word like "marketing" is NOT March, though it does start with "mar".
function monthIndex(token: string): number {
  if (token.length < 3) return -1;
  return MONTHS_FULL.findIndex((m) => m.startsWith(token));
}

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

  // "apr 1", "april 1", "1 apr". Both orderings are collected and the first one
  // that resolves to a real month wins, ordered by position in the text.
  //
  // These two patterns used to be joined with `||`, which meant that if the "mon d"
  // pattern matched *anything* the "d mon" pattern was never tried. In "250 lunch
  // 1 apr" the first pattern matched the note word plus the day ("lunch 1"), the
  // month lookup failed, and the function fell through to the reference date —
  // silently dating the transaction today instead of 1 April.
  const candidates: { index: number; monTok: string; dayTok: string }[] = [];
  for (const m of t.matchAll(/\b([a-z]{3,9})\s+(\d{1,2})\b/g)) {
    candidates.push({ index: m.index ?? 0, monTok: m[1], dayTok: m[2] });
  }
  for (const m of t.matchAll(/\b(\d{1,2})\s+([a-z]{3,9})\b/g)) {
    candidates.push({ index: m.index ?? 0, monTok: m[2], dayTok: m[1] });
  }
  candidates.sort((a, b) => a.index - b.index);

  for (const { monTok, dayTok } of candidates) {
    const mi = monthIndex(monTok);
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
//
// The trailing \b is load-bearing. Without it the optional [km] suffix matched the
// first letter of the FOLLOWING word: "250 milk" parsed as 250 x 1,000,000 = ₱250M,
// "300 movie tickets" as ₱300M, "250 kilo rice" as ₱250,000. With \b a suffix must
// end a word, so "1.2k lunch" and "2m bonus" still work while "250 milk" is ₱250.
const AMOUNT_RE = /(?:₱|php|\$)?\s*([\d,]+(?:\.\d+)?)\s*([km])?\b/i;

function parseAmount(text: string): number | null {
  const m = text.match(AMOUNT_RE);
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
    // Same \b as AMOUNT_RE: without it "250 milk" stripped "250 m" and left "ilk".
    .replace(/(?:₱|php|\$)?\s*[\d,]+(?:\.\d+)?\s*[km]?\b/i, "")
    .replace(/^\s*[+\-]\s*/, "")
    .replace(/\b(yesterday|today|tomorrow)\b/gi, "")
    .trim();

  const occurredAt = toLocal(parseDate(text, ref));
  const confidence: "high" | "low" = accountId != null ? "high" : "low";

  return { kind, amount, note, categoryId, accountId, toAccountId, occurredAt, confidence };
}
