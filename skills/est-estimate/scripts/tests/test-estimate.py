#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Tests for estimate.py.

The first class is the important one, and in 3.0 it says something different from 2.0.
The 2.x claim was that review dominates a sensitive story because review scales with a
manual baseline while the build compresses away. Three delivered projects were then
measured, and the story-level half of that claim did not survive: on the anchor, sensitive
stories run 1.05x routine ones, and 1.06x once every provider-touching story is excluded.
What actually makes a story expensive is the PROVIDER behind it — a money rail carries
+0.75 points over what its surface count predicts, an external IdP +0.73 — and that is
additive console work, not a multiple of anything.

So the first class now pins the measured claims: bands span 4.8x rather than 90x, the
tier barely moves a total but does move where the hours are reported, and the premium is
what a payments story actually costs. If someone re-derives the old shape, these fail.
"""

import importlib.util
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fixtures import feature, inventory, model, options, tag  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "estimate", Path(__file__).resolve().parent.parent / "estimate.py"
)
est = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(est)


def hours(inv, **opt):
    opt.setdefault("granularity", inv.get("granularity", "project"))
    return est.build_estimate(inv, model(), options(**opt))


class TestTheCentralInsight(unittest.TestCase):
    """What the delivered record says makes a story expensive — and what does not."""

    def price(self, **kwargs):
        m = model()
        return est.price_feature(feature(**kwargs), m, m["team_profiles"]["balanced"])

    def test_the_band_spread_is_the_one_the_anchor_measured_not_the_2x_one(self):
        """The single most consequential number in the file. EPP's own per-story record runs
        1.2 h to 5.8 h of dev time across XS to XL — 4.8x. The 2.x bands ran 1 h to 90 h of
        manual baseline, and every sizing bias in the module came from that width."""
        bands = model()["size_bands"]
        spread = bands["XL"]["likely"] / bands["XS"]["likely"]
        self.assertLess(spread, 6.0, "the spread is back to something the anchor cannot support")
        self.assertGreater(spread, 4.0)

    def test_one_band_of_error_costs_about_a_third_not_three_times(self):
        """Under 2.x, M -> L multiplied a story by 3.0x, so band assignment carried roughly
        eight times the weight the delivered record supports. That is what made the review
        step's pull toward the anchor's mix so consequential."""
        step = (est.pert(self.price(size="L")["total"])[0]
                / est.pert(self.price(size="M")["total"])[0])
        self.assertLess(step, 1.6, "a one-band error is expensive again")
        self.assertGreater(step, 1.1)

    def test_review_tier_barely_moves_a_story_because_the_anchor_says_so(self):
        """MEASURED: sensitive 3.24 points against routine 3.08 — 1.05x. Not 1.9x."""
        routine = est.pert(self.price(size="M", review_tier="routine")["total"])[0]
        sensitive = est.pert(self.price(size="M", review_tier="sensitive")["total"])[0]
        self.assertLess(sensitive / routine, 1.15,
                        "review_tier is inflating a story again; the anchor measured 1.05x")
        self.assertGreater(sensitive, routine)

    def test_the_tier_still_moves_where_the_hours_are_reported(self):
        """It costs almost nothing extra and it is still a real difference in kind: a
        sensitive story is read line by line, so more of the same hours land in review."""
        routine = self.price(size="M", review_tier="routine")
        sensitive = self.price(size="M", review_tier="sensitive")
        self.assertGreater(sensitive["component_shares"]["review"],
                           routine["component_shares"]["review"])
        self.assertLess(sensitive["component_shares"]["build"],
                        routine["component_shares"]["build"])

    def test_component_shares_always_sum_to_one(self):
        """They decide where hours are reported, never how many there are. If they stopped
        summing to 1 the phase table would silently become a second, disagreeing total."""
        for tier in ("routine", "sensitive", "critical"):
            for clarity in ("high", "medium", "low"):
                for novelty in ("standard", "novel"):
                    p = self.price(review_tier=tier, clarity=clarity, novelty=novelty)
                    self.assertAlmostEqual(sum(p["component_shares"].values()), 1.0, places=2)

    def test_a_payments_story_costs_more_than_crud_because_of_the_provider(self):
        """The 2.x version of this test asserted the tier did it. The measurement says the
        rail does: 3.2 / 3.3 / 3.4 / 3.5 carry +0.75 points over their surface count."""
        crud = self.price(size="M", review_tier="routine")
        payments = self.price(size="M", review_tier="sensitive", manual_effort=["money_rail"])
        self.assertGreater(est.pert(payments["total"])[0],
                           1.2 * est.pert(crud["total"])[0])
        self.assertGreater(payments["manual_effort_hours"], 0.5)

    def test_the_premium_is_additive_so_it_does_not_scale_with_the_band(self):
        """A payment provider is the same console work behind a small story as a large one.
        Making it a multiplier would say the opposite."""
        small = self.price(size="S", manual_effort=["money_rail"])
        large = self.price(size="L", manual_effort=["money_rail"])
        self.assertAlmostEqual(small["manual_effort_hours"], large["manual_effort_hours"], places=4)

    def test_premiums_stack_when_a_story_carries_more_than_one(self):
        one = self.price(manual_effort=["money_rail"])["manual_effort_hours"]
        two = self.price(manual_effort=["money_rail", "external_idp"])["manual_effort_hours"]
        self.assertGreater(two, one)

    def test_an_unpriced_premium_is_recorded_and_costs_nothing(self):
        """`provisioning` is deliberately unpriced: no anchor ever paid for real environments.
        It has to leave a trace rather than silently costing zero."""
        p = self.price(manual_effort=["provisioning"])
        self.assertEqual(p["manual_effort_hours"], 0.0)
        self.assertEqual([e["key"] for e in p["manual_effort_detail"]], ["provisioning"])
        self.assertIsNone(p["manual_effort_detail"][0]["hours"])

    def test_an_unknown_premium_is_refused_rather_than_ignored(self):
        with self.assertRaises(ValueError):
            self.price(manual_effort=["cryptocurrency"])

    def test_the_premium_is_read_off_the_classification_not_the_inventory(self):
        """It is a judgement about what the work costs, so it lives with the other five axes in
        classification.json — the inventory records what the source said and nothing about
        effort. It is lifted out of the tag block because it is a list of work classes rather
        than a tag with a value and a why."""
        inv = inventory([feature("F1", tags=None)])
        del inv["features"][0]["tags"]
        classification = {"features": {"F1": {
            "size_band": tag("M"), "compressibility": tag("high"), "review_tier": tag("sensitive"),
            "clarity": tag("high"), "novelty": tag("standard"),
            "manual_effort": ["money_rail"]}}}
        joined, missing, orphans = est.load_scope(inv, classification)
        self.assertEqual((missing, orphans), ([], []))
        self.assertEqual(joined["features"][0]["manual_effort"], ["money_rail"])
        self.assertNotIn("manual_effort", joined["features"][0]["tags"])
        priced = est.build_estimate(joined, model(), options())
        self.assertGreater(priced["features"][0]["manual_effort_hours"], 0)

    def test_the_premium_survives_a_round_trip_through_a_priced_estimate(self):
        """est-calibrate backtests history and est-agent-estimator re-prices scope, and both
        go through inventory_from(). A premium that did not come back would make an estimate
        fail to reproduce its own headline — which is exactly what the parity gate refuses."""
        inv = inventory([feature("F1", manual_effort=["money_rail"])])
        e = hours(inv)
        again = est.inventory_from(e)
        self.assertEqual(again["features"][0]["manual_effort"], ["money_rail"])
        self.assertAlmostEqual(est.build_estimate(again, model(), options())["total_hours"]["likely"],
                               e["total_hours"]["likely"], places=6)

    def test_compressibility_changes_the_reported_equivalent_and_nothing_else(self):
        """3.0 stopped dividing by it. Nobody measured a manual baseline on any of the three
        projects, so the division was arithmetic over a construct — it now runs the other way
        and is consumed by nothing."""
        fast = self.price(compressibility="high")
        slow = self.price(compressibility="low")
        self.assertEqual(est.pert(fast["total"])[0], est.pert(slow["total"])[0])
        self.assertGreater(est.pert(fast["manual_equivalent"])[0],
                           est.pert(slow["manual_equivalent"])[0])

    def test_low_clarity_raises_both_spec_and_rework(self):
        clear = self.price(clarity="high")
        vague = self.price(clarity="low")
        self.assertGreater(est.pert(vague["components"]["spec"])[0],
                           est.pert(clear["components"]["spec"])[0])
        self.assertGreater(est.pert(vague["components"]["rework"])[0],
                           est.pert(clear["components"]["rework"])[0])

    def test_novelty_drives_rework_rather_than_build(self):
        standard = self.price(novelty="standard")
        novel = self.price(novelty="novel")
        self.assertGreater(novel["component_shares"]["rework"],
                           standard["component_shares"]["rework"])
        self.assertLess(novel["component_shares"]["build"],
                        standard["component_shares"]["build"])
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
        self.assertEqual(e["planning_volume"]["epics"], 2)         # 10 stories / 7 per epic
        # 10 inventory stories x the 1.7 split factor. Planning is the one component priced
        # per artefact written, so a story that gets split into two costs two story files and
        # two reviews. 2.x keyed this off the size band — claiming big stories split and small
        # ones do not; all three anchors say splitting is a property of the project.
        self.assertAlmostEqual(e["planning_volume"]["stories"], 17.0)
        self.assertEqual(e["planning_volume"]["stories_in_inventory"], 10)

    def test_the_split_factor_touches_planning_and_nothing_else(self):
        """Splitting is decomposition, not scope growth: the scope is unchanged and so is the
        build. Applying it anywhere but planning would bill the same work twice."""
        m = model()
        inv = inventory([feature(f"F{i}") for i in range(1, 11)])
        m["planning"]["split_factor"] = {"lo": 1.0, "likely": 1.0, "hi": 1.0}
        flat = est.build_estimate(inv, m, options())
        m["planning"]["split_factor"] = {"lo": 2.0, "likely": 2.0, "hi": 2.0}
        split = est.build_estimate(inv, m, options())
        self.assertEqual(flat["by_phase"]["build"]["hours"], split["by_phase"]["build"]["hours"])
        self.assertGreater(split["by_phase"]["planning"]["hours"],
                           flat["by_phase"]["planning"]["hours"])

    def test_planning_scales_sublinearly_with_scope(self):
        small = hours(inventory([feature(f"F{i}") for i in range(1, 6)]))
        large = hours(inventory([feature(f"F{i}") for i in range(1, 26)]))
        ratio = (large["project_components"]["planning_review"]["hours"]
                 / small["project_components"]["planning_review"]["hours"])
        self.assertLess(ratio, 5.0)      # five times the features, less than five times the planning

    def test_a_sprint_pays_no_document_planning(self):
        e = hours(inventory(granularity="sprint"), )
        self.assertEqual(e["planning_volume"]["documents"], [])


class ClaritySpread(unittest.TestCase):
    """The spread is the signal: how well-specified the work is has to show up as width.

    Before band_multiplier it ran backwards. Holding size at M on a real 365-story inventory,
    hi/lo was 6.32 at high clarity and 5.52 at low — the vague story presenting as the more
    certain one — because spec and rework are scalar multiples of an interval and therefore
    proportionally tight, so low clarity added more of them and pulled the ratio down.
    """

    def band(self, clarity, size="M", compressibility="medium"):
        e = hours(inventory([feature("F1", clarity=clarity, size=size,
                                     compressibility=compressibility)]))
        return e["features"][0]["range"]

    def test_a_vaguer_story_gets_a_wider_band(self):
        ratios = {c: self.band(c)["high"] / self.band(c)["low"]
                  for c in ("high", "medium", "low")}
        self.assertLess(ratios["high"], ratios["medium"], ratios)
        self.assertLess(ratios["medium"], ratios["low"], ratios)

    def test_it_holds_at_every_size_and_compressibility(self):
        for size in ("XS", "S", "M", "L", "XL"):
            for comp in ("high", "medium", "low"):
                r = {c: self.band(c, size, comp) for c in ("high", "low")}
                self.assertLess(r["high"]["high"] / r["high"]["low"],
                                r["low"]["high"] / r["low"]["low"], f"{size}/{comp}")

    def test_the_likely_vertex_does_not_move(self):
        """Widening says the answer is less certain, not that the work is bigger. The PERT
        mean does rise — hours are floored at zero, so the right tail extends further than
        the left contracts — but the middle of the triangle is where the judgement put it."""
        m = model()
        priced = est.price_feature(feature("F1", clarity="low"), m, m["team_profiles"]["balanced"])
        unwidened = est.add(*priced["components"].values())
        self.assertAlmostEqual(priced["total"][1], unwidened[1], places=6)
        self.assertLess(priced["total"][0], unwidened[0])
        self.assertGreater(priced["total"][2], unwidened[2])

    def test_widening_never_produces_a_negative_or_zero_lower_bound(self):
        """A linear version of this drove a small vague story's lower bound to 0.0 h and its
        ratio to 57x. Hours are floored at zero, so the widening is geometric."""
        for size in ("XS", "S", "M", "L", "XL"):
            for comp in ("high", "medium", "low"):
                r = self.band("low", size, comp)
                self.assertGreater(r["low"], 0.0, f"{size}/{comp}")
                self.assertLess(r["high"] / r["low"], 25, f"{size}/{comp} is not a usable range")

    def test_high_clarity_is_left_exactly_as_it_was(self):
        """band_multiplier 1.0 has to be a no-op, or every previously-defensible estimate
        moves for no reason anyone can point at."""
        m = model()
        priced = est.price_feature(feature("F1", clarity="high"), m,
                                   m["team_profiles"]["balanced"])
        self.assertEqual(priced["total"], est.add(*priced["components"].values()))

    def test_widen_is_scale_free(self):
        """The same clarity has to mean the same spread on a 2-hour story and a 200-hour one."""
        small, big = (1.0, 2.0, 5.0), (100.0, 200.0, 500.0)
        a, b = est.widen(small, 1.35), est.widen(big, 1.35)
        self.assertAlmostEqual(a[2] / a[0], b[2] / b[0], places=6)


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
        self.assertAlmostEqual(sum(r["hours"] for r in e["by_role"].values()),
                               e["total_hours"]["likely"], delta=0.5)

    def test_every_role_carries_an_interval_not_a_point(self):
        """The role table is the estimate's headline now, and a headline with no range is the
        false precision the whole band mechanism exists to prevent."""
        e = hours(inventory([feature(f"F{i}") for i in range(1, 4)]))
        for role, row in e["by_role"].items():
            self.assertLessEqual(row["low"], row["likely"], role)
            self.assertLessEqual(row["likely"], row["high"], role)
            self.assertLess(row["low"], row["high"], f"{role} has no width at all")

    def test_each_role_total_is_its_story_work_plus_its_project_work(self):
        """The arithmetic that used to be missing: summing the story rows gave architect 0
        against 170 h in the table, with 27% of the project outside every row on the page."""
        e = hours(inventory([feature(f"F{i}") for i in range(1, 4)]))
        for role, row in e["by_role"].items():
            self.assertAlmostEqual(row["on_stories"] + row["project_level"], row["hours"],
                                   delta=0.2, msg=role)

    def test_the_roles_with_no_story_work_say_so_rather_than_reading_zero(self):
        e = hours(inventory([feature(f"F{i}") for i in range(1, 4)]))
        architect = e["by_role"]["architect"]
        self.assertEqual(architect["on_stories"], 0.0)
        self.assertGreater(architect["project_level"], 0.0)

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

    def test_no_surface_combination_leaves_a_component_with_nobody_on_it(self):
        """Every role in build, spec, review and rework is now conditional, which means a
        surface set nobody thought about can empty a component and raise mid-estimate. All
        31 combinations are cheap to check, so there is no reason to find out in production."""
        import itertools
        m = model()
        surfaces = ["backend", "frontend", "design", "infra", "data"]
        for size in range(1, len(surfaces) + 1):
            for combo in itertools.combinations(surfaces, size):
                for component in ("build", "spec", "review", "rework"):
                    roles = est.component_roles(m, component, set(combo))
                    self.assertTrue(roles, f"{component} empty for {combo}")
                    self.assertAlmostEqual(sum(roles.values()), 1.0, places=6)

    def test_an_infra_only_story_is_devops_work_end_to_end(self):
        """Nobody reviews a CI pipeline by being a developer. While `dev` was unconditional it
        survived renormalisation on every infra story and billed the pipeline 91% developer."""
        m = model()
        priced = est.price_feature(feature("F1", surfaces=["infra"]), m,
                                   m["team_profiles"]["balanced"])
        roles = est.feature_roles(priced, m)
        self.assertNotIn("dev", roles)
        self.assertIn("devops", roles)

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
        self.assertAlmostEqual(sum(est.pert(v)[0] for v in est.feature_roles(wide, m).values()),
                               sum(est.pert(v)[0] for v in est.feature_roles(narrow, m).values()),
                               delta=0.01)

    def test_surfaces_are_read_from_the_story_and_only_from_there(self):
        """One placement. It used to be read out of the tag block first and off the story
        second, so the field the schema actually defines was the one that lost — and when the
        tags moved to classification.json, surfaces stayed behind, because which kinds of work
        a story touches is an observation about the scope rather than a judgement about cost."""
        m = model()
        priced = est.price_feature(feature("F1", surfaces=["backend"]), m,
                                   m["team_profiles"]["balanced"])
        self.assertEqual(sorted(est.feature_roles(priced, m)), ["ba", "dev"])

        stray = feature("F2", surfaces=None)
        stray["tags"]["surfaces"] = {"value": ["backend"], "why": "x", "status": "inferred"}
        priced = est.price_feature(stray, m, m["team_profiles"]["balanced"])
        self.assertIsNone(priced["surfaces"], "a surfaces tag is not a surfaces field")

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
            for role, row in f["by_role"].items():
                per_story[role] = per_story.get(role, 0.0) + row["hours"]
        project = {name: sum(
            v["hours"] * share for name2, v in e["project_components"].items()
            for r, share in est.component_roles(model(), name2, None).items() if r == name)
            for name in set(e["by_role"])}
        for role, row in e["by_role"].items():
            self.assertAlmostEqual(per_story.get(role, 0.0) + project.get(role, 0.0),
                                   row["hours"], delta=0.5, msg=role)


class TestDependenciesAndDuration(unittest.TestCase):
    def test_standing_work_is_not_the_critical_path(self):
        """Nothing waits on the CI pipeline. Once the bands came down to story scale the
        largest setup item outweighed every product story and became a one-node 'chain'."""
        inv = inventory([feature("F1", "Integration", size="L"),
                         feature("F2", "List view", size="M",
                                 depends_on=[{"feature_id": "F1", "inferred": False, "evidence": "x"}])])
        chain = hours(inv)["dependencies"]["chain"]
        self.assertEqual(chain, ["F1", "F2"])
        self.assertFalse([c for c in chain if c.startswith("SW-")])

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
        # Against the model file, not a literal: the guarantee is that the snapshot is the
        # model that priced this estimate, and a hard-coded coefficient makes this test fail
        # every time anyone calibrates — which trains people to edit it without reading it.
        self.assertEqual(e["cost_model_snapshot"], model())

    def test_compression_compares_like_with_like(self):
        """Story work on both sides. 2.x put a whole-story numerator over a build-only
        denominator, which inflated the reported multiple by roughly the reciprocal of the
        build share — on this fixture, from 17x to 32x.

        Standing work is deliberately excluded: setup and pipeline work barely compresses,
        and mixing it in makes this assertion about the delivery mix rather than about the
        comparison the assertion names."""
        e = hours(inventory([feature(f"F{i}", compressibility="high", review_tier="routine")
                             for i in range(1, 6)]), no_standing_work=True)
        me = e["manual_equivalent"]
        self.assertGreater(me["manual_hours"], me["story_hours"])
        self.assertAlmostEqual(me["story_hours"],
                               sum(f["hours"] for f in e["features"]), delta=0.5)
        # The compression class is `high`, so the multiple must land on it rather than on
        # some ratio of two differently-scoped numerators.
        self.assertAlmostEqual(me["story_compression"],
                               model()["compressibility"]["high"]["likely"], delta=2.0)

    def test_standing_work_drags_the_compression_down_rather_than_being_hidden(self):
        """Setup, pipelines and environments do not compress, and an estimate that leaves
        them out reports a project compression it cannot deliver."""
        args = dict(inventory([feature(f"F{i}", compressibility="high", review_tier="routine")
                               for i in range(1, 6)]))
        with_standing = hours(dict(args))["manual_equivalent"]["story_compression"]
        without = hours(dict(args), no_standing_work=True)["manual_equivalent"]["story_compression"]
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

    def test_compression_is_not_presented_as_project_compression(self):
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
        self.assertGreater(me["story_compression"], 3.0)
        self.assertGreater(e["total_hours"]["likely"], 1.5 * me["story_hours"])
        self.assertIn("story work only", me["basis"])

    def test_an_unknown_tag_value_fails_loudly(self):
        f = feature("F1")
        f["tags"]["size_band"]["value"] = "XXL"
        with self.assertRaises(KeyError):
            hours(inventory([f]))


class CalibrationClaim(unittest.TestCase):
    """`calibrated` gates a claim made to a client, so it is structural, not a prose match."""

    def test_a_model_with_no_history_is_not_calibrated(self):
        cost_model = model()
        cost_model.pop("calibration_history", None)
        self.assertFalse(est.is_calibrated(cost_model))

    def test_the_shipped_model_declares_the_anchor_it_is_fitted_to(self):
        """It is calibrated now, against one project. Both halves have to be true in the
        file: the marker, so no rendered estimate calls itself uncalibrated while carrying
        fitted coefficients, and the sample size, so nobody reads n=1 as a trend."""
        cost_model = model()
        self.assertTrue(est.is_calibrated(cost_model))
        history = cost_model["calibration_history"]
        rebuild = next(h for h in history if h["kind"] == "rebuild")
        # Three projects at project level, one at story level, and the status has to carry
        # BOTH — the size bands rest on EPP alone and nobody should read n=3 as covering them.
        self.assertEqual(rebuild["samples"], 3)
        self.assertEqual(len(rebuild["projects"]), 3)
        self.assertEqual(sum(1 for p in rebuild["projects"] if p["per_story_record"]), 1)
        self.assertIn("n=3", cost_model["calibration_status"])
        self.assertIn("n=1", cost_model["calibration_status"])

    def test_rewording_the_prose_status_cannot_flip_the_claim(self):
        """Both directions, because a prose match would be wrong in both."""
        calibrated = model()
        calibrated["calibration_status"] = "Not yet calibrated against any delivered project."
        self.assertTrue(est.is_calibrated(calibrated))

        bare = model()
        bare.pop("calibration_history", None)
        bare["calibration_status"] = "Fully calibrated against a decade of delivery."
        self.assertFalse(est.is_calibrated(bare))

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
