import { useEffect } from "react";

// Re-run a page's loader when the shared FAB (in the persistent layout) saves a
// transaction. The FAB dispatches a global "ledger:refresh" event; each page
// passes its own `load` callback here so per-page data stays in sync even though
// the FAB no longer lives on the page. `load` is memoized (useCallback) by every
// caller, so the listener is registered once and cleaned up on unmount.
export function useRefresh(load: () => void) {
  useEffect(() => {
    window.addEventListener("ledger:refresh", load);
    return () => window.removeEventListener("ledger:refresh", load);
  }, [load]);
}

// Broadcast that the ledger changed (a transaction, account, category, etc. was
// created/edited/deleted) so every `useRefresh` subscriber — pages *and* the
// global FAB — reloads in real time. Call this after any mutation whose result
// other mounted views depend on (e.g. adding an account the Transfer modal needs).
export function broadcastRefresh() {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event("ledger:refresh"));
  }
}
