"""
Tests for `evaluation.report` — configuration capture and machine-readable results.

The writer is infrastructure every later metric depends on, so its arithmetic is tested
here against synthetic records *before* any real result flows through it. A summarizer
that quietly reports an unmeasured metric as 1.0 would overstate the evaluation more
efficiently than any single wrong test.
"""

from __future__ import annotations

import json

import pytest

from evaluation import report


# --------------------------------------------------------------------------- #
# rate() — the guard against reporting unmeasured metrics
# --------------------------------------------------------------------------- #
def test_a_rate_is_computed_normally():
    assert report.rate(3, 4) == pytest.approx(0.75)


def test_a_rate_over_zero_cases_is_none_not_zero_or_one():
    """A metric with no applicable cases is *undefined*, not 0% and not 100%.
    Reporting either would present something never measured as a result."""
    assert report.rate(0, 0) is None


def test_a_negative_denominator_is_none():
    assert report.rate(1, -1) is None


def test_a_perfect_rate_is_one():
    assert report.rate(5, 5) == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# summarize()
# --------------------------------------------------------------------------- #
def _record(case_id, passed, **checks):
    return {"case_id": case_id, "passed": passed, "checks": checks}


def test_counts_and_rate_are_reported_together():
    """A rate without its denominator cannot be judged: 100% of two cases is not the
    same evidence as 100% of two hundred."""
    summary = report.summarize([
        _record("A", True, route=True),
        _record("B", False, route=False),
    ])
    assert summary["cases"] == 2
    assert summary["passed"] == 1
    assert summary["failed"] == 1
    assert summary["pass_rate"] == pytest.approx(0.5)


def test_failures_are_retained_by_case_id():
    """Failures must stay visible and localizable — deleting them is the easiest way
    to improve a rate."""
    summary = report.summarize([
        _record("A", True), _record("B", False), _record("C", False),
    ])
    assert summary["failed_case_ids"] == ["B", "C"]


def test_each_check_is_broken_out_separately():
    summary = report.summarize([
        _record("A", False, route=True, loop=False),
        _record("B", False, route=False, loop=False),
    ])
    assert summary["checks"]["route"]["passed"] == 1
    assert summary["checks"]["loop"]["passed"] == 0
    assert summary["checks"]["loop"]["rate"] == pytest.approx(0.0)


def test_a_failing_check_names_the_cases_that_failed_it():
    summary = report.summarize([
        _record("A", True, route=True),
        _record("B", False, route=False),
    ])
    assert summary["checks"]["route"]["failed_cases"] == ["B"]


def test_summarizing_nothing_does_not_divide_by_zero():
    summary = report.summarize([])
    assert summary["cases"] == 0
    assert summary["pass_rate"] is None
    assert summary["checks"] == {}


def test_records_without_checks_are_still_counted():
    summary = report.summarize([{"case_id": "A", "passed": True}])
    assert summary["cases"] == 1
    assert summary["checks"] == {}


# --------------------------------------------------------------------------- #
# Configuration capture
# --------------------------------------------------------------------------- #
def test_the_capture_resolves_models_at_runtime(core):
    """Not read from CONFIGURATION.md: `core.py`, `docker-compose.yml` and the README
    disagree three ways about which model is the default, so only the live value is
    meaningful."""
    import extraction

    config = report.capture_configuration()
    assert config["agent_model"] == core.AGENT_MODEL
    assert config["embed_model"] == core.EMBED_MODEL
    assert config["vision_model"] == extraction.DEFAULT_MODEL


def test_the_capture_records_the_database_it_ran_against(core):
    """A result is only interpretable against known input data."""
    config = report.capture_configuration()
    assert config["ledger_db_path"] == str(core.DB_PATH)
    assert config["ledger_db_sha256"]


def test_the_capture_records_agent_behaviour_constants(core):
    config = report.capture_configuration()
    assert config["max_agent_steps"] == core._MAX_AGENT_STEPS
    assert config["ocr_max_image_dim"] == core.OCR_MAX_IMAGE_DIM


def test_the_capture_is_json_serializable():
    """It is embedded in every result file; a non-serializable value would fail the
    write after the run had already been paid for."""
    json.dumps(report.capture_configuration(), default=str)


def test_missing_values_are_recorded_as_none_never_guessed(monkeypatch):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    assert report.capture_configuration()["ollama_host"] is None


def test_the_endpoint_is_captured_when_set(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "http://example:11434")
    assert report.capture_configuration()["ollama_host"] == "http://example:11434"


# --------------------------------------------------------------------------- #
# Configuration gaps
# --------------------------------------------------------------------------- #
def test_a_complete_capture_reports_no_gaps():
    complete = {
        "commit": "abc123", "git_dirty": False, "ollama_host": "http://x:11434",
        "vision_model_digest": "sha256:aaa", "agent_model_digest": "sha256:bbb",
        "ledger_db_sha256": "deadbeef",
    }
    assert report.configuration_gaps(complete) == []


def test_a_dirty_tree_is_a_gap():
    """The commit no longer describes what actually ran."""
    gaps = report.configuration_gaps({"commit": "abc", "git_dirty": True})
    assert any("dirty" in g for g in gaps)


def test_missing_model_digests_are_a_gap():
    """`:latest` is mutable — the tag does not identify what served the run."""
    gaps = report.configuration_gaps({"commit": "abc", "vision_model_digest": None})
    assert any("digest" in g for g in gaps)


def test_a_missing_endpoint_is_a_gap():
    gaps = report.configuration_gaps({"commit": "abc", "ollama_host": None})
    assert any("OLLAMA_HOST" in g for g in gaps)


def test_gaps_are_returned_not_raised():
    """A pilot run with gaps is still worth recording — but the gaps must travel with
    it rather than be discovered afterwards."""
    assert isinstance(report.configuration_gaps({}), list)


# --------------------------------------------------------------------------- #
# Writing
# --------------------------------------------------------------------------- #
@pytest.fixture
def temp_results(monkeypatch, tmp_path):
    """Redirect result output into tmp so tests never write into the repo."""
    kinds = {}
    for kind in ("raw", "processed", "failures"):
        directory = tmp_path / kind
        kinds[kind] = directory
    monkeypatch.setattr(report, "_KINDS", kinds)
    return kinds


def test_a_result_file_is_written(temp_results):
    path = report.write_result("demo", {"ok": True}, identifier="run-1",
                               config={"commit": "abc"})
    assert path.exists()


def test_a_result_carries_its_configuration(temp_results):
    """The rule that makes a stored number evidence rather than a bare figure."""
    path = report.write_result("demo", {"ok": True}, identifier="run-1",
                               config={"commit": "abc", "agent_model": "qwen2.5:latest"})
    document = report.read_result(path)
    assert document["configuration"]["agent_model"] == "qwen2.5:latest"


def test_a_result_carries_its_configuration_gaps(temp_results):
    path = report.write_result("demo", {"ok": True}, identifier="run-1",
                               config={"commit": "abc", "git_dirty": True})
    assert any("dirty" in g for g in report.read_result(path)["configuration_gaps"])


def test_the_payload_round_trips(temp_results):
    payload = {"summary": {"cases": 2, "pass_rate": 0.5},
               "cases": [{"case_id": "A", "passed": True}]}
    path = report.write_result("demo", payload, identifier="run-1", config={})
    assert report.read_result(path)["results"] == payload


def test_the_run_id_is_in_the_filename(temp_results):
    """Results from different runs must never overwrite each other."""
    path = report.write_result("demo", {}, identifier="run-42", config={})
    assert "run-42" in path.name


def test_two_runs_write_two_files(temp_results):
    first = report.write_result("demo", {}, identifier="run-1", config={})
    second = report.write_result("demo", {}, identifier="run-2", config={})
    assert first != second
    assert first.exists() and second.exists()


def test_an_unknown_kind_is_rejected(temp_results):
    with pytest.raises(ValueError):
        report.write_result("demo", {}, kind="nonsense", config={})


@pytest.mark.parametrize("kind", ["raw", "processed", "failures"])
def test_each_result_kind_has_its_own_directory(temp_results, kind):
    path = report.write_result("demo", {}, kind=kind, identifier="run-1", config={})
    assert path.parent == temp_results[kind]


def test_run_ids_are_timestamped_and_prefixed():
    identifier = report.run_id("trajectory")
    assert identifier.startswith("trajectory-")
    assert identifier.endswith("Z")
