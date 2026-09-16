#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Tests for schedule.py — the resource-constrained pass over the dependency graph.

The claims here are about DELIVERABILITY, not arithmetic. A schedule that books somebody onto
blocked work, or lets a new joiner deliver on their first morning, or beats its own dependency
chain by hiring, is a plan that closes on paper and not in the world. Each of those has its
own test because each of them was, at some point in building this, what the code did.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fixtures as F  # noqa: E402

FULL = {"dev": 1, "ba": 1, "ux": 1, "qa": 1, "devops": 1}


class NobodyWorksOnBlockedWork(unittest.TestCase):
    def test_a_story_is_never_built_before_the_story_it_depends_on_is_built(self):
        """The whole point of reading the dependency graph. A plan that ignores it is a plan
        that has a developer waiting for an API that does not exist yet, discovered in week 6.

        Scoped to the build, deliberately: dependencies gate what gets BUILT. A BA specifying
        F102 while F101 is still in flight is not a scheduling error, it is how a pipeline
        works, and asserting otherwise would forbid the archetype the plan exists to offer."""
        estimate = F.priced(F.chain(8))
        sched = F.run(estimate, dict(FULL, dev=3))
        built = {}
        starts = {}
        for person in sched["team"]:
            for item in person["items"]:
                if item["component"] == "build":
                    built[item["story_id"]] = max(built.get(item["story_id"], 0.0),
                                                  item["finish_week"])
                if item["component"] == "build":
                    starts[item["story_id"]] = min(starts.get(item["story_id"], 1e9),
                                                   item["start_week"])
        for feature in estimate["features"]:
            for dep in feature.get("depends_on") or []:
                if dep in built and feature["id"] in starts:
                    self.assertGreaterEqual(starts[feature["id"]] + 1e-6, built[dep],
                                            f"{feature['id']} was built before {dep} was")

    def test_a_story_is_specified_before_it_is_built_and_reviewed_after(self):
        """Component order is read off the cost model's own component_shares and role_weights.
        Inventing a second opinion about who blocks whom would put two orderings in the module."""
        sched = F.run(F.priced(F.wide(12)), FULL)
        seen = {}
        for person in sched["team"]:
            for item in person["items"]:
                seen.setdefault((item["story_id"], item["component"]), []).append(item)
        for (story, component), rows in seen.items():
            previous = F.schedule._previous(component)
            if previous and (story, previous) in seen:
                self.assertGreaterEqual(min(r["start_week"] for r in rows) + 1e-6,
                                        max(r["finish_week"] for r in seen[(story, previous)]),
                                        f"{story} {component} overlapped its {previous}")


class AddingPeopleCannotBeatAChain(unittest.TestCase):
    def test_a_single_chain_does_not_get_shorter_with_three_developers(self):
        """The module's oldest scheduling claim, and the one a Gantt is most likely to break:
        drawing more bars side by side is exactly how a plan pretends a chain is parallel."""
        estimate = F.priced(F.chain(12))
        one = F.run(estimate, FULL)["weeks"]
        three = F.run(estimate, dict(FULL, dev=3))["weeks"]
        self.assertGreater(three, one * 0.8,
                           "three developers collapsed a strictly serial chain")

    def test_two_independent_streams_do_get_shorter(self):
        """The other half of the claim. If parallelism never helped, the guardrail would be
        refusing people for a reason that has nothing to do with the graph."""
        estimate = F.priced(F.two_streams(per=10))
        one = F.run(estimate, FULL)["weeks"]
        two = F.run(estimate, dict(FULL, dev=2))["weeks"]
        self.assertLess(two, one, "a second developer bought nothing on two independent streams")


class TheArchetypesDifferInTheWayTheyClaimTo(unittest.TestCase):
    def setUp(self):
        self.estimate = F.priced(F.two_streams(per=8))

    def test_sequential_never_builds_against_an_unsettled_specification(self):
        """Zero drift is what the archetype IS. If it ever scores above zero the staging has
        stopped working and the baseline every other option is scored against has moved."""
        self.assertEqual(F.run(self.estimate, dict(FULL, dev=2),
                               archetype="sequential")["drift_hours"], 0.0)

    def test_overlapping_costs_drift_and_the_number_is_measured(self):
        """The risk paragraph quotes this figure instead of an adjective. An archetype whose
        whole cost is rework exposure cannot score zero — which the first definition did, for
        every archetype, because it compared a build against a spec the build already waited
        for transitively."""
        shape = dict(FULL, dev=2)
        pipelined = F.run(self.estimate, shape, archetype="pipelined")["drift_hours"]
        sequential = F.run(self.estimate, shape, archetype="sequential")["drift_hours"]
        self.assertGreater(pipelined, 0.0)
        self.assertEqual(sequential, 0.0)

    def test_sequential_specifies_the_whole_backlog_before_building_any_of_it(self):
        sched = F.run(self.estimate, dict(FULL, dev=2), archetype="sequential")
        specs, builds = [], []
        for person in sched["team"]:
            for item in person["items"]:
                (specs if item["component"] == "spec" else
                 builds if item["component"] == "build" else []).append(item)
        self.assertTrue(specs and builds)
        self.assertGreaterEqual(min(b["start_week"] for b in builds) + 1e-6,
                                max(s["finish_week"] for s in specs))

    def test_pipelined_is_never_slower_than_sequential(self):
        """It was, once — for a real reason worth keeping a test over. Scheduling in document
        order handed an idle developer a story's review, which cannot start until that story's
        build finishes, while the next story's specification waited its turn."""
        shape = dict(FULL, dev=2)
        self.assertLessEqual(F.run(self.estimate, shape, archetype="pipelined")["weeks"],
                             F.run(self.estimate, shape, archetype="sequential")["weeks"] + 1e-6)

    def test_the_foundation_epics_are_read_off_the_graph_not_chosen(self):
        features = F.two_streams(per=6)
        features.append(F.feature("F900", epic="E3", size="M", depends_on=("F101",)))
        estimate = F.priced(features)
        self.assertIn("E1", F.archetypes.foundation_epics(estimate))
        self.assertNotIn("E3", F.archetypes.foundation_epics(estimate))

    def test_with_no_dependencies_anywhere_the_first_epic_is_still_the_foundation(self):
        """Otherwise this archetype silently becomes the pipelined one, and the plan offers the
        client two names for the same schedule."""
        self.assertEqual(F.archetypes.foundation_epics(F.priced(F.wide(8, epics=3))), {"E1"})


class ANewJoinerCostsSomethingBeforeTheyDeliver(unittest.TestCase):
    def test_ramp_is_paid_out_of_their_own_time_before_their_first_delivery(self):
        """Charged anywhere else, a plan could add a body in the final fortnight and book their
        whole output — which is the specific optimism this module exists to refuse."""
        sched = F.run(F.priced(F.wide(16)), dict(FULL, dev=2))
        for person in sched["team"]:
            if person["ramp_hours"]:
                self.assertGreaterEqual(person["starts_week"] + 1e-9, person["ramp_until_week"])

    def test_somebody_already_on_the_project_pays_no_ramp(self):
        estimate = F.priced(F.wide(16))
        sched = F.run(estimate, dict(FULL, dev=2), roster={"dev": 2})
        devs = [p for p in sched["team"] if p["role"] == "dev"]
        self.assertTrue(all(p["on_project"] for p in devs))
        self.assertEqual([p["ramp_hours"] for p in devs], [0.0, 0.0])


class ABiggerTeamIsNotFreeAndSometimesIsNotFaster(unittest.TestCase):
    def test_every_extra_person_slows_everybody_down(self):
        """Without this the sweep can only ever recommend the largest team allowed, which is
        not advice. The coefficient is asserted and labelled; the SHAPE is the claim."""
        estimate = F.priced(F.wide(20))
        small = F.run(estimate, FULL)["effective_hours_per_person_week"]
        large = F.run(estimate, dict(FULL, dev=4))["effective_hours_per_person_week"]
        self.assertLess(large, small)

    def test_a_model_with_no_staffing_block_simply_applies_no_drag(self):
        """est-estimate's own model had no such block until 3.2, and a plan run against an
        un-migrated one should degrade rather than crash."""
        m = F.model()
        m.pop("staffing")
        estimate = F.priced(F.wide(10))
        sched = F.schedule.simulate(estimate, m, F.team_of(FULL, m),
                                    F.archetypes.POLICIES["pipelined"](estimate, m))
        self.assertEqual(sched["coordination_drag_applied"], 0.0)
        self.assertEqual(sched["effective_hours_per_person_week"],
                         m["calendar"]["hours_per_person_week"])


class WhatOverheadIsMultipliedBy(unittest.TestCase):
    def test_mean_concurrent_headcount_is_below_the_roster_when_people_are_staggered(self):
        """`overhead = rate x weeks x people`. Using the roster would bill ceremony for a
        developer across the twelve weeks before they arrived."""
        sched = F.run(F.priced(F.chain(10)), dict(FULL, dev=3))
        self.assertLess(F.schedule.mean_concurrent_headcount(sched), len(sched["team"]))

    def test_the_span_handed_back_for_pricing_is_the_shape_the_engine_demands(self):
        """estimate.py refuses a span that carries only the rounded weeks, and it is right to:
        a plan priced on round(weeks, 1) disagrees with its own schedule."""
        sched = F.run(F.priced(F.wide(10)), FULL)
        span = F.schedule.span_for_pricing(sched, F.model(), "test")
        F.estimate_mod.check_span(span)
        self.assertEqual(len(span["weeks_three_point"]), 3)
        self.assertLess(span["weeks_three_point"][0], span["weeks_three_point"][2])


if __name__ == "__main__":
    unittest.main()
