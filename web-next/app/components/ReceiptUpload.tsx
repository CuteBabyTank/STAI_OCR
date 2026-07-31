"use client";
// Add-receipts flow: drag/drop or pick image/PDF files, OR capture a photo with
// the device camera, then run them through the batch OCR endpoint. Reused by the
// combined Receipts page. Camera uses getUserMedia (live preview + snapshot) with
// a graceful fallback message when no camera / permission is unavailable.
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
  const [camera, setCamera] = useState(false);
  const [camErr, setCamErr] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const onFiles = (fl: FileList | null) => fl && stageFiles(Array.from(fl));

  // --- Camera capture ------------------------------------------------------
  const openCamera = async () => {
    setCamErr(null);
    if (!navigator.mediaDevices?.getUserMedia) {
      setCamErr("This browser can't access a camera. Use file upload instead.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "environment", width: { ideal: 1920 }, height: { ideal: 1080 } },
        audio: false,
      });
      streamRef.current = stream;
      setCamera(true);
      // Attach after the <video> mounts.
      requestAnimationFrame(() => {
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          videoRef.current.play().catch(() => {});
        }
      });
    } catch (e: any) {
      setCamErr(
        e?.name === "NotAllowedError"
          ? "Camera permission denied. Allow access or use file upload."
          : "Couldn't open the camera. Use file upload instead."
      );
    }
  };

  const stopCamera = () => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    setCamera(false);
  };

  const snap = () => {
    const v = videoRef.current;
    if (!v || !v.videoWidth) return;
    const canvas = document.createElement("canvas");
    canvas.width = v.videoWidth;
    canvas.height = v.videoHeight;
    canvas.getContext("2d")?.drawImage(v, 0, 0);
    canvas.toBlob((blob) => {
      if (!blob) return;
      const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
      const file = new File([blob], `camera-${ts}.jpg`, { type: "image/jpeg" });
      stopCamera();
      stageFiles([file]);
    }, "image/jpeg", 0.92);
  };

  // Always release the camera when the modal unmounts.
  useEffect(() => () => stopCamera(), []);

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
    stopCamera();
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
          {!camera && (
            <>
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
          )}
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

      {camera ? (
        <div className="rcpt-cam">
          <video ref={videoRef} playsInline muted />
          <div className="rcpt-cam-actions">
            <Button onClick={stopCamera}>Cancel</Button>
            <Button variant="primary" onClick={snap}>Capture</Button>
          </div>
        </div>
      ) : (
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
          <div className="rcpt-drop-title">Drop receipts here, or click to browse</div>
          <div className="rcpt-drop-sub">Images or PDFs · nothing is read until you press Run OCR</div>
          <button
            className="btn-ghost"
            style={{ marginTop: 14 }}
            onClick={(e) => { e.stopPropagation(); openCamera(); }}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" width="18" height="18">
              <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z" strokeLinecap="round" strokeLinejoin="round" />
              <circle cx="12" cy="13" r="4" />
            </svg>
            Use camera
          </button>
        </div>
      )}

      {camErr && <div className="form-error">{camErr}</div>}

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
