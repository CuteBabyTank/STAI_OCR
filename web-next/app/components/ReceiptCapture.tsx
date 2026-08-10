"use client";
// The add-a-receipt UI, split out of ReceiptUpload so the modal on Receipts and
// the /add page reached from the phone tab bar's + are the same code rather than
// two copies that drift. Everything here reads and writes the shared run store
// in lib/ocrJobs, so a read started from either surface is the same run — the
// corner toast reports it, and navigating away does not abandon it.
//
// Uploading and reading stay two separate steps, which is the rule the original
// flow was built around: picking files only stages them, and nothing hits the
// vision model until Run OCR is pressed. A read costs a minute or two per page
// and writes to the ledger, so auto-reading a mis-drop is an expensive mistake
// that has already happened by the time you notice.
import { useEffect, useRef, useState } from "react";
import { money } from "../lib/format";
import { useOcrJobs } from "../lib/ocrJobs";
import { Button } from "./ui";
import { CameraButton, liveCameraBlockedReason } from "./CameraCapture";

/**
 * The two ways in — upload, or camera — plus the drop target.
 *
 * They are siblings, never nested. The camera button used to sit inside the
 * dropzone, which is itself a click target, so a tap landing a pixel outside it
 * opened the file picker instead of the camera.
 */
export function CaptureChoices() {
  const { stage } = useOcrJobs();
  const [dragging, setDragging] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  // Why the in-page viewfinder is unavailable, if it is. Resolved after mount
  // because it reads window.isSecureContext, which does not exist on the server.
  const [camHint, setCamHint] = useState<string | null>(null);
  useEffect(() => setCamHint(liveCameraBlockedReason()), []);

  const onFiles = (fl: FileList | null) => fl && stage(Array.from(fl));

  return (
    <>
      {/* Clip-hidden rather than display:none — iOS Safari will not open a
          display:none file input from a programmatic .click(). */}
      <input
        ref={fileRef}
        type="file"
        accept="image/*,application/pdf"
        multiple
        className="visually-hidden-input"
        onChange={(e) => {
          onFiles(e.target.files);
          e.currentTarget.value = "";
        }}
      />

      <div className="rcpt-actions">
        <button type="button" className="rcpt-action" onClick={() => fileRef.current?.click()}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <span className="rcpt-action-label">Upload a photo</span>
          <span className="rcpt-action-sub">Images or PDFs</span>
        </button>

        {/* Captured shots stage exactly like uploaded files, so the camera can
            stay open for several receipts and the rows below fill in as they
            arrive. */}
        <CameraButton
          className="rcpt-action rcpt-action-cam"
          onFiles={stage}
          label={
            <>
              <span className="rcpt-action-label">Use camera</span>
              <span className="rcpt-action-sub">Take a photo now</span>
            </>
          }
        />
      </div>

      {camHint && <p className="rcpt-cam-hint">{camHint}</p>}

      {/* Drop target only — no click handler, so it can never intercept a
          button. Pointless on a phone, but harmless and one less branch. */}
      <div
        className={"rcpt-drop" + (dragging ? " over" : "")}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          onFiles(e.dataTransfer.files);
        }}
      >
        <div className="rcpt-drop-sub">
          …or drop receipts here · nothing is read until you press Run OCR
        </div>
      </div>
    </>
  );
}

/**
 * Staged and in-flight files. Renders nothing when the queue is empty, so both
 * callers can drop it in unconditionally.
 */
export function CaptureQueue() {
  const { items: batch, counts, unstage, setViewerOpen } = useOcrJobs();
  const { done, reading, queued } = counts;

  // Tell the store this view is on screen, so the toast doesn't clear rows the
  // reader is currently looking at when it retires itself.
  useEffect(() => {
    setViewerOpen(true);
    return () => setViewerOpen(false);
  }, [setViewerOpen]);

  if (batch.length === 0) return null;

  return (
    <>
      {/* Vision reads are slow (~1-2 min per page), so say so rather than
          leaving a silent spinner. */}
      <div className="rcpt-progress">
        {reading > 0
          ? `Reading ${reading} of ${batch.length}… a minute or two per receipt. You can leave this page — it keeps going, and the corner badge will tell you when it's done.`
          : queued > 0
            ? `${queued} file${queued > 1 ? "s" : ""} ready — press Run OCR to read ${queued > 1 ? "them" : "it"}.`
            : `${done} of ${batch.length} filed`}
      </div>
      <div className="rcpt-batch">
        {batch.map((b) => (
          <div key={b.key} className={"rcpt-item " + b.status}>
            <span className="rcpt-dot" />
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="rcpt-item-name">{b.merchant || b.name}</div>
              {b.status === "error" && <div className="rcpt-item-err">{b.error}</div>}
            </div>
            <span className="rcpt-item-amt">
              {b.status === "queued"
                ? "Ready"
                : b.status === "reading"
                  ? "Reading…"
                  : b.status === "done"
                    ? money(b.amount, b.currency)
                    : "Failed"}
            </span>
            {/* Staged files are removable — with no auto-read, a mis-drop should
                be undoable instead of costing a model run. */}
            {b.status === "queued" && (
              <button className="rcpt-item-x" title="Remove" onClick={() => unstage(b.key)}>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true">
                  <path d="M18 6 6 18M6 6l12 12" strokeLinecap="round" />
                </svg>
              </button>
            )}
          </div>
        ))}
      </div>
    </>
  );
}

/** Reads the store itself, so neither caller has to thread the counts through. */
export function RunOcrButton() {
  const { counts, running, run } = useOcrJobs();
  const { queued } = counts;
  return (
    <Button
      variant="primary"
      onClick={run}
      disabled={!queued || running}
      title={queued ? `Read ${queued} staged file${queued > 1 ? "s" : ""}` : "Upload a receipt first"}
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" width="16" height="16" aria-hidden="true">
        <path d="M4 7V5a1 1 0 0 1 1-1h2M20 7V5a1 1 0 0 0-1-1h-2M4 17v2a1 1 0 0 0 1 1h2M20 17v2a1 1 0 0 1-1 1h-2M3 12h18" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      {queued ? `Run OCR (${queued})` : "Run OCR"}
    </Button>
  );
}
