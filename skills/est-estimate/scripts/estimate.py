#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Compute a ranged, role-split, phase-decomposed estimate from a Feature Inventory.

The whole cost model lives in cost-model.json — no coefficient is hardcoded here. This
script does the arithmetic and nothing else: it decides no classification, invents no
scope, and cannot be persuaded to narrow a range.

The one modelling choice worth naming, because it is the reason the module exists:
`review_h` is a share of `manual_baseline`, never of the compressed `build_h`. Review
effort tracks the volume of output produced, not the time taken to produce it, so
compression shrinks the build and leaves the review untouched. Routine CRUD collapses;
a payments feature does not. Nothing special-cases that — it falls out of the formula.

Reads: feature-inventory.json (from est-scope-extract) + cost-model.json
Writes: estimate.json — the source of truth; render-estimate.py makes the human views.
"""

import argparse
import json
import math
import sys
from pathlib import Path

# --- three-point arithmetic -------------------------------------------------
# Every quantity is (lo, likely, hi). Intervals combine conservatively at the feature
# level; the project total then sums PERT variances, so ranges do not balloon linearly.


def tp(node, *keys):
    """Read a three-point value from the cost model."""
    for key in keys:
        node = node[key]
    return (float(node["lo"]), float(node["likely"]), float(node["hi"]))


def add(*values):
    return tuple(sum(v[i] for v in values) for i in range(3)) if values else (0.0, 0.0, 0.0)


def scale(value, factor):
    return tuple(v * factor for v in value)


def mul(a, b):
    return (a[0] * b[0], a[1] * b[1], a[2] * b[2])


def div(a, b):
    """Interval division: the smallest result pairs the smallest numerator with the
    largest divisor. Getting this backwards would quietly narrow every build estimate."""
    return (a[0] / b[2], a[1] / b[1], a[2] / b[0])


def pert(value):
    """PERT mean and standard deviation of a three-point estimate."""
    lo, likely, hi = value
    return ((lo + 4 * likely + hi) / 6.0, (hi - lo) / 6.0)


def band_half_width(components, model, completeness):
    """The half-band, from one definition used everywhere.

    Feature variance and systematic model error combine in quadrature, then the
    completeness multiplier widens the result. Any caller that re-derives this by hand
    will drift from the headline figure, which is how a sensitivity analysis ends up
    reporting the gap between two formulas instead of the value of an answer.
    """
    unc = model["uncertainty"]
    mean, sd_features = combine(components)
    sd_model = unc.get("model_risk", 0.0) * mean
    sd = math.sqrt(sd_features ** 2 + sd_model ** 2)
    multiplier = 1 + unc["completeness_multiplier"]["k"] * \
        (1 - completeness) ** unc["completeness_multiplier"]["p"]
    return mean, sd_features, sd_model, sd, multiplier, unc["z"] * sd * multiplier


def combine(components):
    """Aggregate component means and standard deviations.

    Means add. Variances add, so standard deviations combine in quadrature — which is
    why a hundred features do not produce a hundred-fold range. Treating the components
    as independent is the assumption; the correlated part of the risk is handled
    separately by the completeness multiplier, which widens the band instead.
    """
    mean = sum(pert(c)[0] for c in components)
    sd = math.sqrt(sum(pert(c)[1] ** 2 for c in components))
    return mean, sd


# --- per-feature costing ----------------------------------------------------

def price_feature(feature, model, team):
    """Cost one feature. Returns its components and the inputs that produced them."""
    tags = feature.get("tags", {})

    def value(axis):
        return (tags.get(axis) or {}).get("value")

    size, comp_class = value("size_band"), value("compressibility")
    tier, clarity, novelty = value("review_tier"), value("clarity"), value("novelty")

    manual = tp(model, "size_bands", size)
    compression = tp(model, "compressibility", comp_class)
    clarity_row = model["clarity"][clarity]
    novelty_factor = model["novelty_rework_multiplier"][novelty]["factor"]

    build = div(manual, compression)
    spec = scale(manual, clarity_row["spec_rate"] * team["spec"])
    # The load-bearing line: review scales with manual_baseline, not with build.
    review = scale(mul(manual, tp(model, "review_rate", tier)), team["review"])
    rework = scale(add(build, review),
                   clarity_row["rework_rate"] * novelty_factor * team["rework"])

    return {
        "id": feature.get("id"),
        "name": feature.get("name"),
        "scope_status": feature.get("scope_status") or "in_agreed_scope",
        "commitment": feature.get("commitment"),
        "tags": {a: value(a) for a in
                 ("size_band", "compressibility", "review_tier", "clarity", "novelty")},
        "tag_status": {a: (tags.get(a) or {}).get("status") for a in
                       ("size_band", "compressibility", "review_tier", "clarity", "novelty")},
        "tag_why": {a: (tags.get(a) or {}).get("why") for a in
                    ("size_band", "compressibility", "review_tier", "clarity", "novelty")},
        "citations": [{"source_id": c.get("source_id"), "location": c.get("location"),
                       "quote": c.get("quote")} for c in feature.get("citations", [])],
        "open_questions": feature.get("open_questions", []),
        "depends_on": [d.get("feature_id") for d in feature.get("depends_on", [])],
        "manual_baseline": manual,
        "components": {"build": build, "spec": spec, "review": review, "rework": rework},
        "total": add(build, spec, review, rework),
    }


# --- project-level components ----------------------------------------------

def plan_volume(priced, model, granularity):
    """Derive planning artefact volume from the feature set.

    Deterministic and reproducible: the same inventory always yields the same volume,
    so planning_review_h — the estimate's high-confidence anchor — never depends on
    anyone's recollection of how many stories a project like this usually has.
    """
    per_size = model["planning"]["stories_per_feature"]
    stories = sum(per_size.get(f["tags"]["size_band"], 1) for f in priced)
    epics = math.ceil(len(priced) / model["planning"]["features_per_epic"]) if priced else 0
    documents = model["planning"]["documents_by_granularity"].get(granularity, [])
    return {"epics": epics, "stories": stories, "documents": documents}


def planning_cost(volume, model, key):
    rates = model["planning"][key]
    parts = [tp(rates, doc) for doc in volume["documents"]]
    parts.append(scale(tp(rates, "per_epic"), volume["epics"]))
    parts.append(scale(tp(rates, "per_story"), volume["stories"]))
    return add(*parts)


def project_components(priced, model, granularity, options):
    volume = plan_volume(priced, model, granularity)
    manual_total = add(*[f["manual_baseline"] for f in priced]) if priced else (0.0, 0.0, 0.0)

    components = {
        "planning_agent": planning_cost(volume, model, "agent_hours"),
        "planning_review": planning_cost(volume, model, "review_hours"),
        "env_infra": tp(model, "env_infra", options["stack"]),
        "qa": mul(manual_total, tp(model, "qa", options["qa_platform"])),
    }
    feature_total = add(*[f["total"] for f in priced]) if priced else (0.0, 0.0, 0.0)
    subtotal = add(feature_total, *components.values())
    components["overhead"] = mul(subtotal, tp(model, "overhead_rate", options["engagement"]))
    return components, volume, manual_total


# --- splits ------------------------------------------------------------------

def by_role(priced, project, model):
    """Allocate every component's hours across roles, then report role means."""
    weights = model["role_weights"]
    totals = {}

    def apply(value, key):
        for role, share in weights[key].items():
            totals[role] = totals.get(role, 0.0) + pert(value)[0] * share

    for feature in priced:
        apply(feature["components"]["build"], "build")
        apply(feature["components"]["spec"], "spec")
        tier = feature["tags"]["review_tier"]
        apply(feature["components"]["review"],
              "review_routine" if tier == "routine" else "review_sensitive")
        apply(feature["components"]["rework"], "rework")
    for name, value in project.items():
        apply(value, name)
    return {role: round(hours, 1) for role, hours in sorted(totals.items())}


def by_phase(priced, project, model):
    phases, mapping = {}, model["phase_map"]

    def put(value, component):
        phase = mapping[component]
        mean, sd = pert(value)
        entry = phases.setdefault(phase, {"mean": 0.0, "variance": 0.0})
        entry["mean"] += mean
        entry["variance"] += sd ** 2

    for feature in priced:
        for component, value in feature["components"].items():
            put(value, component)
    for name, value in project.items():
        put(value, name)

    return {phase: {"hours": round(v["mean"], 1), "sd": round(math.sqrt(v["variance"]), 1)}
            for phase, v in phases.items()}


def agreed_split(priced, project, model, options):
    """Agreed and additional scope, never silently merged.

    Reports two different numbers per group, because two different questions get asked
    and answering one with the other misleads:

    - `apportioned_hours` — of this project's total, what share belongs to this scope?
      Project components are split by each side's share of manual_baseline. These sum to
      the project total, which is what an internal allocation needs.
    - `standalone_hours` — what would this scope cost on its own? A full recompute with
      only these features. Higher than the apportioned figure, because environments and
      much of the planning are paid once regardless of how much scope survives. This is
      the number a client negotiation needs: it is what they would actually pay.
    """
    groups = {"in_agreed_scope": [], "outside_agreed_scope": [], "no_agreed_scope_defined": []}
    for feature in priced:
        groups.setdefault(feature["scope_status"], []).append(feature)

    manual_by_group = {k: sum(pert(f["manual_baseline"])[0] for f in v) for k, v in groups.items()}
    manual_all = sum(manual_by_group.values()) or 1.0
    project_mean = sum(pert(v)[0] for v in project.values())

    out = {}
    for name, features in groups.items():
        if not features:
            continue
        mean, sd = combine([f["total"] for f in features])
        share = manual_by_group[name] / manual_all

        # Standalone: recompute the project components for this group alone.
        own_project, _, _ = project_components(features, model, options["granularity"], options)
        standalone_mean, _ = combine([f["total"] for f in features] + list(own_project.values()))

        out[name] = {
            "features": len(features),
            "feature_hours": round(mean, 1),
            "apportioned_project_hours": round(project_mean * share, 1),
            "apportioned_hours": round(mean + project_mean * share, 1),
            "standalone_hours": round(standalone_mean, 1),
            "sd": round(sd, 1),
        }
    total_apportioned = sum(v["apportioned_hours"] for v in out.values())
    for name, row in out.items():
        row["share_of_total_pct"] = round(100 * row["apportioned_hours"] / total_apportioned, 1) \
            if total_apportioned else 0.0
    out["_reading_these"] = ("apportioned_hours sums to the project total and answers 'what share of "
                            "this project is that scope'. standalone_hours answers 'what would that "
                            "scope cost on its own' and is higher, because environments and most "
                            "planning are paid once regardless. Quote standalone_hours to a client "
                            "deciding whether to drop scope; they will not save the apportioned figure.")
    return out


# --- dependencies and duration ----------------------------------------------

def critical_path(priced):
    """Longest dependency chain by mean feature hours. Cycles are impossible here —
    est-scope-extract's checker rejects them — but guard anyway rather than recurse forever."""
    weight = {f["id"]: pert(f["total"])[0] for f in priced}
    deps = {f["id"]: [d for d in f["depends_on"] if d in weight] for f in priced}
    memo, visiting = {}, set()

    def longest(node):
        if node in memo:
            return memo[node]
        if node in visiting:
            return (0.0, [])
        visiting.add(node)
        best = (0.0, [])
        for parent in deps.get(node, []):
            hours, chain = longest(parent)
            if hours > best[0]:
                best = (hours, chain)
        visiting.discard(node)
        memo[node] = (best[0] + weight[node], best[1] + [node])
        return memo[node]

    if not priced:
        return {"hours": 0.0, "chain": []}
    hours, chain = max((longest(f["id"]) for f in priced), key=lambda r: r[0])
    return {"hours": round(hours, 1), "chain": chain}


def duration(priced, project, model, path, team_size):
    """Derived calendar duration. Secondary to hours and labelled as such everywhere."""
    cal = model["calendar"]
    people = min(team_size or cal["max_useful_parallelism"], cal["max_useful_parallelism"])
    feature_hours = sum(pert(f["total"])[0] for f in priced)
    # Planning is a small-group serial prefix; it does not parallelise across a big team.
    planning = pert(project["planning_agent"])[0] + pert(project["planning_review"])[0]
    delivery = max(path["hours"], feature_hours / people) if people else feature_hours
    weeks = (planning / min(people, 2) + delivery) / cal["hours_per_person_week"]
    return {
        "weeks": round(weeks, 1),
        "assumed_team_size": people,
        "critical_path_hours": path["hours"],
        "parallelism_ceiling": round(feature_hours / path["hours"], 1) if path["hours"] else None,
        "basis": (f"{people} people at {cal['hours_per_person_week']}h/week, planning treated as a "
                  f"serial prefix. Derived from hours — not a commitment, and it moves with team shape."),
    }


# --- sensitivity: which questions would narrow the range most ----------------

def narrowing_questions(priced, project, model, options, baseline_band, limit=8):
    """What each unanswered question is worth, in band width.

    Re-prices the whole estimate with one uncertainty removed at a time and reports the
    band reduction. That turns "we need more detail" into a ranked, costed agenda —
    and on a thin brief it is worth more to a presale lead than the number itself.
    """
    def band_with(mutate):
        clone = json.loads(json.dumps([f["_raw"] for f in priced]))
        for feature in clone:
            mutate(feature)
        repriced = [price_feature(f, model, options["team"]) for f in clone]
        components, _, _ = project_components(repriced, model, options["granularity"], options)
        *_, half = band_half_width([f["total"] for f in repriced] + list(components.values()),
                                   model, options["input_completeness"])
        return 2 * half

    candidates = []
    for feature in priced:
        fid, name = feature["id"], feature["name"]
        if feature["tags"]["clarity"] != "high":
            candidates.append((
                f"Get acceptance criteria for '{name}' ({fid})",
                "acceptance criteria are supplied, raising clarity to high",
                lambda f, fid=fid: f["tags"]["clarity"].update({"value": "high"})
                if f["id"] == fid else None,
            ))
        if feature["tags"]["size_band"] == "XL":
            candidates.append((
                f"Break '{name}' ({fid}) into its parts — XL hides too much variance to price",
                "it decomposes into parts no larger than L",
                lambda f, fid=fid: f["tags"]["size_band"].update({"value": "L"})
                if f["id"] == fid else None,
            ))
        if feature["tag_status"].get("review_tier") == "inferred" and \
                feature["tags"]["review_tier"] in ("sensitive", "critical"):
            candidates.append((
                f"Confirm whether '{name}' ({fid}) really touches money, personal data or auth",
                "it comes back routine — if the tier is confirmed instead, the band does not narrow",
                lambda f, fid=fid: f["tags"]["review_tier"].update({"value": "routine"})
                if f["id"] == fid else None,
            ))

    scored = []
    for question, assumed, mutate in candidates:
        narrowed = band_with(mutate)
        reduction = baseline_band - narrowed
        if reduction > 0:
            scored.append({
                "question": question,
                "band_reduction_hours": round(reduction, 1),
                "band_reduction_pct": round(100 * reduction / baseline_band, 1) if baseline_band else 0,
                "assumes": assumed,
            })
    scored.sort(key=lambda s: -s["band_reduction_hours"])
    return scored[:limit]


# --- traceability -------------------------------------------------------------

def traceability(inventory, priced):
    """Every hour traces to a feature; every feature traces to a citation.

    Asserted everywhere in this module, so it is checked rather than trusted.
    """
    inventory_ids = [f.get("id") for f in inventory.get("features", [])]
    priced_ids = [f["id"] for f in priced]
    findings = []
    for fid in inventory_ids:
        if fid not in priced_ids:
            findings.append(f"{fid}: in the inventory but not priced — every feature must be costed or explicitly excluded")
    for feature in priced:
        if not feature["citations"]:
            findings.append(f"{feature['id']}: priced but carries no citation — hours with no source behind them")
    return {
        "features_in_inventory": len(inventory_ids),
        "features_priced": len(priced_ids),
        "findings": findings,
    }


# --- main ---------------------------------------------------------------------

def build_estimate(inventory, model, options):
    features = inventory.get("features", [])
    priced = []
    for raw in features:
        entry = price_feature(raw, model, options["team"])
        entry["_raw"] = raw
        priced.append(entry)

    if not features:
        raise ValueError(
            "the inventory contains no features. There is nothing to estimate, and the project-level "
            "components alone would produce a confident number for no scope at all — run "
            "est-scope-extract first, or check that extraction actually found something."
        )

    project, volume, manual_total = project_components(priced, model, options["granularity"], options)
    completeness = options["input_completeness"]
    unc = model["uncertainty"]

    mean, sd_features, sd_model, sd, multiplier, half_band = band_half_width(
        [f["total"] for f in priced] + list(project.values()), model, completeness)
    options["completeness_multiplier"] = multiplier
    band = 2 * half_band

    estimate = {
        "schema_version": "1.0",
        "project": inventory.get("project"),
        "granularity": options["granularity"],
        "mode": options["mode"],
        "generated": options["generated"],
        "inventory": options["inventory_path"],
        "inputs": {
            "team_profile": options["team_name"],
            "stack": options["stack"],
            "qa_platform": options["qa_platform"],
            "engagement": options["engagement"],
            "team_size": options["team_size"],
            "why": ("The profile inputs that produced these figures. Anything recomputing this "
                    "estimate — the interactive report especially — must use these, or its numbers "
                    "will silently disagree with the headline they sit under."),
        },
        "total_hours": {
            "low": round(max(mean - half_band, 0.0), 1),
            "likely": round(mean, 1),
            "high": round(mean + half_band, 1),
        },
        "confidence": {
            "input_completeness": completeness,
            "band_multiplier": round(multiplier, 2),
            "z": unc["z"],
            "aggregated_sd": round(sd, 1),
            "sd_from_features": round(sd_features, 1),
            "sd_from_model_risk": round(sd_model, 1),
            "why": (f"Band width is computed, not chosen: an input completeness of {completeness} "
                    f"widens the interval by {multiplier:.2f}x. A thinner brief cannot produce a "
                    f"narrower range."),
        },
        "assumptions": [
            f"Team profile: {options['team_name']} — modifiers applied to specification, review and rework only, not to build.",
            f"Stack profile: {options['stack']}. QA profile: {options['qa_platform']}. Engagement model: {options['engagement']}.",
            f"Planning volume derived from the feature set: {volume['epics']} epics, {volume['stories']} stories, documents: {', '.join(volume['documents']) or 'none (inherited from the running project)'}.",
            "Cost model is UNCALIBRATED against this company's actuals; coefficients are reasoned starting points.",
        ] + inventory.get("assumptions", []),
        "planning_volume": volume,
        "features": [
            {k: v for k, v in f.items() if k != "_raw"} | {
                "hours": round(pert(f["total"])[0], 1),
                "sd": round(pert(f["total"])[1], 1),
                "component_hours": {k: round(pert(v)[0], 1) for k, v in f["components"].items()},
            }
            for f in priced
        ],
        "project_components": {
            name: {"hours": round(pert(value)[0], 1), "sd": round(pert(value)[1], 1)}
            for name, value in project.items()
        },
        "by_phase": by_phase(priced, project, model),
        "by_role": by_role(priced, project, model),
        "scope_split": agreed_split(priced, project, model, options),
        "manual_equivalent": {
            "build_hours": round(pert(manual_total)[0], 1),
            "bmad_build_hours": round(sum(pert(f["components"]["build"])[0] for f in priced), 1),
            "build_compression": round(
                pert(manual_total)[0] / sum(pert(f["components"]["build"])[0] for f in priced), 2)
            if priced else None,
            "whole_project_compression": None,
            "why": ("Compares BUILD effort only, which is the one like-for-like comparison available: "
                    "manual_baseline is what a human team would have spent writing this code. It is "
                    "deliberately NOT compared against the project total, because planning, "
                    "environments, QA and client overhead are costs a manual project pays too — "
                    "quoting an 8x build compression as though the project were 8x cheaper is exactly "
                    "the overclaim this module exists to avoid. Whole-project compression needs a full "
                    "manual counterfactual with its own coefficients, which this model does not have."),
        },
        "risk_quadrant": [
            {"id": f["id"], "name": f["name"], "hours": round(pert(f["total"])[0], 1),
             "compressibility": f["tags"]["compressibility"], "review_tier": f["tags"]["review_tier"]}
            for f in priced
            if f["tags"]["compressibility"] == "low"
            and f["tags"]["review_tier"] in ("sensitive", "critical")
        ],
        "traceability": traceability(inventory, priced),
        "cost_model_snapshot": model,
    }

    if options["mode"] != "quick":
        path = critical_path(priced)
        estimate["dependencies"] = path
        estimate["duration"] = duration(priced, project, model, path, options["team_size"])
        estimate["narrowing_questions"] = narrowing_questions(
            priced, project, model, options, band)

    return estimate


def main():
    ap = argparse.ArgumentParser(
        description="Compute a ranged, role-split estimate from a Feature Inventory.",
        epilog="Exit codes: 0 clean, 1 traceability findings, 2 unreadable input.",
    )
    ap.add_argument("inventory", help="path to feature-inventory.json")
    ap.add_argument("--cost-model", required=True, help="path to cost-model.json")
    ap.add_argument("-o", "--output", help="write estimate.json here instead of stdout")
    ap.add_argument("--mode", default="presale", choices=["quick", "presale", "delivery"])
    ap.add_argument("--team-profile", default="balanced")
    ap.add_argument("--stack", default="standard_saas")
    ap.add_argument("--qa-platform", default="web")
    ap.add_argument("--engagement", default="standard")
    ap.add_argument("--team-size", type=int, help="people available; caps parallelism for duration")
    ap.add_argument("--check-report", metavar="PATH",
                    help="JSON output of est-scope-extract's inventory-check.py; supplies the "
                         "input completeness score and confirms the inventory validated")
    ap.add_argument("--completeness", type=float,
                    help="input completeness score, when no check report is available")
    ap.add_argument("--generated", default="", help="ISO timestamp to stamp on the estimate")
    args = ap.parse_args()

    try:
        inventory = json.loads(Path(args.inventory).read_text(encoding="utf-8"))
        model = json.loads(Path(args.cost_model).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 2

    completeness, check_findings = args.completeness, None
    if args.check_report:
        try:
            report = json.loads(Path(args.check_report).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(json.dumps({"ok": False, "error": f"cannot read check report: {exc}"}, indent=2))
            return 2
        check_findings = report.get("findings", [])
        if check_findings:
            # Pricing an inventory that does not validate produces a confident wrong number.
            print(json.dumps({
                "ok": False,
                "error": "the inventory has unresolved inventory-check findings; fix them before estimating",
                "findings": check_findings[:10],
            }, indent=2))
            return 2
        if completeness is None:
            completeness = (report.get("scoring") or {}).get("input_completeness")

    if completeness is None:
        print(json.dumps({
            "ok": False,
            "error": ("no input completeness score. Run est-scope-extract's inventory-check.py and "
                      "pass its JSON as --check-report, or supply --completeness directly. Band width "
                      "is computed from this score, so an estimate cannot be produced without it."),
        }, indent=2))
        return 2

    profiles = model["team_profiles"]
    if args.team_profile not in profiles:
        print(json.dumps({"ok": False,
                          "error": f"unknown team profile '{args.team_profile}' — known: {sorted(k for k in profiles if not k.startswith('_'))}"},
                         indent=2))
        return 2

    options = {
        "mode": args.mode,
        "team": profiles[args.team_profile],
        "team_name": args.team_profile,
        "stack": args.stack,
        "qa_platform": args.qa_platform,
        "engagement": args.engagement,
        "team_size": args.team_size,
        "granularity": inventory.get("granularity", "project"),
        "input_completeness": float(completeness),
        "inventory_path": args.inventory,
        "generated": args.generated,
    }

    try:
        estimate = build_estimate(inventory, model, options)
    except KeyError as exc:
        print(json.dumps({
            "ok": False,
            "error": f"cost model or inventory is missing {exc}. Every tag value in the inventory "
                     f"must have a matching entry in cost-model.json.",
        }, indent=2))
        return 2

    text = json.dumps(estimate, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
        print(json.dumps({"ok": True, "estimate": args.output,
                          "total_hours": estimate["total_hours"],
                          "traceability_findings": estimate["traceability"]["findings"]}, indent=2))
    else:
        print(text)

    return 1 if estimate["traceability"]["findings"] else 0


if __name__ == "__main__":
    sys.exit(main())
