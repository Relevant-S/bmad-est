#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Render a Feature Inventory into the human and sales views.

feature-inventory.json is the source of truth; the .md and .csv are projections
regenerated on demand rather than maintained. Features render as sections rather than
table rows because verbatim citations carry pipes, newlines and non-Latin text that a
markdown table destroys — and destroying the quote destroys the traceability.
"""

import argparse
import csv
import json
import sys
from pathlib import Path

AXES = ["size_band", "compressibility", "review_tier", "clarity", "novelty"]
TIER_MARK = {"routine": "", "sensitive": " ⚠ sensitive", "critical": " ⛔ critical"}
SCOPE_MARK = {"outside_agreed_scope": " · outside agreed scope",
              "no_agreed_scope_defined": " · no agreed scope defined"}


def tag(feature, axis, field="value"):
    return (feature.get("tags", {}).get(axis) or {}).get(field, "")


def render_markdown(inv):
    src_by_id = {s["id"]: s for s in inv.get("sources", [])}
    features = inv.get("features", [])
    out = [f"# Feature Inventory — {inv.get('project', 'untitled')}", ""]
    out.append(
        f"Generated {inv.get('generated', '')} · schema {inv.get('schema_version', '')} · "
        f"granularity: {inv.get('granularity', 'unspecified')}"
    )
    epics = inv.get("epics") or []
    implicit = inv.get("implicit_scope") or []
    tasks = sum(len(f.get("tasks") or []) for f in features)
    # Story count, epic count and source-row count on one line, because the ratio between them
    # is the fastest way to see whether the workbook was grouped or transliterated.
    counts = [f"**{len(features)} stories**"]
    if epics:
        counts.append(f"{len(epics)} epics")
    if tasks:
        counts.append(f"{tasks} source rows")
    if implicit:
        counts.append(f"{len(implicit)} implicit")
    counts += [f"{len(inv.get('not_scope', []))} passages excluded from scope",
               f"{len(inv.get('conflicts', []))} conflicts"]
    out += ["", " · ".join(counts), ""]

    if epics:
        out += ["## Epics", "", "| id | epic | stories | from |", "| --- | --- | ---: | --- |"]
        for epic in epics:
            n = sum(1 for f in features if f.get("epic_id") == epic.get("id"))
            origin = epic.get("origin", "")
            if origin == "synthesised" and epic.get("why"):
                origin += f" — {epic['why']}"
            out.append(f"| {epic.get('id')} | {epic.get('name')} | {n} | {origin} |")
        out.append("")

    out += ["## Sources", "", "| id | document | type | language | converter | coverage note |",
            "| --- | --- | --- | --- | --- | --- |"]
    for s in inv.get("sources", []):
        out.append(
            f"| {s.get('id')} | `{s.get('path')}` | {s.get('doc_type')} | {s.get('language')} "
            f"| {s.get('converter', '')} | {s.get('coverage_note', '')} |"
        )
    out.append("")

    out += ["## Stories", ""]
    for f in features + implicit:
        tier = tag(f, "review_tier")
        out.append(
            f"### {f.get('id')} — {f.get('name')}"
            f"{TIER_MARK.get(tier, '')}{SCOPE_MARK.get(f.get('scope_status'), '')}"
        )
        out += ["", f.get("description", ""), ""]

        out.append("| axis | value | why | status |")
        out.append("| --- | --- | --- | --- |")
        for axis in AXES:
            why = tag(f, axis, "why").replace("|", "\\|")
            out.append(f"| {axis} | **{tag(f, axis)}** | {why} | {tag(f, axis, 'status')} |")
        out.append("")

        triggers = (f.get("tags", {}).get("review_tier") or {}).get("triggers") or []
        if triggers:
            out.append("**Review-tier triggers:** " + ", ".join(f"“{t}”" for t in triggers))
            out.append("")

        surfaces = f.get("surfaces")
        if surfaces:
            out.append(f"**Surfaces:** {', '.join(surfaces)} — only these roles are billed to it.")
        out.append(f"**Commitment:** {f.get('commitment')}")
        if f.get("rationale"):
            out.append(f"**Why it is here, with no quote behind it:** {f['rationale']}")
        rows = f.get("tasks") or []
        if rows:
            out += ["", f"**Assembled from {len(rows)} source rows:**", ""]
            for task in rows:
                where = "; ".join(c.get("location", "") for c in task.get("citations") or [])
                out.append(f"- `{task.get('id')}` {task.get('name')} — {where}")
        if f.get("scope_status") == "outside_agreed_scope":
            out.append("**Outside the agreed scope** — estimated separately, not folded into the agreed number.")
        deps = f.get("depends_on") or []
        if deps:
            rendered = ", ".join(
                f"{d.get('feature_id')}{' *(inferred)*' if d.get('inferred') else ''}" for d in deps
            )
            out.append(f"**Depends on:** {rendered}")
        out.append("")

        out.append("**Source:**")
        out.append("")
        for cit in f.get("citations", []):
            sid = cit.get("source_id")
            doc = Path(src_by_id.get(sid, {}).get("path", sid)).name
            out.append(f"- `{sid}` {doc} — {cit.get('location')}")
            out.append(f"  > {cit.get('quote', '').strip()}")
            if cit.get("quote_original"):
                out.append(f"  > *({cit.get('quote_language', 'original')})* {cit['quote_original'].strip()}")
        out.append("")

        for q in f.get("open_questions") or []:
            out.append(f"- ❓ {q}")
        if f.get("open_questions"):
            out.append("")

    if inv.get("not_scope"):
        out += ["## Not treated as scope", "",
                "Source content that did not become a feature, and why.", "",
                "| source | location | reason | text |", "| --- | --- | --- | --- |"]
        for ns in inv["not_scope"]:
            quote = ns.get("quote", "").replace("|", "\\|").replace("\n", " ")
            quote = quote[:200] + ("…" if len(quote) > 200 else "")
            out.append(f"| {ns.get('source_id')} | {ns.get('location')} | {ns.get('reason')} | {quote} |")
        out.append("")

    if inv.get("conflicts"):
        out += ["## Conflicts between sources", ""]
        for c in inv["conflicts"]:
            out.append(f"- **{c.get('topic')}** ({', '.join(c.get('source_ids', []))}) — {c.get('detail')}")
        out.append("")

    if inv.get("assumptions"):
        out += ["## Assumptions", ""] + [f"- {a}" for a in inv["assumptions"]] + [""]

    return "\n".join(out)


def render_csv(inv, target):
    src_by_id = {s["id"]: s for s in inv.get("sources", [])}
    columns = [
        "id", "name", "description", "epic_id", "surfaces", "tasks", "origin",
        "commitment", "scope_status",
        "size_band", "compressibility", "compressibility_why",
        "review_tier", "review_tier_why", "clarity", "novelty",
        "depends_on", "tag_status", "sources", "locations",
        "primary_quote", "open_questions",
    ]
    with open(target, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        for f in list(inv.get("features", [])) + list(inv.get("implicit_scope") or []):
            citations = f.get("citations", [])
            statuses = {tag(f, a, "status") for a in AXES}
            writer.writerow({
                "id": f.get("id"),
                "name": f.get("name"),
                "description": f.get("description"),
                "epic_id": f.get("epic_id") or "",
                "surfaces": "; ".join(f.get("surfaces") or []),
                "tasks": "; ".join(t.get("id", "") for t in f.get("tasks") or []),
                "origin": f.get("origin") or ("implicit" if f.get("rationale") else "extracted"),
                "commitment": f.get("commitment"),
                "scope_status": f.get("scope_status") or "in_agreed_scope",
                "size_band": tag(f, "size_band"),
                "compressibility": tag(f, "compressibility"),
                "compressibility_why": tag(f, "compressibility", "why"),
                "review_tier": tag(f, "review_tier"),
                "review_tier_why": tag(f, "review_tier", "why"),
                "clarity": tag(f, "clarity"),
                "novelty": tag(f, "novelty"),
                "depends_on": "; ".join(d.get("feature_id", "") for d in f.get("depends_on", [])),
                "tag_status": "confirmed" if statuses == {"confirmed"} else "; ".join(sorted(s for s in statuses if s)),
                "sources": "; ".join(
                    Path(src_by_id.get(c.get("source_id"), {}).get("path", c.get("source_id", ""))).name
                    for c in citations
                ),
                "locations": "; ".join(c.get("location", "") for c in citations),
                "primary_quote": citations[0].get("quote", "") if citations else "",
                "open_questions": "; ".join(f.get("open_questions") or []),
            })


def main():
    ap = argparse.ArgumentParser(
        description="Render feature-inventory.json into feature-inventory.md and feature-inventory.csv.",
        epilog="Exit codes: 0 rendered, 2 unreadable input.",
    )
    ap.add_argument("inventory", help="path to feature-inventory.json")
    ap.add_argument("--out-dir", help="directory for the rendered files (default: alongside the inventory)")
    ap.add_argument("--formats", default="md,csv", help="comma-separated subset of md,csv")
    args = ap.parse_args()

    path = Path(args.inventory)
    try:
        inv = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": f"cannot read {path}: {exc}"}))
        return 2

    out_dir = Path(args.out_dir) if args.out_dir else path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    formats = {f.strip() for f in args.formats.split(",") if f.strip()}
    written = []

    if "md" in formats:
        target = out_dir / "feature-inventory.md"
        target.write_text(render_markdown(inv), encoding="utf-8")
        written.append(str(target))
    if "csv" in formats:
        target = out_dir / "feature-inventory.csv"
        render_csv(inv, target)
        written.append(str(target))

    print(json.dumps({"ok": True, "written": written, "features": len(inv.get("features", []))}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
