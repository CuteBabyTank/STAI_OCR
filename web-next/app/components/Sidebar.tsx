"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";

// Shared left sidebar. On the dashboard the Income/Ask items open in-page panels
// (callbacks passed in); on other pages they fall back to links to the dashboard.
export default function Sidebar({
  onIncome,
  onChat,
}: {
  onIncome?: () => void;
  onChat?: () => void;
}) {
  const path = usePathname() || "/";
  const onDash = path === "/";
  const onReceipts = path.startsWith("/receipts");

  const IncomeIcon = (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M12 1v22M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" /></svg>
  );
  const ChatIcon = (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></svg>
  );

  return (
    <aside className="sidebar">
      <div className="sidebar-inner">
        <div className="brand">
          <div className="brand-mark">◆</div>
          <span className="brand-name">Receipt Ledger</span>
        </div>
        <nav>
          <Link href="/" className={"nav-item" + (onDash ? " active" : "")}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><rect x="3" y="3" width="7" height="9" rx="1.5" /><rect x="14" y="3" width="7" height="5" rx="1.5" /><rect x="14" y="12" width="7" height="9" rx="1.5" /><rect x="3" y="16" width="7" height="5" rx="1.5" /></svg>Overview
          </Link>
          <Link href="/receipts" className={"nav-item" + (onReceipts ? " active" : "")}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M6 2h9l5 5v14a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1z" /><path d="M14 2v6h6M8 13h8M8 17h6" /></svg>Receipts
          </Link>
          {onIncome ? (
            <button className="nav-item" onClick={onIncome}>{IncomeIcon}Income</button>
          ) : (
            <Link href="/" className="nav-item">{IncomeIcon}Income</Link>
          )}
          {onChat ? (
            <button className="nav-item" onClick={onChat}>{ChatIcon}Ask receipts</button>
          ) : (
            <Link href="/" className="nav-item">{ChatIcon}Ask receipts</Link>
          )}
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
  );
}
