"""
W2-F — the reconciliation HTTP surface, driven through the real FastAPI app.

The W0 audit's own method note is the reason this file exists: defect **D4** (Quick Chat
inflating amounts 1,000,000×) was invisible to 100+ passing unit tests and surfaced only
when the real endpoint was driven. A module that works and a route that works are two
different claims.

These are the first HTTP-level tests in the repository. No model is involved — the
reconciliation path is entirely deterministic.
"""

from __future__ import annotations

import io

import pytest


@pytest.fixture
def client(finance_fixture):
    """A TestClient over the real app, bound to the test ledger.

    `api` is imported lazily for the same reason `core` is: the database path is
    resolved at import time (see conftest.py).
    """
    from fastapi.testclient import TestClient

    import api

    return TestClient(api.app)


@pytest.fixture
def make_receipt(finance_fixture, core):
    def _make(vendor: str, receipt_date: str, total: float) -> int:
        data = core.ReceiptData(
            vendor_name=vendor, receipt_date=receipt_date, total_amount=total,
            currency="PHP",
            items=[core.LineItem(description="Item", quantity=1,
                                 unit_price=total, amount=total)],
        )
        return core.save_receipt(data, f"{vendor}.jpg", flagged=False, index=False)

    return _make


def _upload(client, csv_text: str, filename: str = "june.csv"):
    return client.post(
        "/statements",
        files={"file": (filename, io.BytesIO(csv_text.encode()), "text/csv")},
    )


_STATEMENT = (
    "Posting Date,Description,Amount\n"
    "2026-06-16,POS PURCHASE SM SUPERMARKET MAKATI,-500.00\n"
    "2026-06-18,JOLLIBEE CUBAO,-275.00\n"
    "2026-06-19,MERALCO BILL PAYMENT,-3200.00\n"
)


# --------------------------------------------------------------------------- #
# Upload
# --------------------------------------------------------------------------- #
def test_a_statement_uploads(client):
    response = _upload(client, _STATEMENT)
    assert response.status_code == 200
    assert response.json()["rows"] == 3


def test_the_upload_reports_the_period(client):
    body = _upload(client, _STATEMENT).json()
    assert body["period_start"] == "2026-06-16"
    assert body["period_end"] == "2026-06-19"


def test_a_utf8_bom_file_is_accepted(client):
    """Excel exports a BOM. Failing on it would reject the most common real export."""
    csv_text = "﻿Posting Date,Description,Amount\n2026-06-16,SM,-500.00\n"
    assert _upload(client, csv_text).status_code == 200


def test_a_malformed_statement_is_rejected_with_422_not_500(client):
    """A bad upload is the client's error and must be reported as such, with a message
    naming what was missing."""
    response = _upload(client, "Date,Amount\n2026-06-16,-500.00\n")
    assert response.status_code == 422
    assert "description" in response.json()["detail"].lower()


def test_an_empty_statement_is_rejected(client):
    assert _upload(client, "").status_code == 422


# --------------------------------------------------------------------------- #
# Listing and retrieval
# --------------------------------------------------------------------------- #
def test_statements_can_be_listed(client):
    _upload(client, _STATEMENT)
    body = client.get("/statements").json()
    assert body["statements"]
    assert body["statements"][0]["line_count"] == 3


def test_a_statement_can_be_fetched_with_its_lines(client):
    statement_id = _upload(client, _STATEMENT).json()["statement_id"]
    body = client.get(f"/statements/{statement_id}").json()
    assert len(body["lines"]) == 3
    assert body["lines"][0]["amount"] == pytest.approx(-500.0)


def test_an_unknown_statement_returns_404(client):
    assert client.get("/statements/999999").status_code == 404


def test_a_statement_can_be_deleted(client):
    statement_id = _upload(client, _STATEMENT).json()["statement_id"]
    assert client.delete(f"/statements/{statement_id}").status_code == 200
    assert client.get(f"/statements/{statement_id}").status_code == 404


def test_deleting_an_unknown_statement_returns_404(client):
    assert client.delete("/statements/999999").status_code == 404


# --------------------------------------------------------------------------- #
# Matching and the report
# --------------------------------------------------------------------------- #
def test_matching_pairs_a_receipt_with_its_charge(client, make_receipt):
    receipt_id = make_receipt("SM Supermarket", "2026-06-15", 500.0)
    statement_id = _upload(client, _STATEMENT).json()["statement_id"]

    body = client.post(f"/statements/{statement_id}/match",
                       json={"receipt_ids": [receipt_id]}).json()
    assert body["matches"][0]["receipt_id"] == receipt_id
    assert body["matches"][0]["status"] == "matched"


def test_matching_works_without_a_request_body(client, make_receipt):
    """The common call: reconcile against everything in the ledger."""
    make_receipt("SM Supermarket", "2026-06-15", 500.0)
    statement_id = _upload(client, _STATEMENT).json()["statement_id"]
    assert client.post(f"/statements/{statement_id}/match").status_code == 200


def test_the_report_separates_the_categories(client, make_receipt):
    matched = make_receipt("SM Supermarket", "2026-06-15", 500.0)
    overcharged = make_receipt("Jollibee", "2026-06-17", 250.0)
    statement_id = _upload(client, _STATEMENT).json()["statement_id"]

    report = client.post(f"/statements/{statement_id}/report",
                         json={"receipt_ids": [matched, overcharged]}).json()
    assert report["counts"]["matched"] == 1
    assert report["counts"]["amount_mismatch"] == 1     # Jollibee 250 vs 275
    assert report["counts"]["missing_receipt"] == 1     # Meralco
    assert report["accounted_for"] is True


def test_the_report_names_the_unexplained_total(client, make_receipt):
    matched = make_receipt("SM Supermarket", "2026-06-15", 500.0)
    statement_id = _upload(client, _STATEMENT).json()["statement_id"]
    report = client.post(f"/statements/{statement_id}/report",
                         json={"receipt_ids": [matched]}).json()
    # Jollibee 275 + Meralco 3200 have no receipt in this scope.
    assert report["totals"]["unexplained_total"] == pytest.approx(3_475.0)


def test_the_report_flags_itself_for_review(client, make_receipt):
    make_receipt("SM Supermarket", "2026-06-15", 500.0)
    statement_id = _upload(client, _STATEMENT).json()["statement_id"]
    assert client.post(f"/statements/{statement_id}/report").json()["needs_review"]


def test_thresholds_can_be_overridden_over_http(client, make_receipt):
    """A charge posting six weeks late is outside the default window; widening the
    window from the request must move it into a plain match."""
    receipt_id = make_receipt("SM Supermarket", "2026-05-01", 500.0)
    statement_id = _upload(client, _STATEMENT).json()["statement_id"]

    default = client.post(f"/statements/{statement_id}/match",
                          json={"receipt_ids": [receipt_id]}).json()
    widened = client.post(f"/statements/{statement_id}/match",
                          json={"receipt_ids": [receipt_id],
                                "max_posting_lag_days": 90}).json()
    assert default["matches"][0]["status"] == "date_outside_window"
    assert widened["matches"][0]["status"] == "matched"


def test_omitted_thresholds_do_not_override_the_documented_defaults(client, make_receipt):
    """The request model's fields default to None; passing those through would blank
    the module's defaults. Only fields the caller set may be forwarded."""
    receipt_id = make_receipt("SM Supermarket", "2026-06-15", 500.0)
    statement_id = _upload(client, _STATEMENT).json()["statement_id"]
    body = client.post(f"/statements/{statement_id}/match",
                       json={"receipt_ids": [receipt_id]}).json()
    assert body["matches"][0]["status"] == "matched"


def test_reporting_on_an_unknown_statement_returns_404(client):
    assert client.post("/statements/999999/report").status_code == 404


def test_matching_an_unknown_statement_returns_404(client):
    assert client.post("/statements/999999/match").status_code == 404


# --------------------------------------------------------------------------- #
# Human-readable report
# --------------------------------------------------------------------------- #
def test_the_text_report_renders(client, make_receipt):
    make_receipt("SM Supermarket", "2026-06-15", 500.0)
    statement_id = _upload(client, _STATEMENT).json()["statement_id"]

    response = client.get(f"/statements/{statement_id}/report.txt")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "MERALCO" in response.text


def test_the_text_report_does_not_claim_to_have_corrected_anything(client, make_receipt):
    make_receipt("SM Supermarket", "2026-06-15", 500.0)
    statement_id = _upload(client, _STATEMENT).json()["statement_id"]
    text = client.get(f"/statements/{statement_id}/report.txt").text
    assert "candidates for human review, not corrections" in text


def test_the_text_report_on_an_unknown_statement_returns_404(client):
    assert client.get("/statements/999999/report.txt").status_code == 404


# --------------------------------------------------------------------------- #
# The existing API still works
# --------------------------------------------------------------------------- #
def test_health_still_responds(client):
    """The new routes must not have broken the app's existing surface."""
    assert client.get("/health").status_code == 200


def test_receipts_still_list(client, make_receipt):
    make_receipt("SM Supermarket", "2026-06-15", 500.0)
    assert client.get("/receipts").status_code == 200
