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

    def test_the_architect_carries_no_story_work_at_any_review_tier(self):
        """The tech lead does not review stories; the developer does. An architect share
        spread over every story invented a quarter of the Kampies project out of a weight
        table, so this is asserted at the tier where the old model leaned hardest."""
        m = model()
        for tier in ("routine", "sensitive", "critical"):
            priced = est.price_feature(feature("F1", review_tier=tier), m,
                                       m["team_profiles"]["balanced"])
            roles = est.feature_roles(priced, m)
            self.assertNotIn("architect", roles, f"architect billed on a {tier} story")

    def test_a_backend_story_bills_no_ux_and_no_devops(self):
        m = model()
        priced = est.price_feature(feature("F1", surfaces=["backend"]), m,
                                   m["team_profiles"]["balanced"])
        roles = est.feature_roles(priced, m)
        self.assertEqual(sorted(roles), ["ba", "dev"])

    def test_a_design_story_bills_ux_and_still_no_devops(self):
        m = model()
        priced = est.price_feature(feature("F1", surfaces=["frontend", "design"]), m,
                                   m["team_profiles"]["balanced"])
        roles = est.feature_roles(priced, m)
        self.assertIn("ux", roles)
        self.assertNotIn("devops", roles)

    def test_dropping_a_role_reallocates_rather_than_discounts(self):
        """Renormalising is what keeps the split an allocation of the total. If a narrow
        surface set made hours vanish instead of moving, every backend-heavy estimate would
        quietly come in under its own headline."""
        m = model()
        wide = est.price_feature(feature("F1"), m, m["team_profiles"]["balanced"])
        narrow = est.price_feature(feature("F1", surfaces=["backend"]), m,
                                   m["team_profiles"]["balanced"])
        self.assertAlmostEqual(sum(est.feature_roles(wide, m).values()),
                               sum(est.feature_roles(narrow, m).values()), delta=0.01)

    def test_surfaces_are_read_from_either_the_feature_or_its_tags(self):
        """Both placements exist in the wild — the schema puts surfaces on the story, and a
        classifier writing all five axes at once naturally puts it with the tags. Reading only
        one would silently drop every role restriction the other way round."""
        m = model()
        on_feature = feature("F1", surfaces=["backend"])
        in_tags = feature("F2", surfaces=None)
        in_tags["tags"]["surfaces"] = {"value": ["backend"], "why": "x", "status": "inferred"}
        for raw in (on_feature, in_tags):
            priced = est.price_feature(raw, m, m["team_profiles"]["balanced"])
            self.assertEqual(sorted(est.feature_roles(priced, m)), ["ba", "dev"], raw["id"])

    def test_implicit_scope_is_priced_and_needs_a_reason_not_a_quote(self):
        """Work the source implies but never states is real, and pretending it has a quote
        would be worse than admitting it does not."""
        item = feature("I1", "Migrate ten years of bookings", size="L")
        del item["citations"]
        item["rationale"] = "The workbook says bookings already exist; they have to be moved."
        e = hours(inventory([feature("F1")], implicit_scope=[item]))
        self.assertEqual(e["traceability"]["implicit_scope_priced"], 1)
        self.assertEqual(e["traceability"]["findings"], [])
        self.assertIn("I1", [f["id"] for f in e["features"]])

    def test_implicit_scope_without_a_reason_is_reported(self):
        item = feature("I1", "Something nobody asked for")
        del item["citations"]
        e = hours(inventory([feature("F1")], implicit_scope=[item]))
        self.assertTrue(any("I1" in f for f in e["traceability"]["findings"]))

    def test_an_untagged_story_keeps_every_role_rather_than_discounting(self):
        """Silence is not evidence that a role is absent."""
        m = model()
        priced = est.price_feature(feature("F1", surfaces=None), m,
                                   m["team_profiles"]["balanced"])
        self.assertIn("ux", est.feature_roles(priced, m))

    def test_per_story_role_hours_sum_to_the_project_role_totals(self):
        e = hours(inventory([feature(f"F{i}", surfaces=s) for i, s in enumerate(
            [["backend"], ["frontend", "design"], ["infra"], ["backend", "data"]], 1)]))
        per_story = {}
        for f in e["features"]:
            for role, h in f["by_role"].items():
                per_story[role] = per_story.get(role, 0.0) + h
        project = {name: sum(
            v["hours"] * share for name2, v in e["project_components"].items()
            for r, share in est.component_roles(model(), name2, None).items() if r == name)
            for name in set(e["by_role"])}
        for role, total in e["by_role"].items():
            self.assertAlmostEqual(per_story.get(role, 0.0) + project.get(role, 0.0),
                                   total, delta=0.5, msg=role)


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
        raws = inv["features"] + est.standing_features(model(), opts)
        priced = [est.price_feature(f, model(), opts["team"]) for f in raws]
        for p, raw in zip(priced, raws):
            p["_raw"] = raw
        project, *_ = est.project_components(priced, model(), "project", opts)
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
        # Standing work is deliberately excluded here: setup and pipeline work barely
        # compresses, and mixing it in makes this assertion about the delivery mix rather
        # than about the comparison the assertion names.
        e = hours(inventory([feature(f"F{i}", compressibility="high", review_tier="routine")
                             for i in range(1, 6)]), no_standing_work=True)
        me = e["manual_equivalent"]
        self.assertGreater(me["build_hours"], me["bmad_build_hours"])
        self.assertGreater(me["build_compression"], 4.0)

    def test_standing_work_drags_the_compression_down_rather_than_being_hidden(self):
        """Setup, pipelines and environments do not compress, and an estimate that leaves
        them out reports a project compression it cannot deliver."""
        args = dict(inventory([feature(f"F{i}", compressibility="high", review_tier="routine")
                               for i in range(1, 6)]))
        with_standing = hours(dict(args))["manual_equivalent"]["build_compression"]
        without = hours(dict(args), no_standing_work=True)["manual_equivalent"]["build_compression"]
        self.assertLess(with_standing, without)

    def test_standing_work_is_declared_rather_than_folded_into_the_total(self):
        e = hours(inventory([feature("F1")]))
        names = [i["id"] for i in e["standing_work"]["items"]]
        self.assertIn("SW-ci_pipeline", names)
        self.assertGreater(e["standing_work"]["hours"], 0)
        self.assertTrue(all(i["why"] for i in e["standing_work"]["items"]))
        self.assertEqual(e["traceability"]["findings"], [])

    def test_standing_work_gets_no_epic_and_no_story(self):
        """It never reaches a PRD, so billing planning artefacts for it invents documents."""
        inv = inventory([feature(f"F{i}") for i in range(1, 11)])
        self.assertEqual(hours(inv)["planning_volume"],
                         hours(inv, no_standing_work=True)["planning_volume"])

    def test_build_compression_is_not_presented_as_project_compression(self):
        """Quoting an 8x build compression as though the project were 8x cheaper is the
        overclaim this module exists to avoid: planning, QA, infra and overhead do not compress."""
        e = hours(inventory([feature(f"F{i}", compressibility="high", review_tier="routine")
                             for i in range(1, 6)]))
        me = e["manual_equivalent"]
        self.assertIsNone(me["whole_project_compression"])
        self.assertIn("manual project pays too", me["why"])
        # The invariant is that the PROJECT compresses far less than the BUILD does: once
        # generation collapses the build, planning, review, QA and client overhead are what
        # is left, and they dominate. Asserting the total also beats the manual baseline
        # would be a different and weaker claim — on an all-CRUD scope it is simply false,
        # and a test that demanded it would be pushing the module toward the overclaim.
        self.assertGreater(me["build_compression"], 3.0)
        self.assertGreater(e["total_hours"]["likely"], 3 * me["bmad_build_hours"])

    def test_an_unknown_tag_value_fails_loudly(self):
        f = feature("F1")
        f["tags"]["size_band"]["value"] = "XXL"
        with self.assertRaises(KeyError):
            hours(inventory([f]))


class CalibrationClaim(unittest.TestCase):
    """`calibrated` gates a claim made to a client, so it is structural, not a prose match."""

    def test_the_seed_model_is_not_calibrated(self):
        self.assertFalse(est.is_calibrated(model()))

    def test_rewording_the_prose_status_cannot_flip_the_claim(self):
        cost_model = model()
        cost_model["calibration_status"] = "Not yet calibrated against any delivered project."
        self.assertFalse(est.is_calibrated(cost_model))

    def test_a_real_calibration_makes_it_true(self):
        cost_model = model()
        cost_model["calibration_history"] = [{"date": "2026-10-01", "approved_by": "lead"}]
        self.assertTrue(est.is_calibrated(cost_model))

    def test_a_judgement_change_alone_is_not_calibration(self):
        cost_model = model()
        cost_model["calibration_history"] = [{"date": "2026-10-01", "kind": "judgement"}]
        self.assertFalse(est.is_calibrated(cost_model))

    def test_band_width_matches_the_reported_endpoints(self):
        priced = est.build_estimate(inventory(), model(), options())
        total, confidence = priced["total_hours"], priced["confidence"]
        self.assertAlmostEqual(confidence["band_width"], total["high"] - total["low"], places=0)

    def test_options_from_refuses_an_unknown_team_rather_than_defaulting(self):
        priced = est.build_estimate(inventory(), model(), options())
        priced["inputs"]["team_profile"] = "wizards"
        with self.assertRaises(ValueError):
            est.options_from(priced, model())

    def test_options_from_reproduces_the_recorded_inputs(self):
        priced = est.build_estimate(inventory(), model(),
                                    options(team="junior-heavy", completeness=0.33))
        reproduced = est.options_from(priced, model())
        self.assertEqual(reproduced["team_name"], "junior-heavy")
        self.assertEqual(reproduced["input_completeness"], 0.33)


if __name__ == "__main__":
    unittest.main()
