"""
demo_memory_rag_tools.py — a runnable tour of STAI_OCR's three AI capabilities:

    1. Memory   — a persistent SQLite ledger of every processed receipt
    2. RAG      — semantic retrieval + a grounded answer over receipt *content*
    3. Tool Use — a SQL agent for aggregates, and a ReAct agent that reasons
                  and routes between the SQL tool and the RAG search tool

All three already live in core.py; this script just exercises them end to end so
you can see each one work without uploading an image or standing up the API.

By default it runs against an ISOLATED demo database seeded with a handful of
sample receipts, so it never touches your real ledger.db. Pass --ledger to run
the same demonstration against your actual ledger instead.

Usage:
    python demo_memory_rag_tools.py                 # isolated demo DB (safe)
    python demo_memory_rag_tools.py --ledger        # your real ledger.db
    python demo_memory_rag_tools.py --model llama3.2:3b

The LLM-backed parts (RAG answers, SQL generation, the ReAct loop) need a
reachable Ollama endpoint. If `ollama` isn't installed or no model is available,
the Memory section still runs and the rest degrades gracefully with a note.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

import core
from core import LineItem, ReceiptData


# --------------------------------------------------------------------------- #
# Pretty printing
# --------------------------------------------------------------------------- #
def section(title: str) -> None:
    print("\n" + "=" * 74)
    print(f"  {title}")
    print("=" * 74)


def step(title: str) -> None:
    print(f"\n--- {title} ---")


def _ollama_ready() -> bool:
    """True if the LLM endpoint is usable for the agent/RAG parts of the demo."""
    return core.ollama is not None


# --------------------------------------------------------------------------- #
# Sample data — receipts built directly as ReceiptData (no vision model needed)
# --------------------------------------------------------------------------- #
def sample_receipts() -> list[tuple[ReceiptData, str]]:
    """A small, varied ledger: two food stops, a pharmacy run, and a shopping
    trip — enough to show category aggregates, vendor lookups and content search."""
    return [
        (
            ReceiptData(
                vendor_name="Pepper Lunch",
                vendor_tin="123-456-789-000",
                receipt_number="OR-1041",
                receipt_date="2026-06-14",
                items=[
                    LineItem(description="Beef Pepper Rice", quantity=1, unit_price=280.0, amount=280.0),
                    LineItem(description="Iced Oat-Milk Latte", quantity=1, unit_price=150.0, amount=150.0),
                ],
                subtotal=430.0,
                vat_amount=46.07,
                total_amount=430.0,
                cash=500.0,
                change=70.0,
                currency="PHP",
                category="Food",
            ),
            "pepper_lunch_0614.jpg",
        ),
        (
            ReceiptData(
                vendor_name="Starbucks BGC",
                receipt_number="SB-99123",
                receipt_date="2026-06-20",
                items=[
                    LineItem(description="Caramel Macchiato Grande", quantity=1, unit_price=210.0, amount=210.0),
                    LineItem(description="Butter Croissant", quantity=2, unit_price=120.0, amount=240.0),
                ],
                subtotal=450.0,
                vat_amount=48.21,
                total_amount=450.0,
                currency="PHP",
                category="Food",
            ),
            "starbucks_0620.jpg",
        ),
        (
            ReceiptData(
                vendor_name="Mercury Drug",
                vendor_tin="005-111-222-000",
                receipt_number="MD-77410",
                receipt_date="2026-06-22",
                items=[
                    LineItem(description="Biogesic Paracetamol 500mg", quantity=1, unit_price=85.5, amount=85.5),
                    LineItem(description="Vitamin C 1000mg", quantity=1, unit_price=340.0, amount=340.0),
                ],
                subtotal=425.5,
                discount=42.55,
                discount_type="Senior Citizen",
                total_amount=382.95,
                currency="PHP",
                category="Health",
            ),
            "mercury_drug_0622.jpg",
        ),
        (
            ReceiptData(
                vendor_name="Uniqlo Trinoma",
                receipt_number="UQ-30582",
                receipt_date="2026-06-28",
                items=[
                    LineItem(description="AIRism Cotton T-Shirt", quantity=2, unit_price=590.0, amount=1180.0),
                    LineItem(description="HEATTECH Socks 3-pack", quantity=1, unit_price=390.0, amount=390.0),
                ],
                subtotal=1570.0,
                vat_amount=168.21,
                total_amount=1570.0,
                currency="PHP",
                category="Shopping",
            ),
            "uniqlo_0628.jpg",
        ),
    ]


def seed_if_empty() -> int:
    """Populate the (demo) ledger with sample receipts if it has none. Returns the
    number of receipts saved. Uses the same save path the real pipeline uses —
    save_receipt() also builds the RAG document/embedding for each receipt."""
    existing = core.list_receipts(limit=1)
    if existing:
        print(f"Ledger already has receipts — using them as-is "
              f"({len(core.list_receipts(limit=9999))} total).")
        return 0
    n = 0
    for data, source in sample_receipts():
        flagged = bool(core.needs_disambiguation(data))
        rid = core.save_receipt(data, source, flagged=flagged)
        print(f"  saved receipt #{rid}: {data.vendor_name} "
              f"({data.category}, {data.currency} {data.total_amount:g})")
        n += 1
    return n


# --------------------------------------------------------------------------- #
# 1. Memory
# --------------------------------------------------------------------------- #
def demo_memory() -> None:
    section("1. MEMORY — the persistent SQLite ledger")

    step("Seeding sample receipts (only if the ledger is empty)")
    seeded = seed_if_empty()
    if not seeded:
        print("  (skipped seeding)")

    step("Reading them back from memory — list_receipts()")
    for r in core.list_receipts(limit=10):
        flag = "  ⚑ needs review" if r.get("flagged") else ""
        print(f"  #{r['id']:>2}  {r.get('vendor_name'):<18} "
              f"{r.get('category') or '-':<9} "
              f"{r.get('currency') or ''} {r.get('total_amount') or 0:>9,.2f}{flag}")

    step("Aggregated view straight from memory — expense_summary()")
    summ = core.expense_summary()
    print(f"  receipts: {summ['count']}   "
          f"grand total: {summ.get('currency') or ''} {summ['total']:,.2f}   "
          f"top category: {summ['top_category']}")
    print("  by category: " + ", ".join(f"{k} {v:,.2f}" for k, v in summ["by_category"].items()))


# --------------------------------------------------------------------------- #
# 2. RAG
# --------------------------------------------------------------------------- #
def demo_rag(model: str) -> None:
    section("2. RAG — semantic retrieval over receipt content")

    # Retrieval alone works even without the chat model (keyword fallback), so we
    # always show semantic_search(); the grounded answer needs the LLM.
    queries = [
        "which receipt had the oat-milk latte?",
        "what did I buy at the pharmacy?",
    ]

    for q in queries:
        step(f'Query: "{q}"')

        hits = core.semantic_search(q, k=3)
        if not hits:
            print("  (no matching receipts retrieved)")
            continue
        print("  Retrieved (by similarity):")
        for h in hits:
            print(f"    #{h['receipt_id']}  score={h['score']:<7} {h['vendor_name']}")

        if not _ollama_ready():
            print("  (skipping grounded answer — ollama not available)")
            continue
        try:
            result = core.rag_answer(q, model=model, k=3)
            print(f"  Grounded answer: {result['answer']}")
        except Exception as exc:  # noqa: BLE001
            print(f"  (RAG answer unavailable: {exc})")


# --------------------------------------------------------------------------- #
# 3. Tool Use
# --------------------------------------------------------------------------- #
def demo_tool_use(model: str) -> None:
    section("3. TOOL USE — SQL agent + ReAct agent")

    if not _ollama_ready():
        print("  ollama is not available, so the tool-using agents can't run.")
        print("  Install ollama and pull a model (e.g. `ollama pull qwen2.5`) to see this.")
        return

    # --- 3a. The SQL tool on its own: NL question -> SELECT -> rows -> answer ---
    step("SQL agent (ask_ledger) — an aggregate question")
    sql_questions = [
        "How much did I spend in total?",
        "What is my spending by category?",
        "How much did I spend at Mercury Drug?",
    ]
    for q in sql_questions:
        try:
            res = core.ask_ledger(q, model=model)
            print(f"  Q: {q}")
            print(f"     SQL:    {res['sql']}")
            print(f"     Answer: {res['answer']}")
        except Exception as exc:  # noqa: BLE001
            print(f"  Q: {q}\n     (failed: {exc})")

    # --- 3b. The ReAct agent: it CHOOSES which tool to use, per question ---
    step("ReAct agent (agent_run) — it routes between the SQL and search tools")
    agent_questions = [
        "How much have I spent on Food?",          # -> should route to sql_ledger
        "Which receipt had the caramel macchiato?",  # -> should route to search_receipts
    ]
    for q in agent_questions:
        try:
            res = core.agent_run(q, model=model)
            tools = [s.get("tool") for s in res["steps"] if s.get("tool")]
            print(f"  Q: {q}")
            print(f"     tools used: {tools or ['(answered directly)']}")
            print(f"     Answer: {res['answer']}")
        except Exception as exc:  # noqa: BLE001
            print(f"  Q: {q}\n     (failed: {exc})")

    # --- 3c. Scoped tool use: the same agent, physically limited to one receipt ---
    step("Scoped tool use — restrict the agent to a single receipt")
    latest = core.get_latest_receipt_id()
    if latest is not None:
        q = "What did I buy and what was the total?"
        try:
            res = core.agent_run(q, model=model, receipt_ids=[latest])
            print(f"  Scoped to receipt #{latest}")
            print(f"  Q: {q}")
            print(f"     Answer: {res['answer']}")
        except Exception as exc:  # noqa: BLE001
            print(f"     (failed: {exc})")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ledger", action="store_true",
                        help="run against the real ledger.db instead of an isolated demo DB")
    parser.add_argument("--db", default=None,
                        help="path to a specific SQLite DB to use (overrides --ledger)")
    parser.add_argument("--model", default=core.AGENT_MODEL,
                        help=f"chat model for the agents/RAG (default: {core.AGENT_MODEL})")
    args = parser.parse_args()

    # Point every core.* function at the chosen database. DB_PATH is read on each
    # call, so overriding it here reroutes the whole ledger without touching core.
    if args.db:
        core.DB_PATH = Path(args.db)
    elif not args.ledger:
        demo_db = Path(tempfile.gettempdir()) / "stai_ocr_demo_ledger.db"
        core.DB_PATH = demo_db

    print(f"Using database: {core.DB_PATH}")
    print(f"Agent/RAG model: {args.model}")
    print(f"Ollama available: {_ollama_ready()}")

    demo_memory()
    demo_rag(args.model)
    demo_tool_use(args.model)

    section("Done")
    print("Memory, RAG, and Tool Use all exercised above.")
    if not args.ledger and not args.db:
        print(f"Demo data lives in {core.DB_PATH} — delete it to start fresh, or")
        print("re-run with --ledger to use your real receipts.")


if __name__ == "__main__":
    main()
