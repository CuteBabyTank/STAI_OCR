# iOS phone chrome for web-next

Date: 2026-08-10
Status: approved, ready for planning

## Goal

Bring the `web-next` phone layout in line with 2026 iOS Human Interface Guidelines:
bottom tab bar navigation, glass chrome, gesture-dismissible sheets, 44pt touch
targets, scalable type, and 4.5:1 text contrast.

## Scope

**In scope:** the phone tier only — `≤640px` (`BP.phone`).

**Out of scope:** the desktop rail layout, the 641–879px drawer tier, the colour
palette, and the type scale used by desktop-only rules. Nothing above 640px
changes behaviour or appearance, with two deliberate exceptions noted under
"Shared changes" below.

### Not deliverable on the web

Two items from the source brief cannot be built and are dropped, not deferred:

- **Dynamic Island.** No web API exposes it. A page cannot draw into it.
- **Haptics.** `navigator.vibrate` is not implemented in iOS Safari. The
  substitute is visual press feedback — a scale/opacity change on `:active`,
  which the app already applies to `.btn-primary` and `.fab`.

Predictive/AI-adaptive interfaces are also out of scope; that is a product
change, not a design-system change.

## Current state

- Next.js 14, React 18, hand-rolled `globals.css` (~1,750 lines) as the styling
  authority. Tailwind is present but only supplies utilities to vendored
  components; preflight is disabled.
- `framer-motion` v13 is already a dependency.
- Navigation is a 212px sidebar rail that becomes an off-canvas drawer below
  880px, opened by `NavFab` (a bottom-left floating button).
- Three widgets share the bottom-right corner: quick-add `Fab`, `AgentChat`
  launcher, and `OcrToast`. `AppShell` contains explicit logic to shuffle them
  so they do not overlap.
- Two modal systems: `.modal` (receipts; stays centred on phone) and
  `.bt-modal` (becomes a bottom sheet via a CSS keyframe). Neither is
  gesture-dismissible.
- `/scan`, the camera flow, is absent from the nav entirely — reachable only
  from an empty-state CTA on Home (`app/page.tsx:284`).
- `viewport-fit=cover` is **already** set (`app/layout.tsx:24`), so
  `env(safe-area-inset-*)` already resolves. No change needed there.

## Design

### 1. Navigation shell

`BP.phone` (640) becomes a behavioural boundary, not just a styling one. At
≤640px:

- `TabBar` is the navigation.
- `NavFab`, the drawer, and `.nav-scrim` are hidden via CSS, and `AppShell`
  short-circuits their open state so no scrim can mount over the tab bar.
- 641–879px keeps the existing drawer, unchanged.

`useIsPhone()` already exists in `app/lib/useMediaQuery.ts` for the JS side.

#### Route matching extraction

`Sidebar.tsx` currently owns `ALL_HREFS` and the most-specific-match logic, and
its header comment names the risk directly: a second nav is "a second place for
routes to go stale."

Move to a new `app/lib/navRoutes.ts`:

- `WALLET`, `PLAN`, `LENDING`, `ALL_HREFS` route tables
- `activeHref(path: string): string | null` — returns the single longest
  matching href, the logic currently inline at `Sidebar.tsx:140-143`

`Sidebar` and `TabBar` both consume it. This is the only refactor of existing
code in this spec, and it exists to serve the new nav.

#### New: `app/components/TabBar.tsx`

Five destinations, reusing the existing `ICONS` glyph set:

| Tab | Route | Icon |
|---|---|---|
| Home | `/` | `ICONS.home` |
| History | `/history` | `ICONS.history` |
| Wallet | `/wallet` | `ICONS.wallet` |
| Receipts | `/receipts` | `ICONS.receipt` |
| More | (sheet) | kebab/ellipsis |

- `<nav aria-label="Primary">`; each destination a `<Link>` carrying
  `aria-current="page"` when active.
- More is a `<button aria-expanded>`, not a link.
- Item height 56px content + `env(safe-area-inset-bottom)`, comfortably over
  the 44pt floor for an icon+label stack.
- Icon 24px, label 11px (`--t-tab`), 2px gap.
- Active state: `--accent` fill on both icon and label. Inactive: `--ink-3`
  (post-contrast-fix, so the inactive label is legible).
- `z-index: 160`.

`/wallet/payments` is reached as a row on the Wallet page, not a nested tab.

#### New: `app/components/MoreSheet.tsx`

Opened by the More tab. Rendered through `Sheet` (§4). Contents:

- Plan group (9 routes), Lending group (4 routes) — as grouped rows
- Statistics, Settings, Scan
- Theme toggle, moved from the sidebar (which is unreachable on phone)

The More tab renders active whenever the current route is one of its
descendants, so no screen leaves the tab bar with nothing lit.

### 2. Nav bar and corner widgets

**No `NavBar` component is introduced.** Twenty pages already render their own
`<header>` with an `h1`; rewriting them is churn. At ≤640px, CSS gives that
existing `header` `position: sticky; top: 0` plus the glass treatment (§3).

This works because `html` uses `overflow-x: clip` rather than `hidden` — chosen
specifically to preserve sticky descendants (`globals.css:49-56`).

Corner reassignment at ≤640px:

- **Chat launcher** → fixed glyph at top-right, aligned to the sticky header
  (`z-index: 170`, above the header's 100). `AgentChat`'s panel behaviour on
  phone is unchanged.
- **Quick-add FAB** → stays floating bottom-right, lifted to
  `bottom: calc(56px + env(safe-area-inset-bottom) + 12px)` to clear the tab bar.
  It also moves from `right: 96px` to `right: 20px`: that 96px offset existed
  only to sit clear of the chat launcher, which no longer occupies the corner.
  `Fab.tsx`'s flow logic is untouched; only `.fab-wrap` positioning changes.
- **OCR toast** → keeps its existing phone behaviour of floating at the top, but
  gains a top offset so it clears the now-sticky header instead of sitting under it.

`AppShell`'s existing corner-shuffling logic simplifies on phone: with the FAB
and chat no longer sharing the bottom-right, the `toastAside` calculation stays
desktop-only (it already is).

### 3. Material

Glass applies to exactly two surfaces: the sticky header and the tab bar.

New tokens, per theme:

```css
/* light */
--glass: rgba(255,255,255,.72);
--glass-border: rgba(16,24,40,.08);
/* dark */
--glass: rgba(21,22,25,.72);
--glass-border: rgba(255,255,255,.10);
```

Applied as:

```css
background: var(--glass);
backdrop-filter: saturate(180%) blur(20px);
-webkit-backdrop-filter: saturate(180%) blur(20px);
```

`saturate(180%)` is what produces the HIG's "picks up hues from the content
beneath" behaviour. A fallback block keeps the chrome opaque where the filter is
unsupported:

```css
@supports not ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
  .tabbar, main > header { background: var(--surface); }
}
```

Cards and content surfaces stay opaque. Glass over scrolling content is where
the pattern degrades into unreadable mud.

### 4. Sheets

#### New: `app/components/Sheet.tsx`

A controlled framer-motion primitive:

- Props: `open`, `onClose`, `title`, `children`, optional `footer`.
- Visual grab handle at top.
- `drag="y"`, `dragConstraints={{ top: 0, bottom: 0 }}`, `dragElastic={{ top: 0, bottom: 0.4 }}`
  — rubber-bands downward, rigid upward.
- Dismiss when `offset.y > 100 || velocity.y > 500`, so a short flick closes it.
- Scrim opacity interpolated from drag offset.
- Spring easing `cubic-bezier(.32, .72, 0, 1)` — the curve already used by the
  existing `@keyframes sheet`.
- Owns focus trap, Escape-to-close, and `body` scroll lock. This logic is
  currently duplicated across modal call sites; the sheet centralises it for
  phone.
- `prefers-reduced-motion: reduce` → drag disabled, cross-fade instead.
- `z-index: 300`, scrim `200`, matching the existing `.bt-scrim` / modal band.

At ≤640px both `.modal` and `.bt-modal` render through `Sheet`. Above 640px both
keep their current presentation with no change.

### 5. Type and contrast

#### rem type scale

Root stays at the browser default (16px); no `html { font-size }` override,
which would defeat user text-size settings. New tokens:

```css
--t-caption: .6875rem;  /* 11px */
--t-tab:     .6875rem;
--t-small:   .8125rem;  /* 13px */
--t-body:    .9375rem;  /* 15px */
--t-title:   1.3125rem; /* 21px */
```

Applied to the rules the phone layout touches: tab bar, sticky header, stat
tiles, transaction rows, sheet bodies, labels. Desktop-only rules keep their px
values, consistent with the phone-only scope.

This makes text respond to Safari's per-site Text Size control. Note the honest
limit: iOS Safari does not propagate the system Dynamic Type setting to web
pages automatically — the per-site control is the mechanism, and rem is what
makes the app answer it.

#### Contrast fix

`--ink-3` fails 4.5:1 in **both** themes. It carries `.stat-label`,
`.header-figure-sub`, `.brand-sub`, and inactive tab labels.

| Theme | Current | Surface | Canvas | New | Surface | Canvas |
|---|---|---|---|---|---|---|
| Light | `#9AA0AB` | 2.63:1 | 2.47:1 | `#6B7280` | 4.83:1 | 4.55:1 |
| Dark | `#6B7180` | 3.70:1 | 3.98:1 | `#7C828F` | 4.69:1 | 5.04:1 |

Both replacements keep a clear hierarchy step below `--ink-2` (6.21:1 light,
7.12:1 dark). Ratios computed per WCAG 2.1 relative-luminance, not estimated.

This is a token change, so it lands on desktop too — the first of two
deliberate exceptions to the phone-only scope. Fixing a failing contrast ratio
on phone while leaving it failing on desktop is not a defensible split.

#### Touch targets and semantics

The uncommitted working-tree diff already raised `.eye-btn`, `.pn-btn`,
`.collapse-btn` to 44px and gave `.link`/`.back-link` a 44px hit area via
padding with compensating negative margin. That work stands and is not redone.
Remaining: audit the new tab bar, sheet controls, and MoreSheet rows against the
44px floor and the 8px minimum separation.

### Shared changes (outside the phone tier)

Two changes are unavoidably global:

1. The `--ink-3` contrast fix (justified above).
2. `navRoutes.ts` extraction — `Sidebar` changes its imports but not its
   rendered output.

Everything else is inside `@media (max-width: 640px)` or gated on `useIsPhone()`.

## z-index map

Slotting into the existing scale:

| Layer | z-index |
|---|---|
| Sticky glass header | 100 |
| Quick-add FAB (`.fab-wrap`, existing) | 150 |
| Tab bar | 160 |
| Chat launcher glyph | 170 |
| Sheet scrim | 200 |
| Sheet | 300 |
| Camera viewfinder (existing) | 400 |

The tab bar sits above the FAB so a positioning drift can never render the FAB
over the bar.

## Testing

`app/lib/navRoutes.test.ts` (vitest, already configured):

- `activeHref("/")` → `/`, and does not match `/history`
- `activeHref("/wallet/payments")` → `/wallet/payments`, not `/wallet`
- `activeHref("/plan/budgets")` → resolves within PLAN, driving More-tab active state
- An unknown route returns `null`

A contrast assertion in the same suite computes WCAG ratios for the new
`--ink-3` values against both surface and canvas in both themes, asserting
`>= 4.5`. This keeps the fix from silently regressing in a future palette edit.

Gesture behaviour, glass rendering, and safe-area handling are verified manually
in the browser at 375px width, in both themes.

## Success criteria

- Phone navigation is a 5-item bottom tab bar; the drawer is unreachable ≤640px.
- Every route in the sidebar remains reachable on phone.
- `/scan` has a persistent entry point (MoreSheet) for the first time.
- Sheets dismiss on downward swipe or flick.
- Header and tab bar are translucent, with an opaque fallback.
- All text clears 4.5:1 in both themes.
- Text scales with Safari's Text Size control.
- Nothing at 641px or wider renders differently, apart from the `--ink-3`
  darkening/lightening.
