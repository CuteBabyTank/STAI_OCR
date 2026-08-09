"use client";
import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { ICON_PATHS as ICONS, LENDING, PLAN, WALLET, activeHref } from "../lib/navRoutes";
import type { NavItem as Item } from "../lib/navRoutes";

// Full budget-tracker navigation (PRD §2.1). Wallet and Plan are expandable
// groups. A collapse toggle shrinks the rail to icons — a client-only preference
// persisted to localStorage, so it survives reloads without touching routing.
//
// Below 880px this same component is the mobile drawer: AppShell owns the
// open/closed state and passes it in, CSS turns the rail into an off-canvas
// panel, and every link reports the navigation back up so the drawer closes
// behind it. One component, two presentations — a second mobile-only nav would
// be a second place for routes to go stale.

function Icon({ d }: { d: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
      <path d={d} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

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
  // Light is the default (see the token blocks in globals.css); dark is the only
  // state that needs storing. The attribute is already on <html> by now — the
  // inline script in layout.tsx sets it before paint — so this only mirrors it
  // into React state for the button's label.
  const [light, setLight] = useState(true);

  useEffect(() => {
    setCollapsed(localStorage.getItem("sb-collapsed") === "1");
    setLight(document.documentElement.getAttribute("data-theme") !== "dark");
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

  // Resolution lives in navRoutes so the tab bar answers this identically.
  const current = activeHref(path);
  const active = (href: string) => current === href;

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
            <Image className="brand-mark" src="/logo.png" alt="" width={32} height={32} priority />
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
