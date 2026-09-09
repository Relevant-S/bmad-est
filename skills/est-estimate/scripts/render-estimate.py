#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["openpyxl>=3.1"]
# ///
"""Render estimate.json into the human, sales and negotiation views.

estimate.json is the source of truth; these are projections regenerated on demand.

**No output reports a grand total.** A single summed number is meaningless when the work
splits across roles, and this one could not even be reconciled: adding up the story rows gave
1,752 h against a headline of 2,414 h, because planning, planning-review, QA and overhead
touch no story. The role table is the headline now, each role carrying its own range and
saying how much of it is story work and how much is project-level. `total_hours` stays in
estimate.json — calibration compares it against delivered actuals — and nothing renders it.

**Nothing is a point value.** Every story and every role carries low/likely/high, because how
well-specified the work is only becomes visible as width.

**The tabular outputs extend est-scope-extract's, never replace them.** The story and task
columns come from `render-inventory.py`'s own row builders, so a column added there cannot be
dropped here.

The HTML is the interesting one: it carries the per-feature components and the cost
model's own coefficients, so unticking a feature recomputes the whole estimate in the
browser — including the project overheads that scale with what is left. A presale lead
can drive it in a client call and cut scope against a live number. It also self-checks
its own arithmetic against the file it was rendered from.
"""

import argparse
import csv
import importlib.util
import json
import sys
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "assets" / "report-template.html"

AXES = ("size_band", "compressibility", "review_tier", "clarity", "novelty")


def inventory_renderer():
    """est-scope-extract's row builders, so the estimate sheets are the inventory sheets plus
    columns. Imported rather than reimplemented, the way classification-merge.py imports the
    diff's matcher: a second column list is a second thing to forget to update."""
    global _INV
    try:
        return _INV
    except NameError:
        pass
    path = (Path(__file__).resolve().parents[2]
            / "est-scope-extract" / "scripts" / "render-inventory.py")
    spec = importlib.util.spec_from_file_location("render_inventory", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _INV = mod
    return mod


def rng(value):
    """A three-point value as low/likely/high, whatever shape it arrives in."""
    if isinstance(value, dict):
        return value.get("low", 0.0), value.get("likely", 0.0), value.get("high", 0.0)
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return tuple(value)
    return (value, value, value)


def band(value, fmt="{:,.1f}"):
    lo, likely, hi = rng(value)
    return f"{fmt.format(lo)} – {fmt.format(likely)} – {fmt.format(hi)}"


def role_names(est):
    return sorted(est.get("by_role") or {})


def load_inventory(est, override=None):
    """The inventory this estimate was priced from, if it can still be found."""
    path = Path(override) if override else None
    if path is None and est.get("inventory"):
        candidate = Path(est["inventory"])
        for guess in ([candidate] if candidate.is_absolute() else
                      [Path.cwd() / candidate, candidate]):
            if guess.exists():
                path = guess
                break
    if path is None or not path.exists():
        return None, (f"inventory not found at {override or est.get('inventory')!r} — the story "
                      f"and task columns est-scope-extract wrote are not in these outputs. Pass "
                      f"--inventory to point at it.")
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"inventory at {path} could not be read: {exc}"



def engine():
    """est-estimate's own engine, for the facts a renderer must not re-derive.

    `calibrated` gates a claim made to a client, so it has exactly one definition and it lives
    beside the pricing rather than as a prose-prefix match repeated here.
    """
    global _ENGINE
    try:
        return _ENGINE
    except NameError:
        pass
    path = Path(__file__).resolve().parent / "estimate.py"
    spec = importlib.util.spec_from_file_location("estimate", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _ENGINE = mod
    return mod


def role_table(est, indent=""):
    """The estimate's headline. Every role, as a range, with the arithmetic on the page."""
    rows = [f"{indent}| Role | Low | Likely | High | On stories | Project-level |",
            f"{indent}| --- | ---: | ---: | ---: | ---: | ---: |"]
    for role, row in sorted((est.get("by_role") or {}).items(),
                            key=lambda kv: -rng(kv[1])[1]):
        lo, likely, hi = rng(row)
        on_stories = row.get("on_stories") if isinstance(row, dict) else None
        project = row.get("project_level") if isinstance(row, dict) else None
        rows.append(
            f"{indent}| {role} | {lo:,.0f} | {likely:,.0f} | {hi:,.0f} | "
            f"{'—' if not on_stories else format(on_stories, ',.0f')} | "
            f"{'—' if not project else format(project, ',.0f')} |")
    return rows


def markdown(est, show_manual_baseline=False):
    out = [f"# Estimate — {est.get('project', 'untitled')}", ""]
    out.append(f"*{est['granularity']} · {est['mode']} mode · generated {est.get('generated') or 'n/a'}*")
    out += ["", "## Hours by role", ""] + role_table(est) + [""]
    out.append("Each role is a range, not a figure. There is deliberately no single project "
               "total: summing across roles answers no question anyone asks, and the roles are "
               "what gets staffed, quoted and argued about. *On stories* is work that traces to "
               "a line of the client's document; *project-level* is planning, review of "
               "planning, QA and overhead, which the whole project pays regardless of which "
               "story survives.")
    out.append("")

    conf = est["confidence"]
    out.append(f"> {conf['why']}")
    out.append("")

    if not engine().is_calibrated(est.get("cost_model_snapshot") or {}):
        out += ["> **Uncalibrated model.** These coefficients are reasoned starting points, not "
                "measurements from delivered projects. The shape of the estimate is defensible; "
                "the absolute figures are a hypothesis until reconciled against real actuals.", ""]

    if len(est.get("scope_split", {})) > 1:
        out += ["## Agreed scope vs additions", "",
                "| Scope | Features | Share of this project | Cost on its own |",
                "| --- | ---: | ---: | ---: |"]
        for name, row in est["scope_split"].items():
            if name.startswith("_"):
                continue
            out.append(f"| {name.replace('_', ' ')} | {row['features']} | "
                       f"{row['apportioned_hours']:,.0f} | {row['standalone_hours']:,.0f} |")
        out += ["", "Additional scope is priced separately and never folded into the agreed number.",
                "", f"> {est['scope_split']['_reading_these']}", ""]

    out += ["## By BMad phase", "", "| Phase | Hours | ± |", "| --- | ---: | ---: |"]
    for phase, row in sorted(est["by_phase"].items(), key=lambda kv: -kv[1]["hours"]):
        out.append(f"| {phase.replace('-', ' ')} | {row['hours']:,.0f} | {row['sd']:,.0f} |")

    anchor = est["project_components"].get("planning_review")
    if anchor:
        out += ["", f"Planning review — {anchor['hours']:,.0f}h ± {anchor['sd']:,.0f} — carries the "
                "tightest band in the estimate. This company reviews 100% of planning artefacts on "
                "every project, so it is the most predictable component and the part of the number "
                "that can be defended hardest.", ""]

    risky = [f for f in est["features"]
             if f["tags"]["compressibility"] == "low"
             and f["tags"]["review_tier"] in ("sensitive", "critical")]
    if risky:
        out += ["", "## Where the risk is", "",
                f"{len(risky)} feature(s) are hard to build *and* expensive to verify — the quadrant "
                "where BMad's advantage is smallest and the real uncertainty is widest:", ""]
        out += [f"- **{f['id']}** {f['name']} — {f['tags']['compressibility']} compressibility, "
                f"{f['tags']['review_tier']} review, {band(f.get('range') or f['hours'], '{:,.0f}')}h"
                for f in risky]

    if est.get("narrowing_questions"):
        out += ["", "## Answer these to tighten the range", "",
                "| Question | Band reduction |", "| --- | ---: |"]
        out[-2] = "| Question | Assuming | Band reduction |"
        out[-1] = "| --- | --- | ---: |"
        for q in est["narrowing_questions"]:
            out.append(f"| {q['question']} | {q.get('assumes', '')} | "
                       f"−{q['band_reduction_hours']:,.0f}h ({q['band_reduction_pct']}%) |")

    if est.get("duration"):
        d = est["duration"]
        out += ["", "## Calendar duration — derived, not a commitment", "",
                f"**{d['weeks']} weeks.** {d['basis']}", ""]

    # Role columns are the point of the table, not a decoration: "9h" invites a haggle,
    # "9h = dev 6.1, ba 1.5, ux 1.4" invites a conversation about who is doing what. Each one
    # is a range for the same reason the total is: a point value hides how well-specified
    # the work is, which is the signal the reader is actually after.
    roles = sorted({r for f in est["features"] for r in (f.get("by_role") or {})})
    out += ["", "## Features", "",
            "| ID | Feature | Size | Compress | Review | Clarity | Low | Likely | High | "
            + "".join(f"{r} | " for r in roles) + "Source |",
            "| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | "
            + "---: | " * len(roles) + "--- |"]
    for f in est["features"]:
        cites = "; ".join(f"{c['source_id']} {c['location']}" for c in f["citations"]) or "—"
        scope = {"outside_agreed_scope": " *(outside agreed scope)*",
                 "standing_work": " *(standing work — every project pays it)*",
                 }.get(f.get("scope_status"), "")
        split = f.get("by_role") or {}
        cells = ""
        for r in roles:
            if not split.get(r):
                cells += "— | "
                continue
            lo, likely, hi = rng(split[r])
            cells += f"{lo:,.1f}–{likely:,.1f}–{hi:,.1f} | "
        # Standing work carries its own hours rather than a size band, so the column is honestly
        # empty for it instead of borrowing a label that no longer prices anything.
        size = f["tags"].get("size_band") or "—"
        lo, likely, hi = rng(f.get("range") or f["hours"])
        out.append(f"| {f['id']} | {f['name']}{scope} | {size} | "
                   f"{f['tags']['compressibility']} | {f['tags']['review_tier']} | "
                   f"{f['tags']['clarity']} | {lo:,.1f} | {likely:,.1f} | {hi:,.1f} | "
                   f"{cells}{cites} |")

    out += ["", "## Assumptions", ""] + [f"- {a}" for a in est["assumptions"]]

    if show_manual_baseline:
        me = est["manual_equivalent"]
        out += ["", "## Build compression (internal only)", "",
                f"Story work by hand {me['manual_hours']:,.0f}h → this estimate's story work "
                f"{me['story_hours']:,.0f}h, a **{me['story_compression']}× compression on story "
                f"work**. Project components are outside both figures.",
                "", me["why"]]

    findings = est["traceability"]["findings"]
    out += ["", "## Traceability", "",
            f"{est['traceability']['features_priced']} of "
            f"{est['traceability']['features_in_inventory']} inventory features priced."]
    out += [""] + [f"- ⚠ {f}" for f in findings] if findings else \
           ["", "Every feature is priced and every priced feature cites a source."]

    return "\n".join(out) + "\n"


def brief(est):
    """The distillate a conversational agent loads to explain and defend the number.

    estimate.json is the ledger payload: it carries the whole cost-model snapshot and a
    three-point interval for every component, which is what calibration needs and what a
    conversation does not. This keeps the chain a human actually asks about — hours, the
    tag that drove them, the reason for that tag, and the sentence in the client's own
    document behind it — and drops everything else.
    """
    def dominant(feature):
        return max(feature["component_hours"], key=feature["component_hours"].get)

    return {
        "project": est.get("project"),
        "generated": est.get("generated"),
        "total_hours": est["total_hours"],
        "confidence": {"input_completeness": est["confidence"]["input_completeness"],
                       "why": est["confidence"]["why"]},
        "calibrated": engine().is_calibrated(est.get("cost_model_snapshot") or {}),
        "inputs": est.get("inputs", {}),
        "scope_split": {k: v for k, v in est.get("scope_split", {}).items()
                        if not k.startswith("_")},
        "by_phase": est["by_phase"],
        "by_role": est["by_role"],
        "assumptions": est["assumptions"],
        "narrowing_questions": est.get("narrowing_questions", []),
        "features": [{
            "id": f["id"],
            "name": f["name"],
            "hours": f["hours"],
            "range": f.get("range") or {"low": f["hours"], "likely": f["hours"],
                                        "high": f["hours"]},
            "by_role": f.get("by_role") or {},
            "scope_status": f.get("scope_status") or "in_agreed_scope",
            "origin": f.get("origin") or "extracted",
            "dominant_component": dominant(f),
            "why": {axis: {"value": f["tags"][axis], "why": (f.get("tag_why") or {}).get(axis),
                           "status": (f.get("tag_status") or {}).get(axis)}
                    for axis in ("size_band", "compressibility", "review_tier", "clarity", "novelty")},
            "source": ({"location": f["citations"][0].get("location"),
                        "quote": f["citations"][0].get("quote")} if f["citations"] else None),
        } for f in est["features"]],
    }


def estimate_columns(est):
    """The columns the estimate adds on top of whatever the inventory already carried."""
    cols = ["hours", "hours_low", "hours_likely", "hours_high", "sd",
            *AXES, "build", "spec", "review", "rework"]
    for role in role_names(est):
        cols += [f"{role}_low", f"{role}_likely", f"{role}_high"]
    return cols


def estimate_cells(f, est):
    """One story's priced columns. Every figure that is a range is written as three."""
    lo, likely, hi = rng(f.get("range") or f["hours"])
    row = {"hours": f["hours"], "hours_low": lo, "hours_likely": likely, "hours_high": hi,
           "sd": f.get("sd"),
           **{axis: f["tags"].get(axis) for axis in AXES},
           **{k: v for k, v in (f.get("component_hours") or {}).items()}}
    split = f.get("by_role") or {}
    for role in role_names(est):
        r_lo, r_likely, r_hi = rng(split.get(role, 0.0))
        row[f"{role}_low"] = round(r_lo, 2)
        row[f"{role}_likely"] = round(r_likely, 2)
        row[f"{role}_high"] = round(r_hi, 2)
    return row


def tabular(est, inventory=None):
    """The Stories and Tasks tables, as (columns, rows) each.

    Stories start as est-scope-extract's own story rows — description, epic name, surfaces,
    task ids, open questions, quotes, all of it — and the priced columns are appended. That is
    why no inventory column can be dropped here: they are not re-listed, they are reused.
    Without the inventory the estimate still renders, with its own columns only, and the
    caller is told.
    """
    inv_mod = inventory_renderer()
    priced = {f["id"]: f for f in est["features"]}

    if inventory:
        links = inv_mod.Links()
        story_rows = inv_mod.story_rows(inventory, links)
        task_rows = inv_mod.task_rows(inventory, links)
        story_columns = list(inv_mod.STORY_COLUMNS)
        task_columns = list(inv_mod.TASK_COLUMNS)
        seen = {row["id"] for row in story_rows}
        # Standing work and anything else priced but absent from the inventory still has to
        # appear, or the sheet silently prices less than the estimate does.
        for fid, f in priced.items():
            if fid not in seen:
                story_rows.append({"id": fid, "name": f.get("name"),
                                   "description": f.get("description"),
                                   "epic_id": f.get("epic_id") or "",
                                   "origin": f.get("origin") or "extracted"})
    else:
        story_columns = ["id", "name", "description", "epic_id", "origin", "commitment",
                         "scope_status", "depends_on", "sources"]
        task_columns = ["task_id", "feature_id", "feature_name", "name", "text", "location"]
        story_rows = [{"id": f["id"], "name": f.get("name"),
                       "description": f.get("description"),
                       "epic_id": f.get("epic_id") or "",
                       "origin": f.get("origin") or "extracted",
                       "commitment": f.get("commitment"),
                       "scope_status": f.get("scope_status") or "in_agreed_scope",
                       "depends_on": "; ".join(f.get("depends_on") or []),
                       "sources": "; ".join(f"{c['source_id']} {c['location']}"
                                            for c in f.get("citations") or [])}
                      for f in est["features"]]
        task_rows = [{"task_id": tk.get("id"), "feature_id": f["id"],
                      "feature_name": f.get("name"), "name": tk.get("name"),
                      "text": "\n\n".join((c.get("quote") or "").strip()
                                           for c in tk.get("citations") or []),
                      "location": "; ".join(c.get("location", "")
                                            for c in tk.get("citations") or [])}
                     for f in est["features"] for tk in f.get("tasks") or []]

    added = [c for c in estimate_columns(est) if c not in story_columns]
    for row in story_rows:
        f = priced.get(row.get("id"))
        if f:
            row.update(estimate_cells(f, est))
    # Project-level lines are real hours someone pays for, so they belong in the sales sheet.
    # They carry no story columns, and no grand total row follows them.
    for name, comp in (est.get("project_components") or {}).items():
        row = {"id": "—", "name": f"[project] {name.replace('_', ' ')}",
               "scope_status": "project-wide", "origin": "project",
               "hours": comp["hours"], "sd": comp["sd"]}
        lo, likely, hi = rng(comp.get("range") or comp["hours"])
        row.update({"hours_low": lo, "hours_likely": likely, "hours_high": hi})
        for role, split in (comp.get("by_role") or {}).items():
            r_lo, r_likely, r_hi = rng(split)
            row[f"{role}_low"] = r_lo
            row[f"{role}_likely"] = r_likely
            row[f"{role}_high"] = r_hi
        story_rows.append(row)

    return (story_columns + added, story_rows), (task_columns, task_rows)


def write_csv(est, target, inventory=None):
    (columns, rows), _ = tabular(est, inventory)
    with open(target, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_tasks_csv(est, target, inventory=None):
    _, (columns, rows) = tabular(est, inventory)
    with open(target, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_xlsx(est, target, inventory=None):
    """The inventory workbook with the estimate's columns on it — same two tabs, same links."""
    inv_mod = inventory_renderer()
    (story_columns, story_rows), (task_columns, task_rows) = tabular(est, inventory)
    task_parent = "feature_id" if "feature_id" in task_columns else None
    links = inv_mod.workbook_links(story_rows, task_rows) if task_parent else []
    return inv_mod.write_workbook(
        [("Stories", story_columns, story_rows), ("Tasks", task_columns, task_rows)],
        target, links)


def write_html(est, target, options):
    payload = dict(est)
    payload["_render_options"] = options
    template = TEMPLATE.read_text(encoding="utf-8")
    # </script> inside embedded JSON would close the tag early and break the page.
    blob = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    html = template.replace("__TITLE__", f"Estimate — {est.get('project', 'untitled')}")
    html = html.replace("__ESTIMATE_JSON__", blob)
    Path(target).write_text(html, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(
        description="Render estimate.json into markdown, CSV and an interactive HTML report.",
        epilog="Exit codes: 0 rendered, 2 unreadable input.",
    )
    ap.add_argument("estimate", help="path to estimate.json")
    ap.add_argument("--out-dir", help="directory for rendered files (default: alongside the estimate)")
    ap.add_argument("--formats", default="md,csv,xlsx,html,brief",
                    help="comma-separated subset of md,csv,xlsx,html,brief. Members this "
                         "script does not produce are ignored, so the shared est_output_formats "
                         "value can be passed through unchanged.")
    ap.add_argument("--inventory",
                    help="path to feature-inventory.json. Defaults to the path recorded in the "
                         "estimate. The story and task columns come from it, so without it the "
                         "sheets carry the priced columns only and the render says so.")
    ap.add_argument("--show-manual-baseline", action="store_true",
                    help="include the build-compression comparison; internal output only")
    ap.add_argument("--stack", help="override; defaults to the profile recorded in the estimate")
    ap.add_argument("--qa-platform", help="override; defaults to the profile recorded in the estimate")
    ap.add_argument("--engagement", help="override; defaults to the profile recorded in the estimate")
    args = ap.parse_args()

    path = Path(args.estimate)
    try:
        est = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": f"cannot read {path}: {exc}"}, indent=2))
        return 2

    out_dir = Path(args.out_dir) if args.out_dir else path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    formats = {f.strip() for f in args.formats.split(",") if f.strip()}
    written, notes = [], []
    inventory, problem = load_inventory(est, args.inventory)
    if problem:
        notes.append(problem)

    if "md" in formats:
        target = out_dir / "estimate.md"
        target.write_text(markdown(est, args.show_manual_baseline), encoding="utf-8")
        written.append(str(target))
    if "csv" in formats:
        target = out_dir / "estimate.csv"
        write_csv(est, target, inventory)
        written.append(str(target))
        target = out_dir / "estimate.tasks.csv"
        write_tasks_csv(est, target, inventory)
        written.append(str(target))
    if "xlsx" in formats:
        target = out_dir / "estimate.xlsx"
        if write_xlsx(est, target, inventory):
            written.append(str(target))
        else:
            notes.append("xlsx skipped: openpyxl is not importable. Run this under `uv run`, "
                         "which provisions it, or drop xlsx from est_output_formats.")
    if "brief" in formats:
        target = out_dir / "estimate-brief.json"
        target.write_text(json.dumps(brief(est), indent=2, ensure_ascii=False) + "\n",
                          encoding="utf-8")
        written.append(str(target))
    if "html" in formats:
        # Take the profile from the estimate itself. Passing it separately invites the report's
        # live recompute to use different coefficients from the headline figure printed above it,
        # which is exactly the contradiction a client would find by unticking one feature.
        recorded = est.get("inputs", {})
        target = out_dir / "estimate.html"
        write_html(est, target, {
            "stack": args.stack or recorded.get("stack", "standard_saas"),
            "qa_platform": args.qa_platform or recorded.get("qa_platform", "web"),
            "engagement": args.engagement or recorded.get("engagement", "standard"),
            # Overhead is priced per person per week, so the page cannot recompute it
            # without the team size the document assumed.
            "team_size": recorded.get("team_size"),
            "show_manual_baseline": bool(args.show_manual_baseline),
        })
        written.append(str(target))

    result = {"ok": True, "written": written,
              "by_role": {r: rng(v)[1] for r, v in (est.get("by_role") or {}).items()}}
    if notes:
        result["notes"] = notes
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
