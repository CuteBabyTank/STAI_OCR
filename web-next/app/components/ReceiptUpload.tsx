"use client";
// Add-receipts flow: drag/drop or pick image/PDF files, OR capture a photo with
// the device camera, then run them through the batch OCR endpoint. Reused by the
// combined Receipts page. Camera uses getUserMedia (live preview + snapshot) with
// a graceful fallback message when no camera / permission is unavailable.
import { useEffect, useRef, useState } from "react";
import { money } from "../lib/format";
import { Modal, Button } from "./ui";

type BatchItem = {
  name: string;
  status: "reading" | "done" | "error";
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
  const [busy, setBusy] = useState(false);
  const [camera, setCamera] = useState(false);
  const [camErr, setCamErr] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);

  // --- Batch OCR upload (chunked, one chunk at a time) --------------------
  const processFiles = async (files: File[]) => {
    if (!files.length) return;
    setBusy(true);
    const base = batch.length;
    setBatch((prev) => [...prev, ...files.map((f) => ({ name: f.name, status: "reading" as const }))]);
    let ok = 0;

    for (let start = 0; start < files.length; start += CLIENT_CHUNK) {
      const chunk = files.slice(start, start + CLIENT_CHUNK);
      const fd = new FormData();
      chunk.forEach((f) => fd.append("files", f));
      try {
        const res = await fetch("/api/extract/batch", { method: "POST", body: fd });
        const rawText = await res.text();
        let j: any = {};
        try { j = rawText ? JSON.parse(rawText) : {}; } catch { /* non-JSON */ }
        if (!res.ok) {
          throw new Error(
            j.detail ||
              (res.status >= 500
                ? "The model took too long to read these receipts (it may be busy). Try again in a moment."
                : rawText.slice(0, 160) || res.statusText)
          );
        }
        const results: any[] = j.results || [];
        chunk.forEach((f, ci) => {
          const idx = base + start + ci;
          const mine = results.filter((r) => r.source_file === f.name);
          const good = mine.filter((r) => !r.error && r.receipt_id);
          good.forEach(() => (ok += 1));
          setBatch((prev) => {
            const next = [...prev];
            if (good.length === 0) {
              next[idx] = { name: f.name, status: "error", error: mine[0]?.error || "Failed to read" };
            } else {
              const first = good[0].data || {};
              const pages = mine.length;
              next[idx] = {
                name: pages > 1 ? `${f.name} · ${good.length}/${pages} pages` : f.name,
                status: "done",
                id: good[0].receipt_id,
                merchant: first.vendor_name || f.name,
                amount: pages > 1
                  ? good.reduce((s, r) => s + (r.data?.total_amount || 0), 0)
                  : (first.total_amount ?? 0),
                currency: first.currency,
              };
            }
            return next;
          });
        });
      } catch (e: any) {
        chunk.forEach((f, ci) => {
          const idx = base + start + ci;
          setBatch((prev) => {
            const next = [...prev];
            next[idx] = { name: f.name, status: "error", error: e?.message || "Failed to read" };
            return next;
          });
        });
      }
    }
    setBusy(false);
    if (ok) onDone();
  };

  const onFiles = (fl: FileList | null) => fl && processFiles(Array.from(fl));

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
      processFiles([file]);
    }, "image/jpeg", 0.92);
  };

  // Always release the camera when the modal unmounts.
  useEffect(() => () => stopCamera(), []);

  const done = batch.filter((b) => b.status === "done").length;

  return (
    <Modal
      title="Add receipts"
      wide
      onClose={() => { stopCamera(); onClose(); }}
      footer={
        <>
          <Button onClick={() => { stopCamera(); onClose(); }}>{done ? "Done" : "Close"}</Button>
          {!camera && (
            <Button variant="primary" onClick={() => fileRef.current?.click()} disabled={busy}>
              {busy ? "Reading…" : "Choose files"}
            </Button>
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
          <div className="rcpt-drop-sub">Images or PDFs · multiple at once</div>
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
        <div className="rcpt-batch">
          {batch.map((b, i) => (
            <div key={i} className={"rcpt-item " + b.status}>
              <span className="rcpt-dot" />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div className="rcpt-item-name">{b.merchant || b.name}</div>
                {b.status === "error" && <div className="rcpt-item-err">{b.error}</div>}
              </div>
              <span className="rcpt-item-amt">
                {b.status === "reading" ? "Reading…" : b.status === "done" ? money(b.amount, b.currency) : "Failed"}
              </span>
            </div>
          ))}
        </div>
      )}
    </Modal>
  );
}
