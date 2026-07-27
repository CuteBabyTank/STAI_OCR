"""
conftest.py — test wiring for the evaluation suite.

The import-order problem
------------------------
`core.DB_PATH` is resolved from `LEDGER_DB_PATH` at import time, and `core._connect()`
binds it as a default argument value. Once `core` is imported, the database it writes
to is fixed for the life of the process. So `LEDGER_DB_PATH` must be set *before* the
first `import core` anywhere in the session.

pytest loads conftest.py before the test modules in its directory, so setting the
environment variable at module scope here (not inside a fixture) is what makes this
work. Nothing in this package may import `core` or `finance` at module scope.

Isolation
---------
Because the path cannot change per test, the `finance_fixture` fixture instead rebuilds
the database file at that one path before each test. `_connect()` opens a fresh
connection per call, so no stale handle survives the rebuild. Every test therefore
starts from the identical known state in `seed_finance.EXPECTED`, and tests that write
cannot leak into each other.

Safety
------
The fixture database lives under `evaluation/fixtures/`, never at the repo root, so a
developer's real `ledger.db` is never opened, seeded, or deleted by the test suite.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# The one database this test session may touch. Keep it outside the repository and
# unique to this process so fixture rebuilds cannot inherit stale SQLite handles.
TEST_DB = Path(tempfile.gettempdir()) / f"snag-evaluation-{os.getpid()}" / "ledger.db"
os.environ["LEDGER_DB_PATH"] = str(TEST_DB)

# Keep evaluation runs out of the developer's MLflow store. Tests assert on
# behaviour, not on traces, and a test run should not pollute recorded runs.
os.environ.setdefault("MLFLOW_ENABLED", "0")


@pytest.fixture
def finance_fixture():
    """Rebuild the deterministic finance fixture and hand back its expected state.

    Function-scoped: every test gets the same clean known-good database.
    """
    from evaluation.fixtures import seed_finance

    expected = seed_finance.build(TEST_DB)
    yield expected


@pytest.fixture
def finance():
    """The `finance` module, imported only after LEDGER_DB_PATH is set."""
    import finance as _finance

    return _finance


@pytest.fixture
def core():
    """The `core` module, imported only after LEDGER_DB_PATH is set."""
    import core as _core

    return _core


@pytest.fixture
def accounts_by_name(finance):
    """Map account name -> row, including archived ones."""

    def _lookup():
        return {a["name"]: a for a in finance.list_accounts(include_archived=True)}

    return _lookup
