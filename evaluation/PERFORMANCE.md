# Performance work — what was changed and what was measured

**Honest scope statement first.** Neither Ollama endpoint (`localhost:11434`, the shared
`103.231.240.155`) was reachable during this work, so **no end-to-end latency was
measured**. Nothing here claims a wall-clock speedup for a real request. What is measured
is stated with its method; what is structural is stated as structural.

The two things that dominate a request on a remote endpoint are **how many model round
trips it costs** and **whether the model is resident**. Both are verifiable offline. The
Python-side work (retrieval, preprocessing) is far below the noise floor of a single model
call and was optimized only where it was free or where it also bought accuracy.

---

## The number that framed every decision

| Path | Cost |
|---|---|
| One vision call, `gemma4:e4b`, shared endpoint | **~6,000 ms** (recorded previously) |
| One vision call, `gemma4:12b` | **~20,000 ms** (recorded previously) |
| Whole retrieval path at 5,000 receipts | **~15 ms** |
| Image preprocessing, per page | **~18 ms** |

Retrieval and preprocessing together are ~0.5% of one model call. **Micro-optimizing
Python here is not where the time is** — cutting a round trip is worth ~400× more than
making retrieval infinitely fast. That is why the round-trip count got a regression test.

---

## 1. The agent model was being evicted between calls — fixed

**Only the vision call passed `keep_alive`.** Every text call — SQL generation, the retry,
the answer summarizer, RAG, `_force_final`, and each ReAct step — passed neither
`keep_alive` nor `num_ctx`.

Consequences on a shared endpoint serving both a vision and a text model:

1. The text model fell back to Ollama's short default and was evicted, so **every agent
   turn could pay a cold model load** — which on a 7B–12B model dwarfs the inference.
2. Without an explicit `num_ctx`, the server default applies (as low as 2048 on some
   builds). A ReAct transcript carries the prompt, the schema, and accumulated
   observations. Exceeding the window is **silently truncated** — the model loses the
   observation it is supposed to answer from. That surfaces as a wrong answer or a
   repeated tool call, never as an error. This is a correctness bug that also *costs*
   time, because the loop then burns extra steps.

**Fix:** `_chat()` now applies `keep_alive`, `num_ctx` (`AGENT_NUM_CTX`, default 8192) and
`num_predict` (`AGENT_NUM_PREDICT`, default 512) via `setdefault`, so an explicit caller
argument always wins — the vision path keeps its own much larger `num_predict=4096`, which
it needs or a receipt with many line items truncates mid-JSON.

Tests: `test_w6_performance.py` — residency, context floor, output bound, and that the
vision path is not clobbered.

## 2. Round trips per question: cut

Measured by counting calls into `_chat` with a stubbed model.

| Endpoint | Before | After |
|---|---|---|
| `POST /ask` (SQL agent) | 2 | **1** |
| `POST /agent` (ReAct, one tool) | 4 | **3** |

The removed call was `_generate_answer` re-phrasing an already-computed SQL result as
prose. For simple result shapes that call is now replaced by deterministic formatting:

- one row, one column → formatted directly (`₱1,585.00`)
- one row, several columns → `label: value` pairs
- a single `NULL` aggregate → "no matching records" (a `SUM` over zero rows is *nothing
  found*, not an answer of `None`)
- **multi-row results still go to the model**, where prose genuinely helps

This is **faster and more accurate at once**: the number now reaches the user exactly as
SQLite computed it, instead of being re-typed by a model that was previously observed
garbling amounts. At ~6 s/call this is ~6 s off every SQL question, including the one
nested inside the ReAct loop.

*User-visible change:* `POST /ask` returns a terse exact answer (`₱1,585.00`) rather than
a sentence. The ReAct path is unaffected — it still writes prose in its final step, which
was deliberately kept so multi-tool synthesis and the observation→final trajectory
contract survive.

Tests: `test_a_scalar_sql_question_costs_one_model_call`,
`test_a_react_question_costs_three_model_calls` — these fail if a round trip is added back.

## 3. Missing database index — 227× on a real query

`line_items` had **no index on `receipt_id`**, so every per-receipt lookup was a full
table scan. That is on the receipt detail view, delete, category backfill, `ensure_index()`,
and the SQL the agent generates — its few-shot examples literally teach it
`WHERE receipt_id = N`.

Measured at 100,000 line items (20,000 receipts × 5):

| | 500 single-receipt lookups | bulk insert |
|---|---|---|
| without index | 658.9 ms | 42 ms |
| with index | **2.9 ms** | 58 ms |

227× faster reads for +16 ms on a 100k-row import, paid once. Also added
`idx_receipts_date` — the ledger is read-heavy and nearly every listing and analytics
query filters or orders by date.

## 4. Retrieval hot path

Measured with `evaluation/bench_retrieval.py` (synthetic embeddings, no model, best of 5):

| receipts | whole-ledger before | after | scoped-to-1 before | after |
|---|---|---|---|---|
| 1,000 | 3.77 ms | 3.19 ms | 1.47 ms | **0.15 ms** |
| 5,000 | 19.21 ms | **14.58 ms** | 7.99 ms | **0.33 ms** |

Three changes:
- **Scope pushed into SQL.** Out-of-scope rows are no longer read at all. This is the 24×
  win on scoped search, and it also makes the isolation guarantee structural rather than a
  post-filter.
- **Two-phase fetch.** Scoring reads only `(id, embedding)`; the surviving k rows are
  hydrated in a second query. Previously every candidate's doc text and metadata were
  materialized into Python dicts just to rank them and discard all but k — megabytes of
  strings at 5k receipts.
- **Vectorized scoring.** One matrix product instead of a per-row Python loop, query norm
  computed once instead of per row.

An intermediate version that vectorized *without* the two-phase split was **slower**
(22.3 ms) than the original, because `vstack` added a 15 MB copy while the real cost was
the row hydration. That is why the split matters and why it was measured rather than
assumed.

`semantic_search` is a security-relevant function (scope isolation), so it got 19
behavioural tests before the rewrite was trusted — `test_w5_retrieval.py`.

## 5. Preprocessing: stopped re-encoding conforming images

`preprocess_image` always re-encoded to JPEG. On the sample receipt the output was
**larger than the input** (251 KB → 318 KB). For an image that is already JPEG, upright,
RGB and within the size limit, that re-encode is a second lossy generation over exactly
the faint thermal-receipt text the model must read — for no benefit, plus CPU and extra
upload bytes.

Now such images are returned byte-identical. Images that need rotation, conversion or
downscaling are unaffected. This is an **accuracy** change more than a speed one;
preprocessing was already only ~18 ms.

Tests: `test_w2a_preprocess.py` (15), including a guard that an EXIF-rotated photo is
*not* taken by the fast path — silently skipping rotation would feed the model a sideways
receipt.

---

## Deliberately NOT changed

- **The vision model default.** `gemma4:e4b` (~6 s) vs `gemma4:12b` (~20 s) is a recorded
  *tradeoff*, not a win: e4b misses line items and the VAT block; 12b reads the VAT block
  exactly but garbles descriptions, misreads amounts and corrupts the receipt number.
  Neither is reliably accurate. Switching for speed without labelled receipts to measure
  against would be trading unknown accuracy for known speed.
- **Image resolution.** `OCR_MAX_IMAGE_DIM=1600` is at the shared endpoint's hard ceiling
  — above ~1600 px it returns **empty content** regardless of `num_ctx`. Resolution is not
  an available lever in either direction.
- **JPEG quality.** Lowering `OCR_JPEG_QUALITY` would cut upload size, but its effect on
  thermal-receipt legibility cannot be assessed without labelled receipts.
- **Short-circuiting the ReAct loop.** Would cut 4→2 calls, but the agent would lose
  multi-tool synthesis and the ability to caveat, and it weakens trajectory evaluation.

Every one of these is blocked on the same thing: **labelled receipt images** (audit
blocker B1). They are accuracy decisions, and there is still no measured accuracy baseline
to trade against.

---

## What to measure once an endpoint is reachable

`evaluation/bench_retrieval.py` covers the offline half. The model-dependent half needs a
live run and belongs in W6:

1. Cold vs warm first-call latency — confirms the `keep_alive` fix in wall-clock terms.
2. Per-endpoint latency (`/extract`, `/ask`, `/search`, `/agent`) at fixed seed, repeated.
3. Batch throughput in pages/minute at `OCR_CONCURRENCY` 1–4. **Do not exceed the
   endpoint's `OLLAMA_NUM_PARALLEL`**, and note that concurrency 2 OOMs two local 7B
   vision models on 16 GB.
4. Token counts per question — already logged to MLflow as `prompt_eval_count` /
   `eval_count`.

Attach the `CONFIGURATION.md` capture template to every run.
