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

# Standing work (repo, CI, environments) and planning are on the calendar too now, and both
# legitimately start at week zero — they are what the team does while the specification is
# still being written. Assertions about STORY work have to say so.
STORY = ("spec", "build", "review", "rework")


def story_items(sched):
    return [(p, i) for p in sched["team"] for i in p["items"]
            if i["component"] in STORY and not str(i["story_id"] or "").startswith("SW-")]


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
        for _, item in story_items(sched):
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
        for _, item in story_items(sched):
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



class QaRunsInPassesAgainstFinishedSlices(unittest.TestCase):
    """QA used to be a tail bolted onto the end of every plan, in every archetype.

    `schedule_qa` was called once, after the stage loop, with the FINAL barrier — so every
    epic's QA, including the first epic's, was floored at the finish of all story work. A real
    plan put the first QA hour in week 36 of 41. That is not a presentation problem: it lets a
    defect propagate through everything built after it, and the architectural ones are the most
    expensive to undo.
    """

    SHAPE = {"dev": 2, "ba": 1, "ux": 1, "qa": 1, "devops": 1}

    def parts(self, estimate, archetype="pipelined"):
        sched = F.run(estimate, self.SHAPE, archetype=archetype)
        items = [i for p in sched["team"] for i in p["items"]]
        return (sched,
                [i for i in items if i["component"] == "qa"],
                [i for i in items if i["component"] == "build"])

    def test_the_first_pass_starts_before_the_last_build_finishes(self):
        estimate = F.priced(F.wide(30, epics=5, size="L"))
        for archetype in ("sequential", "foundation", "pipelined"):
            with self.subTest(archetype=archetype):
                _, qa, builds = self.parts(estimate, archetype)
                self.assertTrue(qa, "no QA was scheduled at all")
                self.assertLess(min(i["start_week"] for i in qa),
                                max(i["finish_week"] for i in builds))

    def test_a_pass_never_starts_before_its_own_epic_is_built(self):
        """Testing work that does not exist yet is the opposite failure and just as wrong."""
        estimate = F.priced(F.wide(24, epics=4, size="L"))
        sched, qa, _ = self.parts(estimate)
        built = {}
        for person in sched["team"]:
            for item in person["items"]:
                if item["component"] == "build":
                    built[item["epic_id"]] = max(built.get(item["epic_id"], 0.0),
                                                 item["finish_week"])
        for item in qa:
            if item["epic_id"] in built:
                self.assertGreaterEqual(item["start_week"] + 1e-6, built[item["epic_id"]],
                                        item["label"])

    def test_the_number_of_passes_scales_with_the_scope(self):
        """One pass per epic plus a regression sweep, so a bigger backlog is tested more often
        rather than tested later."""
        small = len(self.parts(F.priced(F.wide(12, epics=2, size="L")))[1])
        large = len(self.parts(F.priced(F.wide(48, epics=8, size="L")))[1])
        self.assertGreater(large, small)

    def test_a_regression_pass_closes_the_project(self):
        """A per-epic sweep alone asserts every defect is found inside the epic that caused it,
        which is the assumption integration testing exists because nobody believes."""
        _, qa, builds = self.parts(F.priced(F.wide(24, epics=4, size="L")))
        last = max(qa, key=lambda i: i["start_week"])
        self.assertIn("regression", last["label"].lower())
        self.assertGreaterEqual(last["start_week"] + 1e-6,
                                max(i["finish_week"] for i in builds))

    def test_every_priced_qa_hour_is_scheduled_to_somebody(self):
        """QA is priced on `project_components`, not on a story, so it has to be placed
        explicitly — and hours that are billed and assigned to nobody are exactly the defect
        this area is being corrected for."""
        estimate = F.priced(F.wide(24, epics=4, size="L"))
        sched, qa, _ = self.parts(estimate)
        priced = estimate["project_components"]["qa"]["hours"]
        self.assertAlmostEqual(sum(i["hours"] for i in qa), priced, delta=max(0.5, priced * 0.02))


class TheAnalystLeads(unittest.TestCase):
    """Until the BA has defined what gets built, a developer can do project setup and not much
    else. A real plan had dev starting in week 0.6 and the BA in week 2.9, because the planning
    prefix lifted `ready` only for the roles performing planning, and `role_weights.spec` puts
    dev on specification at w=0.28.
    """

    SHAPE = {"dev": 1, "ba": 1, "ux": 1, "qa": 1, "devops": 1}

    def test_no_story_work_starts_before_the_planning_prefix(self):
        sched = F.run(F.priced(F.wide(20, epics=4, size="L")), self.SHAPE)
        prefix = sched["planning_prefix_weeks"]
        self.assertGreater(prefix, 0.0)
        for person, item in story_items(sched):
            self.assertGreaterEqual(item["start_week"] + 1e-6, prefix,
                                    f"{person['name']} started {item['label']} before "
                                    f"planning closed")

    def test_but_setup_and_planning_do_start_at_once(self):
        """Because that is the honest answer to "what does the developer do first". Standing
        work is the repository, the pipeline and the environments; it depends on nothing and
        it is what fills the weeks before there is a specification to build against."""
        sched = F.run(F.priced(F.wide(20, epics=4, size="L")), self.SHAPE)
        early = [i for p in sched["team"] for i in p["items"]
                 if i["start_week"] < sched["planning_prefix_weeks"]]
        self.assertTrue(early, "nobody works during planning")
        self.assertTrue(all(i["component"] == "planning"
                            or str(i["story_id"] or "").startswith("SW-") for i in early),
                        sorted({i["label"] for i in early}))

    def test_the_developers_share_of_a_spec_follows_the_analysts(self):
        """Ordering is applied to specification only — a build is genuinely concurrent across
        the surfaces it touches, and forcing an order there would invent a dependency."""
        sched = F.run(F.priced(F.wide(16, epics=4, size="L")), self.SHAPE)
        ba, dev = {}, {}
        for person, item in story_items(sched):
            if item["component"] != "spec":
                continue
            (ba if person["role"] == "ba" else dev).setdefault(item["story_id"], item)
        shared = set(ba) & set(dev)
        self.assertTrue(shared, "no story had both a BA and a dev share of its spec")
        for story in shared:
            self.assertGreaterEqual(dev[story]["start_week"] + 1e-6, ba[story]["finish_week"],
                                    f"{story}: dev specified it before the BA did")

    def test_the_analyst_is_not_held_up_by_the_developer_in_return(self):
        """The BA specifies story k+1 while the dev reads story k. A rule that serialised the
        whole backlog through one analyst would be worse than the defect it fixed."""
        sched = F.run(F.priced(F.wide(16, epics=4, size="L")), self.SHAPE)
        ba = next(p for p in sched["team"] if p["role"] == "ba")
        specs = [i for i in ba["items"] if i["component"] == "spec"]
        self.assertGreater(len(specs), 4)
        gaps = sum(1 for a, b in zip(specs, specs[1:]) if b["start_week"] > a["finish_week"] + 1e-6)
        self.assertLess(gaps, len(specs) / 2, "the analyst spends most of the plan waiting")


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




class PeopleArriveWhenTheWorkDoes(unittest.TestCase):
    """Nobody joins before their role has more ready work than the people already on it can
    clear. The plan used to start everybody on the same Monday: a real Kitespire run put four
    developers who had never seen the codebase at `ramp_until` 2.587, 2.590, 2.592 and 2.597 —
    inside a hundredth of a week of each other — against a repository that did not exist yet."""

    def test_the_first_person_in_a_role_starts_in_week_one_and_the_rest_do_not(self):
        sched = F.run(F.priced(F.wide(40, epics=8)), dict(FULL, dev=4))
        devs = [p for p in sched["team"] if p["role"] == "dev"]
        self.assertEqual(devs[0]["join_week"], 0.0)
        self.assertGreater(max(p["join_week"] for p in devs), 0.0,
                           "every developer still arrives in week one")

    def test_join_weeks_never_run_backwards(self):
        """Person k+1 cannot be justified by demand that person k already answered."""
        sched = F.run(F.priced(F.wide(40, epics=8)), dict(FULL, dev=4))
        weeks = [p["join_week"] for p in sched["team"] if p["role"] == "dev"]
        self.assertEqual(weeks, sorted(weeks))

    def test_a_one_person_team_is_untouched(self):
        """The change has to be inert where there is nobody to stagger — otherwise every
        single-person span in the module moved for a reason unrelated to the fix."""
        estimate = F.priced(F.wide(24, epics=4))
        sched = F.run(estimate, FULL)
        self.assertTrue(all(p["join_week"] == 0.0 for p in sched["team"]))

    def test_nobody_delivers_before_they_arrive(self):
        sched = F.run(F.priced(F.wide(40, epics=8)), dict(FULL, dev=4))
        for person in sched["team"]:
            for item in person["items"]:
                self.assertGreaterEqual(item["start_week"] + 1e-9, person["join_week"],
                                        f"{person['name']} works before joining")

    def test_the_weeks_before_arrival_are_not_counted_as_blocked(self):
        """staffing.judge() refuses headcount on marginal blocked time. A late joiner charged
        for the weeks they were not yet here would be refused for not existing."""
        sched = F.run(F.priced(F.wide(40, epics=8)), dict(FULL, dev=4))
        for person in sched["team"]:
            self.assertLessEqual(person["blocked_weeks"],
                                 sched["weeks"] - person["join_week"] + 1e-6,
                                 f"{person['name']} was blocked for longer than they were here")

    def test_somebody_on_the_supplied_roster_never_waits_to_join(self):
        """They are already on the project. Arrival is a question about hiring."""
        estimate = F.priced(F.wide(40, epics=8))
        sched = F.run(estimate, dict(FULL, dev=3), roster={"dev": 3})
        self.assertTrue(all(p["join_week"] == 0.0
                            for p in sched["team"] if p["role"] == "dev"))

    def test_a_staggered_team_reports_fewer_concurrent_people_than_its_roster(self):
        """Which is what `mean_concurrent_headcount` always claimed and never delivered —
        overhead is `rate x weeks x people`, and before the stagger the average and the roster
        were the same number by construction."""
        sched = F.run(F.priced(F.wide(40, epics=8)), dict(FULL, dev=4))
        self.assertLess(F.schedule.mean_concurrent_headcount(sched), len(sched["team"]))




class TheEpicOrderingIsHonoured(unittest.TestCase):
    """A cross-epic story dependency orders the two EPICS, not only the two stories.

    Treating it as story-local is what let a real plan build `Phase 2 AI — Module 2` in week
    5.3 against a prerequisites epic that finished in week 9.3, while violating none of its 190
    story edges: only a fraction of an epic's stories carry a cross-epic gate — Kitespire's
    Authentication epic had one in eight — and the rest floated to whoever was idle. 94 of 253
    epic pairs ran against the stated build order.
    """

    def windows(self, sched, component):
        out = {}
        for person in sched["team"]:
            for item in person["items"]:
                key = item.get("epic_id")
                if key and item.get("component") == component:
                    lo, hi = out.get(key, (1e9, 0.0))
                    out[key] = (min(lo, item["start_week"]), max(hi, item["finish_week"]))
        return out

    def test_an_epic_is_not_built_before_the_epic_it_stands_on(self):
        estimate = F.priced(F.layered(per=4, layers=4))
        for archetype in ("sequential", "foundation", "pipelined"):
            sched = F.run(estimate, dict(FULL, dev=3), archetype=archetype)
            built = self.windows(sched, "build")
            for n in range(2, 5):
                self.assertGreaterEqual(
                    built[f"E{n}"][0] + 1e-6, built[f"E{n - 1}"][1],
                    f"{archetype}: E{n} builds at {built[f'E{n}'][0]:.2f} before E{n - 1} "
                    f"finishes at {built[f'E{n - 1}'][1]:.2f}")

    def test_the_unconstrained_stories_are_carried_too(self):
        """The whole point. Only story F201 names F101; F202..F204 name nothing, and before
        this they were built alongside epic 1."""
        estimate = F.priced(F.layered(per=4, layers=3))
        sched = F.run(estimate, dict(FULL, dev=3))
        first = {}
        for person in sched["team"]:
            for item in person["items"]:
                if item.get("component") == "build" and item.get("story_id"):
                    first[item["story_id"]] = min(first.get(item["story_id"], 1e9),
                                                  item["start_week"])
        last_of_one = max(w for s, w in first.items() if s.startswith("F1"))
        for story in ("F202", "F203", "F204"):
            self.assertGreaterEqual(first[story], last_of_one - 1e-6,
                                    f"{story} carries no dependency of its own and was built "
                                    f"before epic 1 finished")

    def test_a_declared_epic_dependency_is_scheduled_not_just_read(self):
        """`depends_on_epics` was read in exactly one place — `foundation_epics()` — and never
        scheduled against, so all three of Kitespire's declared orderings were violated."""
        features, epics = F.declared_only()
        estimate = F.priced(features, epics=epics)
        built = self.windows(F.run(estimate, dict(FULL, dev=2)), "build")
        self.assertGreaterEqual(built["E2"][0] + 1e-6, built["E1"][1])

    def test_specification_is_ordered_by_the_epic_graph_too(self):
        """Every one of 23 epics began its specification inside the same fifth of a week, which
        is what a reader saw as `Phase 2 starts alongside Phase 1`. Spec waits for its
        predecessors to be SPECIFIED, never built, so no analyst waits on a developer."""
        estimate = F.priced(F.layered(per=4, layers=4))
        sched = F.run(estimate, dict(FULL, dev=3))
        spec, build = self.windows(sched, "spec"), self.windows(sched, "build")
        for n in range(2, 5):
            self.assertGreaterEqual(spec[f"E{n}"][0] + 1e-6, spec[f"E{n - 1}"][1])
            self.assertLess(spec[f"E{n}"][0], build[f"E{n - 1}"][1],
                            f"E{n}'s specification waited for E{n - 1} to be BUILT — that is "
                            f"the rule that made pipelined slower than sequential")

    def test_the_archetypes_still_differ(self):
        """If the epic gate collapses all three onto one answer it has over-constrained, and
        the module would be offering a choice that is not a choice.

        Two values, not three: on a pure chain of epics every epic but the last is foundational,
        so `foundation`'s single barrier falls where the epic gate already puts it and it comes
        out identical to `pipelined`. That is the fixture being a chain, not the gate flattening
        anything — the real Kitespire backlog separates all three (14.0 / 12.8 / 12.4 weeks).
        What must not happen is sequential collapsing too, since it is the baseline the other
        two are read against.
        """
        estimate = F.priced(F.layered(per=5, layers=4))
        spans = {a: F.run(estimate, dict(FULL, dev=3), archetype=a)["weeks"]
                 for a in ("sequential", "foundation", "pipelined")}
        self.assertGreaterEqual(len(set(spans.values())), 2, spans)
        self.assertGreater(spans["sequential"], spans["pipelined"], spans)

    def test_an_epic_cycle_is_reported_rather_than_hung_on(self):
        """Rolling story edges up can make an epic cycle out of an acyclic story graph. The
        scheduler must not deadlock, and must not silently pick a winner either."""
        features = [F.feature("A1", epic="EA", depends_on=("B1",)),
                    F.feature("A2", epic="EA"),
                    F.feature("B1", epic="EB", depends_on=("A2",)),
                    F.feature("B2", epic="EB")]
        sched = F.run(F.priced(features), dict(FULL, dev=2))
        self.assertGreater(sched["weeks"], 0)
        dropped = [r for r in sched["unresolved_dependencies"] if r.get("dropped")]
        self.assertTrue(dropped, "the broken epic edge was not reported")
        self.assertIn(dropped[0]["waits_on"], ("EA", "EB"))




class APhaseIsACommitmentNotADependency(unittest.TestCase):
    """Everything in phase N is built before anything in phase N+1, whether or not the graph
    requires it.

    The regenerated Kitespire plan honoured every dependency and still opened Phase 2's build in
    week 8.85 against committed work running to 10.18. Nothing in Phase 2 depended on anything
    late in Phase 1, so nothing stopped them. Phase 2 was a separate contract.
    """

    def windows(self, sched, estimate, component):
        phase = {f["id"]: f.get("phase") or 1 for f in estimate["features"]}
        out = {}
        for person in sched["team"]:
            for item in person["items"]:
                key = phase.get(item.get("story_id"))
                if key is None or item.get("component") != component:
                    continue
                lo, hi = out.get(key, (1e9, 0.0))
                out[key] = (min(lo, item["start_week"]), max(hi, item["finish_week"]))
        return out

    def test_a_later_phase_is_not_built_until_the_earlier_one_closes(self):
        features, epics = F.two_phases()
        estimate = F.priced(features, epics=epics)
        for archetype in ("sequential", "foundation", "pipelined"):
            sched = F.run(estimate, dict(FULL, dev=3), archetype=archetype)
            built = self.windows(sched, estimate, "build")
            self.assertGreaterEqual(
                built[2][0] + 1e-6, built[1][1],
                f"{archetype}: phase 2 builds at {built[2][0]:.2f} before phase 1 finishes at "
                f"{built[1][1]:.2f}")

    def test_analysis_may_still_overlap_the_previous_phase(self):
        """Deliberate, and worth pinning: a hard wall on specification too would idle the BA
        through the last stretch of every project, and discovery for a next phase genuinely does
        run alongside the current one."""
        features, epics = F.two_phases()
        estimate = F.priced(features, epics=epics)
        sched = F.run(estimate, dict(FULL, dev=3))
        spec, built = self.windows(sched, estimate, "spec"), self.windows(sched, estimate, "build")
        self.assertLess(spec[2][0], built[1][1],
                        "phase 2's specification waited for phase 1 to be BUILT")

    def test_a_stated_phase_beats_the_derivation(self):
        features, epics = F.stated_phases()
        estimate = F.priced(features, epics=epics)
        phases = {f["epic_id"]: f["phase"] for f in estimate["features"] if f.get("epic_id")}
        self.assertEqual(phases, {"E1": 1, "E2": 2})
        # The basis says which it was. A stated phase is a decision somebody recorded; a
        # derived one is the module's inference, and quoting them identically would let an
        # inference read as a client's own words.
        self.assertTrue(estimate["features"][0]["phase_basis"].startswith("stated"))
        self.assertIn("the SOW names the phase", estimate["features"][0]["phase_basis"])
        built = self.windows(F.run(estimate, dict(FULL, dev=2)), estimate, "build")
        self.assertGreaterEqual(built[2][0] + 1e-6, built[1][1])

    def test_a_backlog_with_one_phase_is_untouched(self):
        """The gate must be inert where there is only one phase, or every span in the module
        moved for a reason unrelated to the fix."""
        estimate = F.priced(F.wide(24, epics=4))
        self.assertEqual({f.get("phase") for f in estimate["features"]}, {1})

    def test_the_foundation_archetype_does_not_deadlock_across_a_phase(self):
        """`foundation_epics()` is "every epic something waits on", and on a real backlog that
        reached across the boundary — Kitespire's E21 and E22 are both Phase 2 and both depended
        upon. Unrestricted, that put phase-2 epics in stage 0 while phase 1 sat in stage 1, and
        the phase gate cannot be satisfied inside that staging."""
        features, epics = F.two_phases()
        # Give phase 2 an internal dependency so its first epic IS depended upon, which is what
        # dragged Kitespire's E21 into the foundation set.
        features[-1]["depends_on"] = [{"feature_id": "F301", "inferred": False,
                                       "evidence": "stated"}]
        estimate = F.priced(features, epics=epics)
        phase = {f["epic_id"]: f.get("phase") for f in estimate["features"] if f.get("epic_id")}
        self.assertEqual(set(F.archetypes.foundation_epics(estimate)),
                         {e for e in phase if phase[e] == 1} & set(F.archetypes.foundation_epics(estimate)),
                         "the foundation set reaches into a later phase")
        self.assertTrue(all(phase[e] == 1 for e in F.archetypes.foundation_epics(estimate)))
        for archetype in ("sequential", "foundation", "pipelined"):
            sched = F.run(estimate, dict(FULL, dev=3), archetype=archetype)
            self.assertEqual(sched["unresolved_dependencies"], [], archetype)


if __name__ == "__main__":
    unittest.main()
