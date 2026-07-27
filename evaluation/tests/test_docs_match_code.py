"""
Regression guard against documentation drifting from the code it describes.

The W0 audit found `evaluation/README.md` claiming 39 finance tests when there were 52,
62 SQL/ReAct tests when there were 65, and 64 Quick Chat tests when there were 78 — and
`CONFIGURATION.md` asserting two things that had already been fixed in `core.py`. Stale
evaluation documentation is not a cosmetic problem: the follow-up's own rule is that
completion must never be inferred from documentation, and a reader who trusts a stale
count is doing exactly that.

These tests assert the *checkable* claims. They deliberately do not police prose.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

EVALUATION_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = EVALUATION_DIR.parent

# The exact sentence that must hold while no run has produced a result file.
_NO_RESULTS_DISCLAIMER = "Nothing in this directory is a measured evaluation result."


def _read(name: str) -> str:
    return (EVALUATION_DIR / name).read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Files the documentation points at must exist
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("doc", ["README.md", "IMPLEMENTATION_STATUS.md",
                                 "IMPLEMENTATION_BACKLOG.md", "CONFIGURATION.md",
                                 "REQUIREMENTS_AUDIT.md", "PERFORMANCE.md"])
def test_the_documentation_file_exists(doc):
    assert (EVALUATION_DIR / doc).exists()


def test_every_test_file_is_listed_in_the_readme():
    """The layout block omitted five files after the last round of work, which is how
    `test_w2a_preprocess.py`, `test_w5_retrieval.py` and `test_w6_performance.py`
    became invisible to anyone reading the README."""
    readme = _read("README.md")
    for path in sorted((EVALUATION_DIR / "tests").glob("test_*.py")):
        assert path.name in readme, f"{path.name} is not mentioned in evaluation/README.md"


def test_every_readme_command_references_a_real_path():
    """A documented command that points at a moved file wastes the reader's time and
    silently signals the docs are unmaintained."""
    for match in re.finditer(r"evaluation/[\w/.]+\.(?:py|json|md|txt)", _read("README.md")):
        assert (REPO_ROOT / match.group(0)).exists(), f"{match.group(0)} does not exist"


# --------------------------------------------------------------------------- #
# Constants quoted in the documentation must match the code
# --------------------------------------------------------------------------- #
def test_the_documented_step_budget_matches_the_code(core):
    """`_MAX_AGENT_STEPS` is quoted in CONFIGURATION.md and used to set `max_tool_calls`
    in the trajectory case file. If the code changes and the docs do not, every case
    silently tests the wrong bound."""
    assert f"| `_MAX_AGENT_STEPS` | `{core._MAX_AGENT_STEPS}` |" in _read("CONFIGURATION.md")


def test_the_documented_image_ceiling_matches_the_code(core):
    """`OCR_MAX_IMAGE_DIM` is the live downscale knob — the W0 audit found the compose
    file documenting a *dead* one (`VISION_MAX_DIM`), which would have mis-recorded the
    tested configuration."""
    assert str(core.OCR_MAX_IMAGE_DIM) in _read("CONFIGURATION.md")


def test_the_documented_tools_match_the_real_dispatcher():
    """The tool names in the case file must be the ones `_run_agent_tool` dispatches,
    or every routing assertion is vacuous."""
    from evaluation import trajectory

    configuration = _read("CONFIGURATION.md")
    for tool in trajectory.KNOWN_TOOLS:
        assert tool in configuration


# --------------------------------------------------------------------------- #
# Claims about the current state that must not silently become false
# --------------------------------------------------------------------------- #
def test_the_status_document_pins_the_commit_it_audited():
    """An audit without a commit cannot be checked against anything."""
    assert re.search(r"\*\*Audited commit:\*\*\s*`[0-9a-f]{7,40}`",
                     _read("IMPLEMENTATION_STATUS.md"))


def test_the_results_directory_exists_with_its_contract():
    """`IMPLEMENTATION_STATUS.md` recorded "no results directory exists" as a P0 gap.
    It exists now; the rules that make a stored result meaningful travel with it."""
    results = EVALUATION_DIR / "results"
    assert results.is_dir()
    assert (results / "README.md").exists()


def test_the_backlog_states_that_it_contains_only_verified_gaps():
    """Phase 5's rule: the backlog contains only *verified gaps*. Receipt-to-finance
    posting and Quick Chat parsing were verified complete and must not reappear as
    work to redo."""
    assert "verified gaps" in _read("IMPLEMENTATION_BACKLOG.md")


def test_the_no_measured_results_disclaimer_holds_while_no_results_exist():
    """The project's central honesty constraint: no accuracy figure, pass rate, or
    real latency has been produced. While `results/raw/` is empty that must be stated
    plainly where a reader will see it.

    Written as an *invariant tied to the artifacts* rather than a prose filter: a
    regex hunting for "N% accuracy" flags the breakdown's own warnings ("this is 0%
    receipt-level exact match, **not** 0% field accuracy") and would push the docs
    toward vaguer language instead of more honest language. When real results land in
    `raw/`, this test starts requiring the disclaimer to be revised — which is exactly
    when it should be.
    """
    produced = [p for p in (EVALUATION_DIR / "results" / "raw").glob("*.json")]
    readme = _read("README.md")
    if not produced:
        assert _NO_RESULTS_DISCLAIMER in readme, (
            "no results exist yet, so README must still carry the disclaimer"
        )
    else:
        assert _NO_RESULTS_DISCLAIMER not in readme, (
            f"{len(produced)} result file(s) exist — the blanket 'nothing has been "
            "measured' disclaimer is now false and must be revised"
        )
