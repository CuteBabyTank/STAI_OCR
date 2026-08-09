"use client";
// Add-receipts flow: drag/drop or pick image/PDF files, OR capture a photo with
// the device camera, then run them through the batch OCR endpoint. Reused by the
// combined Receipts page. Camera capture lives in components/CameraCapture.tsx
// and is shared with the /scan slide-over — it uses a live getUserMedia preview
// where the browser allows one and hands off to the phone's own camera app
// otherwise (notably over plain http on a LAN address, where getUserMedia is
// unavailable by spec).
//
// Uploading and reading are two SEPARATE steps. Picking files only stages them;
// nothing hits the vision model until "Run OCR" is pressed. A read costs a minute
// or two per page and writes a receipt to the ledger, so firing it off the moment
// a file lands means a mis-drop is an expensive, already-committed mistake.
//
// The staging list and the run itself live in lib/ocrJobs.tsx, above this modal in
// the tree — so pressing Run OCR and immediately closing this window no longer
// abandons the read. This component is now just the view over that store: the
// corner toast (components/OcrToast.tsx) reports the same run once the modal is
// gone, and reopening the modal shows the run still in progress.
import { useEffect, useRef, useState } from "react";
import { money } from "../lib/format";
import { useOcrJobs } from "../lib/ocrJobs";
import { Modal, Button } from "./ui";
import { CameraButton } from "./CameraCapture";

export default function ReceiptUpload({ onClose }: { onClose: () => void }) {
  const {
    items: batch,
    counts,
    running,
    stage: stageFiles,
    unstage,
    run: runOcr,
    clearFinished,
    setViewerOpen,
  } = useOcrJobs();
  const [dragging, setDragging] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const onFiles = (fl: FileList | null) => fl && stageFiles(Array.from(fl));

  // Tell the store this view is on screen, so the toast doesn't clear rows the
  // user is currently reading when it retires itself.
  useEffect(() => {
    setViewerOpen(true);
    return () => setViewerOpen(false);
  }, [setViewerOpen]);

  // Closing the window is the user acknowledging a finished run: its rows go away
  // so the next open starts clean, and the corner toast stops reporting it. A run
  // still in flight is untouched (clearFinished is a no-op then) — the whole point
  // is that closing does not cancel it.
  const closeModal = () => {
    clearFinished();
    onClose();
  };

  const { done, reading, queued } = counts;

  return (
    <Modal
      title="Add receipts"
      wide
      onClose={closeModal}
      footer={
        <>
          {/* Closing mid-read is now a supported move, not an abandonment: the run
              belongs to the store and the corner toast takes over reporting it. */}
          <Button onClick={closeModal}>
            {reading > 0 ? "Close — keep reading" : done ? "Done" : "Close"}
          </Button>
          {/* Two distinct actions: stage files, then read them. Neither button
              ever becomes a status label — progress lives on the rows below, so
              the modal can't look stuck and more files can be staged mid-read. */}
          <Button onClick={() => fileRef.current?.click()}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" width="16" height="16" aria-hidden="true">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            Upload
          </Button>
          <Button
            variant="primary"
            onClick={runOcr}
            disabled={!queued || running}
            title={queued ? `Read ${queued} staged file${queued > 1 ? "s" : ""}` : "Upload a receipt first"}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" width="16" height="16" aria-hidden="true">
              <path d="M4 7V5a1 1 0 0 1 1-1h2M20 7V5a1 1 0 0 0-1-1h-2M4 17v2a1 1 0 0 0 1 1h2M20 17v2a1 1 0 0 1-1 1h-2M3 12h18" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            {queued ? `Run OCR (${queued})` : "Run OCR"}
          </Button>
        </>
      }
    >
      <input
        ref={fileRef}
        type="file"
        accept="image/*,application/pdf"
        multiple
        style={{ display: "none" }}
        onChange={(e) => { onFiles(e.target.files); e.currentTarget.value = ""; }}
      />

      <div
        className={"rcpt-drop" + (dragging ? " over" : "")}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); onFiles(e.dataTransfer.files); }}
        onClick={() => fileRef.current?.click()}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
          <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        <div className="rcpt-drop-title">Drop receipts here, or tap to browse</div>
        <div className="rcpt-drop-sub">Images or PDFs · nothing is read until you press Run OCR</div>
        {/* Captured shots stage exactly like dropped files, so the camera can stay
            open for several receipts and the rows below fill in as they arrive. */}
        <CameraButton onFiles={stageFiles} style={{ marginTop: 14 }} />
      </div>

      {batch.length > 0 && (
        <>
          {/* The progress the button used to carry. Vision reads are slow
              (~1-2 min per page), so say so rather than leaving a silent spinner. */}
          <div className="rcpt-progress">
            {reading > 0
              ? `Reading ${reading} of ${batch.length}… a minute or two per receipt. You can close this window — it keeps going, and the corner badge will tell you when it's done.`
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
                {/* Staged files are removable — with no auto-read, a mis-drop
                    should be undoable instead of costing a model run. */}
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
      )}
    </Modal>
  );
}
