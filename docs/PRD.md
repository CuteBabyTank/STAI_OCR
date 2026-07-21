# [Product Name] — Product Requirements Document

## 1. Product Overview

[Product Name] is a browser-based personal budget tracker (currently in "Beta") built around an imported-session model rather than live user accounts. On load, the app reads a JSON backup file (in the observed session, a demo file named `demo-backup.json`) into memory. Every create, edit, or delete action in the UI mutates this in-memory session so the dashboard, wallet, plan, history, and statistics views stay synchronized.

**Core Value Proposition:**
Philippine-peso-oriented budgeting for individuals, featuring:

* Tracking for multiple cash, e-wallet, credit, and investment accounts.
* Categorizing income and expenses.
* Planning through budgets and savings goals.
* Tracking debts owed and receivables due.
* Reviewing data through charts and a searchable transaction history.

**Brand Identity:** Uses a friendly mascot character, a soft green and cream color palette, rounded cards, and a friendly, informal tone (greeting the user by first name, e.g., "Good morning, Bryl!").

---

## 2. Global Application Shell

The app uses a persistent left sidebar and a scrollable main content pane on the right.

### 2.1 Sidebar & Navigation

* **Header:** Shows the application wordmark, a "BETA" pill badge, the subtitle "Budget Tracker," and a circular collapse toggle. Clicking the toggle shrinks the sidebar to an icon-only rail; this is a client-side preference and does not affect routing.
* **Primary Navigation:** Home, History, Wallet, Plan, Statistics, and Settings.
* **Wallet (Expandable):** Accounts, Payments.
* **Plan (Expandable):** Upcoming, Budgets, Categories, Tags, Templates, Recurring, Installments, Goals, Goal activity, Debts, Debt activity, Owed to you, and Receivable activity.


* **Quick Entry Panel:** Documents keyboard shortcuts for the transaction entry dialog: **Cmd+K** and **Alt+K**. Both open a natural-language "Quick chat" modal.
* **Imported File Card:** Reflects the loaded backup metadata (Format, Imported timestamp, Exported timestamp). Contains three actions: **Export data**, **Import another**, and **Clear file**.
* **Floating Action Button (FAB):** A green "+" pinned to the bottom-right. Opens a popover menu:
* **Quick chat:** Enter a quick transaction.
* **Transfer:** Move money between debit accounts.
* **Income:** Record new money coming in.
* **Expense:** Log spending from a wallet or card.



### 2.2 Quick Chat Modal

* **UI:** Header reads "Quick chat." Body is an auto-focused multiline textbox ("Describe the transaction").
* **Suggestions:** Six pill-shaped chips demonstrating NLP parsing rules: Amount shorthand (1.2k), Expense keyword, Income keyword (+), Prefixed symbol (₱), Relative date (yesterday), Specific date (apr 1), and Transfer logic.
* **Behavior:** Requires a backend/client-side NLP parser that extracts amount, sign/keyword, merchant/category, account, and date.

### 2.3 Expense Modal

* **UI:** Title "Add expense" (or "Edit expense").
* **Fields:**
* **Amount:** Numeric, placeholder 0.00. Client-side validation requires a value > 0.
* **Account:** Select (Allows Debit and Credit accounts).
* **Category:** Select with full taxonomy (Bills, Food, custom categories, etc.).
* **Date and time:** Native `datetime-local` input.
* **Note:** Free-text.


* **Actions:** Cancel, **Save expense** (primary).

### 2.4 Income Modal

* **UI:** Title "Add income."
* **Fields:**
* **Amount:** Numeric.
* **Account:** Select (Restricted to **Debit** accounts only).
* **Note:** Free-text.
* **Date and time:** Native `datetime-local` input.


* **Actions:** Cancel, **Save income**. *(Note: No category field is present).*

### 2.5 Transfer Modal

* **UI:** Title "Add transfer."
* **Fields:**
* **From Account / To Account:** Independent selects restricted to Debit accounts. Selecting a "From" account excludes it from the "To" list.
* **Amount:** Dynamic helper label shows available balance.
* **Transfer Fee:** Optional numeric field (deducted from "From" account).
* **Note & Date:** Standard inputs.



---

## 3. Home (Dashboard)

The Home route is a vertically scrolling page composed of stacked, aggregate cards.

* **Greeting Header:** Contextual mascot message driven by the system clock and Settings profile name.
* **Month Summary:** "This month out" (red) and "This month in" (green) stat tiles. Scoped strictly to the current calendar month.
* **Cashflow Chart:** 6-month trend bar chart. Y-axis scales in thousands; X-axis shows months. Current month is solid green.
* **Transactions:** Reverse-chronological list showing recent ledger entries with category pills, amounts, and source accounts.
* **Wallet:** Collapsible account groupings (Everyday balances, Credit and dues, Assets and investing).
* **Goals & Budgets:** Progress bars mapping current state against targets/limits.
* **Upcoming:** Deadlines for credit dues and recurring items.
* **Debts and Receivables:** Open balances and overdue statuses for counterparties.

---

## 4. Wallet > Accounts

* **Net Worth Summary:** Central card featuring a privacy toggle (eye icon) to mask all financial figures. Features a segmented control: **All**, **Assets**, and **Liabilities**, which updates the headline figure in real-time.
* **Accounts Grid:** Responsive grid categorized by type (teal for debit, pink for credit, etc.).
* **Add Account Modal:** Fields include Name, Type (Debit, Credit, Loans, Assets, Stocks, Crypto), Opening Balance, Currency (21 options), and an "Include in wallet totals" checkbox.
* **Edit Constraints:** Account Type and Currency are disabled/read-only during edits to prevent desynchronizing historical data.

---

## 5. Wallet > Payments

Three independent utility forms:

1. **Credit Payment:** Select Credit account, Source (Debit) account, Amount, Date.
2. **Loan Payment:** Select Loan account, Source (Debit) account, Amount, Date.
3. **Balance Adjustment:** Directly overwrites an account's balance (useful for reconciling stock/crypto valuations without logging a fake transaction).

---

## 6. Plan > Upcoming

A read-only aggregation view for action items. Features three stacked cards: **Credit dues**, **Recurring expenses**, and **Recurring income**. Items display overdue/countdown badges (e.g., "117 days overdue").

---

## 7. Plan > Budgets

* **Grid View:** Displays category name, status pill ("On track"), spent amount, progress bar, and limit.
* **Add Budget Modal:** Fields include Category, Type (Fixed amount / % of income), Interval (Daily, Weekly, Monthly, Yearly), and a "Carry unused budget forward" toggle.
* **Dynamic UI:** Selecting "% of income" swaps the fixed amount field for a percentage input.

---

## 8. Plan > Categories

Two management panels (Categories and Subcategories) for inline creation.

* **Fields:** Name, Kind (Expense/Income), Color hex input, and Parent select (for subcategories).
* **Constraints:** Only custom categories display a delete icon. System defaults (like Food or Bills) cannot be removed.

---

## 9. Plan > Tags

Lightweight tagging system with inline creation. Fields include Name, Kind (Custom, Trip), and Color hex input.

---

## 10. Plan > Templates

Reusable transaction presets for fast repeat entry.

* **Fields:** Title, Amount, Kind (Expense/Income), Account.
* **Lists:** Grouped into "Expense templates" and "Income templates."

---

## 11. Plan > Recurring

Manages scheduled, repeating transactions.

* **Fields:** Kind, Amount, Name, Account, Next due date.
* **Actionable Toggles:** Existing items feature a "Paid" or "Received" button to log the occurrence and advance the schedule.

---

## 12. Plan > Installments

* **Installment Plans:** Defines the financed purchase (Title, Total, Monthly, Months).
* **Log Payment:** Records a payment against an active plan (Plan select, Account, Amount, Date).

---

## 13. Plan > Goals

* **Add/Edit Goal Modal:** Title, Target amount, Current amount, Currency, Target date.
* *Note:* Funding or withdrawing from a goal is handled in **Goal Activity**, not here.

---

## 14. Plan > Goal Activity

Logs movements against goals. Fields include Goal select, Account select (Debit only), Amount, Type (Deposit/Withdrawal). Submitting a form synchronously updates the Goal's current amount and the Wallet Account's balance.

---

## 15. Plan > Debts & 16. Debt Activity

* **Debts (Definitions):** Tracks counterparties. Fields include Debt name, Total amount, Paid amount, Currency, Due date.
* **Debt Activity (Transactions):** Logs payments and borrowings. "Payment" reduces outstanding balance and debits the account; "Borrowing" increases outstanding balance and credits the account.

---

## 17. Plan > Owed to You & 18. Receivable Activity

Mirrors the Debt system but for money owed to the user.

* **Owed to You:** Dashboard showing Awaiting collection, Open receivables, and Average progress.
* **Receivable Activity:** Logs "Collections" and "Advances" to adjust the remaining amount owed.

---

## 19. History

Full transaction ledger.

* **Filtering & Search:** Text search box, segmented Kind filter (All/Expense/Income), and an All Categories dropdown. Summary tiles (Income/Expense) dynamically recompute based on active filters.
* **Actions:** Kebab menu (⋯) on rows allows for Edit (re-opens the respective transaction modal) or Delete (destructive, requires confirmation).

---

## 20. Statistics

Configurable analytics dashboard.

* **Filters:** Period (30D, 90D, 12M, All), Measure (Amount, Count), Trend chart style (Area, Bar, Line), and Focus (All, Expense, Income).
* **Visualizations:** Trend chart, Breakdown (donut chart with top 6 list), and Accounts (horizontal bar chart).
* **Insights:** Lightweight, rules-based text summarization offering plain-language takeaways on income/expenses, top buckets, collection health, and planning loads.

---

## 21. Settings

* **Profile:** Preferred name (controls dashboard greeting), Preferred currency, Language (Filipino, English).
* **Net Worth Preferences:** Toggles for "Include debts," "Include receivables," "Include credit card debt in wallet," and "Show decimals."
* **Persistence Note:** The copy explicitly states "Edit export-backed preferences here, then keep them in your next downloaded backup file," confirming no server-side authentication or syncing exists.

---

## 22. Cross-Cutting Behaviors and Inferred Backend Logic

All monetary values are formatted with a ₱ (peso) glyph, thousands separators, and two decimal places by default, and are consistently signed (+ for inflows, − for outflows) with color coding (green positive, red negative) throughout Home, Wallet, History, and Statistics.

Every account-bearing form (Expense, Income, Transfer, Payments, Balance adjustment, Templates, Recurring, Installments, Goal/Debt/Receivable activity) sources its account list from the same underlying Accounts collection, and several of them intentionally restrict the selectable subset by account type — expenses can draw from any account type including credit, while **income and transfers are restricted strictly to debit-type accounts.**

**Additional System Architecture Inferences:**

* **State Management & Data Persistence:** Because the application operates on an imported session model (`demo-backup.json`), all CRUD operations mutate an in-memory state. To persist changes permanently, the user must utilize the "Export data" function in the sidebar to download an updated JSON file. Refreshing the browser or clearing the file without exporting will result in total data loss for that session.
* **Referential Integrity:** Deleting or altering core entities (like Accounts or seeded Categories) is heavily restricted (or disabled) if those entities are tied to historical transactions. This is evidenced by the inability to change an Account's type/currency after creation.
* **Client-Side NLP:** The "Quick chat" functionality requires a robust client-side parser (or lightweight serverless function) capable of interpreting shorthand metrics (`k` suffix), regex matching for categories/brands, and relative time processing (`yesterday`, `apr 1`) to map unstructured text into the strict schema required by the ledger.
