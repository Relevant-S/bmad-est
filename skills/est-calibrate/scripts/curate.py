#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Apply a coefficient change a human decided from expertise, with the same audit trail as one
the evidence decided.

`apply.py` moves the model on backtested actuals and refuses anything less. That is the right
bar for a calibrator — but it leaves a real case unserved: on day one there are no closed
projects, the seed coefficients are a hypothesis, and a delivery lead who has run twenty of
these projects genuinely knows that sensitive review costs more here than the seed assumes.

Refusing that edit does not prevent it. It sends someone to open cost-model.json in an editor,
where there is no backup, no provenance, no log and no way back. So this exists as the second
door into the same room: same directory, same backup scheme, same log, same refusal to run
unattended — and every entry it writes is stamped `judgement` rather than `calibrated`, so
nobody later mistakes an informed opinion for evidence.

It shows the damage first. Before writing anything, `--preview` re-prices every ledger entry
through est-estimate's engine, so the person approving sees what their change does to numbers
already sent to clients.
"""

import argparse
import json
import shutil
import sys
from datetime import date
from pathlib import Path

import apply as apply_script  # sibling: the other writer of the cost model, and the
                             # single definition of how a backup is taken and pruned
import backtest  # sibling: the engine loader and the re-pricing this shares

BOUNDS = ("lo", "likely", "hi")


class Refused(Exception):
    """Something the operator must decide differently, not a number to hand back."""


def resolve(model, path):
    """Walk a dotted path, returning the container and the final key."""
    node, parts = model, path.split(".")
    for part in parts[:-1]:
        if not isinstance(node, dict) or part not in node:
            raise Refused(f"'{path}' is not in the cost model — '{part}' does not exist. "
                          f"Read cost-model.json for the coefficient's real path.")
        node = node[part]
    if not isinstance(node, dict) or parts[-1] not in node:
        raise Refused(f"'{path}' is not in the cost model. Read cost-model.json for the "
                      f"coefficient's real path; this script never creates one.")
    return node, parts[-1]


def parse_change(raw):
    """`path=value` or `path=lo/likely/hi`."""
    try:
        path, value = raw.split("=", 1)
    except ValueError:
        raise Refused(f"--set wants path=value, got '{raw}'")
    path, value = path.strip(), value.strip()
    if "/" in value:
        parts = value.split("/")
        if len(parts) != 3:
            raise Refused(f"a three-point value is lo/likely/hi — got '{value}'")
        try:
            return path, {b: float(p) for b, p in zip(BOUNDS, parts)}
        except ValueError:
            raise Refused(f"three-point values must be numbers — got '{value}'")
    try:
        return path, float(value)
    except ValueError:
        raise Refused(f"'{value}' is not a number. This script sets numeric coefficients; prose "
                      f"belongs in --why.")


def check_sane(path, row, values):
    """The two ways a hand-set coefficient breaks the model without failing.

    `row` is the resulting three-point range when the coefficient is one, else None.
    """
    for name, value in values.items():
        if value < 0:
            raise Refused(f"{path}.{name} would be {value}. A negative coefficient produces "
                          f"negative hours, which the engine reports without complaint.")
    if "compressibility" in path and any(v <= 0 for v in values.values()):
        raise Refused(f"{path} would be zero or less. Build hours divide by the compression "
                      f"factor, so this makes the estimate infinite or negative.")
    if row and all(b in row for b in BOUNDS):
        lo, likely, hi = (row[b] for b in BOUNDS)
        if not lo <= likely <= hi:
            raise Refused(
                f"{path} would become lo={lo}, likely={likely}, hi={hi}. PERT reads these as an "
                f"ordered range, and an inverted one gives a negative standard deviation — the "
                f"band collapses silently instead of failing.")


def stamp_for(why, approved_by, when, previous):
    return (f"Set by judgement on {when} by {approved_by}: {why} "
            f"(previous: {json.dumps(previous, ensure_ascii=False)}). "
            f"NOT calibrated against delivered actuals.")


def set_one(model, path, value, why, approved_by, when):
    """Apply one change and stamp its provenance into the coefficient itself.

    Three shapes exist in the model and each records its reasoning where a reader will look:
    a whole three-point range, one bound of one, and a plain scalar.
    """
    node, key = resolve(model, path)
    target = node[key]

    if isinstance(value, dict):
        if not isinstance(target, dict):
            raise Refused(f"{path} is a single value, not a three-point range.")
        previous = {b: target[b] for b in BOUNDS if b in target}
        merged = {**previous, **value}
        check_sane(path, merged, value)
        target.update(value)
        target["why"] = f"{target.get('why', '')} — {stamp_for(why, approved_by, when, previous)}".strip(" —")
        return {"coefficient": path, "from": previous, "to": {b: target[b] for b in previous}}

    if isinstance(target, dict):
        raise Refused(f"{path} is a three-point range. Set it as lo/likely/hi, or name one bound "
                      f"such as {path}.likely.")

    row = {b: node[b] for b in BOUNDS} if all(b in node for b in BOUNDS) else None
    if row is not None:
        row[key] = value
        check_sane(path.rsplit(".", 1)[0], row, {key: value})
        node[key] = value
        node["why"] = f"{node.get('why', '')} — {stamp_for(why, approved_by, when, target)}".strip(" —")
    else:
        check_sane(path, None, {key: value})
        node[key] = value
        node[f"{key}_why"] = stamp_for(why, approved_by, when, target)
    return {"coefficient": path, "from": target, "to": value}


def overrides_evidence(model, path):
    """Is the operator replacing a calibrated value with an opinion? Say so before, not after."""
    node = model
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    text = node.get("why", "") if isinstance(node, dict) else ""
    if "Calibrated" in text:
        return ("this coefficient was last set by calibration against delivered projects. "
                "Setting it by judgement replaces evidence with an opinion — which is allowed, "
                "and should be a deliberate choice rather than a surprise.")
    return None


def impact(model_before, model_after, ledger_dir, engine_path=None):
    """What this change does to estimates already sent, re-priced through est-estimate's engine."""
    entries = []
    if ledger_dir and Path(ledger_dir).is_dir():
        for path in sorted(Path(ledger_dir).glob("EST-*.json")):
            try:
                entries.append(json.loads(path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                continue
    if not entries:
        return {"entries": 0,
                "note": ("no ledger entries to re-price, so the effect of this change on past "
                         "estimates is unknown. That is expected before the first estimate and "
                         "worth noticing after.")}

    est = backtest.engine(engine_path)
    rows = []
    for entry in entries:
        before = backtest.reprice(entry, model_before, est)["total_hours"]["likely"]
        after = backtest.reprice(entry, model_after, est)["total_hours"]["likely"]
        actual = ((entry.get("ledger") or {}).get("actuals") or {}).get("delivery_hours")
        row = {"id": (entry.get("ledger") or {}).get("id"), "project": entry.get("project"),
               "status": (entry.get("ledger") or {}).get("status"),
               "before": round(before, 1), "after": round(after, 1),
               "change_pct": round((after - before) / before * 100, 1) if before else None}
        if actual:
            row["actual"] = actual
            row["closer_to_actual"] = abs(after - actual) < abs(before - actual)
        rows.append(row)

    moved = [abs(r["change_pct"]) for r in rows if r["change_pct"] is not None]
    with_actuals = [r for r in rows if "closer_to_actual" in r]
    summary = {
        "entries": len(rows),
        "largest_move_pct": max(moved) if moved else None,
        "median_move_pct": round(sorted(moved)[len(moved) // 2], 1) if moved else None,
        "sent_or_won_affected": [r["id"] for r in rows
                                 if r["status"] in ("sent", "won", "delivered")
                                 and abs(r["change_pct"] or 0) >= 1],
        "per_entry": rows,
    }
    if with_actuals:
        closer = sum(1 for r in with_actuals if r["closer_to_actual"])
        summary["against_actuals"] = {
            "compared": len(with_actuals), "closer": closer,
            "further": len(with_actuals) - closer,
            "note": ("these projects have real hours. If a judgement change moves estimates away "
                     "from what actually happened, est-calibrate has better evidence than this "
                     "opinion does."),
        }
    return summary


def log_entry(applied, why, approved_by, when, effect, warnings):
    lines = [f"## {when} — {applied['coefficient']} (judgement)", "",
             f"- **Change:** {json.dumps(applied, ensure_ascii=False)}",
             f"- **Basis:** judgement, not delivered actuals — {why}",
             f"- **Set by:** {approved_by}",
             f"- **Effect on recorded estimates:** "
             f"{effect.get('entries', 0)} entries re-priced; "
             f"largest move {effect.get('largest_move_pct', 'n/a')}%"]
    if effect.get("sent_or_won_affected"):
        lines.append(f"- **Already quoted and now re-priced:** "
                     f"{', '.join(effect['sent_or_won_affected'])}")
    if effect.get("against_actuals"):
        a = effect["against_actuals"]
        lines.append(f"- **Against real actuals:** closer on {a['closer']} of {a['compared']}")
    for warning in warnings:
        lines.append(f"- **Warning:** {warning}")
    lines += ["", f"To reverse this, restore {json.dumps(applied['from'], ensure_ascii=False)} "
                  f"and log the reversal here.", ""]
    return "\n".join(lines)


def run(args):
    model_path = Path(args.cost_model)
    model = json.loads(model_path.read_text(encoding="utf-8"))
    before_model = json.loads(json.dumps(model))

    if not (args.why or "").strip():
        raise Refused("every change needs --why. A coefficient nobody can interrogate is exactly "
                      "what this module refuses to ship, and judgement needs its reasoning "
                      "recorded more than evidence does, not less.")

    changes = [parse_change(raw) for raw in args.set]
    warnings = [w for w in (overrides_evidence(model, path) for path, _ in changes) if w]

    when = date.today().isoformat()
    applied = [set_one(model, path, value, args.why, args.approved_by or "preview", when)
               for path, value in changes]
    effect = impact(before_model, model, args.ledger, args.engine)

    if args.preview:
        return {"ok": True, "preview": True, "would_apply": applied, "warnings": warnings,
                "impact": effect, "why": args.why,
                "next": ("nothing was written. Re-run without --preview, with --approved-by, to "
                         "apply this.")}

    # Same gate as apply.py, for the same reason: an approval has no safe unattended default,
    # and a rule that lives only in prose ends at the next compaction.
    if not sys.stdin.isatty():
        raise Refused("refusing to write the cost model from an unattended run. A judgement change "
                      "is a person's opinion and needs that person present. Use --preview to "
                      "produce the analysis; apply it interactively.")
    if not (args.approved_by or "").strip():
        raise Refused("--approved-by is required: the log records who decided this, and 'the "
                      "agent' is not an answer anyone can go back to.")

    # One definition of "take a backup and prune the old ones", shared with apply.py. Two
    # would drift on the retention count, and the two writers of this file must not disagree
    # about how far back a reversal can reach.
    backup, pruned = apply_script.take_backup(model_path, when)

    model.setdefault("calibration_history", []).append({
        "date": when, "approved_by": args.approved_by, "kind": "judgement",
        "coefficients": [a["coefficient"] for a in applied], "why": args.why,
    })
    model_path.write_text(json.dumps(model, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    log_path = Path(args.calibration_log)
    header = "" if log_path.exists() else \
        "# Calibration log\n\nEvery coefficient change, its evidence, and how to reverse it.\n\n"
    try:
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(header + "\n".join(
                log_entry(a, args.why, args.approved_by, when, effect, warnings) for a in applied))
    except OSError as exc:
        shutil.copyfile(backup, model_path)
        raise Refused(f"the calibration log at {log_path} could not be written ({exc}), so the "
                      f"change was rolled back. A coefficient that moved with no record of why is "
                      f"the silent drift this module exists to prevent.")

    return {"ok": True, "applied": applied, "warnings": warnings, "impact": effect,
            "backup": str(backup), "calibration_log": str(log_path)}


def main():
    ap = argparse.ArgumentParser(
        description="Set a cost-model coefficient from human judgement, with a full audit trail.",
        epilog="Exit codes: 0 done, 1 refused, 2 unreadable input.",
    )
    ap.add_argument("--cost-model", required=True, help="cost-model.json to update in place")
    ap.add_argument("--calibration-log", required=True, help="calibration-log.md to append to")
    ap.add_argument("--set", nargs="+", required=True, metavar="PATH=VALUE",
                    help="e.g. qa.web=0.07/0.095/0.14 or uncertainty.model_risk=0.10")
    ap.add_argument("--why", required=True, help="the reasoning; recorded in the coefficient itself")
    ap.add_argument("--approved-by", help="who decided this; required to apply, not to preview")
    ap.add_argument("--ledger", help="ledger directory, to re-price what this would change")
    ap.add_argument("--engine", help="est-estimate's estimate.py, if not at the usual path")
    ap.add_argument("--preview", action="store_true",
                    help="report the change and its effect on past estimates; write nothing")
    args = ap.parse_args()

    try:
        result = run(args)
    except Refused as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 2

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
