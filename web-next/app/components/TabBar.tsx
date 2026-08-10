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

// The bar's layout floor, shipped with the markup instead of only in
// globals.css. Everything cosmetic — glass, colour, sizing, the bubble — stays
// in the stylesheet; what lives here is only the handful of declarations that
// decide whether this is a usable bar or a broken one.
//
// The reason is a real failure this bar hit repeatedly: a deploy can serve a
// JS bundle newer than its stylesheet. When that happens the markup arrives
// with no .tabbar rules at all, so the <nav> falls back to whatever the old
// stylesheet said about bare navs — a column — and the five tabs stack on top
// of each other. A <style> element rendered by the component cannot be out of
// sync with the component, so this floor holds no matter which stylesheet the
// browser got.
//
// `nav.tabbar` rather than `.tabbar` so it outranks any bare `nav` rule, and
// the block sits after the stylesheet link in document order so it also wins
// specificity ties.
const LAYOUT_FLOOR = `
nav.tabbar{display:none}
@media (max-width:640px){
nav.tabbar{display:flex;flex-direction:row;flex-wrap:nowrap;display:grid;grid-template-columns:repeat(5,1fr);gap:0;align-items:end;position:fixed;left:0;right:0;bottom:0;z-index:160}
nav.tabbar>a,nav.tabbar>button{flex:1 1 0;min-width:0;height:56px;display:flex;align-items:center;justify-content:center;padding:0;border:none;background:none}
}`;

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
      // The bar is glyphs only, so the label has to survive as the accessible
      // name — an icon-only link with no aria-label announces as its href.
      aria-label={label}
    >
      <Glyph d={icon} />
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
    <>
      {/* Outside the <nav>, not inside it: a grid container treats every child
          as a cell, and a stray non-item in the track list is a trap waiting
          for the first rule that gives it a box. */}
      <style dangerouslySetInnerHTML={{ __html: LAYOUT_FLOOR }} />
      <nav className="tabbar" aria-label="Primary">
      {LEFT.map((t) => (
        <TabLink key={t.id} {...t} current={current} />
      ))}

      {/* Adding a receipt, raised out of the bar as its own affordance. A plain
          tab would read as one more place to go; the whole point is that it is
          the thing you came to do. It carries no visible label — the bubble is
          the label — so the accessible name has to be spelled out here.
          It opens /add, which offers upload or camera, rather than jumping
          straight into the viewfinder: about half the time the photo already
          exists in the camera roll, and a flow that assumes otherwise makes
          that the longer path. */}
      <Link
        href="/add"
        className={"tabbar-item tabbar-plus" + (current === "add" ? " on" : "")}
        aria-label="Add a receipt"
        aria-current={current === "add" ? "page" : undefined}
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
        aria-label="More"
      >
        <Glyph d={ICON_PATHS.more} />
      </button>
      </nav>
    </>
  );
}
