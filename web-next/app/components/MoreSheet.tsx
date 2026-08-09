"use client";
// The tab bar's fifth slot. Four tabs cannot hold ~20 routes, so everything
// without a slot of its own lives here: the Wallet, Plan and Lending groups,
// plus the standalone destinations and the theme toggle that would otherwise be
// stranded in a sidebar the phone tier can no longer open.
//
// Wallet is first and carries a glyph because it was demoted out of the bar
// when the camera took the centre slot — it is the one group here a reader may
// arrive looking for by name, having watched its tab disappear.
//
// Scan is deliberately absent: it owns the centre bubble now, and a second
// entry point in this list would be a row that duplicates the button the reader
// just tapped past.
import Link from "next/link";
import { usePathname } from "next/navigation";
import Sheet from "./Sheet";
import { ICON_PATHS, LENDING, PLAN, WALLET, activeHref } from "../lib/navRoutes";
import type { NavItem } from "../lib/navRoutes";
import { useTheme } from "../lib/useTheme";

const STANDALONE: (NavItem & { icon: string })[] = [
  { href: "/statistics", label: "Statistics", icon: ICON_PATHS.stats },
  { href: "/settings", label: "Settings", icon: ICON_PATHS.settings },
];

function Glyph({ d }: { d: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">
      <path d={d} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export default function MoreSheet({ onClose }: { onClose: () => void }) {
  const path = usePathname() || "/";
  const current = activeHref(path);
  const { light, toggle } = useTheme();

  const Row = ({ href, label, icon }: { href: string; label: string; icon?: string }) => (
    <Link
      href={href}
      className={"more-row" + (current === href ? " on" : "")}
      aria-current={current === href ? "page" : undefined}
    >
      {icon ? <Glyph d={icon} /> : <span className="more-dot" aria-hidden="true" />}
      <span>{label}</span>
    </Link>
  );

  return (
    <Sheet title="More" onClose={onClose}>
      <div className="more-group">
        <Row href="/wallet" label="Wallet" icon={ICON_PATHS.wallet} />
        {WALLET.filter((i) => i.href !== "/wallet").map((i) => (
          <Row key={i.href} href={i.href} label={i.label} />
        ))}
      </div>

      <div className="more-group">
        {STANDALONE.map((i) => (
          <Row key={i.href} href={i.href} label={i.label} icon={i.icon} />
        ))}
      </div>

      <div className="more-group">
        <p className="more-label">Plan</p>
        {PLAN.map((i) => (
          <Row key={i.href} href={i.href} label={i.label} />
        ))}
      </div>

      <div className="more-group">
        <p className="more-label">Borrowing &amp; Lending</p>
        {LENDING.map((i) => (
          <Row key={i.href} href={i.href} label={i.label} />
        ))}
      </div>

      <div className="more-group">
        <button className="more-row" onClick={toggle}>
          <Glyph d={light ? ICON_PATHS.moon : ICON_PATHS.sun} />
          <span>{light ? "Dark mode" : "Light mode"}</span>
        </button>
      </div>
    </Sheet>
  );
}
