"use client";
// The navigation entry point below 880px: a floating button rather than a top
// bar. It replaces the sticky header for two reasons — the header ate 56px of
// vertical space on every screen, and a bottom-left button is inside thumb reach
// on a phone while the top-left corner is not.
//
// It sits opposite the quick-add and chat FABs (bottom-right), so the bottom row
// reads left-to-right as "where am I going" then "what am I adding". Rendered by
// AppShell, which owns the drawer's open state; `.nav-fab` is display:none above
// the breakpoint so the desktop rail is untouched.
export default function NavFab({
  onClick,
  open,
}: {
  onClick: () => void;
  open: boolean;
}) {
  return (
    <button
      className={"nav-fab" + (open ? " open" : "")}
      onClick={onClick}
      aria-label={open ? "Close navigation" : "Open navigation"}
      aria-expanded={open}
      aria-controls="app-sidebar"
    >
      {/* Three bars that fold into an X: the button states what it will do next,
          and the drawer covers this corner while open so the X stays reachable. */}
      <span className="nav-fab-bars" aria-hidden="true">
        <i />
        <i />
        <i />
      </span>
    </button>
  );
}
