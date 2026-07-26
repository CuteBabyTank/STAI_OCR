/**
 * W2-C — the TypeScript half of the two-parser agreement check.
 *
 * Snag ships two Quick Chat parsers: this one (`parseQuick`, called by
 * QuickChatModal.tsx) and `finance.parse_quick_text` behind POST /quick. Both were
 * tested; neither was tested *against* the other. Defect D2 was present in BOTH,
 * which is why agreement has to be measured rather than assumed.
 *
 * Both suites read the SAME corpus file — evaluation/datasets/quickchat_corpus.json —
 * so a divergence fails on exactly one side and is immediately localizable:
 *   this file                                     (vitest)
 *   evaluation/tests/test_w2c_parser_agreement.py (pytest)
 *
 * Only parser-intrinsic fields are compared (kind, amount, note, date). Account and
 * category ids are excluded: this parser is *given* accounts and categories while the
 * Python one reads them from the database, so an id mismatch would reflect different
 * inputs rather than different parsing.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { parseQuick } from "./parseQuick";
import type { Account, TxnCategory } from "./types";

const CORPUS_PATH = join(__dirname, "..", "..", "..", "evaluation", "datasets",
  "quickchat_corpus.json");
const CORPUS = JSON.parse(readFileSync(CORPUS_PATH, "utf8")) as {
  cases: {
    case_id: string;
    input: string;
    kind: string;
    amount: number;
    note?: string;
    date_offset_days: number;
  }[];
  rejected_cases: { case_id: string; input: string; reason: string }[];
};

// Fixed reference so relative-date cases do not depend on when the suite runs.
// The Python side uses `date.today()`; both are compared as an offset from their own
// reference, which is what the corpus stores.
const REF = new Date(2026, 5, 10, 14, 30);

const ACCOUNTS = [
  { id: 1, name: "Cash", type: "debit", archived: false },
  { id: 2, name: "BPI Checking", type: "debit", archived: false },
  { id: 3, name: "Credit Card", type: "credit", archived: false },
] as unknown as Account[];

const CATEGORIES = [
  { id: 10, name: "Food", kind: "expense" },
  { id: 11, name: "Groceries", kind: "expense" },
  { id: 12, name: "Bills", kind: "expense" },
  { id: 13, name: "Salary", kind: "income" },
] as unknown as TxnCategory[];

const parse = (text: string) => parseQuick(text, ACCOUNTS, CATEGORIES, REF);

/** Whole-day offset between a draft's date and the reference date. */
function offsetDays(occurredAt: string): number {
  const [y, m, d] = occurredAt.slice(0, 10).split("-").map(Number);
  const parsed = new Date(y, m - 1, d);
  const ref = new Date(REF.getFullYear(), REF.getMonth(), REF.getDate());
  return Math.round((parsed.getTime() - ref.getTime()) / 86_400_000);
}

describe("shared corpus is loadable", () => {
  it("reads the same file the Python suite reads", () => {
    expect(CORPUS.cases.length).toBeGreaterThan(0);
    expect(CORPUS.rejected_cases.length).toBeGreaterThan(0);
  });
});

describe("accepted cases", () => {
  for (const c of CORPUS.cases) {
    it(`${c.case_id} "${c.input}" produces a draft`, () => {
      expect(parse(c.input)).not.toBeNull();
    });

    it(`${c.case_id} "${c.input}" reads the expected kind`, () => {
      expect(parse(c.input)!.kind).toBe(c.kind);
    });

    it(`${c.case_id} "${c.input}" reads the expected amount`, () => {
      expect(parse(c.input)!.amount).toBeCloseTo(c.amount, 2);
    });

    if (c.note !== undefined) {
      it(`${c.case_id} "${c.input}" reads the expected note`, () => {
        expect(parse(c.input)!.note).toBe(c.note);
      });
    }

    it(`${c.case_id} "${c.input}" resolves the expected date`, () => {
      expect(offsetDays(parse(c.input)!.occurredAt)).toBe(c.date_offset_days);
    });
  }
});

describe("rejected cases", () => {
  for (const c of CORPUS.rejected_cases) {
    it(`${c.case_id} rejects "${c.input}" (${c.reason})`, () => {
      // Both parsers must refuse the same inputs. Inventing a draft from
      // "lunch with friends" would put an unintended transaction in front of the user.
      expect(parse(c.input)).toBeNull();
    });
  }
});

describe("cross-parser invariants", () => {
  it("never proposes a self-transfer", () => {
    // create_transaction rejects a transfer to the same account, so such a draft
    // would fail the moment the user accepted it.
    for (const c of CORPUS.cases.filter((x) => x.kind === "transfer")) {
      const draft = parse(c.input)!;
      if (draft.toAccountId != null) {
        expect(draft.toAccountId).not.toBe(draft.accountId);
      }
    }
  });

  it("never categorizes income with an expense category", () => {
    for (const c of CORPUS.cases.filter((x) => x.kind === "income")) {
      expect(parse(c.input)!.categoryId).toBeNull();
    }
  });

  it("always produces a positive amount", () => {
    for (const c of CORPUS.cases) {
      expect(parse(c.input)!.amount).toBeGreaterThan(0);
    }
  });
});
