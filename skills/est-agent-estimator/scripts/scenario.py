#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Re-price an estimate under changed scope, tags or team — through est-estimate's own engine.

Every "what if" this agent answers is the same operation: build a variant of the priced scope
and cost it again. Doing that by subtracting a feature's hours from the total is wrong in a way
that reads correct, because planning review, QA and client overhead all scale with the scope
that remains — so the real saving is never the feature's own hours, and quoting it as one is
how a client is promised a discount the project cannot deliver.

Nothing here prices anything itself. It loads est-estimate's engine and asks. Before reporting
any difference it re-prices the *untouched* baseline and checks that it reproduces the headline
it was handed: a what-if measured against a number this script cannot reproduce is the gap
between two models, not the effect of the change.
"""

import argparse
import importlib.util
import json
import sys
from pathlib import Path

# Correct while both skills sit under one parent, which is the normal install. --engine
# recovers any other layout without editing this file.
DEFAULT_ENGINE = Path(__file__).resolve().parent.parent.parent / "est-estimate" / "scripts" / "estimate.py"

PROFILE_KEYS = ("team_profile", "stack", "qa_platform", "engagement", "team_size")

# What a client can be asked to give up first. Nothing here decides that a feature should go —
# it orders the candidates so the cheapest conversation comes before the hardest one, and the
# ordering is reported alongside every figure so a human can overrule it.
DROP_PRIORITY = {"speculative": 0, "implied": 1, "committed": 2}


class Refused(Exception):
    """A condition the caller must see rather than a number they should not trust."""


def engine(path=None):
    """Load est-estimate's pricing engine, or say plainly why nothing can be re-priced."""
    target = Path(path) if path else DEFAULT_ENGINE
    if not target.exists():
        raise Refused(
            f"est-estimate's engine is not at {target}. Every scenario is a re-price through that "
            f"engine rather than arithmetic on the totals, so without it a what-if can be described "
            f"but never costed. Look for estimate.py under the project's skills directory and pass "
            f"it with --engine."
        )
    spec = importlib.util.spec_from_file_location("estimate", target)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def options_from(estimate, model, est, overrides=None):
    """The profile inputs this estimate was priced on, from the engine's own definition.

    Taking these from the estimate rather than from defaults is the whole point: an estimate
    priced for a junior team, re-priced at the default balanced profile, reports a saving that is
    really the team profile changing underneath the scope question. The rule lives in
    est-estimate beside the pricing, so est-calibrate's backtests and these scenarios cannot
    drift apart on a fallback neither owner noticed.
    """
    try:
        return est.options_from(estimate, model, overrides)
    except ValueError as exc:
        raise Refused(str(exc))


def dependents_of(features):
    """id → the features that would break if it went away."""
    reverse = {f["id"]: set() for f in features}
    for f in features:
        for dep in f.get("depends_on") or []:
            target = dep["feature_id"] if isinstance(dep, dict) else dep
            if target in reverse:
                reverse[target].add(f["id"])
    return reverse


def closure(ids, features):
    """Everything that must go with these features, because it cannot stand without them.

    Dropping a feature three others depend on is not a saving of one feature; it is a saving
    of four or a broken plan, and the difference is the entire value of capturing dependencies.
    """
    reverse = dependents_of(features)
    out, stack = set(), list(ids)
    while stack:
        current = stack.pop()
        if current in out:
            continue
        out.add(current)
        stack.extend(reverse.get(current, ()))
    return out


def apply_mutations(inventory, drops=(), retags=(), additions=(), axes=None):
    """A copy of the scope with features removed, retagged or added. Never mutates the input."""
    scope = json.loads(json.dumps(inventory))
    known = {f["id"] for f in scope["features"]}

    missing = [d for d in drops if d not in known]
    if missing:
        raise Refused(f"cannot drop {missing}: not in this estimate. Priced features are "
                      f"{sorted(known)}.")
    scope["features"] = [f for f in scope["features"] if f["id"] not in set(drops)]

    by_id = {f["id"]: f for f in scope["features"]}
    for fid, axis, value in retags:
        if fid not in by_id:
            raise Refused(f"cannot retag {fid}: not in the remaining scope "
                          f"(dropped in the same scenario, or never priced).")
        if axes and axis not in axes:
            raise Refused(f"'{axis}' is not a classification axis — one of {list(axes)}.")
        tag = by_id[fid]["tags"].setdefault(axis, {})
        tag.update({"value": value, "status": "overridden",
                    "why": f"scenario override: {axis} set to '{value}' to test its effect"})

    for feature in additions:
        if feature.get("id") in by_id:
            raise Refused(f"cannot add {feature.get('id')}: that id is already priced.")
        scope["features"].append(feature)

    if not scope["features"]:
        raise Refused(
            "that scenario drops every feature. The remaining number would be project overhead "
            "priced against no scope at all, which is not an estimate of anything."
        )
    return scope


PRICED = [0]


def price(scope, model, options, est, note=""):
    """Every hour in this file comes through here, so the count of engine calls is exact."""
    PRICED[0] += 1
    if VERBOSE[0]:
        print(f"  [{PRICED[0]:3d}] pricing {len(scope['features'])} features {note}",
              file=sys.stderr)
    return est.build_estimate(scope, model, options)


VERBOSE = [False]


def totals(priced):
    return {k: priced["total_hours"][k] for k in ("low", "likely", "high")}


def band_width(priced):
    t = priced["total_hours"]
    return round(t["high"] - t["low"], 1)


def delta_map(before, after):
    keys = sorted(set(before) | set(after))
    return {k: round(after.get(k, 0.0) - before.get(k, 0.0), 1) for k in keys}


def phase_hours(priced):
    return {k: (v["hours"] if isinstance(v, dict) else v) for k, v in priced["by_phase"].items()}


def role_hours(priced):
    return {k: (v["hours"] if isinstance(v, dict) else v) for k, v in priced["by_role"].items()}


def compare(baseline, variant, dropped, features):
    """The difference, with the trap named: the saving is not the features' own hours."""
    own_hours = round(sum(f["hours"] for f in baseline["features"] if f["id"] in dropped), 1)
    saving = round(baseline["total_hours"]["likely"] - variant["total_hours"]["likely"], 1)
    reverse = dependents_of(features)
    warnings = []
    for fid in dropped:
        orphaned = sorted(reverse.get(fid, set()) - set(dropped))
        if orphaned:
            warnings.append({
                "dropped": fid,
                "breaks": orphaned,
                "detail": (f"{', '.join(orphaned)} "
                           f"{'depends' if len(orphaned) == 1 else 'depend'} on {fid} and "
                           f"{'is' if len(orphaned) == 1 else 'are'} still in scope. This scenario "
                           f"prices work that has lost what it was built on."),
            })
    return {
        "total_hours": {"before": totals(baseline), "after": totals(variant)},
        "saving": saving,
        "dropped_features_own_hours": own_hours,
        "saving_vs_own_hours": (
            None if not dropped else
            f"dropping {len(dropped)} feature(s) worth {own_hours}h of their own effort changes the "
            f"project by {saving}h, because planning review, QA and overhead scale with the scope "
            f"that remains. Quote {saving}h, never {own_hours}h."
        ),
        "band_width": {"before": band_width(baseline), "after": band_width(variant)},
        "by_phase_change": delta_map(phase_hours(baseline), phase_hours(variant)),
        "by_role_change": delta_map(role_hours(baseline), role_hours(variant)),
        "risk_quadrant": {"before": len(baseline.get("risk_quadrant", [])),
                          "after": len(variant.get("risk_quadrant", []))},
        "dependency_warnings": warnings,
    }


def cutline(baseline, scope, model, options, est, target):
    """Candidate cuts to reach a budget, every figure a real re-price.

    The ordering is a proposal, not a decision: speculative scope before implied before
    committed, and within a tier the biggest saving first. What is actually worth keeping is
    the one judgement in this file that belongs to a human, so the full candidate table is
    returned alongside whatever the greedy walk picked.
    """
    features = scope["features"]
    by_feature = {f["id"]: f for f in features}
    baseline_likely = baseline["total_hours"]["likely"]

    candidates = []
    for feature in features:
        group = sorted(closure([feature["id"]], features))
        if len(group) == len(features):
            # Dropping this takes the whole project with it; there is nothing left to price.
            candidates.append({
                "id": feature["id"], "name": feature["name"], "closure": group,
                "features_lost": len(group), "saving": None,
                "priority": DROP_PRIORITY.get(feature.get("commitment"), 2),
                "commitment": feature.get("commitment"), "scope_status": feature.get("scope_status"),
                "note": "everything else depends on this, directly or transitively — it is not a cut",
            })
            continue
        variant = price(apply_mutations(scope, drops=group), model, options, est)
        candidates.append({
            "id": feature["id"], "name": feature["name"], "closure": group,
            "features_lost": len(group),
            "saving": round(baseline_likely - variant["total_hours"]["likely"], 1),
            "priority": DROP_PRIORITY.get(feature.get("commitment"), 2),
            "commitment": feature.get("commitment"),
            "scope_status": feature.get("scope_status"),
            "note": None,
        })

    def tier(c):
        return (0 if c.get("scope_status") == "outside_agreed_scope" else 1, c["priority"])

    # Exhaust the easiest tier before touching the next, and inside a tier take the smallest cut
    # that closes the remaining gap — falling back to the largest only when nothing does. Sorting
    # by biggest saving instead proposes cutting payments to reach a budget three peripheral
    # features would have covered, which is a correct number and a bad recommendation.
    remaining = [c for c in candidates if c["saving"] is not None]
    dropped, achieved, steps = set(), baseline_likely, []
    while remaining and achieved > target:
        lowest = min(tier(c) for c in remaining)
        pool = [c for c in remaining if tier(c) == lowest]
        gap = achieved - target

        # A candidate's headline saving is measured against the untouched baseline, so once
        # anything has been dropped it overstates what that candidate still buys — its closure
        # may be mostly gone already. Re-price those against the current scope rather than
        # choosing a cut on a figure that is no longer true.
        def marginal(c):
            if not (set(c["closure"]) & dropped):
                return c["saving"]
            group = set(c["closure"]) | dropped
            if len(group) >= len(features):
                return 0.0
            after = price(apply_mutations(scope, drops=sorted(group)), model, options, est)
            return round(achieved - after["total_hours"]["likely"], 1)

        scored = [(marginal(c), c) for c in pool]
        sufficient = sorted((pair for pair in scored if pair[0] >= gap), key=lambda pair: pair[0])
        candidate = sufficient[0][1] if sufficient else max(scored, key=lambda pair: pair[0])[1]
        remaining.remove(candidate)

        group = set(candidate["closure"]) - dropped
        if not group or len(dropped | group) >= len(features):
            continue
        trial = price(apply_mutations(scope, drops=sorted(dropped | group)), model, options, est)
        dropped |= group
        achieved = trial["total_hours"]["likely"]
        steps.append({"drop": sorted(group), "cumulative_likely": achieved,
                      "cumulative_saving": round(baseline_likely - achieved, 1),
                      "reason": ("outside the agreed scope"
                                 if candidate.get("scope_status") == "outside_agreed_scope"
                                 else f"{candidate.get('commitment') or 'committed'} scope")})

    # The greedy walk overshoots: it takes the cheap outside-scope cut first, then a large one
    # that would have sufficed alone, and the client is asked to give up something for nothing.
    # Put back everything the target did not actually need, hardest-to-lose first.
    restored = []
    if dropped and achieved <= target:
        kept = {f["id"] for f in features} - dropped
        for candidate in sorted((c for c in candidates if c["id"] in dropped),
                                key=lambda c: (-c["priority"],
                                               1 if c.get("scope_status") == "outside_agreed_scope" else 0,
                                               c["saving"] or 0)):
            fid = candidate["id"]
            if fid not in dropped:
                continue
            needs = {d["feature_id"] if isinstance(d, dict) else d
                     for d in (by_feature[fid].get("depends_on") or [])}
            if needs - kept:
                continue  # it cannot come back without what it was built on
            trial = price(apply_mutations(scope, drops=sorted(dropped - {fid})), model, options, est)
            if trial["total_hours"]["likely"] <= target:
                dropped.discard(fid)
                kept.add(fid)
                achieved = trial["total_hours"]["likely"]
                restored.append(fid)
        # Re-walk what survived, so every cumulative figure stays a real re-price rather than a
        # leftover from a step that was later partly undone.
        rebuilt, running = [], set()
        for step in steps:
            group = [d for d in step["drop"] if d in dropped]
            if not group:
                continue
            running |= set(group)
            after = price(apply_mutations(scope, drops=sorted(running)), model, options, est)
            rebuilt.append({"drop": sorted(group),
                            "cumulative_likely": after["total_hours"]["likely"],
                            "cumulative_saving": round(baseline_likely - after["total_hours"]["likely"], 1),
                            "reason": step["reason"]})
        steps = rebuilt

    unreachable = None
    if achieved > target:
        unreachable = (
            f"{target}h is below what this scope can reach. Cutting everything droppable leaves "
            f"{round(achieved, 1)}h, because planning, environments, QA and client overhead are "
            f"paid on whatever ships. The conversation is about a different scope, not a smaller "
            f"version of this one."
        )

    return {
        "target_hours": target,
        "baseline_likely": baseline_likely,
        "achieved_likely": round(achieved, 1),
        "under_target": achieved <= target,
        "unreachable_reason": unreachable,
        "proposed_drop": sorted(dropped),
        "features_lost": len(dropped),
        "steps": steps,
        "restored_as_unnecessary": restored,
        "candidates": sorted(candidates, key=lambda c: (c["saving"] is None, -(c["saving"] or 0))),
        "why": ("Every figure is a re-price of the remaining scope, not a subtraction. The walk "
                "empties the easiest tier first — outside-agreed-scope, then speculative, implied, "
                "committed — and inside a tier takes the smallest cut that closes the gap, so it "
                "disturbs as little as possible. It is a proposal: the candidate table carries every "
                "alternative, and what is actually worth keeping is not something a rule can know."),
    }


def parse_retag(raw):
    try:
        fid, rest = raw.split(":", 1)
        axis, value = rest.split("=", 1)
    except ValueError:
        raise Refused(f"--retag wants FEATURE:axis=value, got '{raw}'")
    return fid.strip(), axis.strip(), value.strip()


def parse_set(raw):
    try:
        key, value = raw.split("=", 1)
    except ValueError:
        raise Refused(f"--set wants key=value, got '{raw}'")
    key = key.strip()
    if key not in PROFILE_KEYS:
        raise Refused(f"'{key}' is not a profile input — one of {list(PROFILE_KEYS)}")
    value = value.strip()
    return key, int(value) if key == "team_size" else value


def run(args):
    est = engine(args.engine)
    estimate = json.loads(Path(args.estimate).read_text(encoding="utf-8"))

    snapshot = estimate.get("cost_model_snapshot")
    if args.cost_model:
        model = json.loads(Path(args.cost_model).read_text(encoding="utf-8"))
    elif snapshot:
        model = snapshot
    else:
        raise Refused(
            "this estimate carries no cost_model_snapshot, so the model that produced it is gone. "
            "Pass --cost-model deliberately, knowing the comparison then mixes a scope change with "
            "a model change."
        )

    overrides = dict(parse_set(s) for s in args.set or [])
    options = options_from(estimate, model, est, overrides)
    scope = est.inventory_from(estimate)

    # The parity gate. Re-price the untouched scope and require the headline back. Every figure
    # below is a difference against this, so if it does not reproduce, nothing below means what
    # it says.
    baseline_options = options_from(estimate, model, est)
    baseline = price(scope, model, baseline_options, est)
    headline = estimate["total_hours"]["likely"]
    drift = round(baseline["total_hours"]["likely"] - headline, 2)
    tolerance = max(0.1, abs(headline) * 0.001)
    reproduced = abs(drift) <= tolerance

    if not reproduced and not args.cost_model:
        raise Refused(
            f"re-pricing this estimate's own scope under its own snapshot gives "
            f"{baseline['total_hours']['likely']}h against a recorded {headline}h. Every scenario "
            f"figure is a difference against that baseline, so a drift of {drift}h would be "
            f"reported as the effect of the change. Something has edited the estimate by hand, or "
            f"the engine has moved since it was priced."
        )

    result = {
        "ok": True,
        "project": estimate.get("project"),
        "engine": str(Path(args.engine) if args.engine else DEFAULT_ENGINE),
        "model_source": "cost-model.json (deliberate override)" if args.cost_model
                        else "the estimate's own snapshot",
        "baseline": {"recorded_likely": headline,
                     "repriced_likely": baseline["total_hours"]["likely"],
                     "drift": drift, "reproduced": reproduced},
        "inputs": {k: baseline_options[k] for k in ("team_name", "stack", "qa_platform",
                                                    "engagement", "team_size")},
    }
    if args.cost_model and not reproduced:
        result["model_shift"] = (
            f"Under the model passed in, this same scope prices at "
            f"{baseline['total_hours']['likely']}h against the {headline}h recorded. That "
            f"{drift}h is the model moving, not the scenario — read it separately."
        )
    if overrides:
        result["overrides"] = overrides

    if args.to_budget is not None:
        result["cutline"] = cutline(baseline, scope, model, options, est, args.to_budget)
        return result

    additions = []
    if args.add_file:
        loaded = json.loads(Path(args.add_file).read_text(encoding="utf-8"))
        additions = loaded if isinstance(loaded, list) else loaded.get("features", [loaded])

    retags = [parse_retag(r) for r in args.retag or []]
    drops = list(args.drop or [])
    if drops and args.with_dependents:
        drops = sorted(closure(drops, scope["features"]))

    variant = price(apply_mutations(scope, drops, retags, additions, est.AXES), model, options, est)
    result["mutations"] = {"dropped": drops, "retagged": [f"{f}:{a}={v}" for f, a, v in retags],
                           "added": [f.get("id") for f in additions],
                           "profile_overrides": overrides or None}
    result["comparison"] = compare(baseline, variant, set(drops), scope["features"])
    # Per-feature hours, not just the headline. A retag or a team change moves every feature at
    # once, and a scenario total is exactly the number that gets said out loud in a negotiation —
    # so it has to break down the same way the original estimate does, or the agent is asserting
    # a figure it cannot decompose.
    before_hours = {f["id"]: f["hours"] for f in baseline["features"]}
    result["scenario_estimate"] = {
        "total_hours": totals(variant),
        "by_phase": phase_hours(variant),
        "by_role": role_hours(variant),
        "features_priced": len(variant["features"]),
        "features": [{
            "id": f["id"], "name": f["name"], "hours": f["hours"],
            "was": before_hours.get(f["id"]),
            "change": (None if f["id"] not in before_hours
                       else round(f["hours"] - before_hours[f["id"]], 1)),
            "dominant_component": max(f["component_hours"], key=f["component_hours"].get),
            "component_hours": f["component_hours"],
            "tags": f["tags"],
        } for f in variant["features"]],
        "dropped": [{"id": fid, "was": before_hours[fid]} for fid in sorted(set(drops))
                    if fid in before_hours],
    }
    return result


def main():
    ap = argparse.ArgumentParser(
        description="Re-price an estimate under a changed scope, tag set, team or budget.",
        epilog="Exit codes: 0 done, 1 refused, 2 unreadable input.",
    )
    ap.add_argument("estimate", help="estimate.json, or a ledger entry (which contains one)")
    ap.add_argument("--drop", nargs="+", metavar="ID", help="feature ids to remove from scope")
    ap.add_argument("--with-dependents", action="store_true",
                    help="also drop everything that depends on the dropped features")
    ap.add_argument("--retag", nargs="+", metavar="F:axis=value",
                    help="change a classification, e.g. F3:review_tier=routine")
    ap.add_argument("--verbose", action="store_true",
                    help="report each engine call to stderr; --to-budget makes dozens")
    ap.add_argument("--set", nargs="+", metavar="key=value",
                    help=f"override a profile input: {', '.join(PROFILE_KEYS)}")
    ap.add_argument("--add-file", metavar="PATH",
                    help="JSON file holding one feature object, or a list, in inventory shape")
    ap.add_argument("--to-budget", type=float, metavar="HOURS",
                    help="find cuts that bring the estimate under this many hours")
    ap.add_argument("--cost-model", metavar="PATH",
                    help="re-price under this model instead of the estimate's own snapshot; "
                         "mixes a model change into the comparison, so it is never the default")
    ap.add_argument("--engine", metavar="PATH", help="est-estimate's estimate.py, if not a sibling")
    ap.add_argument("-o", "--output", help="write the result here instead of stdout")
    args = ap.parse_args()

    if not any([args.drop, args.retag, args.set, args.add_file, args.to_budget is not None]):
        print(json.dumps({"ok": False, "error": "nothing to test — give at least one of --drop, "
                                                "--retag, --set, --add-file or --to-budget"}, indent=2))
        return 1

    VERBOSE[0] = args.verbose

    def refuse(message, code):
        # The JSON envelope on stdout is the module-wide contract; stderr is so a human running
        # this in a terminal sees the reason without piping through a formatter.
        print(json.dumps({"ok": False, "error": message}, indent=2))
        print(f"scenario.py: {message}", file=sys.stderr)
        return code

    try:
        result = run(args)
    except Refused as exc:
        return refuse(str(exc), 1)
    except (OSError, json.JSONDecodeError) as exc:
        return refuse(str(exc), 2)
    except (KeyError, ValueError) as exc:
        return refuse(f"the engine could not price that scenario: {exc}. A retagged value must "
                      f"exist in the cost model.", 1)

    if args.verbose:
        print(f"scenario.py: {PRICED[0]} engine calls", file=sys.stderr)

    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
        print(json.dumps({"ok": True, "scenario": args.output,
                          "total_hours": (result.get("scenario_estimate") or {}).get("total_hours")
                          or {"achieved": (result.get("cutline") or {}).get("achieved_likely")}},
                         indent=2))
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
