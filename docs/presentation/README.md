# Final Capstone deck: Snag

`Snag_Final_Capstone.pptx` holds 27 slides, 16:9, editable in PowerPoint. At roughly
forty seconds a slide that is a full fifteen-minute talk, so the deck has no room for
a slide that is not carrying an argument.

Three rules hold it together:

1. **One idea per slide, three blocks at most.** If a slide needs a fourth block it is
   two slides, and if the fourth block is not worth a slide, it is not worth saying.
2. **Structure comes from whitespace, a hairline and type weight, never from a box.**
   A shape is drawn only when it carries meaning: an architecture block, a database
   cylinder, the one quadrant that survived.
3. **The architecture is drawn once and referred to everywhere.** Five blocks, fixed
   x positions, and a header minimap that lights the one under discussion. A slide
   that needs a sixth block is not an architecture slide.

Explanation is set as bullets (`bullets()`), because the architecture feedback asked for
explanations and a bullet with a bold lead (*the claim, then why*) is the shape an
explanation wants. Diagrams still carry the flow; bullets carry the reasoning under it.

## The five blocks, and why everything hangs off them

The system is drawn once, abstractly, as five blocks, **Capture › Extract › Ledger ›
Agent › Answer**, with three things that run under or across all of them: the **API**
in front, the **models** underneath, and **traces** around. That abstraction is the
deck's spine, and it is defined once in `build_deck.py`:

```python
STAGES = [("Capture", …), ("Extract", …), ("Ledger", …), ("Agent", …), ("Answer", …)]
BANDS  = ["API", "Models", "Traces"]
stage_x(i)   # left edge of block i, the same x on slides 7, 8 and 9
gap_x(i)     # centre of the hand-off between block i and i+1
minimap(sl, "extract")   # the whole diagram, shrunk into the header, one block lit
```

Slide 7 draws the blocks full size. Slide 8 hangs the dataflow off the *same x
positions*, so the hand-offs are read as arrows on a diagram already in the room.
Slide 9 hangs all fourteen components off the same five columns. Slides 10–15 carry
`minimap()` in the header: the section nav says where we are in the talk, the minimap
says where we are in the system, and exactly one block is lit.

Anything finer-grained than the five blocks (file names, line counts, `core.py`'s
sections) is code spec, and code spec is slide 27, after *Questions?*.

## What the third round of feedback asked for, and where it now lives

| Deduction | Answer in the deck |
|---|---|
| By the end, the proof point must be answered: how does this compare with a $20 Claude Cowork | **Slide 23**, the last Findings slide. Three things the seat does better in its own column, five it cannot do at any price, each with the figure behind it, and a recommendation that is a hybrid rather than a win. **Slide 26** closes the talk on the same verdict |
| It does not have to be better outright, but the test cases and experiment design must be sound | **Slide 19** puts the frozen Cowork prompt on screen word for word, with the five run rules that stop a comparison becoming a demo, and states the fairness limits out loud |
| Are there specific cases where yours is better? Highlight those | Line items on Philippine thermal receipts: **50 of 50 labelled lines found**, including nine near-identical rows and a sideways photo. It is a row on slide 23 and a rebuilt figure on slide 18 |
| Make sure the metrics are reliable, and prove it | `verify_facts.py` recomputes 20 figures from source and fails if a slide disagrees. **Slide 18** puts the command, the count and four rebuilt figures on screen. Four numbers were wrong and were corrected: `ReceiptData` 25 to 23 fields, sixteen to nineteen prompt rules, the qwen row to 86.3 / 89.6 / 94.5, and the line-item denominator |

## What the second round of feedback asked for, and where it now lives

| Deduction | Answer in the deck |
|---|---|
| The system architecture slide is busy; abstract the modules and only display the ones being discussed | **Slide 7** is five blocks, three bands and three model cards, eleven objects where there were eighteen. No file names, no per-service boxes. Then `minimap()` puts the diagram in the header of every component slide with one block lit, so slide 11 is visibly *inside Extract* and slide 12 is visibly *inside Agent* |
| The dataflow is all text; integrate it with the functional components or with the architecture | **Slide 8** is the slide-7 block row with the four hand-offs drawn on the arrows between them: shape, the function that guards it, and one line of reason, hung under the gap it belongs to. Six long bullets became four captions and two side-branch lines |
| Modules can be in the appendix, we don't need code spec, it distracts | **Slide 27, section Appendix.** Same content, moved whole; slide 7's footnote points at it. `SECTIONS` grew an "Appendix" entry so the nav says out loud that it exists |
| Component discussion comes out of nowhere, outline all of them before delving into 14 | **Slide 9 comes before the deep dives now.** All fourteen are laid out in the five architecture columns, each with its owner and *the slide it gets*: a table of contents, not a grid of tiles. The closing line names the running order: 14, then 5, 9, 10, 7 |

## What the first round of architecture feedback asked for, and where it now lives

| Deduction | Answer in the deck |
|---|---|
| No comprehensive dataflow diagram; no explanation of the chosen representations (JSON, models/objects, SQL) | **Slide 8, Dataflow.** The shapes ride the arrows of the architecture diagram, each hand-off annotated with the function that guards it and the reason that representation and not another |
| Most of the dataflow happens in a single `core.py` | **Slide 27, Appendix: modules.** Every module with its line count and responsibility, `core.py`'s own eight numbered sections in order, and a statement that agrees with the criticism and names the seams. It is answered when asked, not volunteered |
| No explanation of how LLMOps and Dockerization were performed | **Slide 15, LLMOps** (backend, run naming, the three helpers, what lands on a run, the two env knobs) and **Slide 16, Docker** (the three services, the volume decision, models-as-environment, start order) |
| No decision-flow / ReAct loop definition | **Slide 12, the ReAct loop.** ReAct is defined in a sentence, the loop is *drawn as a loop* (return arc, "at most 4 steps, one tool each"), the branches are drawn (ambiguous → ask once, budget spent → forced final), and all five exits plus the post-loop grounding veto are listed. The load-bearing detail: generation stops at the token `Observation:`, so the model can never write its own observation |
| Tools, guardrail integrations and agentic flow not illustrated | **Slide 13** lists all eleven tools, 4 read / 7 write, with `KNOWN_TOOLS` as the single source of truth and the two answer paths; **slide 11** prints the function behind each of the seven gates (`validate_input`, `_validate_sql`, `_build_scoped_db`, `_sanitize_observation`, `_ungrounded_numbers`, `_guard_amount`) |

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
door, the shared write spine, the VRAM caveat on slide 17, the two unsourced rows on slide 18, the fairness limits on slide 19, and the disclosure that a
limitation you find yourself is not a defect. Calls without `keep=True` stay in the source
so the point is not lost; they just do not compete with the slide.

## Slide map

| # | Section | Slide | Map |
|---|---|---|---|
| 1 | | Title: agent, tagline, model + parameter sizes, stack, team | |
| 2 | Use case | Today: the manual workflow and what it costs | |
| 3 | Use case | Scope: in / out, and the ChatGPT sanity check | |
| 4 | Use case | The arithmetic: UoM, both equations, the saved figures | |
| 5 | Use case | What it costs: ₱1,562 by hand vs ₱1,160 DIY subscription vs ₱99 Snag | |
| 6 | RRL | Option space, the model we chose, the trade-off we recorded | |
| 7 | Architecture | **System architecture**: five blocks, one door, one model server | draws it |
| 8 | Architecture | **Dataflow**: the same five blocks, four hand-offs on the arrows | draws it |
| 9 | Components | **Fourteen components, on the map**: the outline, and the slide each gets | draws it |
| 10 | Components | Component 14: ten stages and the re-read loop | Extract |
| 11 | Components | Guardrails: seven gates, the function behind each, the prompt rules | Extract |
| 12 | Components | **The ReAct loop**: defined, drawn as a loop, with every exit | Agent |
| 13 | Components | Eleven tools, one dispatcher, and the two answer paths | Agent |
| 14 | Components | The API: one surface, three clients | API |
| 15 | Components | **LLMOps**: how the tracing is wired | Traces |
| 16 | Components | **Docker**: one command, three services | |
| 17 | Findings | **Three models, measured**: accuracy, precision, recall, speed, cost | |
| 18 | Findings | **Every number here is recomputed**: the command, the count, four rebuilt figures | |
| 19 | Findings | **How we ran Cowork**: the frozen prompt verbatim, and the five run rules | |
| 20 | Findings | One full reasoning trace (case RCT-006) | |
| 21 | Findings | It works, and where it doesn't | |
| 22 | Findings | What we cannot claim | |
| 23 | Findings | **Snag against a $20 seat**: what we concede, what we win, what we recommend | |
| 24 | Wrap-up | Who built what + retrospective | |
| 25 | Wrap-up | Live demo (at the end, per the brief) | |
| 26 | Wrap-up | Take away five things, closing on the verdict | |
| 27 | Appendix | Modules: what each file owns, and core.py's eight sections | |

The "Map" column is what `minimap()` lights in the header. A blank means the slide is
not about one block of the system.

Everything the brief asks to see is on exactly one slide: LLM and parameter size (1),
UoM and value (4, 5), RRL (6), architecture (7, 8), the component inventory (9), CV/DS
integration (10), component ownership (9 and 24), the agentic decision flow (12),
quantitative metrics (17) with their audit trail (18) and the protocol behind the
comparison (19), a full reasoning trace (20), limitations and lessons (22, 24), the
build-vs-buy proof point (23), team contributions (24), live demo last (25).

### The model comparison (slide 17)

| Model | Accuracy | Precision | Recall | Time / receipt | Cost |
|---|---|---|---|---|---|
| Claude Cowork | 97% | 94% | 98% | 15 s | $20 / month |
| qwen2.5-VL 7B | 85% | 87% | 94% | 5–6 min * | free, local |
| Gemma | 51.7% † | 92.5% ‡ | 69.8% ‡ | 21.7 s | free, API |

† Gemma is measured field by field: 51.7% headers, 47% financial fields, 37.1% line-item
fields. ‡ Its precision/recall pair is line **detection**, not field values.
\* qwen ran on a card with less VRAM than the model needs, so part of every page fell back
to the CPU, and that is where the five to six minutes goes, not the model.

These figures are typed into `MODELS` in `build_deck.py`; unlike the trace numbers they do
not come from `facts.json`, so update them there when the benchmark is re-run.

## Rebuild

```bash
python docs/presentation/charts.py       # regenerate figures + assets/facts.json
python docs/presentation/build_deck.py   # regenerate the .pptx
python docs/presentation/verify_facts.py # check every number against its source
```

## Every number on a slide is checked

`verify_facts.py` recomputes each load-bearing figure from the thing it describes and
asserts that the recomputed value is the one written in `build_deck.py`. Exit code is 1
if any check fails, so it can gate a rebuild. Run it before you present.

| It checks | Against |
|---|---|
| 80 routes, 21 request models | `api.py`, parsed as an AST, not grepped |
| 23 `ReceiptData` fields, 4 read + 7 write tools, a 4-step budget | `core.py` |
| 19 prompt rules (28 with sub-rules) | the `STRICT RULES` literal in `extraction.py` |
| 17 ledger tables, 768-dim embeddings | `ledger.db` schema; `len(embedding) / 4` bytes |
| 0 ungrounded numbers in 64 runs, 15.4% held | `mlflow.db`, recomputed from `latest_metrics` |
| 86.3 / 89.6 / 94.5 and 50 of 50 line items | the benchmark's 197 per-field verdicts, rebuilt and then compared to its own stored summary |
| three services, MLflow 3.14 | `docker-compose.yml` |

Two rules keep it honest. **It recomputes rather than re-reads**: the OCR headline is
rebuilt from the individual verdicts (including the documented `FP+FN` dual charge for a
wrong value) and only then compared to the summary in the same file, so a corrupted
summary fails rather than passes. And **a claim with no source in this repository is
reported `UNSOURCED`, never as a pass**: currently the Claude Cowork row and the Gemma
row, both of which come from runs held outside the tree. Drop their raw output in
`evaluation/results/raw/` and each becomes a real check.

`charts.py` reads live repository data (`mlflow.db`, `evaluation/results/raw/trajectory-*.json`,
and the benchmark tables in `evaluation/PERFORMANCE.md`) and writes both the figures and
`assets/facts.json`. `build_deck.py` reads that file, so **every number on a slide moves when
the underlying data moves**. Nothing is typed twice. The figures use the deck's own typeface,
palette and restraint (no tick marks, no legend frame, left-aligned titles), so a chart and a
slide read as one document.

As of the model-comparison revision **no figure is placed on a slide**: every number that
survived is set as type, which is why the deck reads as one document rather than a slide
with a picture on it. `charts.py` still builds all seven figures and still writes
`facts.json` (the deck reads the traced-run count from it), so any of them can come back:
`picture(s, "chart_latency.png", M, 3.26, 7.30, 2.70)` is all it takes.

## Things to change before presenting

| What | Where | Why |
|---|---|---|
| Team names and component ownership | `TEAM` in `build_deck.py` (slides 1, 9, 24) | Taken from the root `README.md` ownership table. Confirm it is current |
| Tech-stack logos | slide 1, the `STACK` list | Brand-coloured monogram tiles, 0.22″ square, already positioned. Drop a real logo PNG on top of a tile and it lines up |
| The ₱99 price | slide 5 | A proposal, not a decision, and the whole value slide hangs off it |
| The $/₱ rate | slide 5 | $20/month is converted at **₱58 = $1 → ₱1,160**. The slide says so out loud; check the rate on the day and change both the number and the "12×" chip |
| Benchmark figures | `MODELS` in `build_deck.py` (slide 17) | Typed in, not read from `facts.json`. Re-run the benchmark, update them here |
| Demo URLs | slide 25, "WHERE TO LOOK" | Deliberately left as descriptions; add the actual ports you will present on |

## The UoM model

Every assumption behind the value proposition lives in one dictionary, `UOM` in
`charts.py`, mirrored in the equations on slide 4. Two of the eight inputs are measured
from our own traces (OCR seconds per page, share of receipts held for review); the other
six are declared assumptions and are labelled as such on the slide. Slide 5 adds one more
declared input, the peso/dollar rate, and states it on the slide rather than burying it.

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
**All geometry is written in inches as plain floats**: `E()` converts to whole EMUs at
the XML boundary. Skip it and PowerPoint reports the file as corrupt: a float in an
`off`/`ext` attribute is invalid OOXML, and that is exactly how this deck broke once.

```python
bullets(sl, x, y, w, [("Lead", "why it matters"), …])  # the explanation primitive
rule(sl, x, y, w)                              # the hairline, the only divider
vrule(sl, x, y, h)                             # its vertical twin
eyebrow(sl, x, y, w, "request")                # tracked small caps, labels a region
chain(sl, y, [("Read", "sub"), …], accent=(0,))# steps separated by chevrons
rows(sl, x, y, w, [("Scope", "read-only copy")])  # hairline-separated label/detail rows
stat(sl, x, y, w, "26×", "less human time")    # a number and what it counts
statement(sl, y, "Transcribe, then repair.", "the caveat")   # accent rule + quiet claim
mark(sl, x, y, "ok" | "bad")                   # a ✓ or ✗ glyph, 11 pt, no disc
chip(sl, x, y, "label")                        # a soft pill, returns the next x
card(sl, x, y, w, h, "Extract", "read, repair")  # the only bordered box, blocks only
store(sl, x, y, w, h, "Ledger", "18 tables")   # a database cylinder
note(sl, y, "Lead:", "the rest", keep=True)    # the opt-in footnote

stage_x(i) / gap_x(i)                          # the architecture's x grid: 7, 8 and 9
minimap(sl, "agent")                           # the header breadcrumb: one block lit
```

Positions are literal inches. Content lives between `TOP` (2.00″) and ~6.60″; the footer
sits at 6.98″. When a shape collides with it, move it or drop a line. Do not shrink the
font.

## If you need a cut slide back

Earlier revisions carried 34 slides: separate slides for the 10× rule, the parallel-vs-
sequential timeline, the prompt text in full, the ten tool contracts, the nine-endpoint API
table, the break-even chart and three priced tiers, the eval pyramid, three metric slides,
and a standalone retrospective. They are in git history:
`git log --oneline -- docs/presentation/build_deck.py`. Pull one back only if a question in
the dry run demands it.

The evaluation-suite slides (831 unit tests, the four-layer pyramid, the 6/7 trajectory
result and the scorer post-mortem) were retired in favour of the model-comparison table on
slide 17. The harness itself still lives in `evaluation/`, and `charts.py` still reads it;
only the slides went away.
