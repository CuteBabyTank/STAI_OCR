"use client";
// One drawn icon system for every empty state in the ledger.
//
// A single chip form — the same rounded card, border, and shadow — carries a
// different glyph per domain. That is deliberate: it gives twenty-odd empty
// states one visual family instead of twenty unrelated illustrations, and it
// keeps every glyph on one stroke weight (1.8) at one size, which is what stops
// a set like this reading as clip art. No emoji, no unicode glyphs: every mark
// here is authored.

export type GlyphName =
  | "receipt" | "coins" | "card" | "target" | "gauge" | "tag"
  | "handshake" | "calendar" | "clock" | "chart" | "document" | "arrows";

/* 24×24, stroked, no fill. Every path is drawn on the same grid so the chips
   read as siblings when they travel the path together. */
const GLYPHS: Record<GlyphName, React.ReactNode> = {
  receipt: <><path d="M6 3h12v18l-2.4-1.6L13.2 21l-2.4-1.6L8.4 21 6 19.4V3Z" /><path d="M9.5 8h5M9.5 12h5" /></>,
  coins: <><ellipse cx="12" cy="6.5" rx="6.5" ry="2.8" /><path d="M5.5 6.5v5c0 1.55 2.91 2.8 6.5 2.8s6.5-1.25 6.5-2.8v-5" /><path d="M5.5 11.5v5c0 1.55 2.91 2.8 6.5 2.8s6.5-1.25 6.5-2.8v-5" /></>,
  card: <><rect x="2.5" y="5" width="19" height="14" rx="2.6" /><path d="M2.5 9.75h19" /><path d="M6.5 14.75h4" /></>,
  target: <><circle cx="12" cy="12" r="8.5" /><circle cx="12" cy="12" r="4.4" /><circle cx="12" cy="12" r="1" /></>,
  gauge: <><path d="M3.5 16.5a8.5 8.5 0 0 1 17 0" /><path d="M12 16.5 16 10" /><circle cx="12" cy="16.5" r="1.1" /></>,
  tag: <><path d="m11.6 3 8.4 8.4a2 2 0 0 1 0 2.83l-5.77 5.77a2 2 0 0 1-2.83 0L3 11.6V3h8.6Z" /><circle cx="7.6" cy="7.6" r="1.3" /></>,
  handshake: <><path d="m8 12.5 2.5 2.5 2-2 2.5 2.5" /><path d="M3 9.5 7.5 5h9L21 9.5l-3.5 5.5-3-3-2 2-2.5-2.5L7 15 3 9.5Z" /></>,
  calendar: <><rect x="3.5" y="5" width="17" height="15.5" rx="2.4" /><path d="M3.5 10h17M8.5 3v4M15.5 3v4" /></>,
  clock: <><circle cx="12" cy="12" r="8.6" /><path d="M12 7v5.2l3.4 2" /></>,
  chart: <><path d="M4 20.2V13M9.4 20.2V7.5M14.8 20.2v-9M20.2 20.2V4.5" /></>,
  document: <><path d="M6 2.8h7.6L19 8.2v13H6V2.8Z" /><path d="M13.4 2.8v5.6H19" /><path d="M9 13h7M9 16.6h4.6" /></>,
  arrows: <><path d="M7.5 4.5v15M7.5 4.5 4 8M7.5 4.5 11 8" /><path d="M16.5 19.5v-15M16.5 19.5 13 16M16.5 19.5 20 16" /></>,
};

/* The chip: a card of "paper" with the glyph inside, tinted by a category token
   so the art speaks the same colour language as the ledger's real rows. */
export function Chip({ glyph, tone }: { glyph: GlyphName; tone: string }) {
  return (
    <svg className="es-chip" viewBox="0 0 56 56" aria-hidden="true" focusable="false">
      <rect className="es-chip-card" x="3" y="3" width="50" height="50" rx="15" />
      <g
        className="es-chip-glyph"
        transform="translate(16 16)"
        stroke={tone}
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      >
        {GLYPHS[glyph]}
      </g>
    </svg>
  );
}

/* The four category tones already in the token set, cycled so a run of chips
   never repeats a colour back to back. */
export const TONES = [
  "var(--cat-food)",
  "var(--cat-shopping)",
  "var(--cat-health)",
  "var(--cat-other)",
] as const;

export function chipsFor(glyphs: GlyphName[]) {
  return glyphs.map((glyph, i) => ({ glyph, tone: TONES[i % TONES.length] }));
}
