#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Render estimate.json into the human, sales and negotiation views.

estimate.json is the source of truth; these are projections regenerated on demand.

The HTML is the interesting one: it carries the per-feature components and the cost
model's own coefficients, so unticking a feature recomputes the whole estimate in the
browser — including the project overheads that scale with what is left. A presale lead
can drive it in a client call and cut scope against a live number. It also self-checks
its own arithmetic against the file it was rendered from.
"""

import argparse
import csv
import json
import sys
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "assets" / "report-template.html"


def markdown(est, show_manual_baseline=False):
    total = est["total_hours"]
    out = [f"# Estimate — {est.get('project', 'untitled')}", ""]
    out.append(f"*{est['granularity']} · {est['mode']} mode · generated {est.get('generated') or 'n/a'}*")
    out += ["", f"## {total['likely']:,.0f} hours  ·  range {total['low']:,.0f} – {total['high']:,.0f}", ""]

    conf = est["confidence"]
    out.append(f"> {conf['why']}")
    out.append("")

    if (est.get("cost_model_snapshot", {}).get("calibration_status", "")).startswith("UNCALIBRATED"):
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

    out += ["## By role", "", "| Role | Hours |", "| --- | ---: |"]
    for role, hours in sorted(est["by_role"].items(), key=lambda kv: -kv[1]):
        out.append(f"| {role} | {hours:,.0f} |")

    risky = [f for f in est["features"]
             if f["tags"]["compressibility"] == "low"
             and f["tags"]["review_tier"] in ("sensitive", "critical")]
    if risky:
        out += ["", "## Where the risk is", "",
                f"{len(risky)} feature(s) are hard to build *and* expensive to verify — the quadrant "
                "where BMad's advantage is smallest and the real uncertainty is widest:", ""]
        out += [f"- **{f['id']}** {f['name']} — {f['tags']['compressibility']} compressibility, "
                f"{f['tags']['review_tier']} review, {f['hours']:,.0f}h" for f in risky]

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

    out += ["", "## Features", "",
            "| ID | Feature | Size | Compress | Review | Clarity | Hours | Source |",
            "| --- | --- | --- | --- | --- | --- | ---: | --- |"]
    for f in est["features"]:
        cites = "; ".join(f"{c['source_id']} {c['location']}" for c in f["citations"]) or "—"
        scope = " *(outside agreed scope)*" if f.get("scope_status") not in (None, "in_agreed_scope") else ""
        out.append(f"| {f['id']} | {f['name']}{scope} | {f['tags']['size_band']} | "
                   f"{f['tags']['compressibility']} | {f['tags']['review_tier']} | "
                   f"{f['tags']['clarity']} | {f['hours']:,.0f} | {cites} |")

    out += ["", "## Assumptions", ""] + [f"- {a}" for a in est["assumptions"]]

    if show_manual_baseline:
        me = est["manual_equivalent"]
        out += ["", "## Build compression (internal only)", "",
                f"Manual build effort {me['build_hours']:,.0f}h → BMad build effort "
                f"{me['bmad_build_hours']:,.0f}h, a **{me['build_compression']}× compression on build**.",
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
        "calibrated": not (est.get("cost_model_snapshot", {})
                           .get("calibration_status", "")).startswith("UNCALIBRATED"),
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
            "scope_status": f.get("scope_status") or "in_agreed_scope",
            "dominant_component": dominant(f),
            "why": {axis: {"value": f["tags"][axis], "why": (f.get("tag_why") or {}).get(axis),
                           "status": (f.get("tag_status") or {}).get(axis)}
                    for axis in ("size_band", "compressibility", "review_tier", "clarity", "novelty")},
            "source": ({"location": f["citations"][0].get("location"),
                        "quote": f["citations"][0].get("quote")} if f["citations"] else None),
        } for f in est["features"]],
    }


def write_csv(est, target):
    columns = ["id", "name", "scope_status", "commitment", "size_band", "compressibility",
               "review_tier", "clarity", "novelty", "hours", "sd", "build", "spec", "review",
               "rework", "depends_on", "sources"]
    with open(target, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        for f in est["features"]:
            writer.writerow({
                "id": f["id"], "name": f["name"],
                "scope_status": f.get("scope_status") or "in_agreed_scope",
                "commitment": f.get("commitment"),
                **{axis: f["tags"][axis] for axis in
                   ("size_band", "compressibility", "review_tier", "clarity", "novelty")},
                "hours": f["hours"], "sd": f["sd"],
                **{k: v for k, v in f["component_hours"].items()},
                "depends_on": "; ".join(f.get("depends_on") or []),
                "sources": "; ".join(f"{c['source_id']} {c['location']}" for c in f["citations"]),
            })
        # Project-level lines belong in the sales sheet too: they are real hours someone pays for.
        for name, row in est["project_components"].items():
            writer.writerow({"id": "—", "name": f"[project] {name.replace('_', ' ')}",
                             "scope_status": "project-wide", "hours": row["hours"], "sd": row["sd"]})
        writer.writerow({"id": "—", "name": "[total] likely", "hours": est["total_hours"]["likely"]})
        writer.writerow({"id": "—", "name": "[total] low", "hours": est["total_hours"]["low"]})
        writer.writerow({"id": "—", "name": "[total] high", "hours": est["total_hours"]["high"]})


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
    ap.add_argument("--formats", default="md,csv,html,brief",
                    help="comma-separated subset of md,csv,html,brief")
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
    written = []

    if "md" in formats:
        target = out_dir / "estimate.md"
        target.write_text(markdown(est, args.show_manual_baseline), encoding="utf-8")
        written.append(str(target))
    if "csv" in formats:
        target = out_dir / "estimate.csv"
        write_csv(est, target)
        written.append(str(target))
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
        })
        written.append(str(target))

    print(json.dumps({"ok": True, "written": written,
                      "total_hours": est["total_hours"]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
