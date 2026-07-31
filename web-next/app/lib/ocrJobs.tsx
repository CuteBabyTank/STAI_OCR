"use client";
// Background OCR runs, owned above the page tree.
//
// The run used to live inside the Add-receipts modal, so closing that modal
// orphaned it: the POST kept going and the backend still filed the receipts, but
// its progress and results had nowhere to land, and the receipts list never
// refreshed. A vision read costs a minute or two per page, so "wait with this
// window open" was the whole cost of the design.
//
// This provider owns the staging list AND the run. It is mounted in layout.tsx
// around AppShell, so a run outlives the modal and every route change, and the
// corner toast can report on it from anywhere in the app.
//
// Scope of "background": the fetch still belongs to this document, so a full page
// reload (or closing the tab) drops the progress display. The backend completes
// the read and writes the receipts regardless — nothing is lost from the ledger,
// it just stops being watched. Surviving a reload would need a server-side job
// queue with a status endpoint, which is a different change.

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
} from "react";
import { broadcastRefresh } from "./useRefresh";

export type OcrStatus = "queued" | "reading" | "done" | "error";

export interface OcrItem {
  // Stable id, not the array index: files can be staged while an earlier read is
  // still running, so rows shift and positional writes would clobber each other.
  key: number;
  name: string;
  status: OcrStatus;
  id?: number;
  merchant?: string;
  amount?: number;
  currency?: string;
  error?: string;
}

export interface OcrCounts {
  queued: number;
  reading: number;
  done: number;
  error: number;
}

interface OcrJobsValue {
  items: OcrItem[];
  counts: OcrCounts;
  running: boolean;
  /** Files in the current (or most recent) run — the denominator for progress.
   *  Taken from the run itself rather than from `items`, which can still hold
   *  rows from an earlier run the user hasn't dismissed. */
  runTotal: number;
  /** Bumped each time a run finishes, so the toast can react to completion. */
  finishedAt: number | null;
  /** What the most recent run actually achieved. A snapshot, not derived from
   *  `items` — the toast has to keep reporting it after the modal closes and
   *  clears those rows. `filed` counts receipts (a PDF page is a receipt), while
   *  `failed` counts files that produced nothing. */
  lastResult: { filed: number; failed: number } | null;
  /** Stage files for a later read. No network call, nothing written. */
  stage: (files: File[]) => void;
  /** Drop a staged file before it is ever read. */
  unstage: (key: number) => void;
  /** Start reading every staged file. Returns immediately — the run continues
   *  after the caller unmounts. */
  run: () => void;
  /** Acknowledge a finished run: drop its rows and stop reporting it. Ignored
   *  while a run is in flight, so closing the modal mid-read changes nothing. */
  clearFinished: () => void;
  /** Whether the Add-receipts modal is on screen. The toast needs to know: when
   *  it retires itself it also acknowledges the run, and doing that while the
   *  modal is open would pull the results out from under the person reading them. */
  viewerOpen: boolean;
  setViewerOpen: (open: boolean) => void;
}

// One POST per chunk, one chunk at a time, so a big drop never oversubscribes
// the model.
const CLIENT_CHUNK = 12;

const OcrJobsContext = createContext<OcrJobsValue | null>(null);

export function OcrJobsProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<OcrItem[]>([]);
  const [running, setRunning] = useState(false);
  const [runTotal, setRunTotal] = useState(0);
  const [finishedAt, setFinishedAt] = useState<number | null>(null);
  const [lastResult, setLastResult] = useState<{
    filed: number;
    failed: number;
  } | null>(null);
  const [viewerOpen, setViewerOpen] = useState(false);

  // `items` is mirrored into a ref and every write goes through commit(). The run
  // loop is a long-lived async closure that must read the CURRENT rows, and it
  // outlives the render that started it — reading React state from that closure
  // would see whatever was there when the run began.
  const itemsRef = useRef<OcrItem[]>([]);
  const runningRef = useRef(false);
  const seqRef = useRef(0);
  // Staged files, keyed by row. A File is inert data the render never reads, so
  // it stays out of state.
  const stagedRef = useRef(new Map<number, File>());

  const commit = useCallback((next: OcrItem[]) => {
    itemsRef.current = next;
    setItems(next);
  }, []);

  const patch = useCallback(
    (key: number, next: OcrItem) =>
      commit(itemsRef.current.map((it) => (it.key === key ? next : it))),
    [commit],
  );

  const stage = useCallback(
    (files: File[]) => {
      if (!files.length) return;
      const rows = files.map((f) => {
        const key = (seqRef.current += 1);
        stagedRef.current.set(key, f);
        return { key, name: f.name, status: "queued" as const };
      });
      commit([...itemsRef.current, ...rows]);
    },
    [commit],
  );

  const unstage = useCallback(
    (key: number) => {
      stagedRef.current.delete(key);
      commit(itemsRef.current.filter((it) => it.key !== key));
    },
    [commit],
  );

  const clearFinished = useCallback(() => {
    if (runningRef.current) return;
    commit(
      itemsRef.current.filter(
        (it) => it.status !== "done" && it.status !== "error",
      ),
    );
    setFinishedAt(null);
    setLastResult(null);
  }, [commit]);

  const run = useCallback(() => {
    // One run at a time: chunks are already sequential, and a second concurrent
    // run would oversubscribe the model the chunking exists to protect.
    if (runningRef.current) return;
    const queued = itemsRef.current
      .filter((it) => it.status === "queued")
      .map((it) => ({ key: it.key, file: stagedRef.current.get(it.key)! }))
      .filter((q) => q.file);
    if (!queued.length) return;

    runningRef.current = true;
    setRunning(true);
    setRunTotal(queued.length);
    setFinishedAt(null);
    setLastResult(null);
    commit(
      itemsRef.current.map((it) =>
        queued.some((q) => q.key === it.key)
          ? { ...it, status: "reading" as const }
          : it,
      ),
    );

    // Deliberately not awaited: the caller (the modal) may unmount at any moment,
    // and this loop has to keep going when it does.
    void (async () => {
      let ok = 0;
      try {
        for (let start = 0; start < queued.length; start += CLIENT_CHUNK) {
          const chunk = queued.slice(start, start + CLIENT_CHUNK);
          const fd = new FormData();
          chunk.forEach(({ file }) => fd.append("files", file));
          try {
            const res = await fetch("/api/extract/batch", {
              method: "POST",
              body: fd,
            });
            const rawText = await res.text();
            let j: any = {};
            try {
              j = rawText ? JSON.parse(rawText) : {};
            } catch {
              /* non-JSON */
            }
            if (!res.ok) {
              throw new Error(
                j.detail ||
                  (res.status >= 500
                    ? "The model couldn't read these receipts (it may be busy). Try again in a moment."
                    : rawText.slice(0, 160) || res.statusText),
              );
            }
            const results: any[] = j.results || [];
            chunk.forEach(({ key, file: f }) => {
              const mine = results.filter((r) => r.source_file === f.name);
              const good = mine.filter((r) => !r.error && r.receipt_id);
              good.forEach(() => (ok += 1));
              if (good.length === 0) {
                patch(key, {
                  key,
                  name: f.name,
                  status: "error",
                  error: mine[0]?.error || "Failed to read",
                });
              } else {
                const first = good[0].data || {};
                const pages = mine.length;
                patch(key, {
                  key,
                  name:
                    pages > 1
                      ? `${f.name} · ${good.length}/${pages} pages`
                      : f.name,
                  status: "done",
                  id: good[0].receipt_id,
                  merchant: first.vendor_name || f.name,
                  amount:
                    pages > 1
                      ? good.reduce(
                          (s, r) => s + (r.data?.total_amount || 0),
                          0,
                        )
                      : (first.total_amount ?? 0),
                  currency: first.currency,
                });
              }
            });
          } catch (e: any) {
            chunk.forEach(({ key, file: f }) =>
              patch(key, {
                key,
                name: f.name,
                status: "error",
                error: e?.message || "Failed to read",
              }),
            );
          }
        }
      } finally {
        // Read attempts are spent — don't let a retry silently re-send them.
        queued.forEach(({ key }) => stagedRef.current.delete(key));
        // Snapshot this run's outcome before anything can clear its rows.
        const failed = itemsRef.current.filter(
          (r) => r.status === "error" && queued.some((q) => q.key === r.key),
        ).length;
        runningRef.current = false;
        setRunning(false);
        setLastResult({ filed: ok, failed });
        setFinishedAt(Date.now());
        // Broadcast rather than call back into the modal: by now the modal is
        // often closed, and the receipts list still has to pick the new rows up.
        if (ok) broadcastRefresh();
      }
    })();
  }, [commit, patch]);

  const counts = useMemo<OcrCounts>(
    () => ({
      queued: items.filter((i) => i.status === "queued").length,
      reading: items.filter((i) => i.status === "reading").length,
      done: items.filter((i) => i.status === "done").length,
      error: items.filter((i) => i.status === "error").length,
    }),
    [items],
  );

  const value = useMemo<OcrJobsValue>(
    () => ({
      items,
      counts,
      running,
      runTotal,
      finishedAt,
      lastResult,
      stage,
      unstage,
      run,
      clearFinished,
      viewerOpen,
      setViewerOpen,
    }),
    [
      items,
      counts,
      running,
      runTotal,
      finishedAt,
      lastResult,
      stage,
      unstage,
      run,
      clearFinished,
      viewerOpen,
    ],
  );

  return (
    <OcrJobsContext.Provider value={value}>{children}</OcrJobsContext.Provider>
  );
}

export function useOcrJobs(): OcrJobsValue {
  const ctx = useContext(OcrJobsContext);
  if (!ctx) throw new Error("useOcrJobs must be used inside <OcrJobsProvider>");
  return ctx;
}
