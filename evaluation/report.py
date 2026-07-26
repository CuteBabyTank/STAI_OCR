"""
Machine-readable evaluation results + tested-configuration capture.

Two W0/W2 deliverables that were missing entirely (IMPLEMENTATION_STATUS.md §3.3, §4
items 19 and 20): there was no `evaluation/results/` directory and nothing that could
write a result file, so no run could produce an artifact.

Design rules taken from the breakdown
-------------------------------------
* **Every result file carries its configuration.** A number without the commit, the
  resolved model names and the endpoint it came from is not evidence — the repository
  has a documented three-way model-default conflict, so "which model produced this"
  cannot be inferred from any default.
* **Resolved at runtime, never back-filled.** Model names are read from the live
  modules, not from `CONFIGURATION.md`.
* **Failures are recorded, not dropped.** `summarize()` reports denominators alongside
  every rate, and returns `None` rather than 0 or 1 when a metric has no applicable
  cases — a rate over zero cases is undefined, not perfect.
* **Nothing here computes an accuracy figure.** It stores and summarizes what a runner
  measured.

`core` and `finance` are imported lazily inside functions: `core.DB_PATH` is bound from
`LEDGER_DB_PATH` at import time, so importing at module scope would pin the wrong
database for the test suite (see `tests/conftest.py`).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EVALUATION_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVALUATION_DIR.parent
RESULTS_DIR = EVALUATION_DIR / "results"
RAW_DIR = RESULTS_DIR / "raw"
PROCESSED_DIR = RESULTS_DIR / "processed"
FAILURES_DIR = RESULTS_DIR / "failures"

_KINDS = {"raw": RAW_DIR, "processed": PROCESSED_DIR, "failures": FAILURES_DIR}


# --------------------------------------------------------------------------- #
# Configuration capture
# --------------------------------------------------------------------------- #
def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, timeout=10
        )
        return out.stdout.strip() if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def _sha256(path: Path) -> str | None:
    """Hash a database file so a result can be tied to the exact data it ran against."""
    try:
        digest = hashlib.sha256()
        with path.open("rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                digest.update(block)
        return digest.hexdigest()
    except OSError:
        return None


def run_id(prefix: str = "run") -> str:
    return f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"


def capture_configuration() -> dict[str, Any]:
    """The per-run capture record from CONFIGURATION.md, filled from the live system.

    Model names are read from the imported modules rather than from any documented
    default, because `core.py`, `docker-compose.yml` and the README disagree three
    ways. Missing values are recorded as `None` — never guessed.
    """
    import core
    import extraction

    ledger_path = Path(core.DB_PATH)
    dirty = _git("status", "--porcelain")

    return {
        "utc_timestamp": datetime.now(timezone.utc).isoformat(),
        "commit": _git("rev-parse", "HEAD"),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "git_dirty": bool(dirty) if dirty is not None else None,
        "python": sys.version.split()[0],
        "platform": sys.platform,
        # Resolved at runtime — the three documented defaults disagree.
        "vision_model": extraction.DEFAULT_MODEL,
        "agent_model": core.AGENT_MODEL,
        "embed_model": core.EMBED_MODEL,
        # Tags like ":latest" are mutable; the digest is the only stable identity.
        # Populated by the caller from `ollama list` on the serving host.
        "vision_model_digest": None,
        "agent_model_digest": None,
        "ollama_host": os.getenv("OLLAMA_HOST"),
        "ledger_db_path": str(ledger_path),
        "ledger_db_sha256": _sha256(ledger_path),
        "mlflow_tracking_uri": os.getenv("MLFLOW_TRACKING_URI"),
        "mlflow_enabled": core.MLFLOW_ENABLED,
        "mlflow_sample_rate": core.MLFLOW_SAMPLE_RATE,
        "ocr_max_image_dim": core.OCR_MAX_IMAGE_DIM,
        "ocr_num_ctx": core.OCR_NUM_CTX,
        "ocr_num_predict": core.OCR_NUM_PREDICT,
        "ocr_concurrency": core.OCR_CONCURRENCY,
        "agent_num_ctx": core.AGENT_NUM_CTX,
        "max_agent_steps": core._MAX_AGENT_STEPS,
        "deployment": "docker" if Path("/.dockerenv").exists() else "local",
    }


def configuration_gaps(config: dict[str, Any]) -> list[str]:
    """Fields that must be filled before a run counts as reproducible.

    Returned rather than raised: a pilot run with gaps is still worth recording, but
    the gaps must travel with it instead of being discovered later.
    """
    gaps = []
    if not config.get("commit"):
        gaps.append("commit is unknown (not a git checkout?)")
    if config.get("git_dirty"):
        gaps.append("working tree is dirty — the commit does not describe what ran")
    if not config.get("ollama_host"):
        gaps.append("OLLAMA_HOST is unset — the endpoint that served the run is unrecorded")
    if not config.get("vision_model_digest") or not config.get("agent_model_digest"):
        gaps.append("model digests are unset — mutable tags cannot identify a model")
    if not config.get("ledger_db_sha256"):
        gaps.append("ledger database could not be hashed — the input data is unpinned")
    return gaps


# --------------------------------------------------------------------------- #
# Writing results
# --------------------------------------------------------------------------- #
def write_result(name: str, payload: dict[str, Any], kind: str = "raw",
                 config: dict[str, Any] | None = None,
                 identifier: str | None = None) -> Path:
    """Write one result file and return its path.

    The configuration record is attached to every file, so a result can never be
    separated from the setup that produced it.
    """
    if kind not in _KINDS:
        raise ValueError(f"kind must be one of {sorted(_KINDS)}, got {kind!r}")

    identifier = identifier or run_id()
    config = config if config is not None else capture_configuration()
    document = {
        "run_id": identifier,
        "name": name,
        "configuration": config,
        "configuration_gaps": configuration_gaps(config),
        "results": payload,
    }

    directory = _KINDS[kind]
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{identifier}_{name}.json"
    path.write_text(json.dumps(document, indent=2, default=str))
    return path


def read_result(path: Path | str) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


# --------------------------------------------------------------------------- #
# Summarizing
# --------------------------------------------------------------------------- #
def rate(numerator: int, denominator: int) -> float | None:
    """A rate, or `None` when there are no applicable cases.

    Returning 0.0 or 1.0 for an empty denominator would report a metric that was never
    measured as if it had been — the single easiest way to overstate an evaluation.
    """
    if denominator <= 0:
        return None
    return numerator / denominator


def summarize(case_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-case pass/fail records into counts and rates.

    Each record needs `case_id` and `passed`; `checks` (name -> bool) is optional and
    produces a per-check breakdown. Failures are retained in the output.
    """
    total = len(case_results)
    passed = sum(1 for r in case_results if r.get("passed"))

    per_check: dict[str, dict[str, Any]] = {}
    for record in case_results:
        for check, ok in (record.get("checks") or {}).items():
            entry = per_check.setdefault(check, {"passed": 0, "total": 0, "failed_cases": []})
            entry["total"] += 1
            if ok:
                entry["passed"] += 1
            else:
                entry["failed_cases"].append(record.get("case_id"))
    for entry in per_check.values():
        entry["rate"] = rate(entry["passed"], entry["total"])

    return {
        "cases": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": rate(passed, total),
        "checks": per_check,
        "failed_case_ids": [r.get("case_id") for r in case_results if not r.get("passed")],
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    command = argv[0] if argv else "config"

    if command in ("-h", "--help", "help"):
        print(__doc__)
        print("Usage:\n"
              "  python -m evaluation.report config   Print the tested-configuration capture\n"
              "  python -m evaluation.report gaps     Exit non-zero if the capture is incomplete")
        return 0

    if command not in ("config", "gaps"):
        print(f"unknown command: {command}", file=sys.stderr)
        return 2

    config = capture_configuration()
    gaps = configuration_gaps(config)

    if command == "config":
        print(json.dumps(config, indent=2, default=str))

    if gaps:
        print("\nConfiguration gaps — this run is not fully reproducible:", file=sys.stderr)
        for gap in gaps:
            print(f"  - {gap}", file=sys.stderr)
        return 1 if command == "gaps" else 0

    if command == "gaps":
        print("Configuration capture is complete.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
