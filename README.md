# STAI_OCR — Receipt Processor & Ledger Agent

A drag-and-drop web app that reads **any purchase receipt** — restaurant, cafe,
grocery, retail, pharmacy — with a **local vision model** and extracts the useful
fields (merchant, tax ID, line items, subtotal, tax/VAT, discounts, total, cash
and change) into an editable ledger you can export to CSV / Excel.

On top of the ledger sits a **ReAct agent** you can talk to in plain English. It
decides on its own whether a question needs a **database query** (totals, counts,
top vendors) or a **semantic search** (what you bought, finding a specific
receipt), runs the right tool, and **streams its reasoning** so you can watch it
think. It answers questions about a single receipt or across your whole history.

Everything runs **locally and free** via [Ollama](https://ollama.com); no data
leaves your machine.

---

## Architecture

```
web-next/              Next.js frontend (drag-and-drop scan, dashboard,
                        streaming chat agent, measured OCR confidence)
extraction.py          Pure extraction primitives: prompt, JSON coercion +
                        clean-up, reconciliation (no UI, no heavy deps)
core.py                Backend pipeline: schema validation, guardrails,
                        disambiguation, confidence scoring, SQLite memory,
                        RAG retriever, SQL agent, ReAct agent, MLflow logging
api.py                  FastAPI REST API the frontend calls
ledger.db               SQLite memory + vector store, created on first run
Dockerfile               API container (backend)
docker-compose.yml       web + api + ollama + mlflow, wired together
```

**Three models, all local via Ollama.** These are the defaults in `core.py` /
`extraction.py`; each is overridable by env var:

| Model              | Role                                          | Env var        |
| ------------------ | --------------------------------------------- | -------------- |
| `qwen2.5vl:7b`     | vision/OCR — reads the receipt image          | `VISION_MODEL` |
| `qwen2.5:latest`   | text — SQL agent, RAG answerer, ReAct planner | `AGENT_MODEL`  |
| `nomic-embed-text` | embeddings — powers semantic search (RAG)     | `EMBED_MODEL`  |

> **`docker-compose.yml` overrides the first two** to `gemma4:e4b` / `gemma4:12b`,
> because the container targets the shared class Ollama endpoint rather than a local
> model. So the model actually in use depends on how you launched the app. Never cite
> a default from this table when recording an evaluation run — read the effective
> value from `GET /health` instead. See `evaluation/CONFIGURATION.md`.

### Data flow

```
┌─────────────────────────────────────────────────────────────────┐
│                      Receipt image upload                        │
│              (Next.js UI  →  POST /extract)                      │
└──────────────────────────────┬──────────────────────────────────┘
                               │
                    ┌──────────▼──────────┐
                    │  validate_input()    │  guardrail: file type (PNG/JPG/
                    │                     │  WEBP/BMP) + size (≤ 8 MB)
                    └──────────┬──────────┘
                               │ passes
                    ┌──────────▼──────────┐
                    │  ollama qwen2.5vl:7b  │  local vision model
                    │  (OCR extraction)   │  temperature=0, format="json"
                    └──────────┬──────────┘
                               │ raw JSON
          ┌────────────────────▼────────────────────┐
          │          Post-processing pipeline         │
          │  _clean_items()   strip "qty @ price"    │
          │  _remap_summary_lines()  move tax lines  │
          │  _dedupe_items()  collapse duplicates    │
          │  _fix_payment_fields()  Total/Cash/Change│
          │  _coerce_numeric_fields()  str → float   │
          └────────────────────┬────────────────────┘
                               │
                    ┌──────────▼──────────┐
                    │  validate_output()   │  guardrail: Pydantic ReceiptData
                    │                     │  schema — reject on mismatch
                    └──────────┬──────────┘
                               │
                    ┌──────────▼──────────┐
                    │ needs_disambiguation │  flag if: no total, no items,
                    │      ()              │  discount without TIN, or line
                    │                     │  items don't reconcile to total
                    └──────────┬──────────┘
                               │
               ┌───────────────┼───────────────┐
               │               │               │
    ┌──────────▼────┐  ┌───────▼──────┐  ┌────▼──────────┐
    │  save_receipt  │  │  Editable    │  │  MLflow run    │
    │  → ledger.db   │  │  ledger UI   │  │  (latency,     │
    │  (SQLite)      │  │  CSV / Excel │  │  token counts, │
    └───────────────┘  └──────────────┘  │  errors)       │
                                         └────────────────┘

────────────────────────────────────────────────────────────────
         ReAct Agent  (Ask your receipts / POST /agent)
────────────────────────────────────────────────────────────────

  Natural-language question
           │
  ┌────────▼─────────┐   qwen2.5 reasons in a Thought → Action →
  │  ReAct planner    │   Observation loop and picks a tool. Reasoning
  │  (streamed)       │   is streamed token-by-token to the UI.
  └───┬───────────┬──┘
      │           │
  "numbers?"   "content?"
      │           │
 ┌────▼─────┐ ┌───▼───────────┐
 │sql_ledger│ │search_receipts│   TOOLS
 └────┬─────┘ └───┬───────────┘
      │           │
 generate     embed query (nomic-embed-text),
 SELECT →     cosine-match against stored
 _validate_   receipt vectors, retrieve top-k
 sql() →      documents
 run on            │
 ledger.db    ┌────▼──────────┐
      │       │ receipt_docs  │  vector store (SQLite): one
      │       │ (SQLite BLOB) │  embedded document per receipt
      │       └───────────────┘
      │           │
      └─────┬─────┘
            │ Observation(s) fed back into the loop
  ┌─────────▼─────────┐
  │  Final Answer      │  grounded only in what the tools returned
  └───────────────────┘

  Scope guardrail: the agent can be pinned to a single receipt / the
  current upload batch (receipt_ids) or run across the whole ledger.

  Also exposed directly:
    POST /ask     → sql_ledger tool only (SQL agent)
    POST /search  → search_receipts tool only (RAG)
```

---

## Module coverage

| Module                 | Where                                                                                                                                                                                                                                                                               |
| ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Prompt Engineering     | `EXTRACTION_PROMPT` (strict transcription), `_SQL_AGENT_PROMPT` (few-shot SQL), `_RAG_PROMPT`, `_REACT_PROMPT` (tool-routing)                                                                                                                                                       |
| Structured Outputs     | `core.ReceiptData` / `LineItem` — Pydantic-validated JSON from the model                                                                                                                                                                                                            |
| Guardrails             | `core.validate_input` (file type/size) + `core.validate_output` (schema) + SQL-agent read-only query filter + agent `receipt_ids` scope                                                                                                                                             |
| Disambiguation         | `core.needs_disambiguation` — flags missing totals/items/mismatched tax ID for human review instead of guessing                                                                                                                                                                     |
| Memory                 | `core.save_receipt` / `list_receipts` — persistent SQLite ledger across sessions                                                                                                                                                                                                    |
| RAG                    | `core.semantic_search` / `rag_answer` — embeds each receipt (`nomic-embed-text`) into `receipt_docs`, retrieves by cosine similarity, answers grounded in retrieved docs (keyword fallback if the embed model is absent)                                                            |
| SQL Agent              | `core.ask_ledger` — NL question → generated SQL → executed against `ledger.db`                                                                                                                                                                                                      |
| ReAct Agent            | `core.agent_stream` — Thought→Action→Observation loop that routes between the SQL tool and the RAG tool, streams reasoning, and cites its sources                                                                                                                                   |
| Tool Use               | the agent's two tools — `sql_ledger` (SQL over the ledger) and `search_receipts` (vector search) — plus the `qwen2.5vl:7b` vision tool                                                                                                                                              |
| Chat UI                | "Ask your receipts" streaming agent panel — floating robot assistant in the Aperture (Next.js) dashboard; the original Streamlit panel still works standalone (`streamlit run receipt_processor.py`) but isn't part of the Docker stack                                             |
| Personal Finance Layer | `core.add_income` / `list_income`, `core.set_budget` / `list_budgets`, `core.expense_summary`, `core.analytics_summary` — income tracking, per-category budgets, and the period-aware analytics payload behind the dashboard                                                        |
| API Endpoint           | `api.py` — receipts (`POST /extract`, `GET /receipts`, `GET /receipts/{id}/items`, `DELETE /receipts/{id}`), dashboard (`GET /summary`, `GET /analytics`, `GET/POST/DELETE /income`, `GET/PUT /budgets`), agents (`POST /ask`, `POST /search`, `POST /agent`, `POST /agent/stream`) |
| LLMOps Monitoring      | every extraction, SQL-agent, RAG, and ReAct-agent call wrapped in `mlflow.start_run()`, logging latency, params, token counts, tools used, and errors                                                                                                                               |
| Dockerization          | `Dockerfile` + `docker-compose.yml`                                                                                                                                                                                                                                                 |

### Module ownership

Fill in owners before the presentation — each member owns and can walk through ≥ 2 modules.

| Owner              | Modules                                              |
| ------------------ | ---------------------------------------------------- |
| _Nathaniel Adiong_ | Chat UI · API Endpoints · Dockerization              |
| _Clarence Ang_     | Prompt Engineering · Structured Outputs · Guardrails |
| _Fraser Sim_       | RAG · Memory · Tool Use · Disambiguation             |
| _Aaron Go_         | SQL Agent · ReAct Agent · LLMOps Monitoring          |

---

## Features

- Drag-and-drop one or many receipt images (PNG / JPG / WEBP / BMP)
- Local OCR via the `qwen2.5vl:7b` vision model (no API key, no per-receipt cost)
- Faithful extraction — values are transcribed, never calculated or assumed;
  missing fields are left blank rather than guessed
- Automatic clean-up: removes `2 @ price` notation from item names, de-duplicates
  repeated line items, and fixes mis-assigned Total / Cash / Change
- Reconciliation check flags receipts where line items don't add up to the total
- **Measured OCR confidence** — every field gets a real confidence score computed
  from the vision model's token-level logprobs (not a self-reported number), shown
  as color-coded badges on every receipt and a per-field breakdown on expand
- Every processed receipt is saved to a persistent SQLite ledger **and** indexed
  into a local vector store for semantic search
- **Ask your receipts** — a ReAct agent answers in plain English, choosing between
  a SQL query ("How much did I spend this month?") and a semantic search ("What did
  I buy at the coffee shop?"), and **streams its reasoning** as it works
- Scope any question to a **single receipt / the current upload** or the **whole
  ledger** with one toggle
- Multi-currency aware (₱, $, €, £, ¥, …) — reads and displays the currency printed
  on each receipt
- Exposed as a REST API for headless/integration use, in addition to the UI

---

## Requirements

- macOS / Linux / Windows
- Python 3.9+
- [Ollama](https://ollama.com/download)
- Docker + Docker Compose (optional, for containerized run)

---

## Setup (local, no Docker)

```bash
# 1. Install the backend (Python) dependencies
pip install -r requirements.txt
```

> If the project ships a `requirements.txt`, you can use that instead:
>
> ```bash
> pip install -r requirements.txt
> ```

```bash
# 2. Install Ollama (macOS example; see ollama.com/download for other platforms)
brew install ollama

# 3. Pull the models
#    qwen2.5vl:7b     — vision/OCR model that reads receipt images    (~6.0 GB, one-time)
#    qwen2.5:latest   — text model: SQL agent, RAG answerer, ReAct    (~4.7 GB, one-time)
#    nomic-embed-text — embedding model for semantic search (RAG)     (~275 MB, one-time)
ollama pull qwen2.5vl:7b
ollama pull qwen2.5:latest
ollama pull nomic-embed-text
```

> The app still runs without `nomic-embed-text` — semantic search transparently
> falls back to keyword matching — but retrieval quality is much better with it.

> **Note:** the text model cannot read images, and `llama3.2-vision` needs a newer
> Ollama engine than some builds ship. This app uses `qwen2.5vl:7b` for OCR, which is
> tuned for document/invoice extraction with structured JSON output, and the text
> model only for the SQL agent / RAG / ReAct planner.
>
> `qwen2.5:latest` routes tools and summarizes numbers far more reliably than a 3B
> model, which mis-routed tools, looped, and garbled amounts. On a constrained host
> set `AGENT_MODEL=llama3.2:3b` for a smaller/faster (and measurably worse) agent.

---

## Running locally

```bash
# 1. Start the Ollama server (leave this running in its own terminal)
ollama serve

# 2. In another terminal, launch the UI
streamlit run receipt_processor.py

# 2b. ...and/or launch the REST API
uvicorn api:app --host 0.0.0.0 --port 8000
# interactive docs at http://localhost:8000/docs

# 2c. ...and/or launch the MLflow dashboard to see traces
mlflow ui --backend-store-uri file:./mlruns
```

Streamlit prints a local URL (default <http://localhost:8501>). Drag a receipt
onto the dropzone, click **Process receipts**, review/edit the ledger, then
download CSV or Excel. Use the **Ask your receipts** panel at the bottom to talk
to the ReAct agent — watch it stream its reasoning, pick a tool, and answer.

---

## Running with Docker

```bash
docker compose up --build
```

This brings up four containers:

- `ollama` — pulls `qwen2.5vl:7b`, `qwen2.5:latest`, and `nomic-embed-text` automatically on first start
- `web` — the **Aperture** UI (Next.js) at <http://localhost:8502> — a clean white
  dashboard with KPI stat tiles, a cashflow chart, a top-vendors breakdown, a
  budgets card with per-category monthly limits, an income panel, a slide-over
  "Scan receipts" panel (drag-and-drop multi-upload → OCR), a monthly
  past-receipts view, and a floating robot chat assistant. It calls the `api`
  service; the browser hits same-origin `/api/*`, which Next rewrites to the API
  (no CORS)
- `api` — the REST API at <http://localhost:8001> (docs at `/docs`)
- `mlflow` — the MLflow tracking UI at <http://localhost:5001>
  The frontend source lives in `web-next/`. The original Streamlit app
  (`receipt_processor.py`) is kept in the repo but no longer wired into the stack;
  run it standalone with `streamlit run receipt_processor.py` if you want it.

First start will take a while while the models download (~7.8 GB total).

---

## REST API

**Receipts**

| Method   | Path                           | Description                                                                  |
| -------- | ------------------------------ | ---------------------------------------------------------------------------- |
| `GET`    | `/health`                      | Liveness check + effective config (model, concurrency, image dim)            |
| `POST`   | `/extract`                     | Multipart image upload → validated receipt JSON (first page of a PDF)        |
| `POST`   | `/extract/batch`               | Multipart **multi-file** upload (images and/or PDFs) → one result per page, processed concurrently, with per-page error isolation |
| `GET`    | `/receipts`                    | List saved receipts from the ledger (paginated via `?limit=`)                |
| `GET`    | `/receipts/{receipt_id}/items` | Line items for a single receipt                                              |
| `DELETE` | `/receipts/{receipt_id}`       | Delete a receipt and everything derived from it (line items + RAG embedding) |

**Dashboard / personal finance**

| Method   | Path                  | Description                                                                                                                                                                          |
| -------- | --------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `GET`    | `/summary`            | Aggregated spending: total, count, per-category totals, top category, dominant currency                                                                                              |
| `GET`    | `/analytics`          | Period-aware dashboard payload (cashflow series, category totals, budgets, top vendors, period-over-period deltas). Query params: `granularity` (`month` \| `year`), `year`, `month` |
| `GET`    | `/income`             | List income entries                                                                                                                                                                  |
| `POST`   | `/income`             | Add an income entry — `{"source", "amount", "currency"?, "date"?, "recurring"?}`                                                                                                     |
| `DELETE` | `/income/{income_id}` | Delete an income entry                                                                                                                                                               |
| `GET`    | `/budgets`            | List per-category monthly budgets                                                                                                                                                    |
| `PUT`    | `/budgets`            | Create/update a budget — `{"category", "monthly_limit", "currency"?}`                                                                                                                |

**Agents**

| Method | Path            | Description                                                           |
| ------ | --------------- | --------------------------------------------------------------------- |
| `POST` | `/ask`          | `{"question": "..."}` → answer via the **SQL agent** only             |
| `POST` | `/search`       | `{"query": "..."}` → **RAG** retrieval + grounded answer + sources    |
| `POST` | `/agent`        | `{"question": "..."}` → **ReAct agent** answer + full reasoning trace |
| `POST` | `/agent/stream` | Same as `/agent`, streamed as Server-Sent Events                      |

All agent endpoints accept an optional `"receipt_ids": [..]` to scope the answer
to specific receipts (e.g. a single receipt).

Interactive docs: <http://localhost:8000/docs>

---

## Scaling & production (bulk imports up to ~1000 pages)

The extraction pipeline is built to ingest large drops of images or multi-hundred
-page PDFs without falling over:

- **Image preprocessing** — every image is EXIF-rotated and downscaled (longest
  edge → `OCR_MAX_IMAGE_DIM`, default 1600px) before inference. This cuts the
  vision model's image prefill by ~30% with no accuracy loss on legible receipts,
  and lets large phone photos through instead of bouncing off the size limit.
- **PDF support** — PDFs are rasterized to one image per page (`pypdfium2`) and
  each page becomes its own receipt.
- **Concurrent batch path** — `/extract/batch` runs a bounded thread pool of
  vision calls (`OCR_CONCURRENCY`); the real ceiling is the Ollama server's
  `OLLAMA_NUM_PARALLEL`, which `OCR_CONCURRENCY` should match. One unreadable page
  is reported in-band and never aborts the run. The web UI uploads in chunks so a
  huge drop streams progress instead of blocking.
- **SQLite under concurrency** — WAL mode + a busy timeout so many workers can
  save at once without `database is locked`.
- **Deferred embedding** — bulk saves skip the per-receipt RAG embedding; it is
  backfilled in parallel on the next semantic search, so import throughput isn't
  gated on it.
- **Tunable observability** — MLflow tracing can be sampled or disabled for bulk
  loads to avoid per-page overhead.

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `OCR_MAX_IMAGE_DIM` | `1600` | Longest-edge downscale target (px); `0` disables |
| `OCR_JPEG_QUALITY` | `88` | Re-encode quality after preprocessing |
| `OCR_CONCURRENCY` | `3` | Parallel vision calls per batch (match `OLLAMA_NUM_PARALLEL`) |
| `OCR_NUM_CTX` / `OCR_NUM_PREDICT` | `8192` / `4096` | Ollama context / max output tokens |
| `OLLAMA_KEEP_ALIVE` | `30m` | Keep the model resident between requests |
| `OCR_PDF_RENDER_SCALE` | `2.0` | PDF rasterization scale (~144 DPI) |
| `OCR_MAX_IMAGE_BYTES` | `26214400` | Hard upload ceiling (25 MB) |
| `MLFLOW_ENABLED` | `1` | Turn all MLflow tracing on/off |
| `MLFLOW_SAMPLE_RATE` | `1.0` | Fraction of extraction traces to keep |
| `SQLITE_BUSY_TIMEOUT_MS` | `30000` | Lock wait before erroring |
| `LEDGER_DB_PATH` | `./ledger.db` | Ledger location |

> **Note:** `docker-compose.yml` points the API at a shared remote Ollama endpoint
> (`OLLAMA_HOST`), so no local GPU is needed. To run fully offline, set
> `OLLAMA_HOST` to a local Ollama (e.g. `http://host.docker.internal:11434`) and
> `VISION_MODEL` / `AGENT_MODEL` to locally-pulled models.

---

## SQLite ledger schema

Two tables are created automatically in `ledger.db` on first run:

**`receipts`** — one row per processed receipt  
`id`, `source_file`, `processed_at`, `vendor_name`, `vendor_tin`, `vendor_address`,
`receipt_number`, `receipt_date`, `subtotal`, `vatable_sales`, `vat_exempt_sales`,
`zero_rated_sales`, `vat_amount`, `discount`, `discount_type`, `total_amount`,
`cash`, `change`, `currency`, `flagged`

**`line_items`** — one row per line item, linked by `receipt_id`  
`id`, `receipt_id`, `description`, `quantity`, `unit_price`, `amount`

**`receipt_docs`** — RAG vector store, one row per receipt  
`receipt_id`, `doc` (natural-language summary), `embedding` (float32 BLOB)

Two more tables back the dashboard's personal-finance layer (income vs. spend,
budgets), created on first run by `init_finance_tables()`:

**`income`** — one row per income entry  
`id`, `source`, `amount`, `currency`, `income_date`, `recurring`, `created_at`

**`budgets`** — one row per category, upserted via `PUT /budgets`  
`category` (primary key), `monthly_limit`, `currency`

Example questions you can ask the agent in plain English:

Routed to **`sql_ledger`** (numbers/aggregates):

- _"How much did I spend this month?"_
- _"What are my top 5 vendors by total spend?"_
- _"How much tax did I pay in total?"_
- _"Which receipts were flagged for review?"_
  Routed to **`search_receipts`** (content/semantic):
- _"What did I buy at the coffee shop?"_
- _"Which receipt had the biggest single item?"_
- _"Find the receipt with the birthday cake."_
- _"Summarize what's on my grocery receipt."_

---

## Using from a Jupyter / Colab notebook

```python
%pip install -r requirements.txt --quiet
!ollama pull qwen2.5vl:7b
!ollama pull qwen2.5:latest
!ollama pull nomic-embed-text

from core import extract_receipt_validated
data, review_reasons, confidence = extract_receipt_validated(open("Receipt.jpg","rb").read())
print(data.total_amount, "overall confidence:", confidence["overall"])
```

Then run `streamlit run receipt_processor.py` from a terminal as above.

---

## Tips for best accuracy

`qwen2.5vl:7b` is an 8B local vision model — accurate, but not flawless on hard photos. For
the best results:

- Use a **flat, well-lit, straight-on** photo with no shadow over the figures
- Avoid blur and steep angles
- Always glance at the editable table and fix any value the ⚠ flag points to
  before exporting; receipts flagged for **disambiguation** (missing total,
  missing items, discount without a matching TIN) are called out explicitly
  and should always be reviewed before being treated as final
  For tougher receipts you can switch the model name in the sidebar to any other
  Ollama vision model you've pulled.

---

## How it works

1. The image passes **input guardrails** (file type/size) before anything is sent
   to the model.
2. The image is sent to the local `qwen2.5vl:7b` model with a strict
   transcription prompt (`format="json"`, `temperature=0`).
3. The JSON response is **post-processed deterministically**: item descriptions are
   cleaned, duplicate items merged, mis-filed summary/tax lines moved to their
   proper fields, and Total / Cash / Change corrected using receipt arithmetic
   (always reassigning numbers actually read off the receipt — never inventing).
4. The cleaned JSON is validated against a **Pydantic schema** (output guardrail);
   anything that doesn't fit the contract is rejected rather than silently
   passed through.
5. **Reconciliation + disambiguation** checks decide whether the receipt can be
   auto-filed or needs a human's eyes first.
6. **Confidence** is measured from the model's per-token logprobs: each field's
   value is scored by the geometric mean of its tokens' probabilities — a real read
   of the output distribution, never a self-reported number. This is shown as
   badges in the UI and stored with the receipt.
7. The result is saved to a **persistent SQLite ledger** (memory) with its
   confidence. It is also turned into a short document, **embedded**, and stored in
   the `receipt_docs` **vector store** for RAG.
8. Every model call is timed and logged to **MLflow** for observability (latency,
   token counts, confidence, errors).
9. The **"Ask your receipts"** panel / `POST /agent` runs a **ReAct agent**: it
   reasons in a Thought→Action→Observation loop and routes each question to the
   right tool —
   - **`sql_ledger`** — a **SQL agent** that generates and runs a read-only
     `SELECT` against `ledger.db` (great for totals, counts, top-N), or
   - **`search_receipts`** — a **RAG** retriever that embeds the query, finds the
     most similar receipts by cosine similarity, and answers grounded in them.
     The agent streams its reasoning to the UI, and can be scoped to one receipt or
     the whole ledger. `POST /ask` and `POST /search` expose the two tools directly.

The frontend theme and components live in `web-next/`.
