#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Record an estimate in the module ledger, and list what the ledger holds.

The ledger is what makes calibration possible later. Each entry stores the estimate
whole — including the snapshot of the cost model that produced it — because without
that snapshot est-calibrate cannot tell a bad estimate from a model that has since
changed, and every delta it computes would be meaningless.

Entries are durable. A draft may be deliberately replaced; an entry that has been sent,
won, lost or delivered is a commercial fact and is never overwritten. Re-estimating the
same project on the same day is the normal presale case after a client pushes back, so
that collision records a revision alongside the original rather than destroying it —
calibration wants the history of how a number moved as much as the final figure.
"""

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path


def slugify(text):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", (text or "estimate").lower())).strip("-")[:48]


def entry_id(estimate, when=None):
    stamp = (when or (estimate.get("generated") or "")[:10] or date.today().isoformat())
    return f"EST-{stamp.replace('-', '')}-{slugify(estimate.get('project'))}"


def record(estimate, ledger_dir, status, replace=False, revision=False):
    ledger_dir = Path(ledger_dir)
    ledger_dir.mkdir(parents=True, exist_ok=True)
    eid = entry_id(estimate)
    target = ledger_dir / f"{eid}.json"
    if revision and target.exists():
        # Keep both. A revision is a new estimate, not a correction of the old one, and
        # calibration wants the history of how a number moved as much as the final figure.
        n = 2
        while (ledger_dir / f"{eid}-r{n}.json").exists():
            n += 1
        eid = f"{eid}-r{n}"
        target = ledger_dir / f"{eid}.json"
    if target.exists() and not replace:
        existing = json.loads(target.read_text(encoding="utf-8")).get("ledger", {})
        existing_status = existing.get("status", "draft")
        if existing_status == "draft":
            return {"ok": False, "collision": eid, "existing_status": existing_status,
                    "error": (f"{eid} already recorded as a draft. Re-estimating the same project on "
                              f"the same day is normal after a client pushes back — record this as a "
                              f"revision with --revision, which keeps both entries, or --replace to "
                              f"overwrite the draft deliberately."),
                    "entry": str(target)}
        return {"ok": False, "collision": eid, "existing_status": existing_status,
                "error": (f"{eid} is already recorded with status '{existing_status}'. An entry that has been "
                          f"sent, won, lost or delivered is a commercial fact and is never overwritten "
                          f"— record this as a revision with --revision."),
                "entry": str(target)}

    if target.exists() and replace:
        prior = json.loads(target.read_text(encoding="utf-8")).get("ledger", {})
        if prior.get("status") not in (None, "draft"):
            return {"ok": False, "collision": eid, "existing_status": prior.get("status"),
                    "error": (f"refusing to replace {eid}: it is recorded as "
                              f"'{prior.get('status')}'. Use --revision."),
                    "entry": str(target)}

    payload = dict(estimate)
    payload["ledger"] = {
        "id": eid,
        "status": status,
        "recorded": date.today().isoformat(),
        "actuals": None,
        "note": ("Set status as the deal moves: draft, sent, won, lost, delivered. When the work "
                 "is done, est-calibrate reads this entry and fills in actuals."),
    }
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    reindex(ledger_dir)
    return {"ok": True, "id": eid, "entry": str(target), "status": status}


def reindex(ledger_dir):
    """Rebuild index.json from the entries themselves, so it can never drift."""
    ledger_dir = Path(ledger_dir)
    rows = []
    for path in sorted(ledger_dir.glob("EST-*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        ledger = data.get("ledger", {})
        rows.append({
            "id": ledger.get("id", path.stem),
            "project": data.get("project"),
            "granularity": data.get("granularity"),
            "mode": data.get("mode"),
            "generated": data.get("generated"),
            "status": ledger.get("status"),
            "likely_hours": (data.get("total_hours") or {}).get("likely"),
            "low_hours": (data.get("total_hours") or {}).get("low"),
            "high_hours": (data.get("total_hours") or {}).get("high"),
            "input_completeness": (data.get("confidence") or {}).get("input_completeness"),
            "features": len((data.get("features") or [])),
            "has_actuals": bool(ledger.get("actuals")),
            "file": path.name,
        })
    index = ledger_dir / "index.json"
    index.write_text(json.dumps({"entries": rows}, indent=2, ensure_ascii=False) + "\n",
                     encoding="utf-8")
    return rows


def set_status(ledger_dir, eid, status):
    target = Path(ledger_dir) / f"{eid}.json"
    if not target.exists():
        return {"ok": False, "error": f"no ledger entry {eid} in {ledger_dir}"}
    data = json.loads(target.read_text(encoding="utf-8"))
    data.setdefault("ledger", {})["status"] = status
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    reindex(ledger_dir)
    return {"ok": True, "id": eid, "status": status}


def main():
    ap = argparse.ArgumentParser(
        description="Record an estimate in the module ledger, or inspect what it holds.",
        epilog="Exit codes: 0 ok, 1 refused (already recorded / unknown entry), 2 unreadable input.",
    )
    ap.add_argument("--ledger", required=True, help="ledger directory, e.g. {project-root}/_bmad/memory/est/ledger")
    ap.add_argument("--record", metavar="ESTIMATE", help="path to estimate.json to record")
    ap.add_argument("--status", default="draft",
                    help="draft | sent | won | lost | delivered (default: draft)")
    ap.add_argument("--replace", action="store_true",
                    help="overwrite an existing DRAFT entry; refused once an entry has been sent or won")
    ap.add_argument("--revision", action="store_true",
                    help="record alongside an existing entry as a revision, keeping both")
    ap.add_argument("--set-status", nargs=2, metavar=("ID", "STATUS"), help="update an entry's status")
    ap.add_argument("--list", action="store_true", help="print the ledger index")
    args = ap.parse_args()

    if args.set_status:
        result = set_status(args.ledger, *args.set_status)
    elif args.list:
        result = {"ok": True, "entries": reindex(args.ledger)}
    elif args.record:
        try:
            estimate = json.loads(Path(args.record).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
            return 2
        if "cost_model_snapshot" not in estimate:
            print(json.dumps({
                "ok": False,
                "error": ("estimate carries no cost_model_snapshot; recording it would produce a "
                          "ledger entry calibration cannot use"),
            }, indent=2))
            return 2
        result = record(estimate, args.ledger, args.status, args.replace, args.revision)
    else:
        ap.error("one of --record, --set-status or --list is required")

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
