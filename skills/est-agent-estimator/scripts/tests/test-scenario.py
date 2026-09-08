#!/usr/bin/env python3
"""Tests for scenario.py.

The cases that matter here are the ones where a wrong answer reads correct: a saving quoted
as the dropped feature's own hours, a what-if silently re-priced at the default team profile,
a cut proposed that the budget never needed, a budget below what any scope can reach.
"""

import json
import tempfile
import unittest
from pathlib import Path

import fixtures as fx

sc = fx.scenario_module()


def priced(features=None, **kw):
    # Standing work off by default here. It is an uncuttable floor of setup, pipeline and
    # environment hours, which is correct in an estimate and noise in a test about the cut-line
    # walk — it would make every budget assertion a statement about the catalogue's size. The
    # tests that care about the floor turn it back on.
    kw.setdefault("no_standing_work", True)
    return fx.estimate(features=features, **kw)


def run(estimate, **kw):
    """Drive the module the way the CLI does, without the subprocess."""
    class Args:
        pass
    args = Args()
    with tempfile.TemporaryDirectory() as tmp:
        args.estimate = fx.write(tmp, "estimate.json", estimate)
        args.drop = kw.get("drop")
        args.with_dependents = kw.get("with_dependents", False)
        args.retag = kw.get("retag")
        args.set = kw.get("set")
        args.add_file = None
        if kw.get("add"):
            args.add_file = fx.write(tmp, "add.json", kw["add"])
        args.to_budget = kw.get("to_budget")
        args.cost_model = None
        if kw.get("cost_model"):
            args.cost_model = fx.write(tmp, "model.json", kw["cost_model"])
        args.engine = kw.get("engine")
        args.output = None
        return sc.run(args)


CHAIN = [
    ("F1", dict(size="L", review_tier="sensitive")),
    ("F2", dict(size="M")),
    ("F4", dict(size="XS", commitment="speculative", scope_status="outside_agreed_scope")),
]


def chain_features():
    feats = [fx.feature(fid, **kw) for fid, kw in CHAIN]
    feats.append(fx.depends("F3", "F1", size="S"))
    return feats


class StandingWorkFloor(unittest.TestCase):
    """Setup, pipeline and environment work is not scope a client declines line by line."""

    def test_standing_work_is_never_offered_as_a_cut(self):
        cut = run(fx.estimate(features=chain_features()), to_budget=50.0)["cutline"]
        offered = {c["id"] for c in cut["candidates"]}
        self.assertFalse({i for i in offered if i.startswith("SW-")}, offered)

    def test_a_budget_under_the_standing_floor_says_so_rather_than_cutting_the_pipeline(self):
        cut = run(fx.estimate(features=chain_features()), to_budget=1.0)["cutline"]
        self.assertFalse(cut["under_target"])
        self.assertIn("standing setup work", cut["unreachable_reason"])


class Parity(unittest.TestCase):
    def test_baseline_reproduces_the_recorded_headline(self):
        result = run(priced(), drop=None, retag=["F1:clarity=high"])
        self.assertTrue(result["baseline"]["reproduced"])
        self.assertEqual(result["baseline"]["drift"], 0.0)

    def test_refuses_when_the_baseline_does_not_reproduce(self):
        estimate = priced()
        estimate["total_hours"]["likely"] += 40  # someone edited the estimate by hand
        with self.assertRaises(sc.Refused) as ctx:
            run(estimate, drop=None, retag=["F1:clarity=high"])
        self.assertIn("difference against that baseline", str(ctx.exception))

    def test_a_deliberate_model_override_reports_the_shift_instead_of_refusing(self):
        estimate = priced()
        model = json.loads(json.dumps(estimate["cost_model_snapshot"]))
        for bound in ("lo", "likely", "hi"):
            model["review_rate"]["routine"][bound] *= 3
        result = run(estimate, retag=["F1:clarity=high"], cost_model=model)
        self.assertFalse(result["baseline"]["reproduced"])
        self.assertIn("model moving, not the scenario", result["model_shift"])


class ProfileInputs(unittest.TestCase):
    def test_reprices_on_the_estimates_own_team_not_the_default(self):
        result = run(priced(team="junior-heavy"), drop=None, retag=["F1:clarity=high"])
        self.assertEqual(result["inputs"]["team_name"], "junior-heavy")
        self.assertTrue(result["baseline"]["reproduced"])

    def test_a_senior_team_is_cheaper_than_the_estimates_junior_one(self):
        result = run(priced(team="junior-heavy"), set=["team_profile=senior-heavy"])
        before = result["comparison"]["total_hours"]["before"]["likely"]
        after = result["comparison"]["total_hours"]["after"]["likely"]
        self.assertLess(after, before)

    def test_the_engine_owns_the_options_definition(self):
        """Not a local copy: a divergent fallback re-prices at a different profile silently."""
        import inspect
        source = inspect.getsource(sc.options_from)
        self.assertIn("est.options_from", source)

    def test_unknown_team_profile_is_refused_with_the_known_ones(self):
        with self.assertRaises(sc.Refused) as ctx:
            run(priced(), set=["team_profile=wizards"])
        self.assertIn("balanced", str(ctx.exception))

    def test_unknown_profile_key_is_refused(self):
        with self.assertRaises(sc.Refused) as ctx:
            run(priced(), set=["velocity=high"])
        self.assertIn("not a profile input", str(ctx.exception))


class Dropping(unittest.TestCase):
    def test_the_saving_is_not_the_dropped_features_own_hours(self):
        result = run(priced(chain_features()), drop=["F2"])
        comparison = result["comparison"]
        self.assertNotEqual(comparison["saving"], comparison["dropped_features_own_hours"])
        self.assertIn("never", comparison["saving_vs_own_hours"])

    def test_the_saving_equals_a_genuine_reprice(self):
        features = chain_features()
        result = run(priced(features), drop=["F2"])
        remaining = [f for f in features if f["id"] != "F2"]
        self.assertAlmostEqual(
            result["comparison"]["total_hours"]["after"]["likely"],
            priced(remaining)["total_hours"]["likely"], places=1)

    def test_dropping_a_depended_on_feature_warns_about_what_breaks(self):
        result = run(priced(chain_features()), drop=["F1"])
        warnings = result["comparison"]["dependency_warnings"]
        self.assertEqual(warnings[0]["breaks"], ["F3"])
        self.assertIn("depends on F1", warnings[0]["detail"])

    def test_with_dependents_takes_the_whole_closure_and_stops_warning(self):
        result = run(priced(chain_features()), drop=["F1"], with_dependents=True)
        self.assertEqual(result["mutations"]["dropped"], ["F1", "F3"])
        self.assertEqual(result["comparison"]["dependency_warnings"], [])

    def test_dropping_an_unknown_feature_is_refused(self):
        with self.assertRaises(sc.Refused) as ctx:
            run(priced(chain_features()), drop=["F9"])
        self.assertIn("not in this estimate", str(ctx.exception))

    def test_dropping_everything_is_refused(self):
        with self.assertRaises(sc.Refused) as ctx:
            run(priced(chain_features()), drop=["F1", "F2", "F3", "F4"])
        self.assertIn("not an estimate of anything", str(ctx.exception))

    def test_band_narrows_with_scope(self):
        result = run(priced(chain_features()), drop=["F1"])
        band = result["comparison"]["band_width"]
        self.assertLess(band["after"], band["before"])


class Retagging(unittest.TestCase):
    def test_downgrading_a_review_tier_reduces_review_hours(self):
        result = run(priced(chain_features()), retag=["F1:review_tier=routine"])
        self.assertLess(result["comparison"]["by_phase_change"]["review"], 0)

    def test_a_tag_value_absent_from_the_cost_model_fails_loudly(self):
        with self.assertRaises(KeyError):
            run(priced(chain_features()), retag=["F1:review_tier=paranoid"])

    def test_an_unknown_axis_is_refused(self):
        with self.assertRaises(sc.Refused) as ctx:
            run(priced(chain_features()), retag=["F1:urgency=high"])
        self.assertIn("not a classification axis", str(ctx.exception))

    def test_retagging_a_dropped_feature_is_refused(self):
        with self.assertRaises(sc.Refused) as ctx:
            run(priced(chain_features()), drop=["F1"], retag=["F1:clarity=high"])
        self.assertIn("not in the remaining scope", str(ctx.exception))

    def test_malformed_retag_is_refused(self):
        with self.assertRaises(sc.Refused):
            run(priced(), retag=["F1 review_tier routine"])


class Adding(unittest.TestCase):
    def test_a_change_request_is_priced_into_the_project(self):
        result = run(priced(chain_features()), add=[fx.feature("F9", size="L")])
        self.assertEqual(result["mutations"]["added"], ["F9"])
        self.assertGreater(result["comparison"]["saving"], -10_000)
        self.assertLess(result["comparison"]["saving"], 0)  # a negative saving is a cost

    def test_adding_a_duplicate_id_is_refused(self):
        with self.assertRaises(sc.Refused) as ctx:
            run(priced(chain_features()), add=[fx.feature("F1")])
        self.assertIn("already priced", str(ctx.exception))


class Decomposable(unittest.TestCase):
    """A scenario total is said out loud in a negotiation, so it must break down like any other."""

    def test_a_retagged_scenario_reports_per_feature_hours(self):
        result = run(priced(chain_features()), retag=["F1:review_tier=routine"])
        features = result["scenario_estimate"]["features"]
        self.assertEqual({f["id"] for f in features}, {"F1", "F2", "F3", "F4"})
        self.assertTrue(all(f.get("hours") is not None for f in features))
        moved = next(f for f in features if f["id"] == "F1")
        self.assertLess(moved["change"], 0)
        self.assertEqual(moved["hours"], round(moved["was"] + moved["change"], 1))

    def test_per_feature_hours_sum_consistently_with_the_headline(self):
        features = chain_features()
        result = run(priced(features), set=["team_profile=senior-heavy"])
        rows = result["scenario_estimate"]["features"]
        repriced = priced(features, team="senior-heavy")
        self.assertEqual({f["id"]: f["hours"] for f in rows},
                         {f["id"]: f["hours"] for f in repriced["features"]})

    def test_the_coefficient_behind_a_feature_is_reachable(self):
        result = run(priced(chain_features()), retag=["F1:review_tier=routine"])
        row = next(f for f in result["scenario_estimate"]["features"] if f["id"] == "F1")
        self.assertEqual(row["tags"]["review_tier"], "routine")
        self.assertIn("review", row["component_hours"])
        self.assertIn(row["dominant_component"], row["component_hours"])

    def test_dropped_features_report_what_they_were_worth(self):
        result = run(priced(chain_features()), drop=["F2"])
        dropped = result["scenario_estimate"]["dropped"]
        self.assertEqual([d["id"] for d in dropped], ["F2"])
        self.assertGreater(dropped[0]["was"], 0)


class Cutline(unittest.TestCase):
    """Budgets are a share of the fixture's own total, never an absolute.

    These were pinned at 150 h, which is more than the whole fixture costs once the bands
    moved to story scale — so each one asked for a budget already met and passed without
    cutting anything, and the restore case failed because there was nothing to restore. A
    cut-line test whose budget exceeds the total is not testing a cut line.
    """

    def budget(self, estimate, share=0.75):
        return estimate["total_hours"]["likely"] * share

    def test_reaches_a_feasible_budget(self):
        estimate = priced(chain_features())
        target = self.budget(estimate)
        cut = run(estimate, to_budget=target)["cutline"]
        self.assertTrue(cut["under_target"])
        self.assertLessEqual(cut["achieved_likely"], target)

    def test_restores_cuts_the_budget_did_not_need(self):
        estimate = priced(chain_features())
        cut = run(estimate, to_budget=self.budget(estimate))["cutline"]
        self.assertIn("F4", cut["restored_as_unnecessary"])
        self.assertNotIn("F4", cut["proposed_drop"])

    def test_a_dropped_feature_takes_its_dependents_with_it(self):
        """F3 depends on F1, so F1 cannot go while F3 stays."""
        estimate = priced(chain_features())
        cut = run(estimate, to_budget=self.budget(estimate))["cutline"]
        if "F1" in cut["proposed_drop"]:
            self.assertIn("F3", cut["proposed_drop"])

    def test_an_unreachable_budget_says_why_rather_than_returning_nothing(self):
        cut = run(priced(chain_features()), to_budget=20.0)["cutline"]
        self.assertFalse(cut["under_target"])
        self.assertIn("paid on whatever ships", cut["unreachable_reason"])
        self.assertGreater(cut["achieved_likely"], 20.0)

    def test_never_proposes_dropping_every_feature(self):
        cut = run(priced(chain_features()), to_budget=1.0)["cutline"]
        self.assertLess(len(cut["proposed_drop"]), 4)

    def test_a_budget_already_met_proposes_nothing(self):
        cut = run(priced(chain_features()), to_budget=10_000.0)["cutline"]
        self.assertEqual(cut["proposed_drop"], [])
        self.assertTrue(cut["under_target"])

    def test_a_feature_everything_depends_on_is_not_offered_as_a_cut(self):
        features = [fx.feature("F1", size="M"),
                    fx.depends("F2", "F1", size="M"),
                    fx.depends("F3", "F2", size="M")]
        cut = run(priced(features), to_budget=10.0)["cutline"]
        root = next(c for c in cut["candidates"] if c["id"] == "F1")
        self.assertIsNone(root["saving"])
        self.assertIn("not a cut", root["note"])

    def test_every_candidate_saving_is_a_real_reprice(self):
        features = chain_features()
        cut = run(priced(features), to_budget=150.0)["cutline"]
        f2 = next(c for c in cut["candidates"] if c["id"] == "F2")
        remaining = [f for f in features if f["id"] != "F2"]
        expected = priced(features)["total_hours"]["likely"] - priced(remaining)["total_hours"]["likely"]
        self.assertAlmostEqual(f2["saving"], round(expected, 1), places=1)


class Refusals(unittest.TestCase):
    def test_an_estimate_without_a_snapshot_is_refused(self):
        estimate = priced()
        del estimate["cost_model_snapshot"]
        with self.assertRaises(sc.Refused) as ctx:
            run(estimate, drop=None, retag=["F1:clarity=high"])
        self.assertIn("no cost_model_snapshot", str(ctx.exception))

    def test_an_estimate_without_a_completeness_score_is_refused(self):
        estimate = priced()
        del estimate["confidence"]["input_completeness"]
        with self.assertRaises(sc.Refused) as ctx:
            run(estimate, drop=["F1"])
        self.assertIn("band cannot be reproduced", str(ctx.exception))

    def test_a_missing_engine_names_the_recovery(self):
        with self.assertRaises(sc.Refused) as ctx:
            run(priced(), drop=["F1"], engine="/nowhere/estimate.py")
        self.assertIn("--engine", str(ctx.exception))


class Closure(unittest.TestCase):
    def test_transitive_dependents_are_included(self):
        features = [fx.feature("F1"), fx.depends("F2", "F1"), fx.depends("F3", "F2")]
        self.assertEqual(sc.closure(["F1"], features), {"F1", "F2", "F3"})

    def test_a_leaf_closes_over_itself_only(self):
        features = [fx.feature("F1"), fx.depends("F2", "F1")]
        self.assertEqual(sc.closure(["F2"], features), {"F2"})

    def test_a_dependency_cycle_terminates(self):
        a, b = fx.depends("F1", "F2"), fx.depends("F2", "F1")
        self.assertEqual(sc.closure(["F1"], [a, b]), {"F1", "F2"})

    def test_a_dependency_on_a_feature_outside_the_scope_is_ignored(self):
        features = [fx.depends("F1", "GONE")]
        self.assertEqual(sc.closure(["F1"], features), {"F1"})


class CutlineOrdering(unittest.TestCase):
    """A budget is reached by disturbing as little as possible, not by taking the biggest cut."""

    def big_and_small(self):
        return [fx.feature("BIG", size="XL", review_tier="critical", compressibility="low"),
                fx.feature("S1", size="S"), fx.feature("S2", size="S"), fx.feature("S3", size="S")]

    def test_small_cuts_are_preferred_over_one_drastic_one(self):
        features = self.big_and_small()
        estimate = priced(features)
        smalls = [f for f in estimate["features"] if f["id"] != "BIG"]
        target = estimate["total_hours"]["likely"] - sum(f["hours"] for f in smalls) * 0.5
        cut = run(estimate, to_budget=target)["cutline"]
        self.assertTrue(cut["under_target"])
        self.assertNotIn("BIG", cut["proposed_drop"])

    def test_the_drastic_cut_is_taken_when_nothing_else_reaches(self):
        features = self.big_and_small()
        estimate = priced(features)
        cut = run(estimate, to_budget=estimate["total_hours"]["likely"] * 0.3)["cutline"]
        self.assertIn("BIG", cut["proposed_drop"])

    def test_outside_agreed_scope_goes_before_committed_work(self):
        """The budget is derived from what dropping B actually achieves, rather than a
        percentage. A fixed percentage silently became unreachable-by-one-story the moment
        the bands moved to story scale, and the test then failed for arithmetic reasons
        while the ordering rule it names was working perfectly."""
        features = [fx.feature("A", size="M"),
                    fx.feature("B", size="M", scope_status="outside_agreed_scope"),
                    fx.feature("C", size="M")]
        estimate = priced(features)
        reachable = run(estimate, drop=["B"])["scenario_estimate"]["total_hours"]["likely"]
        cut = run(estimate, to_budget=reachable)["cutline"]
        self.assertEqual(cut["proposed_drop"], ["B"])

    def test_no_proposed_cut_is_unnecessary(self):
        """The invariant that matters: putting any one of them back breaks the budget.

        This is what protects the proposal from a stale saving figure. A candidate chosen on a
        number that was true of the untouched baseline but no longer true of the current scope
        contributes nothing, and a client would be asked to give it up for no reason.
        """
        features = chain_features() + [fx.feature("F5", size="M"), fx.feature("F6", size="S")]
        estimate = priced(features)
        target = estimate["total_hours"]["likely"] * 0.6
        cut = run(estimate, to_budget=target)["cutline"]
        self.assertTrue(cut["under_target"])
        for restored in cut["proposed_drop"]:
            needs = {d["feature_id"] for f in features if f["id"] == restored
                     for d in (f.get("depends_on") or [])}
            if needs & set(cut["proposed_drop"]):
                continue  # it cannot come back without what it was built on
            kept = [f for f in features if f["id"] not in set(cut["proposed_drop"]) - {restored}]
            self.assertGreater(priced(kept)["total_hours"]["likely"], target,
                               f"{restored} was cut but the budget did not need it")

    def test_every_step_reports_a_real_cumulative_reprice(self):
        features = self.big_and_small()
        estimate = priced(features)
        cut = run(estimate, to_budget=estimate["total_hours"]["likely"] * 0.7)["cutline"]
        running = []
        for step in cut["steps"]:
            running += step["drop"]
            remaining = [f for f in features if f["id"] not in running]
            self.assertAlmostEqual(step["cumulative_likely"],
                                   priced(remaining)["total_hours"]["likely"], places=1)


if __name__ == "__main__":
    unittest.main(verbosity=1)
