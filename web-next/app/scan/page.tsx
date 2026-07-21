"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Analytics, Granularity, Receipt } from "../lib/types";
import { CAT_ORDER, catMeta, money, monthKey, monthLabel } from "../lib/format";
import StatTiles from "../components/StatTiles";
import CashflowChart from "../components/CashflowChart";
import TopVendors from "../components/TopVendors";
import BudgetsCard from "../components/BudgetsCard";
import IncomePanel from "../components/IncomePanel";
import { Select } from "../components/ui";
import PeriodControl from "../components/PeriodControl";
import TxnRow from "../components/TxnRow";
import ConfidenceBadge from "../components/ConfidenceBadge";

interface PeriodSel {
  granularity: Granularity;
  year: number;
  month: number;
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
  confidence?: number; // measured OCR confidence (0..1) from token logprobs
  error?: string;
}

// One step in the ReAct agent's reasoning trace, streamed live from the backend.
interface ReasonStep {
  kind: "thought" | "action" | "observation";
  text: string;
  tool?: string;
  live?: boolean; // a thought still being streamed token-by-token
}

interface ChatMsg {
  who: "me" | "bot";
  text: string;
  cite?: string;
  err?: boolean;
  steps?: ReasonStep[]; // the ReAct reasoning behind a bot answer
  thinking?: boolean; // still streaming
  clarify?: boolean; // a clarifying question back to the user
}

// Keep only the "Thought:" portion of a raw ReAct block for display, dropping the
// Action / Action Input lines (those are shown as their own steps).
function thoughtOnly(text: string): string {
  const cut = text.split(/\n?\s*Action\s*:/i)[0];
  return cut.replace(/^\s*Thought\s*:\s*/i, "").trim();
}

// One compact line describing a tool's result, for the reasoning trace.
function obsSummary(ev: any): string {
  const d = ev.data || {};
  if (d.kind === "sql") {
    const n = (d.rows || []).length;
    return `queried the ledger · ${n} row${n === 1 ? "" : "s"}`;
  }
  if (d.kind === "search") {
    const hits = d.hits || [];
    if (!hits.length) return "searched receipts · no matches";
    const names = hits
      .slice(0, 3)
      .map((h: any) => `#${h.receipt_id} ${h.vendor_name || "—"}`)
      .join(", ");
    return `searched receipts · ${hits.length} found · ${names}`;
  }
  if (d.kind === "note") return "already had that result";
  return String(ev.text || "").slice(0, 120);
}

// --------------------------------------------------------------------------- //
// Icons
// --------------------------------------------------------------------------- //
const RobotSVG = ({
  eye = "#fff",
  body = "var(--accent)",
}: {
  eye?: string;
  body?: string;
}) => (
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
  const [analytics, setAnalytics] = useState<Analytics | null>(null);
  const [periodSel, setPeriodSel] = useState<PeriodSel | null>(null);
  const [receipts, setReceipts] = useState<Receipt[]>([]);
  const [greeting, setGreeting] = useState("Welcome");
  const [today, setToday] = useState("");
  const [newIds, setNewIds] = useState<number[]>([]);

  const [panelOpen, setPanelOpen] = useState(false);
  const [incomeOpen, setIncomeOpen] = useState(false);
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

  // ---- data loading (defaults to ALL-TIME so the dashboard totals every receipt) ----
  const refresh = useCallback(async () => {
    try {
      const qs = periodSel
        ? `?granularity=${periodSel.granularity}&year=${periodSel.year}&month=${periodSel.month}`
        : "?granularity=all";
      const [r, a] = await Promise.all([
        fetch("/api/receipts?limit=1000").then((x) => x.json()),
        fetch("/api/analytics" + qs).then((x) => x.json()),
      ]);
      setReceipts(r.receipts || []);
      setAnalytics(a);
      // First load defaults to All time (the grand total of every receipt). Keep the
      // backend's latest year/month as the baseline for when the user switches to
      // Month/Year with the period control.
      if (!periodSel && a.period) {
        setPeriodSel({
          granularity: "all",
          year: a.period.year,
          month: a.period.month,
        });
      }
    } catch {
      /* backend not ready yet — leave last-known state */
    }
  }, [periodSel]);

  useEffect(() => {
    const h = new Date().getHours();
    setGreeting(
      h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening",
    );
    setToday(
      new Date().toLocaleDateString(undefined, {
        month: "long",
        day: "numeric",
      }),
    );
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    if (chatBodyRef.current)
      chatBodyRef.current.scrollTop = chatBodyRef.current.scrollHeight;
  }, [msgs, typing]);

  const flashToast = (m: string) => {
    setToast(m);
    window.setTimeout(() => setToast(""), 2600);
  };

  // ---- upload / OCR (real /extract/batch) ----
  // Files are sent in chunks to the batch endpoint, which expands PDFs to one
  // receipt per page and processes each chunk with server-side concurrency. We
  // send one chunk at a time (so we never oversubscribe the vision model) and
  // update the UI as each chunk returns — this is what makes a large drop of
  // images or a multi-hundred-page PDF import tractable instead of one-at-a-time.
  const CLIENT_CHUNK = 12;
  const processFiles = async (files: File[]) => {
    if (!files.length) return;
    setBatch(files.map((f) => ({ name: f.name, status: "reading" as const })));
    const added: number[] = [];

    for (let start = 0; start < files.length; start += CLIENT_CHUNK) {
      const chunk = files.slice(start, start + CLIENT_CHUNK);
      const fd = new FormData();
      chunk.forEach((f) => fd.append("files", f));
      try {
        const res = await fetch("/api/extract/batch", { method: "POST", body: fd });
        // Parse defensively: a slow/overloaded endpoint can return a non-JSON
        // proxy error body instead of JSON.
        const rawText = await res.text();
        let j: any = {};
        try {
          j = rawText ? JSON.parse(rawText) : {};
        } catch {
          /* non-JSON error body */
        }
        if (!res.ok) {
          throw new Error(
            j.detail ||
              (res.status >= 500
                ? "The model took too long to read these receipts (it may be busy). Try again in a moment."
                : rawText.slice(0, 160) || res.statusText),
          );
        }
        const results: any[] = j.results || [];
        chunk.forEach((f, ci) => {
          const idx = start + ci;
          // Results link back by source filename; a PDF yields several pages.
          const mine = results.filter((r) => r.source_file === f.name);
          const ok = mine.filter((r) => !r.error && r.receipt_id);
          ok.forEach((r) => added.push(r.receipt_id));
          setBatch((prev) => {
            const next = [...prev];
            if (ok.length === 0) {
              next[idx] = {
                name: f.name,
                status: "error",
                error: mine[0]?.error || "Failed to read",
              };
            } else {
              const first = ok[0].data || {};
              const pages = mine.length;
              next[idx] = {
                name: pages > 1 ? `${f.name} · ${ok.length}/${pages} pages` : f.name,
                status: "done",
                id: ok[0].receipt_id,
                merchant: first.vendor_name || f.name,
                category: first.category || "Other",
                amount: pages > 1
                  ? ok.reduce((s, r) => s + (r.data?.total_amount || 0), 0)
                  : (first.total_amount ?? 0),
                currency: first.currency,
                needsReview: ok.some((r) => r.needs_review),
                confidence:
                  typeof ok[0].confidence?.overall === "number"
                    ? ok[0].confidence.overall
                    : undefined,
              };
            }
            return next;
          });
        });
      } catch (e: any) {
        chunk.forEach((f, ci) => {
          const idx = start + ci;
          setBatch((prev) => {
            const next = [...prev];
            next[idx] = { name: f.name, status: "error", error: e?.message || "Failed to read" };
            return next;
          });
        });
      }
    }

    const uniq = Array.from(new Set(added));
    setNewIds(uniq);
    window.setTimeout(() => setNewIds([]), 700);

    // Reflect the upload in the dashboard's grand total: switch to All time so the
    // new receipt is counted regardless of its date. Changing periodSel re-runs
    // refresh() via its effect.
    setPeriodSel((p) => ({
      granularity: "all",
      year: p?.year ?? new Date().getFullYear(),
      month: p?.month ?? new Date().getMonth() + 1,
    }));
    const ok = uniq.length;
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

  const saveBudget = async (category: string, limit: number) => {
    try {
      await fetch("/api/budgets", {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          category,
          monthly_limit: limit,
          currency: analytics?.currency,
        }),
      });
      await refresh();
      flashToast(`${category} budget set`);
    } catch {
      flashToast("Couldn't save that budget");
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

  // ---- chat (streaming ReAct agent — shows the bot's reasoning) ----
  const seedChat = () => {
    if (seeded) return;
    setSeeded(true);
    setMsgs([
      {
        who: "bot",
        text: "Hi 👋 I'm your receipt assistant. Ask me anything about your spending — I'll show you my reasoning as I look it up.",
      },
    ]);
  };
  const openChat = () => {
    setChatOpen(true);
    seedChat();
  };

  const ask = async (q: string) => {
    q = q.trim();
    if (!q || typing) return;
    // Snapshot the conversation so far (before this question) so the agent can
    // resolve follow-ups like "what did each of those cost".
    const history = msgs
      .filter((m) => m.text)
      .slice(-10)
      .map((m) => ({
        role: m.who === "me" ? "user" : "assistant",
        text: m.text,
      }));
    // Append the user's message plus an empty bot bubble we fill in as events stream.
    setMsgs((m) => [
      ...m,
      { who: "me", text: q },
      { who: "bot", text: "", steps: [], thinking: true },
    ]);
    setChatText("");
    setTyping(true);

    // Patch the most recent bot message in place as reasoning events arrive.
    const patchBot = (fn: (b: ChatMsg) => ChatMsg) =>
      setMsgs((m) => {
        const copy = m.slice();
        for (let i = copy.length - 1; i >= 0; i--) {
          if (copy[i].who === "bot") {
            copy[i] = fn(copy[i]);
            break;
          }
        }
        return copy;
      });

    let curThought = "";
    const handle = (ev: any) => {
      if (ev.type === "token") {
        curThought += ev.text;
        const shown = thoughtOnly(curThought);
        patchBot((b) => {
          const steps = (b.steps || []).slice();
          const last = steps[steps.length - 1];
          if (last && last.kind === "thought" && last.live) {
            steps[steps.length - 1] = { ...last, text: shown };
          } else if (shown) {
            steps.push({ kind: "thought", text: shown, live: true });
          }
          return { ...b, steps };
        });
      } else if (ev.type === "action") {
        patchBot((b) => {
          const steps = (b.steps || []).map((s) =>
            s.live ? { ...s, live: false } : s,
          );
          steps.push({ kind: "action", tool: ev.tool, text: ev.input });
          return { ...b, steps };
        });
        curThought = "";
      } else if (ev.type === "observation") {
        patchBot((b) => ({
          ...b,
          steps: [
            ...(b.steps || []),
            { kind: "observation", tool: ev.tool, text: obsSummary(ev) },
          ],
        }));
      } else if (ev.type === "final") {
        const nCalls = (ev.steps || []).filter((s: any) => s.tool).length;
        patchBot((b) => ({
          ...b,
          text: ev.answer || "I couldn't find an answer for that.",
          thinking: false,
          steps: (b.steps || []).map((s) =>
            s.live ? { ...s, live: false } : s,
          ),
          cite: nCalls
            ? `reasoned · ${nCalls} tool call${nCalls === 1 ? "" : "s"}`
            : undefined,
        }));
      } else if (ev.type === "clarify") {
        // The agent is unsure and is asking the user a question instead of guessing.
        patchBot((b) => ({
          ...b,
          text: ev.question || "Could you clarify what you mean?",
          thinking: false,
          clarify: true,
          steps: (b.steps || []).map((s) =>
            s.live ? { ...s, live: false } : s,
          ),
        }));
      } else if (ev.type === "error") {
        patchBot((b) => ({
          ...b,
          err: true,
          thinking: false,
          text: `Something went wrong: ${
            ev.message || "the agent didn't respond"
          }.`,
        }));
      }
    };

    try {
      const res = await fetch("/api/agent/stream", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ question: q, history }),
      });
      if (!res.ok || !res.body) {
        const detail = await res.text().catch(() => "");
        throw new Error(detail || res.statusText);
      }
      // Parse the Server-Sent Events stream frame by frame.
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let idx: number;
        while ((idx = buf.indexOf("\n\n")) >= 0) {
          const frame = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          const line = frame.split("\n").find((l) => l.startsWith("data:"));
          if (line) {
            try {
              handle(JSON.parse(line.slice(5).trim()));
            } catch {
              /* ignore partial */
            }
          }
        }
      }
      // Safety net: if the stream ended without a final/error, don't leave it spinning.
      patchBot((b) =>
        b.thinking
          ? {
              ...b,
              thinking: false,
              text: b.text || "I couldn't find an answer for that.",
            }
          : b,
      );
    } catch (e: any) {
      patchBot((b) => ({
        ...b,
        err: true,
        thinking: false,
        text: `Something went wrong: ${
          e?.message || "the agent didn't respond"
        }.`,
      }));
    } finally {
      setTyping(false);
    }
  };

  const toggleTheme = () => {
    const root = document.documentElement;
    const cur =
      root.getAttribute("data-theme") ||
      (window.matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light");
    root.setAttribute("data-theme", cur === "dark" ? "light" : "dark");
  };

  // ---- derived ----
  const cur = analytics?.currency;
  const byCat = analytics?.by_category || {};
  const catTotal = Object.values(byCat).reduce((s, v) => s + v, 0);
  const donutCats = [
    ...CAT_ORDER.filter((c) => byCat[c] > 0),
    ...Object.keys(byCat).filter(
      (c) => !CAT_ORDER.includes(c as any) && byCat[c] > 0,
    ),
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
  const periodLabel = analytics?.period.label || "this period";

  const pastMonths = Array.from(
    new Set(receipts.map((r) => monthKey(r.receipt_date))),
  )
    .sort()
    .reverse();
  const filtered =
    pastMonth === "All months"
      ? receipts
      : receipts.filter(
          (r) => monthLabel(monthKey(r.receipt_date)) === pastMonth,
        );
  const groupMonths = Array.from(
    new Set(filtered.map((r) => monthKey(r.receipt_date))),
  )
    .sort()
    .reverse();

  const chips = [
    "How much did I spend?",
    "Top category?",
    "My biggest purchase",
    "Food spending",
  ];
  const savedInBatch = batch.filter((b) => b.status === "done").length;

  return (
    <>
      <main>
        <header>
          <div>
            <h1>{greeting}</h1>
            <p className="subhead">Here&apos;s your cashflow · {today}</p>
          </div>
          <div className="header-actions">
            <button
              className="icon-btn"
              onClick={toggleTheme}
              title="Toggle theme"
              aria-label="Toggle theme"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
              </svg>
            </button>
            <button className="btn-ghost" onClick={() => setIncomeOpen(true)}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path d="M12 5v14M5 12h14" />
              </svg>
              Income
            </button>
            <button className="btn-primary" onClick={openPanel}>
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path d="M12 5v14M5 12h14" />
              </svg>
              Add receipt
            </button>
          </div>
        </header>

        {/* Period selector — scopes every panel below */}
        {analytics && periodSel && (
          <PeriodControl
            period={analytics.period}
            onChange={(next) => setPeriodSel(next)}
          />
        )}

        {/* Overview cards with period-over-period deltas */}
        <StatTiles a={analytics} />

        {/* Cashflow over time */}
        <section className="card wide">
          <div className="card-head">
            <p className="card-title">Cashflow over time</p>
            <div className="cf-legend">
              <span>
                <i className="sw" style={{ background: "var(--positive)" }} />
                Income
              </span>
              <span>
                <i
                  className="sw inset"
                  style={{ background: "var(--accent)" }}
                />
                Expense
              </span>
            </div>
          </div>
          {analytics && analytics.bars.length > 0 ? (
            <CashflowChart
              bars={analytics.bars}
              currency={analytics.currency}
              focusKey={analytics.focus_key}
            />
          ) : (
            <div className="empty">
              <p className="h">No activity in {periodLabel}</p>
              <p className="s">
                Add a receipt or some income, or pick another period above.
              </p>
            </div>
          )}
        </section>

        {/* Category + budgets (both scoped to the selected period) */}
        <section className="band">
          <div className="card">
            <div className="card-head">
              <p className="card-title">Spending by category · {periodLabel}</p>
            </div>
            <div className="donut-wrap">
              <div className="donut" style={{ background: donutBg }}>
                <div className="donut-hole">
                  <div>
                    <p className="k">Spent</p>
                    <p className="v num">{money(catTotal, cur, 0)}</p>
                  </div>
                </div>
              </div>
              <ul className="legend">
                {CAT_ORDER.map((c) => {
                  const pct =
                    catTotal > 0
                      ? Math.round(((byCat[c] || 0) / catTotal) * 100)
                      : 0;
                  return (
                    <li key={c}>
                      <span
                        className="dot"
                        style={{ background: catMeta(c).color }}
                      />
                      <span className="name">{c}</span>
                      <span className="pct num">{pct}%</span>
                    </li>
                  );
                })}
              </ul>
            </div>
          </div>

          <BudgetsCard
            budgets={analytics?.budgets || []}
            currency={analytics?.currency ?? null}
            monthLabel={periodLabel}
            onSave={saveBudget}
          />
        </section>

        {/* Top vendors + recent transactions */}
        <section className="band">
          <div className="card">
            <div className="card-head">
              <p className="card-title">Top vendors</p>
            </div>
            <TopVendors
              vendors={analytics?.top_vendors || []}
              currency={analytics?.currency ?? null}
            />
          </div>

          <div className="card">
            <div className="card-head">
              <p className="card-title">Recent transactions</p>
              <button className="link" onClick={() => setShowPast(true)}>
                View all
              </button>
            </div>
            {recent.length === 0 ? (
              <div className="empty">
                <p className="h">Nothing logged yet</p>
                <p className="s">
                  Scan a receipt with “Add” and it&apos;ll show up here.
                </p>
              </div>
            ) : (
              <ul className="txn-list">
                {recent.map((t) => (
                  <TxnRow
                    key={t.id}
                    r={t}
                    isNew={newIds.includes(t.id)}
                    onDelete={deleteReceipt}
                  />
                ))}
              </ul>
            )}
          </div>
        </section>
      </main>

      {/* Income slide-over */}
      <IncomePanel
        open={incomeOpen}
        currency={analytics?.currency ?? null}
        onClose={() => setIncomeOpen(false)}
        onChanged={refresh}
        flashToast={flashToast}
      />

      {/* Past receipts modal */}
      <div
        className={"scrim" + (showPast ? " open" : "")}
        onClick={() => setShowPast(false)}
      />
      <div
        className={"modal" + (showPast ? " open" : "")}
        role="dialog"
        aria-modal="true"
        aria-label="Past receipts"
      >
        <div className="modal-head">
          <p className="section-eyebrow">Past receipts</p>
          <button
            className="close-x"
            onClick={() => setShowPast(false)}
            aria-label="Close"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path d="M6 6l12 12M18 6 6 18" />
            </svg>
          </button>
        </div>
        <div className="modal-body">
          {receipts.length === 0 ? (
            <p className="s" style={{ color: "var(--ink-3)", fontSize: 14 }}>
              No receipts yet.
            </p>
          ) : (
            <>
              <div className="month-filter" style={{ maxWidth: 200 }}>
                <Select value={pastMonth} onChange={(e) => setPastMonth(e.target.value)}>
                  <option>All months</option>
                  {pastMonths.map((m) => (
                    <option key={m}>{monthLabel(m)}</option>
                  ))}
                </Select>
              </div>
              {groupMonths.map((m) => {
                const group = filtered
                  .filter((r) => monthKey(r.receipt_date) === m)
                  .sort((a, b) =>
                    (b.receipt_date || "").localeCompare(a.receipt_date || ""),
                  );
                const subtotal = group.reduce(
                  (s, r) => s + (r.total_amount || 0),
                  0,
                );
                const cur = group.find((r) => r.currency)?.currency;
                return (
                  <div key={m} className="month-group">
                    <p className="month-head">
                      {monthLabel(m)} — {group.length} receipt
                      {group.length > 1 ? "s" : ""} · {money(subtotal, cur)}
                    </p>
                    {group.map((r) => (
                      <div key={r.id} className="past-row">
                        <div className="txn-icon">
                          {catMeta(r.category).emoji}
                        </div>
                        <div className="p-body">
                          <div className="p-merch">
                            #{r.id} · {r.vendor_name || "Unknown merchant"}
                          </div>
                          <div className="p-meta">
                            {r.category || "Other"} ·{" "}
                            {r.receipt_date || "Undated"}
                            <ConfidenceBadge value={r.confidence} />
                          </div>
                        </div>
                        <span className="p-amt num">
                          {money(r.total_amount, r.currency)}
                        </span>
                        <button
                          className="p-del"
                          title="Delete (also removes from search memory)"
                          onClick={() => deleteReceipt(r.id)}
                        >
                          <svg
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                          >
                            <path d="M6 6l12 12M18 6 6 18" />
                          </svg>
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
      <div
        className={"scrim" + (panelOpen ? " open" : "")}
        onClick={closePanel}
      />
      <div
        className={"panel" + (panelOpen ? " open" : "")}
        role="dialog"
        aria-modal="true"
        aria-label="Add receipts"
      >
        <div className="panel-head">
          <h2>Scan receipts</h2>
          <button
            className="icon-btn"
            style={{ width: 34, height: 34 }}
            onClick={closePanel}
            aria-label="Close"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path d="M6 6l12 12M18 6 6 18" />
            </svg>
          </button>
        </div>
        <p className="panel-desc">
          Drop receipt images or PDFs — the vision model reads every page and
          files each one automatically.
        </p>

        <div className="panel-scroll">
          <input
            ref={fileRef}
            type="file"
            accept="image/*,application/pdf"
            multiple
            hidden
            onChange={(e) => onFiles(e.target.files)}
          />
          <div
            className={"dropzone" + (dragging ? " drag" : "")}
            onClick={onPick}
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={(e) => {
              e.preventDefault();
              setDragging(false);
            }}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              onFiles(e.dataTransfer.files);
            }}
          >
            <div className="dz-icon">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path d="M12 16V4M12 4 8 8M12 4l4 4" />
                <path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" />
              </svg>
            </div>
            <div className="dz-title">Drop images or click to browse</div>
            <div className="dz-sub">PNG · JPG · WEBP</div>
          </div>

          {batch.length > 0 && (
            <>
              <p className="batch-head">
                {savedInBatch > 0
                  ? `${savedInBatch} of ${batch.length} filed`
                  : `Reading ${batch.length} receipt${
                      batch.length > 1 ? "s" : ""
                    }…`}
              </p>
              <div className="batch-list">
                {batch.map((b, i) => (
                  <div
                    key={i}
                    className={
                      "batch-row" + (b.status === "error" ? " error" : "")
                    }
                  >
                    {b.status === "reading" ? (
                      <div className="b-spin-wrap">
                        <div className="dz-spin" />
                      </div>
                    ) : (
                      <span className="b-emoji">
                        {b.status === "error"
                          ? "⚠️"
                          : catMeta(b.category).emoji}
                      </span>
                    )}
                    <div className="b-body">
                      {b.status === "done" ? (
                        <>
                          <div className="b-merch">
                            {b.merchant}
                            {b.needsReview && (
                              <span className="b-review">needs review</span>
                            )}
                            <ConfidenceBadge value={b.confidence} />
                          </div>
                          <span
                            className="b-cat"
                            style={{ background: catMeta(b.category).color }}
                          >
                            {b.category}
                          </span>
                        </>
                      ) : b.status === "error" ? (
                        <>
                          <div className="b-merch">{b.name}</div>
                          <div className="b-err">{b.error}</div>
                        </>
                      ) : (
                        <>
                          <div className="b-merch">{b.name}</div>
                          <div className="b-file">
                            Reading with the vision model… (can take a few
                            minutes)
                          </div>
                        </>
                      )}
                    </div>
                    {b.status === "done" && (
                      <span className="b-amt num">
                        {money(b.amount, b.currency)}
                      </span>
                    )}
                    {b.status === "done" && b.id != null && (
                      <button
                        className="b-del"
                        title="Delete"
                        onClick={() => deleteReceipt(b.id!, true)}
                      >
                        <svg
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                        >
                          <path d="M6 6l12 12M18 6 6 18" />
                        </svg>
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </>
          )}
        </div>

        <div className="panel-foot">
          <button className="btn-save" onClick={closePanel}>
            Done
          </button>
        </div>
      </div>

      {/* Toast */}
      <div className={"toast" + (toast ? " show" : "")}>
        <span className="tdot" />
        {toast}
      </div>

      {/* Robot RAG assistant */}
      <button
        className="robot-fab"
        onClick={() => (chatOpen ? setChatOpen(false) : openChat())}
        aria-label="Ask the assistant"
      >
        {!chatOpen && <span className="ping" />}
        <span className="float">
          <RobotSVG />
        </span>
      </button>

      <div
        className={"chat" + (chatOpen ? " open" : "")}
        role="dialog"
        aria-label="Receipt assistant"
      >
        <div className="chat-head">
          <div className="chat-ava">
            <RobotSVG eye="var(--accent)" body="var(--accent-wash)" />
          </div>
          <div>
            <div className="ct">Receipt Assistant</div>
            <div className="cs">
              <span className="live" />
              ReAct agent · shows its reasoning
            </div>
          </div>
          <button
            className="close-x"
            onClick={() => setChatOpen(false)}
            aria-label="Close chat"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path d="M6 6l12 12M18 6 6 18" />
            </svg>
          </button>
        </div>
        <div className="chat-body" ref={chatBodyRef}>
          {msgs.map((m, i) => {
            const steps = m.steps || [];
            const nCalls = steps.filter((s) => s.kind === "action").length;
            return (
              <div key={i} className={"msg " + m.who + (m.err ? " err" : "")}>
                {m.who === "bot" && steps.length > 0 && (
                  <details className="reason" open={m.thinking || undefined}>
                    <summary>
                      {m.thinking
                        ? "Thinking…"
                        : `Reasoning · ${nCalls} tool call${
                            nCalls === 1 ? "" : "s"
                          }`}
                    </summary>
                    <div className="rsteps">
                      {steps.map((s, j) => (
                        <div
                          key={j}
                          className={
                            "rstep " + s.kind + (s.live ? " live" : "")
                          }
                        >
                          <span className="ri">
                            {s.kind === "thought"
                              ? "🧠"
                              : s.kind === "action"
                              ? "🔧"
                              : "↳"}
                          </span>
                          <span className="rt">
                            {s.kind === "action" ? (
                              <>
                                <b>{s.tool}</b> · {s.text}
                              </>
                            ) : (
                              s.text || "…"
                            )}
                          </span>
                        </div>
                      ))}
                    </div>
                  </details>
                )}
                {m.thinking && !m.text && steps.length === 0 && (
                  <span className="typing inline">
                    <span />
                    <span />
                    <span />
                  </span>
                )}
                {m.clarify && (
                  <span className="clarify-tag">❓ Quick question</span>
                )}
                {m.text && <div className="ans">{m.text}</div>}
                {m.cite && <span className="cite">📎 {m.cite}</span>}
              </div>
            );
          })}
        </div>
        {msgs.length <= 1 && !typing && (
          <div className="chips">
            {chips.map((c) => (
              <button key={c} className="chip" onClick={() => ask(c)}>
                {c}
              </button>
            ))}
          </div>
        )}
        <div className="chat-input">
          <input
            value={chatText}
            onChange={(e) => setChatText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") ask(chatText);
            }}
            placeholder="Ask about your spending…"
          />
          <button
            className="send"
            disabled={typing}
            onClick={() => ask(chatText)}
            aria-label="Send"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
              <path d="M22 2 11 13M22 2l-7 20-4-9-9-4 20-7z" />
            </svg>
          </button>
        </div>
      </div>
    </>
  );
}
