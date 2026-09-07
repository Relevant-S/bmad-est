#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Tests for estimate.py.

The first class is the important one. The module's whole claim is that under BMad,
effort redistributes rather than shrinking uniformly — and that claim lives or dies on
`review_h` being a share of `manual_baseline` rather than of the compressed `build_h`.
If someone "simplifies" that later, these tests fail loudly.
"""

import importlib.util
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fixtures import feature, inventory, model, options  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "estimate", Path(__file__).resolve().parent.parent / "estimate.py"
)
est = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(est)


def hours(inv, **opt):
    opt.setdefault("granularity", inv.get("granularity", "project"))
    return est.build_estimate(inv, model(), options(**opt))


class TestTheCentralInsight(unittest.TestCase):
    """review_h tracks the volume of output produced, not the time taken to produce it."""

    def price(self, **kwargs):
        m = model()
        return est.price_feature(feature(**kwargs), m, m["team_profiles"]["balanced"])

    def test_compression_shrinks_build_and_leaves_review_untouched(self):
        fast = self.price(compressibility="high", review_tier="sensitive")
        slow = self.price(compressibility="low", review_tier="sensitive")
        self.assertLess(est.pert(fast["components"]["build"])[0],
                        est.pert(slow["components"]["build"])[0])
        self.assertEqual(est.pert(fast["components"]["review"])[0],
                         est.pert(slow["components"]["review"])[0])

    def test_review_scales_with_the_feature_size_not_with_the_build_effort(self):
        small = self.price(size="S", compressibility="high", review_tier="sensitive")
        large = self.price(size="L", compressibility="high", review_tier="sensitive")
        review_ratio = (est.pert(large["components"]["review"])[0]
                        / est.pert(small["components"]["review"])[0])
        manual_ratio = (est.pert(large["manual_baseline"])[0]
                        / est.pert(small["manual_baseline"])[0])
        self.assertAlmostEqual(review_ratio, manual_ratio, delta=0.35)

    def test_review_dominates_a_sensitive_feature_but_not_a_routine_one(self):
        """The whole claim in one assertion: compression moves the bottleneck to review."""
        sensitive = self.price(size="M", compressibility="high", review_tier="sensitive")
        routine = self.price(size="M", compressibility="high", review_tier="routine")
        self.assertEqual(max(sensitive["components"], key=lambda k: est.pert(sensitive["components"][k])[0]),
                         "review")
        self.assertNotEqual(max(routine["components"], key=lambda k: est.pert(routine["components"][k])[0]),
                            "review")

    def test_a_payments_feature_costs_far_more_than_crud_of_the_same_size(self):
        crud = self.price(size="M", compressibility="high", review_tier="routine")
        payments = self.price(size="M", compressibility="high", review_tier="sensitive")
        critical = self.price(size="M", compressibility="high", review_tier="critical")
        self.assertGreater(est.pert(payments["total"])[0], 1.7 * est.pert(crud["total"])[0])
        self.assertGreater(est.pert(critical["total"])[0], est.pert(payments["total"])[0])

    def test_compression_barely_helps_a_sensitive_feature(self):
        """The relative benefit of high compression is much smaller when review dominates."""
        def gain(tier):
            fast = est.pert(self.price(compressibility="high", review_tier=tier)["total"])[0]
            slow = est.pert(self.price(compressibility="low", review_tier=tier)["total"])[0]
            return (slow - fast) / slow

        self.assertGreater(gain("routine"), gain("critical"))

    def test_low_clarity_raises_both_spec_and_rework(self):
        clear = self.price(clarity="high")
        vague = self.price(clarity="low")
        self.assertGreater(est.pert(vague["components"]["spec"])[0],
                           est.pert(clear["components"]["spec"])[0])
        self.assertGreater(est.pert(vague["components"]["rework"])[0],
                           est.pert(clear["components"]["rework"])[0])

    def test_novelty_drives_rework_but_not_build(self):
        standard = self.price(novelty="standard")
        novel = self.price(novelty="novel")
        self.assertEqual(est.pert(standard["components"]["build"])[0],
                         est.pert(novel["components"]["build"])[0])
        self.assertGreater(est.pert(novel["components"]["rework"])[0],
                           est.pert(standard["components"]["rework"])[0])


class TestArithmetic(unittest.TestCase):
    def test_interval_division_pairs_low_numerator_with_high_divisor(self):
        result = est.div((10.0, 20.0, 30.0), (2.0, 4.0, 5.0))
        self.assertEqual(result, (10 / 5, 20 / 4, 30 / 2))

    def test_pert_mean_and_sd(self):
        mean, sd = est.pert((10.0, 20.0, 60.0))
        self.assertAlmostEqual(mean, (10 + 80 + 60) / 6)
        self.assertAlmostEqual(sd, 50 / 6)

    def test_variance_combines_in_quadrature_not_linearly(self):
        one = (0.0, 0.0, 6.0)
        _, sd_single = est.combine([one])
        _, sd_four = est.combine([one] * 4)
        self.assertAlmostEqual(sd_four, 2 * sd_single)    # sqrt(4), not 4

    def test_means_add_exactly(self):
        mean, _ = est.combine([(1.0, 2.0, 3.0)] * 3)
        self.assertAlmostEqual(mean, 3 * 2.0)


class TestBandWidth(unittest.TestCase):
    """Band width is computed from the input, never chosen."""

    def test_thinner_input_produces_a_wider_band(self):
        thin = hours(inventory(), completeness=0.1)
        rich = hours(inventory(), completeness=0.95)
        thin_band = thin["total_hours"]["high"] - thin["total_hours"]["low"]
        rich_band = rich["total_hours"]["high"] - rich["total_hours"]["low"]
        self.assertGreater(thin_band, rich_band)

    def test_band_width_is_monotonic_in_completeness(self):
        widths = []
        for score in (0.0, 0.25, 0.5, 0.75, 1.0):
            e = hours(inventory(), completeness=score)
            widths.append(e["total_hours"]["high"] - e["total_hours"]["low"])
        self.assertEqual(widths, sorted(widths, reverse=True))

    def test_perfect_completeness_applies_no_multiplier(self):
        self.assertAlmostEqual(hours(inventory(), completeness=1.0)["confidence"]["band_multiplier"], 1.0)

    def test_zero_completeness_triples_the_band(self):
        self.assertAlmostEqual(hours(inventory(), completeness=0.0)["confidence"]["band_multiplier"], 3.0)

    def test_the_likely_figure_does_not_move_with_completeness(self):
        """Completeness widens the band; it must not shift the central estimate."""
        thin = hours(inventory(), completeness=0.1)["total_hours"]["likely"]
        rich = hours(inventory(), completeness=0.9)["total_hours"]["likely"]
        self.assertAlmostEqual(thin, rich)

    def test_an_empty_inventory_is_refused_rather_than_priced(self):
        """Project components alone would return a confident number for no scope at all."""
        with self.assertRaises(ValueError) as ctx:
            hours(inventory([]))
        self.assertIn("nothing to estimate", str(ctx.exception))

    def test_model_risk_and_feature_variance_are_reported_separately(self):
        c = hours(inventory([feature(f"F{i}") for i in range(1, 6)]))["confidence"]
        self.assertGreater(c["sd_from_features"], 0)
        self.assertGreater(c["sd_from_model_risk"], 0)
        self.assertLessEqual(c["aggregated_sd"],
                             c["sd_from_features"] + c["sd_from_model_risk"] + 0.01)

    def test_the_band_does_not_collapse_as_features_multiply(self):
        """Quadrature alone would report a suspiciously tight band on a large scope, because
        it assumes feature errors are independent. Systematic model error does not shrink."""
        def relative(n):
            e = hours(inventory([feature(f"F{i}") for i in range(1, n + 1)]))
            t = e["total_hours"]
            return (t["high"] - t["low"]) / 2 / t["likely"]

        self.assertGreater(relative(100), 0.5 * relative(1))

    def test_low_bound_never_goes_negative(self):
        e = hours(inventory([feature(size="XS")]), completeness=0.0)
        self.assertGreaterEqual(e["total_hours"]["low"], 0.0)


class TestPlanningAnchor(unittest.TestCase):
    def test_planning_review_has_a_tighter_relative_band_than_feature_work(self):
        e = hours(inventory([feature(f"F{i}", clarity="low") for i in range(1, 9)]))
        review = e["project_components"]["planning_review"]
        relative_planning = review["sd"] / review["hours"]
        phases = e["by_phase"]
        relative_build = phases["build"]["sd"] / phases["build"]["hours"]
        self.assertLess(relative_planning, relative_build)

    def test_planning_volume_is_derived_from_the_feature_set(self):
        e = hours(inventory([feature(f"F{i}", size="L") for i in range(1, 11)]))
        self.assertEqual(e["planning_volume"]["epics"], 2)         # 10 features / 5
        self.assertEqual(e["planning_volume"]["stories"], 40)      # 10 x 4 stories for L

    def test_planning_scales_sublinearly_with_scope(self):
        small = hours(inventory([feature(f"F{i}") for i in range(1, 6)]))
        large = hours(inventory([feature(f"F{i}") for i in range(1, 26)]))
        ratio = (large["project_components"]["planning_review"]["hours"]
                 / small["project_components"]["planning_review"]["hours"])
        self.assertLess(ratio, 5.0)      # five times the features, less than five times the planning

    def test_a_sprint_pays_no_document_planning(self):
        e = hours(inventory(granularity="sprint"), )
        self.assertEqual(e["planning_volume"]["documents"], [])


class TestSplits(unittest.TestCase):
    def test_agreed_and_additional_scope_are_reported_separately(self):
        inv = inventory([
            feature("F1", "In the SOW"),
            feature("F2", "Raised on the call", scope_status="outside_agreed_scope"),
        ])
        split = hours(inv)["scope_split"]
        self.assertIn("in_agreed_scope", split)
        self.assertIn("outside_agreed_scope", split)
        self.assertEqual(split["outside_agreed_scope"]["features"], 1)

    def test_standalone_cost_exceeds_the_apportioned_share(self):
        """Dropping scope does not save its apportioned share: fixed costs stay behind."""
        inv = inventory([
            feature("F1", "In the SOW"),
            feature("F2", "Raised on the call", scope_status="outside_agreed_scope"),
        ])
        agreed = hours(inv)["scope_split"]["in_agreed_scope"]
        self.assertGreater(agreed["standalone_hours"], agreed["apportioned_hours"])

    def test_apportioned_hours_sum_to_the_project_total(self):
        inv = inventory([
            feature("F1", "In the SOW"),
            feature("F2", "Raised on the call", scope_status="outside_agreed_scope"),
        ])
        e = hours(inv)
        apportioned = sum(v["apportioned_hours"] for k, v in e["scope_split"].items()
                          if not k.startswith("_"))
        self.assertAlmostEqual(apportioned, e["total_hours"]["likely"], delta=0.5)

    def test_project_overheads_are_apportioned_to_additional_scope_too(self):
        inv = inventory([
            feature("F1", "In the SOW"),
            feature("F2", "Raised on the call", scope_status="outside_agreed_scope"),
        ])
        split = hours(inv)["scope_split"]
        self.assertGreater(split["outside_agreed_scope"]["apportioned_project_hours"], 0)

    def test_no_pm_role_appears_anywhere(self):
        roles = hours(inventory())["by_role"]
        self.assertNotIn("pm", roles)
        self.assertIn("architect", roles)

    def test_role_hours_sum_to_the_central_estimate(self):
        e = hours(inventory([feature(f"F{i}", review_tier=t)
                             for i, t in enumerate(["routine", "sensitive", "critical"], 1)]))
        self.assertAlmostEqual(sum(e["by_role"].values()), e["total_hours"]["likely"], delta=0.5)

    def test_phase_hours_sum_to_the_central_estimate(self):
        e = hours(inventory([feature(f"F{i}") for i in range(1, 6)]))
        total = sum(p["hours"] for p in e["by_phase"].values())
        self.assertAlmostEqual(total, e["total_hours"]["likely"], delta=0.5)

    def test_sensitive_review_shifts_hours_toward_the_architect(self):
        routine = hours(inventory([feature("F1", review_tier="routine")]))["by_role"]
        sensitive = hours(inventory([feature("F1", review_tier="sensitive")]))["by_role"]
        self.assertGreater(sensitive["architect"] / sum(sensitive.values()),
                           routine["architect"] / sum(routine.values()))


class TestDependenciesAndDuration(unittest.TestCase):
    def test_critical_path_is_the_longest_chain_not_the_total(self):
        inv = inventory([
            feature("F1", "Integration", size="L"),
            feature("F2", "List view", size="M", depends_on=[{"feature_id": "F1", "inferred": False, "evidence": "x"}]),
            feature("F3", "Unrelated page", size="M"),
        ])
        e = hours(inv)
        feature_total = sum(f["hours"] for f in e["features"])
        self.assertLess(e["dependencies"]["hours"], feature_total)
        self.assertEqual(e["dependencies"]["chain"], ["F1", "F2"])

    def test_independent_features_give_a_short_critical_path(self):
        inv = inventory([feature(f"F{i}", size="M") for i in range(1, 6)])
        e = hours(inv)
        self.assertEqual(len(e["dependencies"]["chain"]), 1)

    def test_duration_states_its_assumed_team_size(self):
        e = hours(inventory([feature(f"F{i}") for i in range(1, 6)]), team_size=3)
        self.assertEqual(e["duration"]["assumed_team_size"], 3)
        self.assertIn("not a commitment", e["duration"]["basis"])

    def test_more_people_cannot_beat_the_critical_path(self):
        inv = inventory([
            feature("F1", size="L"),
            feature("F2", size="L", depends_on=[{"feature_id": "F1", "inferred": True}]),
            feature("F3", size="L", depends_on=[{"feature_id": "F2", "inferred": True}]),
        ])
        few = hours(inv, team_size=2)["duration"]["weeks"]
        many = hours(inv, team_size=6)["duration"]["weeks"]
        self.assertGreaterEqual(few, many)
        self.assertGreater(many, 0)


class TestTeamProfiles(unittest.TestCase):
    def test_seniority_moves_human_effort_but_not_build(self):
        senior = hours(inventory(), team="senior-heavy")
        junior = hours(inventory(), team="junior-heavy")
        self.assertEqual(senior["by_phase"]["build"]["hours"], junior["by_phase"]["build"]["hours"])
        self.assertGreater(junior["by_phase"]["review"]["hours"], senior["by_phase"]["review"]["hours"])

    def test_a_junior_team_costs_more_overall(self):
        self.assertGreater(hours(inventory(), team="junior-heavy")["total_hours"]["likely"],
                           hours(inventory(), team="senior-heavy")["total_hours"]["likely"])

    def test_the_assumed_profile_is_stated_in_the_assumptions(self):
        e = hours(inventory(), team="new-to-bmad")
        self.assertTrue(any("new-to-bmad" in a for a in e["assumptions"]))


class TestTraceabilityAndQuestions(unittest.TestCase):
    def test_a_feature_without_a_citation_is_reported(self):
        e = hours(inventory([feature("F1", citations=[])]))
        self.assertTrue(any("no citation" in f for f in e["traceability"]["findings"]))

    def test_every_inventory_feature_is_priced(self):
        e = hours(inventory([feature(f"F{i}") for i in range(1, 4)]))
        self.assertEqual(e["traceability"]["features_priced"], 3)
        self.assertEqual(e["traceability"]["findings"], [])

    def test_a_low_clarity_feature_generates_a_narrowing_question_worth_hours(self):
        e = hours(inventory([feature("F1", "Vague thing", clarity="low", size="L")]))
        questions = e["narrowing_questions"]
        self.assertTrue(questions)
        self.assertGreater(questions[0]["band_reduction_hours"], 0)
        self.assertIn("F1", questions[0]["question"])

    def test_a_no_op_change_removes_no_band_at_all(self):
        """The guard against the two-formula bug: the sensitivity analysis and the headline
        must share one definition of the band, or every reported reduction is the gap between
        them rather than the value of an answer."""
        inv = inventory([feature(f"F{i}", f"Thing {i}", size="L", clarity="low")
                         for i in range(1, 5)])
        e = hours(inv, completeness=0.4)
        opts = options(completeness=0.4, granularity="project")
        priced = [est.price_feature(f, model(), opts["team"]) for f in inv["features"]]
        for p, raw in zip(priced, inv["features"]):
            p["_raw"] = raw
        project, _, _ = est.project_components(priced, model(), "project", opts)
        opts["completeness_multiplier"] = e["confidence"]["band_multiplier"]
        baseline = e["total_hours"]["high"] - e["total_hours"]["low"]
        # Re-price with no mutation at all; the band must come back identical.
        *_, half = est.band_half_width(
            [f["total"] for f in priced] + list(project.values()), model(), 0.4)
        self.assertAlmostEqual(2 * half, baseline, delta=0.2)

    def test_a_question_removes_a_plausible_slice_not_the_whole_band(self):
        e = hours(inventory([feature(f"F{i}", f"Thing {i}", size="L", clarity="low")
                             for i in range(1, 7)]), completeness=0.4)
        for q in e["narrowing_questions"]:
            self.assertLess(q["band_reduction_pct"], 25.0)
            self.assertGreater(q["band_reduction_hours"], 0.0)

    def test_questions_are_ranked_by_how_much_they_narrow_the_band(self):
        e = hours(inventory([feature("F1", "Big vague", clarity="low", size="XL"),
                             feature("F2", "Small vague", clarity="low", size="XS")]))
        reductions = [q["band_reduction_hours"] for q in e["narrowing_questions"]]
        self.assertEqual(reductions, sorted(reductions, reverse=True))

    def test_an_unconfirmed_sensitive_tier_is_worth_asking_about(self):
        f = feature("F1", "Maybe payments", review_tier="sensitive", size="L")
        e = hours(inventory([f]))
        self.assertTrue(any("really touches money" in q["question"] for q in e["narrowing_questions"]))

    def test_a_fully_specified_inventory_raises_no_questions(self):
        f = feature("F1", clarity="high", review_tier="routine", size="M")
        f["tags"]["review_tier"]["status"] = "confirmed"
        self.assertEqual(hours(inventory([f]))["narrowing_questions"], [])


class TestModeAndSnapshot(unittest.TestCase):
    def test_quick_mode_skips_the_expensive_analysis(self):
        e = hours(inventory(), mode="quick")
        self.assertNotIn("narrowing_questions", e)
        self.assertNotIn("dependencies", e)
        self.assertIn("total_hours", e)

    def test_the_cost_model_is_snapshotted_into_every_estimate(self):
        e = hours(inventory())
        self.assertEqual(e["cost_model_snapshot"]["review_rate"]["sensitive"]["likely"], 0.35)

    def test_build_compression_compares_like_with_like(self):
        e = hours(inventory([feature(f"F{i}", compressibility="high", review_tier="routine")
                             for i in range(1, 6)]))
        me = e["manual_equivalent"]
        self.assertGreater(me["build_hours"], me["bmad_build_hours"])
        self.assertGreater(me["build_compression"], 4.0)

    def test_build_compression_is_not_presented_as_project_compression(self):
        """Quoting an 8x build compression as though the project were 8x cheaper is the
        overclaim this module exists to avoid: planning, QA, infra and overhead do not compress."""
        e = hours(inventory([feature(f"F{i}", compressibility="high", review_tier="routine")
                             for i in range(1, 6)]))
        self.assertIsNone(e["manual_equivalent"]["whole_project_compression"])
        self.assertIn("manual project pays too", e["manual_equivalent"]["why"])
        # The project total exceeds the features' manual baseline, because the manual baseline
        # never included planning, environments, QA or client overhead in the first place.
        self.assertGreater(e["total_hours"]["likely"], e["manual_equivalent"]["build_hours"])

    def test_an_unknown_tag_value_fails_loudly(self):
        f = feature("F1")
        f["tags"]["size_band"]["value"] = "XXL"
        with self.assertRaises(KeyError):
            hours(inventory([f]))


if __name__ == "__main__":
    unittest.main()
