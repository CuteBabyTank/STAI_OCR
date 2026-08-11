# Final Capstone deck — Snag

`Snag_Final_Capstone.pptx` — 24 slides, 16:9, editable in PowerPoint. At roughly
forty seconds a slide that is a full fifteen-minute talk, so the deck has no room for
a slide that is not carrying an argument.

Two rules hold it together:

1. **One idea per slide, three blocks at most.** If a slide needs a fourth block it is
   two slides — and if the fourth block is not worth a slide, it is not worth saying.
2. **Structure comes from whitespace, a hairline and type weight — never from a box.**
   A shape is drawn only when it carries meaning: an architecture lane, a database
   cylinder, the one quadrant that survived.

Explanation is set as bullets (`bullets()`), because the architecture feedback asked for
explanations and a bullet with a bold lead — *the claim, then why* — is the shape an
explanation wants. Diagrams still carry the flow; bullets carry the reasoning under it.

## What the architecture feedback asked for, and where it now lives

| Deduction | Answer in the deck |
|---|---|
| No comprehensive dataflow diagram; no explanation of the chosen representations (JSON, models/objects, SQL) | **Slide 8 — Dataflow.** The five shapes as a chain, each hand-off annotated with the function that guards it, and a bullet per shape saying why that representation and not another |
| Most of the dataflow happens in a single `core.py` | **Slide 9 — Modules.** Every module with its line count and responsibility, `core.py`'s own eight numbered sections in order, and a statement that agrees with the criticism and names the seams |
| No explanation of how LLMOps and Dockerization were performed | **Slide 16 — LLMOps** (backend, run naming, the three helpers, what lands on a run, the two env knobs) and **Slide 17 — Docker** (the three services, the volume decision, models-as-environment, start order) |
| No decision-flow / ReAct loop definition | **Slide 13 — The ReAct loop.** ReAct is defined in a sentence, the loop is *drawn as a loop* (return arc, "at most 4 steps, one tool each"), the branches are drawn (ambiguous → ask once, budget spent → forced final), and all five exits plus the post-loop grounding veto are listed. The load-bearing detail: generation stops at the token `Observation:`, so the model can never write its own observation |
| Tools, guardrail integrations and agentic flow not illustrated | **Slide 14** lists all eleven tools, 4 read / 7 write, with `KNOWN_TOOLS` as the single source of truth and the two answer paths; **slide 12** prints the function behind each of the seven gates (`validate_input`, `_validate_sql`, `_build_scoped_db`, `_sanitize_observation`, `_ungrounded_numbers`, `_guard_amount`) |

Every figure on those slides was read out of the source, not remembered: 80 routes and
21 request models from `api.py`, 17 tables from `ledger.db`, the line counts from `wc -l`,
the metric names from the `_mlog_*` call sites, the services and volumes from
`docker-compose.yml`.

## The rules the deck holds itself to

| Rule | Why |
|---|---|
| One accent (`#B45309`), used at most twice per slide | if everything is emphasised, nothing is |
| Green (`#047857`) and red (`#B91C1C`) are **ink, never fill** | a tinted card reads as decoration; a green tick reads as a verdict |
| No box has both a fill and a border | pick one, or neither |
| Icons are glyphs, not discs | `✓` `✗` at 11–12 pt, monogram tiles at 0.22″, avatars at 0.44″ |
| Arrows are chevrons (`›`) unless direction is the point | a drawn arrowhead is heavy; a chevron is a comma |
| No dark bars | a claim is set as large quiet type over a short accent rule (`statement()`) |
| Nothing competes with the title | title 27 pt, kicker 11.5 pt, body 11–13 pt, small caps at 8.5 pt with tracking |

## Footnotes are opt-in

`note()` renders nothing unless you pass `keep=True`. A footnote earns it only if it
states something a grader could challenge: measured-vs-assumed inputs, the peso/dollar
rate, the vision trade-off, the compose services, why #11 is greyed out, the grounding
count, the MLflow sampling knobs, the API being a deliverable rather than the UI's back
door, the shared write spine, the two benchmark caveats on slide 18, and the disclosure that a
limitation you find yourself is not a defect. Calls without `keep=True` stay in the source
so the point is not lost — they just do not compete with the slide.

## Slide map

| # | Section | Slide |
|---|---|---|
| 1 | — | Title — agent, tagline, model + parameter sizes, stack, team |
| 2 | Use case | Today — the manual workflow and what it costs |
| 3 | Use case | Scope — in / out, and the ChatGPT sanity check |
| 4 | Use case | The arithmetic — UoM, both equations, the saved figures |
| 5 | Use case | What it costs — ₱1,562 by hand vs ₱1,160 DIY subscription vs ₱99 Snag |
| 6 | RRL | Option space, the model we chose, the trade-off we recorded |
| 7 | Architecture | System diagram — three lanes, where the CV model plugs in |
| 8 | Architecture | **Dataflow** — five shapes, and why each one |
| 9 | Architecture | **Modules** — what each file owns, and core.py's eight sections |
| 10 | Architecture | Component 14 — ten stages and the re-read loop |
| 11 | Components | 13 of 14 components, with owner initials |
| 12 | Components | Guardrails — seven gates, the function behind each, the prompt rules |
| 13 | Components | **The ReAct loop** — defined, drawn as a loop, with every exit |
| 14 | Components | Eleven tools, one dispatcher — and the two answer paths |
| 15 | Components | The API — one surface, three clients |
| 16 | Components | **LLMOps** — how the tracing is wired |
| 17 | Components | **Docker** — one command, three services |
| 18 | Findings | **Three models, measured** — accuracy, precision, recall, speed, cost |
| 19 | Findings | One full reasoning trace (case RCT-006) |
| 20 | Findings | It works, and where it doesn't |
| 21 | Findings | What we cannot claim |
| 22 | Wrap-up | Who built what + retrospective |
| 23 | Wrap-up | Live demo (at the end, per the brief) |
| 24 | Wrap-up | Take away four things |

Everything the brief asks to see is on exactly one slide: LLM and parameter size (1),
UoM and value (4, 5), RRL (6), architecture (7–9), CV/DS integration (10), component
ownership (11 and 22), the agentic decision flow (13), quantitative metrics (18), a full
reasoning trace (19), limitations and lessons (21, 22), team contributions (22), live
demo last (23).

### The model comparison (slide 18)

| Model | Accuracy | Precision | Recall | Time / receipt | Cost |
|---|---|---|---|---|---|
| Claude Cowork | 97% | 94% | 98% | 15 s | $20 / month |
| qwen2.5-VL 7B | 85% | 87% | 94% | 5–6 min * | free, local |
| Gemma | 51.7% † | 92.5% ‡ | 69.8% ‡ | 21.7 s | free, API |

† Gemma is measured field by field: 51.7% headers, 47% financial fields, 37.1% line-item
fields. ‡ Its precision/recall pair is line **detection**, not field values.
\* qwen ran on a card with less VRAM than the model needs, so part of every page fell back
to the CPU — that is where the five to six minutes goes, not the model.

These figures are typed into `MODELS` in `build_deck.py`; unlike the trace numbers they do
not come from `facts.json`, so update them there when the benchmark is re-run.

## Rebuild

```bash
python docs/presentation/charts.py      # regenerate figures + assets/facts.json
python docs/presentation/build_deck.py  # regenerate the .pptx
```

`charts.py` reads live repository data — `mlflow.db`, `evaluation/results/raw/trajectory-*.json`,
and the benchmark tables in `evaluation/PERFORMANCE.md` — and writes both the figures and
`assets/facts.json`. `build_deck.py` reads that file, so **every number on a slide moves when
the underlying data moves**. Nothing is typed twice. The figures use the deck's own typeface,
palette and restraint (no tick marks, no legend frame, left-aligned titles), so a chart and a
slide read as one document.

As of the model-comparison revision **no figure is placed on a slide** — every number that
survived is set as type, which is why the deck reads as one document rather than a slide
with a picture on it. `charts.py` still builds all seven figures and still writes
`facts.json` (the deck reads the traced-run count from it), so any of them can come back:
`picture(s, "chart_latency.png", M, 3.26, 7.30, 2.70)` is all it takes.

## Things to change before presenting

| What | Where | Why |
|---|---|---|
| Team names and component ownership | `TEAM` in `build_deck.py` (slides 1, 11, 22) | Taken from the root `README.md` ownership table — confirm it is current |
| Tech-stack logos | slide 1, the `STACK` list | Brand-coloured monogram tiles, 0.22″ square, already positioned. Drop a real logo PNG on top of a tile and it lines up |
| The ₱99 price | slide 5 | A proposal, not a decision — and the whole value slide hangs off it |
| The $/₱ rate | slide 5 | $20/month is converted at **₱58 = $1 → ₱1,160**. The slide says so out loud; check the rate on the day and change both the number and the "12×" chip |
| Benchmark figures | `MODELS` in `build_deck.py` (slide 18) | Typed in, not read from `facts.json`. Re-run the benchmark, update them here |
| Demo URLs | slide 23, "WHERE TO LOOK" | Deliberately left as descriptions; add the actual ports you will present on |

## The UoM model

Every assumption behind the value proposition lives in one dictionary — `UOM` in
`charts.py`, mirrored in the equations on slide 4. Two of the eight inputs are measured
from our own traces (OCR seconds per page, share of receipts held for review); the other
six are declared assumptions and are labelled as such on the slide. Slide 5 adds one more
declared input — the peso/dollar rate — and states it on the slide rather than burying it.

## What the deck deliberately does not claim

- **A human baseline.** 97% is accuracy against ground truth, not against a bookkeeper.
  Nobody has timed a person on the same 300 receipts, so "better than a human" is not on a
  slide. It is item three on *What we cannot claim*.
- **That the free model is good enough alone.** Gemma reads line-item fields at 37.1%. The
  ten checks, the re-read loop and the review gate are what make that shippable, and the
  deck says so rather than hiding the number.
- **Multi-agent orchestration** (component #11). One planner over ten tools is not several
  collaborating agents.

## Editing a slide

`build_deck.py` has a small vocabulary of primitives; every slide is built from them.
**All geometry is written in inches as plain floats** — `E()` converts to whole EMUs at
the XML boundary. Skip it and PowerPoint reports the file as corrupt: a float in an
`off`/`ext` attribute is invalid OOXML, and that is exactly how this deck broke once.

```python
bullets(sl, x, y, w, [("Lead", "why it matters"), …])  # the explanation primitive
rule(sl, x, y, w)                              # the hairline — the only divider
vrule(sl, x, y, h)                             # its vertical twin
eyebrow(sl, x, y, w, "request")                # tracked small caps, labels a region
chain(sl, y, [("Read", "sub"), …], accent=(0,))# steps separated by chevrons
rows(sl, x, y, w, [("Scope", "read-only copy")])  # hairline-separated label/detail rows
stat(sl, x, y, w, "26×", "less human time")    # a number and what it counts
statement(sl, y, "Transcribe, then repair.", "the caveat")   # accent rule + quiet claim
mark(sl, x, y, "ok" | "bad")                   # a ✓ or ✗ glyph, 11 pt, no disc
chip(sl, x, y, "label")                        # a soft pill, returns the next x
card(sl, x, y, w, h, "API server", "~70 endpoints")  # the only bordered box — lanes only
store(sl, x, y, w, h, "Ledger", "18 tables")   # a database cylinder
note(sl, y, "Lead:", "the rest", keep=True)    # the opt-in footnote
```

Positions are literal inches. Content lives between `TOP` (2.00″) and ~6.60″; the footer
sits at 6.98″. When a shape collides with it, move it or drop a line — do not shrink the
font.

## If you need a cut slide back

Earlier revisions carried 34 slides: separate slides for the 10× rule, the parallel-vs-
sequential timeline, the prompt text in full, the ten tool contracts, the nine-endpoint API
table, the break-even chart and three priced tiers, the eval pyramid, three metric slides,
and a standalone retrospective. They are in git history —
`git log --oneline -- docs/presentation/build_deck.py`. Pull one back only if a question in
the dry run demands it.

The evaluation-suite slides (831 unit tests, the four-layer pyramid, the 6/7 trajectory
result and the scorer post-mortem) were retired in favour of the model-comparison table on
slide 13. The harness itself still lives in `evaluation/`, and `charts.py` still reads it —
only the slides went away.
