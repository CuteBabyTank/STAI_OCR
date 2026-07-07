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
receipt_processor.py   Streamlit UI (drag-and-drop, editable ledger, streaming agent)
core.py                Shared pipeline: schema validation, guardrails,
                        disambiguation, SQLite memory, RAG retriever, SQL agent,
                        ReAct agent, MLflow logging
api.py                  FastAPI REST API (same pipeline, headless)
ledger.db               SQLite memory + vector store, created on first run
Dockerfile               App container (UI or API, selectable via CMD)
docker-compose.yml       app + api + ollama + mlflow, wired together
```

**Three models, all local via Ollama:**

| Model | Role |
|---|---|
| `qwen2.5vl:7b` | vision/OCR — reads the receipt image |
| `llama3.2:3b` | text — SQL agent, RAG answerer, ReAct planner |
| `nomic-embed-text` | embeddings — powers semantic search (RAG) |

### Data flow

```
┌─────────────────────────────────────────────────────────────────┐
│                      Receipt image upload                        │
│              (Streamlit UI  or  POST /extract)                   │
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
  ┌────────▼─────────┐   llama3.2:3b reasons in a Thought → Action →
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

| Module | Where |
|---|---|
| Prompt Engineering | `EXTRACTION_PROMPT` (strict transcription), `_SQL_AGENT_PROMPT` (few-shot SQL), `_RAG_PROMPT`, `_REACT_PROMPT` (tool-routing) |
| Structured Outputs | `core.ReceiptData` / `LineItem` — Pydantic-validated JSON from the model |
| Guardrails | `core.validate_input` (file type/size) + `core.validate_output` (schema) + SQL-agent read-only query filter + agent `receipt_ids` scope |
| Disambiguation | `core.needs_disambiguation` — flags missing totals/items/mismatched tax ID for human review instead of guessing |
| Memory | `core.save_receipt` / `list_receipts` — persistent SQLite ledger across sessions |
| RAG | `core.semantic_search` / `rag_answer` — embeds each receipt (`nomic-embed-text`) into `receipt_docs`, retrieves by cosine similarity, answers grounded in retrieved docs (keyword fallback if the embed model is absent) |
| SQL Agent | `core.ask_ledger` — NL question → generated SQL → executed against `ledger.db` |
| ReAct Agent | `core.agent_stream` — Thought→Action→Observation loop that routes between the SQL tool and the RAG tool, streams reasoning, and cites its sources |
| Tool Use | the agent's two tools — `sql_ledger` (SQL over the ledger) and `search_receipts` (vector search) — plus the `qwen2.5vl:7b` vision tool |
| Chat UI | "Ask your receipts" streaming agent panel in the Streamlit app |
| API Endpoint | `api.py` — `POST /extract`, `GET /receipts`, `POST /ask`, `POST /search`, `POST /agent`, `POST /agent/stream` |
| LLMOps Monitoring | every extraction, SQL-agent, RAG, and ReAct-agent call wrapped in `mlflow.start_run()`, logging latency, params, token counts, tools used, and errors |
| Dockerization | `Dockerfile` + `docker-compose.yml` |

### Module ownership

Fill in owners before the presentation — each member owns and can walk through ≥ 2 modules.

| Owner | Modules |
|---|---|
| _Member A_ | Prompt Engineering · Structured Outputs |
| _Member B_ | RAG · Guardrails |
| _Member C_ | ReAct Agent · SQL Agent |
| _Member D_ | LLMOps Monitoring · Tool Use · Dockerization |


---

## Features

- Drag-and-drop one or many receipt images (PNG / JPG / WEBP / BMP)
- Local OCR via the `qwen2.5vl:7b` vision model (no API key, no per-receipt cost)
- Faithful extraction — values are transcribed, never calculated or assumed;
  missing fields are left blank rather than guessed
- Automatic clean-up: removes `2 @ price` notation from item names, de-duplicates
  repeated line items, and fixes mis-assigned Total / Cash / Change
- Reconciliation check flags receipts where line items don't add up to the total
- Editable tables — correct any misread value before exporting
- Export to CSV (summary + line items) or a single Excel workbook
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
# 1. Install Python dependencies
pip install streamlit ollama pandas numpy openpyxl pillow \
            fastapi uvicorn pydantic mlflow
```

> If the project ships a `requirements.txt`, you can use that instead:
> ```bash
> pip install -r requirements.txt
> ```

```bash
# 2. Install Ollama (macOS example; see ollama.com/download for other platforms)
brew install ollama

# 3. Pull the models
#    qwen2.5vl:7b      — vision/OCR model that reads receipt images   (~6.0 GB, one-time)
#    llama3.2:3b      — text model: SQL agent, RAG answerer, ReAct    (~2 GB,   one-time)
#    nomic-embed-text — embedding model for semantic search (RAG)     (~275 MB, one-time)
ollama pull qwen2.5vl:7b
ollama pull llama3.2:3b
ollama pull nomic-embed-text
```

> The app still runs without `nomic-embed-text` — semantic search transparently
> falls back to keyword matching — but retrieval quality is much better with it.

> **Note:** `llama3.2:3b` is text-only and cannot read images, and
> `llama3.2-vision` needs a newer Ollama engine than some builds ship. This app
> uses `qwen2.5vl:7b` for OCR, which is tuned for document/invoice extraction with
> structured JSON output, and `llama3.2:3b` only for the text-only SQL agent.

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

- `ollama` — pulls `qwen2.5vl:7b`, `llama3.2:3b`, and `nomic-embed-text` automatically on first start
- `web` — the Streamlit UI at <http://localhost:8501>
- `api` — the REST API at <http://localhost:8000> (docs at `/docs`)
- `mlflow` — the MLflow tracking UI at <http://localhost:5000>

First start will take a while while the models download (~7.8 GB total).

---

## REST API

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness check |
| `POST` | `/extract` | Multipart image upload → validated receipt JSON |
| `GET` | `/receipts` | List saved receipts from the ledger (paginated via `?limit=`) |
| `POST` | `/ask` | `{"question": "..."}` → answer via the **SQL agent** only |
| `POST` | `/search` | `{"query": "..."}` → **RAG** retrieval + grounded answer + sources |
| `POST` | `/agent` | `{"question": "..."}` → **ReAct agent** answer + full reasoning trace |
| `POST` | `/agent/stream` | Same as `/agent`, streamed as Server-Sent Events |

All question endpoints accept an optional `"receipt_ids": [..]` to scope the answer
to specific receipts (e.g. a single receipt).

Interactive docs: <http://localhost:8000/docs>

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

Example questions you can ask the agent in plain English:

Routed to **`sql_ledger`** (numbers/aggregates):
- *"How much did I spend this month?"*
- *"What are my top 5 vendors by total spend?"*
- *"How much tax did I pay in total?"*
- *"Which receipts were flagged for review?"*

Routed to **`search_receipts`** (content/semantic):
- *"What did I buy at the coffee shop?"*
- *"Which receipt had the biggest single item?"*
- *"Find the receipt with the birthday cake."*
- *"Summarize what's on my grocery receipt."*

---

## Using from a Jupyter / Colab notebook

```python
%pip install streamlit ollama pandas numpy openpyxl pillow fastapi uvicorn pydantic mlflow --quiet
!ollama pull qwen2.5vl:7b
!ollama pull llama3.2:3b
!ollama pull nomic-embed-text
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
6. The result is saved to a **persistent SQLite ledger** (memory), shown in
   editable tables, and exported. It is also turned into a short document,
   **embedded**, and stored in the `receipt_docs` **vector store** for RAG.
7. Every step (1–4) is timed and logged to **MLflow** for observability.
8. The **"Ask your receipts"** panel / `POST /agent` runs a **ReAct agent**: it
   reasons in a Thought→Action→Observation loop and routes each question to the
   right tool —
   - **`sql_ledger`** — a **SQL agent** that generates and runs a read-only
     `SELECT` against `ledger.db` (great for totals, counts, top-N), or
   - **`search_receipts`** — a **RAG** retriever that embeds the query, finds the
     most similar receipts by cosine similarity, and answers grounded in them.

   The agent streams its reasoning to the UI, and can be scoped to one receipt or
   the whole ledger. `POST /ask` and `POST /search` expose the two tools directly.
  
The Streamlit theme lives in `.streamlit/config.toml`.
