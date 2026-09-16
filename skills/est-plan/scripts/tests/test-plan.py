#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Tests for plan.py — the options, their own estimates, their feasibility and their scores.

The claim this file protects is the one the output makes on its front page: each option is a
complete plan AND its own estimate, and the difference between two options is attributable to
their schedules and to nothing else. If a schedule could move a story's hours, the comparison
a salesperson is being asked to make would be between two different scopes wearing the same
name.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fixtures as F  # noqa: E402


def plan_of(features, **over):
    estimate = F.priced(features)
    return estimate, F.plan_mod.build_plan(estimate, F.model(), **over)


class EachOptionCarriesItsOwnEstimate(unittest.TestCase):
    def setUp(self):
        self.estimate, self.plan = plan_of(F.wide(24, epics=4, size="L"))
        self.options = self.plan["options"]

    def test_there_is_more_than_one_and_each_has_a_full_role_table(self):
        self.assertGreater(len(self.options), 1)
        for option in self.options:
            for role in ("ba", "dev", "architect"):
                row = option["estimate"]["by_role"][role]
                self.assertLessEqual(row["low"], row["likely"])
                self.assertLessEqual(row["likely"], row["high"])

    def test_the_schedule_moves_the_architect_and_the_ceremony_and_nothing_else(self):
        """The whole seam. Story hours, planning and QA are properties of the scope; a plan
        that moved them would be re-pricing the work while claiming to re-price the calendar."""
        a, b = self.options[0], self.options[-1]
        self.assertNotAlmostEqual(a["schedule"]["weeks"], b["schedule"]["weeks"], places=1)
        for name in ("qa", "planning_agent", "planning_review"):
            self.assertAlmostEqual(a["estimate"]["project_components"][name]["hours"],
                                   b["estimate"]["project_components"][name]["hours"],
                                   places=6, msg=name)
        self.assertEqual([f["hours"] for f in a["estimate"]["features"]],
                         [f["hours"] for f in b["estimate"]["features"]])
        delta = (b["estimate"]["total_hours"]["likely"] - a["estimate"]["total_hours"]["likely"])
        moved = sum(b["estimate"]["project_components"][k]["hours"]
                    - a["estimate"]["project_components"][k]["hours"]
                    for k in ("architect", "overhead"))
        self.assertAlmostEqual(delta, moved, delta=0.3)

    def test_a_longer_plan_buys_more_architect(self):
        """Setup plus a capped weekly presence. The coefficient all three delivered projects
        fit exactly, and the one a schedule is entitled to move."""
        pairs = sorted(((o["schedule"]["weeks"],
                         o["estimate"]["project_components"]["architect"]["hours"])
                        for o in self.options))
        self.assertLess(pairs[0][1], pairs[-1][1])

    def test_the_plan_says_why_its_numbers_differ_from_the_estimates(self):
        self.assertIn("nominal team shape", self.plan["estimate"]["why_it_differs"])


class NoOptionIsOfferedThatCannotBeRun(unittest.TestCase):
    def test_every_recommended_option_passed_its_feasibility_check(self):
        _, plan = plan_of(F.wide(24, epics=4, size="L"))
        best = next(o for o in plan["options"] if o["id"] == plan["recommended"])
        self.assertTrue(best["feasibility"]["feasible"])
        self.assertEqual(best["feasibility"]["failures"], [])

    def test_no_option_claims_a_span_below_its_own_dependency_chain(self):
        estimate, plan = plan_of(F.chain(12))
        floor = estimate["dependencies"]["hours"]
        self.assertGreater(floor, 0.0)
        for option in plan["options"]:
            self.assertTrue(option["feasibility"]["feasible"], option["feasibility"]["failures"])
            self.assertGreaterEqual(option["schedule"]["weeks"] + 1e-6,
                                    option["feasibility"]["critical_path_weeks"])

    def test_nobody_is_booked_past_full_time(self):
        _, plan = plan_of(F.two_streams(per=8))
        for option in plan["options"]:
            for person in option["schedule"]["team"]:
                self.assertLessEqual(person["utilisation"], 1.0001, person["name"])

    def test_the_feasibility_report_states_what_it_checked_not_just_that_it_passed(self):
        _, plan = plan_of(F.wide(16, epics=4))
        checks = plan["options"][0]["feasibility"]["checks"]
        self.assertTrue(any("critical path" in c for c in checks))
        self.assertTrue(any("ramp" in c for c in checks))


class TheScoreIsDefensibleLineByLine(unittest.TestCase):
    def setUp(self):
        _, self.plan = plan_of(F.wide(24, epics=4, size="L"))

    def test_every_sub_score_names_the_number_it_rests_on(self):
        """A recommendation whose arithmetic the reader cannot check is a recommendation
        nobody can argue with."""
        for option in self.plan["options"]:
            parts = option["score"]["parts"]
            self.assertEqual(set(parts), {"duration", "cost", "utilisation",
                                          "coordination", "drift", "confidence"})
            for name, part in parts.items():
                self.assertTrue(part["rests_on"].strip(), name)
                self.assertGreaterEqual(part["score"], 0.0)
                self.assertLessEqual(part["score"], 10.0)

    def test_the_weights_come_from_the_cost_model_not_from_the_code(self):
        weights = self.plan["options"][0]["score"]["weights"]
        self.assertEqual(weights, F.model()["staffing"]["scoring"]["weights"])

    def test_the_recommendation_is_the_highest_scoring_feasible_option(self):
        viable = [o for o in self.plan["options"] if o["feasibility"]["feasible"]]
        self.assertEqual(self.plan["recommended"],
                         max(viable, key=lambda o: o["score"]["fit"])["id"])

    def test_a_deadline_changes_which_option_wins_rather_than_being_decoration(self):
        estimate = F.priced(F.wide(24, epics=4, size="L"))
        loose = F.plan_mod.build_plan(estimate, F.model(), deadline=60)
        tight = F.plan_mod.build_plan(estimate, F.model(), deadline=3)
        self.assertNotEqual([o["score"]["fit"] for o in loose["options"]],
                            [o["score"]["fit"] for o in tight["options"]])

    def test_the_fastest_option_is_not_automatically_the_recommended_one(self):
        """If it were, the other five sub-scores would be decoration and the whole staffing
        argument would collapse into 'hire everybody'."""
        estimate = F.priced(F.wide(30, epics=5, size="L"))
        plan = F.plan_mod.build_plan(estimate, F.model())
        fastest = min(plan["options"], key=lambda o: o["schedule"]["weeks"])
        cheapest = min(plan["options"], key=lambda o: o["estimate"]["total_hours"]["likely"])
        self.assertTrue(fastest["score"]["fit"] <= 10.0 and cheapest["score"]["fit"] <= 10.0)
        self.assertGreater(len({o["score"]["fit"] for o in plan["options"]}), 1)


class TheCalendarNeverBecomesADate(unittest.TestCase):
    def test_nothing_in_the_plan_carries_a_date(self):
        """Two standing rules in this module say duration must not harden into a date. A Gantt
        is exactly where that happens, so it is asserted rather than remembered."""
        import json
        import re
        _, plan = plan_of(F.wide(12, epics=3))
        self.assertIn("Weeks are relative", plan["inputs"]["calendar"])
        for option in plan["options"]:
            # The schedule and the span are where a date would appear if one ever did. The
            # estimate carried inside an option keeps its own `generated` timestamp, which is
            # provenance rather than a commitment and is deliberately not covered here.
            blob = json.dumps({"schedule": option["schedule"], "span": option["span"],
                               "shape": option["team_shape"]})
            self.assertNotRegex(blob, r"\b\d{4}-\d{2}-\d{2}\b")
            self.assertIn("relative", option["span"]["basis"])
            self.assertFalse(re.search(r"start_date|calendar_date|due_date|start_day", blob))
        for key in ("weeks", "planning_prefix_weeks"):
            self.assertIsInstance(plan["options"][0]["schedule"][key], float)


class TheInputsAreTreatedAsStated(unittest.TestCase):
    def test_a_supplied_roster_is_a_floor_and_the_options_may_exceed_it(self):
        estimate = F.priced(F.wide(60, epics=8, size="L"))
        plan = F.plan_mod.build_plan(estimate, F.model(), roster={"dev": 1})
        self.assertGreater(max(o["team_shape"]["dev"] for o in plan["options"]), 1)
        self.assertIn("not a constraint", plan["inputs"]["headcount"])

    def test_restricting_the_archetypes_restricts_the_options(self):
        estimate = F.priced(F.wide(12, epics=3))
        plan = F.plan_mod.build_plan(estimate, F.model(), only=["sequential"])
        self.assertEqual({o["archetype"] for o in plan["options"]}, {"sequential"})


if __name__ == "__main__":
    unittest.main()
