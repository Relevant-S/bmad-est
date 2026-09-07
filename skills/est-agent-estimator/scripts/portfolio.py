#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""One pass over every estimate workspace and every ledger entry, as one JSON.

Triage answers a question nobody can answer by memory — which of eleven pending deals needs
attention first, which quoted scope has drifted since the client sent v2, which won project
closed months ago and never came back with hours. All of that is file state: what exists,
what is newer than what, what the ledger says. Reading it by hand across a dozen folders is
where a stale estimate gets treated as current.

This decides nothing. It reports state and the signals that bear on priority; which deal
actually matters is the judgement it hands back.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ordered by how much a wrong answer costs: a broken inventory silently prices wrong, a stale
# estimate is quoted as current, an uncaptured actual is calibration evidence lost for good.
ACTION_URGENCY = [
    "fix inventory findings",
    "re-extract: sources changed",
    "re-estimate: scope changed",
    "capture actuals",
    "estimate",
    "extract",
    "record in ledger",
    "current",
]


def mtime(path):
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def load(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def parse_stamp(value):
    """A `generated` timestamp as epoch seconds, or None if it is absent or unparseable."""
    if not value:
        return None
    try:
        text = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except ValueError:
        return None


def newer(later, earlier, later_stamp=None, earlier_stamp=None):
    """Is `later` genuinely newer than `earlier`?

    Recorded `generated` timestamps beat file mtimes, because a clone or a checkout rewrites
    every mtime at once and would report the whole portfolio as stale on a fresh machine. The
    mtime comparison is the fallback for artefacts that carry no stamp.
    """
    a, b = parse_stamp(later_stamp), parse_stamp(earlier_stamp)
    if a is not None and b is not None:
        return a > b, "recorded timestamps"
    a, b = mtime(later), mtime(earlier)
    if a is None or b is None:
        return False, "not comparable"
    return a > b + 1, "file modification times"


def share(part, whole):
    return round(part / whole * 100, 1) if whole else None


# What makes a directory an estimate workspace. A folder with none of these was put here by
# something else — a calibration run, a stray export, a half-made directory — and reporting it
# as a project needing scope extraction produces a phantom that never goes away. Skipped folders
# are still named in the output: silently dropping one is how a real project disappears.
WORKSPACE_MARKERS = ("feature-inventory.json", "estimate.json", "normalized")


def is_workspace(folder):
    """A workspace carries a marker, or holds files someone put there directly.

    The second half matters: a folder of raw client documents nobody has extracted yet is
    exactly what triage should surface. What it excludes is a folder holding only dated
    subdirectories — the shape of a calibration run, which is portfolio-wide and not a project.
    """
    if any((folder / marker).exists() for marker in WORKSPACE_MARKERS):
        return True
    try:
        return any(child.is_file() and not child.name.startswith(".") for child in folder.iterdir())
    except OSError:
        return False


def read_workspace(folder):
    """Everything one estimate folder can tell us, without opinions about it."""
    inventory_path = folder / "feature-inventory.json"
    estimate_path = folder / "estimate.json"
    inventory, estimate = load(inventory_path), load(estimate_path)
    check = load(folder / "check.json")
    manifest = load(folder / "normalized" / "manifest.json")

    row = {
        "slug": folder.name,
        "path": str(folder),
        "project": (estimate or {}).get("project") or (inventory or {}).get("project") or folder.name,
        "has": {
            "inventory": inventory is not None,
            "check": check is not None,
            "estimate": estimate is not None,
            "brief": (folder / "estimate-brief.json").exists(),
            "html": (folder / "estimate.html").exists(),
            "memlog": (folder / ".memlog.md").exists(),
            "normalized_sources": manifest is not None,
        },
        "signals": [],
    }

    if inventory:
        row["features"] = len(inventory.get("features") or [])
        row["granularity"] = inventory.get("granularity")
        row["open_questions"] = sum(len(f.get("open_questions") or [])
                                    for f in inventory.get("features") or [])
    if check:
        row["input_completeness"] = (check.get("scoring") or {}).get("input_completeness")
        row["check_findings"] = len(check.get("findings") or [])
    if estimate:
        total = estimate.get("total_hours") or {}
        likely = total.get("likely")
        risk_hours = sum(f.get("hours", 0.0) for f in estimate.get("risk_quadrant") or [])
        outside = ((estimate.get("scope_split") or {}).get("outside_agreed_scope") or {})
        row.update({
            "mode": estimate.get("mode"),
            "total_hours": total,
            "band_width_pct": (estimate.get("confidence") or {}).get("band_width_pct")
                              or share((total.get("high", 0) - total.get("low", 0)), likely),
            "input_completeness": row.get("input_completeness")
                                  or (estimate.get("confidence") or {}).get("input_completeness"),
            "risk_quadrant_hours": round(risk_hours, 1),
            "risk_quadrant_pct": share(risk_hours, likely),
            "outside_agreed_scope_pct": outside.get("share_of_total_pct"),
            "calibrated": bool((estimate.get("cost_model_snapshot") or {})
                               .get("calibration_history")
                               and any((h.get("kind") or "calibrated") != "judgement"
                                       for h in estimate["cost_model_snapshot"]["calibration_history"])),
            "traceability_findings": len((estimate.get("traceability") or {}).get("findings") or []),
        })

    # Staleness, in the two places it bites: a client sends v2 of a document, or the inventory
    # is corrected after the number went out.
    if manifest and inventory:
        sources = [Path(s["converted_path"]) for s in (manifest.get("sources") or [])
                   if s.get("converted_path")]
        latest = max((p for p in sources if mtime(p)), key=mtime, default=None)
        if latest:
            stale, basis = newer(latest, inventory_path)
            if stale:
                row["signals"].append({"kind": "sources_changed",
                                       "detail": f"{latest.name} is newer than the inventory "
                                                 f"(by {basis}) — the extraction may not cover it"})
    if inventory and estimate:
        stale, basis = newer(inventory_path, estimate_path,
                             inventory.get("generated"), estimate.get("generated"))
        if stale:
            row["signals"].append({"kind": "scope_changed",
                                   "detail": f"the inventory is newer than the estimate "
                                             f"(by {basis}) — the quoted number is behind the scope"})
    return row, inventory, estimate


def read_ledger(ledger_dir):
    """The entries themselves, never index.json — an index can drift, entries cannot."""
    entries = []
    if not ledger_dir or not Path(ledger_dir).is_dir():
        return entries
    for path in sorted(Path(ledger_dir).glob("EST-*.json")):
        data = load(path)
        if not data:
            continue
        ledger = data.get("ledger") or {}
        actuals = ledger.get("actuals") or None
        entries.append({
            "id": ledger.get("id", path.stem),
            "file": str(path),
            "project": data.get("project"),
            "status": ledger.get("status"),
            "recorded": ledger.get("recorded"),
            "generated": data.get("generated"),
            "likely_hours": (data.get("total_hours") or {}).get("likely"),
            "has_actuals": bool(actuals),
            "delivery_hours": (actuals or {}).get("delivery_hours"),
        })
    return entries


def next_action(row, entries):
    """Derived strictly from what exists on disk. What matters most is the agent's call."""
    if row["has"].get("inventory") and row.get("check_findings"):
        return "fix inventory findings"
    if any(s["kind"] == "sources_changed" for s in row["signals"]):
        return "re-extract: sources changed"
    if any(s["kind"] == "scope_changed" for s in row["signals"]):
        return "re-estimate: scope changed"
    if not row["has"].get("inventory"):
        return "extract"
    if not row["has"].get("estimate"):
        return "estimate"
    closed = [e for e in entries if e["status"] in ("won", "delivered") and not e["has_actuals"]]
    if closed:
        return "capture actuals"
    if not entries and row.get("mode") != "quick":
        return "record in ledger"
    return "current"


def attention(row, entries):
    """Signals that bear on priority. Thresholds are stated so nobody has to infer them."""
    out = list(row["signals"])
    completeness = row.get("input_completeness")
    if completeness is not None and completeness < 0.35:
        out.append({"kind": "thin_input",
                    "detail": f"input completeness {completeness} — the band is wide because the "
                              f"brief is thin, and questions will move it more than analysis will"})
    if (row.get("risk_quadrant_pct") or 0) >= 25:
        out.append({"kind": "risk_quadrant",
                    "detail": f"{row['risk_quadrant_pct']}% of the hours are low-compressibility and "
                              f"sensitive or critical — where BMad's advantage is smallest"})
    if (row.get("outside_agreed_scope_pct") or 0) >= 20:
        out.append({"kind": "outside_agreed_scope",
                    "detail": f"{row['outside_agreed_scope_pct']}% of the estimate is work no "
                              f"contract covers"})
    if row.get("traceability_findings"):
        out.append({"kind": "traceability",
                    "detail": f"{row['traceability_findings']} priced items do not trace to a source"})
    for entry in entries:
        if entry["status"] in ("won", "delivered") and not entry["has_actuals"]:
            out.append({"kind": "awaiting_actuals",
                        "detail": f"{entry['id']} is {entry['status']} with no actuals recorded — "
                                  f"calibration evidence going cold"})
    return out


def main():
    ap = argparse.ArgumentParser(
        description="State of every estimate workspace and ledger entry, as one JSON.",
        epilog="Exit codes: 0 read, 2 the estimates folder does not exist.",
    )
    ap.add_argument("--estimates", required=True, help="folder holding one directory per project")
    ap.add_argument("--ledger", help="the module's ledger directory")
    ap.add_argument("-o", "--output", help="write here instead of stdout")
    args = ap.parse_args()

    root = Path(args.estimates)
    if not root.is_dir():
        print(json.dumps({
            "ok": False,
            "error": (f"{root} does not exist. Nothing has been estimated in this project yet — "
                      f"that is a legitimate day-one state, not a failure."),
            "projects": [], "ledger": [],
        }, indent=2))
        return 2

    ledger_entries = read_ledger(args.ledger)
    projects, skipped = [], []
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        if not is_workspace(folder):
            skipped.append({"name": folder.name,
                            "why": (f"holds none of {', '.join(WORKSPACE_MARKERS)}, so it is not an "
                                    f"estimate workspace")})
            continue
        row, _, _ = read_workspace(folder)
        entries = [e for e in ledger_entries if e["project"] == row["project"]]
        row["ledger_entries"] = sorted(entries, key=lambda e: e.get("recorded") or "", reverse=True)
        row["next_action"] = next_action(row, entries)
        row["attention"] = attention(row, entries)
        projects.append(row)

    projects.sort(key=lambda r: (ACTION_URGENCY.index(r["next_action"]),
                                 -((r.get("total_hours") or {}).get("likely") or 0)))

    by_status = {}
    for entry in ledger_entries:
        bucket = by_status.setdefault(entry["status"] or "unknown", {"count": 0, "likely_hours": 0.0})
        bucket["count"] += 1
        bucket["likely_hours"] = round(bucket["likely_hours"] + (entry["likely_hours"] or 0), 1)

    print_target = json.dumps({
        "ok": True,
        "estimates_folder": str(root),
        "projects": projects,
        "skipped_folders": skipped,
        "ledger": {"entries": ledger_entries, "by_status": by_status,
                   "awaiting_actuals": [e["id"] for e in ledger_entries
                                        if e["status"] in ("won", "delivered") and not e["has_actuals"]]},
        "summary": {
            "projects": len(projects),
            "needing_action": sum(1 for p in projects if p["next_action"] != "current"),
            "by_next_action": {a: sum(1 for p in projects if p["next_action"] == a)
                               for a in ACTION_URGENCY
                               if any(p["next_action"] == a for p in projects)},
        },
        "why": ("Ordering is by how much a wrong answer costs, then by size. It is a starting "
                "point for triage, not a decision about which deal matters."),
    }, indent=2, ensure_ascii=False)

    if args.output:
        Path(args.output).write_text(print_target + "\n", encoding="utf-8")
        print(json.dumps({"ok": True, "portfolio": args.output, "projects": len(projects)}, indent=2))
    else:
        print(print_target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
