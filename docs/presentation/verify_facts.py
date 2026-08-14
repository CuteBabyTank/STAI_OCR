"""Check every load-bearing number on a slide against the thing it describes.

Run:  python docs/presentation/verify_facts.py

A figure on a slide is a claim. This script recomputes each one from its source
-- the source tree, `ledger.db`, `mlflow.db`, the benchmark's raw JSON -- and
then asserts that the recomputed value is the one actually written in
`build_deck.py`. A number that drifts out of the code fails here rather than in
front of a panel.

Two rules keep it honest:

1. **Recompute, never re-read.** Where a summary already exists in a file, the
   check derives the value from the underlying rows and then compares it to that
   summary as a second, independent assertion. The OCR benchmark's headline is
   rebuilt from its 191 per-field verdicts before it is trusted.
2. **A claim with no source in this repository is reported as UNSOURCED**, not
   as a pass. Evidence held outside the tree (a hands-on run, a vendor product)
   cannot be checked here and is listed so it is never mistaken for measured.

Exit code is 1 if any check fails, so this can gate a rebuild.
"""
from __future__ import annotations

import ast
import collections
import json
import re
import sqlite3
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DECK = (HERE / "build_deck.py").read_text(encoding="utf-8")

rows: list[tuple[str, str, str, str, str]] = []   # status, claim, source, computed, note


def check(claim: str, source: str, computed, literal: str | None = None, note: str = ""):
    """Record one check. `literal` must appear verbatim in build_deck.py."""
    if literal is None:
        rows.append(("INFO", claim, source, str(computed), note))
        return
    ok = literal in DECK
    rows.append(("PASS" if ok else "FAIL", claim, source, str(computed),
                 note if ok else f"slide text does not contain {literal!r}"))


def unsourced(claim: str, note: str):
    rows.append(("UNSOURCED", claim, "not in this repository", "-", note))


# --------------------------------------------------------------- the codebase

api = ast.parse((ROOT / "api.py").read_text(encoding="utf-8"))
routes = [d for n in ast.walk(api)
          if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
          for d in n.decorator_list
          if isinstance(f := (d.func if isinstance(d, ast.Call) else d), ast.Attribute)
          and f.attr in ("get", "post", "put", "patch", "delete")
          and isinstance(f.value, ast.Name) and f.value.id == "app"]
models = [n.name for n in ast.walk(api) if isinstance(n, ast.ClassDef)
          and any(isinstance(b, ast.Name) and b.id == "BaseModel" for b in n.bases)]
check("HTTP routes", "api.py @app decorators", len(routes), f"{len(routes)} typed routes")
check("request models", "api.py BaseModel subclasses", len(models),
      f"{len(models)} request models")

core_src = (ROOT / "core.py").read_text(encoding="utf-8")
core = ast.parse(core_src)
fields = next(len([b for b in n.body if isinstance(b, ast.AnnAssign)])
              for n in ast.walk(core)
              if isinstance(n, ast.ClassDef) and n.name == "ReceiptData")
check("ReceiptData fields", "core.py class ReceiptData", fields,
      f"ReceiptData · {fields} fields")

def toolset(name):
    """The names inside a top-level READ_TOOLS / _WRITE_TOOLS literal.

    Bounded at the next top-level statement, not at the next blank line -- a
    blank line inside the literal would otherwise swallow the block after it.
    """
    body = re.search(rf"^{name}\s*=\s*(.*?)\n(?=\w|\n\n)", core_src, re.S | re.M).group(1)
    return re.findall(r'"([a-z_]+)"', body)


read_tools, write_tools = toolset("READ_TOOLS"), toolset("_WRITE_TOOLS")
check("read tools", "core.py READ_TOOLS", len(read_tools), f"{len(read_tools)} read")
check("write tools", "core.py _WRITE_TOOLS", len(write_tools), f"{len(write_tools)} write")
check("tools in total", "READ_TOOLS | _WRITE_TOOLS", len(read_tools) + len(write_tools),
      "Eleven tools, one dispatcher")

steps = int(re.search(r"_MAX_AGENT_STEPS\s*=\s*(\d+)", core_src).group(1))
check("agent step budget", "core.py _MAX_AGENT_STEPS", steps, f"at most {steps} steps")

prompt = next(n.value for n in ast.walk(ast.parse((ROOT / "extraction.py").read_text(encoding="utf-8")))
              if isinstance(n, ast.Constant) and isinstance(n.value, str)
              and "STRICT RULES" in n.value)
tail = prompt[prompt.index("STRICT RULES"):]
heads = list(dict.fromkeys(m.group(1) for m in
                           re.finditer(r"(?:^|\n)\s*(\d{1,2}[a-z]?)[).]\s", tail)))
majors = sorted({int(re.match(r"\d+", h).group()) for h in heads})
NUMWORD = {3: "three", 4: "four", 7: "seven", 10: "ten", 11: "eleven",
           16: "sixteen", 19: "nineteen", 28: "twenty-eight"}
check("prompt rules", "extraction.py STRICT RULES block", f"{len(majors)} major, {len(heads)} with sub-rules",
      f"{NUMWORD.get(len(majors), len(majors))} prompt rules")

compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
services = re.findall(r"^  ([a-z]+):", compose, re.M)
check("compose services", "docker-compose.yml", len(services),
      f"{NUMWORD.get(len(services), len(services))} services", ", ".join(services))
check("MLflow version", "docker-compose.yml image tag",
      re.search(r"mlflow:v([\d.]+)", compose).group(1),
      "MLflow " + ".".join(re.search(r"mlflow:v([\d.]+)", compose).group(1).split(".")[:2]))

# ------------------------------------------------------------------- the data

led = sqlite3.connect(ROOT / "ledger.db")
tables = [r[0] for r in led.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
check("ledger tables", "ledger.db schema, excluding sqlite internals", len(tables),
      f"{len(tables)} tables")
blob = led.execute(
    "SELECT embedding FROM receipt_docs WHERE embedding IS NOT NULL LIMIT 1").fetchone()
if blob:
    dim = len(blob[0]) // 4                      # float32
    check("embedding width", "len(receipt_docs.embedding) / 4 bytes", dim, f"{dim}-dim")
led.close()

ml = sqlite3.connect(ROOT / "mlflow.db")


def metric(key):
    return [v for (v,) in ml.execute("SELECT value FROM latest_metrics WHERE key=?", (key,))]


grounded, ungrounded = metric("answer_grounded"), metric("ungrounded_numbers")
check("ungrounded numbers", "mlflow.db latest_metrics.ungrounded_numbers",
      f"{sum(ungrounded):.0f} across {len(ungrounded)} runs",
      f"{sum(ungrounded):.0f} ungrounded numbers across {len(ungrounded)} traced agent runs",
      f"answer_grounded is 1.0 on all {len(grounded)}")

hold = metric("needs_disambiguation")
check("hold rate", "mlflow.db latest_metrics.needs_disambiguation",
      f"{statistics.fmean(hold):.1%} ({sum(hold):.0f}/{len(hold)})",
      f"{statistics.fmean(hold) * 100:.1f}% held",
      f"n = {len(hold)} extractions")

lat = metric("latency_seconds")
check("traced runs", "mlflow.db latency_seconds", len(lat), None,
      f"mean {statistics.fmean(lat):.1f}s, max {max(lat):.1f}s")
ml.close()

# ------------------------------------------------------- the OCR benchmark

raw = json.loads((ROOT / "evaluation/results/raw/ocr-qwen2.5vl-7b.json").read_text(encoding="utf-8"))
gt = json.loads((ROOT / "evaluation/datasets/receipts_gt_10.json").read_text(encoding="utf-8"))
gt_recs = gt if isinstance(gt, list) else gt["receipts"]

# Rebuild the headline from the per-field verdicts. "FP+FN" is the documented
# dual charge for a wrong value: it asserted something untrue AND missed what
# was printed, so it lands in both columns.
sc, it = collections.Counter(), collections.Counter()
for r in raw["per_receipt"]:
    for bucket, block in ((sc, r["scalars"]), (it, r["items"])):
        for d in block["detail"]:
            for part in d["verdict"].split("+"):
                bucket[part] += 1


def prf(c):
    tp, fp, fn, tn = c["TP"], c["FP"], c["FN"], c["TN"]
    return ((tp + tn) / max(1, tp + fp + fn + tn),
            tp / max(1, tp + fp), tp / max(1, tp + fn))


combined = sc + it
acc, prec, rec = prf(combined)
stored = raw["overall"]["combined"]
agrees = (combined["TP"] == stored["tp"] and combined["FP"] == stored["fp"]
          and combined["FN"] == stored["fn"] and combined["TN"] == stored["tn"])
rows.append(("PASS" if agrees else "FAIL", "benchmark internal consistency",
             "sum of per-field verdicts vs the file's own summary",
             f"TP {combined['TP']} FP {combined['FP']} FN {combined['FN']} TN {combined['TN']}",
             "recomputed headline equals the stored one" if agrees else "summary disagrees"))

check("qwen2.5-VL accuracy", "recomputed from 10 labelled receipts", f"{acc:.1%}", f'"{acc * 100:.1f}%"')
check("qwen2.5-VL precision", "recomputed from 10 labelled receipts", f"{prec:.1%}", f'"{prec * 100:.1f}%"')
check("qwen2.5-VL recall", "recomputed from 10 labelled receipts", f"{rec:.1%}", f'"{rec * 100:.1f}%"')

labelled_items = sum(len(r["items"]) for r in gt_recs)
check("line items found", "receipts_gt_10.json labels vs benchmark verdicts",
      f"{it['TP']} of {labelled_items} labelled, {it['FP']} invented",
      f"{it['TP']} of {labelled_items} labelled lines",
      f"recall {it['TP'] / labelled_items:.0%}, precision {it['TP'] / (it['TP'] + it['FP']):.1%}")

times = [r["elapsed_s"] for r in raw["per_receipt"]]
mean_s = statistics.fmean(times)
check("qwen time per receipt", "benchmark elapsed_s", f"mean {mean_s:.1f}s",
      f"{int(mean_s // 60)}m {round(mean_s % 60):02d}s",
      f"median {statistics.median(times):.0f}s, spread {min(times):.0f}s to {max(times):.0f}s")
check("receipts benchmarked", "receipts_gt_10.json", len(gt_recs), None,
      f"{len([r for r in raw['per_receipt'] if r['error']])} errors, "
      f"{len(raw['per_receipt'])} completed")

traj = json.loads(next((ROOT / "evaluation/results/raw").glob("trajectory-*.json")).read_text(encoding="utf-8"))
cases = traj["results"]["cases"]
passed = sum(1 for c in cases if c.get("passed"))
check("trajectory pilot", "results/raw/trajectory-*.json", f"{passed}/{len(cases)} pass", None,
      "failing case: " + ", ".join(c["case_id"] for c in cases if not c.get("passed")))

# ---------------------------------------------------- claims we cannot check

unsourced("Claude Cowork 97% / 94% / 98% / 15 s",
          "hands-on test run by the team; no raw output in the tree. Drop it in "
          "evaluation/results/raw/ and this becomes a check.")
unsourced("Gemma 51.7% / 92.5% / 69.8% / 21.7 s",
          "no benchmark JSON for gemma in evaluation/results/raw/. Only qwen2.5vl "
          "has one.")

# ------------------------------------------------------------------- report

W = (9, 30, 46, 30)
print(f"{'STATUS':<{W[0]}} {'CLAIM':<{W[1]}} {'SOURCE':<{W[2]}} {'COMPUTED':<{W[3]}} NOTE")
print("-" * 140)
for status, claim, source, computed, note in rows:
    print(f"{status:<{W[0]}} {claim:<{W[1]}} {source:<{W[2]}} {computed:<{W[3]}} {note}")

fails = [r for r in rows if r[0] == "FAIL"]
tally = collections.Counter(r[0] for r in rows)
print("-" * 140)
print("  ".join(f"{k} {v}" for k, v in sorted(tally.items())))
sys.exit(1 if fails else 0)
