"""repair_receipts.py — backfill the VAT-inflated-total fix over receipts that are
already in the ledger.

The pipeline fix in `extraction.undo_vat_added_to_total` only helps receipts read
from here on. Rows saved before it — Pepper Lunch #61 among them, whose ₱545.00
receipt was filed as ₱603.39 — keep the inflated figure, and every spend total,
category chart and agent answer built on those rows stays wrong until they are
corrected. This script applies the exact same deterministic repair to stored rows,
so there is one implementation of the rule and no chance of the two drifting.

It is conservative by the same test the pipeline uses: a row is only rewritten when
the receipt's own tax breakdown proves the VAT sits inside the subtotal AND the
stored total is exactly that subtotal plus that VAT. Anything else is reported and
left alone.

Usage (dry run — prints what it would change, writes nothing):

    python repair_receipts.py

Apply the corrections:

    python repair_receipts.py --apply

Against the ledger inside Docker (the live one; the repo copy is only the seed):

    docker compose exec api python repair_receipts.py --apply

Options:
    --db PATH    ledger to operate on (default: $LEDGER_DB_PATH, else ./ledger.db)
    --id N       restrict to a single receipt id (repeatable)
"""

from __future__ import annotations

import argparse
import os
import sys

from extraction import _symbol, undo_vat_added_to_total

_FIELDS = ("subtotal", "vatable_sales", "vat_exempt_sales", "zero_rated_sales",
           "vat_amount", "discount", "total_amount", "cash", "change")


def _row_to_extraction(row: dict, items: list[dict]) -> dict:
    """Shape a stored receipt row like the model dict the repair expects."""
    data = {k: row.get(k) for k in _FIELDS}
    data["items"] = [{"description": i.get("description"), "quantity": i.get("quantity"),
                      "unit_price": i.get("unit_price"), "amount": i.get("amount")}
                     for i in items]
    return data


def _money(value, currency: str | None) -> str:
    # ASCII only: this prints to a Windows console under cp1252 as often as to a
    # Linux one inside the container.
    if value is None:
        return "(none)"
    sym = _symbol(currency)
    try:
        f"{sym}".encode(sys.stdout.encoding or "utf-8")
    except (UnicodeEncodeError, LookupError):
        sym = f"{currency} " if currency else ""
    return f"{sym}{value:,.2f}"


def find_repairs(receipt_ids: list[int] | None = None) -> list[dict]:
    """Return one entry per receipt whose stored total double-counts its VAT."""
    import core  # imported after DB_PATH is set, so it binds the right ledger

    core.init_db()
    rows = core.list_receipts(limit=10_000)
    if receipt_ids:
        wanted = set(receipt_ids)
        rows = [r for r in rows if r["id"] in wanted]

    repairs = []
    for row in rows:
        full = core.get_receipt(row["id"]) or row
        before = _row_to_extraction(full, core.get_receipt_items(row["id"]))
        after = undo_vat_added_to_total(dict(before))
        changed = {k: after[k] for k in ("total_amount", "change")
                   if after.get(k) != before.get(k)}
        if changed:
            repairs.append({
                "id": row["id"],
                "vendor": full.get("vendor_name") or "(unknown vendor)",
                "date": full.get("receipt_date") or "",
                "currency": full.get("currency"),
                "before": {k: before.get(k) for k in changed},
                "after": changed,
                "vat": before.get("vat_amount"),
            })
    return repairs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true",
                        help="write the corrections (default is a dry run)")
    parser.add_argument("--db", help="path to the ledger database")
    parser.add_argument("--id", type=int, action="append",
                        help="only consider this receipt id (repeatable)")
    args = parser.parse_args(argv)

    if args.db:
        os.environ["LEDGER_DB_PATH"] = args.db
    import core

    print(f"Ledger: {core.DB_PATH}")
    repairs = find_repairs(args.id)
    if not repairs:
        print("No receipts have a VAT-inflated total. Nothing to repair.")
        return 0

    print(f"\n{len(repairs)} receipt(s) with VAT counted twice in the total:\n")
    for r in repairs:
        cur = r["currency"]
        head = f"  #{r['id']}  {r['vendor']}" + (f"  {r['date']}" if r["date"] else "")
        print(head)
        for field, new in r["after"].items():
            old = r["before"][field]
            print(f"      {field:<13} {_money(old, cur)}  ->  {_money(new, cur)}")
        print(f"      (VAT of {_money(r['vat'], cur)} was added on top of a "
              f"VAT-inclusive subtotal)")

    if not args.apply:
        print("\nDry run - nothing written. Re-run with --apply to correct these.")
        return 0

    for r in repairs:
        core.update_receipt(r["id"], r["after"])
    print(f"\nCorrected {len(repairs)} receipt(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
