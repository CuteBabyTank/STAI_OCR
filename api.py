"""
api.py — REST API for STAI_OCR.

Run with:
    uvicorn api:app --host 0.0.0.0 --port 8000

Endpoints:
    POST /extract        multipart file upload -> validated receipt JSON
    GET  /receipts        list saved receipts (memory)
    POST /ask             {"question": "..."} -> SQL agent over the ledger
    POST /search          {"query": "..."} -> RAG semantic search over receipts
    POST /agent           {"question": "..."} -> ReAct agent (routes SQL vs RAG) + trace
    POST /agent/stream     same as /agent but streams the reasoning as SSE
    GET  /health           liveness check
"""

from __future__ import annotations

import json

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from core import (
    DEFAULT_MODEL,
    AGENT_MODEL,
    GuardrailError,
    add_income,
    agent_run,
    agent_stream,
    analytics_summary,
    ask_ledger,
    delete_income,
    delete_receipt,
    expense_summary,
    extract_receipt_validated,
    get_receipt_items,
    list_budgets,
    list_income,
    list_receipts,
    rag_answer,
    save_receipt,
    semantic_search,
    set_budget,
)

app = FastAPI(title="STAI_OCR Receipt API", version="2.0")


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
    return {"status": "ok"}


@app.post("/extract")
async def extract(file: UploadFile = File(...), model: str = DEFAULT_MODEL):
    image_bytes = await file.read()
    try:
        data, disambiguation_reasons, confidence = extract_receipt_validated(
            image_bytes, model=model, content_type=file.content_type
        )
    except GuardrailError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    receipt_id = save_receipt(
        data, file.filename or "upload",
        flagged=bool(disambiguation_reasons), confidence=confidence,
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


@app.get("/receipts")
def receipts(limit: int = 100):
    return {"receipts": list_receipts(limit=limit)}


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
