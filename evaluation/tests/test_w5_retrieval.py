"""
W5 — retrieval behaviour of `core.semantic_search`.

Runs offline: embeddings are written directly into `receipt_docs` as synthetic
vectors and `_embed` is stubbed, so both the vector path and the keyword-fallback
path are exercised without a model.

These tests exist because `semantic_search` was restructured for speed (scope pushed
into SQL, scoring on ids+vectors only, top-k hydrated in a second query). Their job is
to pin the behaviour that must survive that change: top-k ordering, the relevance
floor, and above all **scope isolation** — the guardrail that stops a single-receipt
question reading the rest of the ledger.
"""

from __future__ import annotations

import numpy as np
import pytest


DIM = 8


def _unit(*values) -> np.ndarray:
    v = np.zeros(DIM, dtype=np.float32)
    for i, x in enumerate(values):
        v[i] = x
    return v


@pytest.fixture
def corpus(finance_fixture, core):
    """Three receipts with hand-chosen orthogonal-ish vectors.

    coffee  -> [1,0,...]   rice -> [0,1,...]   fuel -> [0,0,1,...]
    A query equal to one of these scores 1.0 on it and 0.0 on the others, so
    ranking and the _VEC_MIN_SCORE floor are both unambiguous.
    """
    core.init_rag_db()
    specs = [
        ("Coffee Shop", "coffee latte espresso beans", _unit(1, 0, 0)),
        ("Rice Store", "rice grain sack harvest", _unit(0, 1, 0)),
        ("Fuel Station", "diesel gasoline petrol", _unit(0, 0, 1)),
    ]
    ids = []
    with core._connect() as con:
        for vendor, doc, vec in specs:
            cur = con.execute(
                "INSERT INTO receipts (source_file, processed_at, vendor_name, "
                "receipt_date, total_amount, currency, category, flagged) "
                "VALUES (?,?,?,?,?,?,?,0)",
                (f"{vendor}.jpg", "2026-06-01T00:00:00", vendor, "2026-06-01",
                 100.0, "PHP", "Other"),
            )
            rid = cur.lastrowid
            ids.append(rid)
            con.execute(
                "INSERT INTO receipt_docs (receipt_id, doc, embedding, emb_ver) "
                "VALUES (?,?,?,?)",
                (rid, doc, vec.tobytes(), core._EMBED_VERSION),
            )
        con.commit()
    return dict(zip(["coffee", "rice", "fuel"], ids))


@pytest.fixture
def stub_embed(core, monkeypatch):
    """Force `_embed` to return a chosen vector, and stop ensure_index from trying
    to reach a model for the fixture's un-embedded receipts."""
    monkeypatch.setattr(core, "ensure_index", lambda: None)

    def _set(vec):
        monkeypatch.setattr(core, "_embed", lambda text: None if vec is None else list(vec))

    return _set


# --------------------------------------------------------------------------- #
# Ranking
# --------------------------------------------------------------------------- #
def test_best_match_ranks_first(corpus, core, stub_embed):
    stub_embed(_unit(1, 0, 0))
    hits = core.semantic_search("coffee", k=3)
    assert hits[0]["receipt_id"] == corpus["coffee"]


def test_results_are_ordered_by_descending_score(corpus, core, stub_embed):
    stub_embed(_unit(1, 0.5, 0.2))
    hits = core.semantic_search("anything", k=3)
    scores = [h["score"] for h in hits]
    assert scores == sorted(scores, reverse=True)


def test_k_limits_the_result_count(corpus, core, stub_embed):
    stub_embed(_unit(1, 0.9, 0.8))
    assert len(core.semantic_search("anything", k=2)) == 2


def test_hydrated_rows_carry_full_metadata(corpus, core, stub_embed):
    """The two-query split must not drop fields — the RAG prompt and the UI both
    read vendor/date/total off these hits."""
    stub_embed(_unit(1, 0, 0))
    hit = core.semantic_search("coffee", k=1)[0]
    assert hit["vendor_name"] == "Coffee Shop"
    assert hit["receipt_date"] == "2026-06-01"
    assert hit["total_amount"] == pytest.approx(100.0)
    assert hit["currency"] == "PHP"
    assert hit["source_file"] == "Coffee Shop.jpg"
    assert "coffee" in hit["doc"]


# --------------------------------------------------------------------------- #
# Relevance floor
# --------------------------------------------------------------------------- #
def test_irrelevant_receipts_are_dropped_on_a_whole_ledger_search(corpus, core, stub_embed):
    """A query matching only 'coffee' must not return rice and fuel — RAG has to be
    able to say "not found" instead of answering from arbitrary receipts."""
    stub_embed(_unit(1, 0, 0))
    hits = core.semantic_search("coffee", k=10)
    assert [h["receipt_id"] for h in hits] == [corpus["coffee"]]


def test_a_query_matching_nothing_returns_no_hits(corpus, core, stub_embed):
    stub_embed(_unit(0, 0, 0, 1))  # orthogonal to every document
    assert core.semantic_search("submarine parts", k=10) == []


def test_scoped_search_keeps_low_scoring_receipts(corpus, core, stub_embed):
    """The relevance floor is for whole-ledger searches only. When the caller pinned
    specific receipts the user chose them, so they must come back even at score 0."""
    stub_embed(_unit(0, 0, 0, 1))
    hits = core.semantic_search("anything", k=10, receipt_ids=[corpus["rice"]])
    assert [h["receipt_id"] for h in hits] == [corpus["rice"]]


# --------------------------------------------------------------------------- #
# Scope isolation — the security-relevant guardrail
# --------------------------------------------------------------------------- #
def test_scope_restricts_results_to_the_named_receipts(corpus, core, stub_embed):
    stub_embed(_unit(1, 0, 0))  # would otherwise rank coffee first
    hits = core.semantic_search("coffee", k=10, receipt_ids=[corpus["rice"]])
    assert [h["receipt_id"] for h in hits] == [corpus["rice"]]


def test_scope_of_several_receipts_excludes_the_rest(corpus, core, stub_embed):
    stub_embed(_unit(1, 1, 1))
    scope = [corpus["rice"], corpus["fuel"]]
    hits = core.semantic_search("anything", k=10, receipt_ids=scope)
    assert set(h["receipt_id"] for h in hits) <= set(scope)
    assert corpus["coffee"] not in {h["receipt_id"] for h in hits}


def test_explicit_receipt_reference_pins_the_search(corpus, core, stub_embed):
    """"receipt #N" must win over semantic similarity: the query text is about
    coffee, but the reference names the rice receipt."""
    stub_embed(_unit(1, 0, 0))
    hits = core.semantic_search(f"what was on receipt #{corpus['rice']}", k=10)
    assert [h["receipt_id"] for h in hits] == [corpus["rice"]]


def test_a_reference_to_a_nonexistent_receipt_does_not_pin(corpus, core, stub_embed):
    """An id that isn't in the ledger must fall back to normal search rather than
    returning nothing or raising."""
    stub_embed(_unit(1, 0, 0))
    hits = core.semantic_search("coffee on receipt #99999", k=10)
    assert [h["receipt_id"] for h in hits] == [corpus["coffee"]]


def test_explicit_scope_argument_beats_an_inline_reference(corpus, core, stub_embed):
    """The caller's scope is the guardrail and must not be widened by question text."""
    stub_embed(_unit(1, 0, 0))
    hits = core.semantic_search(
        f"receipt #{corpus['coffee']}", k=10, receipt_ids=[corpus["fuel"]]
    )
    assert [h["receipt_id"] for h in hits] == [corpus["fuel"]]


# --------------------------------------------------------------------------- #
# Keyword fallback (no embedding model)
# --------------------------------------------------------------------------- #
def test_keyword_fallback_finds_the_right_receipt(corpus, core, stub_embed):
    stub_embed(None)  # no embedding model available
    hits = core.semantic_search("diesel", k=3)
    assert hits and hits[0]["receipt_id"] == corpus["fuel"]


def test_keyword_fallback_respects_scope(corpus, core, stub_embed):
    stub_embed(None)
    hits = core.semantic_search("diesel", k=10, receipt_ids=[corpus["rice"]])
    assert [h["receipt_id"] for h in hits] == [corpus["rice"]]


def test_keyword_fallback_drops_non_matches_on_whole_ledger(corpus, core, stub_embed):
    stub_embed(None)
    assert core.semantic_search("submarine", k=10) == []


# --------------------------------------------------------------------------- #
# Robustness
# --------------------------------------------------------------------------- #
def test_empty_query_returns_nothing(corpus, core, stub_embed):
    stub_embed(_unit(1, 0, 0))
    assert core.semantic_search("", k=3) == []
    assert core.semantic_search("   ", k=3) == []


def test_a_stale_vector_of_another_dimension_is_skipped_not_crashed(corpus, core, stub_embed):
    """An embedding written by a previous model has a different length. Comparing it
    would raise, so it must be skipped while the rest still rank."""
    with core._connect() as con:
        con.execute(
            "UPDATE receipt_docs SET embedding = ? WHERE receipt_id = ?",
            (np.zeros(DIM + 5, dtype=np.float32).tobytes(), corpus["rice"]),
        )
        con.commit()

    stub_embed(_unit(1, 0, 0))
    hits = core.semantic_search("coffee", k=10)
    assert [h["receipt_id"] for h in hits] == [corpus["coffee"]]


def test_a_null_embedding_is_skipped(corpus, core, stub_embed):
    with core._connect() as con:
        con.execute(
            "UPDATE receipt_docs SET embedding = NULL WHERE receipt_id = ?",
            (corpus["rice"],),
        )
        con.commit()

    stub_embed(_unit(0, 1, 0))  # would have matched rice
    assert core.semantic_search("rice", k=10) == []


def test_invalid_scope_ids_are_rejected(corpus, core, stub_embed):
    stub_embed(_unit(1, 0, 0))
    with pytest.raises(core.GuardrailError):
        core.semantic_search("coffee", k=3, receipt_ids=["not-an-id"])
