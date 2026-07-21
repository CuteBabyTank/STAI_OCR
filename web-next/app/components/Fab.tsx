"use client";
// Floating action button + popover (PRD §2.1). Opens the Quick chat / Transfer /
// Income / Expense flows. It owns the shared accounts + categories collections so
// each modal doesn't refetch; pages pass `refreshKey`/`onChange` to stay in sync.
import { useCallback, useEffect, useState } from "react";
import type { Account, TxnCategory } from "../lib/types";
import { listAccounts, listCategories } from "../lib/api";
import { useRefresh } from "../lib/useRefresh";
import { ExpenseModal, IncomeModal, TransferModal } from "./TransactionModals";
import QuickChatModal from "./QuickChatModal";

type Flow = "chat" | "transfer" | "income" | "expense" | null;

export default function Fab({ onChange, hidden }: { onChange?: () => void; hidden?: boolean }) {
  const [menu, setMenu] = useState(false);
  const [flow, setFlow] = useState<Flow>(null);
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [categories, setCategories] = useState<TxnCategory[]>([]);

  const load = useCallback(() => {
    listAccounts().then(setAccounts).catch(() => setAccounts([]));
    listCategories().then(setCategories).catch(() => setCategories([]));
  }, []);
  useEffect(() => {
    load();
  }, [load]);
  // Stay in sync in real time: reload whenever any view mutates the ledger
  // (e.g. an account added on the Wallet page), so the Transfer / Quick-chat
  // modals always see the current accounts — including detecting 2+ debit
  // accounts as soon as they exist, without a page reload.
  useRefresh(load);

  // Keyboard shortcut: Cmd+K / Alt+K opens Quick chat (PRD §2.1).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.altKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setFlow("chat");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const saved = () => {
    load();
    onChange?.();
  };
  const open = (f: Flow) => {
    // Pull the latest accounts/categories the instant a flow opens so a modal
    // never renders against a stale snapshot (e.g. Transfer seeing <2 accounts).
    load();
    setFlow(f);
    setMenu(false);
  };

  const MENU = [
    { flow: "chat" as const, label: "Quick chat", color: "var(--accent)",
      icon: "M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" },
    { flow: "transfer" as const, label: "Transfer", color: "#0EA5E9",
      icon: "M7 16V4m0 0L3 8m4-4 4 4M17 8v12m0 0 4-4m-4 4-4-4" },
    { flow: "income" as const, label: "Income", color: "var(--positive)",
      icon: "M12 5v14m0-14 5 5m-5-5-5 5" },
    { flow: "expense" as const, label: "Expense", color: "var(--negative)",
      icon: "M12 19V5m0 14 5-5m-5 5-5-5" },
  ];

  // Stay mounted (so accounts/categories aren't refetched) but hide while the
  // chat panel occupies the corner.
  return (
    <div className="fab-wrap" style={hidden ? { display: "none" } : undefined}>
      {menu && (
        <div className="fab-menu" onMouseLeave={() => setMenu(false)}>
          {MENU.map((m) => (
            <button key={m.label} className="fab-item" onClick={() => open(m.flow)}>
              <svg viewBox="0 0 24 24" fill="none" stroke={m.color}>
                <path d={m.icon} strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              {m.label}
            </button>
          ))}
        </div>
      )}
      <button className={"fab" + (menu ? " open" : "")} onClick={() => setMenu((v) => !v)} aria-label="Quick add">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
          <path d="M12 5v14M5 12h14" strokeLinecap="round" />
        </svg>
      </button>

      {flow === "chat" && (
        <QuickChatModal accounts={accounts} categories={categories} onClose={() => setFlow(null)} onSaved={saved} />
      )}
      {flow === "expense" && (
        <ExpenseModal accounts={accounts} categories={categories} onClose={() => setFlow(null)} onSaved={saved} />
      )}
      {flow === "income" && (
        <IncomeModal accounts={accounts} onClose={() => setFlow(null)} onSaved={saved} />
      )}
      {flow === "transfer" && (
        <TransferModal accounts={accounts} onClose={() => setFlow(null)} onSaved={saved} />
      )}
    </div>
  );
}
