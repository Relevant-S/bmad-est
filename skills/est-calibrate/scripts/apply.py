#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Apply approved coefficient changes to the cost model, with a full audit trail.

This is the only place in the module that writes to the cost model, and it is deliberately
hard to use carelessly. It refuses a change that carries no backtest, refuses one with no
stated reason, writes the provenance into the coefficient's own `why` so the model explains
its own history, and appends an entry to the calibration log that names every ledger entry
the change was derived from.

Nothing here decides anything. It applies what a human already approved by id.
"""

import argparse
import json
import shutil
import sys
from datetime import date
from pathlib import Path


def resolve(model, path):
    """Walk a dotted coefficient path, returning the container and the final key."""
    node, parts = model, path.split(".")
    for part in parts[:-1]:
        node = node[part]
    return node, parts[-1]


def apply_one(model, proposal, backtest, approved_by, when):
    """Apply one proposal and stamp its provenance into the model itself."""
    target, kind, value = proposal["coefficient"], proposal.get("kind", "factor"), proposal["proposed"]
    stamp = (f"Calibrated {when} from {proposal['samples']} delivered projects "
             f"({proposal.get('why', 'no reason recorded')}). "
             f"Backtest: {backtest.get('verdict', 'not run')}, improved "
             f"{backtest.get('improved', 0)} of {backtest.get('samples', 0)}. "
             f"Approved by {approved_by}.")

    if kind == "absolute":
        node, key = resolve(model, target)
        previous = node.get(key)
        node[key] = value
        node[f"{key}_why"] = f"{stamp} Previous value {previous}."
        return {"coefficient": target, "from": previous, "to": value}

    family = target.replace(".*", "")
    node = model
    for part in family.split("."):
        node = node[part]
    changed = {}
    for key, entry in node.items():
        if key.startswith("_") or not isinstance(entry, dict):
            continue
        before = {b: entry[b] for b in ("lo", "likely", "hi") if b in entry}
        for bound in before:
            entry[bound] = round(entry[bound] * value, 4)
        entry["why"] = f"{entry.get('why', '')} — {stamp} Scaled by {value}x from {before}.".strip(" —")
        changed[key] = {"from": before,
                        "to": {b: entry[b] for b in before}}
    return {"coefficient": target, "factor": value, "entries": changed}


def log_entry(applied, proposal, backtest, approved_by, when, ledger_ids):
    lines = [
        f"## {when} — {proposal['coefficient']}",
        "",
        f"- **Change:** {json.dumps(applied, ensure_ascii=False)}",
        f"- **Evidence:** {proposal.get('evidence', 'none recorded')}",
        f"- **Samples:** {proposal['samples']} delivered projects"
        + (" — **weak signal**" if proposal.get("weak_signal") else ""),
        f"- **Backtest:** {backtest.get('verdict', 'not run')} — improved {backtest.get('improved', 0)}, "
        f"worsened {backtest.get('worsened', 0)}, unchanged {backtest.get('unchanged', 0)}",
        f"- **Band hit rate:** {backtest.get('before', {}).get('band_hit_rate')} → "
        f"{backtest.get('after', {}).get('band_hit_rate')}",
        f"- **Median absolute error:** {backtest.get('before', {}).get('median_abs_error_pct')}% → "
        f"{backtest.get('after', {}).get('median_abs_error_pct')}%",
        f"- **Derived from:** {', '.join(ledger_ids) if ledger_ids else 'not recorded'}",
        f"- **Approved by:** {approved_by}",
        "",
        "To reverse this, restore the previous values named above and log the reversal here.",
        "",
    ]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(
        description="Apply human-approved coefficient changes to the cost model.",
        epilog="Exit codes: 0 applied, 1 refused, 2 unreadable input.",
    )
    ap.add_argument("--analysis", required=True, help="analysis JSON from analyze.py")
    ap.add_argument("--backtest", required=True, help="backtest JSON from backtest.py")
    ap.add_argument("--cost-model", required=True, help="cost-model.json to update in place")
    ap.add_argument("--calibration-log", required=True, help="calibration-log.md to append to")
    ap.add_argument("--accept", nargs="+", required=True, metavar="ID",
                    help="proposal ids a human approved, e.g. P1 P3")
    ap.add_argument("--approved-by", required=True,
                    help="who approved these changes; recorded in the model and the log")
    args = ap.parse_args()

    # The one guarantee this module rests on is that nothing changes the cost model without a
    # human deciding it. A prose rule holds only while the agent is still carrying it, which
    # compaction or a programmatic caller can end. There is deliberately no override flag:
    # an override would reintroduce exactly the hole this closes.
    if not sys.stdin.isatty():
        print(json.dumps({
            "ok": False,
            "error": ("refusing to write the cost model from an unattended run. Every coefficient "
                      "change needs a human who decided it, and an approval gate has no safe "
                      "default. Run est-calibrate interactively to review and accept proposals; "
                      "a scheduled run can produce the analysis, the backtests and the report."),
        }, indent=2))
        return 1

    try:
        analysis = json.loads(Path(args.analysis).read_text(encoding="utf-8"))
        backtests = json.loads(Path(args.backtest).read_text(encoding="utf-8"))
        model_path = Path(args.cost_model)
        model = json.loads(model_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 2

    by_id = {p["id"]: p for p in analysis.get("proposals", [])}
    results = {b["proposal"]: b for b in backtests.get("backtests", [])}

    chosen = []
    for pid in args.accept:
        proposal = by_id.get(pid)
        if not proposal:
            print(json.dumps({"ok": False, "error": f"no proposal {pid} in this analysis — "
                                                    f"available: {sorted(by_id)}"}, indent=2))
            return 1
        result = results.get(pid)
        if not result:
            print(json.dumps({
                "ok": False,
                "error": (f"{pid} has no backtest result. A coefficient change with no evidence that "
                          f"it improves past estimates is a different guess, not a calibration. Run "
                          f"backtest.py over this analysis first. There is no override: if history "
                          f"cannot be re-priced, the model does not move."),
            }, indent=2))
            return 1
        if not (proposal.get("why") or "").strip():
            print(json.dumps({"ok": False, "error": f"{pid} carries no 'why'; a coefficient nobody "
                                                    f"can interrogate is what this module refuses to ship"},
                             indent=2))
            return 1
        chosen.append((proposal, result or {}))

    when = date.today().isoformat()
    ledger_ids = [e["id"] for e in (analysis.get("accuracy") or {}).get("entries", [])]

    # Keep the pre-change model beside the new one; a reversal should never depend on someone
    # having remembered to take a copy. Numbered per run, because a second calibration on the
    # same day would otherwise overwrite the first backup with an already-calibrated model —
    # leaving the rollback path pointing at the wrong state.
    n = 1
    while (backup := model_path.with_suffix(f".{when}.{n}.bak.json")).exists():
        n += 1
    shutil.copyfile(model_path, backup)

    applied, log = [], []
    for proposal, result in chosen:
        applied.append(apply_one(model, proposal, result, args.approved_by, when))
        log.append(log_entry(applied[-1], proposal, result, args.approved_by, when, ledger_ids))

    model.setdefault("calibration_history", []).append({
        "date": when, "approved_by": args.approved_by,
        "proposals": [p["id"] for p, _ in chosen], "samples": analysis.get("samples"),
    })
    if applied:
        model["calibration_status"] = (
            f"Calibrated {when} against {analysis.get('samples')} delivered projects. "
            f"See calibration-log.md for what changed and why.")

    model_path.write_text(json.dumps(model, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # A changed model with no log entry is exactly the silent drift this skill exists to
    # prevent, so if the log cannot be written the model goes back.
    log_path = Path(args.calibration_log)
    header = "" if log_path.exists() else "# Calibration log\n\nEvery coefficient change, its evidence, and how to reverse it.\n\n"
    try:
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(header + "\n".join(log))
    except OSError as exc:
        shutil.copyfile(backup, model_path)
        print(json.dumps({
            "ok": False,
            "error": (f"the calibration log at {log_path} could not be written ({exc}), so the "
                      f"model change was rolled back. A coefficient that moved with no record of "
                      f"why is the silent drift this skill exists to prevent."),
        }, indent=2))
        return 1

    print(json.dumps({"ok": True, "applied": applied, "backup": str(backup),
                      "calibration_log": str(log_path)}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
