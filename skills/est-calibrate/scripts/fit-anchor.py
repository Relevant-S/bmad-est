#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Attribute one delivered project's estimate error to the coefficients that caused it.

`analyze.py` can propose seven coefficient paths and shrinks every one of them toward the
current value by n/(n+6) — sensible over a portfolio, useless on the first project, where it
moves 14% of the way and calls the rest converged. Worse, of the seven paths only a uniform
`size_bands.*` scale is reachable from a project total, so the entire error lands on the one
family whatever actually caused it. That is how a model ends up with a review rate of 0.016:
numerically right, and meaningless on its own.

This does the opposite. It reads the per-role and per-phase actuals the ledger already holds —
which `analyze.py` counts for a readiness display and never reads again — and reports which
coefficient families the evidence can separate and which it cannot, then emits the `curate.py`
commands for the ones it can. It proposes nothing it cannot attribute.

    uv run scripts/fit-anchor.py --entry {memory}/ledger/<id>.json \
        --cost-model {memory}/cost-model.json

Exit 0 with an attribution, 1 when the entry carries no usable actuals, 2 on unreadable input.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backtest  # sibling: the engine loader, so pricing has exactly one definition

# A role that maps to exactly one component maps that component's coefficient family, with no
# algebra in between. Everything else is a mixture and is reported as one.
DIRECT = {"qa": ("qa", "qa.<platform>")}


def ratios(predicted, actual):
    out = {}
    for key in sorted(set(predicted) | set(actual)):
        p, a = predicted.get(key, 0.0), actual.get(key, 0.0)
        out[key] = {
            "predicted": round(p, 1),
            "actual": round(a, 1),
            "ratio": round(p / a, 2) if a else None,
            "share_predicted": None,
            "share_actual": None,
        }
    total_p = sum(v["predicted"] for v in out.values()) or 1.0
    total_a = sum(v["actual"] for v in out.values()) or 1.0
    for v in out.values():
        v["share_predicted"] = round(100 * v["predicted"] / total_p, 1)
        v["share_actual"] = round(100 * v["actual"] / total_a, 1)
    return out


def attribute(entry, model):
    """What this project's actuals can and cannot say about the model."""
    actuals = (entry.get("ledger") or {}).get("actuals") or {}
    total_actual = actuals.get("delivery_hours")
    total_pred = (entry.get("total_hours") or {}).get("likely")
    scale = total_pred / total_actual if total_actual else None

    by_role = ratios(entry.get("by_role") or {}, actuals.get("by_role") or {})
    by_phase = ratios({k: v["hours"] for k, v in (entry.get("by_phase") or {}).items()},
                      actuals.get("by_phase") or {})

    separable, blended, sets = [], [], []

    if scale:
        sets.append({
            "path": "size_bands.*",
            "factor": round(1 / scale, 3),
            "why": (f"The project came in at {total_actual}h against {total_pred}h estimated — "
                    f"{scale:.2f}x. This is the whole-project correction and it is NOT a "
                    f"size_bands finding on its own; apply it there only after the separable "
                    f"families below have taken their share, or the bands absorb every other "
                    f"coefficient's error."),
            "caution": "uniform scale — read the separable rows first",
        })

    for role, (component, path) in DIRECT.items():
        row = by_role.get(role)
        if not row or not row["ratio"]:
            continue
        separable.append({
            "role": role,
            "component": component,
            "observed_ratio": row["ratio"],
            "factor": round(1 / row["ratio"], 3),
            "why": (f"`{role}` maps to the `{component}` component alone, so its "
                    f"{row['ratio']}x is that coefficient's error with nothing else mixed in."),
        })
        sets.append({"path": path, "factor": round(1 / row["ratio"], 3),
                     "why": f"{role} actual {row['actual']}h against {row['predicted']}h estimated",
                     "caution": None})

    for role, row in by_role.items():
        if role in DIRECT or not row["ratio"]:
            continue
        drift = row["share_predicted"] - row["share_actual"]
        blended.append({
            "role": role,
            "observed_ratio": row["ratio"],
            "share_predicted": row["share_predicted"],
            "share_actual": row["share_actual"],
            "reading": ("this role is over-weighted relative to the others" if drift > 3
                        else "under-weighted relative to the others" if drift < -3
                        else "its share is about right; the error is in the total, not the split"),
        })

    return {
        "project": entry.get("project"),
        "total": {"estimated": total_pred, "actual": total_actual,
                  "ratio": round(scale, 2) if scale else None},
        "confidence": actuals.get("confidence"),
        "samples": 1,
        "by_role": by_role,
        "by_phase": by_phase if actuals.get("by_phase") else None,
        "separable": separable,
        "blended": blended,
        "not_identifiable": not_identifiable(actuals),
        "suggested": sets,
    }


def not_identifiable(actuals):
    """Said plainly, because the alternative is a confident number nobody can source."""
    missing = []
    if not actuals.get("by_phase"):
        missing.append(
            "size_bands vs review_rate vs compressibility cannot be separated: all three drive "
            "components that only `by_phase` actuals distinguish. Without them the total's error "
            "can be attributed to any of the three, or split between them, and the evidence "
            "cannot say which. Capture hours by BMad phase on the next project.")
    if not actuals.get("by_feature"):
        missing.append(
            "review_tier and compressibility per class need per-feature hours. A project total "
            "cannot tell a sensitive feature's overrun from a routine one's.")
    if not actuals.get("by_role"):
        missing.append(
            "role_weights cannot be touched at all without `by_role`. Record it with "
            "ingest-actuals.py --by-role.")
    return missing


def main():
    ap = argparse.ArgumentParser(
        description="Attribute one project's estimate error to the coefficients behind it.",
        epilog="Exit codes: 0 attribution produced, 1 no usable actuals, 2 unreadable input.",
    )
    ap.add_argument("--entry", required=True, help="ledger entry with actuals attached")
    ap.add_argument("--cost-model", required=True, help="the model to phrase the changes against")
    ap.add_argument("-o", "--output", help="write the attribution here instead of stdout")
    args = ap.parse_args()

    try:
        entry = json.loads(Path(args.entry).read_text(encoding="utf-8"))
        model = json.loads(Path(args.cost_model).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 2

    actuals = (entry.get("ledger") or {}).get("actuals") or {}
    if not actuals.get("delivery_hours"):
        print(json.dumps({
            "ok": False,
            "error": ("this entry carries no delivery_hours, so there is nothing to attribute. "
                      "Attach actuals with ingest-actuals.py first — a total alone is enough to "
                      "start, and --by-role is what makes the role split calibratable."),
        }, indent=2))
        return 1

    result = attribute(entry, model)
    result["ok"] = True
    result["next"] = (
        "Every figure above is one project. Take the separable rows first, preview each with "
        "curate.py --preview, and put the sample size in every --why: a coefficient fitted to "
        "n=1 is far better than a guess and is not a trend."
    )
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
        print(json.dumps({k: v for k, v in result.items()
                          if k in ("ok", "project", "total", "separable", "not_identifiable")},
                         indent=2, ensure_ascii=False))
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
