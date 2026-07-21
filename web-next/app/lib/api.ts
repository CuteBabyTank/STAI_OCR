// Typed client for the budget-tracker endpoints. The browser calls same-origin
// "/api/*", which Next rewrites to the FastAPI service (see next.config.js).
import type {
  Account,
  ActivityType,
  BudgetPlan,
  Debt,
  DebtActivityRow,
  Goal,
  Installment,
  NetWorth,
  Receivable,
  ReceivableActivityRow,
  Recurring,
  Tag,
  Template,
  Transaction,
  TxnCategory,
  TxnKind,
  Upcoming,
} from "./types";

async function j<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (body?.detail) msg = typeof body.detail === "string" ? body.detail : msg;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}

const get = (url: string) => fetch(url).then((r) => j<any>(r));
const send = (url: string, method: string, body?: unknown) =>
  fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  }).then((r) => j<any>(r));

// ---- Accounts --------------------------------------------------------------
export const listAccounts = (includeArchived = false) =>
  get(`/api/accounts?include_archived=${includeArchived}`).then(
    (d) => d.accounts as Account[]
  );

export const createAccount = (payload: {
  name: string;
  type: string;
  opening_balance?: number;
  currency?: string | null;
  include_in_totals?: boolean;
}) => send(`/api/accounts`, "POST", payload).then((d) => d.account as Account);

export const updateAccount = (id: number, payload: Record<string, unknown>) =>
  send(`/api/accounts/${id}`, "PUT", payload).then((d) => d.account as Account);

export const setAccountBalance = (id: number, balance: number) =>
  send(`/api/accounts/${id}/balance`, "PUT", { balance }).then(
    (d) => d.account as Account
  );

export const deleteAccount = (id: number) =>
  send(`/api/accounts/${id}`, "DELETE");

export const getNetWorth = (opts?: {
  include_credit?: boolean;
  show_liabilities?: boolean;
}) => {
  const p = new URLSearchParams();
  if (opts?.include_credit === false) p.set("include_credit", "false");
  if (opts?.show_liabilities === false) p.set("show_liabilities", "false");
  const qs = p.toString();
  return get(`/api/networth${qs ? "?" + qs : ""}`) as Promise<NetWorth>;
};

// ---- Transactions ----------------------------------------------------------
export const listTransactions = (opts?: {
  limit?: number;
  kind?: TxnKind;
  account_id?: number;
  category_id?: number;
  search?: string;
}) => {
  const p = new URLSearchParams();
  if (opts?.limit) p.set("limit", String(opts.limit));
  if (opts?.kind) p.set("kind", opts.kind);
  if (opts?.account_id != null) p.set("account_id", String(opts.account_id));
  if (opts?.category_id != null) p.set("category_id", String(opts.category_id));
  if (opts?.search) p.set("search", opts.search);
  const qs = p.toString();
  return get(`/api/transactions${qs ? "?" + qs : ""}`).then(
    (d) => d.transactions as Transaction[]
  );
};

export const createTransaction = (payload: {
  kind: TxnKind;
  amount: number;
  account_id?: number | null;
  to_account_id?: number | null;
  category_id?: number | null;
  note?: string | null;
  occurred_at?: string | null;
  fee?: number;
  receipt_id?: number | null;
}) => send(`/api/transactions`, "POST", payload).then((d) => d.transaction as Transaction);

export const updateTransaction = (id: number, payload: Record<string, unknown>) =>
  send(`/api/transactions/${id}`, "PUT", payload).then(
    (d) => d.transaction as Transaction
  );

export const deleteTransaction = (id: number) =>
  send(`/api/transactions/${id}`, "DELETE");

export const postReceiptAsExpense = (receiptId: number, accountId: number) =>
  send(`/api/receipts/${receiptId}/post`, "POST", { account_id: accountId }).then(
    (d) => d.transaction as Transaction
  );

// ---- Categories & tags -----------------------------------------------------
export const listCategories = () =>
  get(`/api/categories`).then((d) => d.categories as TxnCategory[]);

export const createCategory = (payload: {
  name: string;
  kind: "expense" | "income";
  color?: string | null;
  parent_id?: number | null;
}) => send(`/api/categories`, "POST", payload).then((d) => d.id as number);

export const deleteCategory = (id: number) =>
  send(`/api/categories/${id}`, "DELETE");

export const listTags = () => get(`/api/tags`).then((d) => d.tags as Tag[]);

export const createTag = (payload: {
  name: string;
  kind?: string;
  color?: string | null;
}) => send(`/api/tags`, "POST", payload).then((d) => d.id as number);

export const deleteTag = (id: number) => send(`/api/tags/${id}`, "DELETE");

// ---- Budgets ----
export const listBudgetPlans = () =>
  get(`/api/budget-plans`).then((d) => d.budget_plans as BudgetPlan[]);
export const createBudgetPlan = (payload: Record<string, unknown>) =>
  send(`/api/budget-plans`, "POST", payload);
export const deleteBudgetPlan = (id: number) => send(`/api/budget-plans/${id}`, "DELETE");

// ---- Templates ----
export const listTemplates = () => get(`/api/templates`).then((d) => d.templates as Template[]);
export const createTemplate = (payload: Record<string, unknown>) => send(`/api/templates`, "POST", payload);
export const useTemplate = (id: number) => send(`/api/templates/${id}/use`, "POST");
export const deleteTemplate = (id: number) => send(`/api/templates/${id}`, "DELETE");

// ---- Recurring ----
export const listRecurring = () => get(`/api/recurring`).then((d) => d.recurring as Recurring[]);
export const createRecurring = (payload: Record<string, unknown>) => send(`/api/recurring`, "POST", payload);
export const advanceRecurring = (id: number) => send(`/api/recurring/${id}/advance`, "POST");
export const deleteRecurring = (id: number) => send(`/api/recurring/${id}`, "DELETE");

// ---- Installments ----
export const listInstallments = () => get(`/api/installments`).then((d) => d.installments as Installment[]);
export const createInstallment = (payload: Record<string, unknown>) => send(`/api/installments`, "POST", payload);
export const payInstallment = (id: number, payload: Record<string, unknown>) =>
  send(`/api/installments/${id}/pay`, "POST", payload);
export const deleteInstallment = (id: number) => send(`/api/installments/${id}`, "DELETE");

// ---- Goals ----
export const listGoals = () => get(`/api/goals`).then((d) => d.goals as Goal[]);
export const createGoal = (payload: Record<string, unknown>) => send(`/api/goals`, "POST", payload);
export const updateGoal = (id: number, payload: Record<string, unknown>) => send(`/api/goals/${id}`, "PUT", payload);
export const deleteGoal = (id: number) => send(`/api/goals/${id}`, "DELETE");
export const goalActivity = (id: number, payload: { account_id: number; amount: number; type: ActivityType; occurred_at?: string }) =>
  send(`/api/goals/${id}/activity`, "POST", payload);

// ---- Debts ----
export const listDebts = () => get(`/api/debts`).then((d) => d.debts as Debt[]);
export const createDebt = (payload: Record<string, unknown>) => send(`/api/debts`, "POST", payload);
export const deleteDebt = (id: number) => send(`/api/debts/${id}`, "DELETE");
export const debtActivity = (id: number, payload: { account_id: number; amount: number; type: ActivityType; occurred_at?: string }) =>
  send(`/api/debts/${id}/activity`, "POST", payload);
export const listDebtActivity = () =>
  get(`/api/debt-activity`).then((d) => d.activity as DebtActivityRow[]);

// ---- Receivables ----
export const listReceivables = () => get(`/api/receivables`).then((d) => d.receivables as Receivable[]);
export const createReceivable = (payload: Record<string, unknown>) => send(`/api/receivables`, "POST", payload);
export const deleteReceivable = (id: number) => send(`/api/receivables/${id}`, "DELETE");
export const receivableActivity = (id: number, payload: { account_id: number; amount: number; type: ActivityType; occurred_at?: string }) =>
  send(`/api/receivables/${id}/activity`, "POST", payload);
export const listReceivableActivity = () =>
  get(`/api/receivable-activity`).then((d) => d.activity as ReceivableActivityRow[]);

// ---- Upcoming / settings / backup ----
export const getUpcoming = () => get(`/api/upcoming`) as Promise<Upcoming>;
export const getSettings = () => get(`/api/settings`).then((d) => d.settings as Record<string, string>);
export const putSettings = (payload: Record<string, unknown>) =>
  send(`/api/settings`, "PUT", payload).then((d) => d.settings as Record<string, string>);
export const exportBackup = () => get(`/api/backup/export`);
export const importBackup = (payload: unknown) => send(`/api/backup/import`, "POST", payload);
