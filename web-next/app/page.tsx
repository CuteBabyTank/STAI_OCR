"use client";
// Home (PRD §3): the budget-tracker dashboard — greeting, this-month in/out,
// wallet groupings, and recent ledger activity. The receipt-OCR command center
// now lives at /scan; this view is the money overview.
import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import type { Account, Analytics, Granularity, NetWorth, Receipt, Transaction } from "./lib/types";
import { money, signedMoney, fmtDate, acctMeta } from "./lib/format";
import { listAccounts, getNetWorth, listTransactions, listReceipts } from "./lib/api";
import { computePeriodTotals } from "./lib/periodTotals";
import { mergeRecentActivity } from "./lib/recentActivity";
import { useRefresh } from "./lib/useRefresh";
import StatTiles from "./components/StatTiles";
import CashflowChart from "./components/CashflowChart";
import TopVendors from "./components/TopVendors";
import PeriodControl from "./components/PeriodControl";

function greeting(hour: number) {
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

// Accounts grouped into the three wallet buckets from PRD §3.
const GROUPS: { key: string; label: string; types: string[] }[] = [
  { key: "everyday", label: "Everyday balances", types: ["debit"] },
  { key: "credit", label: "Credit and dues", types: ["credit", "loans"] },
  { key: "assets", label: "Assets and investing", types: ["assets", "stocks", "crypto"] },
];

export default function Home() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [nw, setNw] = useState<NetWorth | null>(null);
  // The full stores, not just the 8-row recent slice: both the "Recent
  // transactions" feed and the top out/in tiles need to merge in receipts
  // that were logged from chat and never became a transaction.
  const [allTxns, setAllTxns] = useState<Transaction[]>([]);
  const [allReceipts, setAllReceipts] = useState<Receipt[]>([]);
  const [analytics, setAnalytics] = useState<Analytics | null>(null);
  const [name, setName] = useState("");
  const [greet, setGreet] = useState("Welcome"); // set client-side to avoid SSR/tz mismatch
  const [loading, setLoading] = useState(true);

  // Which month the Spending overview is scoped to. `null` = let the API pick its
  // default (the latest period with activity), which is what should be on screen
  // before the user has touched the arrows. Once they step, this holds their choice.
  const [periodSel, setPeriodSel] = useState<
    { granularity: Granularity; year: number; month: number } | null
  >(null);

  const loadAnalytics = useCallback(() => {
    const qs = periodSel
      ? `?granularity=${periodSel.granularity}&year=${periodSel.year}&month=${periodSel.month}`
      : "";
    fetch(`/api/analytics${qs}`)
      .then((r) => r.json())
      .then(setAnalytics)
      .catch(() => {});
  }, [periodSel]);

  const load = useCallback(() => {
    Promise.all([listAccounts(), getNetWorth(), listTransactions({ limit: 2000 }), listReceipts(2000)])
      .then(([a, n, t, r]) => {
        setAccounts(a);
        setNw(n);
        setAllTxns(t);
        setAllReceipts(r);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  // Analytics loads on its own, keyed to the selected period: stepping months must
  // not re-pull accounts, net worth and transactions, none of which it scopes — and
  // `load` must not re-pull analytics, or mounting would fetch it twice.
  useEffect(() => {
    loadAnalytics();
  }, [loadAnalytics]);
  useRefresh(loadAnalytics); // a receipt logged from chat changes these panels too
  useEffect(() => {
    load();
    setName(localStorage.getItem("profile-name") || "");
    setGreet(greeting(new Date().getHours()));
  }, [load]);
  useRefresh(load); // reload after the shared FAB saves a transaction

  // In/out for the current period, scoped to this calendar month or this
  // calendar year depending on topGranularity. Defaults to year. Merges the
  // transactions and receipts stores (see computePeriodTotals) so a receipt
  // logged from chat — which never becomes a transaction — still counts here,
  // matching the Spending overview panel below.
  const [topGranularity, setTopGranularity] = useState<"month" | "year">("year");
  const periodTotals = useMemo(
    () => computePeriodTotals(allTxns, allReceipts, topGranularity),
    [allTxns, allReceipts, topGranularity]
  );

  // Same merge for the "Recent transactions" feed: a chat-logged receipt has
  // no account, so it can't move a wallet balance, but it should still show
  // up as an entry (see mergeRecentActivity).
  const txns = useMemo(
    () => mergeRecentActivity(allTxns, allReceipts, 8, topGranularity),
    [allTxns, allReceipts, topGranularity]
  );

  return (
    <>
      <main>
        <header>
          <div>
            <h1>{greet}{name ? `, ${name}` : ""}! 👋</h1>
            <p className="subhead">Here's where your money stands today.</p>
          </div>
          {nw && (
            <div style={{ textAlign: "right" }}>
              <div className="stat-label">Net worth</div>
              <div style={{ fontSize: 22, fontWeight: 680, letterSpacing: "-.02em" }}>{money(nw.net)}</div>
            </div>
          )}
        </header>

        {/* Period summary */}
        <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 10 }}>
          <div className="seg">
            <button
              className={"seg-btn" + (topGranularity === "month" ? " on" : "")}
              onClick={() => setTopGranularity("month")}
            >
              Month
            </button>
            <button
              className={"seg-btn" + (topGranularity === "year" ? " on" : "")}
              onClick={() => setTopGranularity("year")}
            >
              Year
            </button>
          </div>
        </div>
        <div className="stat-grid" style={{ gridTemplateColumns: "1fr 1fr" }}>
          <div className="card">
            <p className="stat-label">This {topGranularity} out</p>
            <div className="stat-value" style={{ color: "var(--negative)" }}>{money(periodTotals.out)}</div>
          </div>
          <div className="card">
            <p className="stat-label">This {topGranularity} in</p>
            <div className="stat-value" style={{ color: "var(--positive)" }}>{money(periodTotals.inn)}</div>
          </div>
        </div>

        <div className="band">
          {/* Wallet groupings */}
          <div className="card">
            <div className="card-head">
              <p className="card-title">Wallet</p>
              <Link href="/wallet" className="link">View all</Link>
            </div>
            {loading ? (
              <div className="empty-note">Loading…</div>
            ) : accounts.length === 0 ? (
              <div className="empty-note">No accounts yet. <Link href="/wallet" className="link">Add one</Link>.</div>
            ) : (
              GROUPS.map((g) => {
                const items = accounts.filter((a) => g.types.includes(a.type));
                if (!items.length) return null;
                const sum = items.reduce((s, a) => s + a.balance, 0);
                return (
                  <div key={g.key} style={{ marginBottom: 14 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12.5, color: "var(--ink-3)", marginBottom: 6 }}>
                      <span>{g.label}</span>
                      <span className="num">{money(sum)}</span>
                    </div>
                    {items.map((a) => (
                      <div key={a.id} style={{ display: "flex", alignItems: "center", gap: 10, padding: "6px 0" }}>
                        <span style={{ width: 8, height: 8, borderRadius: "50%", background: acctMeta(a.type).color }} />
                        <span style={{ flex: 1, fontSize: 13.5 }}>{a.name}</span>
                        <span className="num" style={{ fontSize: 13.5, fontWeight: 560, color: a.balance < 0 ? "var(--negative)" : "var(--ink)" }}>
                          {money(a.balance, a.currency)}
                        </span>
                      </div>
                    ))}
                  </div>
                );
              })
            )}
          </div>

          {/* Recent transactions */}
          <div className="card">
            <div className="card-head">
              <p className="card-title">Recent transactions</p>
              <Link href="/history" className="link">History</Link>
            </div>
            {loading ? (
              <div className="empty-note">Loading…</div>
            ) : txns.length === 0 ? (
              <div className="empty-note">
                {allTxns.length === 0 && allReceipts.length === 0
                  ? "No transactions yet. Use the + button to add one."
                  : `No transactions this ${topGranularity}.`}
              </div>
            ) : (
              txns.map((t) => {
                const sign = t.kind === "income" ? "+" : t.kind === "expense" ? "-" : undefined;
                const cls = t.kind === "income" ? "amt-pos" : t.kind === "expense" ? "amt-neg" : "";
                return (
                  <div key={t.id} className="ledger-row" style={{ padding: "9px 0" }}>
                    <div className="ledger-main">
                      <div className="ledger-title">{t.title}</div>
                      <div className="ledger-sub">{t.subtitle} · {fmtDate(t.date?.slice(0, 10))}</div>
                    </div>
                    <div className={"ledger-amt " + cls}>
                      {t.kind === "transfer" ? money(t.amount) : signedMoney(t.amount, null, sign)}
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Spending overview (receipt analytics — moved here from the scan page) */}
        <div className="card-head" style={{ marginBottom: -6 }}>
          <p className="card-title">Spending overview</p>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            {/* Scopes the three panels below only. The "This month out/in" cards
                above stay on the real current month, so their labels stay true. */}
            {analytics && (
              <PeriodControl
                period={analytics.period}
                monthOnly
                onChange={(next) => setPeriodSel(next)}
              />
            )}
            <Link href="/receipts" className="link">Receipts</Link>
          </div>
        </div>
        <StatTiles a={analytics} />
        <div className="band">
          <div className="card">
            <div className="card-head">
              <p className="card-title">Cashflow</p>
            </div>
            {analytics ? (
              <CashflowChart bars={analytics.bars} currency={analytics.currency} focusKey={analytics.focus_key} />
            ) : (
              <div className="empty-note">No receipt data yet.</div>
            )}
          </div>
          <div className="card">
            <div className="card-head">
              <p className="card-title">Top vendors</p>
            </div>
            {analytics && analytics.top_vendors.length > 0 ? (
              <TopVendors vendors={analytics.top_vendors} currency={analytics.currency} />
            ) : (
              <div className="empty-note">Add receipts to see your top vendors.</div>
            )}
          </div>
        </div>
      </main>
    </>
  );
}
