#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["openpyxl>=3.1"]
# ///
"""Attach real spent hours to a ledger entry.

Takes whatever time data exists — a time-tracking export, or a single typed total — and
records it in the entry's `actuals` slot. Deliberately tolerant about column names, because
every time-tracking tool names them differently and a calibrator nobody can feed is a
calibrator nobody runs.

Deliberately strict about three things, because each one silently invalidates a comparison:
whether the delivered scope matched what was priced, why any hours were excluded, and where
the numbers came from.
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path

# Exact matches on a normalized header, not substrings: "timestamp" contains "time" and is
# not an hours column. The compounds are generated because every tracker names this
# differently — Jira ships "Time Spent", Harvest "Hours", Toggl "Duration".
_HOURS_WORDS = {"hours", "hrs", "duration", "time", "effort", "spent", "logged", "worked"}
_HOURS_QUALIFIERS = {"spent", "logged", "worked", "total", "actual", "billable", "tracked"}
SCHEMA = Path(__file__).resolve().parent.parent / "assets" / "actuals.schema.json"

HOURS_COLUMNS = _HOURS_WORDS | {
    f"{a}{b}" for a in ("time", "hours", "hrs", "duration", "effort") for b in _HOURS_QUALIFIERS
} | {
    f"{b}{a}" for a in ("time", "hours", "hrs", "duration", "effort") for b in _HOURS_QUALIFIERS
}
PHASE_COLUMNS = {"phase", "stage", "activity", "category", "worktype", "work_type"}
FEATURE_COLUMNS = {"feature", "story", "issue", "ticket", "key", "task", "epic"}
ROLE_COLUMNS = {"role", "person", "user", "member", "who", "assignee"}

PHASE_ALIASES = {
    "planning": "planning", "plan": "planning", "discovery": "planning", "prd": "planning",
    "architecture": "planning", "design": "planning",
    "planning-review": "planning-review", "planning review": "planning-review", "review-planning": "planning-review",
    "spec": "spec", "specification": "spec", "refinement": "spec",
    "build": "build", "dev": "build", "development": "build", "implementation": "build", "coding": "build",
    "review": "review", "code review": "review", "codereview": "review", "pr": "review",
    "rework": "rework", "fix": "rework", "bugfix": "rework", "defect": "rework",
    "environments": "environments", "infra": "environments", "devops": "environments",
    "ci": "environments", "deployment": "environments",
    "qa": "qa", "test": "qa", "testing": "qa",
    "overhead": "overhead", "meeting": "overhead", "ceremony": "overhead", "comms": "overhead",
    "standup": "overhead", "demo": "overhead",
}


def normalize(name):
    return re.sub(r"[^a-z]", "", (name or "").lower())


def find_column(headers, candidates):
    for i, header in enumerate(headers):
        if normalize(header) in candidates:
            return i
    return None


def read_rows(path):
    suffix = path.suffix.lower()
    if suffix in (".csv", ".tsv"):
        delim = "\t" if suffix == ".tsv" else None
        with path.open(encoding="utf-8-sig", errors="replace", newline="") as fh:
            sample = fh.read(4096)
            fh.seek(0)
            if delim is None:
                try:
                    delim = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
                except csv.Error:
                    delim = ","
            return [row for row in csv.reader(fh, delimiter=delim) if any(c.strip() for c in row)]
    if suffix in (".xlsx", ".xlsm"):
        try:
            from openpyxl import load_workbook
        except ImportError:
            raise SystemExit(json.dumps({"ok": False, "error": "openpyxl is required to read xlsx"}))
        wb = load_workbook(path, data_only=True, read_only=True)
        rows = []
        for sheet in wb.sheetnames:
            for cells in wb[sheet].iter_rows(values_only=True):
                if any(c is not None and str(c).strip() for c in cells):
                    rows.append(["" if c is None else str(c) for c in cells])
        wb.close()
        return rows
    raise SystemExit(json.dumps({"ok": False, "error": f"unsupported export format {suffix}"}))


def aggregate(rows):
    """Sum hours by whichever dimension the export happens to carry."""
    if not rows:
        return {"total": 0.0, "by_phase": {}, "by_feature": {}, "by_role": {}, "unmapped": []}
    headers = rows[0]
    hours_at = find_column(headers, HOURS_COLUMNS)
    if hours_at is None:
        raise SystemExit(json.dumps({
            "ok": False,
            "error": (f"no hours column found. Looked for {sorted(HOURS_COLUMNS)}; the file has "
                      f"{[h for h in headers if h]}. Rename the column or use --total.")}, indent=2))

    phase_at = find_column(headers, PHASE_COLUMNS)
    feature_at = find_column(headers, FEATURE_COLUMNS)
    role_at = find_column(headers, ROLE_COLUMNS)

    total, by_phase, by_feature, by_role, unmapped = 0.0, {}, {}, {}, []
    for row in rows[1:]:
        try:
            hours = float(str(row[hours_at]).replace(",", "."))
        except (ValueError, IndexError):
            continue
        total += hours
        if phase_at is not None and phase_at < len(row):
            raw = str(row[phase_at]).strip()
            phase = PHASE_ALIASES.get(raw.lower())
            if phase:
                by_phase[phase] = round(by_phase.get(phase, 0.0) + hours, 2)
            elif raw:
                unmapped.append(raw)
        if feature_at is not None and feature_at < len(row):
            key = str(row[feature_at]).strip()
            if key:
                by_feature[key] = round(by_feature.get(key, 0.0) + hours, 2)
        if role_at is not None and role_at < len(row):
            key = str(row[role_at]).strip().lower()
            if key:
                by_role[key] = round(by_role.get(key, 0.0) + hours, 2)

    return {"total": round(total, 2), "by_phase": by_phase, "by_feature": by_feature,
            "by_role": by_role, "unmapped": sorted(set(unmapped))}


def validate(actuals):
    """Check what is about to be written against the contract everything downstream reads.

    A schema nothing validates against is decoration. analyze.py depends on these field
    names and enums, and a typo here surfaces months later as a project silently missing
    from a calibration sample.
    """
    try:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []   # degrade rather than block: the write is still better than no record
    problems = []
    props = schema.get("properties", {})
    for field in schema.get("required", []):
        if field not in actuals:
            problems.append(f"{field} is required by assets/actuals.schema.json and is missing")
    for field, value in actuals.items():
        spec = props.get(field)
        if not spec:
            problems.append(f"{field} is not a field in assets/actuals.schema.json")
            continue
        if "enum" in spec and value not in spec["enum"]:
            problems.append(f"{field}: '{value}' is not one of {spec['enum']}")
        if spec.get("type") == "number" and not isinstance(value, (int, float)):
            problems.append(f"{field}: expected a number, got {type(value).__name__}")
    return problems


def main():
    ap = argparse.ArgumentParser(
        description="Attach real spent hours to a ledger entry.",
        epilog="Exit codes: 0 attached, 1 refused, 2 unreadable input.",
    )
    ap.add_argument("--entry", required=True, help="ledger entry JSON to attach actuals to")
    ap.add_argument("--from-export", help="time-tracking export (csv, tsv or xlsx)")
    ap.add_argument("--total", type=float, help="a single delivery-hours total, when no export exists")
    ap.add_argument("--exclude-hours", type=float, default=0.0,
                    help="hours logged that are not delivery effort")
    ap.add_argument("--exclude-why", help="required whenever --exclude-hours is non-zero")
    ap.add_argument("--scope", required=True, choices=["as_estimated", "reduced", "expanded", "unknown"],
                    help="whether what shipped matches what was priced")
    ap.add_argument("--scope-note", help="required unless scope is as_estimated")
    ap.add_argument("--features-delivered", nargs="*", help="feature ids actually delivered, when scope changed")
    ap.add_argument("--source", required=True, help="where these numbers came from")
    ap.add_argument("--confidence", default="measured", choices=["measured", "reconstructed", "estimated"])
    ap.add_argument("--captured", help="ISO date recorded (default: today)")
    ap.add_argument("--team-profile", help="the team that actually did the work, if it differed")
    ap.add_argument("--notes")
    args = ap.parse_args()

    if not args.from_export and args.total is None:
        ap.error("one of --from-export or --total is required")
    if args.exclude_hours and not (args.exclude_why or "").strip():
        print(json.dumps({"ok": False, "error": "--exclude-why is required with --exclude-hours; an "
                                                "exclusion nobody can interrogate is a thumb on the scale"},
                         indent=2))
        return 1
    if args.scope != "as_estimated" and not (args.scope_note or "").strip():
        print(json.dumps({"ok": False, "error": f"--scope-note is required when scope is '{args.scope}'"},
                         indent=2))
        return 1

    path = Path(args.entry)
    try:
        entry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 2

    if args.from_export:
        agg = aggregate(read_rows(Path(args.from_export)))
        delivery = round(agg["total"] - args.exclude_hours, 2)
        granularity = ("feature" if agg["by_feature"] else "phase" if agg["by_phase"] else "project")
    else:
        agg = {"by_phase": {}, "by_feature": {}, "by_role": {}, "unmapped": []}
        delivery = round(args.total - args.exclude_hours, 2)
        granularity = "project"

    from datetime import date
    actuals = {
        "granularity": granularity,
        "delivery_hours": delivery,
        "scope_delivered": args.scope,
        "source": args.source,
        "confidence": args.confidence,
        "captured": args.captured or date.today().isoformat(),
    }
    for key, value in (("excluded_hours", args.exclude_hours), ("excluded_why", args.exclude_why),
                       ("scope_note", args.scope_note), ("features_delivered", args.features_delivered),
                       ("team_profile", args.team_profile), ("notes", args.notes),
                       ("by_phase", agg["by_phase"]), ("by_feature", agg["by_feature"]),
                       ("by_role", agg["by_role"])):
        if value:
            actuals[key] = value

    problems = validate(actuals)
    if problems:
        print(json.dumps({"ok": False, "error": "the actuals do not match the schema",
                          "problems": problems}, indent=2))
        return 1

    entry.setdefault("ledger", {})["actuals"] = actuals
    entry["ledger"]["status"] = "delivered"
    path.write_text(json.dumps(entry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(json.dumps({"ok": True, "entry": str(path), "granularity": granularity,
                      "delivery_hours": delivery,
                      "unmapped_phases": agg["unmapped"],
                      "note": ("Unmapped activity names were counted in the total but not attributed "
                               "to a phase." if agg["unmapped"] else "")}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
