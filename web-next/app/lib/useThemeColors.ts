"use client";
import { useEffect, useState } from "react";

// Recharts renders SVG whose `fill`/`stroke` can't resolve CSS `var()`, so we
// resolve the design tokens to concrete values at runtime and re-resolve whenever
// the theme changes (data-theme toggle or OS scheme change).
const TOKENS = [
  "accent", "positive", "negative", "ink", "ink-2", "ink-3",
  "border", "surface", "cat-food", "cat-shopping", "cat-health", "cat-other",
] as const;

type Token = (typeof TOKENS)[number];
export type ThemeColors = Record<Token, string>;

function read(): ThemeColors {
  const cs = getComputedStyle(document.documentElement);
  const out = {} as ThemeColors;
  for (const t of TOKENS) out[t] = cs.getPropertyValue(`--${t}`).trim() || "#888";
  return out;
}

export function useThemeColors(): ThemeColors | null {
  const [colors, setColors] = useState<ThemeColors | null>(null);

  useEffect(() => {
    const update = () => setColors(read());
    update();

    const mo = new MutationObserver(update);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });

    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    mq.addEventListener("change", update);

    return () => {
      mo.disconnect();
      mq.removeEventListener("change", update);
    };
  }, []);

  return colors;
}
