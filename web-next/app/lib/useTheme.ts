"use client";
// The theme toggle now has two homes — the desktop sidebar and the phone More
// sheet — so the read/write pair lives here rather than being implemented twice
// and drifting.
import { useEffect, useState } from "react";

export function useTheme(): { light: boolean; toggle: () => void } {
  // Light is the default (see the token blocks in globals.css); dark is the only
  // state that needs storing. The attribute is already on <html> by the time
  // this runs — the inline script in layout.tsx sets it before paint — so this
  // only mirrors it into React state for the button's label.
  const [light, setLight] = useState(true);

  useEffect(() => {
    setLight(document.documentElement.getAttribute("data-theme") !== "dark");
  }, []);

  const toggle = () =>
    setLight((wasLight) => {
      const next = wasLight ? "dark" : "light";
      document.documentElement.setAttribute("data-theme", next);
      try {
        localStorage.setItem("theme", next);
      } catch {
        /* private mode */
      }
      return !wasLight;
    });

  return { light, toggle };
}
