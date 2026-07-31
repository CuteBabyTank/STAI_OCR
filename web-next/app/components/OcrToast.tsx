"use client";
// Corner progress toast for background OCR runs (see lib/ocrJobs.tsx).
//
// It sits in the bottom-right above the chat launcher, which is the point: the
// Add-receipts modal can be closed the moment a read starts, and this is what
// keeps reporting. A spinner while the model reads, a check mark when the
// receipts are filed.
//
// Lives in AppShell, not on a page, so it survives route changes for the whole
// minute-or-two a read takes.
import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useOcrJobs } from "../lib/ocrJobs";

// How long the finished state lingers before it retires itself. Long enough to
// notice on a page you were already reading, short enough not to become furniture.
const DONE_LINGER_MS = 9000;
// Slightly longer than the CSS fade (.22s), so acknowledging a run never rewrites
// the toast's own text while it is still visible — clearing the result mid-fade
// showed "0 receipts filed" on the way out.
const FADE_MS = 300;

export default function OcrToast({ aside = false }: { aside?: boolean }) {
  const {
    counts,
    running,
    runTotal,
    finishedAt,
    lastResult,
    clearFinished,
    viewerOpen,
  } = useOcrJobs();
  const [dismissed, setDismissed] = useState(false);

  const fadeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Fade out, then acknowledge the run once the toast is no longer on screen.
  // Acknowledging drops the run's rows — otherwise the next Add receipts open
  // would still be showing the previous upload's results. The exception is when
  // that modal is already open: the user is looking at those rows, so leave them
  // and let the modal's own close acknowledge them.
  const retire = useCallback(() => {
    setDismissed(true);
    if (fadeTimer.current) clearTimeout(fadeTimer.current);
    fadeTimer.current = setTimeout(() => {
      if (!viewerOpen) clearFinished();
    }, FADE_MS);
  }, [viewerOpen, clearFinished]);

  useEffect(
    () => () => {
      if (fadeTimer.current) clearTimeout(fadeTimer.current);
    },
    [],
  );

  // A new run makes the toast relevant again, whatever the user did with the last one.
  useEffect(() => {
    if (running) {
      if (fadeTimer.current) clearTimeout(fadeTimer.current);
      setDismissed(false);
    }
  }, [running]);

  // Retire the finished state on its own after the linger window.
  useEffect(() => {
    if (!finishedAt || running) return;
    const t = setTimeout(retire, DONE_LINGER_MS);
    return () => clearTimeout(t);
  }, [finishedAt, running, retire]);

  const finished = !running && finishedAt !== null && lastResult !== null;
  // Kept mounted through the fade-out so the transition can actually run.
  const show = !dismissed && (running || finished);
  const filed = lastResult?.filed ?? 0;
  const failed = lastResult?.failed ?? 0;
  // Files still being read, out of the run's own total — `counts` can also hold
  // rows from an earlier run the user hasn't dismissed yet.
  const settled = Math.max(0, runTotal - counts.reading);
  // A check mark has to mean something was filed. If every page failed, say that
  // instead — a green tick over a total failure is worse than no toast at all.
  const allFailed = finished && filed === 0 && failed > 0;

  const title = running
    ? `Reading ${counts.reading} receipt${counts.reading === 1 ? "" : "s"}…`
    : allFailed
      ? `Couldn't read ${failed} receipt${failed === 1 ? "" : "s"}`
      : `${filed} receipt${filed === 1 ? "" : "s"} filed`;

  const sub = running
    ? "The model takes a minute or two per page. You can close the upload window."
    : allFailed
      ? "Open Add receipts to see why and try again."
      : failed > 0
        ? `${failed} couldn't be read`
        : "Added to your ledger";

  return (
    <div
      className={
        "ocr-toast" +
        (show ? " show" : "") +
        (aside ? " aside" : "") +
        (finished ? (allFailed ? " failed" : " done") : "")
      }
      role="status"
      aria-live="polite"
      // Hidden from assistive tech while faded out. The CSS pairs this with
      // visibility:hidden so a retired toast can't be tabbed into either.
      aria-hidden={!show}
    >
      <span className="ocr-toast-icon" aria-hidden="true">
        {running ? (
          <span className="ocr-spinner" />
        ) : allFailed ? (
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
            <path d="M12 8v5M12 16.5v.5" strokeWidth="2.2" strokeLinecap="round" />
            <circle cx="12" cy="12" r="9" strokeWidth="2" />
          </svg>
        ) : (
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
            <path
              className="ocr-check"
              d="M5 13l4.5 4.5L19 7.5"
              strokeWidth="2.6"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        )}
      </span>

      <div className="ocr-toast-text">
        <div className="ocr-toast-title">{title}</div>
        <div className="ocr-toast-sub">
          {sub}
          {running && runTotal > 1 && (
            <>
              {" · "}
              {settled}/{runTotal}
            </>
          )}
        </div>
      </div>

      {finished && !allFailed && (
        <Link className="ocr-toast-link" href="/receipts" onClick={retire}>
          View
        </Link>
      )}

      <button
        className="ocr-toast-x"
        // A run still in flight keeps its rows either way (clearFinished is a
        // no-op then) — dismissing only hides the toast, the read continues.
        onClick={retire}
        aria-label={running ? "Hide progress" : "Dismiss"}
        title={running ? "Hide (the read keeps going)" : "Dismiss"}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
          <path d="M18 6 6 18M6 6l12 12" strokeWidth="2" strokeLinecap="round" />
        </svg>
      </button>
    </div>
  );
}
