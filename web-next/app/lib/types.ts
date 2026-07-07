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

export type Granularity = "month" | "year";

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
