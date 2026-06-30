# STAI_OCR — Philippine Receipt Processor

A drag-and-drop web app that reads Philippine sales receipts / official receipts
(OR) / sales invoices (SI) with a **local vision model** and extracts the fields
needed for BIR bookkeeping — vendor, TIN, line items, subtotal, VAT, discounts,
total, cash and change — into an editable ledger you can export to CSV / Excel.

Everything runs **locally and free** via [Ollama](https://ollama.com); no data
leaves your machine.

---

## Architecture

```
receipt_processor.py   Streamlit UI (drag-and-drop, editable ledger, ledger chat)
core.py                Shared pipeline: schema validation, guardrails,
                        disambiguation, SQLite memory, SQL agent, MLflow logging
api.py                  FastAPI REST API (same pipeline, headless)
ledger.db               SQLite memory store, created on first run
Dockerfile               App container (UI or API, selectable via CMD)
docker-compose.yml       app + api + ollama + mlflow, wired together
```

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
                    │  ollama minicpm-v    │  local vision model
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
               SQL Agent  (Ask your ledger / POST /ask)
────────────────────────────────────────────────────────────────

  Natural-language question
           │
  ┌────────▼────────┐
  │ ollama           │  llama3.2:3b (text-only)
  │ llama3.2:3b      │  generates a SELECT statement
  └────────┬────────┘
           │ raw SQL
  ┌────────▼────────┐
  │ _validate_sql()  │  guardrail: must start with SELECT,
  │                  │  no INSERT/UPDATE/DELETE/DROP/ALTER,
  │                  │  no semicolons (multi-statement block)
  └────────┬────────┘
           │ safe SQL         ┌──────────────────┐
           ├─────────────────►│   ledger.db       │
           │ rows             │   (SQLite)        │
           ◄─────────────────┘└──────────────────┘
           │
  ┌────────▼────────┐
  │ _generate_answer │  llama3.2:3b turns rows into a
  │ ()               │  plain-English answer
  └────────┬────────┘
           │
     Natural-language answer + raw rows returned
```

---

## Module coverage

| Module | Where |
|---|---|
| Structured Outputs | `core.ReceiptData` / `LineItem` — Pydantic-validated JSON from the model |
| Guardrails | `core.validate_input` (file type/size) + `core.validate_output` (schema) + SQL-agent read-only query filter |
| Disambiguation | `core.needs_disambiguation` — flags missing totals/items/mismatched TIN for human review instead of guessing |
| Memory | `core.save_receipt` / `list_receipts` — persistent SQLite ledger across sessions |
| SQL Agent | `core.ask_ledger` — NL question → generated SQL → executed against `ledger.db` |
| Chat UI | "Ask your ledger" box in the Streamlit app |
| API Endpoint | `api.py` — `POST /extract`, `GET /receipts`, `POST /ask` |
| LLMOps Monitoring | every extraction and SQL-agent call wrapped in `mlflow.start_run()`, logging latency, params, token counts, and errors |
| Dockerization | `Dockerfile` + `docker-compose.yml` |


---

## Features

- Drag-and-drop one or many receipt images (PNG / JPG / WEBP / BMP)
- Local OCR via the `minicpm-v` vision model (no API key, no per-receipt cost)
- Faithful extraction — values are transcribed, never calculated or assumed;
  missing fields are left blank rather than guessed
- Automatic clean-up: removes `2 @ price` notation from item names, de-duplicates
  repeated line items, and fixes mis-assigned Total / Cash / Change
- Reconciliation check flags receipts where line items don't add up to the total
- Editable tables — correct any misread value before exporting
- Export to CSV (summary + line items) or a single Excel workbook
- Every processed receipt is saved to a persistent SQLite ledger, queryable in
  plain English ("How much VAT did I pay this month?") via a built-in SQL agent
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
pip install streamlit ollama pandas openpyxl pillow \
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
#    minicpm-v  — vision/OCR model that reads receipt images  (~5.5 GB, one-time)
#    llama3.2:3b — text-only model used by the SQL agent       (~2 GB, one-time)
ollama pull minicpm-v
ollama pull llama3.2:3b
```

> **Note:** `llama3.2:3b` is text-only and cannot read images, and
> `llama3.2-vision` needs a newer Ollama engine than some builds ship. This app
> uses `minicpm-v` for OCR, which is tuned for receipts, and `llama3.2:3b` only
> for the text-only SQL agent.

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
download CSV or Excel. Use the **Ask your ledger** box at the bottom to query
everything you've ever processed in plain English.

---

## Running with Docker

```bash
docker compose up --build
```

This brings up four containers:

- `ollama` — pulls `minicpm-v` and `llama3.2:3b` automatically on first start
- `web` — the Streamlit UI at <http://localhost:8501>
- `api` — the REST API at <http://localhost:8000> (docs at `/docs`)
- `mlflow` — the MLflow tracking UI at <http://localhost:5000>

First start will take a while while the models download (~7.5 GB total).

---

## REST API

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness check |
| `POST` | `/extract` | Multipart image upload → validated receipt JSON |
| `GET` | `/receipts` | List saved receipts from the ledger (paginated via `?limit=`) |
| `POST` | `/ask` | `{"question": "..."}` → natural-language answer via SQL agent |

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

Example ledger questions you can ask in plain English:

- *"How much VAT did I pay this month?"*
- *"What's my total spend at Jollibee?"*
- *"Which receipts were flagged for review?"*
- *"How much did I save from Senior Citizen discounts?"*
- *"What are my top 5 vendors by total spend?"*

---

## Using from a Jupyter / Colab notebook

```python
%pip install streamlit ollama pandas openpyxl pillow fastapi uvicorn pydantic mlflow --quiet
!ollama pull minicpm-v
!ollama pull llama3.2:3b
```

Then run `streamlit run receipt_processor.py` from a terminal as above.

---

## Tips for best accuracy

`minicpm-v` is an 8B local model — accurate, but not flawless on hard photos. For
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
2. The image is sent to the local `minicpm-v` model with a strict
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
   editable tables, and exported.
7. Every step (1–4) is timed and logged to **MLflow** for observability.
8. Separately, the "Ask your ledger" box / `POST /ask` lets you query the
   accumulated ledger in plain English — a small **SQL agent** generates and runs
   a read-only `SELECT` against `ledger.db` and returns the rows.

The Streamlit theme lives in `.streamlit/config.toml`.
