#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Re-price delivered history under a candidate model and score it against actuals.

This is the trust mechanism. "This change would have improved seven of your last nine
estimates" is what makes someone accept a coefficient change; a number with no such
evidence is just a different guess.

It re-prices by calling est-estimate's own engine over an inventory reconstructed from
each ledger entry's stored features. It deliberately does not reimplement pricing: in
skill #2, a second implementation of one quantity made every reported figure the gap
between two formulas rather than the thing it claimed to measure.
"""

import argparse
import importlib.util
import json
import math
import statistics
import sys
from pathlib import Path

# Correct while both skills sit under one parent, which is the normal install. --engine
# recovers any other layout without editing this file.
DEFAULT_ENGINE = Path(__file__).resolve().parent.parent.parent / "est-estimate" / "scripts" / "estimate.py"


def engine(path=None):
    """Load est-estimate's pricing engine, or say plainly why history cannot be re-priced."""
    ENGINE = Path(path) if path else DEFAULT_ENGINE
    if not ENGINE.exists():
        raise SystemExit(json.dumps({
            "ok": False,
            "error": (f"est-estimate's engine is not at {ENGINE}. Backtesting re-prices history "
                      f"with that engine rather than reimplementing it, so without it a proposal "
                      f"can be shown but never evidenced. Look for estimate.py under the project's "
                      f"skills directory and pass it with --engine; if est-estimate is genuinely "
                      f"not installed, report accuracy only and propose nothing."),
        }, indent=2))
    spec = importlib.util.spec_from_file_location("estimate", ENGINE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def inventory_from(entry):
    """Reconstruct the priced scope from a ledger entry.

    Ledger entries store the estimate, not the inventory, but every priced feature keeps
    its tags, their reasons and its citations — which is exactly what pricing consumes.
    """
    features = []
    for f in entry.get("features", []):
        tags = {}
        for axis, value in (f.get("tags") or {}).items():
            tags[axis] = {"value": value,
                          "why": (f.get("tag_why") or {}).get(axis) or "from ledger entry",
                          "status": (f.get("tag_status") or {}).get(axis) or "inferred"}
        features.append({
            "id": f["id"], "name": f.get("name", f["id"]),
            "description": f.get("name", ""),
            "citations": f.get("citations") or [{"source_id": "S1", "location": "ledger",
                                                 "quote": "recorded estimate"}],
            "commitment": f.get("commitment", "committed"),
            "scope_status": f.get("scope_status"),
            "tags": tags,
            "depends_on": [{"feature_id": d, "inferred": True} for d in (f.get("depends_on") or [])],
            "open_questions": f.get("open_questions", []),
        })
    return {
        "schema_version": "1.0", "generated": entry.get("generated"),
        "project": entry.get("project"), "granularity": entry.get("granularity", "project"),
        "working_language": "en",
        "sources": [{"id": "S1", "path": "ledger", "doc_type": "sow", "language": "en"}],
        "features": features, "not_scope": [], "conflicts": [], "assumptions": [],
        "completeness_signals": {},
    }


def reprice(entry, model, est):
    """Price this entry's scope under `model`, holding every other input as recorded."""
    inputs = entry.get("inputs") or {}
    profile = inputs.get("team_profile", "balanced")
    options = {
        "mode": "presale",
        "team": model["team_profiles"].get(profile, model["team_profiles"]["balanced"]),
        "team_name": profile,
        "stack": inputs.get("stack", "standard_saas"),
        "qa_platform": inputs.get("qa_platform", "web"),
        "engagement": inputs.get("engagement", "standard"),
        "team_size": inputs.get("team_size"),
        "granularity": entry.get("granularity", "project"),
        "input_completeness": (entry.get("confidence") or {}).get("input_completeness", 0.6),
        "inventory_path": "ledger", "generated": entry.get("generated", ""),
    }
    return est.build_estimate(inventory_from(entry), model, options)


def apply_proposal(model, proposal):
    """A candidate model with one proposal applied. Never mutates the model passed in."""
    candidate = json.loads(json.dumps(model))
    target, kind, value = proposal["coefficient"], proposal.get("kind", "factor"), proposal["proposed"]

    if kind == "absolute":
        node, *rest = target.split(".")
        ref = candidate[node]
        for part in rest[:-1]:
            ref = ref[part]
        ref[rest[-1]] = value
        return candidate

    family = target.replace(".*", "")
    node = candidate
    for part in family.split("."):
        node = node[part]
    for key, entry in node.items():
        if key.startswith("_") or not isinstance(entry, dict):
            continue
        for bound in ("lo", "likely", "hi"):
            if bound in entry:
                entry[bound] = round(entry[bound] * value, 4)
    return candidate


def score(entries, model, est):
    """How well this model would have predicted what actually happened."""
    errors, hits = [], 0
    per_entry = []
    for entry in entries:
        actual = entry["ledger"]["actuals"]["delivery_hours"]
        priced = reprice(entry, model, est)
        total = priced["total_hours"]
        error = abs(actual - total["likely"]) / actual * 100 if actual else 0.0
        inside = total["low"] <= actual <= total["high"]
        hits += 1 if inside else 0
        errors.append(error)
        per_entry.append({"id": entry["ledger"]["id"], "actual": actual,
                          "likely": total["likely"], "abs_error_pct": round(error, 1),
                          "inside_band": inside})
    return {
        "samples": len(entries),
        "median_abs_error_pct": round(statistics.median(errors), 1) if errors else None,
        "band_hit_rate": round(hits / len(entries), 3) if entries else None,
        "entries": per_entry,
    }


def compare(entries, model, proposal, est):
    model_z = (model.get("uncertainty") or {}).get("z", 1.0) if isinstance(model, dict) else 1.0
    """Before and after, per entry, so 'improved 7 of 9' is a count and not a claim."""
    before = score(entries, model, est)
    after = score(entries, apply_proposal(model, proposal), est)
    improved = sum(1 for b, a in zip(before["entries"], after["entries"])
                   if a["abs_error_pct"] < b["abs_error_pct"] - 0.05)
    worsened = sum(1 for b, a in zip(before["entries"], after["entries"])
                   if a["abs_error_pct"] > b["abs_error_pct"] + 0.05)
    # Judge band movement too, not just central error. A change to band width leaves every
    # central figure untouched, so an error-only verdict reports "no measurable effect" on a
    # change that would have taken the hit rate from 71% to 14% — and someone skimming
    # verdicts would accept it. The band is what this module leads with; it gets a vote.
    # Judged asymmetrically, because the two directions are not equally bad. A band that is
    # too NARROW promises precision the model does not have, which is the failure that costs
    # someone a fixed-price deal. A band that is too wide is merely uninformative, and
    # overshooting the target while central error falls is a good change with a side effect —
    # one the band-width proposal then corrects on debiased residuals.
    # Derived from the model's own z, not assumed: a company that widened its ranges to an
    # 80% band would otherwise have every correctly calibrated estimate judged too wide.
    target = round(math.erf(model_z / math.sqrt(2)), 3)
    under_before = max(0.0, target - (before["band_hit_rate"] or 0))
    under_after = max(0.0, target - (after["band_hit_rate"] or 0))
    band_moved = round((after["band_hit_rate"] or 0) - (before["band_hit_rate"] or 0), 3)
    band_better = under_after < under_before - 0.02
    band_worse = under_after > under_before + 0.02
    overshoot = (after["band_hit_rate"] or 0) - target > 0.15

    if worsened > improved or band_worse:
        verdict = "makes past estimates worse"
    elif improved > worsened or band_better:
        verdict = "improves past estimates"
    else:
        verdict = "no measurable effect on past estimates"

    detail = []
    if improved or worsened:
        detail.append(f"central estimate improved on {improved} of {before['samples']}")
    if band_worse:
        detail.append(f"band hit rate fell below the {target:.0%} target "
                      f"({before['band_hit_rate']:.0%} → {after['band_hit_rate']:.0%}), so the "
                      f"range would promise precision the model does not have")
    elif band_better:
        detail.append(f"band coverage improved toward the {target:.0%} target "
                      f"({before['band_hit_rate']:.0%} → {after['band_hit_rate']:.0%})")
    elif overshoot:
        detail.append(f"band hit rate rises to {after['band_hit_rate']:.0%} against a "
                      f"{target:.0%} target — not harmful, but the range is now wider than it "
                      f"needs to be and the band-width proposal is what tightens it")

    return {
        "proposal": proposal["id"],
        "coefficient": proposal["coefficient"],
        "before": {k: before[k] for k in ("median_abs_error_pct", "band_hit_rate")},
        "after": {k: after[k] for k in ("median_abs_error_pct", "band_hit_rate")},
        "improved": improved,
        "worsened": worsened,
        "unchanged": before["samples"] - improved - worsened,
        "band_hit_change": band_moved,
        "samples": before["samples"],
        "verdict": verdict,
        "detail": "; ".join(detail) or "no movement in either measure",
    }


def main():
    ap = argparse.ArgumentParser(
        description="Re-price delivered history under proposed coefficient changes.",
        epilog="Exit codes: 0 backtest produced, 2 unreadable input or engine missing.",
    )
    ap.add_argument("--analysis", required=True, help="analysis JSON from analyze.py")
    ap.add_argument("--ledger", required=True, help="ledger directory")
    ap.add_argument("--cost-model", required=True, help="current cost-model.json")
    ap.add_argument("-o", "--output", help="write the backtest JSON here instead of stdout")
    ap.add_argument("--engine", help="path to est-estimate's estimate.py, when it is not installed "
                                     "alongside this skill")
    args = ap.parse_args()

    est = engine(args.engine)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    analyze = importlib.util.module_from_spec(
        importlib.util.spec_from_file_location("analyze", Path(__file__).resolve().parent / "analyze.py"))
    analyze.__spec__.loader.exec_module(analyze)

    try:
        analysis = json.loads(Path(args.analysis).read_text(encoding="utf-8"))
        model = json.loads(Path(args.cost_model).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 2

    entries = [e for e in analyze.load_ledger(args.ledger) if analyze.usable(e)[0]]
    results = [compare(entries, model, p, est) for p in analysis.get("proposals", [])]

    out = {"ok": True, "samples": len(entries), "backtests": results}
    text = json.dumps(out, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
        print(json.dumps({"ok": True, "backtest": args.output, "proposals": len(results)}, indent=2))
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
