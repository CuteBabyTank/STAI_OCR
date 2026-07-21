"use client";
// Small, dependency-free UI primitives shared across the budget-tracker screens:
// a modal shell, form fields, a select, a segmented control, and buttons. Styling
// lives in globals.css (.modal-*, .field, .seg, etc.) to match the existing cards.
import {
  Children,
  isValidElement,
  ReactNode,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";

// --------------------------------------------------------------------------- //
// Modal
// --------------------------------------------------------------------------- //
export function Modal({
  title,
  onClose,
  children,
  footer,
  wide,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}) {
  // Close on Escape; lock background scroll while open.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [onClose]);

  // Backdrop close only when BOTH the press and release land on the scrim itself.
  // Guards against: the opening click flashing the modal shut, a text-selection
  // drag ending on the backdrop, and clicks inside the modal bubbling out.
  const pressedOnScrim = useRef(false);

  return (
    <div
      className="bt-scrim"
      onMouseDown={(e) => {
        pressedOnScrim.current = e.target === e.currentTarget;
      }}
      onMouseUp={(e) => {
        if (pressedOnScrim.current && e.target === e.currentTarget) onClose();
        pressedOnScrim.current = false;
      }}
    >
      <div
        className={"bt-modal" + (wide ? " bt-modal-wide" : "")}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="bt-modal-head">
          <h2 className="bt-modal-title">{title}</h2>
          <button className="bt-modal-x" onClick={onClose} aria-label="Close">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path d="M18 6 6 18M6 6l12 12" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </button>
        </div>
        <div className="bt-modal-body">{children}</div>
        {footer && <div className="bt-modal-foot">{footer}</div>}
      </div>
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Form fields
// --------------------------------------------------------------------------- //
export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: ReactNode;
  children: ReactNode;
}) {
  return (
    <label className="field">
      <span className="field-label">
        {label}
        {hint != null && <span className="field-hint">{hint}</span>}
      </span>
      {children}
    </label>
  );
}

export function TextInput(
  props: React.InputHTMLAttributes<HTMLInputElement>
) {
  return <input {...props} className={"input " + (props.className || "")} />;
}

// Custom dropdown that replaces the native <select> while keeping the exact same
// API: pass <option> children and an onChange that reads `e.target.value`. It
// parses those options, renders a styled trigger + a portal-mounted popup (so it
// never clips inside a scrolling modal), and synthesizes a native-shaped change
// event so existing call sites need no changes. Fully keyboard accessible.
type Opt = { value: string; label: ReactNode; disabled: boolean };

export function Select({
  value,
  onChange,
  children,
  disabled,
  id,
  name,
}: React.SelectHTMLAttributes<HTMLSelectElement>) {
  const opts: Opt[] = [];
  Children.forEach(children, (child) => {
    if (!isValidElement(child)) return;
    const p: any = child.props;
    // Match native <option>: when no explicit `value`, its text content is the value.
    const v = p.value ?? (typeof p.children === "string" ? p.children : "");
    opts.push({ value: String(v), label: p.children ?? String(v), disabled: !!p.disabled });
  });

  const selected = opts.find((o) => o.value === String(value ?? ""));
  const [open, setOpen] = useState(false);
  const [hl, setHl] = useState(0); // highlighted index while open
  const [pos, setPos] = useState<{ left: number; width: number; top?: number; bottom?: number; maxH: number } | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const popRef = useRef<HTMLDivElement>(null);

  const place = () => {
    const el = triggerRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const spaceBelow = window.innerHeight - r.bottom;
    const openUp = spaceBelow < 240 && r.top > spaceBelow;
    setPos({
      left: r.left,
      width: r.width,
      ...(openUp ? { bottom: window.innerHeight - r.top + 4 } : { top: r.bottom + 4 }),
      maxH: (openUp ? r.top : spaceBelow) - 16,
    });
  };

  useLayoutEffect(() => {
    if (!open) return;
    place();
    setHl(Math.max(0, opts.findIndex((o) => o.value === String(value ?? ""))));
    const onScrollOrResize = () => place();
    window.addEventListener("scroll", onScrollOrResize, true);
    window.addEventListener("resize", onScrollOrResize);
    return () => {
      window.removeEventListener("scroll", onScrollOrResize, true);
      window.removeEventListener("resize", onScrollOrResize);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // Close on outside click / Escape.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!popRef.current?.contains(e.target as Node) && !triggerRef.current?.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown, true);
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("mousedown", onDown, true);
      document.removeEventListener("keydown", onKey, true);
    };
  }, [open]);

  const commit = (o: Opt) => {
    if (o.disabled) return;
    // Synthesize the native-shaped event so `onChange={(e)=>...e.target.value}` works.
    onChange?.({ target: { value: o.value, name } } as unknown as React.ChangeEvent<HTMLSelectElement>);
    setOpen(false);
    triggerRef.current?.focus();
  };

  const moveHl = (dir: 1 | -1) => {
    setHl((i) => {
      let n = i;
      for (let k = 0; k < opts.length; k++) {
        n = (n + dir + opts.length) % opts.length;
        if (!opts[n].disabled) break;
      }
      return n;
    });
  };

  const onTriggerKey = (e: React.KeyboardEvent) => {
    if (disabled) return;
    if (!open && (e.key === "ArrowDown" || e.key === "Enter" || e.key === " ")) {
      e.preventDefault();
      setOpen(true);
    } else if (open) {
      if (e.key === "ArrowDown") { e.preventDefault(); moveHl(1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); moveHl(-1); }
      else if (e.key === "Enter" || e.key === " ") { e.preventDefault(); opts[hl] && commit(opts[hl]); }
    }
  };

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        id={id}
        disabled={disabled}
        className="input bt-select"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => !disabled && (open ? setOpen(false) : setOpen(true))}
        onKeyDown={onTriggerKey}
      >
        <span className="bt-select-val">{selected ? selected.label : <span style={{ color: "var(--ink-3)" }}>Select…</span>}</span>
        <svg className="bt-select-caret" viewBox="0 0 24 24" fill="none" stroke="currentColor">
          <path d="m6 9 6 6 6-6" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {open && pos && typeof document !== "undefined" &&
        createPortal(
          <div
            ref={popRef}
            className="bt-select-pop"
            role="listbox"
            style={{ left: pos.left, width: pos.width, top: pos.top, bottom: pos.bottom, maxHeight: pos.maxH }}
          >
            {opts.map((o, i) => (
              <div
                key={o.value + i}
                role="option"
                aria-selected={o.value === String(value ?? "")}
                className={
                  "bt-select-opt" +
                  (o.value === String(value ?? "") ? " sel" : "") +
                  (i === hl ? " hl" : "") +
                  (o.disabled ? " disabled" : "")
                }
                onMouseEnter={() => setHl(i)}
                onClick={() => commit(o)}
              >
                <span className="bt-select-val">{o.label}</span>
                {o.value === String(value ?? "") && (
                  <svg className="bt-check" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                    <path d="m5 13 4 4L19 7" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                )}
              </div>
            ))}
          </div>,
          document.body
        )}
    </>
  );
}

// --------------------------------------------------------------------------- //
// Color picker: an interactive HSV widget (saturation/value area + hue slider)
// opened from a trigger swatch, with a live preview, copy button, and an
// editable value field that switches between Hex / RGB / HSL. `value` (a hex
// string) is the source of truth; HSV is kept internally so gray/black values
// don't lose their hue while dragging.
// --------------------------------------------------------------------------- //
type HSV = { h: number; s: number; v: number };

const clamp01 = (n: number) => Math.max(0, Math.min(1, n));

function hsvToRgb({ h, s, v }: HSV): [number, number, number] {
  h = ((h % 360) + 360) % 360;
  const c = v * s;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = v - c;
  let r = 0, g = 0, b = 0;
  if (h < 60) [r, g, b] = [c, x, 0];
  else if (h < 120) [r, g, b] = [x, c, 0];
  else if (h < 180) [r, g, b] = [0, c, x];
  else if (h < 240) [r, g, b] = [0, x, c];
  else if (h < 300) [r, g, b] = [x, 0, c];
  else [r, g, b] = [c, 0, x];
  return [
    Math.round((r + m) * 255),
    Math.round((g + m) * 255),
    Math.round((b + m) * 255),
  ];
}

function rgbToHsv(r: number, g: number, b: number): HSV {
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min;
  let h = 0;
  if (d !== 0) {
    if (max === r) h = ((g - b) / d) % 6;
    else if (max === g) h = (b - r) / d + 2;
    else h = (r - g) / d + 4;
    h = h * 60;
    if (h < 0) h += 360;
  }
  return { h, s: max === 0 ? 0 : d / max, v: max };
}

// Parse #rgb / #rrggbb into [r,g,b]; returns null when the string isn't a hex color.
function hexToRgb(hex: string): [number, number, number] | null {
  const s = hex.trim().replace(/^#/, "");
  if (/^[0-9a-fA-F]{3}$/.test(s)) {
    return [s[0] + s[0], s[1] + s[1], s[2] + s[2]].map((h) => parseInt(h, 16)) as [number, number, number];
  }
  if (/^[0-9a-fA-F]{6}$/.test(s)) {
    return [s.slice(0, 2), s.slice(2, 4), s.slice(4, 6)].map((h) => parseInt(h, 16)) as [number, number, number];
  }
  return null;
}

const toHex2 = (n: number) => Math.max(0, Math.min(255, Math.round(n))).toString(16).padStart(2, "0");
const rgbToHex = (r: number, g: number, b: number) => "#" + toHex2(r) + toHex2(g) + toHex2(b);
const hsvToHex = (hsv: HSV) => rgbToHex(...hsvToRgb(hsv));

function rgbToHsl(r: number, g: number, b: number): [number, number, number] {
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min;
  const l = (max + min) / 2;
  let h = 0, s = 0;
  if (d !== 0) {
    s = d / (1 - Math.abs(2 * l - 1));
    if (max === r) h = ((g - b) / d) % 6;
    else if (max === g) h = (b - r) / d + 2;
    else h = (r - g) / d + 4;
    h = h * 60;
    if (h < 0) h += 360;
  }
  return [Math.round(h), Math.round(s * 100), Math.round(l * 100)];
}

function hslToRgb(h: number, s: number, l: number): [number, number, number] {
  s /= 100; l /= 100;
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const x = c * (1 - Math.abs((((h % 360) + 360) / 60) % 2 - 1));
  const m = l - c / 2;
  let r = 0, g = 0, b = 0;
  const hh = ((h % 360) + 360) % 360;
  if (hh < 60) [r, g, b] = [c, x, 0];
  else if (hh < 120) [r, g, b] = [x, c, 0];
  else if (hh < 180) [r, g, b] = [0, c, x];
  else if (hh < 240) [r, g, b] = [0, x, c];
  else if (hh < 300) [r, g, b] = [x, 0, c];
  else [r, g, b] = [c, 0, x];
  return [Math.round((r + m) * 255), Math.round((g + m) * 255), Math.round((b + m) * 255)];
}

type Fmt = "hex" | "rgb" | "hsl";

// Format the current HSV as a display string for the chosen mode.
function formatColor(hsv: HSV, fmt: Fmt): string {
  const [r, g, b] = hsvToRgb(hsv);
  if (fmt === "rgb") return `${r}, ${g}, ${b}`;
  if (fmt === "hsl") {
    const [h, s, l] = rgbToHsl(r, g, b);
    return `${h}, ${s}%, ${l}%`;
  }
  return hsvToHex(hsv).slice(1).toUpperCase();
}

// Parse an edited value string (for the chosen mode) back into HSV; null if unparseable.
function parseColor(raw: string, fmt: Fmt): HSV | null {
  if (fmt === "hex") {
    const rgb = hexToRgb(raw);
    return rgb ? rgbToHsv(...rgb) : null;
  }
  const nums = raw.match(/-?\d+(\.\d+)?/g)?.map(Number);
  if (!nums || nums.length < 3) return null;
  if (fmt === "rgb") return rgbToHsv(clampByte(nums[0]), clampByte(nums[1]), clampByte(nums[2]));
  return rgbToHsv(...hslToRgb(nums[0], Math.max(0, Math.min(100, nums[1])), Math.max(0, Math.min(100, nums[2]))));
}
const clampByte = (n: number) => Math.max(0, Math.min(255, Math.round(n)));

export function ColorPicker({
  value,
  onChange,
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [fmt, setFmt] = useState<Fmt>("hex");
  const [draft, setDraft] = useState<string | null>(null); // in-flight text while editing the value field
  const [copied, setCopied] = useState(false);
  const [hsv, setHsv] = useState<HSV>(() => {
    const rgb = hexToRgb(value);
    return rgb ? rgbToHsv(...rgb) : { h: 0, s: 0, v: 0 };
  });

  const wrapRef = useRef<HTMLDivElement>(null);
  const areaRef = useRef<HTMLDivElement>(null);
  const hueRef = useRef<HTMLDivElement>(null);
  const hsvRef = useRef(hsv);
  hsvRef.current = hsv;
  const drag = useRef<null | "area" | "hue">(null);

  // Sync external value → internal HSV when it changes and isn't what we already show.
  useEffect(() => {
    const rgb = hexToRgb(value);
    if (rgb && rgbToHex(...rgb).toLowerCase() !== hsvToHex(hsvRef.current).toLowerCase()) {
      setHsv(rgbToHsv(...rgb));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  const commit = useCallback(
    (patch: Partial<HSV>) => {
      const next = { ...hsvRef.current, ...patch };
      hsvRef.current = next;
      setHsv(next);
      onChange(hsvToHex(next));
    },
    [onChange]
  );

  const areaFromEvent = useCallback((clientX: number, clientY: number) => {
    const r = areaRef.current?.getBoundingClientRect();
    if (!r) return;
    commit({ s: clamp01((clientX - r.left) / r.width), v: 1 - clamp01((clientY - r.top) / r.height) });
  }, [commit]);

  const hueFromEvent = useCallback((clientX: number) => {
    const r = hueRef.current?.getBoundingClientRect();
    if (!r) return;
    commit({ h: clamp01((clientX - r.left) / r.width) * 360 });
  }, [commit]);

  // Global drag tracking so the pointer can leave the widget while dragging.
  useEffect(() => {
    const move = (e: PointerEvent) => {
      if (drag.current === "area") areaFromEvent(e.clientX, e.clientY);
      else if (drag.current === "hue") hueFromEvent(e.clientX);
    };
    const up = () => (drag.current = null);
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
  }, [areaFromEvent, hueFromEvent]);

  // Close on outside click / Escape.
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      // The format dropdown renders its popup in a portal outside wrapRef — don't
      // treat clicks inside it as "outside" the picker.
      if (wrapRef.current?.contains(t)) return;
      if ((t as HTMLElement).closest?.(".bt-select-pop")) return;
      setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown, true);
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("mousedown", onDown, true);
      document.removeEventListener("keydown", onKey, true);
    };
  }, [open]);

  const hex = hsvToHex(hsv);
  const hueColor = hsvToHex({ h: hsv.h, s: 1, v: 1 });
  const shown = draft ?? formatColor(hsv, fmt);

  const copy = () => {
    const text = (fmt === "hex" ? "#" : "") + formatColor(hsv, fmt);
    navigator.clipboard?.writeText(text).then(
      () => { setCopied(true); setTimeout(() => setCopied(false), 1200); },
      () => {}
    );
  };

  return (
    <div className="cp" ref={wrapRef}>
      <button type="button" className="cp-trigger" onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-haspopup="dialog">
        <span className="cp-trigger-sw" style={{ background: hex }} />
        <span className="cp-trigger-hex">{hex.toUpperCase()}</span>
        <svg className="bt-select-caret" viewBox="0 0 24 24" fill="none" stroke="currentColor">
          <path d="m6 9 6 6 6-6" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {open && (
        <div className="cp-pop" role="dialog" aria-label="Color picker">
          <div
            ref={areaRef}
            className="cp-area"
            style={{ background: `linear-gradient(to top, #000, transparent), linear-gradient(to right, #fff, ${hueColor})` }}
            onPointerDown={(e) => {
              drag.current = "area";
              (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
              areaFromEvent(e.clientX, e.clientY);
            }}
          >
            <span className="cp-area-cursor" style={{ left: `${hsv.s * 100}%`, top: `${(1 - hsv.v) * 100}%`, background: hex }} />
          </div>

          <div
            ref={hueRef}
            className="cp-hue"
            onPointerDown={(e) => {
              drag.current = "hue";
              (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
              hueFromEvent(e.clientX);
            }}
          >
            <span className="cp-hue-thumb" style={{ left: `${(hsv.h / 360) * 100}%`, background: hueColor }} />
          </div>

          <div className="cp-foot">
            <span className="cp-preview" style={{ background: hex }} />
            <div className="cp-valwrap">
              {fmt === "hex" && <span className="cp-hash">#</span>}
              <input
                className="cp-val"
                value={shown}
                spellCheck={false}
                onChange={(e) => {
                  setDraft(e.target.value);
                  const parsed = parseColor(e.target.value, fmt);
                  if (parsed) commit(parsed);
                }}
                onBlur={() => setDraft(null)}
                aria-label="Color value"
              />
            </div>
            <button type="button" className="cp-copy" onClick={copy} aria-label="Copy color" title={copied ? "Copied" : "Copy"}>
              {copied ? (
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="m5 13 4 4L19 7" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>
              ) : (
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><rect x="9" y="9" width="11" height="11" rx="2" strokeWidth="1.8" /><path d="M5 15V5a2 2 0 0 1 2-2h10" strokeWidth="1.8" strokeLinecap="round" /></svg>
              )}
            </button>
            <div className="cp-fmt">
              <Select value={fmt} onChange={(e) => { setDraft(null); setFmt(e.target.value as Fmt); }}>
                <option value="hex">Hex</option>
                <option value="rgb">RGB</option>
                <option value="hsl">HSL</option>
              </Select>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Segmented control (All / Assets / Liabilities, filters, etc.)
// --------------------------------------------------------------------------- //
export function Segmented<T extends string>({
  options,
  value,
  onChange,
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div className="seg" role="tablist">
      {options.map((o) => (
        <button
          key={o.value}
          role="tab"
          aria-selected={o.value === value}
          className={"seg-btn" + (o.value === value ? " active" : "")}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

// --------------------------------------------------------------------------- //
// Buttons
// --------------------------------------------------------------------------- //
export function Button({
  variant = "ghost",
  children,
  ...rest
}: {
  variant?: "primary" | "ghost" | "danger";
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const cls =
    variant === "primary" ? "btn-primary" : variant === "danger" ? "btn-danger" : "btn-ghost";
  return (
    <button {...rest} className={cls + " " + (rest.className || "")}>
      {children}
    </button>
  );
}

// Inline error banner for form submit failures.
export function FormError({ message }: { message?: string | null }) {
  if (!message) return null;
  return <div className="form-error">{message}</div>;
}

// Progress bar for budgets / goals / debts. `pct` may exceed 100 (over budget).
export function Progress({ pct, color }: { pct: number | null; color?: string }) {
  const p = Math.max(0, Math.min(100, pct ?? 0));
  const over = (pct ?? 0) > 100;
  return (
    <div className="progress">
      <div
        className="progress-fill"
        style={{ width: `${p}%`, background: over ? "var(--negative)" : color || "var(--accent)" }}
      />
    </div>
  );
}

// Countdown / overdue badge from a day delta (PRD "117 days overdue").
export function DueBadge({ days }: { days: number | null | undefined }) {
  if (days == null) return null;
  if (days < 0) return <span className="due-badge overdue">{Math.abs(days)}d overdue</span>;
  if (days === 0) return <span className="due-badge today">Due today</span>;
  return <span className="due-badge">in {days}d</span>;
}
