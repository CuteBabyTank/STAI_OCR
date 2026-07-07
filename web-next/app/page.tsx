"use client";

import { useCallback, useEffect, useRef, useState } from "react";

// --------------------------------------------------------------------------- //
// Types & constants
// --------------------------------------------------------------------------- //
type Category = "Food" | "Shopping" | "Health" | "Other";

interface Receipt {
  id: number;
  vendor_name: string | null;
  category: string | null;
  total_amount: number | null;
  currency: string | null;
  receipt_date: string | null;
  source_file: string | null;
}

interface Summary {
  total: number;
  count: number;
  by_category: Record<string, number>;
  top_category: string | null;
  currency: string | null;
  mixed_currency: boolean;
}

interface BatchItem {
  name: string;
  status: "reading" | "done" | "error";
  id?: number;
  merchant?: string;
  category?: string;
  amount?: number;
  currency?: string;
  needsReview?: boolean;
  error?: string;
}

interface ChatMsg {
  who: "me" | "bot";
  text: string;
  cite?: string;
  err?: boolean;
}

const CAT_ORDER: Category[] = ["Food", "Shopping", "Health", "Other"];
const CAT_META: Record<string, { color: string; emoji: string }> = {
  Food: { color: "var(--cat-food)", emoji: "🍜" },
  Shopping: { color: "var(--cat-shopping)", emoji: "🛍️" },
  Health: { color: "var(--cat-health)", emoji: "💊" },
  Other: { color: "var(--cat-other)", emoji: "•" },
};
const catMeta = (c?: string | null) => CAT_META[c || "Other"] || CAT_META.Other;

const SYMBOLS: Record<string, string> = {
  PHP: "₱", USD: "$", EUR: "€", GBP: "£", JPY: "¥", INR: "₹",
};
const sym = (cur?: string | null) => (cur && SYMBOLS[cur]) || (cur ? cur + " " : "₱");
const money = (n: number | null | undefined, cur?: string | null, dp = 2) =>
  sym(cur) + Number(n || 0).toLocaleString(undefined, { minimumFractionDigits: dp, maximumFractionDigits: dp });

function fmtDate(iso?: string | null) {
  if (!iso) return "Undated";
  const d = new Date(iso + "T00:00:00");
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
const monthKey = (iso?: string | null) =>
  iso && iso.length >= 7 && /^\d{4}/.test(iso) ? iso.slice(0, 7) : "Unknown";
function monthLabel(key: string) {
  if (key === "Unknown") return "Undated";
  const d = new Date(key + "-01T00:00:00");
  return isNaN(d.getTime()) ? key : d.toLocaleDateString(undefined, { month: "long", year: "numeric" });
}

// --------------------------------------------------------------------------- //
// Icons
// --------------------------------------------------------------------------- //
const RobotSVG = ({ eye = "#fff", body = "var(--accent)" }: { eye?: string; body?: string }) => (
  <svg viewBox="0 0 40 40" fill="none">
    <rect x="9" y="12" width="22" height="18" rx="6" fill={body} />
    <rect x="13" y="17" width="5" height="6" rx="2.5" fill={eye} />
    <rect x="22" y="17" width="5" height="6" rx="2.5" fill={eye} />
    <path d="M17 27h6" stroke={eye} strokeWidth="2" strokeLinecap="round" />
    <path d="M20 12V7" stroke={eye} strokeWidth="2" strokeLinecap="round" />
    <circle cx="20" cy="6" r="2.2" fill={eye} />
  </svg>
);

// --------------------------------------------------------------------------- //
// Page
// --------------------------------------------------------------------------- //
export default function Dashboard() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [receipts, setReceipts] = useState<Receipt[]>([]);
  const [greeting, setGreeting] = useState("Welcome");
  const [today, setToday] = useState("");
  const [newIds, setNewIds] = useState<number[]>([]);

  const [panelOpen, setPanelOpen] = useState(false);
  const [batch, setBatch] = useState<BatchItem[]>([]);
  const [dragging, setDragging] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const [chatOpen, setChatOpen] = useState(false);
  const [seeded, setSeeded] = useState(false);
  const [msgs, setMsgs] = useState<ChatMsg[]>([]);
  const [typing, setTyping] = useState(false);
  const [chatText, setChatText] = useState("");
  const chatBodyRef = useRef<HTMLDivElement>(null);

  const [showPast, setShowPast] = useState(false);
  const [pastMonth, setPastMonth] = useState("All months");
  const [toast, setToast] = useState("");

  // ---- data loading ----
  const refresh = useCallback(async () => {
    try {
      const [s, r] = await Promise.all([
        fetch("/api/summary").then((x) => x.json()),
        fetch("/api/receipts?limit=1000").then((x) => x.json()),
      ]);
      setSummary(s);
      setReceipts(r.receipts || []);
    } catch {
      /* backend not ready yet — leave last-known state */
    }
  }, []);

  useEffect(() => {
    const h = new Date().getHours();
    setGreeting(h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening");
    setToday(new Date().toLocaleDateString(undefined, { month: "long", day: "numeric" }));
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (chatBodyRef.current) chatBodyRef.current.scrollTop = chatBodyRef.current.scrollHeight;
  }, [msgs, typing]);

  const flashToast = (m: string) => {
    setToast(m);
    window.setTimeout(() => setToast(""), 2600);
  };

  // ---- upload / OCR (real /extract) ----
  const processFiles = async (files: File[]) => {
    if (!files.length) return;
    setBatch(files.map((f) => ({ name: f.name, status: "reading" as const })));
    const added: number[] = [];
    for (let i = 0; i < files.length; i++) {
      try {
        const fd = new FormData();
        fd.append("file", files[i]);
        const res = await fetch("/api/extract", { method: "POST", body: fd });
        const j = await res.json();
        if (!res.ok) throw new Error(j.detail || res.statusText);
        const d = j.data || {};
        added.push(j.receipt_id);
        setBatch((prev) => {
          const next = [...prev];
          next[i] = {
            name: files[i].name,
            status: "done",
            id: j.receipt_id,
            merchant: d.vendor_name || files[i].name,
            category: d.category || "Other",
            amount: d.total_amount ?? 0,
            currency: d.currency,
            needsReview: !!j.needs_review,
          };
          return next;
        });
      } catch (e: any) {
        setBatch((prev) => {
          const next = [...prev];
          next[i] = { name: files[i].name, status: "error", error: e?.message || "Failed to read" };
          return next;
        });
      }
    }
    setNewIds(added);
    window.setTimeout(() => setNewIds([]), 700);
    await refresh();
    const ok = added.length;
    if (ok) flashToast(`Added ${ok} receipt${ok > 1 ? "s" : ""}`);
  };

  const onPick = () => fileRef.current?.click();
  const onFiles = (fl: FileList | null) => fl && processFiles(Array.from(fl));

  const deleteReceipt = async (id: number, fromBatch = false) => {
    try {
      await fetch(`/api/receipts/${id}`, { method: "DELETE" });
      if (fromBatch) setBatch((prev) => prev.filter((b) => b.id !== id));
      await refresh();
      flashToast(`Deleted receipt #${id}`);
    } catch {
      flashToast("Couldn't delete that receipt");
    }
  };

  const openPanel = () => {
    setBatch([]);
    setPanelOpen(true);
  };
  const closePanel = () => {
    setPanelOpen(false);
    setBatch([]);
  };

  // ---- chat (real /agent) ----
  const seedChat = () => {
    if (seeded) return;
    setSeeded(true);
    setMsgs([{ who: "bot", text: "Hi 👋 I'm your receipt assistant. Ask me anything about your spending — I read straight from your saved receipts." }]);
  };
  const openChat = () => {
    setChatOpen(true);
    seedChat();
  };

  const ask = async (q: string) => {
    q = q.trim();
    if (!q || typing) return;
    setMsgs((m) => [...m, { who: "me", text: q }]);
    setChatText("");
    setTyping(true);
    try {
      // The SQL ledger agent reliably answers spending questions (totals, per
      // category, counts, biggest purchase). It's steadier than the ReAct agent
      // for this chat's aggregate-focused questions.
      const res = await fetch("/api/ask", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ question: q }),
      });
      const j = await res.json();
      if (!res.ok) throw new Error(j.detail || res.statusText);
      const cite = j.sql ? `ledger query · ${j.rows?.length ?? 0} row${j.rows?.length === 1 ? "" : "s"}` : undefined;
      setMsgs((m) => [
        ...m,
        { who: "bot", text: j.answer || "I couldn't find an answer for that.", cite },
      ]);
    } catch (e: any) {
      setMsgs((m) => [...m, { who: "bot", err: true, text: `Something went wrong: ${e?.message || "the agent didn't respond"}.` }]);
    } finally {
      setTyping(false);
    }
  };

  const toggleTheme = () => {
    const root = document.documentElement;
    const cur = root.getAttribute("data-theme") ||
      (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    root.setAttribute("data-theme", cur === "dark" ? "light" : "dark");
  };

  // ---- derived ----
  const byCat = summary?.by_category || {};
  const catTotal = Object.values(byCat).reduce((s, v) => s + v, 0);
  const donutCats = [
    ...CAT_ORDER.filter((c) => byCat[c] > 0),
    ...Object.keys(byCat).filter((c) => !CAT_ORDER.includes(c as Category) && byCat[c] > 0),
  ];
  let acc = 0;
  const stops = donutCats
    .map((c) => {
      const start = (acc / catTotal) * 360;
      acc += byCat[c];
      const end = (acc / catTotal) * 360;
      return `${catMeta(c).color} ${start}deg ${end}deg`;
    })
    .join(", ");
  const donutBg = catTotal > 0 ? `conic-gradient(${stops})` : "var(--border)";

  const recent = receipts.slice(0, 6);

  const pastMonths = Array.from(new Set(receipts.map((r) => monthKey(r.receipt_date)))).sort().reverse();
  const filtered = pastMonth === "All months"
    ? receipts
    : receipts.filter((r) => monthLabel(monthKey(r.receipt_date)) === pastMonth);
  const groupMonths = Array.from(new Set(filtered.map((r) => monthKey(r.receipt_date)))).sort().reverse();

  const chips = ["How much did I spend?", "Top category?", "My biggest purchase", "Food spending"];
  const savedInBatch = batch.filter((b) => b.status === "done").length;

  return (
    <div className="shell">
      {/* Sidebar */}
      <aside className="sidebar">
        <div className="sidebar-inner">
          <div className="brand">
            <div className="brand-mark">◆</div>
            <span className="brand-name">Receipt Ledger</span>
          </div>
          <nav>
            <button className="nav-item active">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><rect x="3" y="3" width="7" height="9" rx="1.5" /><rect x="14" y="3" width="7" height="5" rx="1.5" /><rect x="14" y="12" width="7" height="9" rx="1.5" /><rect x="3" y="16" width="7" height="5" rx="1.5" /></svg>Overview
            </button>
            <button className="nav-item" onClick={openChat}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></svg>Ask receipts
            </button>
          </nav>
          <div className="nav-user">
            <div className="avatar">◆</div>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 13.5, fontWeight: 560, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>Local ledger</div>
              <div style={{ fontSize: 12, color: "var(--ink-3)" }}>runs on your machine</div>
            </div>
          </div>
        </div>
      </aside>

      {/* Main */}
      <main>
        <header>
          <div>
            <h1>{greeting}</h1>
            <p className="subhead">Here&apos;s your spending today · {today}</p>
          </div>
          <div className="header-actions">
            <button className="icon-btn" onClick={toggleTheme} title="Toggle theme" aria-label="Toggle theme">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" /></svg>
            </button>
            <button className="btn-primary" onClick={openPanel}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M12 5v14M5 12h14" /></svg>Add
            </button>
          </div>
        </header>

        {/* Overview cards */}
        <section className="stat-grid">
          <div className="card accent">
            <p className="stat-label">Total spent</p>
            <p className="stat-value num">{money(summary?.total, summary?.currency)}</p>
            <p className="stat-sub">{summary?.mixed_currency ? "⚠ multiple currencies" : "across all receipts"}</p>
          </div>
          <div className="card">
            <p className="stat-label">Receipts</p>
            <p className="stat-value num">{summary?.count ?? 0}</p>
            <p className="stat-sub">in your ledger</p>
          </div>
          <div className="card">
            <p className="stat-label">Top category</p>
            <p className="stat-value">{summary?.top_category || "—"}</p>
            <p className="stat-sub">most spending</p>
          </div>
        </section>

        {/* Insight band */}
        <section className="band">
          <div className="card">
            <div className="card-head"><p className="card-title">Spending by category</p></div>
            <div className="donut-wrap">
              <div className="donut" style={{ background: donutBg }}>
                <div className="donut-hole">
                  <div>
                    <p className="k">Spent</p>
                    <p className="v num">{money(catTotal, summary?.currency, 0)}</p>
                  </div>
                </div>
              </div>
              <ul className="legend">
                {CAT_ORDER.map((c) => {
                  const pct = catTotal > 0 ? Math.round(((byCat[c] || 0) / catTotal) * 100) : 0;
                  return (
                    <li key={c}>
                      <span className="dot" style={{ background: catMeta(c).color }} />
                      <span className="name">{c}</span>
                      <span className="pct num">{pct}%</span>
                    </li>
                  );
                })}
              </ul>
            </div>
          </div>

          <div className="card">
            <div className="card-head">
              <p className="card-title">Recent transactions</p>
              <button className="link" onClick={() => setShowPast(true)}>View all</button>
            </div>
            {recent.length === 0 ? (
              <div className="empty">
                <p className="h">Nothing logged yet</p>
                <p className="s">Scan a receipt with “Add” and it&apos;ll show up here.</p>
              </div>
            ) : (
              <ul className="txn-list">
                {recent.map((t) => (
                  <li key={t.id} className={"txn" + (newIds.includes(t.id) ? " new" : "")}>
                    <div className="txn-icon">{catMeta(t.category).emoji}</div>
                    <div className="txn-body">
                      <div className="txn-merchant">{t.vendor_name || "Unknown merchant"}</div>
                      <div className="txn-meta">{t.category || "Other"} · {fmtDate(t.receipt_date)}</div>
                    </div>
                    <span className="txn-amt num">{money(t.total_amount, t.currency)}</span>
                    <button className="txn-del" title="Delete" onClick={() => deleteReceipt(t.id)}>
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M6 6l12 12M18 6 6 18" /></svg>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>

      </main>

      {/* Past receipts modal */}
      <div className={"scrim" + (showPast ? " open" : "")} onClick={() => setShowPast(false)} />
      <div className={"modal" + (showPast ? " open" : "")} role="dialog" aria-modal="true" aria-label="Past receipts">
        <div className="modal-head">
          <p className="section-eyebrow">Past receipts</p>
          <button className="close-x" onClick={() => setShowPast(false)} aria-label="Close">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M6 6l12 12M18 6 6 18" /></svg>
          </button>
        </div>
        <div className="modal-body">
          {receipts.length === 0 ? (
            <p className="s" style={{ color: "var(--ink-3)", fontSize: 14 }}>No receipts yet.</p>
          ) : (
            <>
              <select className="month-filter" value={pastMonth} onChange={(e) => setPastMonth(e.target.value)}>
                <option>All months</option>
                {pastMonths.map((m) => (
                  <option key={m}>{monthLabel(m)}</option>
                ))}
              </select>
              {groupMonths.map((m) => {
                const group = filtered
                  .filter((r) => monthKey(r.receipt_date) === m)
                  .sort((a, b) => (b.receipt_date || "").localeCompare(a.receipt_date || ""));
                const subtotal = group.reduce((s, r) => s + (r.total_amount || 0), 0);
                const cur = group.find((r) => r.currency)?.currency;
                return (
                  <div key={m} className="month-group">
                    <p className="month-head">{monthLabel(m)} — {group.length} receipt{group.length > 1 ? "s" : ""} · {money(subtotal, cur)}</p>
                    {group.map((r) => (
                      <div key={r.id} className="past-row">
                        <div className="txn-icon">{catMeta(r.category).emoji}</div>
                        <div className="p-body">
                          <div className="p-merch">#{r.id} · {r.vendor_name || "Unknown merchant"}</div>
                          <div className="p-meta">{r.category || "Other"} · {r.receipt_date || "Undated"}</div>
                        </div>
                        <span className="p-amt num">{money(r.total_amount, r.currency)}</span>
                        <button className="p-del" title="Delete (also removes from search memory)" onClick={() => deleteReceipt(r.id)}>
                          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M6 6l12 12M18 6 6 18" /></svg>
                        </button>
                      </div>
                    ))}
                  </div>
                );
              })}
            </>
          )}
        </div>
      </div>

      {/* Add / scan slide-over */}
      <div className={"scrim" + (panelOpen ? " open" : "")} onClick={closePanel} />
      <div className={"panel" + (panelOpen ? " open" : "")} role="dialog" aria-modal="true" aria-label="Add receipts">
        <div className="panel-head">
          <h2>Scan receipts</h2>
          <button className="icon-btn" style={{ width: 34, height: 34 }} onClick={closePanel} aria-label="Close">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M6 6l12 12M18 6 6 18" /></svg>
          </button>
        </div>
        <p className="panel-desc">Drop one or more receipt images — the local vision model reads each and files it automatically.</p>

        <div className="panel-scroll">
          <input ref={fileRef} type="file" accept="image/*" multiple hidden onChange={(e) => onFiles(e.target.files)} />
          <div
            className={"dropzone" + (dragging ? " drag" : "")}
            onClick={onPick}
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave={(e) => { e.preventDefault(); setDragging(false); }}
            onDrop={(e) => { e.preventDefault(); setDragging(false); onFiles(e.dataTransfer.files); }}
          >
            <div className="dz-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M12 16V4M12 4 8 8M12 4l4 4" /><path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" /></svg>
            </div>
            <div className="dz-title">Drop images or click to browse</div>
            <div className="dz-sub">PNG · JPG · WEBP · reads with qwen2.5vl</div>
          </div>

          {batch.length > 0 && (
            <>
              <p className="batch-head">
                {savedInBatch > 0 ? `${savedInBatch} of ${batch.length} filed` : `Reading ${batch.length} receipt${batch.length > 1 ? "s" : ""}…`}
              </p>
              <div className="batch-list">
                {batch.map((b, i) => (
                  <div key={i} className={"batch-row" + (b.status === "error" ? " error" : "")}>
                    {b.status === "reading" ? (
                      <div className="b-spin-wrap"><div className="dz-spin" /></div>
                    ) : (
                      <span className="b-emoji">{b.status === "error" ? "⚠️" : catMeta(b.category).emoji}</span>
                    )}
                    <div className="b-body">
                      {b.status === "done" ? (
                        <>
                          <div className="b-merch">
                            {b.merchant}
                            {b.needsReview && <span className="b-review">needs review</span>}
                          </div>
                          <span className="b-cat" style={{ background: catMeta(b.category).color }}>{b.category}</span>
                        </>
                      ) : b.status === "error" ? (
                        <>
                          <div className="b-merch">{b.name}</div>
                          <div className="b-err">{b.error}</div>
                        </>
                      ) : (
                        <>
                          <div className="b-merch">{b.name}</div>
                          <div className="b-file">Reading with the vision model…</div>
                        </>
                      )}
                    </div>
                    {b.status === "done" && <span className="b-amt num">{money(b.amount, b.currency)}</span>}
                    {b.status === "done" && b.id != null && (
                      <button className="b-del" title="Delete" onClick={() => deleteReceipt(b.id!, true)}>
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M6 6l12 12M18 6 6 18" /></svg>
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </>
          )}
        </div>

        <div className="panel-foot">
          <button className="btn-save" onClick={closePanel}>Done</button>
        </div>
      </div>

      {/* Toast */}
      <div className={"toast" + (toast ? " show" : "")}><span className="tdot" />{toast}</div>

      {/* Robot RAG assistant */}
      <button className="robot-fab" onClick={() => (chatOpen ? setChatOpen(false) : openChat())} aria-label="Ask the assistant">
        {!chatOpen && <span className="ping" />}
        <span className="float"><RobotSVG /></span>
      </button>

      <div className={"chat" + (chatOpen ? " open" : "")} role="dialog" aria-label="Receipt assistant">
        <div className="chat-head">
          <div className="chat-ava"><RobotSVG eye="var(--accent)" body="var(--accent-wash)" /></div>
          <div>
            <div className="ct">Receipt Assistant</div>
            <div className="cs"><span className="live" />RAG agent · reads your receipts</div>
          </div>
          <button className="close-x" onClick={() => setChatOpen(false)} aria-label="Close chat">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M6 6l12 12M18 6 6 18" /></svg>
          </button>
        </div>
        <div className="chat-body" ref={chatBodyRef}>
          {msgs.map((m, i) => (
            <div key={i} className={"msg " + m.who + (m.err ? " err" : "")}>
              {m.text}
              {m.cite && <span className="cite">📎 {m.cite}</span>}
            </div>
          ))}
          {typing && <div className="typing"><span /><span /><span /></div>}
        </div>
        {msgs.length <= 1 && !typing && (
          <div className="chips">
            {chips.map((c) => (
              <button key={c} className="chip" onClick={() => ask(c)}>{c}</button>
            ))}
          </div>
        )}
        <div className="chat-input">
          <input
            value={chatText}
            onChange={(e) => setChatText(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") ask(chatText); }}
            placeholder="Ask about your spending…"
          />
          <button className="send" disabled={typing} onClick={() => ask(chatText)} aria-label="Send">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M22 2 11 13M22 2l-7 20-4-9-9-4 20-7z" /></svg>
          </button>
        </div>
      </div>
    </div>
  );
}
