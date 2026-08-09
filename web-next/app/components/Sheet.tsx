"use client";
// Bottom sheet with iOS-style drag dismissal. The phone presentation of every
// budget-tracker dialog (see ui.tsx) and of the tab bar's More menu.
//
// There is no `open` prop, and that is deliberate. Every caller in this app
// closes a dialog by unmounting it, so an AnimatePresence exit would never get
// to play. Instead the sheet animates itself out on dismissal and calls
// onClose when that finishes — without it, a sheet you dragged halfway down
// would blink out of existence the instant you let go.
//
// Drag is started from the grab handle only, via dragControls. A sheet whose
// whole surface is draggable needs touch-action:none on the panel, which kills
// scrolling inside .sheet-body — and these hold forms taller than the screen.
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { motion, useDragControls, useMotionValue, useReducedMotion, useTransform } from "framer-motion";

// Far enough off-screen that the panel is fully clear at rest, whatever its
// height. Clipped by the viewport, so an over-tall value is invisible.
const OFFSCREEN = 640;
// Distance OR velocity dismisses: requiring the full drag would make a quick
// flick — the way most people actually close a sheet — feel unresponsive.
const DISMISS_DISTANCE = 100;
const DISMISS_VELOCITY = 500;
const SPRING = { type: "spring" as const, stiffness: 420, damping: 40 };

export default function Sheet({
  title,
  onClose,
  children,
  footer,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
}) {
  const reduce = useReducedMotion();
  const dragControls = useDragControls();
  const panelRef = useRef<HTMLDivElement>(null);
  const [leaving, setLeaving] = useState(false);

  // The panel's translation, shared with the scrim so the backdrop lightens as
  // the sheet is pulled down — the drag reads as reversible rather than as a
  // switch that has already flipped.
  const y = useMotionValue(0);
  const scrimOpacity = useTransform(y, [0, OFFSCREEN / 2], [1, 0]);

  useEffect(() => {
    const el = panelRef.current;
    const restoreTo = document.activeElement as HTMLElement | null;
    el?.focus();

    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setLeaving(true);
        return;
      }
      // Keep focus inside: a sheet is modal, and tabbing out to the page
      // underneath leaves a screen-reader user somewhere they cannot see.
      if (e.key !== "Tab" || !el) return;
      const focusable = el.querySelectorAll<HTMLElement>(
        'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])'
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
      restoreTo?.focus();
    };
  }, []);

  return (
    <motion.div
      className="sheet-scrim"
      style={{ opacity: reduce ? undefined : scrimOpacity }}
      initial={{ opacity: 0 }}
      animate={{ opacity: leaving ? 0 : 1 }}
      transition={{ duration: 0.2 }}
      onClick={() => setLeaving(true)}
    >
      <motion.div
        ref={panelRef}
        className="sheet"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        style={{ y }}
        initial={reduce ? { opacity: 0 } : { y: OFFSCREEN }}
        animate={reduce ? { opacity: leaving ? 0 : 1 } : { y: leaving ? OFFSCREEN : 0 }}
        transition={reduce ? { duration: 0.15 } : SPRING}
        onAnimationComplete={() => {
          if (leaving) onClose();
        }}
        drag={reduce ? false : "y"}
        dragListener={false}
        dragControls={dragControls}
        // Pinned at the top so the sheet cannot be thrown up off the screen;
        // elastic only downward, which is the direction that dismisses.
        dragConstraints={{ top: 0, bottom: 0 }}
        dragElastic={{ top: 0, bottom: 0.5 }}
        onDragEnd={(_, info) => {
          if (info.offset.y > DISMISS_DISTANCE || info.velocity.y > DISMISS_VELOCITY) {
            setLeaving(true);
          }
        }}
      >
        <div
          className="sheet-grab-zone"
          onPointerDown={(e) => dragControls.start(e)}
          aria-hidden="true"
        >
          <div className="sheet-grab" />
        </div>
        <div className="sheet-head">
          <h2 className="sheet-title">{title}</h2>
          <button className="sheet-x" onClick={() => setLeaving(true)} aria-label="Close">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path d="M18 6 6 18M6 6l12 12" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </button>
        </div>
        <div className="sheet-body">{children}</div>
        {footer && <div className="sheet-foot">{footer}</div>}
      </motion.div>
    </motion.div>
  );
}
