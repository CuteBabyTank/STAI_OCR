# Qwen2.5-VL 7B — OCR accuracy / precision / recall on 10 receipts

**Run date:** 2026-08-09 · **Branch:** `qwen-vl-ocr-eval` · **Model:** `qwen2.5vl:7b`
**Dataset:** `evaluation/datasets/receipts_gt_10.json` (10 Philippine receipts, hand-labelled)
**Harness:** `evaluation/run_ocr_benchmark.py` · **Raw output:** `results/raw/ocr-qwen2.5vl-7b.json`

---

## Headline

| Population | Accuracy | Precision | Recall | F1 | TP | FP | FN | TN |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| **Scalar fields** (140 slots) | **82.2%** | **86.1%** | **92.1%** | 89.0% | 105 | 17 | 9 | 15 |
| **Line items** (51 slots) | **98.0%** | **98.0%** | **100.0%** | 99.0% | 50 | 1 | 0 | — |
| **Combined** | **86.3%** | **89.6%** | **94.5%** | 92.0% | 155 | 18 | 9 | 15 |

All 10 receipts extracted without a single crash, parse failure, or timeout.

Recall (92.1%) sits well above precision (86.1%), and that gap is the whole story: the
model very rarely **misses** something printed on the paper, but it fairly often
**invents** a field that isn't there. Eleven of the seventeen false positives are values
for lines the receipt never printed; the other six are misreads, charged to both columns.

---

## Per-receipt results and processing time

| # | Merchant | Time | Items | Field acc | Field P | Field R | What went wrong |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| r1 | Ikkoryu Fukuoka Ramen | **4m 52s** | 5/5 | 92.9% | 90.0% | 100% | Invented `subtotal` (copied the 96.00 service charge) |
| r2 | All Filipino Corp. | **7m 40s** | 8/8 | 92.9% | 91.7% | 100% | Invented `subtotal`; split a wrapped item name into a 9th row |
| r3 | Savemore Market | **4m 57s** | 9/9 | 78.6% | 88.9% | 80.0% | Invented `subtotal`; returned null for two printed `0.00` lines |
| r4 | Cara Mia | **4m 04s** | 2/2 | 92.9% | 92.9% | 100% | Invented `change` = 0.00 |
| r5 | Isetann Dept. Store | **9m 25s** | 8/8 | 73.3% | 78.6% | 91.7% | Sideways photo. Put the date in `receipt_number`; called a credit-card payment `cash`; invented `change` |
| r6 | DBarn Manila Corp. | **4m 43s** | 1/1 | 73.3% | 84.6% | 84.6% | Grabbed the POS serial as `receipt_number`; missed the 54.00 senior discount; called a card payment `cash` |
| r7 | McDonald's | **4m 06s** | 5/5 | 73.3% | 72.7% | 88.9% | Worst case: invented `subtotal` **and** `vatable_sales` (486.61), and got `vat_amount` wrong (58.39 vs 23.15) |
| r8 | Bench Boutique | **11m 26s** | 9/9 | 73.3% | 76.9% | 90.9% | Slowest. Took the MAN number as the TIN; invented `subtotal` and `change` |
| r9 | Shake Shack | **3m 00s** | 2/2 | 75.0% | 84.6% | 84.6% | Dropped a leading digit from the TIN (088→08); digit slip in the invoice no. (…5296→…5236) |
| r10 | DBarn Manila Corp. | **2m 29s** | 1/1 | **100%** | **100%** | **100%** | Clean sweep — every field correct |

**Timing summary:** total wall clock **56.7 min** for 10 receipts.
Mean **340.2 s** (5m 40s) · median **287.5 s** (4m 48s) · fastest **148.5 s** (r10) · slowest
**685.7 s** (r8) · std dev **173.8 s**.

Processing time is driven by **how much JSON the model has to generate** and how many
second-look passes the arithmetic audit triggers — not by source file size. r5 is a
3.29 MB image and r8 is 0.17 MB, yet r8 took 2 minutes *longer*, because every image is
downscaled to `OCR_MAX_IMAGE_DIM` before the model ever sees it, while r8's nine
near-identical repeated lines are the longest output in the set. The two 1-item
receipts (r10, r6) and the 2-item ones (r9, r4) sit at the fast end; the 8–9 item
receipts (r8, r5, r2) occupy the slow end.

> ### Hardware — why the minutes
>
> | | |
> | --- | --- |
> | GPU | NVIDIA GeForce RTX 3050 **Laptop** — **4096 MiB** VRAM, CC 8.6, driver 596.36 |
> | CPU | AMD Ryzen 7 4800H — 8 cores / 16 threads |
> | RAM | 25.1 GB |
> | Runtime | Ollama 0.32.5, local (`OLLAMA_HOST=http://localhost:11434`) |
> | Model | `qwen2.5vl:7b` — 8.3B params, Q4_K_M, 6.9 GB resident |
> | **Placement** | **78% CPU / 22% GPU** (`ollama ps`) |
> | Context | `OCR_NUM_CTX=16384`, `OCR_NUM_PREDICT=4096` |
>
> **The 4 GB VRAM is the bottleneck.** A 6.9 GB working set cannot fit in 4096 MiB, so
> Ollama offloads roughly four fifths of the layers to the Ryzen and the run becomes
> CPU-bound. These timings measure *this laptop*, not the model — on a card that holds
> all 6.9 GB in VRAM these numbers should fall by roughly an order of magnitude. Quote
> the accuracy figures anywhere; quote the timings only alongside this table.

---

## Where the errors are

The 17 false positives and 9 false negatives are not scattered — they cluster into six
behaviours, and the top two account for more than half of everything.

### 1. Phantom `subtotal` — 5 FPs, the single largest error class

On every receipt that prints **no** subtotal line, the model manufactures one from the
nearest available number rather than returning null:

| | Printed subtotal | Model answered | Where it took it from |
| --- | --- | --- | --- |
| r1 | *(none)* | 96.00 | the 10% service charge |
| r2 | *(none)* | 1493.00 | the Amount Due |
| r3 | *(none)* | 689.75 | the Total Due |
| r7 | *(none)* | 216.00 | the Eat-In Total |
| r8 | *(none)* | 867.86 | VATable Sales |

**All five** receipts with no printed subtotal were affected — this behaviour is
completely reproducible, not occasional. The five that do print one (r4, r5, r6, r9, r10)
were all read correctly, so the model is not confused about the field, only about
whether to leave it empty. Suppressing this one behaviour lifts scalar precision from
86.1% to **89.7%**.

### 2. Payment fields on card transactions — 5 FPs

- r5 (Credit Card 1,144.14) and r6 (Card 216.00) were both reported as **`cash`**.
- r4, r5, r8 each got an invented `change` = 0.00 where no change line is printed.

Downstream this matters more than it looks: a card payment booked as cash lands in the
wrong wallet account in the ledger.

### 3. Identifier confusion — 3 wrong `receipt_number`, 2 wrong `vendor_tin`

These receipts print three to five different identifiers each, and the model does not
reliably pick the labelled one:

- r5 → returned `06/24/2026` (the **date**) as the receipt number
- r6 → returned `3BN7A25504742` (the **POS serial**) instead of `SI000000225762`
- r8 → returned the **MAN** number `124-000844246-000103` instead of VATREGTIN `000-844-246-008`
- r9 → `088-311-880-00044` read as `08-311-880-00044` (dropped digit), and `…275296` as `…275236`

The last two are genuine character-level OCR slips. The first three are selection
errors — the digits were read fine, the wrong line was chosen.

### 4. Hallucinated VAT breakdown on r7 — 2 FPs + 1 FN

r7 (McDonald's) is the only receipt in the set that prints **no** VAT sales breakdown —
just a VAT-inclusive total and "TOTAL INCLUDES VAT OF 12.00% 23.15". The model filled
the gap: `vatable_sales` = 486.61 (not on the paper anywhere) and `vat_amount` = 58.39
instead of the printed 23.15. Note 486.61 × 12% ≈ 58.39 — it computed a self-consistent
VAT block for a total it had wrong, which is exactly the failure mode that slips past an
arithmetic check.

### 5. Printed zeros read as absent — 2 FNs (r3)

r3 prints `Zero-Rated Sales 0.00` and `VAT-Exempt Sales 0.00`; both came back null. A
printed zero is information ("this receipt has no exempt sales"), so it is scored as a
miss.

### 6. Missed discount — 1 FN (r6)

The 54.00 Senior/PWD discount was not picked up, even though the subtotal (270.00) and
amount due (216.00) it sits between were both read correctly.

---

## Line items — the strong result

**50 of 51 labelled lines matched, recall 100%, one false positive.**

Every product line on every receipt was found, including the hard cases the dataset was
built to probe:

- **r8** — nine near-identical rows (3 × 128.00, 6 × 98.00) with no duplicate collapsed
  and none invented, on the slowest and most repetitive receipt in the set.
- **r5** — eight lines read off a photo taken **sideways**, with quantities as high as 25.
- **r3** — nine lines where "17 Item(s)" is a *unit* count, correctly not treated as a
  line count.
- **r7** — the `EVM Reg Coke` line priced 0.00 kept as a real row.

The single false positive is r2: `Banguis D` — the wrapped continuation of the
`SISIG D / Bangus D` line — emitted as its own row with a null amount. It is the one
error in the item block and it is a line-wrapping artefact, not a misread.

---

## Reproducing

```bash
git checkout qwen-vl-ocr-eval
ollama pull qwen2.5vl:7b

OLLAMA_HOST=http://localhost:11434 MLFLOW_ENABLED=0 \
python -m evaluation.run_ocr_benchmark \
  --images "C:/Users/clare/Downloads/drive-download-20260804T122242Z-1-001" \
  --out evaluation/results/raw/ocr-qwen2.5vl-7b.json
```

### Scoring rules

Every label is one prediction slot, scored against what the receipt actually prints:

- **TP** — field is printed and the model returned the right value
- **FP** — the model returned a wrong value, **or** returned a value for a field the
  receipt does not print
- **FN** — field is printed and the model returned null, **or** returned a wrong value
- **TN** — field is not printed and the model correctly returned null

A wrong value is charged as **both** an FP and an FN: it asserted something untrue
(precision) and failed to capture what was there (recall). This is what stops a model
from buying recall by guessing — and it is why r7's `vat_amount` appears in both columns.

Money is compared to the cent; text after case/punctuation normalisation; identifiers on
alphanumerics only. Where more than one reading is genuinely defensible (a merchant
printed under both brand and corporate name; r4's misprinted `VATable Sale 9856.01`) the
label carries an `accept` list and any listed value counts as correct. Line items match
greedily on amount first, then description similarity ≥ 0.55.

Computed and provenance fields (`items_coverage`, `image_sha256`, `category`) are **not**
scored — they are produced by our code, not read off the paper, so scoring them would
measure the pipeline rather than the model.

---

## Note on the model choice

The brief was "the best free **API** model of Qwen for OCR". There is currently no free
hosted Qwen-VL API:

- **OpenRouter** lists eight `qwen/*-vl-*` models and **every one is paid** (cheapest,
  `qwen3-vl-8b-instruct`, ~$0.12/M input tokens). Its only free vision models are
  Gemma-4 and Nemotron.
- **Alibaba DashScope** (`qwen-vl-ocr`, `qwen3-vl-plus`) and **ModelScope** both offer
  free Qwen-VL quota, but each requires a signup API key.
- **Ollama Cloud** carries no Qwen vision model.

`qwen2.5vl:7b` on local Ollama is therefore the strongest Qwen OCR model available at
zero cost and with no key — and it is served over the same HTTP API the pipeline already
speaks, so the switch was one env var. With a DashScope or ModelScope key, moving to
`qwen3-vl-235b-a22b` would need an OpenAI-compatible client shim in `core._chat`; the
prompt, guardrails and this harness would all carry over unchanged.
