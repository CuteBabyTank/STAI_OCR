"use client";
// Placeholder scaffold for routes not yet built out (Plan sub-modules, Payments,
// Statistics, Settings). Keeps the full PRD navigation live while later phases
// fill in real functionality. Renders only its <main>; the persistent Sidebar +
// FAB come from the shared AppShell in the root layout.
export default function Stub({ title, subtitle, phase }: { title: string; subtitle: string; phase: string }) {
  return (
    <>
      <main>
        <header>
          <div>
            <h1>{title}</h1>
            <p className="subhead">{subtitle}</p>
          </div>
        </header>
        <div className="card empty-note">
          <div style={{ fontSize: 40, marginBottom: 10 }}>🚧</div>
          <div style={{ fontWeight: 560, color: "var(--ink-2)" }}>Coming in {phase}</div>
          <div style={{ marginTop: 4 }}>This screen is scaffolded; its features arrive in a later build phase.</div>
        </div>
      </main>
    </>
  );
}
