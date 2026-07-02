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
    agent_run,
    agent_stream,
    ask_ledger,
    extract_receipt_validated,
    list_receipts,
    rag_answer,
    save_receipt,
    semantic_search,
)

app = FastAPI(title="STAI_OCR Receipt API", version="2.0")


class AskRequest(BaseModel):
    question: str
    model: str = AGENT_MODEL
    # Optional: scope the answer to specific receipts (e.g. a single receipt).
    receipt_ids: list[int] | None = None


class SearchRequest(BaseModel):
    query: str
    k: int = 4
    receipt_ids: list[int] | None = None


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/extract")
async def extract(file: UploadFile = File(...), model: str = DEFAULT_MODEL):
    image_bytes = await file.read()
    try:
        data, disambiguation_reasons = extract_receipt_validated(
            image_bytes, model=model, content_type=file.content_type
        )
    except GuardrailError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    receipt_id = save_receipt(data, file.filename or "upload", flagged=bool(disambiguation_reasons))
    return {
        "receipt_id": receipt_id,
        "data": data.model_dump(),
        "needs_review": bool(disambiguation_reasons),
        "review_reasons": disambiguation_reasons,
    }


@app.get("/receipts")
def receipts(limit: int = 100):
    return {"receipts": list_receipts(limit=limit)}


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
        return agent_run(req.question, model=req.model, receipt_ids=req.receipt_ids)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/agent/stream")
def agent_stream_endpoint(req: AskRequest):
    """Same as /agent but streams each reasoning event as Server-Sent Events, so a
    client can show the agent thinking in real time."""

    def event_source():
        for ev in agent_stream(req.question, model=req.model, receipt_ids=req.receipt_ids):
            yield f"data: {json.dumps(ev, default=str)}\n\n"

    return StreamingResponse(event_source(), media_type="text/event-stream")
