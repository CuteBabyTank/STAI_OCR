"use client";
// Persistent app chrome. Rendered once by the root layout so the Sidebar and FAB
// survive route changes instead of unmounting/remounting on every navigation —
// that remount was the source of the sidebar flash and the FAB refetch churn.
// Pages render only their <main> (as `children`); the FAB now lives here, so it
// can no longer receive a per-page onChange. Instead it broadcasts a global
// "ledger:refresh" event that pages subscribe to via useRefresh() to reload
// their own data after a transaction is saved.
//
// Below 880px the Sidebar stops being a rail and becomes an off-canvas drawer.
// The open/closed state is owned here rather than inside Sidebar because two
// other pieces of chrome depend on it: NavFab is the floating button that opens
// it, and the scrim that closes it is a sibling of both.
import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import Sidebar from "./Sidebar";
import NavFab from "./NavFab";
import Fab from "./Fab";
import AgentChat from "./AgentChat";
import OcrToast from "./OcrToast";
import TabBar from "./TabBar";
import MoreSheet from "./MoreSheet";
import { useOcrJobs } from "../lib/ocrJobs";
import { useIsMobile, useIsPhone } from "../lib/useMediaQuery";

export default function AppShell({ children }: { children: React.ReactNode }) {
  const path = usePathname() || "/";
  // /scan renders its own copy of the assistant + owns the corner, so skip both
  // the global chat and the quick-add FAB there to avoid duplicate widgets.
  const onScan = path.startsWith("/scan");
  const showFab = !onScan;
  const showChat = !onScan;

  const isMobile = useIsMobile();
  const [navOpen, setNavOpen] = useState(false);

  const isPhone = useIsPhone();
  // The More tab's sheet. Owned here rather than inside TabBar because the tab
  // bar has to render the tab as active while the sheet is up, and the sheet
  // has to close on navigation — both need the state above the bar.
  const [moreOpen, setMoreOpen] = useState(false);

  // Navigating is the drawer's job finished — leaving it open would cover the
  // page the user just asked for. Same for the More sheet.
  useEffect(() => {
    setNavOpen(false);
    setMoreOpen(false);
  }, [path]);

  // Growing past the breakpoint turns the drawer back into a rail; a stale "open"
  // would then leave the scrim mounted over a perfectly normal desktop layout.
  useEffect(() => {
    if (!isMobile) setNavOpen(false);
  }, [isMobile]);

  // Crossing down into the phone tier hands navigation to the tab bar. A drawer
  // opened at 700px would otherwise still be sitting there, over a tab bar that
  // now duplicates it.
  useEffect(() => {
    if (isPhone) setNavOpen(false);
  }, [isPhone]);

  // A drawer over a still-scrolling page reads as broken. Escape closes it too,
  // matching every other dismissible surface in the app.
  useEffect(() => {
    if (!navOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setNavOpen(false);
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [navOpen]);

  // Lift the chat's open state so the quick-add FAB can step aside while the chat
  // panel is open — both live in the bottom-right corner and would otherwise
  // overlap the panel.
  const [chatOpen, setChatOpen] = useState(false);
  // Minimized is a third state, not "closed": the conversation stays alive and
  // the panel stays docked as a header bar. Held here rather than inside
  // AgentChat because the quick-add FAB depends on it — a collapsed panel frees
  // the corner, so hiding the FAB then would be hiding it for nothing.
  const [chatMin, setChatMin] = useState(false);

  // Three widgets share the bottom-right corner: the chat launcher (always at
  // right:24), the quick-add FAB (right:96) and now the OCR progress toast. The
  // toast's home is directly above the launcher — but the chat panel opens into
  // exactly that space, so while the panel is up the toast drops into the FAB's
  // slot instead and the FAB steps aside for it. That keeps all three on screen
  // and non-overlapping in every combination of open/minimized.
  //
  // None of that shuffling applies on a phone: there the chat is a full-width
  // bottom sheet and the toast floats at the top of the screen instead, so the
  // two can never collide and the FAB has no reason to move (see the mobile
  // block in globals.css).
  const { running, finishedAt } = useOcrJobs();
  const toastActive = running || finishedAt !== null;
  const toastAside = !isMobile && showChat && chatOpen;

  return (
    <>
      <NavFab onClick={() => setNavOpen((v) => !v)} open={navOpen} />
      <div
        className={"nav-scrim" + (navOpen ? " open" : "")}
        onClick={() => setNavOpen(false)}
        aria-hidden="true"
      />
      <div className="shell">
        <Sidebar mobileOpen={navOpen} onNavigate={() => setNavOpen(false)} />
        {children}
        {showFab && (
          <Fab
            // On a phone the chat sheet covers the bottom of the screen entirely,
            // so the FAB hides whenever the sheet is up rather than only when the
            // toast needs its slot.
            hidden={chatOpen && (isMobile || !chatMin || toastActive)}
            onChange={() => window.dispatchEvent(new Event("ledger:refresh"))}
          />
        )}
        <OcrToast aside={toastAside} />
        {showChat && (
          <AgentChat
            open={chatOpen}
            onOpenChange={(v) => {
              setChatOpen(v);
              // Reopening should never land on a collapsed panel.
              if (v) setChatMin(false);
            }}
            minimized={chatMin}
            onMinimizedChange={setChatMin}
          />
        )}
        <TabBar moreOpen={moreOpen} onMoreToggle={() => setMoreOpen((v) => !v)} />
        {moreOpen && <MoreSheet onClose={() => setMoreOpen(false)} />}
      </div>
    </>
  );
}
