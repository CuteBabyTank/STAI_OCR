"use client";
// The one camera implementation in the app. Both the Receipts "Add receipts"
// modal and the /scan slide-over mount <CameraButton>, so a fix to focus, torch
// or the phone fallback lands in both places at once.
//
// Two capture paths, picked at click time — the choice has to be synchronous
// because the fallback opens a file input, and a file input can only be opened
// from inside a real user gesture:
//
//   1. Live preview (getUserMedia). Needs a SECURE CONTEXT — https, or localhost.
//      A phone hitting the dev server over the LAN (http://192.168.x.x:3000) is
//      NOT a secure context, so navigator.mediaDevices is undefined there. This
//      is the single most common reason "the camera doesn't work on my phone".
//   2. The phone's own camera app, via <input type="file" capture="environment">.
//      No permissions prompt of our own, works over plain http, and on iOS and
//      Android it opens the rear camera straight into the shutter. This is the
//      fallback for (1), and the manual escape hatch when a live stream is denied.
//
// `capture` is a hint, not a guarantee: desktop browsers ignore it and show a
// file picker, which is exactly the right behaviour there.
import { useCallback, useEffect, useRef, useState } from "react";

/** Live preview is only possible in a secure context with a getUserMedia impl. */
export function supportsLiveCamera(): boolean {
  if (typeof window === "undefined") return false;
  return !!(window.isSecureContext && navigator.mediaDevices?.getUserMedia);
}

type Facing = "environment" | "user";

/**
 * Trigger that opens whichever capture path this device supports and hands the
 * resulting File(s) back. Renders the hidden native input itself so the fallback
 * is always one synchronous click away.
 */
export function CameraButton({
  onFiles,
  className = "btn-ghost",
  label = "Use camera",
  style,
}: {
  onFiles: (files: File[]) => void;
  className?: string;
  label?: string;
  style?: React.CSSProperties;
}) {
  const [live, setLive] = useState(false);
  const nativeRef = useRef<HTMLInputElement>(null);

  const openNative = useCallback(() => nativeRef.current?.click(), []);

  return (
    <>
      <button
        type="button"
        className={className}
        style={style}
        onClick={(e) => {
          // Stop the click reaching a parent dropzone, which would open the
          // plain file picker on top of the camera.
          e.stopPropagation();
          if (supportsLiveCamera()) setLive(true);
          else openNative();
        }}
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" width="18" height="18" aria-hidden="true">
          <path
            d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <circle cx="12" cy="13" r="4" />
        </svg>
        {label}
      </button>

      {/* `capture="environment"` asks for the REAR camera — the one pointed at the
          receipt. Without it the phone opens the gallery or the selfie camera. */}
      <input
        ref={nativeRef}
        type="file"
        accept="image/*"
        capture="environment"
        style={{ display: "none" }}
        onChange={(e) => {
          const files = e.target.files ? Array.from(e.target.files) : [];
          // Reset so re-shooting the same filename still fires onChange.
          e.currentTarget.value = "";
          if (files.length) onFiles(files);
        }}
      />

      {live && (
        <CameraOverlay
          onFiles={onFiles}
          onClose={() => setLive(false)}
          onFallback={() => {
            setLive(false);
            openNative();
          }}
        />
      )}
    </>
  );
}

/**
 * Full-screen live viewfinder. Fills the screen on a phone and sits as a large
 * centred sheet on a desktop; the controls are anchored to the bottom inside the
 * safe area so the shutter is always reachable with a thumb.
 */
function CameraOverlay({
  onFiles,
  onClose,
  onFallback,
}: {
  onFiles: (files: File[]) => void;
  onClose: () => void;
  onFallback: () => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [facing, setFacing] = useState<Facing>("environment");
  const [canFlip, setCanFlip] = useState(false);
  const [torch, setTorch] = useState(false);
  const [canTorch, setCanTorch] = useState(false);
  const [shots, setShots] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  const stop = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }, []);

  // (Re)open the stream whenever the requested camera changes.
  useEffect(() => {
    let cancelled = false;
    setReady(false);
    setErr(null);

    (async () => {
      stop();
      try {
        // `ideal` rather than `exact`: a laptop has no "environment" camera, and
        // an exact constraint would fail outright there instead of falling back
        // to the only camera present.
        const stream = await navigator.mediaDevices.getUserMedia({
          video: {
            facingMode: { ideal: facing },
            width: { ideal: 1920 },
            height: { ideal: 1080 },
          },
          audio: false,
        });
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;

        const track = stream.getVideoTracks()[0];
        // Torch is a real help photographing a receipt on a restaurant table, but
        // it only exists on some Android/Chrome builds — feature-detect, never assume.
        const caps: any = track?.getCapabilities?.() ?? {};
        setCanTorch(!!caps.torch);
        setTorch(false);

        // Only offer the flip control when there is genuinely more than one camera.
        // Labels are empty until permission is granted, which is why this runs after.
        try {
          const devices = await navigator.mediaDevices.enumerateDevices();
          if (!cancelled) setCanFlip(devices.filter((d) => d.kind === "videoinput").length > 1);
        } catch {
          /* enumerateDevices can reject in locked-down contexts; the flip button
             is a nicety, so a failure here should not break capture. */
        }

        const v = videoRef.current;
        if (v) {
          v.srcObject = stream;
          // iOS will not autoplay without muted + playsInline, both set on the element.
          await v.play().catch(() => {});
          if (!cancelled) setReady(true);
        }
      } catch (e: any) {
        if (cancelled) return;
        setErr(
          e?.name === "NotAllowedError"
            ? "Camera permission was denied. Allow it in your browser settings, or use your phone's camera app."
            : e?.name === "NotFoundError"
              ? "No camera found on this device."
              : "Couldn't start the camera here."
        );
      }
    })();

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [facing]);

  // Release the hardware on unmount — a stream left running keeps the phone's
  // camera indicator lit and blocks other apps.
  useEffect(() => () => stop(), [stop]);

  // Escape closes, and the page behind must not scroll under the viewfinder.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const close = () => {
    stop();
    onClose();
  };

  const toggleTorch = async () => {
    const track = streamRef.current?.getVideoTracks()[0];
    if (!track) return;
    const next = !torch;
    try {
      await track.applyConstraints({ advanced: [{ torch: next }] } as any);
      setTorch(next);
    } catch {
      setCanTorch(false);
    }
  };

  const snap = () => {
    const v = videoRef.current;
    if (!v || !v.videoWidth) return;
    const canvas = document.createElement("canvas");
    // Capture at the sensor's real resolution, not the on-screen size — the
    // preview is letterboxed to fit a phone screen and OCR needs every pixel.
    canvas.width = v.videoWidth;
    canvas.height = v.videoHeight;
    canvas.getContext("2d")?.drawImage(v, 0, 0);
    canvas.toBlob(
      (blob) => {
        if (!blob) return;
        const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
        const n = shots + 1;
        onFiles([new File([blob], `camera-${ts}-${n}.jpg`, { type: "image/jpeg" })]);
        setShots(n);
      },
      "image/jpeg",
      0.92
    );
  };

  return (
    <div className="cam" role="dialog" aria-modal="true" aria-label="Camera">
      <div className="cam-stage">
        <video ref={videoRef} className="cam-video" autoPlay playsInline muted />
        {/* A receipt is a tall rectangle; the frame tells you how to hold the phone
            before the read comes back blurry and cropped. */}
        {ready && <div className="cam-frame" aria-hidden="true" />}
        {!ready && !err && <div className="cam-status">Starting camera…</div>}

        <div className="cam-top">
          <button type="button" className="cam-icon" onClick={close} aria-label="Close camera">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path d="M18 6 6 18M6 6l12 12" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </button>
          <div className="cam-top-right">
            {canTorch && (
              <button
                type="button"
                className={"cam-icon" + (torch ? " on" : "")}
                onClick={toggleTorch}
                aria-label="Toggle flashlight"
                aria-pressed={torch}
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                  <path d="M13 2 4 14h7l-1 8 9-12h-7z" strokeWidth="1.9" strokeLinejoin="round" />
                </svg>
              </button>
            )}
            {canFlip && (
              <button
                type="button"
                className="cam-icon"
                onClick={() => setFacing((f) => (f === "environment" ? "user" : "environment"))}
                aria-label="Switch camera"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                  <path
                    d="M20 8a8 8 0 0 0-14-3M4 16a8 8 0 0 0 14 3M4 5v5h5M20 19v-5h-5"
                    strokeWidth="1.9"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </button>
            )}
          </div>
        </div>

        {err && (
          <div className="cam-err">
            <p>{err}</p>
            <button type="button" className="btn-primary" onClick={onFallback}>
              Use phone camera app
            </button>
            <button type="button" className="cam-text-btn" onClick={close}>
              Cancel
            </button>
          </div>
        )}
      </div>

      {!err && (
        <div className="cam-controls">
          {/* Shooting several receipts in a row is the normal case, so a capture
              stages the shot and keeps the viewfinder up rather than closing it. */}
          <span className="cam-count">{shots > 0 ? `${shots} captured` : "Fill the frame with the receipt"}</span>
          <div className="cam-controls-row">
            <button type="button" className="cam-text-btn" onClick={close}>
              {shots > 0 ? "Done" : "Cancel"}
            </button>
            <button
              type="button"
              className="cam-shutter"
              onClick={snap}
              disabled={!ready}
              aria-label="Capture photo"
            />
            <button type="button" className="cam-text-btn" onClick={onFallback}>
              Camera app
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
