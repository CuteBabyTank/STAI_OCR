"use client";
// Floating ReAct-agent chatbot (bottom-right), app-wide. It streams the backend
// `/agent/stream` SSE endpoint — the same ReAct agent that routes between the SQL
// tool (ledger queries) and the RAG tool (semantic receipt search) — and shows
// its reasoning trace live. `open` is controlled by the parent (AppShell) so the
// quick-add FAB can step aside while the chat panel is open. Extracted from the
// scan page so every route gets the assistant, not just /scan.
import { useEffect, useRef, useState } from "react";
import { broadcastRefresh } from "../lib/useRefresh";

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
  if (d.kind === "accounts") {
    const n = (d.accounts || []).length;
    return `looked up accounts · ${n} account${n === 1 ? "" : "s"}`;
  }
  // The tools that write: name the amount and the id, so a recorded expense is
  // never a silent side effect of a chat message.
  if (d.kind === "txn") {
    const amt = Number(d.amount || 0).toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
    return `recorded expense #${d.transaction_id} · ${amt} on ${d.account}${
      d.category ? ` · ${d.category}` : ""
    }`;
  }
  // log_spend: a receipt posted to the default Cash account. Says "logged", and
  // names Cash so the dashboard can show which wallet was charged.
  if (d.kind === "receipt") {
    const amt = Number(d.amount || 0).toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
    return `logged receipt #${d.receipt_id} · ${amt}${
      d.vendor ? ` at ${d.vendor}` : ""
    }${d.account ? ` on ${d.account}` : ""}${d.category ? ` · ${d.category}` : ""}`;
  }
  if (d.kind === "note") return "already had that result";
  return String(ev.text || "").slice(0, 120);
}

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

const CHIPS = [
  "How much did I spend?",
  "Top category?",
  "My biggest purchase",
  "Food spending",
];

export default function AgentChat({
  open,
  onOpenChange,
  minimized = false,
  onMinimizedChange,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  minimized?: boolean;
  onMinimizedChange?: (v: boolean) => void;
}) {
  const [seeded, setSeeded] = useState(false);
  const [msgs, setMsgs] = useState<ChatMsg[]>([]);
  const [typing, setTyping] = useState(false);
  const [chatText, setChatText] = useState("");
  const [unread, setUnread] = useState(false);
  const chatBodyRef = useRef<HTMLDivElement>(null);
  // The SSE handler closes over the state it was created with, so a `minimized`
  // read from that closure would be whatever it was when the question was sent —
  // exactly wrong, since minimizing usually happens WHILE the answer streams.
  const minRef = useRef(minimized);
  minRef.current = minimized;

  // Restoring the panel means the user has seen whatever arrived.
  useEffect(() => {
    if (!minimized) setUnread(false);
  }, [minimized]);

  // Seed the greeting the first time the panel opens.
  useEffect(() => {
    if (open && !seeded) {
      setSeeded(true);
      setMsgs([
        {
          who: "bot",
          text: "Hi 👋 I'm your finance assistant. Ask me anything about your spending or receipts — I'll show you my reasoning as I look it up.",
        },
      ]);
    }
  }, [open, seeded]);

  // Keep the transcript pinned to the newest message.
  useEffect(() => {
    if (chatBodyRef.current)
      chatBodyRef.current.scrollTop = chatBodyRef.current.scrollHeight;
  }, [msgs, typing]);

  const ask = async (q: string) => {
    q = q.trim();
    if (!q || typing) return;
    // Snapshot the conversation so far (before this question) so the agent can
    // resolve follow-ups like "what did each of those cost".
    //
    // Matches core._HISTORY_TURNS. This slice used to be the binding constraint:
    // it capped at 10 regardless of what the server would accept, so raising the
    // server-side window alone changed nothing. The server still budgets the block
    // by characters and drops the oldest, so sending more than it can use is safe —
    // it just lets the server make the trimming decision with full information.
    const history = msgs
      .filter((m) => m.text)
      .slice(-30)
      .map((m) => ({
        role: m.who === "me" ? "user" : "assistant",
        text: m.text,
        // Marks a bubble that was a question back to the user. The backend uses it
        // to rejoin a short reply ("from Cash") with the request it answers —
        // without the flag it would have to guess from punctuation.
        clarify: !!m.clarify,
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
        if (minRef.current) setUnread(true);
        // The agent can WRITE (add_expense, record_activity, …). Every other view
        // is already subscribed to "ledger:refresh" via useRefresh, so one
        // broadcast puts the dashboard, wallet, debts and history back in sync
        // without a reload. Without this the chat confirms a payment the page
        // behind it still shows as not having happened.
        //
        // This matters most when minimized: the whole point of collapsing is to
        // watch the page, so the page had better be current.
        if ((ev.writes || []).length) broadcastRefresh();
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
        // A clarification is a question waiting on the user — the one thing they
        // must not miss while the panel is parked.
        if (minRef.current) setUnread(true);
        // A clarification can still follow a completed write (the agent recorded
        // something, then asked a follow-up). Those writes are real and the pages
        // must reflect them, so this branch broadcasts too.
        if ((ev.writes || []).length) broadcastRefresh();
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

  return (
    <>
      <button
        className="robot-fab"
        onClick={() => {
          // From minimized, the robot restores rather than closes — a collapsed
          // panel and a closed one look different, so the same button doing the
          // same thing to both would feel broken.
          if (open && minimized) onMinimizedChange?.(false);
          else onOpenChange(!open);
        }}
        aria-label={
          open && minimized ? "Expand the assistant" : "Ask the assistant"
        }
      >
        {(!open || (minimized && unread)) && <span className="ping" />}
        <span className="float">
          <RobotSVG />
        </span>
      </button>

      <div
        className={"chat" + (open ? " open" : "") + (minimized ? " min" : "")}
        role="dialog"
        aria-label="Finance assistant"
      >
        {/* Collapsed, the whole header is the restore target — a 30px chevron is a
            needlessly small hit area when the bar has nothing else to click. */}
        <div
          className="chat-head"
          onClick={minimized ? () => onMinimizedChange?.(false) : undefined}
        >
          <div className="chat-ava">
            <RobotSVG eye="var(--accent)" body="var(--accent-wash)" />
            {minimized && unread && <span className="unread" />}
          </div>
          <div>
            <div className="ct">Finance Assistant</div>
            <div className="cs">
              {minimized && unread ? (
                <span className="new">New reply · click to open</span>
              ) : minimized && typing ? (
                <>
                  <span className="live" />
                  Working on it…
                </>
              ) : (
                <>
                  <span className="live" />
                  ReAct agent · shows its reasoning
                </>
              )}
            </div>
          </div>
          <div className="head-actions">
            <button
              onClick={(e) => {
                e.stopPropagation();
                onMinimizedChange?.(!minimized);
              }}
              aria-label={minimized ? "Expand chat" : "Minimize chat"}
              aria-expanded={!minimized}
              title={minimized ? "Expand" : "Minimize"}
            >
              <svg
                className="chev"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M6 9l6 6 6-6" />
              </svg>
            </button>
            <button
              onClick={(e) => {
                e.stopPropagation();
                onOpenChange(false);
              }}
              aria-label="Close chat"
              title="Close"
            >
              <svg
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeLinecap="round"
              >
                <path d="M6 6l12 12M18 6 6 18" />
              </svg>
            </button>
          </div>
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
            {CHIPS.map((c) => (
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
