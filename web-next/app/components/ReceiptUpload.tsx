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
import { useEffect, useRef, useState } from "react";
import { money } from "../lib/format";
import { Modal, Button } from "./ui";

type BatchItem = {
  // Stable id, not the array index: files can be staged while an earlier read is
  // still running, so rows shift and positional writes would clobber each other.
  key: number;
  name: string;
  status: "queued" | "reading" | "done" | "error";
  id?: number;
  merchant?: string;
  amount?: number;
  currency?: string;
  error?: string;
};

const CLIENT_CHUNK = 12;

export default function ReceiptUpload({
  onClose,
  onDone,
}: {
  onClose: () => void;
  onDone: () => void;
}) {
  const [batch, setBatch] = useState<BatchItem[]>([]);
  const [dragging, setDragging] = useState(false);
  const [camera, setCamera] = useState(false);
  const [camErr, setCamErr] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const seqRef = useRef(0);
  // Staged files, keyed by row. Kept in a ref (not state) because a File is inert
  // data the render never reads — only the run needs it.
  const stagedRef = useRef(new Map<number, File>());

  const patch = (key: number, item: BatchItem) =>
    setBatch((prev) => prev.map((b) => (b.key === key ? item : b)));

  // --- Step 1: stage files. No network call, no model, nothing written. ------
  const stageFiles = (files: File[]) => {
    if (!files.length) return;
    const rows = files.map((f) => {
      const key = (seqRef.current += 1);
      stagedRef.current.set(key, f);
      return { key, name: f.name, status: "queued" as const };
    });
    setBatch((prev) => [...prev, ...rows]);
  };

  const unstage = (key: number) => {
    stagedRef.current.delete(key);
    setBatch((prev) => prev.filter((b) => b.key !== key));
  };

  // --- Step 2: read the staged files, on an explicit press ------------------
  // Chunked, one chunk at a time, so a big drop never oversubscribes the model.
  const runOcr = async () => {
    const queued = batch
      .filter((b) => b.status === "queued")
      .map((b) => ({ key: b.key, file: stagedRef.current.get(b.key)! }))
      .filter((q) => q.file);
    if (!queued.length) return;

    queued.forEach(({ key, file }) =>
      patch(key, { key, name: file.name, status: "reading" }),
    );
    let ok = 0;

    for (let start = 0; start < queued.length; start += CLIENT_CHUNK) {
      const chunk = queued.slice(start, start + CLIENT_CHUNK);
      const fd = new FormData();
      chunk.forEach(({ file }) => fd.append("files", file));
      try {
        const res = await fetch("/api/extract/batch", { method: "POST", body: fd });
        const rawText = await res.text();
        let j: any = {};
        try { j = rawText ? JSON.parse(rawText) : {}; } catch { /* non-JSON */ }
        if (!res.ok) {
          throw new Error(
            j.detail ||
              (res.status >= 500
                ? "The model couldn't read these receipts (it may be busy). Try again in a moment."
                : rawText.slice(0, 160) || res.statusText)
          );
        }
        const results: any[] = j.results || [];
        chunk.forEach(({ key, file: f }) => {
          const mine = results.filter((r) => r.source_file === f.name);
          const good = mine.filter((r) => !r.error && r.receipt_id);
          good.forEach(() => (ok += 1));
          if (good.length === 0) {
            patch(key, { key, name: f.name, status: "error", error: mine[0]?.error || "Failed to read" });
          } else {
            const first = good[0].data || {};
            const pages = mine.length;
            patch(key, {
              key,
              name: pages > 1 ? `${f.name} · ${good.length}/${pages} pages` : f.name,
              status: "done",
              id: good[0].receipt_id,
              merchant: first.vendor_name || f.name,
              amount: pages > 1
                ? good.reduce((s, r) => s + (r.data?.total_amount || 0), 0)
                : (first.total_amount ?? 0),
              currency: first.currency,
            });
          }
        });
      } catch (e: any) {
        chunk.forEach(({ key, file: f }) =>
          patch(key, { key, name: f.name, status: "error", error: e?.message || "Failed to read" })
        );
      }
    }
    // Read attempts are spent — don't let a retry silently re-send them.
    queued.forEach(({ key }) => stagedRef.current.delete(key));
    if (ok) onDone();
  };

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

  const done = batch.filter((b) => b.status === "done").length;
  const reading = batch.filter((b) => b.status === "reading").length;
  const queued = batch.filter((b) => b.status === "queued").length;

  return (
    <Modal
      title="Add receipts"
      wide
      onClose={() => { stopCamera(); onClose(); }}
      footer={
        <>
          <Button onClick={() => { stopCamera(); onClose(); }}>{done ? "Done" : "Close"}</Button>
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
                disabled={!queued || reading > 0}
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
              ? `Reading ${reading} of ${batch.length}… the vision model can take a minute or two per receipt.`
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
