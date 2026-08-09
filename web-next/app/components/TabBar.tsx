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

// Split either side of the centre bubble rather than one list with the plus
// spliced in: the bubble is a different shape, a different height and carries
// no label, so treating it as "just another tab" only means special-casing it
// at every turn.
const LEFT: Tab[] = [
  { id: "home", href: "/", label: "Home", icon: ICON_PATHS.home },
  { id: "history", href: "/history", label: "History", icon: ICON_PATHS.history },
];

const RIGHT: Tab[] = [
  { id: "receipts", href: "/receipts", label: "Receipts", icon: ICON_PATHS.receipt },
];

function Glyph({ d }: { d: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">
      <path d={d} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

// Module scope, not a closure inside TabBar. React reconciles by component
// identity, and a function declared in the render body is a new identity every
// time — which throws away the DOM node and rebuilds it rather than updating
// it. A fresh node has no previous computed style, so the `transition:color`
// on .tabbar-item never runs and the active tab snaps instead of fading, while
// the More button (inline JSX, so it survives) fades as intended. `key` cannot
// save a subtree whose type changed.
function TabLink({ id, href, label, icon, current }: Tab & { current: TabId }) {
  const on = current === id;
  return (
    <Link
      href={href}
      className={"tabbar-item" + (on ? " on" : "")}
      aria-current={on ? "page" : undefined}
    >
      <Glyph d={icon} />
      <span>{label}</span>
    </Link>
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
      {LEFT.map((t) => (
        <TabLink key={t.id} {...t} current={current} />
      ))}

      {/* The camera, raised out of the bar as its own affordance. A plain tab
          would read as one more place to go; the whole point is that it is the
          thing you came to do. It carries no visible label — the bubble is the
          label — so the accessible name has to be spelled out here.
          The anchor, not the circle, is what overhangs the bar: the raised part
          of a bubble whose parent stops at the bar's edge looks tappable and
          is not, which is worse than not raising it at all. */}
      <Link
        href="/scan"
        className={"tabbar-item tabbar-plus" + (current === "scan" ? " on" : "")}
        aria-label="Scan a receipt"
        aria-current={current === "scan" ? "page" : undefined}
      >
        <span className="tabbar-bubble">
          <Glyph d={ICON_PATHS.plus} />
        </span>
      </Link>

      {RIGHT.map((t) => (
        <TabLink key={t.id} {...t} current={current} />
      ))}

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
