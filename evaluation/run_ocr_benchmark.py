"""
run_ocr_benchmark.py — score the vision/OCR pipeline against a labelled receipt set.

Runs the SAME hot path the app uses (`core.extract_receipt_validated`), so what is
measured is the deployed pipeline — preprocessing, prompt, recovery pass, arithmetic
re-read, cleanup and schema validation included — not a bare model call.

    python -m evaluation.run_ocr_benchmark \
        --images "C:/path/to/receipts" \
        --truth evaluation/datasets/receipts_gt_10.json \
        --out evaluation/results/raw/ocr-qwen.json

Metric definition
-----------------
Every label is one prediction slot. A slot is scored against the printed receipt:

    TP  the field IS printed and the model returned the right value
    FP  the model returned a value that is wrong, or returned a value for a field
        that is NOT printed on the receipt (an invention)
    FN  the field IS printed and the model returned null, or returned a wrong value
    TN  the field is not printed and the model correctly returned null

A wrong value is charged as BOTH an FP and an FN: the model emitted something it
should not have (precision) and it failed to capture what was there (recall). This
is the standard treatment for a value-extraction task and it is what stops a model
from buying recall by guessing.

    accuracy  = (TP + TN) / (TP + TN + FP + FN)   -- over all slots, absence included
    precision = TP / (TP + FP)                    -- of what it asserted, how much held
    recall    = TP / (TP + FN)                    -- of what was printed, how much it got
    F1        = harmonic mean of the two

Line items are scored as their own population: each labelled item is one slot,
matched greedily to an extracted row on amount first, then description similarity.
An unmatched labelled item is an FN (missed line); an unmatched extracted row is an
FP (invented or duplicated line). Items have no TN — an absent line has no slot.

Headline numbers are reported three ways (scalar fields, line items, and the two
pooled) because they fail differently: a model can read every total on the page and
still lose half the item block.
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
import time
import traceback
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# The scalar fields scored. Deliberately the extraction schema's *transcribed*
# fields only: computed/provenance fields (items_coverage, image_sha256, category)
# are not read off the paper, so they have no ground truth to be right or wrong
# against and scoring them would flatter or punish the model for our own code.
SCALAR_FIELDS = (
    "vendor_name", "vendor_tin", "receipt_date", "receipt_number",
    "subtotal", "vatable_sales", "vat_exempt_sales", "zero_rated_sales",
    "vat_amount", "discount", "total_amount", "cash", "change", "currency",
)
MONEY_FIELDS = {
    "subtotal", "vatable_sales", "vat_exempt_sales", "zero_rated_sales",
    "vat_amount", "discount", "total_amount", "cash", "change",
}
# Money is compared to the cent. Anything looser would score a misread digit as a
# hit; anything tighter would trip over float representation.
MONEY_TOLERANCE = 0.005


# --------------------------------------------------------------------------- #
# Comparison
# --------------------------------------------------------------------------- #
def _label_parts(label):
    """Split a ground-truth entry into (canonical value, accepted values).

    A label is either a bare value or {"value": ..., "accept": [...]} for the
    figures where more than one reading is defensible (a merchant printed under
    both a brand and a corporate name, a receipt that prints three different
    identifiers, a misprinted digit)."""
    if isinstance(label, dict) and "value" in label:
        accepted = label.get("accept") or [label["value"]]
        return label["value"], list(accepted)
    return label, [label]


def _norm_text(value) -> str:
    """Case/punctuation-insensitive form used to compare text fields.

    Receipts print the same merchant as "McDonald's", "MCDONALDS" and
    "McDonald`s"; a difference that survives only in punctuation is not an OCR
    error worth charging for."""
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def _text_matches(got, accepted) -> bool:
    """True when the answer names the same thing as any accepted label.

    Containment either way, not equality: a model that answers with the full
    registered name where the label is the brand (or the reverse) has read the
    receipt correctly, and both strings are printed on it."""
    g = _norm_text(got)
    if not g:
        return False
    for candidate in accepted:
        c = _norm_text(candidate)
        if not c:
            continue
        if g == c or g in c or c in g:
            return True
    return False


def _to_float(value):
    """Parse a money value that may arrive as a string with symbols/commas/sign."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = re.sub(r"[^0-9.\-]", "", str(value))
    if cleaned in ("", "-", ".", "-."):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _money_matches(got, accepted) -> bool:
    """True within a cent of any accepted label. Compared on magnitude: a
    receipt that prints tendered cash as "-1,000.00" is not disagreeing with a
    model that answers 1000.00."""
    g = _to_float(got)
    if g is None:
        return False
    for candidate in accepted:
        c = _to_float(candidate)
        if c is not None and abs(abs(g) - abs(c)) <= MONEY_TOLERANCE:
            return True
    return False


def _date_matches(got, accepted) -> bool:
    """Dates are compared on their digits in ISO order, so a model that answers
    2015-12-02 matches a label of 2015-12-02 regardless of separator."""
    g = re.sub(r"[^0-9]", "", str(got or ""))
    return any(g == re.sub(r"[^0-9]", "", str(c or "")) for c in accepted if c is not None)


def _field_matches(field: str, got, accepted) -> bool:
    if field in MONEY_FIELDS:
        return _money_matches(got, accepted)
    if field == "receipt_date":
        return _date_matches(got, accepted)
    if field in ("vendor_tin", "receipt_number"):
        # Identifiers: compare digits/letters only, so a dash or a leading-zero
        # run printed differently isn't scored as a misread.
        g = _norm_text(got)
        return bool(g) and any(g == _norm_text(c) or g in _norm_text(c) or _norm_text(c) in g
                               for c in accepted if c is not None)
    return _text_matches(got, accepted)


def _is_blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def score_scalars(truth_fields: dict, got: dict) -> dict:
    """Confusion counts + a per-field verdict list for one receipt's scalars."""
    counts = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    detail = []
    for field in SCALAR_FIELDS:
        label = truth_fields.get(field, None)
        canonical, accepted = _label_parts(label)
        answer = got.get(field)
        printed = canonical is not None
        answered = not _is_blank(answer)

        if printed and answered and _field_matches(field, answer, accepted):
            verdict, counts["tp"] = "TP", counts["tp"] + 1
        elif printed and not answered:
            verdict, counts["fn"] = "FN", counts["fn"] + 1
        elif printed and answered:                      # answered, but wrong
            verdict = "FP+FN"
            counts["fp"] += 1
            counts["fn"] += 1
        elif not printed and answered:                  # invented a value
            verdict, counts["fp"] = "FP", counts["fp"] + 1
        else:
            verdict, counts["tn"] = "TN", counts["tn"] + 1

        detail.append({"field": field, "verdict": verdict,
                       "expected": canonical, "got": answer})
    return {"counts": counts, "detail": detail}


def _similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, _norm_text(a), _norm_text(b)).ratio()


def score_items(truth_items: list, got_items: list) -> dict:
    """Greedy one-to-one match of labelled lines to extracted rows.

    Amount first, because the amount is the field that actually costs money if it
    is wrong and it is the one a receipt prints unambiguously; description
    similarity only breaks ties among rows carrying the same amount (r8 prints
    six lines at 98.00). A row must clear both the amount and a description
    floor to count as a hit, so a right price attached to the wrong product is
    not scored as a correct line."""
    unmatched_got = list(range(len(got_items)))
    counts = {"tp": 0, "fp": 0, "fn": 0}
    detail = []

    for want in truth_items:
        best_idx, best_sim = None, -1.0
        for idx in unmatched_got:
            row = got_items[idx]
            if not _money_matches(row.get("amount"), [want["amount"]]):
                continue
            sim = _similar(want["description"], row.get("description") or "")
            if sim > best_sim:
                best_idx, best_sim = idx, sim
        # 0.55: tolerant of the abbreviation noise receipts print
        # ("NissinEggnogReg130"), strict enough to reject a different product.
        if best_idx is not None and best_sim >= 0.55:
            unmatched_got.remove(best_idx)
            counts["tp"] += 1
            detail.append({"verdict": "TP", "expected": want,
                           "got": got_items[best_idx], "similarity": round(best_sim, 2)})
        else:
            counts["fn"] += 1
            detail.append({"verdict": "FN", "expected": want, "got": None,
                           "similarity": round(best_sim, 2) if best_sim >= 0 else None})

    for idx in unmatched_got:
        counts["fp"] += 1
        detail.append({"verdict": "FP", "expected": None, "got": got_items[idx]})

    return {"counts": counts, "detail": detail}


def metrics(counts: dict) -> dict:
    tp, fp, fn, tn = (counts.get(k, 0) for k in ("tp", "fp", "fn", "tn"))
    total = tp + fp + fn + tn
    precision = tp / (tp + fp) if (tp + fp) else None
    recall = tp / (tp + fn) if (tp + fn) else None
    f1 = (2 * precision * recall / (precision + recall)
          if precision and recall else (0.0 if precision is not None and recall is not None else None))
    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "accuracy": (tp + tn) / total if total else None,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def _add(into: dict, counts: dict) -> dict:
    for key, value in counts.items():
        into[key] = into.get(key, 0) + value
    return into


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--images", required=True, help="directory holding the receipt images")
    parser.add_argument("--truth", default=str(_REPO_ROOT / "evaluation/datasets/receipts_gt_10.json"))
    parser.add_argument("--out", default=None, help="where to write the full JSON result")
    parser.add_argument("--model", default=None, help="override VISION_MODEL for this run")
    parser.add_argument("--only", default=None, help="comma-separated receipt ids to run")
    args = parser.parse_args()

    if args.model:
        os.environ["VISION_MODEL"] = args.model

    import core  # imported after VISION_MODEL is set, so the run is what was asked for
    import extraction

    model = args.model or extraction.DEFAULT_MODEL
    truth = json.loads(Path(args.truth).read_text(encoding="utf-8"))
    wanted = set(args.only.split(",")) if args.only else None
    images_dir = Path(args.images)

    per_receipt, scalar_totals, item_totals = [], {}, {}
    started = time.time()

    for case in truth["receipts"]:
        if wanted and case["id"] not in wanted:
            continue
        path = images_dir / case["file"]
        print(f"[{case['id']}] {path.name} ... ", end="", flush=True)
        t0 = time.time()
        try:
            data, reasons, confidence, _audit = core.extract_receipt_validated(
                path.read_bytes(), model=model, content_type="image/jpeg"
            )
            got = data.model_dump()
            error = None
        except Exception as exc:  # noqa: BLE001 - a failed read is a result, not a crash
            traceback.print_exc()
            got, reasons, confidence, error = {}, [], {}, f"{type(exc).__name__}: {exc}"

        elapsed = time.time() - t0
        scalars = score_scalars(case["fields"], got)
        # A receipt that failed to extract still owes every labelled line: they
        # are all misses, not absences, or a crash would score better than a bad read.
        items = score_items(case["items"], got.get("items") or [])
        _add(scalar_totals, scalars["counts"])
        _add(item_totals, items["counts"])

        sm, im = metrics(scalars["counts"]), metrics(items["counts"])
        print(f"{elapsed:6.1f}s  fields P={_pct(sm['precision'])} R={_pct(sm['recall'])} "
              f"| items {items['counts']['tp']}/{len(case['items'])}"
              + (f"  ERROR {error}" if error else ""))

        per_receipt.append({
            "id": case["id"], "file": case["file"], "elapsed_s": round(elapsed, 2),
            "error": error,
            "disambiguation_reasons": reasons,
            "confidence_overall": (confidence or {}).get("overall"),
            "scalars": {"metrics": sm, "detail": scalars["detail"]},
            "items": {"metrics": im, "detail": items["detail"],
                      "labelled": len(case["items"]),
                      "extracted": len(got.get("items") or [])},
        })

    combined = _add(dict(scalar_totals), item_totals)
    result = {
        "model": model,
        "ollama_host": os.getenv("OLLAMA_HOST"),
        "dataset": str(Path(args.truth).name),
        "receipts": len(per_receipt),
        "wall_clock_s": round(time.time() - started, 1),
        "overall": {
            "scalar_fields": metrics(scalar_totals),
            "line_items": metrics(item_totals),
            "combined": metrics(combined),
        },
        "per_receipt": per_receipt,
    }

    print()
    for name in ("scalar_fields", "line_items", "combined"):
        m = result["overall"][name]
        print(f"{name:>14}: acc={_pct(m['accuracy'])} prec={_pct(m['precision'])} "
              f"rec={_pct(m['recall'])} f1={_pct(m['f1'])}   "
              f"(TP={m['tp']} FP={m['fp']} FN={m['fn']} TN={m['tn']})")

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
        print(f"\nwrote {out}")
    return 0


def _pct(value) -> str:
    return "  n/a" if value is None else f"{value * 100:5.1f}%"


if __name__ == "__main__":
    raise SystemExit(main())
