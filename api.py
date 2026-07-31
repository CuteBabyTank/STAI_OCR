"""
api.py — REST API for STAI_OCR.

Run with:
    uvicorn api:app --host 0.0.0.0 --port 8000

Endpoints:
    POST /extract        multipart file upload (image) -> validated receipt JSON
    POST /extract/batch   multipart multi-file upload (images + PDFs) -> per-page
                          results, processed concurrently. The 1000-page path.
    GET  /receipts        list saved receipts (memory)
    POST /ask             {"question": "..."} -> SQL agent over the ledger
    POST /search          {"query": "..."} -> RAG semantic search over receipts
    POST /agent           {"question": "..."} -> ReAct agent (routes SQL vs RAG) + trace
    POST /agent/stream     same as /agent but streams the reasoning as SSE
    GET  /health           liveness check + effective config
    POST /statements       upload a bank/credit-card statement CSV
    POST /statements/{id}/report  receipt-to-statement discrepancy report
"""

from __future__ import annotations

import json

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel

from reconciliation import (
    ReconciliationError,
    delete_statement,
    discrepancy_report,
    format_discrepancy_report,
    get_statement,
    import_statement,
    list_statements,
    match_statement,
    statement_lines,
)

from core import (
    DEFAULT_MODEL,
    AGENT_MODEL,
    OCR_CONCURRENCY,
    OCR_MAX_IMAGE_DIM,
    GuardrailError,
    add_income,
    agent_run,
    agent_stream,
    analytics_summary,
    ask_ledger,
    delete_income,
    delete_receipt,
    expense_summary,
    extract_batch,
    extract_receipt_validated,
    get_receipt,
    get_receipt_items,
    iter_page_images,
    update_receipt,
    list_budgets,
    list_income,
    list_receipts,
    rag_answer,
    save_receipt,
    semantic_search,
    set_budget,
)
from finance import (
    FinanceError,
    account_balance,
    advance_recurring,
    create_account,
    create_budget_plan,
    create_category,
    create_debt,
    create_goal,
    create_installment,
    create_receivable,
    create_recurring,
    create_tag,
    create_template,
    create_transaction,
    debt_activity,
    delete_account,
    delete_budget_plan,
    delete_category,
    delete_debt,
    delete_goal,
    delete_installment,
    delete_receivable,
    delete_recurring,
    delete_tag,
    delete_template,
    delete_transaction,
    export_backup,
    get_account,
    get_settings,
    get_transaction,
    goal_activity,
    import_backup,
    list_accounts,
    list_budget_plans,
    list_categories,
    list_debt_activity,
    list_debts,
    list_goals,
    list_installments,
    list_receivable_activity,
    list_receivables,
    list_recurring,
    list_tags,
    list_templates,
    list_transactions,
    log_installment_payment,
    net_worth,
    parse_quick_text,
    post_receipt_as_expense,
    receivable_activity,
    set_account_balance,
    set_settings,
    update_account,
    update_goal,
    update_transaction,
    upcoming,
    use_template,
)

app = FastAPI(title="STAI_OCR Receipt API", version="2.1")


class AskRequest(BaseModel):
    question: str
    model: str = AGENT_MODEL
    # Optional: scope the answer to specific receipts (e.g. a single receipt).
    receipt_ids: list[int] | None = None
    # Optional: recent chat turns [{role, text}] so the agent can resolve follow-up
    # references like "those" / "that receipt".
    history: list[dict] | None = None


class SearchRequest(BaseModel):
    query: str
    k: int = 4
    receipt_ids: list[int] | None = None


class IncomeRequest(BaseModel):
    source: str
    amount: float
    currency: str | None = None
    date: str | None = None
    recurring: bool = False


class BudgetRequest(BaseModel):
    category: str
    monthly_limit: float
    currency: str | None = None


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "vision_model": DEFAULT_MODEL,
        "ocr_concurrency": OCR_CONCURRENCY,
        "max_image_dim": OCR_MAX_IMAGE_DIM,
    }


@app.post("/extract")
async def extract(file: UploadFile = File(...), model: str = DEFAULT_MODEL):
    """Single raster image -> one validated receipt. For PDFs or many files at
    once, use /extract/batch (this endpoint reads only the first page of a PDF)."""
    image_bytes = await file.read()

    def _work():
        # A PDF slipping in here shouldn't 500: extract just its first page so the
        # single-receipt contract still holds. Multi-page PDFs belong on /batch.
        first = iter_page_images(image_bytes, file.content_type)[0]
        return extract_receipt_validated(first, model=model, content_type="image/jpeg")

    try:
        # Offload the blocking vision call to a worker thread so the event loop
        # stays free to accept other requests during the ~seconds-long extraction.
        data, disambiguation_reasons, confidence, audit = await run_in_threadpool(_work)
    except GuardrailError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    receipt_id = await run_in_threadpool(
        save_receipt, data, file.filename or "upload",
        bool(disambiguation_reasons), confidence,
    )
    return {
        "receipt_id": receipt_id,
        "data": data.model_dump(),
        "needs_review": bool(disambiguation_reasons),
        "review_reasons": disambiguation_reasons,
        # Measured confidence from the model's token logprobs (0..1), plus the
        # per-field / per-item breakdown so clients can flag weak reads.
        "confidence": confidence,
        # Structured arithmetic audit: every check the receipt failed, with the two
        # numbers and their difference. `review_reasons` above is the `error` subset
        # rendered as prose; this carries the warnings too.
        "audit": audit,
    }


@app.post("/extract/batch")
async def extract_batch_endpoint(
    files: list[UploadFile] = File(...), model: str = DEFAULT_MODEL
):
    """Many files at once (images and/or PDFs) -> one result per page, processed
    with bounded server-side concurrency. PDFs are expanded to a result per page.
    Individual page failures are reported in-band (never abort the batch), so a
    thousand-page import returns partial success rather than a single 500."""
    payloads = []
    for f in files:
        payloads.append((await f.read(), f.content_type, f.filename or "upload"))
    try:
        # extract_batch runs its own thread pool of vision calls; run the whole
        # thing off the event loop so this request doesn't block the server.
        results = await run_in_threadpool(extract_batch, payloads, model)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    ok = sum(1 for r in results if r["error"] is None)
    return {
        "results": results,
        "summary": {"total": len(results), "succeeded": ok, "failed": len(results) - ok},
    }


@app.get("/receipts")
def receipts(limit: int = 100):
    return {"receipts": list_receipts(limit=limit)}


@app.get("/receipts/{receipt_id}")
def receipt_detail(receipt_id: int):
    """Full detail for one receipt: its header row plus its line items."""
    row = get_receipt(receipt_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Receipt {receipt_id} not found")
    return {"receipt": row, "items": get_receipt_items(receipt_id)}


@app.put("/receipts/{receipt_id}")
def edit_receipt(receipt_id: int, payload: dict):
    """Update a receipt's editable header fields (vendor, date, amounts, category,
    the account it was charged to…). Only whitelisted fields are written; unknown
    keys are ignored."""
    try:
        row = update_receipt(receipt_id, payload)
    except GuardrailError as exc:
        # e.g. account_id naming an account that doesn't exist — a bad request from
        # the client, not a server fault, so 422 rather than a 500.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail=f"Receipt {receipt_id} not found")
    return {"receipt": row}


@app.get("/receipts/{receipt_id}/items")
def receipt_items(receipt_id: int):
    return {"items": get_receipt_items(receipt_id)}


@app.delete("/receipts/{receipt_id}")
def remove_receipt(receipt_id: int):
    """Delete a receipt and everything derived from it (line items + RAG embedding),
    so it vanishes from the ledger, the SQL agent, and semantic search."""
    removed = delete_receipt(receipt_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Receipt {receipt_id} not found")
    return {"deleted": receipt_id}


@app.get("/summary")
def summary():
    """Aggregated spending for the dashboard: total, count, per-category totals,
    top category, and the dominant currency."""
    return expense_summary()


@app.get("/analytics")
def analytics(granularity: str = "month", year: int | None = None, month: int | None = None):
    """Period-aware dashboard payload. `granularity` is "month" or "year"; `year`
    and `month` pick the focused period (defaulting to the latest with activity).
    Returns the cashflow bar series plus period-scoped category totals, budgets,
    vendors, totals and period-over-period deltas — all consistent with each other."""
    return analytics_summary(granularity=granularity, year=year, month=month)


@app.get("/income")
def get_income():
    return {"income": list_income()}


@app.post("/income")
def post_income(req: IncomeRequest):
    income_id = add_income(req.source, req.amount, req.currency, req.date, req.recurring)
    return {"id": income_id}


@app.delete("/income/{income_id}")
def remove_income(income_id: int):
    if not delete_income(income_id):
        raise HTTPException(status_code=404, detail=f"Income {income_id} not found")
    return {"deleted": income_id}


@app.get("/budgets")
def get_budgets():
    return {"budgets": list_budgets()}


@app.put("/budgets")
def put_budget(req: BudgetRequest):
    set_budget(req.category, req.monthly_limit, req.currency)
    return {"category": req.category, "monthly_limit": req.monthly_limit}


# --------------------------------------------------------------------------- #
# Budget-tracker: accounts, transactions, categories, tags (finance.py)
# --------------------------------------------------------------------------- #
class AccountRequest(BaseModel):
    name: str
    type: str
    opening_balance: float = 0.0
    currency: str | None = None
    include_in_totals: bool = True


class TransactionRequest(BaseModel):
    kind: str                       # expense | income | transfer
    amount: float
    account_id: int | None = None
    to_account_id: int | None = None
    category_id: int | None = None
    note: str | None = None
    occurred_at: str | None = None
    fee: float = 0.0
    receipt_id: int | None = None
    template_id: int | None = None


class BalanceAdjustRequest(BaseModel):
    balance: float


class CategoryRequest(BaseModel):
    name: str
    kind: str                       # expense | income
    color: str | None = None
    parent_id: int | None = None


class TagRequest(BaseModel):
    name: str
    kind: str = "Custom"
    color: str | None = None


@app.get("/accounts")
def get_accounts(include_archived: bool = False):
    return {"accounts": list_accounts(include_archived=include_archived)}


@app.post("/accounts")
def post_account(req: AccountRequest):
    try:
        account_id = create_account(
            req.name, req.type, req.opening_balance, req.currency, req.include_in_totals
        )
    except FinanceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"account": get_account(account_id)}


@app.get("/accounts/{account_id}")
def account_detail(account_id: int):
    acct = get_account(account_id)
    if acct is None:
        raise HTTPException(status_code=404, detail=f"Account {account_id} not found")
    return {"account": acct}


@app.put("/accounts/{account_id}")
def put_account(account_id: int, payload: dict):
    try:
        acct = update_account(account_id, payload)
    except FinanceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if acct is None:
        raise HTTPException(status_code=404, detail=f"Account {account_id} not found")
    return {"account": acct}


@app.put("/accounts/{account_id}/balance")
def put_account_balance(account_id: int, req: BalanceAdjustRequest):
    """Balance adjustment (PRD §5.3): overwrite an account's balance directly."""
    acct = set_account_balance(account_id, req.balance)
    if acct is None:
        raise HTTPException(status_code=404, detail=f"Account {account_id} not found")
    return {"account": acct}


@app.delete("/accounts/{account_id}")
def remove_account(account_id: int):
    try:
        removed = delete_account(account_id)
    except FinanceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(status_code=404, detail=f"Account {account_id} not found")
    return {"deleted": account_id}


@app.get("/networth")
def get_networth(include_credit: bool = True, show_liabilities: bool = True):
    return net_worth(include_credit=include_credit, show_liabilities=show_liabilities)


@app.get("/transactions")
def get_transactions(
    limit: int = 1000,
    kind: str | None = None,
    account_id: int | None = None,
    category_id: int | None = None,
    search: str | None = None,
):
    return {
        "transactions": list_transactions(
            limit=limit, kind=kind, account_id=account_id,
            category_id=category_id, search=search,
        )
    }


@app.post("/transactions")
def post_transaction(req: TransactionRequest):
    try:
        txn_id = create_transaction(
            req.kind, req.amount, account_id=req.account_id,
            to_account_id=req.to_account_id, category_id=req.category_id,
            note=req.note, occurred_at=req.occurred_at, fee=req.fee,
            receipt_id=req.receipt_id, template_id=req.template_id,
        )
    except FinanceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"transaction": get_transaction(txn_id)}


@app.put("/transactions/{txn_id}")
def put_transaction(txn_id: int, payload: dict):
    try:
        txn = update_transaction(txn_id, payload)
    except FinanceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if txn is None:
        raise HTTPException(status_code=404, detail=f"Transaction {txn_id} not found")
    return {"transaction": txn}


@app.delete("/transactions/{txn_id}")
def remove_transaction(txn_id: int):
    if not delete_transaction(txn_id):
        raise HTTPException(status_code=404, detail=f"Transaction {txn_id} not found")
    return {"deleted": txn_id}


class PostReceiptRequest(BaseModel):
    account_id: int


@app.post("/receipts/{receipt_id}/post")
def post_receipt(receipt_id: int, req: PostReceiptRequest):
    """Bridge an OCR'd receipt into the ledger as an expense against an account."""
    try:
        txn_id = post_receipt_as_expense(receipt_id, req.account_id)
    except FinanceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"transaction": get_transaction(txn_id)}


@app.get("/categories")
def get_categories():
    return {"categories": list_categories()}


@app.post("/categories")
def post_category(req: CategoryRequest):
    try:
        cat_id = create_category(req.name, req.kind, req.color, req.parent_id)
    except FinanceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"id": cat_id}


@app.delete("/categories/{category_id}")
def remove_category(category_id: int):
    try:
        removed = delete_category(category_id)
    except FinanceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not removed:
        raise HTTPException(status_code=404, detail=f"Category {category_id} not found")
    return {"deleted": category_id}


@app.get("/tags")
def get_tags():
    return {"tags": list_tags()}


@app.post("/tags")
def post_tag(req: TagRequest):
    try:
        tag_id = create_tag(req.name, req.kind, req.color)
    except FinanceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"id": tag_id}


@app.delete("/tags/{tag_id}")
def remove_tag(tag_id: int):
    if not delete_tag(tag_id):
        raise HTTPException(status_code=404, detail=f"Tag {tag_id} not found")
    return {"deleted": tag_id}


# --------------------------------------------------------------------------- #
# Plan: budgets, templates, recurring, installments, goals, debts, receivables
# --------------------------------------------------------------------------- #
class BudgetPlanRequest(BaseModel):
    category_id: int
    type: str = "fixed"          # fixed | percent
    interval: str = "monthly"    # daily | weekly | monthly | yearly
    limit_amount: float = 0
    percent: float = 0
    carry_forward: bool = False


class TemplateRequest(BaseModel):
    title: str
    amount: float = 0
    kind: str = "expense"
    account_id: int | None = None
    category_id: int | None = None


class RecurringRequest(BaseModel):
    kind: str = "expense"
    amount: float = 0
    name: str
    account_id: int | None = None
    category_id: int | None = None
    next_due: str | None = None


class InstallmentRequest(BaseModel):
    title: str
    total: float = 0
    monthly: float = 0
    months: int = 0


class InstallmentPaymentRequest(BaseModel):
    account_id: int
    amount: float
    occurred_at: str | None = None


class GoalRequest(BaseModel):
    title: str
    target_amount: float = 0
    current_amount: float = 0
    currency: str | None = None
    target_date: str | None = None


class DebtRequest(BaseModel):
    name: str
    total_amount: float = 0
    paid_amount: float = 0
    currency: str | None = None
    due_date: str | None = None


class ReceivableRequest(BaseModel):
    name: str
    total_amount: float = 0
    collected_amount: float = 0
    currency: str | None = None
    due_date: str | None = None


class ActivityRequest(BaseModel):
    account_id: int
    amount: float
    type: str                    # deposit/withdrawal | payment/borrowing | collection/advance
    occurred_at: str | None = None


def _guard(fn, *a, **k):
    """Run a finance call, mapping FinanceError -> 422."""
    try:
        return fn(*a, **k)
    except FinanceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ---- Budgets ----
@app.get("/budget-plans")
def get_budget_plans():
    return {"budget_plans": list_budget_plans()}


@app.post("/budget-plans")
def post_budget_plan(req: BudgetPlanRequest):
    bid = _guard(create_budget_plan, req.category_id, req.type, req.interval,
                 req.limit_amount, req.percent, req.carry_forward)
    return {"id": bid}


@app.delete("/budget-plans/{plan_id}")
def remove_budget_plan(plan_id: int):
    if not delete_budget_plan(plan_id):
        raise HTTPException(status_code=404, detail="Budget not found")
    return {"deleted": plan_id}


# ---- Templates ----
@app.get("/templates")
def get_templates():
    return {"templates": list_templates()}


@app.post("/templates")
def post_template(req: TemplateRequest):
    tid = _guard(create_template, req.title, req.amount, req.kind, req.account_id, req.category_id)
    return {"id": tid}


@app.post("/templates/{template_id}/use")
def post_use_template(template_id: int):
    txn_id = _guard(use_template, template_id)
    return {"transaction": get_transaction(txn_id)}


@app.delete("/templates/{template_id}")
def remove_template(template_id: int):
    if not delete_template(template_id):
        raise HTTPException(status_code=404, detail="Template not found")
    return {"deleted": template_id}


# ---- Recurring ----
@app.get("/recurring")
def get_recurring():
    return {"recurring": list_recurring()}


@app.post("/recurring")
def post_recurring(req: RecurringRequest):
    rid = _guard(create_recurring, req.kind, req.amount, req.name, req.account_id,
                 req.next_due, req.category_id)
    return {"id": rid}


@app.post("/recurring/{rec_id}/advance")
def post_advance_recurring(rec_id: int):
    return _guard(advance_recurring, rec_id)


@app.delete("/recurring/{rec_id}")
def remove_recurring(rec_id: int):
    if not delete_recurring(rec_id):
        raise HTTPException(status_code=404, detail="Recurring item not found")
    return {"deleted": rec_id}


# ---- Installments ----
@app.get("/installments")
def get_installments():
    return {"installments": list_installments()}


@app.post("/installments")
def post_installment(req: InstallmentRequest):
    iid = _guard(create_installment, req.title, req.total, req.monthly, req.months)
    return {"id": iid}


@app.post("/installments/{plan_id}/pay")
def post_installment_payment(plan_id: int, req: InstallmentPaymentRequest):
    txn_id = _guard(log_installment_payment, plan_id, req.account_id, req.amount, req.occurred_at)
    return {"transaction": get_transaction(txn_id)}


@app.delete("/installments/{plan_id}")
def remove_installment(plan_id: int):
    if not delete_installment(plan_id):
        raise HTTPException(status_code=404, detail="Installment plan not found")
    return {"deleted": plan_id}


# ---- Goals ----
@app.get("/goals")
def get_goals():
    return {"goals": list_goals()}


@app.post("/goals")
def post_goal(req: GoalRequest):
    gid = _guard(create_goal, req.title, req.target_amount, req.current_amount,
                 req.currency, req.target_date)
    return {"id": gid}


@app.put("/goals/{goal_id}")
def put_goal(goal_id: int, payload: dict):
    if not update_goal(goal_id, payload):
        raise HTTPException(status_code=404, detail="Goal not found")
    return {"updated": goal_id}


@app.delete("/goals/{goal_id}")
def remove_goal(goal_id: int):
    if not delete_goal(goal_id):
        raise HTTPException(status_code=404, detail="Goal not found")
    return {"deleted": goal_id}


@app.post("/goals/{goal_id}/activity")
def post_goal_activity(goal_id: int, req: ActivityRequest):
    txn_id = _guard(goal_activity, goal_id, req.account_id, req.amount, req.type, req.occurred_at)
    return {"transaction": get_transaction(txn_id)}


# ---- Debts ----
@app.get("/debts")
def get_debts():
    return {"debts": list_debts()}


@app.post("/debts")
def post_debt(req: DebtRequest):
    did = _guard(create_debt, req.name, req.total_amount, req.paid_amount, req.currency, req.due_date)
    return {"id": did}


@app.delete("/debts/{debt_id}")
def remove_debt(debt_id: int):
    if not delete_debt(debt_id):
        raise HTTPException(status_code=404, detail="Debt not found")
    return {"deleted": debt_id}


@app.get("/debt-activity")
def get_debt_activity_log():
    """Append-only log of debt payments/borrowings (history, not current balances)."""
    return {"activity": list_debt_activity()}


@app.post("/debts/{debt_id}/activity")
def post_debt_activity(debt_id: int, req: ActivityRequest):
    txn_id = _guard(debt_activity, debt_id, req.account_id, req.amount, req.type, req.occurred_at)
    return {"transaction": get_transaction(txn_id)}


# ---- Receivables ----
@app.get("/receivables")
def get_receivables():
    return {"receivables": list_receivables()}


@app.post("/receivables")
def post_receivable(req: ReceivableRequest):
    rid = _guard(create_receivable, req.name, req.total_amount, req.collected_amount,
                 req.currency, req.due_date)
    return {"id": rid}


@app.delete("/receivables/{rec_id}")
def remove_receivable(rec_id: int):
    if not delete_receivable(rec_id):
        raise HTTPException(status_code=404, detail="Receivable not found")
    return {"deleted": rec_id}


@app.get("/receivable-activity")
def get_receivable_activity_log():
    """Append-only log of receivable collections/advances."""
    return {"activity": list_receivable_activity()}


@app.post("/receivables/{rec_id}/activity")
def post_receivable_activity(rec_id: int, req: ActivityRequest):
    txn_id = _guard(receivable_activity, rec_id, req.account_id, req.amount, req.type, req.occurred_at)
    return {"transaction": get_transaction(txn_id)}


# ---- Upcoming ----
@app.get("/upcoming")
def get_upcoming():
    return upcoming()


# ---- Quick-chat NLP ----
class ParseRequest(BaseModel):
    text: str


@app.post("/parse")
def post_parse(req: ParseRequest):
    """Parse a natural-language quick-entry into a draft transaction (PRD §2.2)."""
    return parse_quick_text(req.text)


# ---- Settings ----
@app.get("/settings")
def get_app_settings():
    return {"settings": get_settings()}


@app.put("/settings")
def put_app_settings(payload: dict):
    return {"settings": set_settings(payload)}


# ---- Backup ----
@app.get("/backup/export")
def get_backup_export():
    return export_backup()


@app.post("/backup/import")
def post_backup_import(payload: dict):
    # `replace` defaults to False here, not True: with replace the import clears every
    # finance table first, so defaulting it on made a caller that simply forgot the key
    # destroy the existing ledger. Wiping records has to be asked for explicitly. The
    # UI (web-next/app/settings/page.tsx) sends replace: true, so restore is unchanged.
    return _guard(import_backup, payload, bool(payload.get("replace", False)))


@app.post("/ask")
def ask(req: AskRequest):
    """SQL agent only: natural language -> SELECT -> rows -> answer."""
    try:
        return ask_ledger(req.question, model=req.model, receipt_ids=req.receipt_ids)
    except GuardrailError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/search")
def search(req: SearchRequest):
    """RAG retrieval + grounded answer over the receipt documents."""
    try:
        result = rag_answer(req.query, k=req.k, receipt_ids=req.receipt_ids)
        return result
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/agent")
def agent(req: AskRequest):
    """ReAct agent: reasons, routes to the SQL tool or the RAG search tool as
    needed, and returns the final answer plus the full reasoning trace."""
    try:
        return agent_run(req.question, model=req.model, receipt_ids=req.receipt_ids,
                         history=req.history)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/agent/stream")
def agent_stream_endpoint(req: AskRequest):
    """Same as /agent but streams each reasoning event as Server-Sent Events, so a
    client can show the agent thinking in real time."""

    def event_source():
        for ev in agent_stream(req.question, model=req.model, receipt_ids=req.receipt_ids,
                               history=req.history):
            yield f"data: {json.dumps(ev, default=str)}\n\n"

    # Anti-buffering headers so events reach the browser live through the Next.js
    # proxy / any reverse proxy instead of being held until the stream closes.
    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# --------------------------------------------------------------------------- #
# Statement reconciliation (receipt-to-bank/credit-statement)
# --------------------------------------------------------------------------- #
# Distinct from the receipt-internal arithmetic check that runs during extraction.
# That one asks "does this receipt add up?"; these ask "was it actually charged,
# once, for this amount?". Deterministic — no model is involved.
class MatchRequest(BaseModel):
    receipt_ids: list[int] | None = None
    max_posting_lag_days: int | None = None
    amount_tolerance: float | None = None
    min_merchant_similarity: float | None = None


def _match_overrides(req: "MatchRequest") -> dict:
    """Only pass through the thresholds the caller actually set, so the documented
    defaults in reconciliation.py remain the single source of truth."""
    names = ("max_posting_lag_days", "amount_tolerance", "min_merchant_similarity")
    return {name: getattr(req, name) for name in names if getattr(req, name) is not None}


@app.post("/statements")
async def import_statement_endpoint(
    file: UploadFile = File(...),
    account_id: int | None = None,
    kind: str = "credit_card",
    currency: str = "PHP",
    charges_are_negative: bool = True,
):
    """Upload a bank or credit-card statement CSV.

    `charges_are_negative` describes the *uploaded file's* convention; the stored rows
    are always normalized to negative-is-money-out.
    """
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")

    try:
        return await run_in_threadpool(
            import_statement, text, file.filename or "statement.csv",
            account_id=account_id, kind=kind, currency=currency,
            charges_are_negative=charges_are_negative,
        )
    except ReconciliationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/statements")
def list_statements_endpoint():
    return {"statements": list_statements()}


@app.get("/statements/{statement_id}")
def get_statement_endpoint(statement_id: int):
    statement = get_statement(statement_id)
    if statement is None:
        raise HTTPException(status_code=404, detail="Statement not found")
    return {**statement, "lines": statement_lines(statement_id)}


@app.delete("/statements/{statement_id}")
def delete_statement_endpoint(statement_id: int):
    if not delete_statement(statement_id):
        raise HTTPException(status_code=404, detail="Statement not found")
    return {"deleted": statement_id}


@app.post("/statements/{statement_id}/match")
async def match_statement_endpoint(statement_id: int, req: MatchRequest | None = None):
    """Match this statement's charges against saved receipts."""
    req = req or MatchRequest()
    try:
        return await run_in_threadpool(
            lambda: match_statement(statement_id, receipt_ids=req.receipt_ids,
                                    **_match_overrides(req))
        )
    except ReconciliationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/statements/{statement_id}/report")
async def statement_report_endpoint(statement_id: int, req: MatchRequest | None = None):
    """The discrepancy report: what the bank says that the receipts do not.

    Every charge lands in exactly one bucket (`accounted_for` asserts it), and nothing
    here is auto-corrected — duplicates and discrepancies are flagged for human review.
    """
    req = req or MatchRequest()
    try:
        return await run_in_threadpool(
            lambda: discrepancy_report(statement_id, receipt_ids=req.receipt_ids,
                                       **_match_overrides(req))
        )
    except ReconciliationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/statements/{statement_id}/report.txt")
def statement_report_text_endpoint(statement_id: int):
    """The same report rendered for a human reviewer."""
    try:
        report = discrepancy_report(statement_id)
    except ReconciliationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return PlainTextResponse(format_discrepancy_report(report))
