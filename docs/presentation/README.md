# Final Capstone deck — Snag

`Snag_Final_Capstone.pptx` — 34 slides, 16:9, editable in PowerPoint.

**Every slide is a diagram.** No paragraphs, no tables, no bullet lists. Words appear
inside a box, on an arrow, or under a number — nowhere else. If a slide needs a sentence
to make sense, the diagram is wrong.

## The colour rule

One neutral ramp, one accent, two colours that mean something. Both the slides and the
matplotlib figures use the same values.

| Role | Use |
|---|---|
| ink / body / muted / faint / line / grey | everything structural |
| **accent** (`#B45309`) | the one thing on the slide that matters most |
| **green** (`#047857`) | *only* "this passed / this was caught" |
| **red** (`#B91C1C`) | *only* "this failed / this is blocked / we do not claim it" |

Green and red are never decorative. If a box is green it is making a claim about a
result, and someone can ask you to defend it. Everything else is a shade of grey with
at most one accented element — the vision-model stage on slide 11, the re-read loop on
slide 13, the write tools on slide 19.

Fills and borders are not both allowed to carry meaning: a box is either white with a
hairline, or a soft tint with a matching border. Boxes never have a coloured border
*and* a coloured fill unless they are semantic.

## Footnotes are opt-in

`note()` renders nothing unless you pass `keep=True`. There are 23 calls in the source
and 9 render. The other 14 stay in the file so the point is not lost — they just do not
compete with the diagram. A footnote earns `keep=True` only if it states something a
grader could challenge you on:

| Slide | Why it stays |
|---|---|
| Why not ChatGPT | the sanity check the spec asks for |
| The 10× rule | why "better" is not claimed |
| Business model | the volume where we lose |
| System architecture | containerisation — a spec requirement |
| Component 14 | why the CV model is core, not decorative |
| 13 of 14 components | why #11 is greyed out |
| How we evaluate | an unmeasured metric returns null |
| It works | "clean" ≠ "correct" |
| What we cannot claim | disclose it or it is a defect |

Median slide is ~90 words. If a slide creeps past ~120, cut something rather than
shrinking the type.

Diagram vocabulary used, one per idea:

| Slide | Shape |
|---|---|
| Today · Scope · vs ChatGPT | left-to-right flows and ✓/✗ columns |
| The 10× rule | three circles, two ticked |
| The arithmetic | two equations stacked, unit under every term |
| Business model | break-even chart + three priced tiers |
| RRL | 2×2 matrix — only one quadrant survives |
| Architecture | three lanes, DB cylinders, no crossing arrows |
| Ten stages · six passes | numbered chains |
| Parallel or sequential | a Gantt of three workers |
| Component 14 | a five-step ring |
| 13 of 14 components | a coloured tile grid, #11 greyed out |
| Prompt engineering | the real prompt with the clause under discussion highlighted |
| Guardrails | seven gates, each dropping a failure |
| Two ways to answer | side-by-side pipelines with the retry arc |
| ReAct | the loop with every exit drawn |
| Ten tools | hub and spokes, each tool showing its typed in → out contract |
| The API | a typed endpoint table — in, out and errors per route |
| How we evaluate | a four-layer pyramid, top one blocked |
| Metrics 1–4 | charts, plus big numbers |
| It works / it fails | receipt cards with ✓/✗ verdicts |
| Who built what | four avatar columns |

## Rebuild

```bash
python docs/presentation/charts.py      # regenerate figures + assets/facts.json
python docs/presentation/build_deck.py  # regenerate the .pptx
```

`charts.py` reads live repository data — `mlflow.db`, `evaluation/results/raw/trajectory-*.json`,
and the benchmark tables in `evaluation/PERFORMANCE.md` — and writes both the figures and
`assets/facts.json`. `build_deck.py` reads that file, so **every number on a slide moves when
the underlying data moves**. Nothing is typed twice.

## Things to change before presenting

| What | Where | Why |
|---|---|---|
| Team names and component ownership | `TEAM` in `build_deck.py` (also slide 32) | Taken from the root `README.md` ownership table — confirm it is current |
| Tech-stack logos | slide 1, the `STACK` list | Brand-coloured monogram tiles, 0.42" square, already positioned. Drop a real logo PNG on top of a tile and it lines up — the wordmark beside it stays |
| Pricing tiers | slide 6, the `tiers` list | ₱1,500/org/month and ₱60,000 appliance are proposals, not decisions |
| SaaS comparison rate | `UOM["saas_php_per_receipt"]` in `charts.py` | Currently ₱5.00/receipt, labelled *indicative*. Replace with a real quote or drop the line |
| Demo URLs | slide 33, "WHERE TO LOOK" | Deliberately left as descriptions; add the actual ports you will present on |

## The UoM model

Every assumption behind the value proposition lives in one dictionary — `UOM` in
`charts.py`. Change one entry and slide 4, slide 5 and the break-even chart on slide 6 all
move together. Two of the eight inputs are measured from our own traces (OCR seconds per
page, share of receipts held for review); the other six are declared assumptions and are
labelled as such on the slide.

## What the deck deliberately does not claim

- **Receipt-level accuracy.** There is no labelled ground truth in this repository, so field
  accuracy, line-item accuracy, exact match, review recall and false-review rate are all
  reported as uncomputed. Slides 4, 22 and 30 say so explicitly.
- **Multi-agent orchestration** (component #11). One planner over ten tools is not several
  collaborating agents.
- **LLM-as-a-judge.** Component #13 in the spec names it; we have unit, component and
  trajectory layers but no judge scorer. It is on the limitations slide as designed-not-built.

## Slide map

| # | Section | Slide |
|---|---|---|
| 1 | — | Title |
| 2–6 | Use case | Narrowed job · vs ChatGPT/Cowork · value proposition · UoM · business model |
| 7–8 | RRL | CV option space · model selection and the levers we left alone |
| 9–12 | Architecture | System diagram · extraction data flow · parallel vs sequential · CV integration |
| 13–21 | Components | Coverage · prompts · guardrails · SQL agent · retrieval · ReAct flow · tools · API · LLMOps |
| 22–30 | Findings | Eval design · 4 metrics · trace walkthrough · sample outputs · limitations |
| 31–32 | Retrospective | Five process questions · team contributions |
| 33–34 | Demo | Live demo script (at the end, per the spec) · takeaways |

## Editing a diagram

`build_deck.py` has a small vocabulary of primitives; every slide is built from them:

```python
label(sl, x, y, w, h, "Title", "subtitle")   # a labelled box
store(sl, x, y, w, h, "Ledger", "18 tables") # a database cylinder
flow(sl, y, [("Read", "sub", fill, edge), …]) # a chain of boxes with arrows
arrow(sl, x1, y1, x2, y2)                     # a line with a head on the end
mark(sl, x, y, "ok" | "bad")                  # a tick or a cross in a circle
chip(sl, x, y, "label")                       # a rounded pill, returns the next x
bignum(sl, x, y, w, "26×", "less human time") # a big number with a caption
note(sl, y, "Lead:", "the rest")              # the full-width strip at the bottom
```

`E()` rounds every coordinate to whole EMUs before it reaches the XML. Skip it and
PowerPoint reports the file as corrupt — a float in an `off`/`ext` attribute is
invalid OOXML, and that is exactly how this deck broke once already.

Positions are literal inches. When a shape collides with the footer at 6.94", move it
or shrink it — do not shrink the font.
