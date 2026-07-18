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
"""

from __future__ import annotations

import json

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

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
        data, disambiguation_reasons, confidence = await run_in_threadpool(_work)
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
    """Update a receipt's editable header fields (vendor, date, amounts, category…).
    Only whitelisted fields are written; unknown keys are ignored."""
    row = update_receipt(receipt_id, payload)
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
