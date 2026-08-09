"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

// Full budget-tracker navigation (PRD §2.1). Wallet and Plan are expandable
// groups. A collapse toggle shrinks the rail to icons — a client-only preference
// persisted to localStorage, so it survives reloads without touching routing.
//
// Below 880px this same component is the mobile drawer: AppShell owns the
// open/closed state and passes it in, CSS turns the rail into an off-canvas
// panel, and every link reports the navigation back up so the drawer closes
// behind it. One component, two presentations — a second mobile-only nav would
// be a second place for routes to go stale.

type Item = { href: string; label: string };

const WALLET: Item[] = [
  { href: "/wallet", label: "Accounts" },
  { href: "/wallet/payments", label: "Payments" },
];

const PLAN: Item[] = [
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
const LENDING: Item[] = [
  { href: "/lending/debts", label: "Debts" },
  { href: "/lending/debt-activity", label: "Debt activity" },
  { href: "/lending/receivables", label: "Owed to you" },
  { href: "/lending/receivable-activity", label: "Receivable activity" },
];

// Every navigable href, used to pick the single most-specific active route.
const ALL_HREFS: string[] = [
  "/", "/history", "/statistics", "/receipts", "/settings",
  ...WALLET.map((i) => i.href),
  ...PLAN.map((i) => i.href),
  ...LENDING.map((i) => i.href),
];

function Icon({ d }: { d: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
      <path d={d} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

const ICONS = {
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
};

export default function Sidebar({
  mobileOpen = false,
  onNavigate,
}: {
  mobileOpen?: boolean;
  onNavigate?: () => void;
} = {}) {
  const path = usePathname() || "/";
  // Defaults match the server render to avoid hydration mismatches; persisted
  // prefs are applied in an effect after mount. Because the sidebar is persistent
  // (mounted once in AppShell), this runs only on first load — not per navigation
  // — so there's no navigation flash.
  const [collapsed, setCollapsed] = useState(false);
  const [open, setOpen] = useState<Record<string, boolean>>({ wallet: true, plan: false, lending: false });
  // Dark is the default (see the token blocks in globals.css); light is the only
  // state that needs storing. The attribute is already on <html> by now — the
  // inline script in layout.tsx sets it before paint — so this only mirrors it
  // into React state for the button's label.
  const [light, setLight] = useState(false);

  useEffect(() => {
    setCollapsed(localStorage.getItem("sb-collapsed") === "1");
    setLight(document.documentElement.getAttribute("data-theme") === "light");
    const groups = localStorage.getItem("sb-groups");
    if (groups) {
      try { setOpen((o) => ({ ...o, ...JSON.parse(groups) })); } catch { /* ignore */ }
    }
  }, []);

  const toggleTheme = () => {
    setLight((wasLight) => {
      const next = wasLight ? "dark" : "light";
      document.documentElement.setAttribute("data-theme", next);
      try { localStorage.setItem("theme", next); } catch { /* private mode */ }
      return !wasLight;
    });
  };

  // Auto-open the group that contains the current route — only ever opens (never
  // closes), and skips the state update when already open so navigation between
  // sibling routes doesn't trigger a needless expand/collapse jump.
  useEffect(() => {
    if (path.startsWith("/wallet")) setOpen((o) => (o.wallet ? o : { ...o, wallet: true }));
    if (path.startsWith("/plan")) setOpen((o) => (o.plan ? o : { ...o, plan: true }));
    if (path.startsWith("/lending")) setOpen((o) => (o.lending ? o : { ...o, lending: true }));
  }, [path]);

  const toggleCollapse = () => {
    setCollapsed((c) => {
      localStorage.setItem("sb-collapsed", c ? "0" : "1");
      return !c;
    });
  };
  const toggleGroup = (key: string) =>
    setOpen((o) => {
      const next = { ...o, [key]: !o[key] };
      localStorage.setItem("sb-groups", JSON.stringify(next));
      return next;
    });

  // A route matches if it's an exact hit or an ancestor of the current path.
  // But `/wallet` is an ancestor of `/wallet/payments`, so on the Payments page
  // both would match. Resolve by letting only the *most specific* (longest)
  // matching href stay active — otherwise a parent index route lights up
  // alongside its sibling child routes.
  const matches = (href: string) =>
    href === "/" ? path === "/" : path === href || path.startsWith(href + "/");
  const bestLen = Math.max(0, ...ALL_HREFS.filter(matches).map((h) => h.length));
  const active = (href: string) => matches(href) && href.length === bestLen;

  const NavLink = ({ href, label, icon }: { href: string; label: string; icon?: string }) => (
    <Link
      href={href}
      className={"nav-item" + (active(href) ? " active" : "")}
      title={label}
      onClick={onNavigate}
    >
      {icon && <Icon d={icon} />}
      <span className="label">{label}</span>
    </Link>
  );

  const Group = ({ id, label, icon, items }: { id: string; label: string; icon: string; items: Item[] }) => (
    <>
      <button
        className={"nav-item nav-group-btn" + (path.startsWith("/" + id) ? " active" : "")}
        onClick={() => toggleGroup(id)}
        title={label}
      >
        <Icon d={icon} />
        <span className="label">{label}</span>
        <svg className={"sb-caret" + (open[id] ? " open" : "")} viewBox="0 0 24 24" fill="none" stroke="currentColor">
          <path d={ICONS.caret} strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open[id] && !collapsed && (
        <div className="nav-sub">
          {items.map((it) => (
            <NavLink key={it.href} href={it.href} label={it.label} />
          ))}
        </div>
      )}
    </>
  );

  return (
    <aside
      id="app-sidebar"
      className={"sidebar" + (collapsed ? " collapsed" : "") + (mobileOpen ? " open" : "")}
    >
      <div className="sidebar-inner">
        <div className="brand-wrap">
          <div className="brand">
            <div className="brand-mark">◆</div>
            <div>
              <span className="brand-name">
                Ledger<span className="beta-pill">BETA</span>
              </span>
              <div className="brand-sub">Budget Tracker</div>
            </div>
          </div>
          {/* Two dismissals for two shapes: the rail collapses to icons, the
              drawer closes outright. CSS shows exactly one of them. */}
          <button className="collapse-btn" onClick={toggleCollapse} aria-label="Collapse sidebar">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path d={collapsed ? "m9 6 6 6-6 6" : "m15 6-6 6 6 6"} strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
          <button className="sb-close" onClick={onNavigate} aria-label="Close navigation">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path d="M18 6 6 18M6 6l12 12" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </button>
        </div>

        <nav>
          <NavLink href="/" label="Home" icon={ICONS.home} />
          <NavLink href="/history" label="History" icon={ICONS.history} />
          <Group id="wallet" label="Wallet" icon={ICONS.wallet} items={WALLET} />
          <Group id="plan" label="Plan" icon={ICONS.plan} items={PLAN} />
          <Group id="lending" label="Borrowing & Lending" icon={ICONS.lending} items={LENDING} />
          <NavLink href="/statistics" label="Statistics" icon={ICONS.stats} />
          <NavLink href="/receipts" label="Receipts" icon={ICONS.receipt} />
          <NavLink href="/settings" label="Settings" icon={ICONS.settings} />
        </nav>

        {/* Lives in the nav rather than on Settings so it is reachable from the
            mobile drawer, which is the only chrome a phone has. */}
        <button className="nav-item theme-toggle" onClick={toggleTheme} title={light ? "Switch to dark" : "Switch to light"}>
          <Icon d={light ? ICONS.moon : ICONS.sun} />
          <span className="label">{light ? "Dark mode" : "Light mode"}</span>
        </button>

        <div className="nav-user">
          <div className="avatar">◆</div>
          <div style={{ minWidth: 0 }}>
            <div style={{ fontSize: 13.5, fontWeight: 560, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              Local ledger
            </div>
            <div style={{ fontSize: 12, color: "var(--ink-3)" }}>runs on your machine</div>
          </div>
        </div>
      </div>
    </aside>
  );
}
