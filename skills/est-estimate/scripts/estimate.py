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


# The classification axes the cost model prices on. Exported because more than one skill
# iterates them, and a sixth axis added here must not need finding in a second tuple.
AXES = ("size_band", "compressibility", "review_tier", "clarity", "novelty")


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


def widen(value, factor):
    """Stretch an interval around its likely value without moving it.

    The likely vertex is unchanged — a vague story is not automatically a longer one — while lo
    and hi move out, because what is not yet decided is what the range exists to carry. The PERT
    *mean* does rise, because hours are floored at zero: the right tail can extend further than
    the left can contract, so the expected cost of ambiguity is genuinely higher. Measured: +5%
    on a project of uniformly low-clarity stories, nothing at all on a high-clarity one.

    Geometric, not linear: hours are floored at zero and unbounded above, so widening both ends
    by the same additive factor collapses the low side long before the high side has moved.
    Scaling the *ratio* instead — lo and hi move to likely·(lo/likely)^f and likely·(hi/likely)^f
    — cannot produce a negative bound, behaves the same on a 2-hour story and a 200-hour one,
    and acts directly on hi/lo, which is the spread being reported. A linear version of this
    drove the lower bound of a small vague story to 0.0 h and its ratio to 57x.
    """
    lo, likely, hi = value
    if factor == 1.0 or likely <= 0:
        return value
    low = likely * (lo / likely) ** factor if lo > 0 else lo
    high = likely * (hi / likely) ** factor if hi > 0 else hi
    return (low, likely, high)


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

def surfaces_of(feature):
    """Which kinds of work a story touches, or None when the inventory never said.

    None means "unknown", and unknown keeps every conditional role in — so an inventory
    written before surfaces existed prices exactly as it used to instead of silently
    shedding the roles it never got the chance to declare.

    One placement, on the feature. It used to be read out of the tag block first and off the
    feature second, which meant the field the schema defined was the one that lost. Surfaces
    is an observation about the scope, not a judgement about cost, so it stayed with the
    inventory when the tags left.
    """
    node = feature.get("surfaces")
    if node is None:
        return None
    return sorted({node} if isinstance(node, str) else {str(x) for x in node})


def standing_features(model, options):
    """The work every project pays that no client document describes.

    Returned in the same shape as an extracted feature so it is priced by the same engine,
    carries the same band and role split, and lands in the same table — where a client can
    argue with it item by item. It has no citation, and that is the point: inventing a
    citation for it would be worse than admitting it has none, so it carries `origin` and
    the coefficient's own `why` instead, and `traceability()` checks for those.
    """
    if options.get("no_standing_work"):
        return []
    stack, out = options["stack"], []
    for key, spec in (model["standing_work"]["items"]).items():
        stacks = spec["stacks"]
        if stacks != "all" and stack not in stacks:
            continue
        out.append({
            "id": f"SW-{key}",
            "name": spec["name"],
            "description": spec["why"],
            "origin": "standing",
            "rationale": spec["why"],
            "citations": [],
            "commitment": "committed",
            # Its own scope group. Labelling it "outside agreed scope" would put setup and
            # pipeline work in the column a client reads as "things we tried to add".
            "scope_status": "standing_work",
            # Its own hours, not a size band. Standing work is a fixed catalogue of real
            # effort — a CI pipeline costs what it costs however the product backlog is
            # sliced — so tying it to a band that describes product stories meant re-scaling
            # the band silently re-priced the pipeline with it.
            "manual_hours": spec["hours"],
            "tags": {axis: {"value": spec.get(axis), "why": spec["reasons"].get(axis),
                            "status": "standing"} for axis in AXES},
            "surfaces": spec["surfaces"],
            "depends_on": [],
            "open_questions": [],
        })
    return out


def price_feature(feature, model, team):
    """Cost one feature. Returns its components and the inputs that produced them."""
    tags = feature.get("tags", {})

    def value(axis):
        return (tags.get(axis) or {}).get("value")

    size, comp_class = value("size_band"), value("compressibility")
    tier, clarity, novelty = value("review_tier"), value("clarity"), value("novelty")

    override = feature.get("manual_hours")
    manual = (override["lo"], override["likely"], override["hi"]) if override \
        else tp(model, "size_bands", size)
    compression = tp(model, "compressibility", comp_class)
    clarity_row = model["clarity"][clarity]
    novelty_factor = model["novelty_rework_multiplier"][novelty]["factor"]

    build = div(manual, compression)
    spec = scale(manual, clarity_row["spec_rate"] * team["spec"])
    # The load-bearing line: review scales with manual_baseline, not with build.
    review = scale(mul(manual, tp(model, "review_rate", tier)), team["review"])
    rework = scale(add(build, review),
                   clarity_row["rework_rate"] * novelty_factor * team["rework"])

    # How well-specified the work is has to show up as width, and until this line it did the
    # opposite: spec and rework are scalar multiples of an interval and so proportionally
    # tight, and low clarity adds MORE of them, which pulled the relative band DOWN. A real
    # inventory read 6.32 hi/lo at high clarity against 5.52 at low — a vague story presenting
    # as the more certain one.
    band = float(clarity_row.get("band_multiplier", 1.0))
    total = widen(add(build, spec, review, rework), band)

    return {
        "id": feature.get("id"),
        "name": feature.get("name"),
        "description": feature.get("description"),
        "epic_id": feature.get("epic_id"),
        "origin": feature.get("origin") or "extracted",
        "surfaces": surfaces_of(feature),
        "scope_status": feature.get("scope_status") or "in_agreed_scope",
        "commitment": feature.get("commitment"),
        "tags": {a: value(a) for a in AXES},
        "tag_status": {a: (tags.get(a) or {}).get("status") for a in AXES},
        "tag_why": {a: (tags.get(a) or {}).get("why") for a in AXES},
        "citations": [{"source_id": c.get("source_id"), "location": c.get("location"),
                       "quote": c.get("quote")} for c in feature.get("citations", [])],
        "open_questions": feature.get("open_questions", []),
        "tasks": [{"id": t.get("id"), "name": t.get("name"),
                   "citations": [{"source_id": c.get("source_id"), "location": c.get("location"),
                                  "quote": c.get("quote")} for c in t.get("citations", [])]}
                  for t in feature.get("tasks", [])],
        "depends_on": [d.get("feature_id") for d in feature.get("depends_on", [])],
        "manual_baseline": manual,
        "components": {"build": build, "spec": spec, "review": review, "rework": rework},
        "clarity_band_multiplier": band,
        "total": total,
    }


# --- project-level components ----------------------------------------------

def plan_volume(priced, model, granularity):
    """Derive planning artefact volume from the feature set.

    Deterministic and reproducible: the same inventory always yields the same volume,
    so planning_review_h — the estimate's high-confidence anchor — never depends on
    anyone's recollection of how many stories a project like this usually has.
    """
    # Standing work is excluded: setting up a pipeline does not get a PRD section, an epic or
    # a story, so counting it here would bill planning artefacts that will never be written.
    priced = [f for f in priced if f.get("origin") != "standing"]
    per_size = model["planning"]["stories_per_feature"]
    stories = sum(per_size.get(f["tags"]["size_band"], 1) for f in priced)
    grouped = {f["epic_id"] for f in priced if f.get("epic_id")}
    if grouped:
        # The source grouped the work itself. Dividing the story count by a rule of thumb
        # instead invents a different number for a fact already on the page — and planning is
        # priced per epic, so the invented number goes straight into the bill. Kampies' BA
        # had written 56 epics; the ratio produced 99, and every per-epic hour was billed
        # against the difference. Counting the epics actually represented also keeps the
        # interactive report honest: drop every story in an epic and the epic stops costing.
        epics, epics_from = len(grouped), "counted from the stories' own epics"
    else:
        epics = math.ceil(len(priced) / model["planning"]["features_per_epic"]) if priced else 0
        epics_from = f"derived: {len(priced)} stories / {model['planning']['features_per_epic']} per epic"
    documents = model["planning"]["documents_by_granularity"].get(granularity, [])
    return {"epics": epics, "epics_from": epics_from, "stories": stories, "documents": documents}


def planning_cost(volume, model, key):
    rates = model["planning"][key]
    parts = [tp(rates, doc) for doc in volume["documents"]]
    parts.append(scale(tp(rates, "per_epic"), volume["epics"]))
    parts.append(scale(tp(rates, "per_story"), volume["stories"]))
    return add(*parts)


def overhead_cost(model, options, span):
    """Ceremony, demos and client comms — priced per person per week, not per hour of scope.

    A status call recurs on the calendar, not on the backlog. Charged as a share of the
    subtotal it inherited every scope error the estimate made: a scope counted ten times
    over billed ten times the meetings, which is how a granularity mistake turned into a
    commercial one. The implied percentage is still reported, as a cross-check rather than
    as the basis.
    """
    rates = model["overhead_rate"]
    if rates.get("basis") != "hours_per_person_week":
        raise ValueError(
            "this cost model prices overhead as a share of the subtotal, which this engine no "
            "longer does — overhead is now weeks x people x hours/week. Run "
            "scripts/migrate-cost-model.py against the model to convert it."
        )
    return mul(tp(rates, options["engagement"]),
               scale(span["weeks_three_point"], span["assumed_team_size"]))


def overhead_check(priced, project, span):
    """What the duration-based overhead works out to as a share of everything else.

    Reported so the change of basis stays auditable against the percentages people carry in
    their heads. It is a division of two numbers already computed, not a second way of
    arriving at the overhead.
    """
    others = sum(pert(v)[0] for name, v in project.items() if name != "overhead")
    subtotal = sum(pert(f["total"])[0] for f in priced) + others
    overhead = pert(project["overhead"])[0]
    return {
        "hours": round(overhead, 1),
        "implied_pct_of_subtotal": round(100 * overhead / subtotal, 1) if subtotal else None,
        "basis": (f"{span['weeks']} weeks ({span['weeks_range'][0]}–{span['weeks_range'][1]}) "
                  f"x {span['assumed_team_size']} people"),
    }


def project_components(priced, model, granularity, options):
    """The costs no feature list contains, plus the single duration everything else reads.

    Duration is computed here rather than by the caller because overhead now depends on it,
    and a second derivation of the same weeks would be a second answer to the same question.
    """
    volume = plan_volume(priced, model, granularity)
    manual_total = add(*[f["manual_baseline"] for f in priced]) if priced else (0.0, 0.0, 0.0)

    components = {
        "planning_agent": planning_cost(volume, model, "agent_hours"),
        "planning_review": planning_cost(volume, model, "review_hours"),
        "qa": mul(manual_total, tp(model, "qa", options["qa_platform"])),
    }
    path = critical_path(priced)
    span = duration(priced, components, model, path, options["team_size"])
    components["overhead"] = overhead_cost(model, options, span)
    return components, volume, manual_total, path, span


# --- splits ------------------------------------------------------------------

def component_roles(model, component, surfaces):
    """Which roles are on this component, and in what share.

    A weight entry may name a `requires` surface. When the story does not have that surface
    the role is dropped and the survivors renormalise, so a pure backend story bills no UX
    and no design story bills devops — while the shares still sum to 1, which is what keeps
    the role split an allocation of the total rather than an adjustment to it.
    """
    entries = {}
    for role, node in model["role_weights"][component].items():
        if role.startswith("_"):
            continue
        spec = node if isinstance(node, dict) else {"w": node}
        requires, any_of = spec.get("requires"), spec.get("requires_any")
        if surfaces is not None:
            if requires and requires not in surfaces:
                continue
            # `requires_any` is what lets a role be conditional without being niche. Making
            # `dev` require backend-or-frontend is the only way an infra-only story reaches
            # devops: while dev was unconditional it survived renormalisation and billed a CI
            # pipeline 91% developer, which is not who builds a CI pipeline.
            if any_of and not set(any_of) & set(surfaces):
                continue
        entries[role] = float(spec["w"])
    total = sum(entries.values())
    if not total:
        raise ValueError(
            f"role_weights.{component} leaves nobody on the work for surfaces "
            f"{sorted(surfaces or [])} — every component needs at least one unconditional role"
        )
    return {role: weight / total for role, weight in entries.items()}


def feature_roles(feature, model):
    """Role intervals for one story, so a line item can be defended role by role.

    Three-point, not a mean. A role figure with no interval behind it is the point value the
    estimate is not allowed to report, and every output breaks the hours out per role.
    The story's clarity band is applied to each role's share, so a role's numbers still add
    up to the story's own range.
    """
    surfaces = feature.get("surfaces")
    surfaces = set(surfaces) if surfaces else None
    band = float(feature.get("clarity_band_multiplier", 1.0))
    totals = {}
    for component, value in feature["components"].items():
        for role, share in component_roles(model, component, surfaces).items():
            totals[role] = add(totals.get(role, (0.0, 0.0, 0.0)), scale(value, share))
    return {role: widen(value, band) for role, value in totals.items()}


def by_role(priced, project, model):
    """Project role totals: an interval per role, and the two sources it came from.

    This replaces the grand total as the estimate's headline, so it has to reconcile. Summing
    the story rows alone gave architect 0 and qa 0 against 170 h and 205 h in the table, because
    planning, planning-review, QA and overhead touch no story — 27% of a real project sitting
    outside every row a reader could add up. Both parts are reported, so the arithmetic is on
    the page rather than left as a gap to discover.
    """
    stories, project_side = {}, {}
    for feature in priced:
        for role, value in feature_roles(feature, model).items():
            stories[role] = add(stories.get(role, (0.0, 0.0, 0.0)), value)
    for name, value in project.items():
        for role, share in component_roles(model, name, None).items():
            project_side[role] = add(project_side.get(role, (0.0, 0.0, 0.0)),
                                     scale(value, share))

    out = {}
    for role in sorted(set(stories) | set(project_side)):
        on_stories = stories.get(role, (0.0, 0.0, 0.0))
        project_level = project_side.get(role, (0.0, 0.0, 0.0))
        total = add(on_stories, project_level)
        out[role] = {
            "low": round(total[0], 1), "likely": round(total[1], 1), "high": round(total[2], 1),
            "hours": round(pert(total)[0], 1),
            "on_stories": round(pert(on_stories)[0], 1),
            "project_level": round(pert(project_level)[0], 1),
        }
    return out


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
        own_project, *_ = project_components(features, model, options["granularity"], options)
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
    """Longest dependency chain by mean story hours. Cycles are impossible here —
    est-scope-extract's checker rejects them — but guard anyway rather than recurse forever.

    Standing work is excluded. It has no dependencies and nothing waits on it, so with the
    bands at story scale the single largest setup item simply became "the critical path" — a
    one-node chain that told a reader nothing about what actually gates delivery.
    """
    priced = [f for f in priced if f.get("origin") != "standing"]
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
    """Derived calendar duration. Secondary to hours and labelled as such everywhere.

    Three-point, because overhead is now priced against it: a project that runs longer holds
    more ceremony, so collapsing the schedule to a single number here would hand overhead a
    certainty the schedule does not have and quietly narrow the whole band.
    """
    cal = model["calendar"]
    people = min(team_size or cal["max_useful_parallelism"], cal["max_useful_parallelism"])
    feature_hours = add(*[f["total"] for f in priced]) if priced else (0.0, 0.0, 0.0)
    # Planning is a small-group serial prefix; it does not parallelise across a big team.
    planning = add(project["planning_agent"], project["planning_review"])
    weeks = tuple(
        (planning[i] / min(people, 2) + (max(path["hours"], feature_hours[i] / people)
                                         if people else feature_hours[i]))
        / cal["hours_per_person_week"]
        for i in range(3)
    )
    mean = pert(feature_hours)[0]
    return {
        "weeks": round(weeks[1], 1),
        "weeks_range": [round(weeks[0], 1), round(weeks[2], 1)],
        "weeks_three_point": weeks,
        "assumed_team_size": people,
        "critical_path_hours": path["hours"],
        "parallelism_ceiling": round(mean / path["hours"], 1) if path["hours"] else None,
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
        components, *_ = project_components(repriced, model, options["granularity"], options)
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
        if feature.get("origin") in ("standing", "implicit"):
            if not feature["_raw"].get("rationale"):
                findings.append(f"{feature['id']}: {feature['origin']} work with no rationale — "
                                f"the one thing work standing in for a quote has to carry instead")
            continue
        if not feature["citations"]:
            findings.append(f"{feature['id']}: priced but carries no citation — hours with no source behind them")
    return {
        "features_in_inventory": len(inventory_ids),
        "features_priced": sum(1 for f in priced if f.get("origin") == "extracted"),
        "implicit_scope_priced": sum(1 for f in priced if f.get("origin") == "implicit"),
        "standing_work_priced": sum(1 for f in priced if f.get("origin") == "standing"),
        "findings": findings,
    }


def load_scope(inventory, classification):
    """A Feature Inventory with its classification joined on, ready to price.

    The join happens here rather than inside the engine, so everything downstream — including
    `inventory_from`, which three other skills re-price through — keeps working on one shape.

    A feature with no classification row is named, never priced. Silently defaulting it would
    put a story in the total at whatever the cost model's first band happens to be, and the
    reader would have no way of telling that hours from a guess from hours from a judgement.
    """
    rows = (classification or {}).get("features") or {}
    joined = json.loads(json.dumps(inventory))
    missing = []
    for key in ("features", "implicit_scope"):
        for feature in joined.get(key) or []:
            tags = rows.get(feature.get("id"))
            if not tags:
                missing.append(feature.get("id"))
                continue
            feature["tags"] = json.loads(json.dumps(tags))
    orphans = sorted(set(rows) - {f.get("id") for k in ("features", "implicit_scope")
                                  for f in joined.get(k) or []})
    return joined, missing, orphans


# --- facts about a model that more than one skill needs to agree on -------------

def is_calibrated(model):
    """Has this model been reconciled against delivered actuals?

    Structural, because the answer gates a claim made to a client. It used to be derived in three
    separate places by prefix-matching the free-prose `calibration_status` sentence, so rewording
    the seed to "Not yet calibrated…" would have silently marked every estimate as calibrated —
    the exact overclaim the module refuses to make. A judgement change through curate.py is
    deliberately not calibration: it is an informed opinion, and saying otherwise to a client is
    the same overclaim wearing a better label.
    """
    return any((entry.get("kind") or "calibrated") != "judgement"
               for entry in model.get("calibration_history") or [])


def calibration_samples(model):
    """How many delivered projects the model's coefficients actually rest on.

    The largest single calibration rather than the sum: two entries fitted against the same anchor
    are one project's worth of evidence, and a client told "calibrated against four projects" when
    it is one anchor read four ways has been told something false.
    """
    return max((int(entry.get("samples") or 0)
                for entry in model.get("calibration_history") or []
                if (entry.get("kind") or "calibrated") != "judgement"), default=0)


def options_from(estimate, model, overrides=None):
    """The pricing inputs an existing estimate was produced with.

    One definition, because three skills need to reproduce a recorded number exactly: est-calibrate
    re-prices history to backtest a coefficient, est-agent-estimator re-prices scope to answer a
    what-if. Rebuilt independently they drift in their fallbacks — a silent default of `balanced`
    for an unknown team profile turns a re-price into a different estimate, and reports the
    difference as the effect of whatever was being tested.
    """
    inputs = dict(estimate.get("inputs") or {})
    inputs.pop("why", None)
    inputs.update({k: v for k, v in (overrides or {}).items() if v is not None})

    profile = inputs.get("team_profile") or "balanced"
    profiles = model["team_profiles"]
    if profile not in profiles:
        known = sorted(k for k in profiles if not k.startswith("_"))
        raise ValueError(f"unknown team profile '{profile}' — known: {known}. Re-pricing it as "
                         f"'balanced' would silently change the estimate being reproduced.")

    completeness = (estimate.get("confidence") or {}).get("input_completeness")
    if completeness is None:
        raise ValueError(
            "the estimate carries no input completeness score, so its band cannot be reproduced. "
            "Band width is computed from that score; defaulting it would invent a confidence the "
            "original number never claimed.")

    return {
        "mode": inputs.get("mode") or estimate.get("mode", "presale"),
        "team": profiles[profile],
        "team_name": profile,
        "stack": inputs.get("stack") or "standard_saas",
        "qa_platform": inputs.get("qa_platform") or "web",
        "engagement": inputs.get("engagement") or "standard",
        "team_size": inputs.get("team_size"),
        # Recorded as a positive ("standing_work": true) and consumed as a negative, so an
        # estimate priced without it re-prices without it rather than silently gaining it back.
        "no_standing_work": inputs.get("standing_work") is False,
        "granularity": estimate.get("granularity", "project"),
        "input_completeness": float(completeness),
        "inventory_path": estimate.get("inventory") or "reprice",
        "generated": estimate.get("generated", ""),
    }


# --- reverse: a priced estimate back into the scope that produced it -----------

def inventory_from(estimate):
    """Reconstruct the priced scope from an estimate — or from a ledger entry, which is
    an estimate plus a `ledger` block.

    Every consumer that re-prices existing work needs this: est-calibrate backtests
    history, est-agent-estimator answers "what if we drop this". It lives here, beside
    the pricing it inverts, so there is exactly one definition of what a priced feature
    turns back into. Two would silently disagree about a field neither owner noticed.

    Priced features store tags flat with their reasons alongside; pricing wants them
    nested. That reshaping is the whole job.
    """
    features, implicit = [], []
    for f in estimate.get("features", []):
        # Standing work is regenerated from the cost model on the re-price, not carried over.
        # Carrying it would add it a second time and report the duplicate as the effect of
        # whatever was being tested — which is precisely what the parity gate exists to catch.
        if f.get("origin") == "standing":
            continue
        tags = {}
        for axis, value in (f.get("tags") or {}).items():
            tags[axis] = {"value": value,
                          "why": (f.get("tag_why") or {}).get(axis) or "from a priced estimate",
                          "status": (f.get("tag_status") or {}).get(axis) or "inferred"}
        entry = {
            "id": f["id"], "name": f.get("name", f["id"]),
            "description": f.get("name", ""),
            "citations": f.get("citations") or [{"source_id": "S1", "location": "ledger",
                                                 "quote": "recorded estimate"}],
            "commitment": f.get("commitment", "committed"),
            "scope_status": f.get("scope_status"),
            "epic_id": f.get("epic_id"),
            "surfaces": f.get("surfaces"),
            "tags": tags,
            "depends_on": [{"feature_id": d, "inferred": True} for d in (f.get("depends_on") or [])],
            "open_questions": f.get("open_questions", []),
        }
        if f.get("origin") == "implicit":
            entry.pop("citations")
            entry["rationale"] = f.get("description") or "carried from a priced estimate"
            implicit.append(entry)
        else:
            features.append(entry)
    return {
        "schema_version": "1.0", "generated": estimate.get("generated"),
        "project": estimate.get("project"), "granularity": estimate.get("granularity", "project"),
        "working_language": "en",
        "sources": [{"id": "S1", "path": "ledger", "doc_type": "sow", "language": "en"}],
        "features": features, "implicit_scope": implicit,
        "not_scope": [], "conflicts": [], "assumptions": [], "completeness_signals": {},
    }


# --- main ---------------------------------------------------------------------

def build_estimate(inventory, model, options):
    features = inventory.get("features", [])
    implicit = [dict(f, origin="implicit") for f in inventory.get("implicit_scope", [])]
    standing = standing_features(model, options)
    priced = []
    for raw in features + implicit + standing:
        entry = price_feature(raw, model, options["team"])
        entry["_raw"] = raw
        priced.append(entry)

    if not features:
        raise ValueError(
            "the inventory contains no features. There is nothing to estimate, and the project-level "
            "components alone would produce a confident number for no scope at all — run "
            "est-scope-extract first, or check that extraction actually found something."
        )

    project, volume, manual_total, path, span = project_components(
        priced, model, options["granularity"], options)
    completeness = options["input_completeness"]
    unc = model["uncertainty"]

    mean, sd_features, sd_model, sd, multiplier, half_band = band_half_width(
        [f["total"] for f in priced] + list(project.values()), model, completeness)
    options["completeness_multiplier"] = multiplier
    band = 2 * half_band

    calibrated_from = calibration_samples(model) if is_calibrated(model) else 0
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
            "standing_work": not options.get("no_standing_work"),
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
            "band_width": round(2 * half_band, 1),
            "band_width_pct": round(200 * half_band / mean, 1) if mean else None,
            "why": (f"Band width is computed, not chosen: an input completeness of {completeness} "
                    f"widens the interval by {multiplier:.2f}x. A thinner brief cannot produce a "
                    f"narrower range."),
        },
        "assumptions": [
            f"Team profile: {options['team_name']} — modifiers applied to specification, review and rework only, not to build.",
            f"Stack profile: {options['stack']}. QA profile: {options['qa_platform']}. Engagement model: {options['engagement']}.",
            f"Planning volume: {volume['epics']} epics ({volume['epics_from']}), {volume['stories']} stories, documents: {', '.join(volume['documents']) or 'none (inherited from the running project)'}.",
            f"Overhead priced as {span['weeks']} weeks ({span['weeks_range'][0]}–{span['weeks_range'][1]}) x {span['assumed_team_size']} people of ceremony, not as a share of scope.",
            (f"Cost model calibrated against {calibrated_from} delivered "
             f"{'project' if calibrated_from == 1 else 'projects'}; a single anchor is a weak "
             f"statistical base and the coefficients say so in their own why lines."
             if calibrated_from else
             "Cost model is UNCALIBRATED against this company's actuals; coefficients are reasoned "
             "starting points."),
        ] + [f"Classification quality: {w}" for w in options.get("inventory_warnings") or []]
          + inventory.get("assumptions", []),
        "planning_volume": volume,
        "features": [
            {k: v for k, v in f.items() if k != "_raw"} | {
                "hours": round(pert(f["total"])[0], 1),
                "sd": round(pert(f["total"])[1], 1),
                # Every level of breakdown carries its interval. A point value is what the
                # reader is meant to stop seeing.
                "range": {"low": round(f["total"][0], 1), "likely": round(f["total"][1], 1),
                          "high": round(f["total"][2], 1)},
                "component_hours": {k: round(pert(v)[0], 1) for k, v in f["components"].items()},
                "by_role": {r: {"low": round(v[0], 1), "likely": round(v[1], 1),
                                "high": round(v[2], 1), "hours": round(pert(v)[0], 1)}
                            for r, v in sorted(feature_roles(f, model).items())
                            if pert(v)[0] >= 0.05},
            }
            for f in priced
        ],
        "project_components": {
            name: {"hours": round(pert(value)[0], 1), "sd": round(pert(value)[1], 1),
                   "range": {"low": round(value[0], 1), "likely": round(value[1], 1),
                             "high": round(value[2], 1)},
                   # The role split of each project line, so a sheet's project rows reconcile
                   # against the role table rather than sitting blank beside it.
                   "by_role": {role: {"low": round(value[0] * share, 1),
                                      "likely": round(value[1] * share, 1),
                                      "high": round(value[2] * share, 1),
                                      "hours": round(pert(value)[0] * share, 1)}
                               for role, share in component_roles(model, name, None).items()}}
            for name, value in project.items()
        },
        "overhead_check": overhead_check(priced, project, span),
        "standing_work": {
            "items": [{"id": f["id"], "name": f["name"], "hours": round(pert(f["total"])[0], 1),
                       "why": f["_raw"]["rationale"]}
                      for f in priced if f.get("origin") == "standing"],
            "hours": round(sum(pert(f["total"])[0] for f in priced
                               if f.get("origin") == "standing"), 1),
            "why": ("Work no client document describes and every project pays. Added openly and "
                    "priced through the same engine as the extracted scope, so it can be argued "
                    "with item by item or suppressed with --no-standing-work."),
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
                    "standing setup work, QA and client overhead are costs a manual project pays "
                    "too — "
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
        estimate["dependencies"] = path
        estimate["duration"] = {k: v for k, v in span.items() if k != "weeks_three_point"}
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
    ap.add_argument("--no-standing-work", action="store_true",
                    help="omit setup, pipeline, environment and release work — only when the "
                         "client is bringing an existing platform that already has it")
    ap.add_argument("--classification", metavar="PATH", required=True,
                    help="classification.json — what each story costs to build, keyed by feature "
                         "id. Written by this skill's classification pass; the inventory holds "
                         "what the source said and nothing about effort")
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
        classification = json.loads(Path(args.classification).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 2

    if inventory.get("features") and "tags" in (inventory["features"][0] or {}):
        print(json.dumps({
            "ok": False,
            "error": "this inventory carries its classification inline, which is the shape from "
                     "before extraction and estimation were separated. Split it first: "
                     "uv run split-inventory.py <inventory> --in-place",
        }, indent=2))
        return 2

    inventory, unclassified, orphans = load_scope(inventory, classification)
    orphan_note = ([f"{len(orphans)} classified features are not in this inventory "
                    f"(e.g. {', '.join(orphans[:3])}) — the classification was made against a "
                    f"different extraction. Re-key it with classification-merge.py"]
                   if orphans else [])
    if unclassified:
        print(json.dumps({
            "ok": False,
            "error": "these features have no classification, and a story priced on a default is "
                     "indistinguishable in the total from one priced on a judgement",
            "unclassified": unclassified[:20],
            "count": len(unclassified),
        }, indent=2))
        return 2

    completeness, check_findings, check_warnings = args.completeness, None, []
    if args.check_report:
        try:
            report = json.loads(Path(args.check_report).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(json.dumps({"ok": False, "error": f"cannot read check report: {exc}"}, indent=2))
            return 2
        check_findings = report.get("findings", [])
        check_warnings = report.get("warnings", [])
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
        "no_standing_work": args.no_standing_work,
        "inventory_warnings": list(check_warnings) + orphan_note,
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
