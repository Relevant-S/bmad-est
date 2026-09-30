#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Tests for architecture-check.py.

The claim under test is not that the audit returns `ok`. A checker that compares nothing also
returns `ok`, and this module has shipped one of those: `check-parity.py` looped over fields
nothing emitted, so every comparison was skipped while the output still advertised them as
checked. So each test here either breaks an architecture and demands a finding, or asserts on
the count of things actually compared.
"""

import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fixtures as F  # noqa: E402

arch = F.load("architect", F.ARCH / "scripts" / "architect.py")
chk = F.load("check", F.ARCH / "scripts" / "architecture-check.py")


def an_architecture(inputs=None, **kw):
    inv = F.clinical()
    return inv, arch.build_architecture(inv, F.model(), F.caps.load_platforms(),
                                        inputs or {"house_platforms": ["aws"]}, **kw)


class TheAuditPassesAGoodArchitecture(unittest.TestCase):
    def setUp(self):
        self.inventory, self.architecture = an_architecture()

    def test_what_this_module_produces_holds(self):
        report = chk.audit(self.architecture, self.inventory)
        self.assertTrue(report["ok"], report["findings"][:3])

    def test_it_says_how_much_it_compared(self):
        """The guard against a checker that passes by doing nothing."""
        report = chk.audit(self.architecture, self.inventory)
        self.assertGreater(report["components"], 0)
        self.assertGreater(report["mapped_story_links"], 0)
        self.assertIn(str(report["components"]), report["checked"])
        self.assertIn(str(report["mapped_story_links"]), report["checked"])

    def test_it_reports_how_much_of_the_map_is_only_a_keyword_match(self):
        """A map that looks authoritative and was built by substring search is exactly the kind
        of confident wrong artefact this module exists to avoid."""
        report = chk.audit(self.architecture, self.inventory)
        self.assertGreater(report["signal_derived_links"], 0)
        self.assertIn("keyword signal rather than judgement", report["checked"])


class TheAuditCatchesAnArchitectureThatSaysNothing(unittest.TestCase):
    def setUp(self):
        self.inventory, self.architecture = an_architecture()

    def test_a_component_serving_nothing_is_caught_and_named(self):
        bad = copy.deepcopy(self.architecture)
        bad["components"].append({"id": "queue", "capability": "async_work",
                                  "name": "A message bus", "tier": "services", "mode": "buy",
                                  "serves": {"stories": [], "standing_work": [],
                                             "assumptions": []}})
        report = chk.audit(bad, self.inventory)
        self.assertFalse(report["ok"])
        finding = next(f for f in report["findings"] if f["kind"] == "component_serves_nothing")
        self.assertIn("A message bus", finding["detail"])
        self.assertIn("invented infrastructure", finding["detail"])

    def test_a_claimed_story_that_does_not_exist_is_caught(self):
        bad = copy.deepcopy(self.architecture)
        bad["capability_map"]["identity"]["stories"].append("F999")
        report = chk.audit(bad, self.inventory)
        finding = next(f for f in report["findings"] if f["kind"] == "unknown_story")
        self.assertEqual("F999", finding["story"])

    def test_a_score_with_no_basis_is_caught(self):
        bad = copy.deepcopy(self.architecture)
        bad["layers"]["platform"]["options"][0]["parts"]["runtime_fit"]["basis"] = ""
        report = chk.audit(bad, self.inventory)
        finding = next(f for f in report["findings"] if f["kind"] == "score_without_basis")
        self.assertIn("nobody can argue with", finding["detail"])

    def test_a_missing_balance_block_is_caught(self):
        bad = copy.deepcopy(self.architecture)
        bad["layers"]["sourcing"]["balance"] = {}
        report = chk.audit(bad, self.inventory)
        self.assertIn("balance_missing", {f["kind"] for f in report["findings"]})


class ScopeMustNotMoveWhileAnArchitectureIsChosen(unittest.TestCase):
    """The most dangerous failure available here: 'we bought auth' and the auth stories quietly
    left the backlog, which has re-priced the deal without telling anyone."""

    def test_a_story_that_leaves_a_capability_is_caught_and_named(self):
        inventory, before = an_architecture()
        after = copy.deepcopy(before)
        after["capability_map"]["identity"]["stories"] = ["F1"]
        report = chk.audit(after, inventory, previous=before)
        dropped = [f for f in report["findings"] if f["kind"] == "story_dropped"]
        self.assertEqual({"F2", "F3"}, {f["story"] for f in dropped})
        self.assertEqual({"identity"}, {f["capability"] for f in dropped})
        self.assertIn("without anybody saying so", dropped[0]["detail"])

    def test_the_comparison_is_per_capability_rather_than_over_the_union(self):
        """`application` takes every backend story, so a union comparison can never shrink and
        would pass while identity quietly lost two thirds of its stories."""
        inventory, before = an_architecture()
        after = copy.deepcopy(before)
        after["capability_map"]["identity"]["stories"] = ["F1"]
        union_before = {s for e in before["capability_map"].values() for s in e["stories"]}
        union_after = {s for e in after["capability_map"].values() for s in e["stories"]}
        self.assertEqual(union_before, union_after, "the union is unchanged, as expected")
        self.assertTrue([f for f in chk.audit(after, inventory, previous=before)["findings"]
                         if f["kind"] == "story_dropped"])

    def test_buying_a_capability_passes_the_same_check(self):
        inventory, before = an_architecture()
        candidates = {"identity": {"buy": {
            "name": "A managed identity service", "covers": ["F1", "F2", "F3"], "gaps": [],
            "health": {"score": 9.0}, "pricing_model": "per MAU", "interface": "standard"}}}
        _, after = an_architecture(candidates=candidates)
        report = chk.audit(after, inventory, previous=before)
        self.assertEqual([], [f for f in report["findings"] if f["kind"] == "story_dropped"])


class EveryStoryMustBeServedBySomething(unittest.TestCase):
    """The other direction of the traceability rule: a component with no stories is invented
    infrastructure, and a story with no component is an architecture that does not cover the
    work it was designed for."""

    def test_a_good_architecture_serves_every_story(self):
        inventory, architecture = an_architecture()
        report = chk.audit(architecture, inventory)
        self.assertEqual([], [f for f in report["findings"] if f["kind"] == "story_unserved"])
        self.assertEqual(len([f for f in inventory["features"]]), report["stories_served"])

    def test_an_unserved_story_is_caught_and_named(self):
        inventory, architecture = an_architecture()
        for component in architecture["components"]:
            component["serves"]["stories"] = [s for s in component["serves"]["stories"]
                                              if s != "F14"]
        report = chk.audit(architecture, inventory)
        finding = next(f for f in report["findings"] if f["kind"] == "story_unserved")
        self.assertEqual("F14", finding["story"])
        self.assertIn("no component on the diagram serves it", finding["detail"])


class AGateMustNotRestOnAFactNobodyChecked(unittest.TestCase):
    def test_a_certification_constraint_against_an_unverified_profile_is_caught(self):
        inventory, architecture = an_architecture(
            {"house_platforms": ["aws"],
             "constraints": [{"id": "C1", "kind": "certification", "detail": "HIPAA",
                              "basis": "stated"}]})
        report = chk.audit(architecture, inventory)
        finding = next(f for f in report["findings"] if f["kind"] == "gate_on_unverified_fact")
        self.assertIn("never been verified", finding["detail"])
        self.assertEqual("C1", finding["constraint"])

    def test_a_stale_but_verified_fact_is_caught_with_its_age(self):
        inventory, architecture = an_architecture(
            {"house_platforms": ["aws"],
             "constraints": [{"id": "C1", "kind": "certification", "detail": "HIPAA",
                              "basis": "stated"}]})
        platforms = F.caps.load_platforms()
        platforms["aws"]["volatile"]["certifications"] = {"value": "HIPAA, SOC 2",
                                                          "checked": "2020-01-01"}
        report = chk.audit(architecture, inventory, platforms=platforms)
        finding = next(f for f in report["findings"] if f["kind"] == "gate_on_stale_fact")
        self.assertIn("days ago", finding["detail"])

    def test_a_fresh_verified_fact_raises_nothing(self):
        """Verified on EVERY platform in the chosen set, not just the one the test had in mind:
        the catalogue grew and the set gained a vendor whose certifications were unverified,
        which the audit correctly flagged while this test still expected silence."""
        import datetime as dt
        inventory, architecture = an_architecture(
            {"house_platforms": ["aws"],
             "constraints": [{"id": "C1", "kind": "certification", "detail": "HIPAA",
                              "basis": "stated"}]})
        platforms = F.caps.load_platforms()
        chosen = next(o for o in architecture["layers"]["platform"]["options"]
                      if o["id"] == architecture["layers"]["platform"]["chosen"])
        self.assertTrue(chosen["detail"]["platforms"])
        for pid in chosen["detail"]["platforms"]:
            platforms[pid]["volatile"]["certifications"] = {
                "value": "HIPAA, SOC 2", "checked": dt.date.today().isoformat()}
        report = chk.audit(architecture, inventory, platforms=platforms)
        self.assertEqual([], [f for f in report["findings"]
                              if f["kind"].startswith("gate_on_")])


class TheCommandLine(unittest.TestCase):
    def test_it_exits_non_zero_on_a_finding(self):
        import contextlib
        import io
        import tempfile
        inventory, architecture = an_architecture()
        architecture["components"].append({"id": "x", "capability": "cache", "name": "A cache",
                                           "tier": "data", "mode": "buy",
                                           "serves": {"stories": [], "standing_work": [],
                                                      "assumptions": []}})
        with tempfile.TemporaryDirectory() as tmp:
            here = Path(tmp)
            (here / "architecture.json").write_text(json.dumps(architecture), encoding="utf-8")
            (here / "feature-inventory.json").write_text(json.dumps(inventory), encoding="utf-8")
            argv = sys.argv
            sys.argv = ["architecture-check.py", str(here / "architecture.json")]
            try:
                with contextlib.redirect_stdout(io.StringIO()) as out:
                    code = chk.main()
            finally:
                sys.argv = argv
        self.assertEqual(1, code)
        self.assertFalse(json.loads(out.getvalue())["ok"])

    def test_a_missing_inventory_is_reported_rather_than_guessed(self):
        import contextlib
        import io
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "architecture.json"
            path.write_text("{}", encoding="utf-8")
            argv = sys.argv
            sys.argv = ["architecture-check.py", str(path)]
            try:
                with contextlib.redirect_stdout(io.StringIO()) as out:
                    code = chk.main()
            finally:
                sys.argv = argv
        self.assertEqual(2, code)
        self.assertIn("inventory", json.loads(out.getvalue())["error"])


class CodeHasToRunSomewhereNamed(unittest.TestCase):
    def architecture(self, **component):
        return {"components": [dict({
            "id": "application", "capability": "application", "name": "Django",
            "platform": "aws", "mode": "build", "tier": "application",
            "serves": {"stories": ["F1"], "standing_work": [], "assumptions": []},
        }, **component)], "capability_map": {}, "layers": {}}

    def kinds(self, architecture):
        return [f["kind"] for f in chk.audit(architecture, model=F.model())["findings"]]

    def test_a_built_component_on_a_platform_with_no_runtime_is_reported(self):
        """The profile answered with a choice — "App Runner, ECS Fargate or Lambda" — which is
        three services and not a runtime, so the diagram cannot draw the code inside anything."""
        self.assertIn("runtime_unnamed", self.kinds(self.architecture()))

    def test_naming_the_runtime_settles_it(self):
        self.assertNotIn("runtime_unnamed", self.kinds(self.architecture(
            runs_on={"service": "AWS Fargate", "platform": "aws"})))

    def test_a_bought_component_needs_no_runtime(self):
        self.assertNotIn("runtime_unnamed", self.kinds(self.architecture(
            mode="buy", name="Amazon RDS")))

    def test_a_label_that_repeats_its_own_runtime_is_reported(self):
        """"Django on Fargate" drawn inside "AWS Fargate" is the collapse the containment was
        added to undo, arriving again by way of an operator override."""
        self.assertIn("label_repeats_runtime", self.kinds(self.architecture(
            name="Django on Fargate", runs_on={"service": "AWS Fargate", "platform": "aws"})))

    def test_the_vendor_word_alone_does_not_trip_it(self):
        """"Amazon SES" inside "AWS Fargate" shares only the vendor, which is not a repetition."""
        self.assertNotIn("label_repeats_runtime", self.kinds(self.architecture(
            name="Amazon SES", runs_on={"service": "AWS Fargate", "platform": "aws"})))


if __name__ == "__main__":
    unittest.main()
