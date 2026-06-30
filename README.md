# STAI_OCR — Philippine Receipt Processor

A drag-and-drop web app that reads Philippine sales receipts / official receipts
(OR) / sales invoices (SI) with a **local vision model** and extracts the fields
needed for BIR bookkeeping — vendor, TIN, line items, subtotal, VAT, discounts,
total, cash and change — into an editable ledger you can export to CSV / Excel.

Everything runs **locally and free** via [Ollama](https://ollama.com); no data
leaves your machine.

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

## Requirements

- macOS / Linux / Windows
- Python 3.9+
- [Ollama](https://ollama.com/download)

## Setup

```bash
# 1. Install Python dependencies
pip install streamlit ollama pandas openpyxl pillow

# 2. Install Ollama (macOS example; see ollama.com/download for other platforms)
brew install ollama

# 3. Pull the vision model (~5.5 GB, one-time download)
ollama pull minicpm-v
```

> **Note:** `llama3.2:3b` is text-only and cannot read images, and
> `llama3.2-vision` needs a newer Ollama engine than some builds ship. This app
> uses `minicpm-v`, which is tuned for OCR and reads receipt figures accurately.

## Running the app

```bash
# 1. Start the Ollama server (leave this running in its own terminal)
ollama serve

# 2. In another terminal, launch the app
streamlit run receipt_processor.py
```

Streamlit prints a local URL (default <http://localhost:8501>) and opens it in
your browser. Drag a receipt onto the dropzone, click **Process receipts**,
review/edit the ledger, then download CSV or Excel.

### Using it from a Jupyter / Colab notebook

```python
%pip install streamlit ollama pandas openpyxl pillow --quiet
!ollama pull minicpm-v
```

Then run `streamlit run receipt_processor.py` from a terminal as above.

## Tips for best accuracy

`minicpm-v` is an 8B local model — accurate, but not flawless on hard photos. For
the best results:

- Use a **flat, well-lit, straight-on** photo with no shadow over the figures
- Avoid blur and steep angles
- Always glance at the editable table and fix any value the ⚠ flag points to
  before exporting

For tougher receipts you can switch the model name in the sidebar to any other
Ollama vision model you've pulled.

## How it works

1. The image is sent to the local `minicpm-v` model with a strict
   transcription prompt (`format="json"`, `temperature=0`).
2. The JSON response is post-processed deterministically: item descriptions are
   cleaned, duplicate items merged, mis-filed summary/tax lines moved to their
   proper fields, and Total / Cash / Change corrected using receipt arithmetic
   (always reassigning numbers actually read off the receipt — never inventing).
3. Results are reconciled, shown in editable tables, and exported.

The Streamlit theme lives in `.streamlit/config.toml`.
