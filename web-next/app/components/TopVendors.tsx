"use client";
import type { VendorPoint } from "../lib/types";
import { money } from "../lib/format";

// "Where my money goes" — a compact horizontal bar list. A single-series magnitude
// ranking, so one accent hue + direct value labels (no legend needed).
export default function TopVendors({
  vendors, currency,
}: { vendors: VendorPoint[]; currency: string | null }) {
  if (!vendors.length) {
    return <p className="muted-note">No vendors yet — scan a receipt to see where your money goes.</p>;
  }
  const max = Math.max(...vendors.map((v) => v.total), 1);
  return (
    <ul className="vendor-list">
      {vendors.map((v) => (
        <li key={v.vendor} className="vendor-row">
          <div className="vendor-top">
            <span className="vendor-name" title={v.vendor}>{v.vendor}</span>
            <span className="vendor-amt num">{money(v.total, currency)}</span>
          </div>
          <div className="vendor-track">
            <div className="vendor-fill" style={{ width: `${(v.total / max) * 100}%` }} />
          </div>
          <span className="vendor-count">{v.count} receipt{v.count === 1 ? "" : "s"}</span>
        </li>
      ))}
    </ul>
  );
}
