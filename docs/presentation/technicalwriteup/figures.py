"""Figures for the Snag technical write-up (Revision 2).

Every figure here is drawn, not screenshotted, and every figure that carries a
number takes that number from a source in this repository wherever one exists:

* `evaluation/results/raw/ocr-qwen2.5vl-7b.json`  -> the OCR benchmark headline,
  the per-receipt timings and the error tally
* `evaluation/PERFORMANCE.md`                     -> round trips, index, retrieval
* the UoM model in `docs/presentation/charts.py`  -> the cost comparison

Two rows of the three-model table have no raw output in the tree (Claude Cowork
and Gemma). They are drawn hatched and labelled UNSOURCED rather than quietly
plotted alongside the measured row -- the same rule `verify_facts.py` applies.

Run:  python docs/presentation/technicalwriteup/figures.py
Out:  docs/presentation/technicalwriteup/assets/fig-*.png
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Polygon

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / "assets"
OUT.mkdir(parents=True, exist_ok=True)

# The deck's ramp, unchanged: one neutral scale, one accent, two semantic colours.
INK = "#0F172A"
MUTED = "#6B7480"
FAINT = "#C2C9D2"
LINE = "#E7EAEE"
WASH = "#F5F7F9"
ACCENT = "#B45309"
ACCENT_WASH = "#FBF3E7"
NEUTRAL = "#A9B3C1"
GOOD = "#047857"
GOOD_WASH = "#EAF3EF"
BAD = "#B91C1C"
BAD_WASH = "#FAEDED"

plt.rcParams.update({
    "font.family": ["Segoe UI", "DejaVu Sans"],
    "font.size": 9,
    "axes.edgecolor": LINE,
    "axes.linewidth": 0.8,
    "axes.labelcolor": MUTED,
    "axes.labelsize": 8.5,
    "axes.titlecolor": INK,
    "axes.titlesize": 10,
    "axes.titlelocation": "left",
    "axes.titlepad": 10,
    "text.color": INK,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "xtick.labelsize": 8.5,
    "ytick.labelsize": 8.5,
    "xtick.major.size": 0,
    "ytick.major.size": 0,
    "legend.frameon": False,
    "legend.fontsize": 8.5,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
})

MONO = ["Consolas", "DejaVu Sans Mono", "monospace"]


# ---------------------------------------------------------------- primitives

def _save(fig, name: str) -> Path:
    path = OUT / name
    fig.savefig(path, dpi=220, bbox_inches="tight", pad_inches=0.06,
                facecolor="white")
    plt.close(fig)
    print(f"  wrote {path.relative_to(ROOT)}")
    return path


def _canvas(w: float, h: float, xlim=(0, 100), ylim=(0, 100)):
    """A blank drawing surface in arbitrary 0-100 units."""
    fig, ax = plt.subplots(figsize=(w, h))
    ax.set_xlim(*xlim)
    ax.set_ylim(*ylim)
    ax.axis("off")
    fig.subplots_adjust(0, 0, 1, 1)
    return fig, ax


def _box(ax, x, y, w, h, title=None, sub=None, *, fill="white", edge=FAINT,
         title_color=INK, sub_color=MUTED, title_size=9.5, sub_size=8,
         bold=True, mono=False, radius=0.9, lw=0.9, align="center", pad=1.6):
    """A rounded box with an optional title line and an optional subtitle."""
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h,
        boxstyle=f"round,pad=0,rounding_size={radius}",
        facecolor=fill, edgecolor=edge, linewidth=lw, zorder=2))
    if align == "center":
        tx, ha = x + w / 2, "center"
    else:
        tx, ha = x + pad, "left"
    if title and sub:
        ax.text(tx, y + h * 0.60, title, ha=ha, va="center", color=title_color,
                fontsize=title_size, fontweight="bold" if bold else "normal",
                family=MONO if mono else None, zorder=3)
        ax.text(tx, y + h * 0.27, sub, ha=ha, va="center", color=sub_color,
                fontsize=sub_size, zorder=3, linespacing=1.35)
    elif title:
        ax.text(tx, y + h / 2, title, ha=ha, va="center", color=title_color,
                fontsize=title_size, fontweight="bold" if bold else "normal",
                family=MONO if mono else None, zorder=3, linespacing=1.35)


def _arrow(ax, x1, y1, x2, y2, *, color=NEUTRAL, lw=1.1, style="-|>",
           mutation=9, connect=None, zorder=1):
    ax.add_patch(FancyArrowPatch(
        (x1, y1), (x2, y2), arrowstyle=style, mutation_scale=mutation,
        color=color, linewidth=lw, zorder=zorder, shrinkA=0, shrinkB=0,
        connectionstyle=connect or "arc3,rad=0"))


def _label(ax, x, y, text, *, size=8, color=MUTED, ha="left", va="center",
           mono=False, bold=False, style="normal", zorder=3):
    ax.text(x, y, text, ha=ha, va=va, fontsize=size, color=color, zorder=zorder,
            family=MONO if mono else None, linespacing=1.4, style=style,
            fontweight="bold" if bold else "normal")


def _band(ax, x, y, w, h, title, body):
    """A full-width cross-cutting band: something that runs under everything."""
    ax.add_patch(FancyBboxPatch(
        (x, y), w, h, boxstyle="round,pad=0,rounding_size=0.8",
        facecolor=WASH, edgecolor=LINE, linewidth=0.9, zorder=1))
    ax.text(x + 2.4, y + h / 2, title, ha="left", va="center", color=INK,
            fontsize=9, fontweight="bold", zorder=3)
    ax.text(x + 17, y + h / 2, body, ha="left", va="center", color=MUTED,
            fontsize=8.2, zorder=3, linespacing=1.4)


def _tidy(ax, *, xgrid=False, ygrid=False):
    ax.spines["left"].set_color(LINE)
    ax.spines["bottom"].set_color(LINE)
    if ygrid:
        ax.set_axisbelow(True)
        ax.yaxis.grid(True, color=LINE, linewidth=0.7)
    if xgrid:
        ax.set_axisbelow(True)
        ax.xaxis.grid(True, color=LINE, linewidth=0.7)


# ------------------------------------------------------------------ sources

def _benchmark() -> dict:
    """The OCR benchmark's raw output, if the eval branch's artefact is here."""
    for candidate in (
        ROOT / "evaluation/results/raw/ocr-qwen2.5vl-7b.json",
        ROOT / ".claude/worktrees/tr-revisions/evaluation/results/raw/ocr-qwen2.5vl-7b.json",
    ):
        if candidate.exists():
            return json.loads(candidate.read_text(encoding="utf-8"))
    return {}


# The per-receipt merchants and field accuracies as scored in the write-up
# (§7.2). The timings come from the raw JSON above; these labels do not.
RECEIPTS = [
    ("r1", "Ikkoryu Ramen", 92.9),
    ("r2", "All Filipino", 92.9),
    ("r3", "Savemore", 78.6),
    ("r4", "Cara Mia", 92.9),
    ("r5", "Isetann", 73.3),
    ("r6", "DBarn Manila", 73.3),
    ("r7", "McDonald's", 73.3),
    ("r8", "Bench Boutique", 73.3),
    ("r9", "Shake Shack", 75.0),
    ("r10", "DBarn Manila", 100.0),
]


# ------------------------------------------------------------------ figure 1

def fig_architecture() -> Path:
    """Five blocks, three things running under all of them.

    The CV model is drawn where it actually sits — inside Extract — with the
    span it feeds marked, because "core, not decorative" is a claim about what
    depends on it, and a diagram is where that claim is either visible or not.
    """
    fig, ax = _canvas(6.5, 4.45)

    blocks = [
        ("Capture", "upload · camera\nchat"),
        ("Extract", "read, repair,\ndecide"),
        ("Ledger", "one SQLite\nfile"),
        ("Agent", "plan,\nthen act"),
        ("Answer", "typed, cited,\ntraced"),
    ]
    w, gap, h, y = 16.4, 4.4, 19, 79
    x0 = (100 - (len(blocks) * w + (len(blocks) - 1) * gap)) / 2
    for i, (title, sub) in enumerate(blocks):
        x = x0 + i * (w + gap)
        accented = title in ("Extract", "Agent")
        _box(ax, x, y, w, h, None, fill=ACCENT_WASH if accented else "white",
             edge=ACCENT if accented else FAINT)
        _label(ax, x + w / 2, y + h * 0.68, title, size=11.5, color=INK,
               ha="center", bold=True)
        _label(ax, x + w / 2, y + h * 0.30, sub, size=7.8, color=MUTED,
               ha="center")
        if i:
            _arrow(ax, x - gap + 0.4, y + h / 2, x - 0.8, y + h / 2,
                   color=FAINT, lw=1.2, mutation=10)

    # where the CV model is, and what depends on it
    ex = x0 + (w + gap)
    _arrow(ax, ex + w / 2, 71.5, ex + w / 2, y - 0.6, color=ACCENT, lw=1.1,
           mutation=8)
    _label(ax, ex + w / 2, 70.5, "gemma4:e4b — the CV model", size=8,
           color=ACCENT, ha="center", va="top", bold=True)
    _label(ax, ex + w / 2, 66.6, "stage 3 of ten", size=7.4, color=ACCENT,
           ha="center", va="top")

    span_l, span_r, sy = x0 + 2 * (w + gap), x0 + 5 * w + 4 * gap, 74.5
    ax.plot([span_l, span_r], [sy, sy], color=FAINT, lw=0.9, zorder=1)
    for xx in (span_l, span_r):
        ax.plot([xx, xx], [sy, sy + 2.2], color=FAINT, lw=0.9, zorder=1)
    _label(ax, (span_l + span_r) / 2, sy - 1.4,
           "every block here reads only what it produced",
           size=7.6, color=MUTED, ha="center", va="top")

    _label(ax, 50, 59,
           "Nothing computes a new figure on the way through — each hand-off "
           "re-represents\nwhat the paper said, which is why a disputed number "
           "walks back to the pixel it came from.",
           size=8, ha="center", color=MUTED)

    bands = [
        ("API", "80 typed routes. Browser, demo and eval harness all enter here;\n"
                "nothing has a privileged path in."),
        ("Models", "vision · planner · embeddings — all over HTTP to OLLAMA_HOST."),
        ("Traces", "every model call opens an MLflow run. A failed call is still a run."),
    ]
    by, bh, bgap = 36, 13, 3.2
    for i, (title, body) in enumerate(bands):
        _band(ax, x0, by - i * (bh + bgap), 100 - 2 * x0, bh, title, body)

    return _save(fig, "fig-01-architecture.png")


# ------------------------------------------------------------------ figure 2

def fig_pipeline() -> Path:
    """The ten stages between a photograph and a filed row."""
    fig, ax = _canvas(6.5, 7.1, ylim=(-18, 102))

    stages = [
        ("1", "validate_input()", "file type and size, before anything touches the model",
         "guard"),
        ("2", "preprocess_image()", "EXIF rotate · long edge to 1,600 px · JPEG re-encode",
         "plain"),
        ("3", "vision model call", "temperature 0 · format=\"json\" · 19-rule transcription prompt",
         "model"),
        ("4", "deterministic cleanup", "strip \"qty @ price\" · dedupe · remap tax lines · undo double VAT",
         "plain"),
        ("5", "validate_output()", "Pydantic ReceiptData / LineItem — 23 typed fields",
         "guard"),
        ("6", "audit_extraction()", "10 arithmetic checks against the receipt's own numbers",
         "guard"),
        ("7", "assess_item_coverage()", "complete · incomplete · unverified · empty",
         "plain"),
        ("8", "needs_disambiguation()", "missing total · no items · discount without TIN · won't reconcile",
         "guard"),
        ("9", "compute_extraction_confidence()", "geometric mean of the field's own token probabilities",
         "plain"),
        ("10", "save_receipt()", "ledger row + line items + (deferred) RAG embedding",
         "plain"),
    ]

    fills = {"guard": ACCENT_WASH, "model": WASH, "plain": "white"}
    edges = {"guard": ACCENT, "model": FAINT, "plain": FAINT}

    top, h, gap = 95.0, 6.4, 2.6
    bx, bw = 6, 62

    _box(ax, bx, top, bw, 5.6, "Receipt image or PDF page",
         fill=WASH, edge=FAINT, title_size=9.5, align="left")

    for i, (num, name, sub, kind) in enumerate(stages):
        y = top - (i + 1) * (h + gap)
        _box(ax, bx, y, bw, h, None, None, fill=fills[kind], edge=edges[kind])
        _label(ax, bx + 3.2, y + h / 2, num, size=8.5, color=MUTED, ha="center",
               bold=True)
        _label(ax, bx + 6.6, y + h * 0.63, name, size=9, color=INK, mono=True,
               bold=True)
        _label(ax, bx + 6.6, y + h * 0.26, sub, size=7.6, color=MUTED)
        _arrow(ax, bx + bw / 2, y + h + gap if i else top, bx + bw / 2,
               y + h + 0.5, color=FAINT, lw=1.1)
        if num == "8":
            hold_y = y
        if num == "6":
            audit_y = y

    # the branch that is the point of the whole thing
    _box(ax, bx + bw + 7, hold_y - 0.6, 24, h + 1.2, "HELD for review",
         "15.4% of receipts (6 of 39 traced)", fill=BAD_WASH, edge=BAD,
         title_color=BAD, title_size=9, sub_size=7.4)
    _arrow(ax, bx + bw + 0.6, hold_y + h / 2, bx + bw + 6.4, hold_y + h / 2,
           color=BAD, lw=1.1)

    _label(ax, bx + bw + 7, audit_y + h / 2,
           "A failure names both numbers\nand the gap. Nothing is\nauto-corrected here.",
           size=7.6, color=MUTED)

    last_y = top - len(stages) * (h + gap)
    _box(ax, bx, last_y - 8.2, bw, 5.6,
         "MLflow run — latency · tokens · confidence · audit codes · errors",
         fill=WASH, edge=FAINT, title_size=8.6, bold=False, align="left")
    _arrow(ax, bx + bw / 2, last_y, bx + bw / 2, last_y - 2.1, color=FAINT, lw=1.1)

    _label(ax, bx, last_y - 14.5,
           "Three second-look mechanisms sit beside this line — recovery, region crop, "
           "and check-driven zoom.\nAll three are strictly additive: a correction is kept "
           "only if the receipt's own arithmetic improves.",
           size=7.8, color=MUTED)

    return _save(fig, "fig-02-pipeline.png")


# ------------------------------------------------------------------ figure 3

def fig_three_models() -> Path:
    """The comparison table as a chart, with its provenance drawn in."""
    fig, (ax, ax2) = plt.subplots(
        1, 2, figsize=(6.5, 3.05), gridspec_kw={"width_ratios": [2.5, 1]})

    models = ["Claude Cowork\nhosted seat", "qwen2.5-VL 7B\nlocal, measured",
              "Gemma  gemma4:e4b\nlocal, in production"]
    accuracy = [97.0, 86.3, 51.7]
    precision = [94.0, 89.6, 92.5]
    recall = [98.0, 94.5, 69.8]
    sourced = [False, True, False]

    xs = range(len(models))
    width = 0.26
    series = [("Accuracy", accuracy, INK), ("Precision", precision, ACCENT),
              ("Recall", recall, NEUTRAL)]
    for si, (name, vals, colour) in enumerate(series):
        off = (si - 1) * width
        for i, v in enumerate(vals):
            ax.bar(i + off, v, width, color=colour if sourced[i] else "white",
                   edgecolor=colour, linewidth=0.9,
                   hatch=None if sourced[i] else "////",
                   label=name if i == 1 else None, zorder=2)
            ax.text(i + off, v + 2, f"{v:.1f}".rstrip("0").rstrip(".") + "%",
                    ha="center", va="bottom", fontsize=7.6, color=INK)

    ax.set_xticks(list(xs))
    ax.set_xticklabels(models, fontsize=8)
    ax.set_ylim(0, 115)
    ax.set_yticks([0, 25, 50, 75, 100])
    ax.set_ylabel("percent")
    ax.legend(loc="upper right", ncol=3, bbox_to_anchor=(1.02, 1.16),
              handlelength=1.1)
    ax.set_title("Accuracy · precision · recall")
    _tidy(ax, ygrid=True)

    chips = ["UNSOURCED", "reproducible from this repo", "UNSOURCED"]
    for i, (s, chip) in enumerate(zip(sourced, chips)):
        ax.annotate(chip, xy=(i, 0), xytext=(0, -34), textcoords="offset points",
                    xycoords=("data", "axes fraction"), ha="center", va="top",
                    fontsize=7, color=GOOD if s else BAD, fontweight="bold")

    times = [15, 340, 21.7]
    labels = ["15 s", "5m 40s", "21.7 s"]
    colours = [NEUTRAL, ACCENT, NEUTRAL]
    ax2.barh(range(3), times, 0.55, color=colours, zorder=2)
    for i, (t, lab) in enumerate(zip(times, labels)):
        ax2.text(t + 12, i, lab, va="center", fontsize=8, color=INK)
    ax2.set_yticks(range(3))
    ax2.set_yticklabels(["Cowork", "qwen2.5-VL", "Gemma"], fontsize=8)
    ax2.invert_yaxis()
    ax2.set_xlim(0, 470)
    ax2.set_xticks([0, 150, 300])
    ax2.set_xlabel("seconds / receipt")
    ax2.set_title("Time per receipt")
    _tidy(ax2, xgrid=True)
    ax2.text(0, 3.05,
             "qwen ran on a 4 GB card:\nfour fifths of every page\nfell back to the CPU.",
             fontsize=7.4, color=MUTED, va="top")

    fig.text(0.005, -0.10,
             "Hatched bars are hands-on runs with no raw output in the tree — "
             "verify_facts.py reports them UNSOURCED rather than as passing checks.\n"
             "Gemma's precision/recall pair is line detection, not field values, "
             "so it is not directly comparable with the qwen row.",
             fontsize=7.4, color=MUTED, linespacing=1.5)
    fig.tight_layout()
    return _save(fig, "fig-03-three-models.png")


# ------------------------------------------------------------------ figure 4

def fig_error_taxonomy() -> Path:
    """The 17 false positives and 9 false negatives are not scattered."""
    fig, ax = plt.subplots(figsize=(6.5, 3.15))

    classes = [
        ("Phantom subtotal", 5, 0, "all 5 receipts that print no subtotal"),
        ("Payment fields on card sales", 5, 0, "card read as cash · invented change = 0.00"),
        ("Identifier confusion", 5, 5, "date, POS serial or MAN taken as the number"),
        ("Hallucinated VAT block (r7)", 2, 1, "486.61 × 12% ≈ 58.39 — self-consistent, wrong"),
        ("Printed zeros read as absent", 0, 2, "a printed 0.00 is information"),
        ("Missed discount", 0, 1, "the 54.00 senior discount on r6"),
    ]
    ys = range(len(classes))
    height = 0.34
    for i, (name, fp, fn, note) in enumerate(classes):
        ax.barh(i - height / 2 - 0.02, fp, height, color=ACCENT, zorder=2,
                label="False positive — asserted something untrue" if i == 0 else None)
        ax.barh(i + height / 2 + 0.02, fn, height, color=NEUTRAL, zorder=2,
                label="False negative — failed to capture what was there" if i == 0 else None)
        if fp:
            ax.text(fp + 0.12, i - height / 2 - 0.02, str(fp), va="center",
                    fontsize=8, color=ACCENT, fontweight="bold")
        if fn:
            ax.text(fn + 0.12, i + height / 2 + 0.02, str(fn), va="center",
                    fontsize=8, color=MUTED, fontweight="bold")
        ax.text(6.15, i, note, va="center", fontsize=7.6, color=MUTED)

    ax.set_yticks(list(ys))
    ax.set_yticklabels([c[0] for c in classes], fontsize=8.4, color=INK)
    ax.invert_yaxis()
    ax.set_xlim(0, 6)
    ax.set_xticks(range(0, 7))
    ax.set_xlabel("scored slots (of 191)")
    ax.set_title("Where the 26 errors are — the top two are more than half")
    ax.legend(loc="lower right", bbox_to_anchor=(1.0, -0.42), handlelength=1.1)
    _tidy(ax, xgrid=True)
    fig.tight_layout()
    return _save(fig, "fig-05-error-taxonomy.png")


# ------------------------------------------------------------------ figure 5

def fig_per_receipt() -> Path:
    """Time is driven by how much JSON comes back, not by how big the file is."""
    data = _benchmark()
    times = {r["id"]: r["elapsed_s"] for r in data.get("per_receipt", [])}
    if not times:                                    # the artefact lives on a branch
        times = {"r1": 291.92, "r2": 460.14, "r3": 297.21, "r4": 244.34,
                 "r5": 564.78, "r6": 283.10, "r7": 246.29, "r8": 685.74,
                 "r9": 180.37, "r10": 148.46}

    fig, (ax, ax2) = plt.subplots(
        1, 2, figsize=(6.5, 2.95), gridspec_kw={"width_ratios": [1.55, 1]})

    ids = [r[0] for r in RECEIPTS]
    vals = [times[i] for i in ids]
    mean = sum(vals) / len(vals)
    labels = [f"{r[0]}  {r[1]}" for r in RECEIPTS]

    colours = [ACCENT if v > 500 else NEUTRAL for v in vals]
    ax.barh(range(len(vals)), vals, 0.62, color=colours, zorder=2)
    for i, v in enumerate(vals):          # one label column, never over the bars
        ax.text(880, i, f"{int(v // 60)}m {int(v % 60):02d}s", va="center",
                ha="right", fontsize=7.6, color=INK)
    ax.axvline(mean, color=INK, linewidth=0.9, linestyle=(0, (3, 2)), zorder=3)
    ax.text(mean + 8, -0.95, f"mean {mean:.0f} s", fontsize=7.4, color=INK)
    ax.set_yticks(range(len(vals)))
    ax.set_yticklabels(labels, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlim(0, 890)
    ax.set_xticks([0, 200, 400, 600])
    ax.set_xlabel("seconds")
    ax.set_title("Time per receipt — 10 labelled receipts")
    _tidy(ax, xgrid=True)

    # the point: output length drives the clock, file size does not
    pairs = [("r5\nIsetann", 3.29, times["r5"]), ("r8\nBench", 0.17, times["r8"])]
    x = [0, 1]
    ax2.bar([i - 0.19 for i in x], [p[1] for p in pairs], 0.36, color=FAINT,
            zorder=2, label="source image (MB)")
    ax2b = ax2.twinx()
    ax2b.bar([i + 0.19 for i in x], [p[2] for p in pairs], 0.36, color=ACCENT,
             zorder=2, label="time (s)")
    for i, p in enumerate(pairs):
        ax2.text(i - 0.19, p[1] + 0.08, f"{p[1]} MB", ha="center", fontsize=7.6,
                 color=MUTED)
        ax2b.text(i + 0.19, p[2] + 18, f"{p[2]:.0f} s", ha="center", fontsize=7.6,
                  color=ACCENT, fontweight="bold")
    ax2.set_xticks(x)
    ax2.set_xticklabels([p[0] for p in pairs], fontsize=8)
    ax2.set_ylim(0, 4.6)
    ax2.set_ylabel("megabytes")
    ax2b.set_ylim(0, 830)
    ax2b.set_ylabel("seconds", color=ACCENT)
    ax2b.tick_params(colors=MUTED)
    ax2b.spines["top"].set_visible(False)
    ax2b.spines["right"].set_color(LINE)
    ax2.set_title("19× smaller, two minutes slower")
    _tidy(ax2)
    ax2.text(-0.42, -1.35,
             "Every image is downscaled to 1,600 px before the model sees it, so file\n"
             "size does not reach it. r8's nine near-identical rows are the longest\n"
             "output in the set — and output length is what drives the clock.",
             fontsize=7.4, color=MUTED, va="top")

    fig.tight_layout()
    return _save(fig, "fig-04-per-receipt.png")


# ------------------------------------------------------------------ figure 6

def fig_performance() -> Path:
    """What the performance pass actually moved."""
    fig, axes = plt.subplots(1, 3, figsize=(6.5, 2.6))
    a, b, c = axes

    # (a) round trips
    labels = ["POST /ask", "POST /agent"]
    before, after = [2, 4], [1, 3]
    x = range(2)
    a.bar([i - 0.18 for i in x], before, 0.34, color=FAINT, zorder=2, label="before")
    a.bar([i + 0.18 for i in x], after, 0.34, color=ACCENT, zorder=2, label="after")
    for i in x:
        a.text(i - 0.18, before[i] + 0.09, str(before[i]), ha="center", fontsize=8,
               color=MUTED)
        a.text(i + 0.18, after[i] + 0.09, str(after[i]), ha="center", fontsize=8,
               color=ACCENT, fontweight="bold")
    a.set_xticks(list(x))
    a.set_xticklabels(labels, fontsize=8)
    a.set_ylim(0, 5)
    a.set_yticks(range(0, 5))
    a.set_ylabel("model round trips")
    a.set_title("One call removed")
    a.legend(loc="upper left", handlelength=1.1)
    _tidy(a, ygrid=True)

    # (b) the index
    b.bar([0, 1], [658.9, 2.9], 0.5, color=[FAINT, ACCENT], zorder=2)
    b.set_yscale("log")
    b.set_ylim(1, 3000)
    b.set_xticks([0, 1])
    b.set_xticklabels(["no index", "indexed"], fontsize=8)
    b.set_ylabel("ms (log)")
    b.text(0, 780, "658.9 ms", ha="center", fontsize=8, color=MUTED)
    b.text(1, 3.6, "2.9 ms", ha="center", fontsize=8, color=ACCENT,
           fontweight="bold")
    b.text(0.5, 1400, "227×", ha="center", fontsize=11, color=INK,
           fontweight="bold")
    b.set_title("line_items(receipt_id)")
    _tidy(b, ygrid=True)

    # (c) retrieval
    groups = ["whole ledger", "scoped to 1"]
    bef, aft = [19.21, 7.99], [14.58, 0.33]
    x = range(2)
    c.bar([i - 0.18 for i in x], bef, 0.34, color=FAINT, zorder=2)
    c.bar([i + 0.18 for i in x], aft, 0.34, color=ACCENT, zorder=2)
    for i in x:
        c.text(i - 0.18, bef[i] + 0.5, f"{bef[i]}", ha="center", fontsize=7.6,
               color=MUTED)
        c.text(i + 0.18, aft[i] + 0.5, f"{aft[i]}", ha="center", fontsize=7.6,
               color=ACCENT, fontweight="bold")
    c.text(1.0, 12.5, "24×", ha="center", fontsize=11, color=INK,
           fontweight="bold")
    c.set_xticks(list(x))
    c.set_xticklabels(groups, fontsize=8)
    c.set_ylim(0, 23)
    c.set_ylabel("ms at 5,000 receipts")
    c.set_title("Retrieval hot path")
    _tidy(c, ygrid=True)

    fig.text(0.005, -0.06,
             "Neither Ollama endpoint was reachable during the performance pass, so no "
             "end-to-end latency was measured. One vision call is ~6,000 ms:\n"
             "cutting a round trip is worth roughly 400× more than making retrieval "
             "infinitely fast, which is why the round-trip count got the regression test.",
             fontsize=7.4, color=MUTED, linespacing=1.5)
    fig.tight_layout()
    return _save(fig, "fig-06-performance.png")


# ------------------------------------------------------------------ figure 7

def fig_react_loop() -> Path:
    """Reasoning and acting, interleaved — and the five ways out."""
    fig, ax = _canvas(6.5, 4.6)

    _box(ax, 4, 87, 40, 9, "Question + the last 10 turns", fill=WASH,
         edge=FAINT, title_size=9.5)

    # the ambiguity gate
    dx, dy = 24, 76
    ax.add_patch(Polygon([(dx, dy + 5.5), (dx + 11, dy), (dx, dy - 5.5),
                          (dx - 11, dy)], closed=True, facecolor="white",
                         edgecolor=FAINT, linewidth=0.9, zorder=2))
    _label(ax, dx, dy, "Ambiguous?", size=8.6, color=INK, ha="center", bold=True)
    _arrow(ax, 24, 87, 24, dy + 5.9, color=FAINT)
    _arrow(ax, dx + 11.4, dy, 51, dy, color=FAINT)
    _box(ax, 51.5, dy - 5, 33, 10, "Ask once", "nothing runs · 0 steps",
         fill=WASH, edge=FAINT, title_size=9, sub_size=7.6)
    _label(ax, 36, dy + 2.4, "yes", size=7.4, color=MUTED, ha="center")
    _label(ax, 25.6, dy - 9, "no", size=7.4, color=MUTED)

    # the loop
    ly, lh = 38, 25
    ax.add_patch(FancyBboxPatch(
        (4, ly), 54, lh, boxstyle="round,pad=0,rounding_size=1.0",
        facecolor=ACCENT_WASH, edgecolor=ACCENT, linewidth=1.0, zorder=1))
    _arrow(ax, 24, dy - 5.9, 24, ly + lh + 0.6, color=FAINT)

    bw, byy, bh = 14.0, ly + 13.5, 7.5
    steps = [("Thought", 7.0), ("Action", 24.0), ("Observation", 41.0)]
    for name, x in steps:
        _box(ax, x, byy, bw, bh, name, fill="white", edge=ACCENT, title_size=8.8)
    for x in (7.0, 24.0):                      # left to right, box to box
        _arrow(ax, x + bw + 0.3, byy + bh / 2, x + bw + 2.7, byy + bh / 2,
               color=ACCENT, lw=1.1)

    # and back again, routed under the boxes rather than through them
    back = ly + 8.0
    ax.plot([48.0, 48.0], [byy - 0.3, back], color=ACCENT, lw=1.0, zorder=3)
    ax.plot([48.0, 14.0], [back, back], color=ACCENT, lw=1.0, zorder=3)
    _arrow(ax, 14.0, back, 14.0, byy - 0.4, color=ACCENT, lw=1.0, mutation=8,
           zorder=3)

    _label(ax, 31, ly + 3.4, "at most 4 steps, one tool each  ·  mean 1.98 "
           "over 113 traced runs", size=7.6, color=ACCENT, ha="center")

    _label(ax, 61, ly + 20,
           "Generation is stopped at the token", size=7.8, color=MUTED)
    _label(ax, 61, ly + 16.4, "Observation:", size=7.8, color=INK, mono=True)
    _label(ax, 61, ly + 12.0,
           "— so the model can never write\nits own. That is what makes this\n"
           "a loop over tools rather than a\nmonologue about them.",
           size=7.8, color=MUTED, va="top")

    # the exit and the veto
    _box(ax, 4, 22, 54, 9, "Final Answer — only what the tools returned",
         fill="white", edge=FAINT, title_size=9)
    _arrow(ax, 31, ly, 31, 31.6, color=FAINT)
    _box(ax, 4, 5, 54, 12, "Grounding veto  ·  _ungrounded_numbers()",
         "a figure about your money with no tool\ncall behind it is replaced, "
         "not shown", fill=BAD_WASH, edge=BAD, title_color=BAD, title_size=8.8,
         sub_size=7.4)
    _arrow(ax, 31, 22, 31, 17.6, color=FAINT)
    _label(ax, 61, 11, "Measured: 0 ungrounded\nnumbers across 64\ntraced runs.",
           size=7.8, color=GOOD, va="center")

    _label(ax, 61, 32,
           "Five ways out:  a Final Answer ·\na clarification · no action and\n"
           "no answer · the same tool twice ·\nthe budget spent, and\n"
           "_force_final writes one from\nthe observations.",
           size=7.8, color=MUTED, va="top")

    return _save(fig, "fig-07-react-loop.png")


# ------------------------------------------------------------------ figure 8

def fig_guardrails() -> Path:
    """Seven gates between a request and the ledger."""
    fig, ax = _canvas(6.5, 4.25)

    gates = [
        ("File check", "validate_input", "wrong type · over 25 MB"),
        ("Schema check", "validate_output", "a malformed model reply"),
        ("SQL filter", "_validate_sql", "anything that is not a SELECT"),
        ("Scope lock", "_build_scoped_db", "reading the whole ledger when scoped"),
        ("Sanitiser", "_sanitize_observation", "injection via a vendor name"),
        ("Grounding", "_ungrounded_numbers", "a figure no tool returned"),
        ("Write guards", "_guard_amount", "wrong account · double entry"),
    ]

    _box(ax, 8, 91, 46, 7, "A request", fill=WASH, edge=FAINT, title_size=9)
    top, h, gap = 88.0, 8.2, 2.2
    for i, (name, fn, drops) in enumerate(gates):
        y = top - (i + 1) * (h + gap)
        _box(ax, 8, y, 46, h, None, fill="white", edge=FAINT)
        _label(ax, 11, y + h / 2, name, size=9, color=INK, bold=True)
        _label(ax, 27, y + h / 2, fn + "()", size=8.2, color=ACCENT, mono=True)
        _arrow(ax, 55, y + h / 2, 60.5, y + h / 2, color=BAD, lw=1.0, mutation=8)
        _label(ax, 61.5, y + h / 2, drops, size=7.8, color=MUTED)
        _arrow(ax, 31, y + h + gap, 31, y + h + 0.4, color=FAINT, lw=1.0)
    _arrow(ax, 31, 91, 31, top - gap - h + h + 0.4, color=FAINT, lw=1.0)

    bottom = top - len(gates) * (h + gap)
    _box(ax, 8, bottom - 8.4, 46, 7, "The ledger", fill=GOOD_WASH, edge=GOOD,
         title_color=GOOD, title_size=9)
    _arrow(ax, 31, bottom, 31, bottom - 1.0, color=FAINT, lw=1.0)
    _label(ax, 61.5, bottom - 4.9, "what survives all seven", size=7.8, color=GOOD)

    return _save(fig, "fig-08-guardrails.png")


# ------------------------------------------------------------------ figure 9

def fig_deployment() -> Path:
    """Three containers, one command, and inference as an HTTP call out."""
    fig, ax = _canvas(6.5, 3.2)

    ax.add_patch(FancyBboxPatch(
        (3, 10), 63, 82, boxstyle="round,pad=0,rounding_size=1.0",
        facecolor="white", edgecolor=FAINT, linewidth=0.9,
        linestyle=(0, (4, 3)), zorder=1))
    _label(ax, 5.5, 88, "docker compose  ·  one host", size=8.2, color=MUTED,
           bold=True)

    _label(ax, 34, 76.5, "same-origin /api/* → http://api:8000\n"
           "no CORS to configure", size=7.2, color=MUTED, ha="center",
           va="bottom")

    _box(ax, 7, 55, 25, 19, "web", "Next.js\n${WEB_PORT:-7860} → 3000",
         fill=WASH, edge=FAINT, title_size=10, sub_size=7.4)
    _box(ax, 36, 55, 25, 19, "api", "FastAPI · uvicorn\n${API_PORT:-8000} → 8000",
         fill=ACCENT_WASH, edge=ACCENT, title_size=10, sub_size=7.4)
    _box(ax, 7, 26, 25, 18, "mlflow", "tracking UI\n5001 → 5000", fill=WASH,
         edge=FAINT, title_size=10, sub_size=7.4)
    _box(ax, 36, 26, 25, 18, "named volume",
         "ledger.db — a real Linux filesystem,\nnot a bind mount",
         fill=GOOD_WASH, edge=GOOD, title_size=9, sub_size=7.0)

    _arrow(ax, 32.4, 64.5, 35.4, 64.5, color=NEUTRAL, lw=1.1)
    _arrow(ax, 48.5, 55, 48.5, 44.6, color=NEUTRAL, lw=1.1)
    _arrow(ax, 39.5, 55, 25, 44.6, color=FAINT, lw=1.0)

    _box(ax, 70, 55, 28, 19, "OLLAMA_HOST", "vision · planner\nembeddings",
         fill="white", edge=ACCENT, title_size=9.5, sub_size=7.4, mono=True)
    _arrow(ax, 61.4, 64.5, 69.4, 64.5, color=ACCENT, lw=1.2)
    _label(ax, 70, 50, "inference is an HTTP call\nout of the container",
           size=7.4, color=ACCENT, va="top")

    _label(ax, 70, 38,
           "Models are environment, not\ncode. Point OLLAMA_HOST at\n"
           "localhost and the whole stack\nruns fully offline.",
           size=7.6, color=MUTED, va="top")

    _label(ax, 5.5, 17,
           "One command builds two images, pulls one, and brings all three up in "
           "declared order.\nNo Python, no Node and no model need be installed first.",
           size=7.6, color=MUTED)

    return _save(fig, "fig-09-deployment.png")


# ----------------------------------------------------------------- figure 10

def fig_cost() -> Path:
    """300 receipts a month, three ways."""
    fig, (ax, ax2) = plt.subplots(
        1, 2, figsize=(6.5, 2.7), gridspec_kw={"width_ratios": [1.35, 1]})

    options = ["One pair of hands\n10 h of typing, every month",
               "A Claude subscription\n$20/mo, and you wire it up",
               "Snag\nset up, running"]
    costs = [1562, 1160, 99]
    colours = [FAINT, NEUTRAL, ACCENT]
    ax.barh(range(3), costs, 0.55, color=colours, zorder=2)
    for i, c in enumerate(costs):
        ax.text(c + 35, i, f"₱{c:,}", va="center", fontsize=9, color=INK,
                fontweight="bold" if i == 2 else "normal")
    ax.set_yticks(range(3))
    ax.set_yticklabels(options, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlim(0, 1980)
    ax.set_xticks([0, 500, 1000, 1500])
    ax.set_xlabel("₱ per month, 300 receipts")
    ax.set_title("Cost of the same 300 receipts")
    _tidy(ax, xgrid=True)
    ax.text(1960, 1.62, "≈16× cheaper than typing them\n≈12× cheaper than a "
            "subscription\nyou configure yourself", fontsize=7.6, color=MUTED,
            ha="right", va="center")

    hours = [10.0, 0.4]
    ax2.bar([0, 1], hours, 0.5, color=[FAINT, ACCENT], zorder=2)
    for i, h in enumerate(hours):
        ax2.text(i, h + 0.25, f"{h} h", ha="center", fontsize=9, color=INK,
                 fontweight="bold" if i else "normal")
    ax2.set_xticks([0, 1])
    ax2.set_xticklabels(["by hand\n2.0 min each", "with Snag\n15.4% held, 0.5 min"],
                        fontsize=8)
    ax2.set_ylim(0, 12.5)
    ax2.set_ylabel("human hours / month")
    ax2.set_title("26× less human time")
    _tidy(ax2, ygrid=True)

    fig.text(0.005, -0.12,
             "Two of the eight inputs behind these figures are measured from our own "
             "MLflow traces — 14.9 s per page and the 15.4% hold rate.\n"
             "The other six are declared assumptions, and the ₱99 price is a proposal, "
             "not a decision.",
             fontsize=7.4, color=MUTED, linespacing=1.5)
    fig.tight_layout()
    return _save(fig, "fig-10-cost.png")


# ---------------------------------------------------------------------- main

FIGURES = [
    ("fig-01-architecture.png", fig_architecture),
    ("fig-02-pipeline.png", fig_pipeline),
    ("fig-03-three-models.png", fig_three_models),
    ("fig-04-per-receipt.png", fig_per_receipt),
    ("fig-05-error-taxonomy.png", fig_error_taxonomy),
    ("fig-06-performance.png", fig_performance),
    ("fig-07-react-loop.png", fig_react_loop),
    ("fig-08-guardrails.png", fig_guardrails),
    ("fig-09-deployment.png", fig_deployment),
    ("fig-10-cost.png", fig_cost),
]


def build_all() -> list[Path]:
    print("Building write-up figures…")
    return [fn() for _, fn in FIGURES]


if __name__ == "__main__":
    build_all()
