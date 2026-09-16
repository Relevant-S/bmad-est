#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Tests for check-order.py — the audit that says a calendar matches its dependency graph.

The claim under test is not that the checker returns `ok`. A checker that compares nothing
also returns `ok`, and this module has shipped one of those: `check-parity.py` looped over
fields nothing emitted, so every comparison was skipped while the output still advertised them
as checked. So each test here either perturbs a schedule and demands a finding, or asserts on
the count of things actually compared.
"""

import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fixtures as F  # noqa: E402

check = F.load("check_order", F.ROOT / "est-plan" / "scripts" / "check-order.py")


def a_plan(features=None, epics=None):
    estimate = F.priced(features or F.layered(per=4, layers=4), epics=epics)
    return estimate, F.plan_mod.build_plan(estimate, F.model())


class TheAuditPassesAGoodPlan(unittest.TestCase):
    def setUp(self):
        self.estimate, self.plan = a_plan()

    def test_a_plan_this_module_produced_holds(self):
        report = check.audit(self.plan, self.estimate)
        self.assertTrue(report["ok"], report["findings"][:3])

    def test_it_says_how_much_it_compared(self):
        """The guard against a checker that passes by doing nothing."""
        report = check.audit(self.plan, self.estimate)
        self.assertGreater(report["edges"], 0, "no epic edges were compared")
        self.assertGreater(report["epics_ordered"], 0)
        self.assertIn(str(report["edges"]), report["checked"])
        self.assertEqual(len(report["by_option"]), len(self.plan["options"]))

    def test_the_plan_carries_its_own_verdict(self):
        self.assertTrue(self.plan["ordering_check"]["ok"])
        self.assertTrue(self.plan["build_order"]["epics"])
        waits = [e for e in self.plan["build_order"]["epics"] if e["waits_for"]]
        self.assertTrue(waits, "no epic recorded what it stands on")
        # Every edge carries the reason it exists, which is what lets the plan answer where a
        # piece of work belongs and on what grounds.
        self.assertTrue(all(w["why"] for e in waits for w in e["waits_for"]))


class TheAuditCatchesABadPlan(unittest.TestCase):
    def setUp(self):
        self.estimate, self.plan = a_plan()

    def _perturb(self, predicate, delta=-5.0):
        plan = copy.deepcopy(self.plan)
        moved = 0
        for option in plan["options"]:
            for person in option["schedule"]["team"]:
                for item in person["items"]:
                    if predicate(item):
                        item["start_week"] += delta
                        item["finish_week"] += delta
                        moved += 1
        self.assertTrue(moved, "the perturbation matched nothing — the test proves nothing")
        return plan

    def test_moving_one_build_earlier_is_caught(self):
        plan = self._perturb(lambda i: i.get("epic_id") == "E4" and i.get("component") == "build")
        report = check.audit(plan, self.estimate)
        self.assertFalse(report["ok"])
        kinds = {f["kind"] for f in report["findings"]}
        self.assertIn("epic_build_order", kinds)

    def test_moving_one_spec_earlier_is_caught(self):
        plan = self._perturb(lambda i: i.get("epic_id") == "E4" and i.get("component") == "spec")
        report = check.audit(plan, self.estimate)
        self.assertFalse(report["ok"])
        self.assertIn("epic_spec_order", {f["kind"] for f in report["findings"]})

    def test_a_build_before_its_own_specification_is_caught(self):
        plan = self._perturb(lambda i: i.get("component") == "build", delta=-50.0)
        report = check.audit(plan, self.estimate)
        self.assertIn("build_before_spec", {f["kind"] for f in report["findings"]})

    def test_a_story_dependency_violation_is_caught(self):
        estimate = F.priced(F.chain(10))
        plan = F.plan_mod.build_plan(estimate, F.model())
        for option in plan["options"]:
            for person in option["schedule"]["team"]:
                for item in person["items"]:
                    if item.get("story_id") == "F10" and item.get("component") == "build":
                        item["start_week"] = 0.0
        report = check.audit(plan, estimate)
        self.assertIn("story_dependency", {f["kind"] for f in report["findings"]})

    def test_a_finding_names_both_ends_and_the_weeks(self):
        """A finding nobody can act on is a finding nobody reads."""
        plan = self._perturb(lambda i: i.get("epic_id") == "E4" and i.get("component") == "build")
        finding = next(f for f in check.audit(plan, self.estimate)["findings"]
                       if f["kind"] == "epic_build_order")
        for part in ("E4", "E3", "week"):
            self.assertIn(part, finding["detail"])
        self.assertTrue(finding["why"], "the finding does not say why the edge exists")


class TheDeclaredOrderingIsChecked(unittest.TestCase):
    def test_an_epic_ordered_only_by_depends_on_epics_is_audited(self):
        """Kitespire's three declared orderings were all violated in a plan that reported no
        problem, because nothing outside `foundation_epics()` ever read them."""
        features, epics = F.declared_only()
        estimate, plan = a_plan(features, epics)
        report = check.audit(plan, estimate)
        self.assertTrue(report["ok"])
        self.assertGreaterEqual(report["edges"], 1)
        for option in plan["options"]:
            for person in option["schedule"]["team"]:
                for item in person["items"]:
                    if item.get("epic_id") == "E2":
                        item["start_week"] = item["finish_week"] = 0.0
        self.assertFalse(check.audit(plan, estimate)["ok"])


class TheCommandLine(unittest.TestCase):
    def test_it_exits_non_zero_on_a_violation(self):
        import tempfile
        estimate, plan = a_plan()
        for option in plan["options"]:
            for person in option["schedule"]["team"]:
                for item in person["items"]:
                    if item.get("epic_id") == "E4":
                        item["start_week"] = item["finish_week"] = 0.0
        with tempfile.TemporaryDirectory() as tmp:
            here = Path(tmp)
            (here / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
            (here / "estimate.json").write_text(json.dumps(estimate), encoding="utf-8")
            argv = sys.argv
            sys.argv = ["check-order.py", str(here / "plan.json")]
            try:
                import contextlib
                import io
                with contextlib.redirect_stdout(io.StringIO()) as out:
                    code = check.main()
            finally:
                sys.argv = argv
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(out.getvalue())["ok"])

    def test_a_missing_estimate_is_reported_rather_than_guessed(self):
        import contextlib
        import io
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plan.json"
            path.write_text("{}", encoding="utf-8")
            argv = sys.argv
            sys.argv = ["check-order.py", str(path)]
            try:
                with contextlib.redirect_stdout(io.StringIO()) as out:
                    code = check.main()
            finally:
                sys.argv = argv
        self.assertEqual(code, 2)
        self.assertIn("estimate", json.loads(out.getvalue())["error"])


if __name__ == "__main__":
    unittest.main()
