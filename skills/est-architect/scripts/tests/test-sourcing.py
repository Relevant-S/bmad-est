#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Tests for sourcing.py — Layer 2, build vs adopt vs buy.

The claims under test are the ones that make the recommendation defensible rather than
plausible: that an unresearched option is not scored as a bad one, that a candidate's gaps
cost effort rather than prose, that build wins when a candidate is poor, and that the asserted
coefficient is labelled as asserted everywhere it is quoted.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fixtures as F  # noqa: E402

src = F.load("sourcing", F.ARCH / "scripts" / "sourcing.py")
caps = F.caps


def decisions(candidates=None, inventory=None):
    inv = inventory or F.clinical()
    model = F.model()
    return src.build_decisions(caps.build_map(inv, model), inv, model, candidates), model


GOOD_BUY = {"identity": {"buy": {
    "name": "A managed identity service", "covers": ["F1", "F2", "F3"], "gaps": [],
    "health": {"score": 9.0, "last_release": "2026-09"}, "pricing_model": "per monthly active user",
    "interface": "standard", "interface_why": "OIDC, so a migration re-issues tokens"}}}

POOR_BUY = {"identity": {"buy": {
    "name": "A narrow identity service", "covers": ["F1"],
    "gaps": ["no role model", "no admin delegation"],
    "health": {"score": 4.0, "note": "single maintainer"}, "pricing_model": "per seat",
    "interface": "proprietary"}}}


class AnUnresearchedOptionIsNotABadOption(unittest.TestCase):
    def test_adopt_scores_null_when_nothing_was_researched(self):
        ds, _ = decisions()
        identity = next(d for d in ds if d["capability"] == "identity")
        adopt = next(o for o in identity["options"] if o["id"] == "adopt")
        for key in ("requirement_fit", "maintenance_health", "cost_licence", "escape_cost"):
            self.assertIsNone(adopt["parts"][key]["score"])
            self.assertIn("never evaluated", adopt["parts"][key]["basis"])

    def test_an_unscored_part_does_not_drag_the_option_down(self):
        """Scoring an unevaluated sub-score as zero would make 'we did not look' and 'we looked
        and it was bad' the same number."""
        ds, _ = decisions()
        identity = next(d for d in ds if d["capability"] == "identity")
        adopt = next(o for o in identity["options"] if o["id"] == "adopt")
        self.assertIsNotNone(adopt["score"], "effort alone should still produce a score")
        self.assertGreater(adopt["score"], 0.0)
        self.assertEqual(["cost_licence", "escape_cost", "maintenance_health",
                          "requirement_fit"], adopt["unscored_parts"])


class GapsCostEffortRatherThanProse(unittest.TestCase):
    def test_a_candidate_with_gaps_scores_lower_on_effort_than_one_without(self):
        good, model = decisions(GOOD_BUY)
        poor, _ = decisions(POOR_BUY)
        g = next(o for o in next(d for d in good if d["capability"] == "identity")["options"]
                 if o["id"] == "buy")
        p = next(o for o in next(d for d in poor if d["capability"] == "identity")["options"]
                 if o["id"] == "buy")
        self.assertGreater(g["parts"]["delivery_effort"]["score"],
                           p["parts"]["delivery_effort"]["score"])

    def test_the_gaps_are_named_in_the_fit_basis(self):
        poor, _ = decisions(POOR_BUY)
        buy = next(o for o in next(d for d in poor if d["capability"] == "identity")["options"]
                   if o["id"] == "buy")
        self.assertIn("no role model", buy["parts"]["requirement_fit"]["basis"])
        self.assertIn("covers 1 of 3", buy["parts"]["requirement_fit"]["basis"])


class NothingUnresearchedIsEverRecommended(unittest.TestCase):
    """The failure the balance check caught in this module's own code: with no candidate, `buy`
    scored on the delivery-effort sub-score alone — which structurally favours not building —
    and beat `build` on every capability nobody had looked at."""

    def test_build_wins_when_no_candidate_was_researched(self):
        ds, _ = decisions()
        for cap in ("async_work", "observability", "analytics_store"):
            d = next(x for x in ds if x["capability"] == cap)
            self.assertEqual("build", d["mode"], f"{cap} recommended an unresearched option")

    def test_it_says_the_alternatives_were_never_researched(self):
        ds, _ = decisions()
        d = next(x for x in ds if x["capability"] == "async_work")
        self.assertEqual(["adopt", "buy"], d["needs_research"])
        self.assertIn("no candidate was researched", d["why"])
        self.assertIn("gap in the evidence rather than a verdict", d["why"])

    def test_a_researched_candidate_is_still_recommendable(self):
        ds, _ = decisions(GOOD_BUY)
        d = next(x for x in ds if x["capability"] == "identity")
        self.assertEqual("buy", d["mode"])
        self.assertEqual(["adopt"], d["needs_research"])


class TheRecommendationRespondsToTheCandidate(unittest.TestCase):
    def test_a_good_candidate_beats_building(self):
        ds, _ = decisions(GOOD_BUY)
        identity = next(d for d in ds if d["capability"] == "identity")
        self.assertEqual("buy", identity["mode"])

    def test_a_poor_candidate_loses_to_building(self):
        """The counterweight that stops the effort sub-score recommending every purchase."""
        ds, _ = decisions(POOR_BUY)
        identity = next(d for d in ds if d["capability"] == "identity")
        self.assertEqual("build", identity["mode"])

    def test_a_blocked_licence_is_visible_on_the_option(self):
        blocked = {"identity": {"adopt": {
            "name": "An AGPL identity server", "covers": ["F1", "F2", "F3"], "gaps": [],
            "licence": "AGPL-3.0", "licence_blocked": True, "interface": "standard"}}}
        ds, _ = decisions(blocked)
        adopt = next(o for o in next(d for d in ds if d["capability"] == "identity")["options"]
                     if o["id"] == "adopt")
        self.assertIn("GATE", adopt["parts"]["cost_licence"]["basis"])


class TheAssertedCoefficientIsLabelledEverywhereItIsQuoted(unittest.TestCase):
    def test_every_non_build_effort_basis_says_it_is_asserted(self):
        ds, _ = decisions(GOOD_BUY)
        checked = 0
        for d in ds:
            for option in d["options"]:
                basis = option["parts"]["delivery_effort"]["basis"]
                if option["id"] == "build":
                    self.assertIn("baseline", basis)
                else:
                    self.assertIn("ASSERTED", basis)
                    checked += 1
        self.assertGreater(checked, 0, "no non-build option was checked — the test proves nothing")

    def test_the_effort_basis_names_the_stories_and_the_size(self):
        ds, _ = decisions()
        identity = next(d for d in ds if d["capability"] == "identity")
        basis = identity["options"][0]["parts"]["delivery_effort"]["basis"]
        self.assertIn("F1", basis)
        self.assertIn("3 stories", basis)


class SettledCapabilitiesStayOutOfTheTables(unittest.TestCase):
    def test_a_settled_capability_carries_its_mode_and_reason_and_no_options(self):
        ds, _ = decisions()
        payments = next(d for d in ds if d["capability"] == "payments")
        self.assertFalse(payments["live"])
        self.assertEqual("buy", payments["mode"])
        self.assertEqual([], payments["options"])
        self.assertIn("compliance regime", payments["why"])

    def test_the_batch_separates_the_scored_from_the_settled(self):
        ds, _ = decisions()
        batch = src.confirmation_batch(ds)
        self.assertIn("| Capability | Work at stake | Recommended |", batch)
        self.assertIn("Settled without scoring", batch)
        self.assertIn("Payments", batch)


class TheBalanceIsMeasuredRatherThanAsserted(unittest.TestCase):
    def test_a_normal_backlog_raises_no_finding(self):
        ds, model = decisions(GOOD_BUY)
        self.assertEqual([], src.balance(ds, model)["findings"])

    def test_settled_defaults_are_excluded_from_the_balance(self):
        """Counting them made the bought share 83% on every backlog, and a finding that fires
        every time is noise that trains a reader to skip it."""
        ds, model = decisions(GOOD_BUY)
        b = src.balance(ds, model)
        self.assertEqual(b["build"] + b["adopt"] + b["buy"], b["live_decisions"])
        self.assertGreater(b["settled"], 0)
        self.assertIn("settled capabilities are excluded", b["counted"])

    def test_building_everything_raises_a_finding_naming_the_share(self):
        ds, model = decisions()
        for d in ds:
            d["mode"], d["live"] = "build", True
        found = src.balance(ds, model)["findings"]
        self.assertEqual(["all_build"], [f["kind"] for f in found])
        self.assertIn("%", found[0]["detail"])

    def test_buying_everything_raises_the_other_finding(self):
        ds, model = decisions()
        for d in ds:
            d["mode"], d["live"] = "buy", True
        found = src.balance(ds, model)["findings"]
        self.assertEqual(["all_buy"], [f["kind"] for f in found])

    def test_the_avoided_stories_are_named_rather_than_counted(self):
        ds, model = decisions(GOOD_BUY)
        avoided = src.balance(ds, model)["stories_avoided"]
        self.assertIn("F1", avoided)
        self.assertTrue(all(isinstance(s, str) for s in avoided))


if __name__ == "__main__":
    unittest.main()
