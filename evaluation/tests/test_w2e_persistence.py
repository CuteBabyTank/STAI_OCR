"""
W2-A / W2-E — receipt persistence and posting fidelity.

Closes two partial checklist items (IMPLEMENTATION_STATUS.md §3.3): "receipt save and
line-item linkage" (W2-A #13), which was only exercised indirectly through the fixture
seeder, and "amount, date, category, account and currency are preserved" (W2-E #3), where
only amount and account were asserted.

Runs offline: `save_receipt` is called with `index=False`, the same flag bulk imports use,
so no embedding call is made.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def receipt(core):
    """A well-formed two-item receipt."""
    return core.ReceiptData(
        vendor_name="SM Supermarket",
        vendor_tin="123-456-789-000",
        vendor_address="Manila",
        receipt_number="OR-00042",
        receipt_date="2026-06-15",
        subtotal=350.0,
        vat_amount=42.0,
        total_amount=350.0,
        currency="PHP",
        items=[
            core.LineItem(description="Rice 5kg", quantity=1, unit_price=250.0, amount=250.0),
            core.LineItem(description="Eggs", quantity=2, unit_price=50.0, amount=100.0),
        ],
    )


# --------------------------------------------------------------------------- #
# Line-item linkage — the join every downstream read depends on
# --------------------------------------------------------------------------- #
def test_saving_a_receipt_writes_its_line_items(finance_fixture, core, receipt):
    receipt_id = core.save_receipt(receipt, "test.jpg", flagged=False, index=False)
    assert len(core.get_receipt_items(receipt_id)) == 2


def test_line_items_are_linked_to_their_own_receipt(finance_fixture, core, receipt):
    """The fixture already contains receipts with items. A missing `WHERE receipt_id`
    would return those too and every per-receipt view would show foreign items."""
    first = core.save_receipt(receipt, "first.jpg", flagged=False, index=False)
    second = core.save_receipt(receipt, "second.jpg", flagged=False, index=False)
    assert len(core.get_receipt_items(first)) == 2
    assert len(core.get_receipt_items(second)) == 2


def test_line_item_fields_survive_the_round_trip(finance_fixture, core, receipt):
    items = core.get_receipt_items(
        core.save_receipt(receipt, "test.jpg", flagged=False, index=False)
    )
    rice = items[0]
    assert rice["description"] == "Rice 5kg"
    assert rice["quantity"] == pytest.approx(1)
    assert rice["unit_price"] == pytest.approx(250.0)
    assert rice["amount"] == pytest.approx(250.0)


def test_line_items_keep_their_printed_order(finance_fixture, core, receipt):
    """Ordered by id, which is insertion order. A user reviewing an extraction against
    the paper receipt is comparing line by line."""
    items = core.get_receipt_items(
        core.save_receipt(receipt, "test.jpg", flagged=False, index=False)
    )
    assert [i["description"] for i in items] == ["Rice 5kg", "Eggs"]


def test_a_receipt_with_no_items_saves_without_items(finance_fixture, core):
    """A receipt whose items failed to extract must still persist — it is flagged for
    review, and losing the header too would lose the evidence."""
    header_only = core.ReceiptData(vendor_name="X", total_amount=100.0, items=[])
    receipt_id = core.save_receipt(header_only, "x.jpg", flagged=True, index=False)
    assert core.get_receipt_items(receipt_id) == []
    assert core.get_receipt(receipt_id) is not None


# --------------------------------------------------------------------------- #
# Header persistence
# --------------------------------------------------------------------------- #
def test_header_fields_survive_the_round_trip(finance_fixture, core, receipt):
    saved = core.get_receipt(
        core.save_receipt(receipt, "test.jpg", flagged=False, index=False)
    )
    assert saved["vendor_name"] == "SM Supermarket"
    assert saved["vendor_tin"] == "123-456-789-000"
    assert saved["receipt_number"] == "OR-00042"
    assert saved["receipt_date"] == "2026-06-15"
    assert saved["total_amount"] == pytest.approx(350.0)
    assert saved["currency"] == "PHP"


def test_the_review_flag_is_persisted(finance_fixture, core, receipt):
    """`flagged` is what the review queue and the agent's `WHERE flagged = 1` read."""
    flagged_id = core.save_receipt(receipt, "a.jpg", flagged=True, index=False)
    clean_id = core.save_receipt(receipt, "b.jpg", flagged=False, index=False)
    assert core.get_receipt(flagged_id)["flagged"] == 1
    assert core.get_receipt(clean_id)["flagged"] == 0


def test_the_source_file_is_recorded(finance_fixture, core, receipt):
    """Traceability back to the uploaded image."""
    receipt_id = core.save_receipt(receipt, "IMG_1234.jpg", flagged=False, index=False)
    assert core.get_receipt(receipt_id)["source_file"] == "IMG_1234.jpg"


def test_a_category_is_resolved_on_save(finance_fixture, core, receipt):
    """`save_receipt` stores `categorize(data)`, not the raw model field, so a receipt
    always lands in the fixed taxonomy the budget side can map."""
    saved = core.get_receipt(
        core.save_receipt(receipt, "test.jpg", flagged=False, index=False)
    )
    assert saved["category"]


def test_unknown_receipts_read_back_as_none(finance_fixture, core):
    assert core.get_receipt(999_999) is None
    assert core.get_receipt_items(999_999) == []


# --------------------------------------------------------------------------- #
# Posting fidelity — what carries across the receipt/finance bridge
# --------------------------------------------------------------------------- #
def test_posting_preserves_the_amount(finance_fixture, core, finance, receipt,
                                      accounts_by_name):
    receipt_id = core.save_receipt(receipt, "test.jpg", flagged=False, index=False)
    txn_id = finance.post_receipt_as_expense(receipt_id, accounts_by_name()["Cash"]["id"])
    assert finance.get_transaction(txn_id)["amount"] == pytest.approx(350.0)


def test_posting_preserves_the_receipt_date(finance_fixture, core, finance, receipt,
                                            accounts_by_name):
    """The transaction must be dated when the money was spent, not when it was
    scanned — otherwise it lands in the wrong budget period."""
    receipt_id = core.save_receipt(receipt, "test.jpg", flagged=False, index=False)
    txn_id = finance.post_receipt_as_expense(receipt_id, accounts_by_name()["Cash"]["id"])
    assert finance.get_transaction(txn_id)["occurred_at"] == "2026-06-15"


def test_posting_targets_the_requested_account(finance_fixture, core, finance, receipt,
                                               accounts_by_name):
    receipt_id = core.save_receipt(receipt, "test.jpg", flagged=False, index=False)
    account_id = accounts_by_name()["BPI Checking"]["id"]
    txn_id = finance.post_receipt_as_expense(receipt_id, account_id)
    assert finance.get_transaction(txn_id)["account_id"] == account_id


def test_posting_carries_the_vendor_name_into_the_note(finance_fixture, core, finance,
                                                      receipt, accounts_by_name):
    """The vendor is how a user recognizes the row in their transaction history."""
    receipt_id = core.save_receipt(receipt, "test.jpg", flagged=False, index=False)
    txn_id = finance.post_receipt_as_expense(receipt_id, accounts_by_name()["Cash"]["id"])
    assert finance.get_transaction(txn_id)["note"] == "SM Supermarket"


def test_posting_maps_the_receipt_category_to_a_finance_category(
    finance_fixture, core, finance, accounts_by_name
):
    """`_category_id_for_name` resolves the receipt's category string against the
    expense taxonomy. Without it a posted receipt is uncategorized and invisible to
    every budget."""
    groceries = core.ReceiptData(
        vendor_name="SM Supermarket", receipt_date="2026-06-15", total_amount=350.0,
        currency="PHP", category="Groceries",
        items=[core.LineItem(description="Rice", quantity=1, unit_price=350.0, amount=350.0)],
    )
    receipt_id = core.save_receipt(groceries, "test.jpg", flagged=False, index=False)
    txn_id = finance.post_receipt_as_expense(receipt_id, accounts_by_name()["Cash"]["id"])

    category_id = finance.get_transaction(txn_id)["category_id"]
    assert category_id is not None
    names = {c["id"]: c["name"] for c in finance.list_categories()}
    assert names[category_id].lower() == core.get_receipt(receipt_id)["category"].lower()


def test_posting_a_receipt_whose_category_has_no_finance_match_still_posts(
    finance_fixture, core, finance, receipt, accounts_by_name
):
    """Category mapping is best-effort. An unmatched category must leave the
    transaction uncategorized rather than block the post."""
    receipt_id = core.save_receipt(receipt, "test.jpg", flagged=False, index=False)
    with core._connect() as con:
        con.execute("UPDATE receipts SET category = ? WHERE id = ?",
                    ("Nonexistent Category", receipt_id))
        con.commit()

    txn_id = finance.post_receipt_as_expense(receipt_id, accounts_by_name()["Cash"]["id"])
    assert finance.get_transaction(txn_id)["category_id"] is None


# --------------------------------------------------------------------------- #
# Currency — a known architectural limitation, characterized rather than assumed
# --------------------------------------------------------------------------- #
# The breakdown's W2-E item lists currency among the fields that must be preserved.
# It cannot be: `transactions` has **no currency column** (see the schema in
# `finance.init_finance_schema`). The ledger is single-currency by construction, so a
# non-PHP receipt loses its currency at the posting boundary. Recorded here as
# "Not applicable to the actual architecture" with the consequence made explicit,
# rather than silently dropped from the checklist.
def test_the_receipt_keeps_its_currency(finance_fixture, core, receipt):
    receipt_id = core.save_receipt(receipt, "test.jpg", flagged=False, index=False)
    assert core.get_receipt(receipt_id)["currency"] == "PHP"


def test_a_posted_transaction_carries_no_currency_of_its_own(
    finance_fixture, core, finance, receipt, accounts_by_name
):
    """**Known limitation.** Posting a USD receipt produces a transaction
    indistinguishable from a PHP one — the amount is carried across as a bare number.
    Nothing converts it and nothing records the original unit. Any multi-currency
    ledger work must start here."""
    usd = core.ReceiptData(
        vendor_name="Amazon", receipt_date="2026-06-15", total_amount=100.0,
        currency="USD",
        items=[core.LineItem(description="Book", quantity=1, unit_price=100.0, amount=100.0)],
    )
    receipt_id = core.save_receipt(usd, "usd.jpg", flagged=False, index=False)
    txn_id = finance.post_receipt_as_expense(receipt_id, accounts_by_name()["Cash"]["id"])

    transaction = finance.get_transaction(txn_id)
    assert "currency" not in transaction
    assert transaction["amount"] == pytest.approx(100.0)  # 100 USD posted as bare 100
