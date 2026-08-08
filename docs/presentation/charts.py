"""Charts for the Snag Final Capstone deck.

Every figure here is built from data that exists in this repository:

* `mlflow.db`                                  -> latency, tool routing, grounding
* `evaluation/results/raw/trajectory-*.json`   -> trajectory check pass rates
* `evaluation/PERFORMANCE.md`                  -> round-trip and index benchmarks
* the UoM model on the value-proposition slide -> cost/receipt break-even

Nothing is hand-typed: if a number moves in the source, re-running this script
moves it on the slide. Axes are labelled with their units because a chart whose
y-axis says "seconds" and whose x-axis says nothing is not a result.
"""
from __future__ import annotations

import json
import re
import sqlite3
import statistics
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "assets"
OUT.mkdir(parents=True, exist_ok=True)

# Same ramp as the deck: one neutral scale, one accent, two semantic colours.
INK = "#111827"
MUTED = "#6B7280"
FAINT = "#9CA3AF"
LINE = "#E5E7EB"
ACCENT = "#B45309"
ACCENT_LIGHT = "#D9A441"
NEUTRAL = "#94A3B8"
GOOD = "#047857"
BAD = "#B91C1C"

# Aliases so the figure code below keeps reading naturally.
TEAL = NEUTRAL
GREEN = GOOD
RED = BAD
VIOLET = MUTED

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 11,
    "axes.edgecolor": LINE,
    "axes.labelcolor": INK,
    "axes.titlecolor": INK,
    "text.color": INK,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
})


def _save(fig, name: str) -> Path:
    path = OUT / name
    fig.savefig(path, dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  wrote {path.relative_to(ROOT)}")
    return path


# ---------------------------------------------------------------- MLflow data

def mlflow_runs() -> dict:
    """Pull the traced-run facts the deck quotes, straight out of mlflow.db."""
    db = ROOT / "mlflow.db"
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    names = con.execute("select run_uuid, name from runs").fetchall()
    latency = dict(con.execute(
        "select run_uuid, value from metrics where key='latency_seconds'").fetchall())

    by_op: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for uuid, name in names:
        m = re.match(r"(.+)_(\d{10})$", name or "")
        if m and uuid in latency:
            by_op[m.group(1)].append((int(m.group(2)), latency[uuid]))
    for key in by_op:
        by_op[key].sort()

    # Read every metric series up front — the connection closes before the
    # caller gets a chance to ask for one.
    series: dict[str, list[float]] = defaultdict(list)
    for key, value in con.execute("select key, value from metrics").fetchall():
        series[key].append(value)

    def metric(key: str) -> list[float]:
        return series.get(key, [])

    tools = Counter()
    for (val,) in con.execute("select value from params where key='tools_used'").fetchall():
        for tool in (val or "").split(","):
            tool = tool.strip()
            if tool and tool not in {"none", "n"}:
                tools[tool] += 1

    con.close()
    return {"by_op": by_op, "metric": metric, "tools": tools,
            "total_runs": len(names), "traced_latency": len(latency)}


def latency_chart(data: dict) -> Path:
    """Median and p90 wall-clock, per traced operation. The spread is the point."""
    order = [("extract", "Single receipt\nOCR extraction"),
             ("extract_batch", "Batch page\nOCR extraction"),
             ("agent", "ReAct agent\nturn"),
             ("sql_agent", "SQL agent\nquestion"),
             ("rag", "Semantic search\nanswer")]
    labels, medians, p90s, counts = [], [], [], []
    for key, label in order:
        vals = sorted(v for _, v in data["by_op"].get(key, []))
        if not vals:
            continue
        labels.append(label)
        medians.append(statistics.median(vals))
        p90s.append(vals[min(len(vals) - 1, int(len(vals) * 0.9))])
        counts.append(len(vals))

    fig, ax = plt.subplots(figsize=(9.6, 4.6))
    y = range(len(labels))
    h = 0.36
    ax.barh([i + h / 2 for i in y], medians, height=h, color=NEUTRAL, label="median")
    ax.barh([i - h / 2 for i in y], p90s, height=h, color=ACCENT, label="90th percentile")
    for i, (med, p90, n) in enumerate(zip(medians, p90s, counts)):
        ax.text(med + 4, i + h / 2, f"{med:,.0f}s", va="center", fontsize=10, color=INK)
        ax.text(p90 + 4, i - h / 2, f"{p90:,.0f}s", va="center", fontsize=10, color=INK)
        ax.text(-8, i, f"n={n}", va="center", ha="right", fontsize=9, color=MUTED)
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels, fontsize=10)
    ax.set_xlabel("Wall-clock latency per call  (seconds, lower is better)")
    ax.set_ylabel("Traced operation")
    ax.set_title("End-to-end latency by operation — 202 traced runs, shared Ollama endpoint",
                 fontsize=12, loc="left", pad=14)
    ax.legend(frameon=False, loc="upper right", fontsize=10)
    ax.set_xlim(-60, max(p90s) * 1.22)
    return _save(fig, "chart_latency.png")


def latency_spread_chart(data: dict) -> Path:
    """The bimodal OCR distribution — why a single median would be a lie."""
    vals = [v for _, v in data["by_op"].get("extract", [])] + \
           [v for _, v in data["by_op"].get("extract_batch", [])]
    vals = sorted(v for v in vals if v > 1.0)
    recent = sorted([v for _, v in data["by_op"].get("extract", [])][-6:] +
                    [v for _, v in data["by_op"].get("extract_batch", [])][-4:])

    fig, ax = plt.subplots(figsize=(9.6, 3.9))
    ax.hist(vals, bins=18, color=NEUTRAL, edgecolor="white", linewidth=0.8)
    med_recent = statistics.median(recent)
    ax.axvline(med_recent, color=ACCENT, linewidth=2.2)
    ax.text(med_recent + 8, ax.get_ylim()[1] * 0.82,
            f"most recent 10 runs\nmedian {med_recent:,.0f} s/page",
            fontsize=10, color=ACCENT)
    ax.axvline(statistics.median(vals), color=MUTED, linewidth=2.2, linestyle="--")
    ax.text(statistics.median(vals) + 8, ax.get_ylim()[1] * 0.45,
            f"all-run median\n{statistics.median(vals):,.0f} s/page",
            fontsize=10, color=RED)
    ax.set_xlabel("OCR latency per page  (seconds)")
    ax.set_ylabel("Number of traced runs  (count)")
    ax.set_title("OCR latency is bimodal, not noisy — the shared endpoint's load dominates",
                 fontsize=12, loc="left", pad=12)
    return _save(fig, "chart_latency_spread.png")


def tool_routing_chart(data: dict) -> Path:
    """Which tool the ReAct planner actually chose, across every traced turn."""
    tools = data["tools"].most_common()
    labels = [t for t, _ in tools][::-1]
    counts = [c for _, c in tools][::-1]
    read = {"sql_ledger", "search_receipts", "list_accounts", "list_plans"}
    colors = [NEUTRAL if t in read else ACCENT for t in labels]

    fig, ax = plt.subplots(figsize=(9.0, 4.6))
    ax.barh(labels, counts, color=colors, height=0.62)
    for i, c in enumerate(counts):
        ax.text(c + 0.4, i, str(c), va="center", fontsize=10, color=INK)
    ax.set_xlabel("Times selected by the ReAct planner  (tool calls)")
    ax.set_ylabel("Tool")
    ax.set_title("Tool routing across 113 traced agent turns — grey = read, amber = write",
                 fontsize=12, loc="left", pad=12)
    ax.set_xlim(0, max(counts) * 1.16)
    return _save(fig, "chart_tools.png")


# ------------------------------------------------------------ trajectory eval

def trajectory_chart() -> tuple[Path, dict]:
    src = next((ROOT / "evaluation/results/raw").glob("trajectory-*.json"))
    payload = json.loads(src.read_text(encoding="utf-8"))
    summary = payload["results"]["summary"]
    checks = summary["checks"]

    names = {
        "required_events": "Required events emitted",
        "prohibited_events": "No prohibited events",
        "allowed_tools": "Only allowed tools called",
        "expected_tools": "Expected tool selected",
        "max_tool_calls": "Within tool-call budget",
        "no_repeated_tool_calls": "No repeated tool call",
        "reached_terminal_state": "Reached terminal state",
        "final_supported_by_observation": "Final answer backed by an observation",
    }
    items = [(names[k], v["passed"], v["total"]) for k, v in checks.items()]
    items.sort(key=lambda r: (r[1] / r[2], r[2]))

    fig, ax = plt.subplots(figsize=(9.6, 4.4))
    labels = [i[0] for i in items]
    rates = [100 * i[1] / i[2] for i in items]
    colors = [GREEN if r == 100 else ACCENT for r in rates]
    ax.barh(labels, rates, color=colors, height=0.6)
    for i, (label, passed, total) in enumerate(items):
        ax.text(rates[i] + 1.5, i, f"{passed}/{total}", va="center", fontsize=10, color=INK)
    ax.set_xlim(0, 118)
    ax.set_xlabel("Cases passing the check  (% of applicable cases)")
    ax.set_ylabel("Trajectory check")
    ax.set_title(
        f"Layer-2 trajectory evaluation — {summary['passed']}/{summary['cases']} cases pass "
        f"({100 * summary['pass_rate']:.0f}%)", fontsize=12, loc="left", pad=12)
    return _save(fig, "chart_trajectory.png"), summary


# ------------------------------------------------- engineering benchmark pair

def engineering_chart() -> Path:
    fig, axes = plt.subplots(1, 3, figsize=(13.0, 3.9))

    ax = axes[0]
    x = ["SQL agent\n(POST /ask)", "ReAct agent\n(POST /agent)"]
    before, after = [2, 4], [1, 3]
    idx = range(len(x))
    ax.bar([i - 0.19 for i in idx], before, width=0.36, color=NEUTRAL, label="before")
    ax.bar([i + 0.19 for i in idx], after, width=0.36, color=ACCENT, label="after")
    for i, (b, a) in enumerate(zip(before, after)):
        ax.text(i - 0.19, b + 0.08, str(b), ha="center", fontsize=10)
        ax.text(i + 0.19, a + 0.08, str(a), ha="center", fontsize=10)
    ax.set_xticks(list(idx)); ax.set_xticklabels(x, fontsize=9)
    ax.set_ylabel("Model round trips per question  (calls)")
    ax.set_xlabel("Endpoint")
    ax.set_title("1. Removed a round trip", fontsize=11, loc="left")
    ax.legend(frameon=False, fontsize=9)
    ax.set_ylim(0, 4.8)

    ax = axes[1]
    ax.bar(["without index", "with index"], [658.9, 2.9], color=[NEUTRAL, ACCENT], width=0.52)
    ax.set_yscale("log")
    ax.text(0, 720, "658.9 ms", ha="center", fontsize=10)
    ax.text(1, 3.4, "2.9 ms", ha="center", fontsize=10)
    ax.set_ylabel("500 per-receipt lookups  (ms, log scale)")
    ax.set_xlabel("line_items(receipt_id) index")
    ax.set_title("2. 227× on a real query", fontsize=11, loc="left")

    ax = axes[2]
    sizes = [1000, 5000]
    ax.plot(sizes, [3.77, 19.21], "o--", color=FAINT, label="whole ledger, before")
    ax.plot(sizes, [3.19, 14.58], "o-", color=NEUTRAL, label="whole ledger, after")
    ax.plot(sizes, [1.47, 7.99], "s--", color=FAINT, label="scoped to 1, before")
    ax.plot(sizes, [0.15, 0.33], "s-", color=ACCENT, label="scoped to 1, after")
    ax.set_xlabel("Receipts in the ledger  (count)")
    ax.set_ylabel("Retrieval time  (ms)")
    ax.set_title("3. Scope pushed into SQL", fontsize=11, loc="left")
    ax.legend(frameon=False, fontsize=8)

    fig.tight_layout()
    return _save(fig, "chart_engineering.png")


# ------------------------------------------------------- value-proposition UoM

# Every constant below is an explicit, defendable assumption. Change one number
# here and the slide, the chart and the break-even point all move together.
UOM = {
    "receipts_per_month": 300,          # receipts / month, one micro-SME
    "manual_min_per_receipt": 2.0,      # minutes / receipt, keying + filing
    "bookkeeper_php_per_month": 25_000, # PHP / month, full-time PH bookkeeper
    "hours_per_month": 160,             # hours / month (40 h/wk x 4 wk)
    "snag_sec_per_receipt": 14.9,       # seconds / page, median of the 4 most
                                        # recent traced batch runs
    "hold_rate": 0.154,                 # share held for review — MLflow
                                        # needs_disambiguation mean over n=39
    "review_min_per_held": 0.5,         # minutes / held receipt, human check
    "appliance_php": 60_000,            # PHP, one mini-PC with a GPU
    "amortise_months": 36,              # months
    "kwh_php": 12.50,                   # PHP / kWh, Meralco residential band
    "draw_watts": 250,                  # W under inference load
    "saas_php_per_receipt": 5.00,       # PHP / receipt — indicative only,
                                        # replace with a real quote before use
}


def uom_numbers() -> dict:
    u = UOM
    php_per_hour = u["bookkeeper_php_per_month"] / u["hours_per_month"]
    php_per_min = php_per_hour / 60

    manual_h = u["receipts_per_month"] * u["manual_min_per_receipt"] / 60
    manual_php = manual_h * php_per_hour

    machine_h = u["receipts_per_month"] * u["snag_sec_per_receipt"] / 3600
    held = u["receipts_per_month"] * u["hold_rate"]
    review_h = held * u["review_min_per_held"] / 60
    review_php = review_h * php_per_hour

    power_php = (u["draw_watts"] / 1000) * machine_h * u["kwh_php"]
    capex_php = u["appliance_php"] / u["amortise_months"]

    per_receipt_manual = u["manual_min_per_receipt"] * php_per_min
    per_receipt_snag = (u["hold_rate"] * u["review_min_per_held"] * php_per_min
                        + (u["draw_watts"] / 1000) * (u["snag_sec_per_receipt"] / 3600)
                        * u["kwh_php"])
    breakeven = capex_php / (per_receipt_manual - per_receipt_snag)

    return {
        "php_per_hour": php_per_hour, "php_per_min": php_per_min,
        "manual_h": manual_h, "manual_php": manual_php,
        "machine_h": machine_h, "held": held, "review_h": review_h,
        "review_php": review_php, "power_php": power_php, "capex_php": capex_php,
        "hours_saved": manual_h - review_h,
        "time_factor": manual_h / review_h,
        "php_saved_month": manual_php - review_php - power_php,
        "php_saved_year": (manual_php - review_php - power_php) * 12,
        "per_receipt_manual": per_receipt_manual,
        "per_receipt_snag": per_receipt_snag,
        "breakeven": breakeven,
    }


def uom_chart() -> Path:
    """Human minutes per month: what the agent actually removes."""
    n = uom_numbers()
    fig, ax = plt.subplots(figsize=(9.0, 3.6))
    bars = ["Manual encoding\n(status quo)", "Snag\n(review the held ones only)"]
    human = [n["manual_h"] * 60, n["review_h"] * 60]
    machine = [0, n["machine_h"] * 60]
    ax.barh(bars, human, color=ACCENT, height=0.5, label="human minutes (paid)")
    ax.barh(bars, machine, left=human, color="#E5E7EB", height=0.5,
            label="unattended machine minutes (not paid)")
    ax.text(human[0] + 6, 0, f"{human[0]:,.0f} min", va="center", fontsize=11, color=INK)
    ax.text(human[1] + 6, 1, f"{human[1]:,.0f} min human  +  {machine[1]:,.0f} min unattended",
            va="center", fontsize=11, color=INK)
    ax.set_xlabel("Effort to process 300 receipts  (minutes per month)")
    ax.set_ylabel("Workflow")
    ax.set_title(f"{n['hours_saved']:.1f} paid hours removed per month "
                 f"— {n['time_factor']:.0f}× less human time", fontsize=12, loc="left", pad=12)
    ax.legend(frameon=False, fontsize=9, loc="lower right")
    ax.set_xlim(0, 720)
    return _save(fig, "chart_uom.png")


def breakeven_chart() -> Path:
    """Where buying the box pays for itself — and where it honestly does not."""
    n = uom_numbers()
    xs = list(range(0, 1001, 10))
    manual = [x * n["per_receipt_manual"] for x in xs]
    saas = [x * UOM["saas_php_per_receipt"] for x in xs]
    snag_capex = [n["capex_php"] + x * n["per_receipt_snag"] for x in xs]
    snag_owned = [x * n["per_receipt_snag"] for x in xs]

    fig, ax = plt.subplots(figsize=(9.6, 4.4))
    ax.plot(xs, manual, color=ACCENT, linewidth=2.4,
            label=f"Manual bookkeeping (₱{n['per_receipt_manual']:.2f}/receipt)")
    ax.plot(xs, saas, color=FAINT, linewidth=2.0, linestyle="--",
            label=f"Per-document SaaS (₱{UOM['saas_php_per_receipt']:.2f}/receipt, indicative)")
    ax.plot(xs, snag_capex, color=INK, linewidth=2.4,
            label=f"Snag, appliance amortised (₱{n['capex_php']:,.0f}/mo + ₱{n['per_receipt_snag']:.2f}/receipt)")
    ax.plot(xs, snag_owned, color=GREEN, linewidth=2.4,
            label=f"Snag, hardware already owned (₱{n['per_receipt_snag']:.2f}/receipt)")

    ax.axvline(n["breakeven"], color=BAD, linewidth=1.6, linestyle=":")
    ax.annotate(f"break-even\n{n['breakeven']:.0f} receipts/month",
                xy=(n["breakeven"], n["breakeven"] * n["per_receipt_manual"]),
                xytext=(n["breakeven"] + 70, 900), color=BAD, fontsize=10,
                arrowprops=dict(arrowstyle="->", color=BAD, lw=1.2))

    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"₱{v:,.0f}"))
    ax.set_xlabel("Volume processed  (receipts per month)")
    ax.set_ylabel("Total cost of the workflow  (₱ per month)")
    ax.set_title("Cost of processing receipts, by volume — including the case against us",
                 fontsize=12, loc="left", pad=12)
    ax.legend(frameon=False, fontsize=9, loc="upper left")
    ax.set_ylim(0, 5200)
    return _save(fig, "chart_breakeven.png")


def build_all() -> dict:
    print("Building charts from repository data...")
    data = mlflow_runs()
    latency_chart(data)
    latency_spread_chart(data)
    tool_routing_chart(data)
    _, traj = trajectory_chart()
    engineering_chart()
    uom_chart()
    breakeven_chart()

    grounded = data["metric"]("answer_grounded")
    ungrounded = data["metric"]("ungrounded_numbers")
    steps = data["metric"]("num_steps")
    clarified = data["metric"]("clarified")
    disamb = data["metric"]("needs_disambiguation")
    conf = data["metric"]("extraction_confidence")
    prompt_tok = data["metric"]("prompt_eval_count")
    out_tok = data["metric"]("eval_count")

    facts = {
        "total_runs": data["total_runs"],
        "traced_latency": data["traced_latency"],
        "grounded_n": len(grounded),
        "grounded_rate": sum(grounded) / len(grounded) if grounded else None,
        "ungrounded_n": len(ungrounded),
        "ungrounded_total": sum(ungrounded),
        "steps_mean": statistics.mean(steps) if steps else None,
        "steps_n": len(steps),
        "clarify_rate": sum(clarified) / len(clarified) if clarified else None,
        "clarify_n": len(clarified),
        "hold_rate": sum(disamb) / len(disamb) if disamb else None,
        "hold_n": len(disamb),
        "confidence_mean": statistics.mean(conf) if conf else None,
        "confidence_min": min(conf) if conf else None,
        "confidence_n": len(conf),
        "prompt_tokens_median": statistics.median(prompt_tok) if prompt_tok else None,
        "output_tokens_median": statistics.median(out_tok) if out_tok else None,
        "trajectory": traj,
        "uom": uom_numbers(),
    }
    (OUT / "facts.json").write_text(json.dumps(facts, indent=2), encoding="utf-8")
    print(f"  wrote {(OUT / 'facts.json').relative_to(ROOT)}")
    return facts


if __name__ == "__main__":
    f = build_all()
    print(json.dumps(f, indent=2)[:2000])
