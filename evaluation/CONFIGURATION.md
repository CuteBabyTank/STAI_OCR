# Tested-Configuration Card

Required by W0 ("Freeze an evaluation configuration"). This records **what the repository
specifies**, at the audited commit. It is not yet a record of an executed evaluation run.

> **This configuration has not been frozen for a run yet.** No evaluation run has been
> executed. Fields marked **RECORD AT RUNTIME** must be captured from the live system at
> the moment of each run and must never be back-filled from the defaults in this file —
> see the model-default conflict below.

---

## Code identity

| Field | Value |
|---|---|
| Commit | `9ac15ec9634ad3b42cb26e3da625a9722233dbaa` |
| Branch | `main` |
| Working tree | clean at audit time |
| Python | 3.12.13 (`.venv`) |
| Platform audited on | macOS (Darwin 25.5.0) |

---

## Model configuration — **conflicting defaults, resolve at runtime**

There is no single "the" default. Three sources disagree:

| Role | `core.py` / `extraction.py` | `docker-compose.yml` | README |
|---|---|---|---|
| Vision / OCR | `qwen2.5vl:7b` | `gemma4:e4b` | `qwen2.5vl:7b` |
| Agent | `qwen2.5:latest` | `gemma4:12b` | `llama3.2:3b` *(README §models)* / `qwen2.5:latest` *(README notebook section)* |
| Embedding | `nomic-embed-text` | `nomic-embed-text` | `nomic-embed-text` |

**Authoritative source at runtime:** `GET /health` returns the effective `vision_model`
(`api.py:150–158`). Capture it per run. For the agent and embedding models, capture the
resolved `core.AGENT_MODEL` / `core.EMBED_MODEL` values from the running process.

**Record per run:**

| Field | How to capture |
|---|---|
| Vision model **RECORD AT RUNTIME** | `GET /health` → `vision_model` |
| Agent model **RECORD AT RUNTIME** | `core.AGENT_MODEL` in-process |
| Embedding model **RECORD AT RUNTIME** | `core.EMBED_MODEL` in-process |
| Model digests | `ollama list` on the serving host — tags like `:latest` are mutable and must not be relied on |
| `OLLAMA_HOST` **RECORD AT RUNTIME** | Environment of the API process |

---

## Environment variables

Consumed by application code (`core.py`):

| Variable | Code default | Compose value | Effect |
|---|---|---|---|
| `LEDGER_DB_PATH` | `./ledger.db` | `/data/ledger.db` | SQLite ledger location |
| `VISION_MODEL` | `qwen2.5vl:7b` | `gemma4:e4b` | OCR model (`extraction.py:26`) |
| `AGENT_MODEL` | `qwen2.5:latest` | `gemma4:12b` | SQL/RAG/ReAct model (`core.py:438`) |
| `EMBED_MODEL` | `nomic-embed-text` | `nomic-embed-text` | Retrieval embeddings (`core.py:440`) |
| `OCR_MAX_IMAGE_BYTES` | `26214400` (25 MB) | — | Input guardrail ceiling |
| `OCR_MAX_IMAGE_DIM` | `1600` | `1600` | **The live downscale knob** (`core.py:408`) |
| `OCR_JPEG_QUALITY` | `88` | — | Re-encode quality |
| `OCR_PDF_RENDER_SCALE` | `2.0` (~144 DPI) | — | PDF rasterization |
| `OCR_PDF_MAX_PAGES` | `1000` | — | PDF page ceiling |
| `OCR_NUM_CTX` | `8192` | — | Ollama context |
| `OCR_NUM_PREDICT` | `4096` | — | Max output tokens — **README says `1024`; README is stale** |
| `OCR_CONCURRENCY` | `3` | `3` | Parallel vision calls per batch |
| `OLLAMA_KEEP_ALIVE` | `30m` | `30m` | Model residency |
| `MLFLOW_ENABLED` | `true` | — | Tracing toggle — **see caveat below** |
| `MLFLOW_SAMPLE_RATE` | `1.0` | — | Fraction of calls traced |

Consumed by libraries, **not** by application code:

| Variable | Set in code? | Compose value | Note |
|---|---|---|---|
| `OLLAMA_HOST` | No — read by the `ollama` client | `http://103.231.240.155:11434` | **Remote by default.** Not offline. |
| `MLFLOW_TRACKING_URI` | No — read by `mlflow` | `sqlite:////app/mlflow.db` | **Unset locally** → local runs go to `./mlruns`, not the repo's `mlflow.db`. Must be set explicitly for every evaluation run. |

**Dead variable — do not record as meaningful:** `VISION_MAX_DIM` (`core.py:82`) and
`VISION_NUM_CTX` (`core.py:83`) are read into `_VISION_MAX_DIM` / `_VISION_NUM_CTX`, and
`_downscale_image` (`core.py:86`) is defined, but **none is ever called**. Compose sets
`VISION_MAX_DIM=0` (`:40`), which has **no effect**: images are still downscaled to 1600 px
by `preprocess_image` via `OCR_MAX_IMAGE_DIM`. Recording `VISION_MAX_DIM=0` as "no
downscaling" would misstate the tested configuration.

**`MLFLOW_ENABLED=0` caveat:** the clarify early-return path in `agent_stream`
(`core.py:2897–2900`) calls `mlflow.log_metric` directly rather than the guarded
`_mlog_metric`, so a stray run is still created for clarification-path questions even when
tracing is disabled or sampled out.

---

## Data stores

| Store | Path | Tracked in git? | Contents at audit |
|---|---|---|---|
| Ledger | `./ledger.db` (or `LEDGER_DB_PATH`) | **No** — `.gitignore:12` | 6 receipts, 14 line items, 5 receipt_docs, 2 budgets, 0 income; **no finance tables** |
| MLflow | `./mlflow.db` | **No** — `.gitignore:16` | 60 dev runs, experiment `stai_ocr_receipts` (id 1) |
| Receipt image | `./Receipt.jpg` | Yes | The only image fixture in the repository |

Neither database is version-controlled. Reproducing an evaluation run currently requires
out-of-band file transfer — a gap W1 must close with un-ignored fixtures.

---

## Services and ports

| Service | Host port | Container port | Source |
|---|---|---|---|
| Frontend (Next.js) | 8502 | 3000 | `docker-compose.yml:10` |
| API (FastAPI) | 8001 | 8000 | `docker-compose.yml:29` |
| MLflow UI | 5001 | 5000 | `docker-compose.yml:70` — 5001 avoids the macOS AirPlay conflict on 5000 |

---

## Agent behaviour constants

Code-derived, not proposals. Use these instead of copying numbers from lecture examples.

| Constant | Value | Location |
|---|---|---|
| `_MAX_AGENT_STEPS` | `3` | `core.py:2617` |
| Registered tools | `sql_ledger`, `search_receipts` | `core.py:2770` |
| Repeat-call guard | cached on 1st repeat; force-finalize at `repeats >= 2` | `core.py:2963` |
| History window | 10 turns × 600 chars | `core.py:2755` |
| Retrieval `k` | `4` | `core.semantic_search` default |
| SQL retry | 1 retry on a bad query | `core._sql_agent_core` |

---

## Pinned dependencies (`requirements.txt`)

```
ollama==0.6.2
numpy==1.26.4
pillow==10.4.0
fastapi==0.112.2
uvicorn[standard]==0.30.6
pydantic==2.9.2
mlflow==3.14.0
python-multipart==0.0.9
pypdfium2==4.30.0
```

**Not pinned but present in `.venv` and required to run the suite:** `pytest`, `pandas`,
`matplotlib`, `httpx`. **Absent:** `ragas`, `sqlglot`, `jupyter`, `notebook`, `datasets`,
`deepeval`, `langgraph`.

---

## Per-run capture template

Copy into every result file; leave no field blank.

```json
{
  "run_id": "",
  "utc_timestamp": "",
  "commit": "",
  "git_dirty": false,
  "vision_model": "",
  "vision_model_digest": "",
  "agent_model": "",
  "agent_model_digest": "",
  "embed_model": "",
  "ollama_host": "",
  "ledger_db_path": "",
  "ledger_db_sha256": "",
  "mlflow_tracking_uri": "",
  "mlflow_enabled": true,
  "mlflow_sample_rate": 1.0,
  "ocr_max_image_dim": 1600,
  "ocr_num_ctx": 8192,
  "ocr_num_predict": 4096,
  "ocr_concurrency": 3,
  "max_agent_steps": 3,
  "deployment": "local | docker",
  "notes": ""
}
```
