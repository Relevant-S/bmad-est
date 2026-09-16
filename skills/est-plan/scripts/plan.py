#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Turn a priced estimate into staffed, scored delivery options.

Consumes a finished `estimate.json`. It never re-extracts scope and it never re-classifies a
story: the priced scope is one fact, and what this produces is a set of readings of it.

Every option carries its OWN estimate. The same scope sequenced and staffed differently costs
differently — architect is `setup + a capped weekly rate` and overhead is `rate x weeks x
people`, so a plan that ran longer genuinely costs more — and re-presenting one set of numbers
under three timelines would be reporting a difference the arithmetic does not contain. So each
option's span goes back through the pricing engine and comes out as a complete role table.

    uv run scripts/plan.py <estimate.json> [-o plan.json] [--team dev=2,qa=1] [--deadline 16]

Exit 0 when at least one option is feasible, 1 when none is.
"""

import argparse
import copy
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EST = HERE.parent.parent / "est-estimate" / "scripts"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


est = _load("estimate", EST / "estimate.py")
schedule = _load("schedule", HERE / "schedule.py")
staffing = _load("staffing", HERE / "staffing.py")
archetypes = _load("archetypes", HERE / "archetypes.py")

ROLE_LABEL = {"ba": "BA", "ux": "UX", "dev": "Dev", "qa": "QA",
              "devops": "DevOps", "architect": "Architect"}


def build_team(shape, model, roster):
    """The people, named the way a reader would name them.

    Anyone in the supplied roster is already on the project and pays no ramp. Everyone beyond
    it is new, and their ramp is charged out of their own capacity before they deliver — which
    is what stops a plan adding a body in the final fortnight and booking their whole output.
    """
    ramp = float(((model.get("staffing") or {}).get("ramp_hours") or {}).get("likely") or 0.0)
    rate = model["calendar"]["hours_per_person_week"]
    team = []
    for role, count in shape.items():
        existing = int((roster or {}).get(role, 0))
        for i in range(1, count + 1):
            label = ROLE_LABEL.get(role, role.title())
            name = label if count == 1 else f"{label} {i}"
            team.append(schedule.Assignee(role, name, rate, ramp, on_project=i <= existing))
    return team


def price_for(estimate, model, span):
    """Re-price the whole estimate against this option's calendar.

    The scope, the classification and every story's hours are untouched — `inventory_from`
    hands back exactly what was priced, and the only thing that differs is the span. So the
    difference between two options is attributable to their schedules and to nothing else,
    which is the claim the output makes and therefore the claim the code has to earn.
    """
    inventory = est.inventory_from(estimate)
    options = est.options_from(estimate, model)
    options["span"] = span
    return est.build_estimate(inventory, copy.deepcopy(model), options)


def feasibility(sched, priced, estimate, model):
    """Whether this plan closes in the real world. A failure disqualifies the option."""
    checks, failures = [], []
    rate = sched["effective_hours_per_person_week"]
    floor_weeks = schedule.chain_floor_weeks(estimate, model, rate)

    if sched["weeks"] + 1e-3 < floor_weeks:
        failures.append(f"claims {sched['weeks']:.1f} weeks against a {floor_weeks:.1f}-week "
                        f"dependency chain. Adding people cannot beat a chain.")
    checks.append(f"span {sched['weeks']:.1f}w clears the {floor_weeks:.1f}w critical path "
                  f"({len((estimate.get('dependencies') or {}).get('chain') or [])} linked stories)")

    for person in sched["team"]:
        if person["utilisation"] > 1.0001:
            failures.append(f"{person['name']} is booked to {person['utilisation']:.0%}")
        if person["ramp_hours"] and person["items"]:
            # Compared against the week the simulator actually finished charging the ramp, not
            # against a figure recomputed from rounded hours and a rounded rate — the first
            # version of this check failed every plan by a thousandth of a week.
            if person["starts_week"] + 1e-6 < person["ramp_until_week"]:
                failures.append(f"{person['name']} delivers in week {person['starts_week']:.2f} "
                                f"before their ramp closes in week {person['ramp_until_week']:.2f}")
    checks.append("no assignee exceeds 100% and every ramp is paid before first delivery")

    for person in sched["team"]:
        for item in person["items"]:
            if item["start_week"] < -1e-9:
                failures.append(f"{person['name']} starts {item['label']} before week zero")
    checks.append("no work starts before its predecessors finish")

    if sched["unresolved_dependencies"]:
        failures.append(f"{len(sched['unresolved_dependencies'])} dependencies point at stories "
                        f"scheduled later — the stated epic sequence contradicts them")

    return {"feasible": not failures, "checks": checks, "failures": failures,
            "critical_path_weeks": round(floor_weeks, 2)}


def score(option, peers, model, deadline=None):
    """The 0-10 fit score, and the six numbers it is made of.

    Each sub-score is reported beside the total. A recommendation whose arithmetic the reader
    cannot check is a recommendation nobody can argue with, and the weights live in the cost
    model so they can be re-weighted by somebody who disagrees.
    """
    weights = ((model.get("staffing") or {}).get("scoring") or {}).get("weights") or {}
    spans = [p["schedule"]["weeks"] for p in peers] or [option["schedule"]["weeks"]]
    costs = [p["estimate"]["total_hours"]["likely"] for p in peers] or [1.0]
    best_span, best_cost = min(spans) or 1.0, min(costs) or 1.0
    weeks = option["schedule"]["weeks"]
    cost = option["estimate"]["total_hours"]["likely"]

    if deadline:
        duration = 10.0 if weeks <= deadline else max(0.0, 10.0 - 10.0 * (weeks - deadline) / deadline)
        duration_why = (f"{weeks:.1f}w against a {deadline:.0f}w target"
                        + ("" if weeks <= deadline else f" — over by {weeks - deadline:.1f}w"))
    else:
        duration = 10.0 * best_span / weeks if weeks else 0.0
        duration_why = f"{weeks:.1f}w against the fastest option's {best_span:.1f}w"

    cost_score = 10.0 * best_cost / cost if cost else 0.0
    util = [p["utilisation"] for p in option["schedule"]["team"]]
    mean_util = sum(util) / len(util) if util else 0.0
    idle = sum(max(0.0, 1.0 - u) for u in util) * weeks * option["schedule"]["effective_hours_per_person_week"]

    size = len(option["schedule"]["team"])
    drag = option["schedule"]["coordination_drag_applied"]
    story_hours = sum(f["hours"] for f in option["estimate"]["features"]
                      if f.get("origin") != "standing") or 1.0
    drift = option["schedule"]["drift_hours"]
    band = option["estimate"]["confidence"]["band_width_pct"]
    widest = max((p["estimate"]["confidence"]["band_width_pct"] for p in peers), default=band) or 1.0

    parts = {
        "duration": {"score": round(min(10.0, duration), 2), "rests_on": duration_why},
        "cost": {"score": round(min(10.0, cost_score), 2),
                 "rests_on": f"{cost:.0f} h against the cheapest option's {best_cost:.0f} h"},
        "utilisation": {"score": round(min(10.0, 10.0 * mean_util), 2),
                        "rests_on": f"team averages {mean_util:.0%} occupied; {idle:.0f} idle hours"},
        # Scored as the throughput each person keeps, not as ten minus a percentage — the
        # latter hit zero at four people and stayed there, which made a real gradient look
        # like a wall and let coordination drop out of the comparison entirely.
        "coordination": {"score": round(max(0.0, 10.0 * (1.0 - drag)), 2),
                         "rests_on": f"{size} people, each keeping {1 - drag:.0%} of their "
                                     f"throughput after coordination"},
        "drift": {"score": round(max(0.0, 10.0 - 10.0 * drift / story_hours), 2),
                  "rests_on": (f"{drift:.0f} h of build booked against unsettled specs, "
                               f"{drift / story_hours:.1%} of story work")},
        "confidence": {"score": round(min(10.0, 10.0 * widest / band if band else 10.0), 2),
                       "rests_on": f"band is ±{band:.1f}% of the total"},
    }
    total = sum(parts[k]["score"] * weights.get(k, 0.0) for k in parts)
    denom = sum(weights.get(k, 0.0) for k in parts) or 1.0
    return {"fit": round(total / denom, 2), "parts": parts,
            "weights": {k: weights.get(k, 0.0) for k in parts}}


def build_plan(estimate, model, roster=None, deadline=None, only=None):
    # The guardrail judges a candidate team against a real pass over the dependency graph, and
    # it is handed the most permissive archetype to run it on: refusing a shape on its best
    # case is a strong refusal, while approving one on its worst would deny the plan people it
    # could have used.
    def trial(shape):
        policy = archetypes.POLICIES["pipelined"](estimate, model)
        return schedule.simulate(estimate, model, build_team(shape, model, roster or {}), policy)

    swept = staffing.sweep(estimate, model, roster, simulate=trial)
    options = []
    for name in archetypes.NAMES:
        if only and name not in only:
            continue
        policy = archetypes.POLICIES[name](estimate, model)
        for shape in swept["shapes"]:
            team = build_team(shape, model, swept["roster"])
            sched = schedule.simulate(estimate, model, team, policy)
            basis = (f"{name} schedule over the dependency graph; "
                     f"{', '.join(f'{n}x {ROLE_LABEL.get(r, r)}' for r, n in sorted(shape.items()))}; "
                     f"{schedule.mean_concurrent_headcount(sched)} people on the project on average. "
                     f"Weeks are relative — week 1 is whenever this starts.")
            span = schedule.span_for_pricing(sched, model, basis)
            priced = price_for(estimate, model, span)
            option = {
                "id": f"{name}-{'-'.join(f'{r}{n}' for r, n in sorted(shape.items()))}",
                "archetype": name,
                "what_it_is": archetypes.DESCRIPTIONS[name],
                "team_shape": shape,
                "schedule": sched,
                "span": span,
                "estimate": priced,
                "risks": [{"risk": r, "mitigation": m} for r, m in archetypes.RISKS[name]],
            }
            option["feasibility"] = feasibility(sched, priced, estimate, model)
            options.append(option)

    viable = [o for o in options if o["feasibility"]["feasible"]]
    for option in options:
        option["score"] = score(option, viable or options, model, deadline)
    viable.sort(key=lambda o: -o["score"]["fit"])

    return {
        "schema_version": "1.0",
        "project": estimate.get("project"),
        # Carried so the renderer can name an epic on a Gantt row without reopening the
        # estimate beside it — the same reason estimate.json carries them for its own renders.
        "epics": estimate.get("epics") or [],
        "estimate": {"generated": estimate.get("generated"),
                     "total_hours": estimate.get("total_hours"),
                     "why_it_differs": ("The estimate's own hours rest on a nominal team shape "
                                        "nobody chose. Each option below re-prices the same "
                                        "scope against the calendar its own schedule produces — "
                                        "architect and the ceremony share of BA and dev move "
                                        "with the span, and nothing else does.")},
        "inputs": {"roster": swept["roster"], "deadline_weeks": deadline,
                   "headcount": ("An output, not a constraint. The sweep explores team shapes "
                                 "and each addition below is justified or refused on the "
                                 "backlog's own dependency graph."),
                   "calendar": "Weeks are relative. This plan carries no dates."},
        "staffing": {"decisions": swept["decisions"], "oversized_roster": swept["oversized"],
                     "shapes_considered": swept["shapes"]},
        "recommended": viable[0]["id"] if viable else None,
        "options": sorted(options, key=lambda o: -o["score"]["fit"]),
    }


def parse_team(value):
    out = {}
    for part in (value or "").split(","):
        part = part.strip()
        if not part:
            continue
        role, _, count = part.partition("=")
        out[role.strip()] = int(count or 1)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("estimate", help="path to estimate.json")
    ap.add_argument("-o", "--output", help="write plan.json here instead of stdout")
    ap.add_argument("--cost-model", help="cost model; defaults to the one the estimate recorded")
    ap.add_argument("--team", help="people already on the project, e.g. dev=2,qa=1. A floor, "
                                   "never a ceiling — the sweep may still add to it")
    ap.add_argument("--deadline", type=float, help="target span in WEEKS (not a date)")
    ap.add_argument("--archetype", action="append", choices=list(archetypes.NAMES),
                    help="restrict to these archetypes; repeatable")
    args = ap.parse_args()

    estimate = json.loads(Path(args.estimate).read_text(encoding="utf-8"))
    model = (json.loads(Path(args.cost_model).read_text(encoding="utf-8"))
             if args.cost_model else estimate.get("cost_model_snapshot"))
    if not model:
        print(json.dumps({"ok": False, "error": "no cost model: the estimate carries no snapshot "
                                                "and --cost-model was not given"}, indent=2))
        return 2
    if not model.get("staffing"):
        print(json.dumps({"ok": False, "error":
                          "this cost model has no `staffing` block, so no headcount can be "
                          "justified or refused. Migrate it: est-estimate/scripts/"
                          "migrate-cost-model.py"}, indent=2))
        return 2

    plan = build_plan(estimate, model, parse_team(args.team), args.deadline, args.archetype)
    text = json.dumps(plan, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
        print(json.dumps({"ok": True, "options": len(plan["options"]),
                          "recommended": plan["recommended"],
                          "written": args.output}, indent=2))
    else:
        print(text)
    return 0 if plan["recommended"] else 1


if __name__ == "__main__":
    sys.exit(main())
