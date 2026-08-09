"use client";
import { useEffect, useState } from "react";

// Single source of truth for the layout breakpoints, so JS and CSS can't drift.
// 880 is where the sidebar stops being a rail and becomes a drawer; 640 is the
// phone-shaped tier (single column, bottom-sheet modals, 16px inputs).
export const BP = { drawer: 880, phone: 640 } as const;

/**
 * Subscribe to a media query. Always returns `false` on the server and on the
 * first client render so the markup matches what the server produced — the real
 * value lands in the effect right after mount. Anything that must be correct in
 * the very first paint belongs in CSS, not here.
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(false);

  useEffect(() => {
    const mq = window.matchMedia(query);
    const update = () => setMatches(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, [query]);

  return matches;
}

/** True while the sidebar is a drawer rather than a persistent rail. */
export const useIsMobile = () => useMediaQuery(`(max-width:${BP.drawer}px)`);

/** True on phone-width screens. */
export const useIsPhone = () => useMediaQuery(`(max-width:${BP.phone}px)`);

/** True when the primary input is touch — no hover, so hover-only affordances
 *  have to be made permanent rather than revealed. */
export const useIsTouch = () => useMediaQuery("(hover:none) and (pointer:coarse)");
