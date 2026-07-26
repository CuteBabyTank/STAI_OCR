"""
W2-D — Layer 1 component evaluation of the SQL, retrieval, and ReAct tooling.

Deliberately model-free. Everything here exercises the deterministic machinery that
surrounds the LLM — validators, scope sandboxing, response parsing, tool dispatch —
so these results are reproducible and do not depend on which Ollama endpoint or model
was reachable. The model-dependent halves (does the agent *choose* the right tool;
does the generated SQL return the right rows) belong to W3/W5 and need a live
endpoint, so they are not asserted here.

Mapping to the W2-D checklist:
  [x] SQL validator accepts read-only SELECT
  [x] SQL validator rejects forbidden verbs and multiple statements
  [x] Explicit receipt references remain scoped   (sandbox + _assert_in_scope)
  [x] Repeated tool calls and step limits are handled  (constants + loop-guard logic)
  [ ] Generated SQL executes against the intended scoped database   -> W5, needs model
  [ ] SQL execution returns the correct result                      -> W5, needs model
  [ ] Retrieval returns the relevant receipt IDs                    -> W5, needs labels
  [ ] ReAct selects SQL / receipt search for the right questions    -> W3, needs model
"""

from __future__ import annotations

import pytest


# --------------------------------------------------------------------------- #
# SQL guardrails
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM receipts",
        "select vendor_name from receipts where total_amount > 100",
        "  SELECT SUM(total_amount) FROM receipts  ",
        "SELECT r.id FROM receipts r JOIN line_items l ON l.receipt_id = r.id",
    ],
)
def test_validator_accepts_read_only_selects(core, sql):
    core._validate_sql(sql)  # must not raise


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO receipts (vendor_name) VALUES ('x')",
        "UPDATE receipts SET total_amount = 0",
        "DELETE FROM receipts",
        "DROP TABLE receipts",
        "ALTER TABLE receipts ADD COLUMN x TEXT",
        "ATTACH DATABASE '/etc/passwd' AS pw",
        "PRAGMA table_info(receipts)",
    ],
)
def test_validator_rejects_write_and_metadata_verbs(core, sql):
    with pytest.raises(core.GuardrailError):
        core._validate_sql(sql)


def test_validator_rejects_multi_statement_queries(core):
    """The semicolon branch, reached with a benign second statement.

    `SELECT 1; DROP TABLE receipts` is also rejected, but by the forbidden-verb
    check, which runs first — so it does not exercise this branch. Both orderings
    are covered: see test_validator_rejects_write_and_metadata_verbs.
    """
    with pytest.raises(core.GuardrailError, match="multi-statement"):
        core._validate_sql("SELECT 1; SELECT 2")


def test_validator_rejects_a_forbidden_verb_hidden_after_a_select(core):
    """Starting with SELECT is not sufficient — the whole string is scanned."""
    with pytest.raises(core.GuardrailError):
        core._validate_sql(
            "SELECT * FROM receipts WHERE id IN (SELECT id FROM receipts) "
            "AND 1=1 DELETE FROM receipts"
        )


def test_validator_rejects_empty_query(core):
    with pytest.raises(core.GuardrailError, match="empty"):
        core._validate_sql("")


@pytest.mark.parametrize("sql", ["WITH x AS (SELECT 1) SELECT * FROM x", "EXPLAIN SELECT 1"])
def test_validator_rejects_non_select_leading_keywords(core, sql):
    """Documents actual behaviour: the validator requires the string to *start*
    with SELECT, so CTEs and EXPLAIN are refused. Recorded as a deliberate
    conservative choice, not a bug — a future relaxation should update this test
    consciously rather than by accident."""
    with pytest.raises(core.GuardrailError):
        core._validate_sql(sql)


# --------------------------------------------------------------------------- #
# SQL extraction from model output
# --------------------------------------------------------------------------- #
def test_extract_sql_strips_markdown_fences(core):
    assert core._extract_sql("```sql\nSELECT 1\n```") == "SELECT 1"


def test_extract_sql_strips_a_sql_prefix(core):
    assert core._extract_sql("SQL: SELECT 1") == "SELECT 1"


def test_extract_sql_cuts_at_the_first_semicolon(core):
    """The cut is what makes the multi-statement guard reachable in practice."""
    assert core._extract_sql("SELECT 1; DROP TABLE receipts") == "SELECT 1"


def test_extract_sql_output_passes_the_validator(core):
    """The two halves compose: whatever _extract_sql yields for a benign fenced
    query must survive _validate_sql."""
    core._validate_sql(core._extract_sql("```sql\nSELECT SUM(total_amount) FROM receipts\n```"))


# --------------------------------------------------------------------------- #
# Receipt scope normalization (hostile input into the sandbox builder)
# --------------------------------------------------------------------------- #
def test_scope_normalization_sorts_and_dedupes(core):
    assert core._normalize_scope([3, 1, 2, 1]) == [1, 2, 3]


def test_scope_normalization_accepts_numeric_strings(core):
    assert core._normalize_scope(["2", "1"]) == [1, 2]


def test_empty_scope_is_none(core):
    assert core._normalize_scope([]) is None
    assert core._normalize_scope(None) is None


@pytest.mark.parametrize("bad", [["abc"], [0], [-1], [None], [{"id": 1}]])
def test_scope_normalization_rejects_invalid_ids(core, bad):
    with pytest.raises(core.GuardrailError, match="Invalid receipt id"):
        core._normalize_scope(bad)


def test_scope_normalization_lets_infinity_escape_as_overflowerror(core):
    """Documents a boundary, deliberately NOT marked xfail.

    `_normalize_scope` catches (TypeError, ValueError) but `int(float('inf'))`
    raises OverflowError, which escapes as an unhandled 500 rather than a
    GuardrailError. Assessed as latent, not exploitable: the only external entry
    points are `AskRequest.receipt_ids` / `SearchRequest.receipt_ids`, both typed
    `list[int] | None`, so pydantic rejects a non-integer before this is reached —
    and `inf` is not expressible in JSON at all. Recorded so the assessment is
    revisited if an untyped caller is ever added.
    """
    with pytest.raises(OverflowError):
        core._normalize_scope([float("inf")])


# --------------------------------------------------------------------------- #
# Scope isolation — the hard boundary for single-receipt questions
# --------------------------------------------------------------------------- #
def test_scoped_db_contains_only_the_requested_receipts(finance_fixture, core):
    """W5 'scope leakage rate' at component level: rows outside the scope are never
    copied into the sandbox, so no query can reach them."""
    all_ids = [r["id"] for r in core.list_receipts()]
    assert len(all_ids) >= 2, "fixture must have >1 receipt for this to mean anything"
    scope = [all_ids[0]]

    mem = core._build_scoped_db(scope)
    try:
        visible = [r[0] for r in mem.execute("SELECT id FROM receipts")]
    finally:
        mem.close()

    assert visible == scope
    assert all_ids[1] not in visible


def test_scoped_db_line_items_are_also_restricted(finance_fixture, core):
    all_ids = [r["id"] for r in core.list_receipts()]
    scope = [all_ids[0]]

    mem = core._build_scoped_db(scope)
    try:
        owners = {r[0] for r in mem.execute("SELECT receipt_id FROM line_items")}
    finally:
        mem.close()

    assert owners <= set(scope)


def test_assert_in_scope_blocks_an_out_of_scope_row(core):
    """Defense in depth: even if the sandbox were bypassed, results referencing an
    unscoped receipt must not leave the door."""
    with pytest.raises(core.GuardrailError, match="outside the requested scope"):
        core._assert_in_scope([{"receipt_id": 99}], [1, 2])


def test_assert_in_scope_allows_in_scope_rows(core):
    rows = [{"receipt_id": 1}, {"id": 2}]
    assert core._assert_in_scope(rows, [1, 2]) == rows


def test_assert_in_scope_ignores_non_id_columns(core):
    """An aggregate result has no id column and must not be rejected."""
    rows = [{"total": 1234.5}]
    assert core._assert_in_scope(rows, [1]) == rows


def test_readonly_connection_refuses_writes(finance_fixture, core):
    """The SQL tool's connection can never mutate the ledger, even if a write
    somehow got past the validator."""
    con = core._readonly_connection()
    try:
        with pytest.raises(Exception):
            con.execute("CREATE TABLE should_not_exist (x INTEGER)")
            con.commit()
    finally:
        con.close()


# --------------------------------------------------------------------------- #
# ReAct response parsing
# --------------------------------------------------------------------------- #
def test_parse_action_extracts_tool_and_input(core):
    tool, inp = core._parse_action(
        "Thought: I should look this up.\nAction: sql_ledger\nAction Input: total spend"
    )
    assert tool == "sql_ledger"
    assert inp == "total spend"


def test_parse_action_is_case_insensitive_and_lowercases_the_tool(core):
    tool, _ = core._parse_action("action: SQL_Ledger\naction input: x")
    assert tool == "sql_ledger"


def test_parse_action_takes_only_the_first_line_of_input(core):
    """Guards the loop-dedup key: a multi-line input would otherwise make two
    identical calls look different and defeat the repeat guard."""
    _, inp = core._parse_action(
        "Action: search_receipts\nAction Input: coffee\nObservation: leaked"
    )
    assert inp == "coffee"


def test_parse_action_returns_none_when_there_is_no_action(core):
    assert core._parse_action("Thought: hmm, no idea.") == (None, "")


def test_parse_final_extracts_the_answer(core):
    assert core._parse_final("Final Answer: You spent 500 pesos.") == "You spent 500 pesos."


def test_parse_final_peels_repeated_labels(core):
    """Small models emit 'Final Answer: Final Answer: ...' — the user must never
    see the scaffolding."""
    assert core._parse_final("Final Answer: Final Answer: 42") == "42"


def test_parse_final_cuts_trailing_scaffolding(core):
    answer = core._parse_final("Final Answer: 42\nThought: maybe I should check again")
    assert answer == "42"


def test_parse_final_returns_none_without_a_final_answer(core):
    assert core._parse_final("Action: sql_ledger") is None


def test_parse_clarification_extracts_the_question(core):
    assert core._parse_clarification("Clarification: Which receipt?") == "Which receipt?"


def test_parse_clarification_returns_none_when_absent(core):
    assert core._parse_clarification("Final Answer: done") is None


# --------------------------------------------------------------------------- #
# Tool dispatch
# --------------------------------------------------------------------------- #
def test_unknown_tool_returns_an_observation_rather_than_raising(core):
    """An unknown tool name must be recoverable: the agent gets told the valid
    names and can retry, instead of the run crashing."""
    obs, payload = core._run_agent_tool("definitely_not_a_tool", "x", "model", None)
    assert "Unknown tool" in obs
    assert "sql_ledger" in obs and "search_receipts" in obs
    assert payload["kind"] == "error"


def test_agent_step_budget_is_a_small_positive_integer(core):
    """Records the real value so W3 cases stop copying a number from a lecture
    example. If this changes, the trajectory expectations must be revisited."""
    assert core._MAX_AGENT_STEPS == 3


# --------------------------------------------------------------------------- #
# Disambiguation trigger (pre-loop, deterministic)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "question",
    [
        "What was on my recent receipt?",
        "Show me the latest receipt",
        "how much was my last receipt",
    ],
)
def test_recent_receipt_questions_are_detected_as_ambiguous(core, question):
    assert core._RECENT_RECEIPT_RE.search(question) is not None


@pytest.mark.parametrize(
    "question",
    [
        "How much did I spend on groceries last month?",
        "What is my total spending?",
        "Show me receipt #3",
    ],
)
def test_unambiguous_questions_do_not_trigger_clarification(core, question):
    assert core._RECENT_RECEIPT_RE.search(question) is None


# --------------------------------------------------------------------------- #
# Input guardrails (W2-A items reachable without a model)
# --------------------------------------------------------------------------- #
def test_empty_upload_is_rejected(core):
    with pytest.raises(core.GuardrailError, match="Empty file"):
        core.validate_input(b"", "image/jpeg")


def test_oversized_upload_is_rejected(core):
    oversized = b"x" * (core.MAX_IMAGE_BYTES + 1)
    with pytest.raises(core.GuardrailError, match="limit"):
        core.validate_input(oversized, "image/jpeg")


def test_unsupported_content_type_is_rejected(core):
    with pytest.raises(core.GuardrailError, match="Unsupported file type"):
        core.validate_input(b"data", "application/zip")


@pytest.mark.parametrize("content_type", ["image/png", "image/jpeg", "application/pdf"])
def test_supported_content_types_are_accepted(core, content_type):
    core.validate_input(b"data", content_type)  # must not raise


def test_schema_validation_rejects_junk_output(core):
    with pytest.raises(core.GuardrailError, match="schema validation"):
        core.validate_output({"items": "not a list"})


# --------------------------------------------------------------------------- #
# Review / disambiguation reasons (W2-A)
# --------------------------------------------------------------------------- #
def test_missing_total_is_flagged_for_review(core):
    reasons = core.needs_disambiguation(
        core.ReceiptData(vendor_name="X", total_amount=None, items=[])
    )
    assert any("total" in r.lower() for r in reasons)


def test_missing_line_items_are_flagged_for_review(core):
    reasons = core.needs_disambiguation(
        core.ReceiptData(vendor_name="X", total_amount=100.0, items=[])
    )
    assert any("line item" in r.lower() for r in reasons)


def test_a_clean_receipt_is_not_flagged(core):
    """False-review rate matters as much as review recall — a well-formed receipt
    must not be sent to a human for no reason."""
    clean = core.ReceiptData(
        vendor_name="SM Supermarket",
        receipt_date="2026-06-10",
        subtotal=100.0,
        total_amount=100.0,
        currency="PHP",
        items=[core.LineItem(description="Rice", quantity=1, unit_price=100.0, amount=100.0)],
    )
    assert core.needs_disambiguation(clean) == []
