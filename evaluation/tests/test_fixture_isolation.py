from __future__ import annotations

from pathlib import Path

from conftest import REPO_ROOT, TEST_DB
from evaluation.fixtures import seed_finance


def test_fixture_database_is_outside_the_synchronized_repository():
    assert not Path(TEST_DB).resolve().is_relative_to(REPO_ROOT.resolve())


def test_fixture_can_be_rebuilt_after_seeding(finance_fixture):
    seed_finance.build(TEST_DB)


def test_receipt_read_releases_the_fixture_database(finance_fixture, core):
    assert core.get_receipt(1) is not None
    seed_finance.build(TEST_DB)
