/**
 * W2-C — Layer 1 component evaluation of the Quick Chat parser.
 *
 * This tests `parseQuick` (TypeScript), which is what the shipped UI actually calls
 * — QuickChatModal.tsx imports it directly. The Python `finance.parse_quick_text`
 * behind POST /quick exists but is not wired to any UI, so evaluating only that one
 * would measure a code path no user exercises. See evaluation/REQUIREMENTS_AUDIT.md §9.
 *
 * Quick Chat is a deterministic, rule-based parser — NOT an LLM feature (breakdown
 * §1 item 5). No model is involved, so every case below is exactly reproducible.
 *
 * Determinism: `parseQuick` takes a `ref: Date` parameter, so all relative-date cases
 * pin a fixed reference instead of depending on when the suite runs.
 */
import { describe, expect, it } from "vitest";

import { parseQuick } from "./parseQuick";
import type { Account, TxnCategory } from "./types";

// Fixed reference date for every relative-date case: Wed 2026-06-10, 14:30 local.
const REF = new Date(2026, 5, 10, 14, 30);

const ACCOUNTS = [
  { id: 1, name: "Cash", type: "debit", archived: false },
  { id: 2, name: "BPI Checking", type: "debit", archived: false },
  { id: 3, name: "Credit Card", type: "credit", archived: false },
  { id: 4, name: "Old Wallet", type: "debit", archived: true },
] as unknown as Account[];

const CATEGORIES = [
  { id: 10, name: "Food", kind: "expense" },
  { id: 11, name: "Transport", kind: "expense" },
  { id: 12, name: "Salary", kind: "income" },
] as unknown as TxnCategory[];

const parse = (text: string, ref: Date = REF) =>
  parseQuick(text, ACCOUNTS, CATEGORIES, ref);

describe("amount parsing", () => {
  it("parses a plain integer amount", () => {
    expect(parse("250 lunch")?.amount).toBe(250);
  });

  it("parses a decimal amount", () => {
    expect(parse("120.50 coffee")?.amount).toBe(120.5);
  });

  it("strips thousands separators", () => {
    expect(parse("3,400.50 groceries")?.amount).toBe(3400.5);
  });

  it("accepts a peso sign", () => {
    expect(parse("₱500 dinner")?.amount).toBe(500);
  });

  it("accepts a php prefix", () => {
    expect(parse("php 750 dinner")?.amount).toBe(750);
  });

  it("expands k shorthand", () => {
    expect(parse("1.2k lunch")?.amount).toBe(1200);
  });

  it("expands m shorthand", () => {
    expect(parse("2m bonus")?.amount).toBe(2_000_000);
  });

  it("treats k as case-insensitive", () => {
    expect(parse("5K rent")?.amount).toBe(5000);
  });

  // Regression guards for defect D4. The optional [km] suffix was not word-bounded,
  // so it matched the first letter of the FOLLOWING word — inflating everyday
  // entries by 1,000x or 1,000,000x with no warning.
  it.each([
    ["250 milk", 250],
    ["300 movie tickets", 300],
    ["250 kilo rice", 250],
    ["500 marketing 5", 500],
    ["120 mango shake", 120],
    ["80 kape", 80],
  ])("does not read the next word's first letter as a k/m suffix in %s", (text, expected) => {
    expect(parse(text)?.amount).toBe(expected);
  });

  it("still expands a suffix attached to the number", () => {
    expect(parse("1.2k lunch")?.amount).toBe(1200);
    expect(parse("2m bonus")?.amount).toBe(2_000_000);
  });
});

describe("invalid input", () => {
  it("returns null for empty text", () => {
    expect(parse("")).toBeNull();
  });

  it("returns null for whitespace only", () => {
    expect(parse("   ")).toBeNull();
  });

  it("returns null when there is no amount at all", () => {
    expect(parse("lunch with friends")).toBeNull();
  });

  it("returns null for a zero amount", () => {
    expect(parse("0 lunch")).toBeNull();
  });

  // Documents actual behaviour: the amount regex has no sign group, so "-50"
  // parses as 50 and the leading minus is dropped rather than rejected. Recorded
  // as a finding for the team, not asserted as desirable.
  it("parses a negative-looking amount as positive (documented behaviour)", () => {
    expect(parse("-50 lunch")?.amount).toBe(50);
  });
});

describe("kind classification", () => {
  it("defaults to expense", () => {
    expect(parse("250 lunch")?.kind).toBe("expense");
  });

  it("treats a leading + as income", () => {
    expect(parse("+5000 from mom")?.kind).toBe("income");
  });

  it.each(["salary", "income", "paid", "received", "refund", "bonus", "deposit", "gift"])(
    "treats %s as an income keyword",
    (word) => {
      expect(parse(`5000 ${word}`)?.kind).toBe("income");
    }
  );

  it.each(["transfer", "move", "moved"])("treats %s as a transfer keyword", (word) => {
    expect(parse(`1000 ${word} to savings`)?.kind).toBe("transfer");
  });

  it("prefers transfer over income when both keywords appear", () => {
    // TRANSFER_WORDS is checked first — pin the precedence so a reordering is caught.
    expect(parse("1000 transfer salary")?.kind).toBe("transfer");
  });
});

describe("relative date parsing", () => {
  it("resolves today to the reference date", () => {
    expect(parse("250 lunch today")?.occurredAt).toBe("2026-06-10T14:30");
  });

  it("resolves yesterday to the day before", () => {
    expect(parse("250 lunch yesterday")?.occurredAt).toBe("2026-06-09T14:30");
  });

  it("resolves tomorrow to the day after", () => {
    expect(parse("250 lunch tomorrow")?.occurredAt).toBe("2026-06-11T14:30");
  });

  it("defaults to the reference date when no date is mentioned", () => {
    expect(parse("250 lunch")?.occurredAt).toBe("2026-06-10T14:30");
  });

  it("crosses a month boundary correctly", () => {
    expect(parse("250 lunch yesterday", new Date(2026, 6, 1, 9, 0))?.occurredAt).toBe(
      "2026-06-30T09:00"
    );
  });

  it("crosses a year boundary correctly", () => {
    expect(parse("250 lunch tomorrow", new Date(2026, 11, 31, 23, 0))?.occurredAt).toBe(
      "2027-01-01T23:00"
    );
  });

  it("parses an explicit 'mon d' date", () => {
    expect(parse("250 lunch apr 1")?.occurredAt).toBe("2026-04-01T14:30");
  });

  it("parses an explicit 'd mon' date when no word precedes the day", () => {
    expect(parse("250 1 apr")?.occurredAt).toBe("2026-04-01T14:30");
  });

  // Regression guard for defect D2. These all used to be silently dated TODAY:
  // parseDate joined its two patterns with `||`, so a note word before the day
  // ("lunch 1") matched the first pattern, failed the month lookup, and the
  // "d mon" pattern was never tried.
  it.each([
    ["250 lunch 1 apr", "2026-04-01T14:30"],
    ["250 dinner 5 may", "2026-05-05T14:30"],
    ["1000 groceries 3 mar", "2026-03-03T14:30"],
    ["500 taxi 2 feb", "2026-02-02T14:30"],
  ])("parses 'd mon' in %s even with a note word before the day", (text, expected) => {
    expect(parse(text)?.occurredAt).toBe(expected);
  });

  it("still parses 'mon d' after a note word", () => {
    expect(parse("250 lunch apr 1")?.occurredAt).toBe("2026-04-01T14:30");
  });

  it("does not mistake a note word starting with a month prefix for a month", () => {
    // "marketing" starts with "mar" but is not March. The month token must be a
    // prefix of a real month name, not the other way round.
    expect(parse("500 marketing 5")?.occurredAt).toBe("2026-06-10T14:30");
  });

  it("accepts a four-letter month abbreviation", () => {
    // Sept 3 is ~85 days after the Jun 10 reference — under the 183-day threshold,
    // so it stays in the current year (unlike the dec 25 case above).
    expect(parse("250 lunch sept 3")?.occurredAt).toBe("2026-09-03T14:30");
  });

  it("takes the earliest resolvable date when the text has several candidates", () => {
    expect(parse("250 lunch apr 1 and may 2")?.occurredAt).toBe("2026-04-01T14:30");
  });

  it("parses a full month name", () => {
    expect(parse("250 lunch april 1")?.occurredAt).toBe("2026-04-01T14:30");
  });

  it("rolls a far-future date back to last year", () => {
    // Dec 25 is >183 days after Jun 10, so it is read as the previous December.
    expect(parse("250 gift dec 25")?.occurredAt).toBe("2025-12-25T14:30");
  });

  it("zero-pads month and day", () => {
    const result = parse("250 lunch", new Date(2026, 0, 5, 9, 5));
    expect(result?.occurredAt).toBe("2026-01-05T09:05");
  });
});

describe("account matching", () => {
  it("matches an account named in the text", () => {
    expect(parse("250 lunch cash")?.accountId).toBe(1);
  });

  it("matches a multi-word account name", () => {
    expect(parse("250 lunch bpi checking")?.accountId).toBe(2);
  });

  it("matches case-insensitively", () => {
    expect(parse("250 lunch CASH")?.accountId).toBe(1);
  });

  it("falls back to the first usable account for an expense", () => {
    expect(parse("250 lunch")?.accountId).toBe(1);
  });

  it("never selects an archived account", () => {
    expect(parse("250 lunch old wallet")?.accountId).not.toBe(4);
  });

  it("restricts income to debit accounts", () => {
    // "credit card" is named, but income may only land on a debit account.
    expect(parse("+5000 salary credit card")?.accountId).not.toBe(3);
  });

  it("allows an expense on a credit account", () => {
    expect(parse("800 shopping credit card")?.accountId).toBe(3);
  });

  it("picks a distinct destination account for a transfer", () => {
    const draft = parse("1000 transfer cash");
    expect(draft?.kind).toBe("transfer");
    expect(draft?.toAccountId).not.toBeNull();
    expect(draft?.toAccountId).not.toBe(draft?.accountId);
  });

  it("reports low confidence when no account can be resolved", () => {
    expect(parseQuick("250 lunch", [], CATEGORIES, REF)?.confidence).toBe("low");
  });

  it("reports high confidence when an account is resolved", () => {
    expect(parse("250 lunch")?.confidence).toBe("high");
  });
});

describe("category matching", () => {
  it("matches an expense category named in the text", () => {
    expect(parse("250 food")?.categoryId).toBe(10);
  });

  it("matches case-insensitively", () => {
    expect(parse("250 FOOD")?.categoryId).toBe(10);
  });

  it("leaves the category null when nothing matches", () => {
    expect(parse("250 something else")?.categoryId).toBeNull();
  });

  it("never selects an income category", () => {
    // "Salary" is an income category and must not be attached by the expense-side match.
    expect(parse("5000 salary")?.categoryId).not.toBe(12);
  });
});

describe("note extraction", () => {
  it("strips the amount token", () => {
    expect(parse("250 lunch")?.note).toBe("lunch");
  });

  it("strips a k-shorthand amount", () => {
    expect(parse("1.2k lunch")?.note).toBe("lunch");
  });

  it("strips relative date words", () => {
    expect(parse("250 lunch yesterday")?.note).toBe("lunch");
  });

  it("strips a leading plus", () => {
    expect(parse("+5000 salary")?.note).toBe("salary");
  });

  it("strips a currency symbol with the amount", () => {
    expect(parse("₱500 dinner")?.note).toBe("dinner");
  });

  it("does not eat the first letter of the note (defect D4)", () => {
    // The note-stripping regex had the same unbounded [km]? — "250 milk" stripped
    // "250 m" and left "ilk".
    expect(parse("250 milk")?.note).toBe("milk");
    expect(parse("300 movie tickets")?.note).toBe("movie tickets");
  });
});

describe("draft shape", () => {
  it("returns every documented field", () => {
    const draft = parse("250 food cash yesterday");
    expect(draft).not.toBeNull();
    expect(Object.keys(draft!).sort()).toEqual(
      [
        "accountId",
        "amount",
        "categoryId",
        "confidence",
        "kind",
        "note",
        "occurredAt",
        "toAccountId",
      ].sort()
    );
  });

  it("sets toAccountId to null for a non-transfer", () => {
    expect(parse("250 lunch")?.toAccountId).toBeNull();
  });

  it("produces an occurredAt in the exact YYYY-MM-DDTHH:mm shape the API expects", () => {
    expect(parse("250 lunch")?.occurredAt).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/);
  });
});

describe("worked examples from the source comments", () => {
  // The parser's own docstring advertises these two. If they break, the documented
  // contract broke.
  it('parses "1.2k lunch yesterday"', () => {
    const draft = parse("1.2k lunch yesterday");
    expect(draft?.amount).toBe(1200);
    expect(draft?.kind).toBe("expense");
    expect(draft?.note).toBe("lunch");
    expect(draft?.occurredAt).toBe("2026-06-09T14:30");
  });

  it('parses "+5000 salary"', () => {
    const draft = parse("+5000 salary");
    expect(draft?.amount).toBe(5000);
    expect(draft?.kind).toBe("income");
    expect(draft?.note).toBe("salary");
  });
});
