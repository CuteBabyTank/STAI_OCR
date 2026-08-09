"use client";
// Primary navigation for the phone tier. Rendered unconditionally by AppShell
// and hidden above 640px by CSS rather than by a JS breakpoint check: the
// media-query hooks in lib/useMediaQuery return false on the server and on the
// first client render, so gating this in JS would flash a tab bar onto every
// desktop first paint.
//
// display:none (not visibility) is what hides it, so on desktop these links are
// out of the tab order and out of the accessibility tree entirely.
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ICON_PATHS, tabForPath } from "../lib/navRoutes";
import type { TabId } from "../lib/navRoutes";

type Tab = { id: TabId; href: string; label: string; icon: string };

const TABS: Tab[] = [
  { id: "home", href: "/", label: "Home", icon: ICON_PATHS.home },
  { id: "history", href: "/history", label: "History", icon: ICON_PATHS.history },
  { id: "wallet", href: "/wallet", label: "Wallet", icon: ICON_PATHS.wallet },
  { id: "receipts", href: "/receipts", label: "Receipts", icon: ICON_PATHS.receipt },
];

function Glyph({ d }: { d: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">
      <path d={d} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export default function TabBar({
  moreOpen,
  onMoreToggle,
}: {
  moreOpen: boolean;
  onMoreToggle: () => void;
}) {
  const path = usePathname() || "/";
  const current = tabForPath(path);

  return (
    <nav className="tabbar" aria-label="Primary">
      {TABS.map((t) => {
        const on = current === t.id;
        return (
          <Link
            key={t.id}
            href={t.href}
            className={"tabbar-item" + (on ? " on" : "")}
            aria-current={on ? "page" : undefined}
          >
            <Glyph d={t.icon} />
            <span>{t.label}</span>
          </Link>
        );
      })}
      {/* More is a button, not a link: it opens a sheet rather than navigating.
          It also reports active for every destination it contains, so routes
          like /plan/budgets never leave the bar with nothing lit. */}
      <button
        type="button"
        className={"tabbar-item" + (current === "more" || moreOpen ? " on" : "")}
        onClick={onMoreToggle}
        aria-expanded={moreOpen}
        aria-haspopup="dialog"
      >
        <Glyph d={ICON_PATHS.more} />
        <span>More</span>
      </button>
    </nav>
  );
}
