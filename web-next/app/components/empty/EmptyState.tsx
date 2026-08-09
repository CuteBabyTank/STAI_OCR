"use client";
// The one empty state used across the ledger.
//
// Every page that can show "nothing here" renders this: a ribbon of drawn chips
// travelling a curve, then the line explaining the state, then the action that
// resolves it. An empty state that only says "No data." tells you the query
// worked; this one tells you what the page is for and how to fill it.
//
// It is the only animated element on any view it appears in, and it inherits the
// marquee's motion budget: the loop parks under prefers-reduced-motion and
// whenever it is offscreen or the tab is hidden.
import { useMemo } from "react";
import MarqueeAlongSvgPath from "@/components/ui/marquee-along-svg-path";
import { useIsPhone } from "../../lib/useMediaQuery";
import { Chip, chipsFor, type GlyphName } from "./EmptyArt";

/* Three curves, so nine pages do not all run the same sweep. Each viewBox is
   sized to its curve's real extent plus half a chip — `responsive` scales by
   min(w/vbW, h/vbH), so slack in the box is slack the chips pay for by
   rendering smaller. Phone curves are steeper and near-square rather than the
   desktop curve shrunk, which would flatten to a line of specks at 390px. */
const CURVES = [
  {
    desktop: { path: "M-40 150 C 150 45, 300 205, 470 140 S 760 25, 1036 122", viewBox: "0 0 996 220" },
    phone: { path: "M-24 50 C 70 14, 128 104, 172 150 S 262 210, 384 172", viewBox: "0 0 360 250" },
    panel: { path: "M-20 96 C 60 40, 140 120, 210 88 S 330 44, 420 84", viewBox: "0 0 400 160" },
  },
  {
    desktop: { path: "M-40 120 C 190 210, 320 30, 500 120 S 780 210, 1036 130", viewBox: "0 0 996 220" },
    phone: { path: "M-24 190 C 80 214, 120 96, 176 74 S 280 60, 384 120", viewBox: "0 0 360 250" },
    panel: { path: "M-20 68 C 70 120, 150 44, 220 76 S 340 118, 420 78", viewBox: "0 0 400 160" },
  },
  {
    desktop: { path: "M-40 96 C 220 40, 300 190, 520 168 S 800 60, 1036 106", viewBox: "0 0 996 220" },
    phone: { path: "M-24 96 C 90 178, 150 60, 190 118 S 280 214, 384 150", viewBox: "0 0 360 250" },
    panel: { path: "M-20 60 C 80 34, 130 116, 200 104 S 330 48, 420 70", viewBox: "0 0 400 160" },
  },
];

export type EmptyStateProps = {
  glyphs: GlyphName[];
  title: string;
  sub?: string;
  action?: { label: string; onClick: () => void } | { label: string; href: string };
  /** `panel` is the inner-card size — a breakdown list, a modal, a sub-panel. */
  size?: "page" | "panel";
  /** Which of the three curves to run. Defaults to a stable pick from `title`. */
  curve?: number;
};

export default function EmptyState({
  glyphs, title, sub, action, size = "page", curve,
}: EmptyStateProps) {
  const isPhone = useIsPhone();

  // A stable per-page curve without threading an index through every call site.
  const idx = curve ?? [...title].reduce((n, c) => n + c.charCodeAt(0), 0) % CURVES.length;
  /* A panel is ~370px wide whatever the device, so it takes the narrow box on
     desktop too — running the 996-wide curve inside it would scale the chips
     down to specks, which is the same trap the phone breakpoint avoids. */
  const cfg = size === "panel"
    ? CURVES[idx].panel
    : isPhone ? CURVES[idx].phone : CURVES[idx].desktop;

  // Panels are narrow; a long run of chips there reads as clutter.
  const chips = useMemo(() => {
    const wanted = size === "panel" ? 3 : isPhone ? 4 : 6;
    const g: GlyphName[] = [];
    while (g.length < wanted) g.push(...glyphs);
    return chipsFor(g.slice(0, wanted));
  }, [glyphs, isPhone, size]);

  return (
    <div className={`es es-${size}`}>
      <div className="es-stage">
        <MarqueeAlongSvgPath
          key={`${size}-${isPhone ? "p" : "d"}-${idx}`}
          path={cfg.path}
          viewBox={cfg.viewBox}
          repeat={size === "panel" ? 1 : isPhone ? 1 : 2}
          baseVelocity={size === "panel" ? 3.5 : isPhone ? 4.5 : 5.5}
          slowdownOnHover
          slowDownFactor={0.18}
          draggable
          grabCursor
          dragSensitivity={0.08}
          responsive
          /* Chips stay upright: a tilted glyph stops reading as its own icon. */
          followPathRotation={false}
          className="es-marquee"
        >
          {chips.map((c, i) => (
            <Chip key={i} glyph={c.glyph} tone={c.tone} />
          ))}
        </MarqueeAlongSvgPath>
      </div>

      <div className="es-say">
        <h2 className="es-title">{title}</h2>
        {sub && <p className="es-sub">{sub}</p>}
        {action && ("href" in action ? (
          <a className="btn-primary es-cta" href={action.href}>{action.label}</a>
        ) : (
          <button className="btn-primary es-cta" onClick={action.onClick}>{action.label}</button>
        ))}
      </div>
    </div>
  );
}
