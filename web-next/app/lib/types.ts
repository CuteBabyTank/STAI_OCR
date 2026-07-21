// Shared types for the receipt-ledger dashboard.

export type Category = "Food" | "Shopping" | "Health" | "Other";

export interface Receipt {
  id: number;
  vendor_name: string | null;
  category: string | null;
  total_amount: number | null;
  currency: string | null;
  receipt_date: string | null;
  source_file: string | null;
  confidence?: number | null;         // measured OCR confidence 0..1 (overall)
  field_confidence?: string | null;   // JSON string: {overall, fields, items}
}

// Parsed shape of Receipt.field_confidence / the /extract "confidence" payload.
export interface FieldConfidence {
  overall: number | null;
  fields: Record<string, number>;
  items: Array<Record<string, number>>;
}

export interface LineItem {
  description: string | null;
  quantity: number | null;
  unit_price: number | null;
  amount: number | null;
}

export interface Summary {
  total: number;
  count: number;
  by_category: Record<string, number>;
  top_category: string | null;
  currency: string | null;
  mixed_currency: boolean;
}

export interface Bar {
  key: string;   // "YYYY-MM" (month mode) or "YYYY" (year mode)
  label: string; // "Jun" or "2026"
  income: number;
  expense: number;
}

export type Granularity = "month" | "year" | "all";

export interface Period {
  granularity: Granularity;
  year: number;
  month: number;
  label: string;     // "June 2026" or "2026"
  min_year: number;
  max_year: number;
}

export interface MoMField {
  current: number;
  prev: number;
  pct: number | null;
}

export interface VendorPoint {
  vendor: string;
  total: number;
  count: number;
}

export interface BudgetRow {
  category: string;
  limit: number;
  spent: number;
  pct: number | null;
  currency: string | null;
}

export interface Analytics {
  bars: Bar[];
  focus_key: string;
  by_category: Record<string, number>;
  top_category: string | null;
  top_vendors: VendorPoint[];
  budgets: BudgetRow[];
  mom: { expense: MoMField; income: MoMField; net: MoMField; label: string | null };
  income_total: number;
  expense_total: number;
  net_total: number;
  receipt_count: number;
  period: Period;
  currency: string | null;
  mixed_currency: boolean;
}

export interface IncomeEntry {
  id: number;
  source: string | null;
  amount: number | null;
  currency: string | null;
  income_date: string | null;
  recurring: number;
}

// --------------------------------------------------------------------------- //
// Budget-tracker layer (accounts, transactions, categories, tags)
// --------------------------------------------------------------------------- //
export type AccountType = "debit" | "credit" | "loans" | "assets" | "stocks" | "crypto";

export const ACCOUNT_TYPES: AccountType[] = [
  "debit", "credit", "loans", "assets", "stocks", "crypto",
];
export const DEBIT_TYPES: AccountType[] = ["debit"];
export const ASSET_TYPES: AccountType[] = ["debit", "assets", "stocks", "crypto"];
export const LIABILITY_TYPES: AccountType[] = ["credit", "loans"];

export interface Account {
  id: number;
  name: string;
  type: AccountType;
  opening_balance: number;
  currency: string | null;
  include_in_totals: number;
  archived: number;
  created_at: string | null;
  balance: number; // derived server-side
}

export interface NetWorth {
  assets: number;
  liabilities: number;
  net: number;
}

export type TxnKind = "expense" | "income" | "transfer";

export interface Transaction {
  id: number;
  kind: TxnKind;
  amount: number;
  account_id: number | null;
  to_account_id: number | null;
  category_id: number | null;
  note: string | null;
  occurred_at: string | null;
  fee: number | null;
  receipt_id: number | null;
  template_id: number | null;
  created_at: string | null;
  // Joined display fields from list_transactions:
  account_name?: string | null;
  account_type?: AccountType | null;
  to_account_name?: string | null;
  category_name?: string | null;
  category_color?: string | null;
}

export interface TxnCategory {
  id: number;
  name: string;
  kind: "expense" | "income";
  color: string | null;
  parent_id: number | null;
  is_system: number;
}

export interface Tag {
  id: number;
  name: string;
  kind: string;
  color: string | null;
}

export interface BudgetPlan {
  id: number;
  category_id: number | null;
  category_name: string | null;
  category_color: string | null;
  type: "fixed" | "percent";
  interval: "daily" | "weekly" | "monthly" | "yearly";
  limit_amount: number;
  percent: number;
  carry_forward: number;
  spent: number;
  limit: number;
  pct: number | null;
}

export interface Template {
  id: number;
  title: string;
  amount: number;
  kind: "expense" | "income";
  account_id: number | null;
  account_name: string | null;
  category_id: number | null;
}

export interface Recurring {
  id: number;
  kind: "expense" | "income";
  amount: number;
  name: string | null;
  account_id: number | null;
  account_name: string | null;
  category_id: number | null;
  next_due: string | null;
  days_to_due?: number | null;
}

export interface Installment {
  id: number;
  title: string;
  total: number;
  monthly: number;
  months: number;
  paid_amount: number;
  remaining: number;
  pct: number | null;
}

export interface Goal {
  id: number;
  title: string;
  target_amount: number;
  current_amount: number;
  currency: string | null;
  target_date: string | null;
  pct: number | null;
}

export interface Debt {
  id: number;
  name: string;
  total_amount: number;
  paid_amount: number;
  currency: string | null;
  due_date: string | null;
  outstanding: number;
  pct: number | null;
  days_to_due?: number | null;
}

export interface Receivable {
  id: number;
  name: string;
  total_amount: number;
  collected_amount: number;
  currency: string | null;
  due_date: string | null;
  remaining: number;
  pct: number | null;
}

export interface Upcoming {
  recurring_expenses: Recurring[];
  recurring_income: Recurring[];
  debts: Debt[];
}

export type ActivityType =
  | "deposit" | "withdrawal"
  | "payment" | "borrowing"
  | "collection" | "advance";

// A single logged movement (one row of the append-only activity history).
export interface DebtActivityRow {
  id: number;
  kind: TxnKind;
  amount: number;
  occurred_at: string | null;
  note: string | null;
  debt_id: number;
  debt_name: string | null;
  currency: string | null;
  account_name: string | null;
  activity_type: "payment" | "borrowing";
}

export interface ReceivableActivityRow {
  id: number;
  kind: TxnKind;
  amount: number;
  occurred_at: string | null;
  note: string | null;
  receivable_id: number;
  receivable_name: string | null;
  currency: string | null;
  account_name: string | null;
  activity_type: "collection" | "advance";
}
