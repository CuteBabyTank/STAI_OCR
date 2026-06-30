"""
api.py — REST API for STAI_OCR.

Run with:
    uvicorn api:app --host 0.0.0.0 --port 8000

Endpoints:
    POST /extract        multipart file upload -> validated receipt JSON
    GET  /receipts        list saved receipts (memory)
    POST /ask             {"question": "..."} -> NL question over the ledger (SQL agent)
    GET  /health           liveness check
"""

from __future__ import annotations

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel

from core import (
    DEFAULT_MODEL,
    GuardrailError,
    ask_ledger,
    extract_receipt_validated,
    list_receipts,
    save_receipt,
)

app = FastAPI(title="STAI_OCR Receipt API", version="1.0")


class AskRequest(BaseModel):
    question: str
    model: str = "llama3.2:3b"


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
    try:
        return ask_ledger(req.question, model=req.model)
    except GuardrailError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc