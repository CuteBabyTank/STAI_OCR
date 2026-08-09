# iOS Phone Chrome Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the phone-tier (≤640px) navigation and dialog chrome in `web-next` with iOS-conventional equivalents — a 5-item bottom tab bar, glass nav/tab surfaces, gesture-dismissible sheets, a rem type scale, and WCAG-passing secondary text.

**Architecture:** Nav route data moves out of `Sidebar.tsx` into a shared `app/lib/navRoutes.ts` so the new tab bar and the existing sidebar cannot drift. A new `TabBar` renders always and is hidden above 640px by CSS (never by JS, so the first paint is correct). A new `Sheet` primitive built on framer-motion's `dragControls` becomes the phone presentation of the existing `ui.tsx` `Modal`. All positioning changes are CSS inside the existing `@media (max-width:640px)` block.

**Tech Stack:** Next.js 14 (App Router), React 18, TypeScript, framer-motion 13 (already a dependency), vitest 2 (already configured via `npm test`, no config file — node environment, plain TS).

## Global Constraints

- **Phone tier is `≤640px`** — `BP.phone` in `app/lib/useMediaQuery.ts`. Do not introduce a second literal.
- **Nothing at 641px or wider may change**, with exactly two sanctioned exceptions: the `--ink-3` token fix (Task 2) and the `navRoutes.ts` extraction (Task 1), which changes Sidebar's imports but not its rendered output.
- **No new npm dependencies.** framer-motion 13 is already installed.
- **Minimum touch target 44×44px**, minimum 8px separation between adjacent targets.
- **Minimum text contrast 4.5:1** against both `--surface` and `--canvas`, in both themes.
- **`viewport-fit=cover` is already set** (`app/layout.tsx:24`). Do not re-add it. `env(safe-area-inset-*)` already resolves.
- **Comment style:** this codebase's comments explain *why* a rule exists and what breaks without it, not what the code does. Match that. Look at any existing block in `globals.css` for the register.
- **`globals.css` is the styling authority** — Tailwind preflight is disabled and Tailwind only serves vendored components. Write plain CSS.
- Reference spec: `docs/superpowers/specs/2026-08-10-ios-phone-chrome-design.md`.

### Deviations from the spec, decided during planning

1. **The spec said both `.modal` and `.bt-modal` route through `Sheet`.** In fact `.bt-modal` has a single shared owner (`ui.tsx`'s `Modal`), which makes Task 8 a one-file change. `.modal` has exactly one consumer — `app/scan/page.tsx:792` — and it is an always-mounted element toggled by an `.open` class rather than conditionally rendered. Converting it to `Sheet` is a differently-shaped refactor on a page that already owns its own chrome, so **`.modal` gets the CSS grab-handle/sheet treatment only** (Task 9) and is not converted. Flagged for the reviewer.
2. **`Sheet` has no `open` prop.** Every existing caller closes a dialog by unmounting it, so `AnimatePresence` would never play an exit. `Sheet` is visible while mounted and runs its own out-animation before invoking `onClose` — otherwise a sheet you dragged down would blink out at the moment you released it.

### Known limitation, accepted

Component behaviour is not unit-tested: there is no `vitest.config.*`, no jsdom, and no React Testing Library, and adding them is a dependency + config change outside this scope. Automated coverage is therefore limited to the two pure modules (Tasks 1 and 2). Task 10 is an explicit manual verification pass with a fixed checklist.

---

### Task 1: Extract nav route data and active-route resolution

`Sidebar.tsx` currently owns the route tables and the "which entry is current" logic, and its own header comment warns that a second nav would be "a second place for routes to go stale." The tab bar is that second nav, so the data moves first.

**Files:**
- Create: `web-next/app/lib/navRoutes.ts`
- Create: `web-next/app/lib/navRoutes.test.ts`
- Modify: `web-next/app/components/Sidebar.tsx` (remove lines 17–50 route tables and 140–143 matching logic; import instead)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `type NavItem = { href: string; label: string }`
  - `type TabId = "home" | "history" | "wallet" | "receipts" | "more"`
  - `const WALLET: NavItem[]`, `const PLAN: NavItem[]`, `const LENDING: NavItem[]`
  - `const ALL_HREFS: string[]`
  - `const ICON_PATHS: Record<string, string>`
  - `function activeHref(path: string): string | null`
  - `function tabForPath(path: string): TabId`

- [ ] **Step 1: Write the failing test**

Create `web-next/app/lib/navRoutes.test.ts`:

```ts
/**
 * The sidebar and the phone tab bar both have to agree on which route is
 * "current", and `/wallet` is an ancestor of `/wallet/payments` — so a naive
 * prefix match lights up two entries at once. `activeHref` resolves that by
 * returning only the longest matching href. `tabForPath` then folds that answer
 * into one of five tabs, since the tab bar has five slots for ~20 routes.
 */
import { describe, expect, it } from "vitest";

import { activeHref, tabForPath } from "./navRoutes";

describe("activeHref", () => {
  it("matches the root only exactly", () => {
    expect(activeHref("/")).toBe("/");
    expect(activeHref("/history")).toBe("/history");
  });

  it("prefers the most specific match over its ancestor", () => {
    expect(activeHref("/wallet")).toBe("/wallet");
    expect(activeHref("/wallet/payments")).toBe("/wallet/payments");
  });

  it("resolves nested group routes", () => {
    expect(activeHref("/plan/budgets")).toBe("/plan/budgets");
    expect(activeHref("/lending/receivable-activity")).toBe("/lending/receivable-activity");
  });

  it("does not match on a bare string prefix", () => {
    // "/historyz" starts with "/history" but is not a descendant of it.
    expect(activeHref("/historyz")).toBeNull();
  });

  it("returns null for an unknown route", () => {
    expect(activeHref("/nope")).toBeNull();
  });
});

describe("tabForPath", () => {
  it("maps the four direct tabs", () => {
    expect(tabForPath("/")).toBe("home");
    expect(tabForPath("/history")).toBe("history");
    expect(tabForPath("/wallet")).toBe("wallet");
    expect(tabForPath("/receipts")).toBe("receipts");
  });

  it("keeps a wallet child on the wallet tab", () => {
    expect(tabForPath("/wallet/payments")).toBe("wallet");
  });

  it("folds everything else into More, so the bar is never fully unlit", () => {
    expect(tabForPath("/plan/budgets")).toBe("more");
    expect(tabForPath("/lending/debts")).toBe("more");
    expect(tabForPath("/statistics")).toBe("more");
    expect(tabForPath("/settings")).toBe("more");
    expect(tabForPath("/scan")).toBe("more");
    expect(tabForPath("/nope")).toBe("more");
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd web-next && npx vitest run app/lib/navRoutes.test.ts`
Expected: FAIL — `Failed to resolve import "./navRoutes"`.

- [ ] **Step 3: Write the implementation**

Create `web-next/app/lib/navRoutes.ts`:

```ts
// Single source of truth for the app's route tables, its nav glyphs, and the
// question "which entry is current". Both the desktop sidebar rail and the
// phone tab bar read from here. Sidebar used to own all of this privately; a
// second navigation with its own copy would be a second place for routes to go
// stale, which is exactly what this module exists to prevent.

export type NavItem = { href: string; label: string };

export const WALLET: NavItem[] = [
  { href: "/wallet", label: "Accounts" },
  { href: "/wallet/payments", label: "Payments" },
];

export const PLAN: NavItem[] = [
  { href: "/plan/upcoming", label: "Upcoming" },
  { href: "/plan/budgets", label: "Budgets" },
  { href: "/plan/categories", label: "Categories" },
  { href: "/plan/tags", label: "Tags" },
  { href: "/plan/templates", label: "Templates" },
  { href: "/plan/recurring", label: "Recurring" },
  { href: "/plan/installments", label: "Installments" },
  { href: "/plan/goals", label: "Goals" },
  { href: "/plan/goal-activity", label: "Goal activity" },
];

// Debts & receivables and their activity logs live in their own category.
export const LENDING: NavItem[] = [
  { href: "/lending/debts", label: "Debts" },
  { href: "/lending/debt-activity", label: "Debt activity" },
  { href: "/lending/receivables", label: "Owed to you" },
  { href: "/lending/receivable-activity", label: "Receivable activity" },
];

// `/scan` is included even though no sidebar entry links to it: the phone More
// sheet does, and without it here the camera route would resolve to no active
// entry at all.
export const ALL_HREFS: string[] = [
  "/", "/history", "/statistics", "/receipts", "/settings", "/scan",
  ...WALLET.map((i) => i.href),
  ...PLAN.map((i) => i.href),
  ...LENDING.map((i) => i.href),
];

export const ICON_PATHS = {
  home: "M3 10.5 12 3l9 7.5M5 9.5V21h14V9.5",
  history: "M3 3v6h6M3 9a9 9 0 1 1 2 9M12 7v5l3 2",
  wallet: "M3 7a2 2 0 0 1 2-2h14v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zM16 12h4",
  plan: "M9 11l3 3 8-8M20 12v6a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h9",
  lending: "M3 6h18M3 12h18M3 18h18M7 3v3M7 18v3M17 3v3M17 18v3",
  stats: "M3 3v18h18M8 13v5M13 9v9M18 5v13",
  settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-2.9 1.3V22a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 7 20.4l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 3.6 15H3.5a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 5 8.6l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 10 5.6V5.5a2 2 0 0 1 4 0v.09A1.65 1.65 0 0 0 17 7l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 20.4 12v.09a1.65 1.65 0 0 0 1.3 2.9",
  receipt: "M6 2h9l5 5v14a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1zM14 2v6h6M8 13h8M8 17h6",
  scan: "M4 7V5a1 1 0 0 1 1-1h2M17 4h2a1 1 0 0 1 1 1v2M20 17v2a1 1 0 0 1-1 1h-2M7 20H5a1 1 0 0 1-1-1v-2M3 12h18",
  caret: "m9 6 6 6-6 6",
  sun: "M12 3v2m0 14v2M5.6 5.6l1.4 1.4m10 10 1.4 1.4M3 12h2m14 0h2M5.6 18.4 7 17m10-10 1.4-1.4M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z",
  moon: "M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z",
  more: "M5 12h.01M12 12h.01M19 12h.01",
};

/**
 * The single most-specific route that matches `path`, or null.
 *
 * A route matches if it is an exact hit or a true ancestor. `/wallet` is an
 * ancestor of `/wallet/payments`, so on the Payments page both match — only the
 * longest is returned, otherwise a parent index route lights up alongside its
 * own children.
 */
export function activeHref(path: string): string | null {
  const matches = (href: string) =>
    href === "/" ? path === "/" : path === href || path.startsWith(href + "/");
  const hits = ALL_HREFS.filter(matches);
  if (hits.length === 0) return null;
  return hits.reduce((best, h) => (h.length > best.length ? h : best));
}

export type TabId = "home" | "history" | "wallet" | "receipts" | "more";

/**
 * Which of the phone tab bar's five slots owns `path`.
 *
 * Wallet keeps its children (Payments is a row on the Wallet page, not its own
 * tab). Everything the bar has no slot for — Plan, Lending, Statistics,
 * Settings, Scan — belongs to More, as does an unrecognised route: leaving the
 * bar with nothing lit reads as a broken screen, and More is the honest answer
 * since that is where those destinations actually live.
 */
export function tabForPath(path: string): TabId {
  const href = activeHref(path);
  if (href === "/") return "home";
  if (href === "/history") return "history";
  if (href === "/wallet" || href?.startsWith("/wallet/")) return "wallet";
  if (href === "/receipts") return "receipts";
  return "more";
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd web-next && npx vitest run app/lib/navRoutes.test.ts`
Expected: PASS, 8 tests.

- [ ] **Step 5: Point Sidebar at the shared module**

In `web-next/app/components/Sidebar.tsx`:

Delete the local `type Item`, `WALLET`, `PLAN`, `LENDING`, `ALL_HREFS` declarations (lines 17–50) and the local `ICONS` object (lines 60–73). Add to the imports at the top:

```ts
import { ALL_HREFS, ICON_PATHS as ICONS, LENDING, PLAN, WALLET, activeHref } from "../lib/navRoutes";
import type { NavItem as Item } from "../lib/navRoutes";
```

Replace the matching logic at lines 140–143:

```ts
  const matches = (href: string) =>
    href === "/" ? path === "/" : path === href || path.startsWith(href + "/");
  const bestLen = Math.max(0, ...ALL_HREFS.filter(matches).map((h) => h.length));
  const active = (href: string) => matches(href) && href.length === bestLen;
```

with:

```ts
  // Resolution lives in navRoutes so the tab bar answers this identically.
  const current = activeHref(path);
  const active = (href: string) => current === href;
```

`ALL_HREFS` is no longer referenced in this file after that change — drop it from the import list.

- [ ] **Step 6: Verify the sidebar still builds and behaves**

Run: `cd web-next && npx tsc --noEmit`
Expected: no errors.

Run: `cd web-next && npm test`
Expected: all suites pass.

Run: `cd web-next && npm run dev`, open `http://localhost:3000` at desktop width. Confirm: Home is highlighted; navigating to Wallet → Payments highlights Payments and *not* Accounts; the Plan group auto-expands on `/plan/budgets`.

- [ ] **Step 7: Commit**

```bash
git add web-next/app/lib/navRoutes.ts web-next/app/lib/navRoutes.test.ts web-next/app/components/Sidebar.tsx
git commit -m "refactor: extract nav routes and active-route resolution from Sidebar"
```

---

### Task 2: Fix `--ink-3` contrast and lock it with a regression test

`--ink-3` carries `.stat-label`, `.header-figure-sub`, `.brand-sub`, and (from Task 4) inactive tab labels. It fails 4.5:1 in **both** themes today.

| Theme | Current | vs surface | vs canvas | New | vs surface | vs canvas |
|---|---|---|---|---|---|---|
| Light | `#9AA0AB` | 2.63:1 | 2.47:1 | `#6B7280` | 4.83:1 | 4.55:1 |
| Dark | `#6B7180` | 3.70:1 | 3.98:1 | `#7C828F` | 4.69:1 | 5.04:1 |

**Files:**
- Create: `web-next/app/lib/palette.test.ts`
- Modify: `web-next/app/globals.css:21` (light `--ink-3`), `web-next/app/globals.css:33` (dark `--ink-3`)

**Interfaces:**
- Consumes: nothing.
- Produces: nothing importable. This task's output is the corrected token values plus a test that reads `globals.css` directly, so a future palette edit cannot silently reintroduce the failure.

- [ ] **Step 1: Write the failing test**

Create `web-next/app/lib/palette.test.ts`:

```ts
/**
 * Contrast is a property of the stylesheet, not of any TS module, so this test
 * reads globals.css and checks the real token values. The point is the
 * regression guard: --ink-3 shipped at 2.63:1 in light and 3.70:1 in dark, and
 * nothing in the build would have complained. Now something does.
 */
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = readFileSync(new URL("../globals.css", import.meta.url), "utf8");

/** The declaration body of the first rule whose selector contains `selector`. */
function block(selector: string): string {
  const at = css.indexOf(selector);
  if (at < 0) throw new Error(`no rule containing selector: ${selector}`);
  const open = css.indexOf("{", at);
  const close = css.indexOf("}", open);
  if (open < 0 || close < 0) throw new Error(`unterminated rule: ${selector}`);
  return css.slice(open, close);
}

function token(body: string, name: string): string {
  const m = new RegExp(`--${name}\\s*:\\s*(#[0-9A-Fa-f]{6})`).exec(body);
  if (!m) throw new Error(`no --${name} in block`);
  return m[1];
}

/** WCAG 2.1 relative luminance. */
function luminance(hex: string): number {
  const ch = (i: number) => {
    const c = parseInt(hex.slice(1 + i * 2, 3 + i * 2), 16) / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * ch(0) + 0.7152 * ch(1) + 0.0722 * ch(2);
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

const LIGHT = block(':root[data-theme="light"]');
const DARK = block(':root[data-theme="dark"]');

describe("text tokens clear WCAG AA (4.5:1)", () => {
  for (const [theme, body] of [["light", LIGHT], ["dark", DARK]] as const) {
    const surface = token(body, "surface");
    const canvas = token(body, "canvas");

    for (const ink of ["ink", "ink-2", "ink-3"]) {
      it(`${theme}: --${ink} on surface and canvas`, () => {
        const c = token(body, ink);
        expect(contrast(c, surface)).toBeGreaterThanOrEqual(4.5);
        expect(contrast(c, canvas)).toBeGreaterThanOrEqual(4.5);
      });
    }
  }
});

describe("the secondary/tertiary hierarchy survives the fix", () => {
  it("keeps --ink-3 lighter than --ink-2 in both themes", () => {
    for (const body of [LIGHT, DARK]) {
      const surface = token(body, "surface");
      expect(contrast(token(body, "ink-3"), surface))
        .toBeLessThan(contrast(token(body, "ink-2"), surface));
    }
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd web-next && npx vitest run app/lib/palette.test.ts`
Expected: FAIL — `light: --ink-3 on surface and canvas` expects ≥4.5, receives ~2.63; `dark: --ink-3 …` receives ~3.70. The `--ink` and `--ink-2` cases pass.

- [ ] **Step 3: Fix the tokens**

In `web-next/app/globals.css`, light block (line 21), change:

```css
  --ink:#0E1116; --ink-2:#5B616E; --ink-3:#9AA0AB;
```

to:

```css
  /* --ink-3 was #9AA0AB, which is 2.63:1 on white — it carries real secondary
     copy (.stat-label, .header-figure-sub), not just decoration. 4.83:1 now,
     still a clear step lighter than --ink-2's 6.21:1. */
  --ink:#0E1116; --ink-2:#5B616E; --ink-3:#6B7280;
```

Dark block (line 33), change:

```css
  --ink:#F3F4F6; --ink-2:#9CA3AE; --ink-3:#6B7180;
```

to:

```css
  /* Dark failed too, at 3.70:1 — so this one lightens rather than darkens. */
  --ink:#F3F4F6; --ink-2:#9CA3AE; --ink-3:#7C828F;
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd web-next && npx vitest run app/lib/palette.test.ts`
Expected: PASS, 7 tests.

- [ ] **Step 5: Commit**

```bash
git add web-next/app/globals.css web-next/app/lib/palette.test.ts
git commit -m "fix: raise --ink-3 to WCAG AA in both themes, with a regression test"
```

---

### Task 3: Add glass and rem type-scale tokens

Tokens land before anything consumes them, so Tasks 4–9 can reference them without forward declarations.

**Files:**
- Modify: `web-next/app/globals.css` — the two theme blocks (lines 17–41) and the shared `:root` block (lines 42–45)

**Interfaces:**
- Consumes: nothing.
- Produces: CSS custom properties `--glass`, `--glass-border` (per theme) and `--t-tab`, `--t-caption`, `--t-small`, `--t-body`, `--t-title` (shared).

- [ ] **Step 1: Add the glass tokens to the light theme block**

In `web-next/app/globals.css`, inside `:root, :root[data-theme="light"]`, immediately after the `--shadow-lg` line, add:

```css
  /* Chrome that floats over scrolling content (the phone nav bar and tab bar).
     Deliberately not a --surface alpha: the saturate() in the backdrop-filter
     is what pulls colour up from whatever is passing underneath, and that only
     reads correctly against a near-neutral base. */
  --glass:rgba(255,255,255,.72); --glass-border:rgba(16,24,40,.08);
```

- [ ] **Step 2: Add the glass tokens to the dark theme block**

Inside `:root[data-theme="dark"]`, in the same position:

```css
  --glass:rgba(21,22,25,.72); --glass-border:rgba(255,255,255,.10);
```

- [ ] **Step 3: Add the rem type scale**

Replace the shared `:root` block (lines 42–45):

```css
:root {
  --radius:16px; --radius-sm:12px;
  --sans: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", system-ui, sans-serif;
}
```

with:

```css
:root {
  --radius:16px; --radius-sm:12px;
  --sans: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", system-ui, sans-serif;

  /* Phone type scale, in rem so it answers the reader's text-size setting.
     There is deliberately no `html { font-size }` override anywhere in this
     file — setting one in px is exactly what stops a page from scaling.
     Worth being precise about the mechanism: iOS Safari does not push the
     system Dynamic Type setting into web content. What these do respond to is
     Safari's per-site Text Size control (aA in the address bar) and the desktop
     browser's default-font-size preference. Desktop rules keep their px values;
     these are applied only to phone-tier rules. */
  --t-tab:.6875rem;    /* 11px */
  --t-caption:.75rem;  /* 12px */
  --t-small:.8125rem;  /* 13px */
  --t-body:.9375rem;   /* 15px */
  --t-title:1.3125rem; /* 21px */
}
```

- [ ] **Step 4: Verify nothing changed visually**

Run: `cd web-next && npm run dev`. The new tokens have no consumers yet, so the app must look byte-identical. Load Home at desktop and at 375px, in both themes, and confirm no visible change.

Run: `cd web-next && npm test`
Expected: all suites pass — `palette.test.ts` still resolves `--ink-3`, `--surface`, `--canvas` from both blocks.

- [ ] **Step 5: Commit**

```bash
git add web-next/app/globals.css
git commit -m "feat: add glass and rem type-scale tokens"
```

---

### Task 4: Build the TabBar component and its styles

**Files:**
- Create: `web-next/app/components/TabBar.tsx`
- Modify: `web-next/app/globals.css` — a new base rule near the other component blocks, plus rules inside `@media (max-width:640px)`

**Interfaces:**
- Consumes: `activeHref`, `tabForPath`, `ICON_PATHS`, `TabId` from `app/lib/navRoutes` (Task 1); `--glass`, `--glass-border`, `--t-tab` from Task 3.
- Produces: `default export function TabBar({ moreOpen, onMoreToggle }: { moreOpen: boolean; onMoreToggle: () => void })`.

- [ ] **Step 1: Create the component**

Create `web-next/app/components/TabBar.tsx`:

```tsx
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

const TABS: Tab[] = [
  { id: "home", href: "/", label: "Home", icon: ICON_PATHS.home },
  { id: "history", href: "/history", label: "History", icon: ICON_PATHS.history },
  { id: "wallet", href: "/wallet", label: "Wallet", icon: ICON_PATHS.wallet },
  { id: "receipts", href: "/receipts", label: "Receipts", icon: ICON_PATHS.receipt },
];

function Glyph({ d }: { d: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">
      <path d={d} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
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
      {TABS.map((t) => {
        const on = current === t.id;
        return (
          <Link
            key={t.id}
            href={t.href}
            className={"tabbar-item" + (on ? " on" : "")}
            aria-current={on ? "page" : undefined}
          >
            <Glyph d={t.icon} />
            <span>{t.label}</span>
          </Link>
        );
      })}
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
```

- [ ] **Step 2: Add the base (hidden) rule**

In `web-next/app/globals.css`, immediately before the `/* ---- ≤880px` comment that opens the drawer media block, add:

```css
/* Phone tab bar. Hidden by default and switched on in the ≤640px block, so the
   boundary lives in exactly one place and the desktop first paint is correct
   without any JS. */
.tabbar { display:none; }
```

- [ ] **Step 3: Add the phone rules**

Inside `@media (max-width:640px)`, after the `.seg-btn` rules, add:

```css
  /* ---- Bottom tab bar ------------------------------------------------ */
  .tabbar {
    display:flex; position:fixed; z-index:160;
    left:0; right:0; bottom:0;
    /* The inset is padding, not margin, so the glass runs all the way to the
       bottom of the screen behind the home indicator instead of leaving a
       stripe of page showing under the bar. */
    padding-bottom:env(safe-area-inset-bottom);
    background:var(--glass);
    -webkit-backdrop-filter:saturate(180%) blur(20px);
    backdrop-filter:saturate(180%) blur(20px);
    border-top:1px solid var(--glass-border);
  }
  .tabbar-item {
    flex:1; min-height:56px; min-width:44px;
    display:flex; flex-direction:column; align-items:center; justify-content:center; gap:3px;
    border:none; background:none; text-decoration:none;
    color:var(--ink-3); font-size:var(--t-tab); font-weight:530;
    letter-spacing:0; line-height:1;
    -webkit-tap-highlight-color:transparent;
    transition:color .15s, transform .12s;
  }
  .tabbar-item svg { width:24px; height:24px; stroke-width:1.9; }
  .tabbar-item.on { color:var(--accent); }
  /* No haptics are available to a web page on iOS, so the press has to be
     legible visually or the tap feels like it did nothing. */
  .tabbar-item:active { transform:scale(.93); }
```

- [ ] **Step 4: Add the no-backdrop-filter fallback**

At the very end of `web-next/app/globals.css`, append:

```css
/* ---- Glass fallback. Without backdrop-filter, a 72%-alpha bar over scrolling
   content is just unreadable, so the chrome goes opaque instead. ---------- */
@supports not ((backdrop-filter:blur(1px)) or (-webkit-backdrop-filter:blur(1px))) {
  @media (max-width:640px) {
    .tabbar { background:var(--surface); }
  }
}
```

- [ ] **Step 5: Verify types**

Run: `cd web-next && npx tsc --noEmit`
Expected: no errors. (The component is not yet rendered anywhere — that is Task 5.)

- [ ] **Step 6: Commit**

```bash
git add web-next/app/components/TabBar.tsx web-next/app/globals.css
git commit -m "feat: add phone bottom tab bar component and styles"
```

---

### Task 5: Wire the tab bar into AppShell and re-home the corner widgets

The tab bar takes the bottom edge, so the drawer, its trigger, and the three floating widgets all have to move out of the way.

**Files:**
- Modify: `web-next/app/components/AppShell.tsx`
- Modify: `web-next/app/globals.css` — additions inside `@media (max-width:640px)`

**Interfaces:**
- Consumes: `TabBar` (Task 4), `useIsPhone` from `app/lib/useMediaQuery`.
- Produces: `moreOpen` / `setMoreOpen` state in AppShell, consumed by `MoreSheet` in Task 7.

- [ ] **Step 1: Render the tab bar from AppShell**

In `web-next/app/components/AppShell.tsx`, add to the imports:

```ts
import TabBar from "./TabBar";
import { useIsMobile, useIsPhone } from "../lib/useMediaQuery";
```

(replacing the existing `useIsMobile` import line).

After `const [navOpen, setNavOpen] = useState(false);` add:

```ts
  const isPhone = useIsPhone();
  // The More tab's sheet. Owned here rather than inside TabBar because the tab
  // bar has to render the tab as active while the sheet is up, and the sheet
  // has to close on navigation — both need the state above the bar.
  const [moreOpen, setMoreOpen] = useState(false);
```

Extend the existing path effect (currently `setNavOpen(false)` on path change) to close the sheet too:

```ts
  // Navigating is the drawer's job finished — leaving it open would cover the
  // page the user just asked for. Same for the More sheet.
  useEffect(() => {
    setNavOpen(false);
    setMoreOpen(false);
  }, [path]);
```

Add a new effect below the existing `!isMobile` one:

```ts
  // Crossing down into the phone tier hands navigation to the tab bar. A drawer
  // opened at 700px would otherwise still be sitting there, over a tab bar that
  // now duplicates it.
  useEffect(() => {
    if (isPhone) setNavOpen(false);
  }, [isPhone]);
```

Finally, render the bar as the last child inside the `.shell` div, after `{showChat && (...)}`:

```tsx
        <TabBar moreOpen={moreOpen} onMoreToggle={() => setMoreOpen((v) => !v)} />
```

- [ ] **Step 2: Add the phone chrome rules**

In `web-next/app/globals.css`, inside `@media (max-width:640px)`, after the `.tabbar-item:active` rule from Task 4, add:

```css
  /* The drawer trigger is gone: the tab bar is the navigation now. The drawer
     itself stays in the DOM for the 641–880px tier and is simply unreachable
     here, since AppShell forces it closed on entry to this width. */
  .nav-fab { display:none; }

  /* Room for the bar, so the last row of every list clears it. */
  .shell { padding-bottom:calc(72px + env(safe-area-inset-bottom)); }
  main { min-height:calc(100dvh - 172px); }

  /* The chat launcher leaves the bottom corner to the tab bar and becomes a
     nav-bar glyph. 44px because it is now a small round target in a corner
     rather than a 54px FAB, and the floor applies either way. */
  .robot-fab {
    top:calc(10px + env(safe-area-inset-top)); bottom:auto;
    right:calc(12px + env(safe-area-inset-right));
    width:44px; height:44px; z-index:170;
  }
  .robot-fab svg { width:24px; height:24px; }
  /* The idle bob reads as a mascot in the corner; in the nav bar it just looks
     like the chrome is loose. */
  .robot-fab .float { animation:none; }
  .robot-fab .ping { width:10px; height:10px; border-width:2px; }

  /* Quick-add keeps a floating slot but clears the bar — and reclaims the right
     edge, since the 80px offset existed only to sit clear of the chat launcher
     that just vacated the corner. */
  .fab-wrap {
    right:calc(20px + env(safe-area-inset-right));
    bottom:calc(68px + env(safe-area-inset-bottom));
  }

  /* The chat sheet opens above the tab bar rather than under it. */
  .chat { bottom:calc(68px + env(safe-area-inset-bottom)); }

  /* The toast floats below the sticky nav bar instead of sliding beneath it. */
  .ocr-toast,
  .ocr-toast.aside { top:calc(66px + env(safe-area-inset-top)); }
```

- [ ] **Step 3: Verify types**

Run: `cd web-next && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Verify in the browser**

Run: `cd web-next && npm run dev`. In Chrome DevTools device toolbar at **375×812**:

- The tab bar is fixed to the bottom with five items; Home is lit on `/`.
- Tapping History / Wallet / Receipts navigates and moves the lit state.
- The bottom-left hamburger (`.nav-fab`) is **gone**.
- The chat launcher is a round button at the **top right**.
- The quick-add `+` floats at the bottom right, clear of the tab bar.
- Scrolling to the bottom of Home, the last card is not hidden behind the bar.
- At **768×1024** the hamburger and the drawer are back and the tab bar is gone.

- [ ] **Step 5: Commit**

```bash
git add web-next/app/components/AppShell.tsx web-next/app/globals.css
git commit -m "feat: wire tab bar into AppShell and re-home phone corner widgets"
```

---

### Task 6: Build the Sheet primitive

**Files:**
- Create: `web-next/app/components/Sheet.tsx`
- Modify: `web-next/app/globals.css` — a new component block before the `≤880px` media block

**Interfaces:**
- Consumes: `framer-motion` (`motion`, `useDragControls`, `useMotionValue`, `useTransform`, `useReducedMotion`).
- Produces: `default export function Sheet({ title, onClose, children, footer }: { title: string; onClose: () => void; children: ReactNode; footer?: ReactNode })`. **Visible while mounted** — there is no `open` prop. Callers mount it to show it, and `onClose` fires *after* the out-animation completes.

- [ ] **Step 1: Create the component**

Create `web-next/app/components/Sheet.tsx`:

```tsx
"use client";
// Bottom sheet with iOS-style drag dismissal. The phone presentation of every
// budget-tracker dialog (see ui.tsx) and of the tab bar's More menu.
//
// There is no `open` prop, and that is deliberate. Every caller in this app
// closes a dialog by unmounting it, so an AnimatePresence exit would never get
// to play. Instead the sheet animates itself out on dismissal and calls
// onClose when that finishes — without it, a sheet you dragged halfway down
// would blink out of existence the instant you let go.
//
// Drag is started from the grab handle only, via dragControls. A sheet whose
// whole surface is draggable needs touch-action:none on the panel, which kills
// scrolling inside .sheet-body — and these hold forms taller than the screen.
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { motion, useDragControls, useMotionValue, useReducedMotion, useTransform } from "framer-motion";

// Far enough off-screen that the panel is fully clear at rest, whatever its
// height. Clipped by the viewport, so an over-tall value is invisible.
const OFFSCREEN = 640;
// Distance OR velocity dismisses: requiring the full drag would make a quick
// flick — the way most people actually close a sheet — feel unresponsive.
const DISMISS_DISTANCE = 100;
const DISMISS_VELOCITY = 500;
const SPRING = { type: "spring" as const, stiffness: 420, damping: 40 };

export default function Sheet({
  title,
  onClose,
  children,
  footer,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
}) {
  const reduce = useReducedMotion();
  const dragControls = useDragControls();
  const panelRef = useRef<HTMLDivElement>(null);
  const [leaving, setLeaving] = useState(false);

  // The panel's translation, shared with the scrim so the backdrop lightens as
  // the sheet is pulled down — the drag reads as reversible rather than as a
  // switch that has already flipped.
  const y = useMotionValue(0);
  const scrimOpacity = useTransform(y, [0, OFFSCREEN / 2], [1, 0]);

  useEffect(() => {
    const el = panelRef.current;
    const restoreTo = document.activeElement as HTMLElement | null;
    el?.focus();

    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setLeaving(true);
        return;
      }
      // Keep focus inside: a sheet is modal, and tabbing out to the page
      // underneath leaves a screen-reader user somewhere they cannot see.
      if (e.key !== "Tab" || !el) return;
      const focusable = el.querySelectorAll<HTMLElement>(
        'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])'
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
      restoreTo?.focus();
    };
  }, []);

  return (
    <motion.div
      className="sheet-scrim"
      style={{ opacity: reduce ? undefined : scrimOpacity }}
      initial={{ opacity: 0 }}
      animate={{ opacity: leaving ? 0 : 1 }}
      transition={{ duration: 0.2 }}
      onClick={() => setLeaving(true)}
    >
      <motion.div
        ref={panelRef}
        className="sheet"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        style={{ y }}
        initial={reduce ? { opacity: 0 } : { y: OFFSCREEN }}
        animate={reduce ? { opacity: leaving ? 0 : 1 } : { y: leaving ? OFFSCREEN : 0 }}
        transition={reduce ? { duration: 0.15 } : SPRING}
        onAnimationComplete={() => {
          if (leaving) onClose();
        }}
        drag={reduce ? false : "y"}
        dragListener={false}
        dragControls={dragControls}
        // Pinned at the top so the sheet cannot be thrown up off the screen;
        // elastic only downward, which is the direction that dismisses.
        dragConstraints={{ top: 0, bottom: 0 }}
        dragElastic={{ top: 0, bottom: 0.5 }}
        onDragEnd={(_, info) => {
          if (info.offset.y > DISMISS_DISTANCE || info.velocity.y > DISMISS_VELOCITY) {
            setLeaving(true);
          }
        }}
      >
        <div
          className="sheet-grab-zone"
          onPointerDown={(e) => dragControls.start(e)}
          aria-hidden="true"
        >
          <div className="sheet-grab" />
        </div>
        <div className="sheet-head">
          <h2 className="sheet-title">{title}</h2>
          <button className="sheet-x" onClick={() => setLeaving(true)} aria-label="Close">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path d="M18 6 6 18M6 6l12 12" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </button>
        </div>
        <div className="sheet-body">{children}</div>
        {footer && <div className="sheet-foot">{footer}</div>}
      </motion.div>
    </motion.div>
  );
}
```

- [ ] **Step 2: Add the styles**

In `web-next/app/globals.css`, immediately before the `.tabbar { display:none; }` rule added in Task 4, add:

```css
/* ---- Bottom sheet (phone presentation of every dialog) ----------------- */
.sheet-scrim {
  position:fixed; inset:0; z-index:200; background:var(--scrim);
  display:flex; align-items:flex-end; justify-content:center;
}
.sheet {
  position:relative; z-index:300;
  width:100%; max-width:560px; max-height:92dvh;
  display:flex; flex-direction:column;
  background:var(--surface);
  border-radius:22px 22px 0 0; border-top:1px solid var(--border);
  box-shadow:var(--shadow-lg);
  padding-bottom:env(safe-area-inset-bottom);
  outline:none;
}
/* touch-action:none is scoped to the handle, not the panel: on the panel it
   would stop .sheet-body scrolling, and these hold forms taller than a phone. */
.sheet-grab-zone { padding:9px 0 3px; touch-action:none; cursor:grab; flex-shrink:0; }
.sheet-grab-zone:active { cursor:grabbing; }
.sheet-grab { width:38px; height:5px; border-radius:3px; background:var(--border-strong); margin:0 auto; }
.sheet-head {
  display:flex; align-items:center; justify-content:space-between;
  padding:4px 20px 4px; flex-shrink:0;
}
.sheet-title { margin:0; font-size:var(--t-title); font-weight:640; letter-spacing:-.02em; }
.sheet-x {
  width:44px; height:44px; margin-right:-10px; border-radius:50%;
  border:none; background:none; color:var(--ink-3);
  display:grid; place-items:center; flex-shrink:0;
}
.sheet-x svg { width:20px; height:20px; }
.sheet-body {
  padding:10px 20px 18px; overflow-y:auto; overscroll-behavior:contain;
  display:flex; flex-direction:column; gap:14px;
}
.sheet-foot {
  padding:14px 20px; border-top:1px solid var(--border);
  display:flex; gap:10px; flex-shrink:0;
}
.sheet-foot > * { flex:1; justify-content:center; }
```

- [ ] **Step 3: Verify types**

Run: `cd web-next && npx tsc --noEmit`
Expected: no errors. (Nothing renders `Sheet` yet — that is Task 7.)

- [ ] **Step 4: Commit**

```bash
git add web-next/app/components/Sheet.tsx web-next/app/globals.css
git commit -m "feat: add gesture-dismissible bottom Sheet primitive"
```

---

### Task 7: Build the More sheet and share the theme toggle

The More tab needs a destination, and the theme toggle currently lives only in the sidebar — which is unreachable on a phone once Task 5 lands. Both are handled here.

**Files:**
- Create: `web-next/app/lib/useTheme.ts`
- Create: `web-next/app/components/MoreSheet.tsx`
- Modify: `web-next/app/components/AppShell.tsx` (render `MoreSheet`)
- Modify: `web-next/app/components/Sidebar.tsx` (consume `useTheme`)
- Modify: `web-next/app/globals.css` (More-sheet row styles)

**Interfaces:**
- Consumes: `Sheet` (Task 6); `PLAN`, `LENDING`, `ICON_PATHS`, `activeHref` from `app/lib/navRoutes` (Task 1); `moreOpen` / `setMoreOpen` from AppShell (Task 5).
- Produces:
  - `function useTheme(): { light: boolean; toggle: () => void }`
  - `default export function MoreSheet({ onClose }: { onClose: () => void })` — visible while mounted, matching `Sheet`.

- [ ] **Step 1: Extract the theme toggle**

Create `web-next/app/lib/useTheme.ts`:

```ts
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
```

- [ ] **Step 2: Point Sidebar at the hook**

In `web-next/app/components/Sidebar.tsx`:

Add to the imports:

```ts
import { useTheme } from "../lib/useTheme";
```

Delete the `const [light, setLight] = useState(true);` declaration and the whole `toggleTheme` function (lines 104–111). Remove the `setLight(...)` line from the mount effect, leaving the `collapsed` and `groups` restoration in place. Add near the other hooks:

```ts
  const { light, toggle: toggleTheme } = useTheme();
```

The `theme-toggle` button's JSX is unchanged.

- [ ] **Step 3: Create the More sheet**

Create `web-next/app/components/MoreSheet.tsx`:

```tsx
"use client";
// The tab bar's fifth slot. Four tabs cannot hold ~20 routes, so everything
// without a slot of its own lives here: the Plan and Lending groups, plus the
// three standalone destinations and the theme toggle that would otherwise be
// stranded in a sidebar the phone tier can no longer open.
//
// Scan is listed first among the standalone rows because until now the camera
// flow — the thing this app is for — had no persistent entry point at all; it
// was reachable only from an empty-state CTA on Home.
import Link from "next/link";
import { usePathname } from "next/navigation";
import Sheet from "./Sheet";
import { ICON_PATHS, LENDING, PLAN, activeHref } from "../lib/navRoutes";
import type { NavItem } from "../lib/navRoutes";
import { useTheme } from "../lib/useTheme";

const STANDALONE: (NavItem & { icon: string })[] = [
  { href: "/scan", label: "Scan a receipt", icon: ICON_PATHS.scan },
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
```

- [ ] **Step 4: Render it from AppShell**

In `web-next/app/components/AppShell.tsx`, add to the imports:

```ts
import MoreSheet from "./MoreSheet";
```

and render it directly after `<TabBar ... />`:

```tsx
        {moreOpen && <MoreSheet onClose={() => setMoreOpen(false)} />}
```

- [ ] **Step 5: Add the row styles**

In `web-next/app/globals.css`, immediately after the `.sheet-foot > *` rule from Task 6, add:

```css
/* More-sheet rows. Grouped rather than one flat list: nineteen undifferentiated
   links is a wall, and the groups already exist as concepts in the sidebar. */
.more-group { display:flex; flex-direction:column; gap:2px; }
.more-group + .more-group { margin-top:6px; padding-top:10px; border-top:1px solid var(--border); }
.more-label {
  margin:0 0 4px; padding:0 12px;
  font-size:var(--t-caption); font-weight:600; letter-spacing:.04em;
  text-transform:uppercase; color:var(--ink-3);
}
.more-row {
  display:flex; align-items:center; gap:12px;
  min-height:48px; padding:0 12px; border-radius:12px;
  border:none; background:none; width:100%; text-align:left;
  font-size:var(--t-body); font-weight:500; color:var(--ink); text-decoration:none;
  -webkit-tap-highlight-color:transparent;
}
.more-row svg { width:20px; height:20px; stroke-width:1.9; color:var(--ink-2); flex-shrink:0; }
.more-row.on { background:var(--accent-wash); color:var(--accent); }
.more-row.on svg { color:var(--accent); }
.more-row:active { background:var(--sunken); }
/* Rows without a glyph keep their labels on the same left edge as those with
   one, so the list does not read as two ragged columns. */
.more-dot { width:20px; flex-shrink:0; }
```

- [ ] **Step 6: Verify types**

Run: `cd web-next && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 7: Verify in the browser**

Run: `cd web-next && npm run dev`, DevTools device toolbar at **375×812**:

- Tapping **More** slides a sheet up from the bottom with a grab handle.
- **Dragging the handle down ~120px releases and dismisses it**, animating out rather than vanishing.
- A short, fast **flick** down also dismisses it.
- Dragging down 30px and releasing **springs it back**.
- Tapping the scrim dismisses it; pressing **Escape** dismisses it.
- The sheet body **scrolls** when the content overflows, and scrolling the body does not drag the sheet.
- Tapping **Scan a receipt** navigates to `/scan` and the sheet closes.
- On `/plan/budgets`, the **More** tab is lit.
- The theme toggle in the sheet switches themes and the choice survives a reload.
- At desktop width, the sidebar theme toggle still works.

- [ ] **Step 8: Commit**

```bash
git add web-next/app/lib/useTheme.ts web-next/app/components/MoreSheet.tsx web-next/app/components/AppShell.tsx web-next/app/components/Sidebar.tsx web-next/app/globals.css
git commit -m "feat: add More sheet and share the theme toggle between navs"
```

---

### Task 8: Route the shared Modal through Sheet on phone

`ui.tsx` exports one `Modal` used by every budget-tracker dialog, so this is a single-file change that converts all of them at once.

**Files:**
- Modify: `web-next/app/components/ui.tsx:20-80` (the `Modal` function)

**Interfaces:**
- Consumes: `Sheet` (Task 6), `useIsPhone` from `app/lib/useMediaQuery`.
- Produces: no signature change. `Modal`'s public props (`title`, `onClose`, `children`, `footer`, `wide`) are unchanged, so no caller is touched.

- [ ] **Step 1: Add the phone branch**

In `web-next/app/components/ui.tsx`, add to the imports at the top of the file:

```ts
import Sheet from "./Sheet";
import { useIsPhone } from "../lib/useMediaQuery";
```

Inside `Modal`, immediately after the destructured parameter list and **before** the existing `useEffect`, insert:

```tsx
  // On a phone this dialog is a drag-dismissible sheet instead. Sheet owns its
  // own Escape handling, scroll lock and focus trap, so the effect below is
  // skipped along with the desktop markup.
  //
  // useIsPhone reports false on the first render by design (it must match the
  // server), which would flash the desktop dialog for a frame. It does not in
  // practice: a Modal is only ever mounted in response to a tap, long after the
  // media-query effect has settled.
  const isPhone = useIsPhone();
```

Then, immediately before the existing `return (` statement, insert:

```tsx
  if (isPhone) {
    // `wide` is a desktop max-width concern; a sheet is always full-bleed.
    return (
      <Sheet title={title} onClose={onClose} footer={footer}>
        {children}
      </Sheet>
    );
  }
```

The existing `useEffect` must be moved **above** the `if (isPhone)` early return so hook order stays stable across renders — React requires every hook to run on every render. Keep the effect where it is (before the `if`), and leave its body unchanged; the duplicate Escape/scroll-lock while a sheet is up is harmless because `Sheet` restores the previous `overflow` value it captured.

- [ ] **Step 2: Verify hook ordering**

Read the modified `Modal` top to bottom and confirm the order is: `useIsPhone()` → `useEffect(...)` → `useRef(...)` → `if (isPhone) return <Sheet/>` → desktop `return`. No hook may appear after the early return.

Run: `cd web-next && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Verify in the browser**

Run: `cd web-next && npm run dev`, at **375×812**:

- Tap the quick-add `+` → **Expense**. The form arrives as a sheet with a grab handle.
- Drag it down and release: it dismisses without saving.
- Scroll the form fields: the sheet does not move.
- Focus an input; the keyboard does not hide the field.
- The footer buttons are full-width and side by side.
- Saving an expense still works and the ledger refreshes.

At **1280×800**: the same dialog is the unchanged centred modal.

- [ ] **Step 4: Commit**

```bash
git add web-next/app/components/ui.tsx
git commit -m "feat: present shared Modal as a drag-dismissible sheet on phone"
```

---

### Task 9: Sticky glass nav bar and the rem type scale

The last two visual pieces: the per-page `<header>` becomes the nav bar, and phone-tier text moves onto the rem scale.

**Files:**
- Modify: `web-next/app/globals.css` — the `@media (max-width:640px)` block and the `@supports` fallback at the end of the file

**Interfaces:**
- Consumes: `--glass`, `--glass-border`, `--t-*` (Task 3).
- Produces: nothing importable.

- [ ] **Step 1: Make the page header a sticky glass nav bar**

In `web-next/app/globals.css`, inside `@media (max-width:640px)`, at the **top** of the block (before the `.stat-grid` rules), add:

```css
  /* ---- Nav bar ------------------------------------------------------- */
  /* The page's own <header> becomes the nav bar. No NavBar component is
     introduced: twenty routes already render a header with an h1, and this way
     none of them need touching. Sticky works here because html uses
     `overflow-x:clip` rather than `hidden` — chosen originally for exactly this
     reason, since `hidden` would make html a scroll container and break every
     position:sticky descendant.
     The negative margins cancel .shell's padding so the glass reaches both
     edges; the right padding reserves the chat launcher's 44px corner. */
  main > header {
    position:sticky; top:0; z-index:100;
    margin:-16px calc(-14px - env(safe-area-inset-right)) 0 calc(-14px - env(safe-area-inset-left));
    padding:calc(10px + env(safe-area-inset-top)) calc(64px + env(safe-area-inset-right))
            10px calc(14px + env(safe-area-inset-left));
    background:var(--glass);
    -webkit-backdrop-filter:saturate(180%) blur(20px);
    backdrop-filter:saturate(180%) blur(20px);
    border-bottom:1px solid var(--glass-border);
  }
```

- [ ] **Step 2: Extend the glass fallback**

At the end of `web-next/app/globals.css`, change the `@supports` block added in Task 4 from:

```css
  @media (max-width:640px) {
    .tabbar { background:var(--surface); }
  }
```

to:

```css
  @media (max-width:640px) {
    .tabbar, main > header { background:var(--surface); }
  }
```

- [ ] **Step 3: Move phone text onto the rem scale**

Inside `@media (max-width:640px)`, replace these existing declarations with their token equivalents:

- `h1 { font-size:19px; }` → `h1 { font-size:var(--t-title); }`
- `.header-figure-sub { font-size:12.5px; }` → `.header-figure-sub { font-size:var(--t-caption); }`

And append at the end of the block:

```css
  /* Phone-tier body copy on the rem scale, so it answers Safari's per-site Text
     Size control. Desktop rules keep their px values — this is scoped to the
     phone tier along with everything else in this block. */
  .subhead, .stat-label { font-size:var(--t-small); }
  .nav-item, .more-row, .btn-primary, .chip { font-size:var(--t-body); }
```

- [ ] **Step 4: Give the legacy scan modal the sheet treatment**

`.modal` has one consumer, `app/scan/page.tsx:792`, and it is an always-mounted element toggled by an `.open` class rather than conditionally rendered — so it is not converted to `Sheet` (see "Deviations" above). It gets the visual treatment only. Replace the existing line inside the ≤640px block:

```css
  .modal { width:calc(100vw - 24px); max-height:86dvh; padding:20px; }
```

with:

```css
  /* The scan page's past-receipts dialog. Not routed through <Sheet>: it is
     always mounted and toggled by an .open class, so it would need converting
     to conditional rendering first. It gets the sheet's shape and a handle so
     it does not read as a stray centred box among real sheets. */
  .modal {
    top:auto; bottom:0; left:0; transform:translateY(12px); width:100%;
    max-height:86dvh; padding:20px 20px calc(20px + env(safe-area-inset-bottom));
    border-radius:22px 22px 0 0;
  }
  .modal.open { transform:none; }
  .modal::before {
    content:""; display:block; width:38px; height:5px; border-radius:3px;
    background:var(--border-strong); margin:-6px auto 12px;
  }
```

- [ ] **Step 5: Verify in the browser**

Run: `cd web-next && npm run dev`, at **375×812**:

- Scrolling Home: the header **stays pinned** at the top and content passes translucently beneath it, tinting as coloured cards go by.
- The chat launcher sits inside the header band and does not overlap the title.
- The OCR toast (trigger a scan) appears **below** the header, not under it.
- In Safari on a real device or the iOS simulator, set **aA → larger text**: labels, headings and rows grow; the tab bar and layout hold.
- At **1280×800**: the header is not sticky and not translucent.
- On `/scan`, opening past receipts shows a bottom-anchored panel with a handle.

Run: `cd web-next && npm test`
Expected: all suites pass.

- [ ] **Step 6: Commit**

```bash
git add web-next/app/globals.css
git commit -m "feat: sticky glass nav bar and phone-tier rem type scale"
```

---

### Task 10: Verification pass

Component behaviour has no automated coverage (see "Known limitation"), so this pass is the gate.

**Files:** none modified unless a defect is found.

- [ ] **Step 1: Full automated suite**

```bash
cd web-next && npm test && npx tsc --noEmit && npm run build
```
Expected: tests pass, no type errors, production build succeeds.

- [ ] **Step 2: Touch-target audit**

In DevTools at 375×812, inspect each and confirm the rendered box is ≥44px in both dimensions, with ≥8px between neighbours:

- each `.tabbar-item`
- `.robot-fab`
- `.fab`
- `.sheet-x`
- `.more-row` (48px specified)
- `.pn-btn`, `.eye-btn` (already raised in the pre-existing working-tree diff)

- [ ] **Step 3: Both themes, both orientations**

At 375×812 and 812×375, in light and dark: Home, History, Wallet, Receipts, and one More destination. Confirm no horizontal scrollbar, no content trapped under the tab bar or header, and glass legible over both pale and saturated cards.

- [ ] **Step 4: Small-phone check**

At **320×568** (iPhone SE gen 1): the five tab labels must not truncate or wrap. If any does, reduce `.tabbar-item` `font-size` to `.625rem` inside the existing `@media (max-width:360px)` block rather than shrinking it for every phone.

- [ ] **Step 5: Reduced motion**

Enable "Emulate CSS prefers-reduced-motion: reduce" in DevTools Rendering. Open a sheet: it must **cross-fade**, not slide, and must not be draggable. Closing must still work via the X, the scrim and Escape.

- [ ] **Step 6: Keyboard and screen reader**

With the More sheet open: `Tab` cycles within the sheet and never reaches the page behind it; `Escape` closes it; focus returns to the More tab. In VoiceOver (or Chrome's accessibility tree), the tab bar announces as a navigation landmark named "Primary" and the current tab reports as current.

- [ ] **Step 7: No desktop regression**

At 1280×800, compare against `main`:

```bash
git stash list && git diff main --stat -- web-next/app/globals.css
```

Walk Home, History, Wallet → Payments, Plan → Budgets, Receipts, Settings. The only intended visual difference is slightly darker (light) / lighter (dark) secondary text from the `--ink-3` fix. Anything else is a defect.

- [ ] **Step 8: Commit any fixes**

```bash
git add -A web-next
git commit -m "fix: address findings from the phone chrome verification pass"
```

---

## Self-review

**Spec coverage:**

| Spec section | Task |
|---|---|
| §1 Boundary at 640, drawer disabled | 5 |
| §1 Route matching extraction | 1 |
| §1 TabBar (5 items, aria, 44pt, safe area) | 4 |
| §1 MoreSheet | 7 |
| §1 Wallet keeps children | 1 (`tabForPath`), 7 |
| §2 No NavBar component; sticky glass header | 9 |
| §2 Chat launcher → nav bar | 5 |
| §2 FAB lifted + right:20px | 5 |
| §2 OCR toast clears header | 5 |
| §3 Glass tokens, saturate(180%), @supports fallback | 3, 4, 9 |
| §4 Sheet primitive, drag/velocity dismiss, reduced motion, focus trap | 6 |
| §4 `.bt-modal` routes through Sheet | 8 |
| §4 `.modal` routes through Sheet | **9 — deviated, CSS only, documented** |
| §5 rem type scale | 3, 9 |
| §5 `--ink-3` contrast fix | 2 |
| §5 Touch targets and semantics audit | 10 |
| §6 `navRoutes` tests | 1 |
| §6 Contrast assertions | 2 |
| §6 Manual browser verification | 10 |
| z-index map | 4 (160), 5 (170), 6 (200/300), 9 (100) |

No spec requirement is unimplemented; the one deviation is stated at the top and in the table.

**Placeholder scan:** no TBD/TODO, no "add error handling", no "similar to Task N". Every code step carries the literal code.

**Type consistency:** `activeHref`, `tabForPath`, `TabId`, `NavItem`, `ICON_PATHS`, `WALLET`/`PLAN`/`LENDING` are declared in Task 1 and used with those exact names in Tasks 4, 7 and 9. `Sheet`'s props (`title`, `onClose`, `children`, `footer`) are declared in Task 6 and consumed identically in Tasks 7 and 8. `useTheme` returns `{ light, toggle }` in Task 7 and is destructured as such in both consumers. `MoreSheet` takes only `onClose`, matching its Task 5 call site.
