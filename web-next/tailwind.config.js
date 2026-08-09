/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  corePlugins: {
    /* Preflight is off on purpose. app/globals.css is a complete hand-written
       system — it already owns the box-sizing reset, margin zeroing, heading
       scale, and control styling. Letting Tailwind's reset in underneath would
       restyle every heading, list, and button in the ledger to gain four
       layout utilities. Tailwind is here as a utility supplement for vendored
       components under components/ui, not as this project's base layer. */
    preflight: false,
  },
  theme: {
    extend: {
      /* Bridge to the design tokens in globals.css so a utility written against
         Tailwind resolves to the same value as the hand-written CSS, in both
         themes. Without this, `bg-surface` and `var(--surface)` would drift. */
      colors: {
        canvas: "var(--canvas)",
        surface: "var(--surface)",
        sunken: "var(--sunken)",
        border: "var(--border)",
        "border-strong": "var(--border-strong)",
        ink: "var(--ink)",
        "ink-2": "var(--ink-2)",
        "ink-3": "var(--ink-3)",
        accent: "var(--accent)",
        "accent-hover": "var(--accent-hover)",
        "accent-wash": "var(--accent-wash)",
        positive: "var(--positive)",
        negative: "var(--negative)",
        warn: "var(--warn)",
      },
      borderRadius: {
        token: "var(--radius)",
        "token-sm": "var(--radius-sm)",
      },
      boxShadow: {
        token: "var(--shadow)",
        "token-lg": "var(--shadow-lg)",
      },
      fontFamily: {
        sans: "var(--sans)",
      },
      transitionTimingFunction: {
        /* The two curves already in use across globals.css. */
        arrive: "cubic-bezier(.22, 1, .36, 1)",
        sheet: "cubic-bezier(.32, .72, 0, 1)",
      },
    },
  },
  plugins: [],
}
