"""
bench_retrieval.py — W6 microbenchmark for the retrieval hot path.

Measures the part of RAG that does NOT need a model: loading candidate rows out of
SQLite and scoring them against a query vector. Embeddings are synthesised locally,
so this runs offline and is the same on any machine.

What it deliberately does NOT measure: vision/OCR latency, agent latency, or the
embedding call itself. Those need a reachable Ollama endpoint and belong in a live
W6 run. Nothing here should be quoted as an end-to-end figure.

Usage:
    python evaluation/bench_retrieval.py [n_receipts ...]
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

BENCH_DB = Path(__file__).parent / "fixtures" / "_bench.db"
EMBED_DIM = 768  # nomic-embed-text
REPEATS = 5


def build_corpus(n: int) -> None:
    """Create n receipts with deterministic synthetic embeddings."""
    import numpy as np

    import core

    for suffix in ("", "-journal", "-wal", "-shm"):
        p = Path(str(BENCH_DB) + suffix)
        if p.exists():
            p.unlink()

    core.init_db()
    core.init_rag_db()

    rng = np.random.default_rng(1234)  # fixed seed -> identical corpus every run
    vendors = ["SM Supermarket", "Jollibee", "7-Eleven", "Mercury Drug", "Uniqlo"]

    with core._connect() as con:
        for i in range(n):
            vendor = vendors[i % len(vendors)]
            con.execute(
                "INSERT INTO receipts (source_file, processed_at, vendor_name, "
                "receipt_date, total_amount, currency, category, flagged) "
                "VALUES (?,?,?,?,?,?,?,0)",
                (f"bench_{i}.jpg", "2026-06-01T00:00:00", vendor,
                 "2026-06-01", 100.0 + i, "PHP", "Groceries"),
            )
        con.commit()

        rows = con.execute("SELECT id, vendor_name FROM receipts").fetchall()
        for rid, vendor in rows:
            doc = (f"Receipt from {vendor} dated 2026-06-01 total 100.00 PHP. "
                   f"Items: rice, cooking oil, chicken, bread, milk, eggs, coffee. "
                   f"Reference {rid}.")
            vec = rng.standard_normal(EMBED_DIM).astype("float32")
            con.execute(
                "INSERT INTO receipt_docs (receipt_id, doc, embedding, emb_ver) "
                "VALUES (?,?,?,?)",
                (rid, doc, vec.tobytes(), core._EMBED_VERSION),
            )
        con.commit()


def time_search(query_vec, n: int, scope=None) -> float:
    """Time semantic_search with the embedding call stubbed out, so the number
    reflects DB load + scoring only."""
    import core

    real_embed = core._embed
    core._embed = lambda text: query_vec          # stub: no network
    real_ensure = core.ensure_index
    core.ensure_index = lambda: None              # corpus is already indexed
    try:
        best = float("inf")
        for _ in range(REPEATS):
            t0 = time.perf_counter()
            core.semantic_search("rice and cooking oil", k=4, receipt_ids=scope)
            best = min(best, time.perf_counter() - t0)
        return best * 1000.0
    finally:
        core._embed = real_embed
        core.ensure_index = real_ensure


def main() -> int:
    sizes = [int(a) for a in sys.argv[1:]] or [50, 200, 1000, 5000]

    os.environ["LEDGER_DB_PATH"] = str(BENCH_DB)
    os.environ.setdefault("MLFLOW_ENABLED", "0")

    import numpy as np

    import core

    if Path(core.DB_PATH).resolve() != BENCH_DB.resolve():
        print(f"ERROR: core.DB_PATH is {core.DB_PATH}, expected {BENCH_DB}", file=sys.stderr)
        return 1

    rng = np.random.default_rng(999)
    qvec = rng.standard_normal(EMBED_DIM).astype("float32").tolist()

    print(f"{'receipts':>9} | {'whole-ledger':>13} | {'scoped to 1':>12}")
    print("-" * 42)
    for n in sizes:
        build_corpus(n)
        whole = time_search(qvec, n)
        scoped = time_search(qvec, n, scope=[1])
        print(f"{n:>9} | {whole:>10.2f} ms | {scoped:>9.2f} ms")

    for suffix in ("", "-journal", "-wal", "-shm"):
        p = Path(str(BENCH_DB) + suffix)
        if p.exists():
            p.unlink()
    print("\nBest-of-%d per configuration. DB load + scoring only; no model calls." % REPEATS)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
