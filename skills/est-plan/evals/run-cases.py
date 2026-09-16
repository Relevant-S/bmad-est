#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Adversarial cases for est-plan — the conclusions, not the arithmetic.

These are not unit tests. Each case is a backlog shape whose *emergent* answer is the claim
being checked: that a chain cannot be hired away, that a bigger team can be the wrong team,
that a roster is a floor and not a ceiling, that the fastest option is not automatically the
recommended one. Unit tests protect the simulation; these protect the advice, which is where
a plausible-looking plan goes wrong.

Every case runs against the SHIPPED cost model, not a fixture model, because the coefficients
that decide a refusal are the ones a client will be told about.

    uv run evals/run-cases.py [--case NAME] [--quiet]

Exit 0 when every case holds, 1 when any fails.
"""

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EST = ROOT / "est-estimate"
PLAN = ROOT / "est-plan"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


est = load("estimate", EST / "scripts" / "estimate.py")
plan_mod = load("plan", PLAN / "scripts" / "plan.py")
staffing = load("staffing", PLAN / "scripts" / "staffing.py")
MODEL = json.loads((EST / "assets" / "cost-model.seed.json").read_text(encoding="utf-8"))


def tag(v):
    return {"value": v, "why": "eval fixture", "status": "inferred"}


def feature(fid, epic="E1", size="M", depends_on=()):
    return {"id": fid, "name": f"Feature {fid}", "description": f"{fid} does a thing.",
            "epic_id": epic, "commitment": "committed",
            "citations": [{"source_id": "S1", "location": "§1", "quote": f"{fid} required."}],
            "surfaces": ["backend", "frontend", "design", "infra", "data"],
            "depends_on": [{"feature_id": d, "inferred": False, "evidence": "stated"}
                           for d in depends_on],
            "open_questions": [],
            "tags": {"size_band": tag(size), "compressibility": tag("high"),
                     "review_tier": tag("routine"), "clarity": tag("medium"),
                     "novelty": tag("standard")}}


def priced(features):
    epics = sorted({f["epic_id"] for f in features})
    inventory = {"schema_version": "1.1", "generated": "2026-09-16T00:00:00Z",
                 "project": "Eval", "granularity": "project", "working_language": "en",
                 "sources": [{"id": "S1", "path": "d.md", "doc_type": "sow", "language": "en"}],
                 "epics": [{"id": e, "name": f"Epic {e}", "origin": "source", "sequence": i + 1,
                            "sequence_why": "stated", "citations": []}
                           for i, e in enumerate(epics)],
                 "features": features, "not_scope": [], "conflicts": [], "assumptions": [],
                 "completeness_signals": {}}
    options = {"mode": "presale", "team": MODEL["team_profiles"]["balanced"],
               "team_name": "balanced", "stack": "standard_saas", "qa_platform": "web",
               "engagement": "standard", "team_size": None, "granularity": "project",
               "input_completeness": 0.75, "inventory_path": "eval.json",
               "generated": "2026-09-16T00:00:00Z"}
    return est.build_estimate(inventory, json.loads(json.dumps(MODEL)), options)


def chain(n, size="L"):
    return [feature(f"F{i}", epic=f"E{(i - 1) // 5 + 1}", size=size,
                    depends_on=() if i == 1 else (f"F{i - 1}",)) for i in range(1, n + 1)]


def wide(n, epics=5, size="L"):
    return [feature(f"F{i}", epic=f"E{i % epics + 1}", size=size) for i in range(1, n + 1)]


# --- the cases ---------------------------------------------------------------

def case_a_chain_cannot_be_hired_away():
    """A long backlog that is one chain. There are plenty of hours; nobody can help.

    A Gantt is the single most likely place for this to go wrong, because drawing more bars
    side by side is exactly how a plan pretends a chain is parallel.
    """
    estimate = priced(chain(16))
    plan = plan_mod.build_plan(estimate, MODEL)
    shapes = plan["staffing"]["shapes_considered"]
    refused = [d for d in plan["staffing"]["decisions"] if not d["allowed"]]
    spans = sorted(o["schedule"]["weeks"] for o in plan["options"])
    return plan, [
        ("no second person is proposed at all", len(shapes) == 1),
        ("every proposed addition was refused", bool(refused) and
         all(not d["allowed"] for d in plan["staffing"]["decisions"])),
        ("a refusal names its idle hours", any(d["idle_hours"] > 0 for d in refused)),
        ("no option beats the dependency chain", all(
            o["schedule"]["weeks"] + 1e-3 >= o["feasibility"]["critical_path_weeks"]
            for o in plan["options"])),
        ("the options do not differ wildly in span", spans[-1] / max(spans[0], 1e-9) < 2.5),
    ]


def case_a_bigger_team_can_be_the_wrong_team():
    """Where parallelism exists, the sweep should still not recommend everybody it can hire.

    A model with no coordination cost can only ever return the largest team allowed, which is
    not advice. The claim here is that cost rises with headcount even where the calendar falls.
    """
    estimate = priced(wide(36, epics=6))
    plan = plan_mod.build_plan(estimate, MODEL)
    by_size = sorted(plan["options"], key=lambda o: sum(o["team_shape"].values()))
    small, large = by_size[0], by_size[-1]
    per_head = [(sum(o["team_shape"].values()), o["schedule"]["effective_hours_per_person_week"])
                for o in plan["options"]]
    return plan, [
        ("more than one team shape was explored", len(plan["staffing"]["shapes_considered"]) > 1),
        ("a bigger team finishes sooner here", large["schedule"]["weeks"] < small["schedule"]["weeks"]),
        ("and each person on it delivers less per week",
         min(r for _, r in per_head) < max(r for _, r in per_head)),
        ("the sweep stopped before the cap, on the guardrail",
         any(not d["allowed"] for d in plan["staffing"]["decisions"])),
    ]


def case_the_roster_is_a_floor_not_a_ceiling():
    """A user who names two developers is telling us where to start, not where to stop."""
    # Deliberately a backlog wide enough that a third developer is genuinely justified. The
    # claim under test is that a roster is a FLOOR — not that any roster gets added to, which
    # would be the guardrail failing rather than the roster rule working.
    estimate = priced(wide(90, epics=10))
    plan = plan_mod.build_plan(estimate, MODEL, roster={"dev": 2})
    devs = [o["team_shape"].get("dev", 0) for o in plan["options"]]
    on_project = [p for o in plan["options"] for p in o["schedule"]["team"] if p["role"] == "dev"]
    return plan, [
        ("no option staffs fewer developers than the user has", min(devs) >= 2),
        ("at least one option adds to them", max(devs) > 2),
        ("the two they already have pay no ramp",
         any(p["on_project"] and p["ramp_hours"] == 0.0 for p in on_project)),
        ("the plan says headcount is an output", "not a constraint" in plan["inputs"]["headcount"]),
    ]


def case_an_oversized_roster_is_flagged_not_absorbed():
    """Six developers on a backlog that holds work for one. Somebody is being billed to sit
    still, and a plan that quietly staffs around it is how that is discovered in week 9."""
    estimate = priced(wide(5, epics=2, size="XS"))
    plan = plan_mod.build_plan(estimate, MODEL, roster={"dev": 6})
    flagged = plan["staffing"]["oversized_roster"]
    return plan, [
        ("the oversized roster is reported", bool(flagged)),
        ("it names the idle hours", all(row["idle_hours"] > 0 for row in flagged)),
        ("it says how many would be busy",
         all(row["sustainable_count"] < row["supplied"] for row in flagged)),
    ]


def case_the_fastest_option_is_not_automatically_recommended():
    """If it were, the other five sub-scores would be decoration and the whole staffing
    argument would collapse into 'hire everybody, pipeline everything'."""
    estimate = priced(wide(30, epics=5))
    tight = plan_mod.build_plan(estimate, MODEL, deadline=2)
    loose = plan_mod.build_plan(estimate, MODEL, deadline=80)
    return loose, [
        ("a tight deadline and a loose one do not score the same",
         [o["score"]["fit"] for o in tight["options"]] !=
         [o["score"]["fit"] for o in loose["options"]]),
        ("with a loose deadline, cost matters",
         loose["options"][0]["score"]["parts"]["cost"]["score"] > 0),
        ("every sub-score names the number it rests on",
         all(part["rests_on"].strip()
             for o in loose["options"] for part in o["score"]["parts"].values())),
    ]


def case_overlapping_costs_something_and_it_is_measured():
    """Sequential has to be the zero-drift baseline. If it ever scores above zero the staging
    has stopped working and every other option's risk paragraph is measured against nothing."""
    estimate = priced(chain(6) + wide(14, epics=3))
    plan = plan_mod.build_plan(estimate, MODEL)
    by_type = {}
    for option in plan["options"]:
        by_type.setdefault(option["archetype"], []).append(option["schedule"]["drift_hours"])
    return plan, [
        ("sequential drifts by nothing, in every shape",
         all(d == 0.0 for d in by_type.get("sequential", [1]))),
        ("pipelining costs measurable drift", max(by_type.get("pipelined", [0])) > 0.0),
        ("the risk paragraph offers a mitigation for it",
         all(row["mitigation"].strip()
             for o in plan["options"] for row in o["risks"])),
    ]


def case_a_schedule_reprices_the_calendar_and_not_the_scope():
    """The front-page claim. If a schedule can move a story's hours, the comparison the client
    is being asked to make is between two different scopes wearing the same name."""
    estimate = priced(wide(24, epics=4))
    plan = plan_mod.build_plan(estimate, MODEL)
    a, b = plan["options"][0], plan["options"][-1]
    same = all(
        abs(a["estimate"]["project_components"][k]["hours"]
            - b["estimate"]["project_components"][k]["hours"]) < 1e-6
        for k in ("qa", "planning_agent", "planning_review"))
    delta = b["estimate"]["total_hours"]["likely"] - a["estimate"]["total_hours"]["likely"]
    moved = sum(b["estimate"]["project_components"][k]["hours"]
                - a["estimate"]["project_components"][k]["hours"]
                for k in ("architect", "overhead"))
    return plan, [
        ("story hours are identical across options",
         [f["hours"] for f in a["estimate"]["features"]] ==
         [f["hours"] for f in b["estimate"]["features"]]),
        ("QA and planning are identical too", same),
        ("the whole difference is architect plus ceremony", abs(delta - moved) < 0.35),
        ("and the options really do differ",
         abs(a["schedule"]["weeks"] - b["schedule"]["weeks"]) > 0.1),
    ]


def case_no_plan_hardens_into_a_date():
    """Two standing rules in this module forbid it, and a Gantt is precisely where it happens."""
    import re
    estimate = priced(wide(12, epics=3))
    plan = plan_mod.build_plan(estimate, MODEL)
    blob = json.dumps([{"schedule": o["schedule"], "span": o["span"]} for o in plan["options"]])
    return plan, [
        ("no schedule or span carries a date", not re.search(r"\b\d{4}-\d{2}-\d{2}\b", blob)),
        ("the plan says weeks are relative", "relative" in plan["inputs"]["calendar"].lower()),
        ("every option's basis repeats it",
         all("relative" in o["span"]["basis"] for o in plan["options"])),
    ]


CASES = {
    "a-chain-cannot-be-hired-away": case_a_chain_cannot_be_hired_away,
    "a-bigger-team-can-be-the-wrong-team": case_a_bigger_team_can_be_the_wrong_team,
    "the-roster-is-a-floor-not-a-ceiling": case_the_roster_is_a_floor_not_a_ceiling,
    "an-oversized-roster-is-flagged": case_an_oversized_roster_is_flagged_not_absorbed,
    "fastest-is-not-automatically-recommended": case_the_fastest_option_is_not_automatically_recommended,
    "overlapping-costs-something-measured": case_overlapping_costs_something_and_it_is_measured,
    "reprices-the-calendar-not-the-scope": case_a_schedule_reprices_the_calendar_and_not_the_scope,
    "no-plan-hardens-into-a-date": case_no_plan_hardens_into_a_date,
}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--case", action="append", choices=sorted(CASES))
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    failures = 0
    names = args.case or sorted(CASES)
    for name in names:
        plan, checks = CASES[name]()
        held = [label for label, ok in checks if ok]
        broke = [label for label, ok in checks if not ok]
        if broke:
            failures += 1
            print(f"FAIL  {name} — {len(held)}/{len(checks)} held")
            for label in broke:
                print(f"        ✗ {label}")
        elif not args.quiet:
            best = plan.get("recommended") or "none feasible"
            print(f"ok    {name} — {len(held)}/{len(checks)} held ({best})")
    print(f"\n{len(names) - failures}/{len(names)} cases fully held")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
