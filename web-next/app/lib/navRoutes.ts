// Single source of truth for the app's route tables, its nav glyphs, and the
// question "which entry is current". Both the desktop sidebar rail and the
// phone tab bar read from here. Sidebar used to own all of this privately; a
// second navigation with its own copy would be a second place for routes to go
// stale, which is exactly what this module exists to prevent.

export type NavItem = { href: string; label: string };

export const WALLET: NavItem[] = [
  { href: "/wallet", label: "Accounts" },
  { href: "/wallet/payments", label: "Payments" },
];

export const PLAN: NavItem[] = [
  { href: "/plan/upcoming", label: "Upcoming" },
  { href: "/plan/budgets", label: "Budgets" },
  { href: "/plan/categories", label: "Categories" },
  { href: "/plan/tags", label: "Tags" },
  { href: "/plan/templates", label: "Templates" },
  { href: "/plan/recurring", label: "Recurring" },
  { href: "/plan/installments", label: "Installments" },
  { href: "/plan/goals", label: "Goals" },
  { href: "/plan/goal-activity", label: "Goal activity" },
];

// Debts & receivables and their activity logs live in their own category.
export const LENDING: NavItem[] = [
  { href: "/lending/debts", label: "Debts" },
  { href: "/lending/debt-activity", label: "Debt activity" },
  { href: "/lending/receivables", label: "Owed to you" },
  { href: "/lending/receivable-activity", label: "Receivable activity" },
];

// `/add` and `/scan` are included even though no sidebar entry links to either:
// the phone tab bar's centre button goes to /add, and without them here those
// routes would resolve to no active entry at all.
export const ALL_HREFS: string[] = [
  "/", "/history", "/statistics", "/receipts", "/settings", "/scan", "/add",
  ...WALLET.map((i) => i.href),
  ...PLAN.map((i) => i.href),
  ...LENDING.map((i) => i.href),
];

export const ICON_PATHS = {
  home: "M3 10.5 12 3l9 7.5M5 9.5V21h14V9.5",
  history: "M3 3v6h6M3 9a9 9 0 1 1 2 9M12 7v5l3 2",
  wallet: "M3 7a2 2 0 0 1 2-2h14v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zM16 12h4",
  plan: "M9 11l3 3 8-8M20 12v6a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h9",
  lending: "M3 6h18M3 12h18M3 18h18M7 3v3M7 18v3M17 3v3M17 18v3",
  stats: "M3 3v18h18M8 13v5M13 9v9M18 5v13",
  settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-2.9 1.3V22a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 7 20.4l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 3.6 15H3.5a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 5 8.6l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 10 5.6V5.5a2 2 0 0 1 4 0v.09A1.65 1.65 0 0 0 17 7l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 20.4 12v.09a1.65 1.65 0 0 0 1.3 2.9",
  receipt: "M6 2h9l5 5v14a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1zM14 2v6h6M8 13h8M8 17h6",
  scan: "M4 7V5a1 1 0 0 1 1-1h2M17 4h2a1 1 0 0 1 1 1v2M20 17v2a1 1 0 0 1-1 1h-2M7 20H5a1 1 0 0 1-1-1v-2M3 12h18",
  caret: "m9 6 6 6-6 6",
  sun: "M12 3v2m0 14v2M5.6 5.6l1.4 1.4m10 10 1.4 1.4M3 12h2m14 0h2M5.6 18.4 7 17m10-10 1.4-1.4M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z",
  moon: "M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z",
  more: "M5 12h.01M12 12h.01M19 12h.01",
  plus: "M12 5v14M5 12h14",
};

/**
 * The single most-specific route that matches `path`, or null.
 *
 * A route matches if it is an exact hit or a true ancestor. `/wallet` is an
 * ancestor of `/wallet/payments`, so on the Payments page both match — only the
 * longest is returned, otherwise a parent index route lights up alongside its
 * own children.
 */
export function activeHref(path: string): string | null {
  const matches = (href: string) =>
    href === "/" ? path === "/" : path === href || path.startsWith(href + "/");
  const hits = ALL_HREFS.filter(matches);
  if (hits.length === 0) return null;
  return hits.reduce((best, h) => (h.length > best.length ? h : best));
}

export type TabId = "home" | "history" | "add" | "receipts" | "more";

/**
 * Which of the phone tab bar's five slots owns `path`.
 *
 * The centre slot is adding a receipt, not a destination in the usual sense —
 * it is the one thing this app exists to do, and burying it two taps deep in
 * More made the common case the expensive one. It costs Wallet its slot: five
 * is what fits a thumb's reach across a phone, and Wallet is the tab whose work
 * (reading balances) is least often the reason someone opens the app.
 *
 * /scan shares that slot with /add. They are two entrances to the same job —
 * /add offers the choice, /scan is the standalone camera flow — so lighting a
 * different tab depending on which one you came through would be noise.
 *
 * Everything with no slot of its own — Wallet, Plan, Lending, Statistics,
 * Settings — belongs to More, as does an unrecognised route: leaving the bar
 * with nothing lit reads as a broken screen, and More is the honest answer
 * since that is where those destinations actually live.
 */
export function tabForPath(path: string): TabId {
  const href = activeHref(path);
  if (href === "/") return "home";
  if (href === "/history") return "history";
  if (href === "/add" || href === "/scan") return "add";
  if (href === "/receipts") return "receipts";
  return "more";
}
