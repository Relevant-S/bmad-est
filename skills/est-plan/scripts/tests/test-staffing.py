#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Tests for staffing.py — the guardrail, and the sweep it bounds.

Headcount is an output of this module. These tests are about the refusals, because a sweep
that never refuses is a sweep that recommends the largest team allowed on every project, and
a refusal nobody can check is a refusal nobody can argue with. Every one of them asserts that
the numbers behind the decision are on the page.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fixtures as F  # noqa: E402


class TheIndependentWorkFloor(unittest.TestCase):
    def test_a_chain_bound_backlog_refuses_a_second_developer_and_says_why(self):
        """The case the whole guardrail exists for. There are plenty of hours; there is no way
        for two people to work them at once, and hours alone cannot see that."""
        estimate = F.priced(F.chain(10))
        verdict = F.judge_shape(estimate, "dev", 2)
        self.assertFalse(verdict["allowed"])
        self.assertTrue(verdict["refusals"])
        self.assertGreater(verdict["idle_hours"], 0.0)
        # The refusal has to carry its arithmetic, whichever gate caught it — the split the
        # graph cannot make, or the calendar the person does not buy.
        self.assertRegex(" ".join(verdict["refusals"]), r"\d")
        self.assertLess(verdict["weeks_saved"], 1.0)

    def test_a_wide_backlog_allows_one_and_names_the_epics_each_person_takes(self):
        """A justification that does not say which work is whose is not a plan, it is a wish."""
        estimate = F.priced(F.wide(28, epics=4, size="L"))
        verdict = F.judge_shape(estimate, "dev", 2)
        self.assertTrue(verdict["allowed"], verdict["refusals"])
        self.assertEqual(len(verdict["partition"]), 2)
        self.assertTrue(all(b["epics"] for b in verdict["partition"]))
        self.assertIn("takes", " ".join(verdict["justification"]))

    def test_the_split_minimises_the_seam_two_people_would_share(self):
        """Two developers in one epic are in the same files. The partition is by epic for that
        reason, and the cut is reported so a reader can see what will collide."""
        estimate = F.priced(F.two_streams(per=8))
        split = F.staffing.partition(estimate, "dev", 2)
        self.assertEqual(split["cut_edges"], 0)
        self.assertEqual(sorted(len(b["epics"]) for b in split["buckets"]), [1, 1])

    def test_a_backlog_whose_dependencies_cross_every_split_is_refused_on_collisions(self):
        """Interleaved dependencies mean whoever owns which epic, they are working the same
        seam — parallelism on paper and blocked mornings in practice."""
        features = []
        for i in range(1, 17):
            epic = f"E{i % 2 + 1}"
            features.append(F.feature(f"F{i}", epic=epic, size="L",
                                      depends_on=() if i == 1 else (f"F{i - 1}",)))
        estimate = F.priced(features)
        split = F.staffing.partition(estimate, "dev", 2)
        self.assertGreater(split["cut_share"], 0.25)
        verdict = F.judge_shape(estimate, "dev", 2)
        self.assertFalse(verdict["allowed"])
        self.assertIn("same seam", " ".join(verdict["refusals"]))


class TheCoordinationCost(unittest.TestCase):
    def test_a_newcomer_is_refused_when_they_would_deliver_less_than_they_ramp(self):
        """Somebody who spends sixteen hours arriving to perform twelve is not a member of a
        team, they are a line item."""
        estimate = F.priced(F.wide(6, epics=3, size="XS"))
        verdict = F.judge_shape(estimate, "ux", 3)
        self.assertFalse(verdict["allowed"])
        self.assertTrue(any("cost more than they carry" in r or "cost more calendar" in r
                            for r in verdict["refusals"]), verdict["refusals"])

    def test_but_a_person_who_buys_more_calendar_than_they_cost_is_allowed(self):
        """The ramp is a cost the plan carries and shows, not a reason to leave a backlog
        unstaffed. What decides is the margin: does this person shorten the plan by more than
        they spend arriving. An earlier gate compared the ramp against a share of the role's
        backlog and suppressed itself when the role was 'over-subscribed' — a condition
        measured by a utilisation that was pinned at 100% by its own arithmetic."""
        estimate = F.priced(F.wide(40, epics=6, size="L"))
        verdict = F.judge_shape(estimate, "dev", 2)
        self.assertTrue(verdict["allowed"], verdict["refusals"])
        self.assertEqual(len(verdict["delivered_each"]), 2)
        self.assertGreater(verdict["weeks_saved"],
                           F.model()["staffing"]["ramp_hours"]["likely"]
                           / F.model()["calendar"]["hours_per_person_week"])

    def test_a_person_who_buys_almost_no_calendar_is_refused_on_the_margin(self):
        estimate = F.priced(F.chain(14))
        verdict = F.judge_shape(estimate, "dev", 2)
        self.assertFalse(verdict["allowed"])
        self.assertIn("cost more calendar than they buy", " ".join(verdict["refusals"]))

    def test_someone_already_on_the_project_is_not_a_newcomer(self):
        estimate = F.priced(F.wide(20, epics=4))
        self.assertEqual(F.judge_shape(estimate, "dev", 2, roster={"dev": 2})["newcomers"], 0)
        self.assertEqual(F.judge_shape(estimate, "dev", 2)["newcomers"], 2)


class TheSuppliedRoster(unittest.TestCase):
    def test_a_roster_is_a_floor_and_the_sweep_may_still_add_to_it(self):
        """Stated as a decision: the user's team is where this starts, not where it stops."""
        estimate = F.priced(F.wide(40, epics=6, size="L"))
        swept = F.staffing.sweep(estimate, F.model(), roster={"dev": 2})
        self.assertGreaterEqual(swept["shapes"][0]["dev"], 2)
        self.assertGreater(max(s["dev"] for s in swept["shapes"]), 2)

    def test_a_roster_larger_than_the_backlog_can_occupy_is_flagged_with_its_idle_hours(self):
        """The one thing a plan must not quietly absorb. Somebody is being billed for sitting
        still and it will be discovered late."""
        estimate = F.priced(F.wide(6, epics=2, size="XS"))
        flagged = F.staffing.oversized_roster(estimate, F.model(), {"dev": 5}, span_weeks=4.0)
        self.assertTrue(flagged)
        self.assertEqual(flagged[0]["role"], "dev")
        self.assertGreater(flagged[0]["idle_hours"], 0.0)
        self.assertLess(flagged[0]["sustainable_count"], 5)

    def test_a_roster_the_backlog_can_keep_busy_is_not_flagged(self):
        estimate = F.priced(F.wide(40, epics=6, size="L"))
        self.assertEqual(F.staffing.oversized_roster(estimate, F.model(), {"dev": 2},
                                                     F.span_for(estimate, "dev", 2)), [])


class TheSweep(unittest.TestCase):
    def test_every_shape_it_offers_carries_a_recorded_decision(self):
        swept = F.staffing.sweep(F.priced(F.wide(30, epics=5, size="L")), F.model())
        self.assertGreater(len(swept["shapes"]), 1)
        self.assertTrue(swept["decisions"])
        for decision in swept["decisions"]:
            self.assertTrue(decision["justification"] or decision["refusals"])

    def test_it_stops_when_the_guardrail_refuses_rather_than_at_an_arbitrary_size(self):
        """A chain-bound backlog gets one of each role and no more, however many hours it holds."""
        swept = F.staffing.sweep(F.priced(F.chain(16)), F.model())
        self.assertEqual(len(swept["shapes"]), 1)
        self.assertTrue(all(not d["allowed"] for d in swept["decisions"]))

    def test_a_refused_role_is_not_retried(self):
        """The backlog does not get wider on the second ask, and a sweep that keeps asking
        prints the same refusal until it hits a cap."""
        swept = F.staffing.sweep(F.priced(F.wide(24, epics=4)), F.model())
        refused = [d["role"] for d in swept["decisions"] if not d["allowed"]]
        self.assertEqual(len(refused), len(set(refused)))

    def test_the_architect_is_never_multiplied(self):
        """Priced as setup plus a capped weekly presence, so a second architect buys nothing
        this model can price. Proposing one would be inventing a coefficient."""
        swept = F.staffing.sweep(F.priced(F.wide(40, epics=6, size="L")), F.model())
        self.assertNotIn("architect", F.staffing.PARALLELISABLE)
        self.assertTrue(all("architect" not in shape for shape in swept["shapes"]))


if __name__ == "__main__":
    unittest.main()
