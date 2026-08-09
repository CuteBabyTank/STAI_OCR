"use client";
// The /receipts empty state. Before the ledger has anything in it there is
// nothing to operate on, which is the one place in this app where an authored
// moment earns its room: a ribbon of receipt slips travelling the curve they
// take through the product — photographed, read, filed. It answers "what is
// this page for?" for someone who has never scanned anything.
//
// It is the only animated element on the view, and it is decorative, so it
// carries its own budget: the marquee parks itself under prefers-reduced-motion
// and whenever it is offscreen or the tab is hidden (see components/ui).
import { useMemo } from "react";
import MarqueeAlongSvgPath from "@/components/ui/marquee-along-svg-path";
import { useIsPhone } from "../lib/useMediaQuery";

/* A drawn receipt, not an emoji or a photograph: thermal-paper proportions, a
   torn bottom edge, three ruled lines standing in for line items, and a solid
   total bar tinted with the category token it would carry in the real list.
   `lines` varies the ruled widths so no two slips read as the same asset. */
function ReceiptSlip({ tone, lines }: { tone: string; lines: [number, number, number] }) {
  return (
    <svg className="rl-slip" viewBox="0 0 44 58" aria-hidden="true" focusable="false">
      <path
        className="rl-slip-paper"
        d="M2 6 Q2 2 6 2 H38 Q42 2 42 6 V50 l-4 4 l-4-4 l-4 4 l-4-4 l-4 4 l-4-4 l-4 4 l-4-4 l-4 4 l-4-4 Z"
      />
      <rect className="rl-slip-rule" x="9" y="13" width={lines[0]} height="2.5" rx="1.25" />
      <rect className="rl-slip-rule" x="9" y="20" width={lines[1]} height="2.5" rx="1.25" />
      <rect className="rl-slip-rule" x="9" y="27" width={lines[2]} height="2.5" rx="1.25" />
      <rect x="9" y="36" width="19" height="5" rx="2.5" fill={tone} />
    </svg>
  );
}

/* Four category tones, matching the tokens the real receipt rows use, so the
   empty state is already speaking the ledger's colour language. */
const SLIPS: { tone: string; lines: [number, number, number] }[] = [
  { tone: "var(--cat-food)", lines: [26, 18, 22] },
  { tone: "var(--cat-shopping)", lines: [20, 25, 15] },
  { tone: "var(--cat-health)", lines: [24, 14, 20] },
  { tone: "var(--cat-other)", lines: [17, 23, 26] },
  { tone: "var(--cat-food)", lines: [22, 26, 17] },
  { tone: "var(--cat-shopping)", lines: [25, 16, 24] },
];

/* Two genuinely different paths rather than one path scaled down. The desktop
   sweep is wide and shallow — it reads as a horizontal ribbon across a roomy
   card. Squeezed into a 320px phone that same curve collapses to a flat line of
   specks, so the phone gets its own steeper curve in a near-square box: fewer
   slips, larger, with real vertical travel.

   The viewBox is sized to the curve's actual extent plus half a slip of margin,
   not to a round number. `responsive` scales by min(w/vbW, h/vbH), so any slack
   in the box is slack the slips pay for by rendering smaller. */
const DESKTOP = {
  path: "M-40 150 C 150 45, 300 205, 470 140 S 760 25, 1036 122",
  viewBox: "0 0 996 220",
  repeat: 2,
  velocity: 5.5,
};

const PHONE = {
  path: "M-24 50 C 70 14, 128 104, 172 150 S 262 210, 384 172",
  viewBox: "0 0 360 250",
  repeat: 1,
  velocity: 4.5,
};

export default function ReceiptsEmptyState({ onAdd }: { onAdd: () => void }) {
  const isPhone = useIsPhone();
  const cfg = isPhone ? PHONE : DESKTOP;

  const slips = useMemo(
    () => (isPhone ? SLIPS.slice(0, 4) : SLIPS),
    [isPhone]
  );

  return (
    <div className="es es-page">
      <div className="es-stage">
        <MarqueeAlongSvgPath
          key={isPhone ? "phone" : "desktop"}
          path={cfg.path}
          viewBox={cfg.viewBox}
          repeat={cfg.repeat}
          baseVelocity={cfg.velocity}
          slowdownOnHover
          slowDownFactor={0.18}
          draggable
          grabCursor
          dragSensitivity={0.08}
          responsive
          className="es-marquee"
        >
          {slips.map((s, i) => (
            <ReceiptSlip key={i} tone={s.tone} lines={s.lines} />
          ))}
        </MarqueeAlongSvgPath>
      </div>

      <div className="es-say">
        <h2 className="es-title">No receipts yet</h2>
        <p className="es-sub">Scan or photograph one to get started.</p>
        <button className="btn-primary es-cta" onClick={onAdd}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">
            <path d="M12 5v14M5 12h14" strokeLinecap="round" />
          </svg>
          Add receipts
        </button>
      </div>
    </div>
  );
}
