"use client";
// Persistent app chrome. Rendered once by the root layout so the Sidebar and FAB
// survive route changes instead of unmounting/remounting on every navigation —
// that remount was the source of the sidebar flash and the FAB refetch churn.
// Pages render only their <main> (as `children`); the FAB now lives here, so it
// can no longer receive a per-page onChange. Instead it broadcasts a global
// "ledger:refresh" event that pages subscribe to via useRefresh() to reload
// their own data after a transaction is saved.
import { useState } from "react";
import { usePathname } from "next/navigation";
import Sidebar from "./Sidebar";
import Fab from "./Fab";
import AgentChat from "./AgentChat";

export default function AppShell({ children }: { children: React.ReactNode }) {
  const path = usePathname() || "/";
  // /scan renders its own copy of the assistant + owns the corner, so skip both
  // the global chat and the quick-add FAB there to avoid duplicate widgets.
  const onScan = path.startsWith("/scan");
  const showFab = !onScan;
  const showChat = !onScan;

  // Lift the chat's open state so the quick-add FAB can step aside while the chat
  // panel is open — both live in the bottom-right corner and would otherwise
  // overlap the panel.
  const [chatOpen, setChatOpen] = useState(false);
  // Minimized is a third state, not "closed": the conversation stays alive and
  // the panel stays docked as a header bar. Held here rather than inside
  // AgentChat because the quick-add FAB depends on it — a collapsed panel frees
  // the corner, so hiding the FAB then would be hiding it for nothing.
  const [chatMin, setChatMin] = useState(false);

  return (
    <div className="shell">
      <Sidebar />
      {children}
      {showFab && (
        <Fab
          hidden={chatOpen && !chatMin}
          onChange={() => window.dispatchEvent(new Event("ledger:refresh"))}
        />
      )}
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
    </div>
  );
}
