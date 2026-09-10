#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""The backtest: does the model reproduce the projects it claims to be fitted to?

This did not exist before 3.0, and its absence is why the 2.x model could carry coefficients
fitted to "540 h actual" long after the same scope was recorded at 690 h without a single
test noticing. Everything else in the suite checks that the arithmetic is internally
consistent. This checks that it is *right about something*.

Three delivered projects, priced from their own delivered story lists:

    EPP epics 1-9                dev 300 / architect 110 / BA 100 / UX 100 / QA 40 / DevOps 40
    memorial-healthcare 1-9.7    dev 140 / architect  60 / BA  80 / UX  80
    easyterms 1-5 + 8            dev 160 / architect  80

The fixtures under `anchors/` are checked in so this does not depend on those three repos
being present; `_provenance` in each one records how it was built and how far it can be
trusted. EPP's bands are its own measured record. The other two have no per-story effort
record at all, so their bands are bridged by files-touched and their assertions are
correspondingly loose — and deliberately two-sided, because the overshoot on those two is a
KNOWN LIMITATION rather than a defect, and locking it down is how it stops being quietly
"fixed" by someone re-tuning a coefficient with no new evidence.

Standing work is excluded from every run here. All three projects deferred real
infrastructure — EPP's own retrospectives say "no AWS resource was provisioned" and SES was
"still in sandbox" — so pricing a catalogue none of them paid for would compare the model
against hours that were never spent.
"""

import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "estimate", ROOT / "est-estimate" / "scripts" / "estimate.py")
est = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(est)

MODEL_PATH = ROOT / "est-estimate" / "assets" / "cost-model.seed.json"
ANCHOR_DIR = Path(__file__).resolve().parent / "anchors"

ANCHORS = {
    "epp": {
        "weeks": 7, "epics_planned": 8, "team": 3,
        "actual": {"dev": 300, "architect": 110, "ba": 100, "ux": 100, "qa": 40, "devops": 40},
    },
    "memorial-healthcare": {
        "weeks": 3.5, "epics_planned": 9, "team": 3,
        "actual": {"dev": 140, "architect": 60, "ba": 80, "ux": 80, "qa": 0, "devops": 0},
    },
    "easyterms": {
        "weeks": 5, "epics_planned": 6, "team": 2,
        "actual": {"dev": 160, "architect": 80, "ba": 0, "ux": 0, "qa": 0, "devops": 0},
    },
}


def model():
    return json.loads(MODEL_PATH.read_text(encoding="utf-8"))


def inventory(name):
    return json.loads((ANCHOR_DIR / f"{name}.json").read_text(encoding="utf-8"))


def price(name, cost_model=None, standing=False):
    """Price an anchor's delivered story list.

    `split_factor` is forced to 1.0: it describes plan-to-delivery decomposition, and these
    inventories ARE the delivered list, so applying it would count every story file 1.7 times.
    """
    m = cost_model or model()
    m["planning"]["split_factor"] = {"lo": 1.0, "likely": 1.0, "hi": 1.0}
    a = ANCHORS[name]
    options = {
        "mode": "presale", "team": m["team_profiles"]["balanced"], "team_name": "balanced",
        "stack": "standard_saas", "qa_platform": "web", "engagement": "standard",
        "team_size": a["team"], "no_standing_work": not standing, "granularity": "project",
        "input_completeness": 0.85, "inventory_path": name, "generated": "",
        "inventory_warnings": [],
    }
    return est.build_estimate(inventory(name), m, options)


def roles(name, **kw):
    return {r: v["hours"] for r, v in price(name, **kw)["by_role"].items()}


class TheProjectItIsFittedTo(unittest.TestCase):
    """EPP is the only anchor with a per-story effort record, so it is the only one the bands
    could be fitted to — and the only one the model owes a close answer."""

    def test_the_total_lands_on_the_recorded_hours(self):
        got = roles("epp")
        # DevOps is out: EPP's 40 h went on pipelines and environments, which are standing_work
        # and appear in no story list. Its own line is asserted separately, below.
        predicted = sum(v for r, v in got.items() if r != "devops")
        actual = sum(v for r, v in ANCHORS["epp"]["actual"].items() if r != "devops")
        self.assertAlmostEqual(predicted / actual, 1.0, delta=0.25,
                               msg=f"{predicted:.0f} h against a recorded {actual} h")

    def test_every_staffed_role_lands_within_a_quarter(self):
        got = roles("epp")
        for role, actual in ANCHORS["epp"]["actual"].items():
            if role == "devops":
                continue
            with self.subTest(role=role):
                self.assertAlmostEqual(got.get(role, 0.0) / actual, 1.0, delta=0.25,
                                       msg=f"{role}: {got.get(role, 0.0):.1f} h against {actual} h")

    def test_devops_is_near_zero_because_its_work_is_not_in_the_story_list(self):
        """Not a miss — a correct answer to the question asked. The model is being shown a
        product backlog, and EPP's DevOps hours went on CI and environments."""
        self.assertLess(roles("epp").get("devops", 0.0), 10)

    def test_standing_work_adds_roughly_a_fifth_that_no_anchor_ever_paid(self):
        """The least-evidenced block in the model, pinned so its size stays visible. All three
        projects deferred real infrastructure, so this is the part of the estimate with no
        delivered hours behind it at all."""
        without = sum(roles("epp").values())
        with_it = sum(roles("epp", standing=True).values())
        self.assertGreater(with_it / without, 1.10)
        self.assertLess(with_it / without, 1.45)


class TheProjectsItIsNotFittedTo(unittest.TestCase):
    """memorial-healthcare and easyterms, where the model runs high — and why.

    Both assertions are two-sided on purpose. The overshoot is the granularity effect the
    module cannot remove: the same scope was written as 50 stories or 125 depending on who
    sliced it, and no unit available at presale distinguishes the cases better than about
    1.7x. Asserting only an upper bound would let the number be tuned away against no new
    evidence; asserting a lower bound too means anyone who genuinely fixes it has to say so
    here.
    """

    def test_memorial_healthcare_runs_high_and_by_how_much(self):
        predicted = sum(roles("memorial-healthcare").values())
        actual = sum(ANCHORS["memorial-healthcare"]["actual"].values())
        self.assertGreater(predicted / actual, 1.2)
        self.assertLess(predicted / actual, 1.8,
                        "the overshoot grew; check the bands before accepting it")

    def test_easyterms_runs_high_and_by_how_much(self):
        predicted = sum(roles("easyterms").values())
        actual = sum(ANCHORS["easyterms"]["actual"].values())
        self.assertGreater(predicted / actual, 2.2)
        self.assertLess(predicted / actual, 3.4)

    def test_the_model_says_out_loud_that_it_is_fitted_to_the_expensive_end(self):
        """A limitation nobody can read is a limitation nobody will price around."""
        anchor = model()["size_bands"]["_anchor"]
        self.assertIn("run HIGH", anchor["h_per_point_dev_cross_project"])
        self.assertIn("check_granularity", anchor["h_per_point_dev_cross_project"])


class TheArchitectFormula(unittest.TestCase):
    """setup + a capped weekly rate. Three projects, and it was stated independently of the
    totals rather than fitted to them — the best-evidenced coefficient in the file."""

    def hours_for(self, weeks):
        m = model()
        span = {"weeks_three_point": (weeks, weeks, weeks)}
        return est.pert(est.architect_cost(m, span))[0]

    def test_it_reproduces_all_three_projects(self):
        for name, recorded in (("epp", 110), ("memorial-healthcare", 60), ("easyterms", 80)):
            with self.subTest(project=name):
                got = self.hours_for(ANCHORS[name]["weeks"])
                self.assertAlmostEqual(got / recorded, 1.0, delta=0.25,
                                       msg=f"{name}: {got:.1f} h against a recorded {recorded} h")

    def test_setup_does_not_scale_with_the_backlog(self):
        """The 2.x failure this replaces: architect hours fell out of role weights on planning
        and overhead, both of which scale with story count, so a 371-story inventory bought
        three times the anchored setup."""
        small = price("epp")
        big = price("memorial-healthcare")            # 125 stories against 75
        self.assertGreater(len(big["features"]), len(small["features"]))
        per_week_small = small["project_components"]["architect"]["hours"] / small["duration"]["weeks"]
        per_week_big = big["project_components"]["architect"]["hours"] / big["duration"]["weeks"]
        self.assertLess(abs(per_week_small - per_week_big), 6.0)

    def test_the_weekly_rate_is_capped(self):
        """All three sat at 10 h/week, so a long project must not buy proportionally more."""
        m = model()
        self.assertLessEqual(m["architect"]["weekly_h"]["likely"], m["architect"]["weekly_cap"])
        long_run = self.hours_for(52)
        self.assertLessEqual(long_run, m["architect"]["setup_h"]["hi"] + 52 * m["architect"]["weekly_cap"])


class TheBandsReproduceTheirSource(unittest.TestCase):
    """EPP's per-story CSV is the whole evidence base for size_bands, and the file has to be
    able to point back at it."""

    def test_the_measured_dev_figures_are_the_scale_the_anchor_recorded(self):
        bands = model()["size_bands"]
        measured = {b: bands[b]["measured_dev_h"] for b in ("XS", "S", "M", "L", "XL")}
        points = {b: bands[b]["points"] for b in measured}
        self.assertEqual(list(points.values()), [1, 2, 3, 4, 5])
        rate = model()["size_bands"]["_anchor"]["h_per_point_dev"]
        for band, hours in measured.items():
            self.assertAlmostEqual(hours, points[band] * rate, delta=0.15, msg=band)

    def test_the_whole_anchor_reconciles_to_its_recorded_dev_hours(self):
        """237 points at 1.165 h/point is 276 h; EPP recorded 300 for epics 1-9, and its own
        CSV marks epics 8 and 9 as extrapolated. Both halves have to stay true."""
        bands = model()["size_bands"]
        inv = inventory("epp")["features"]
        points = sum(bands[f["tags"]["size_band"]["value"]]["points"] for f in inv)
        self.assertEqual(points, 237)
        dev = points * bands["_anchor"]["h_per_point_dev"]
        self.assertAlmostEqual(dev / 300, 1.0, delta=0.15)

    def test_the_distribution_is_the_one_the_anchor_actually_delivered(self):
        """2.x claimed XS 0%, S 11%, M 64%, L 25%, XL 0%. The record says otherwise, and the
        difference was being enforced on every classification."""
        got = model()["size_bands"]["_anchor"]["distribution"]
        self.assertEqual(got, {"XS": 0.027, "S": 0.173, "M": 0.453, "L": 0.307, "XL": 0.040})
        inv = inventory("epp")["features"]
        for band, share in got.items():
            actual = sum(1 for f in inv if f["tags"]["size_band"]["value"] == band) / len(inv)
            self.assertAlmostEqual(actual, share, delta=0.01, msg=band)

    def test_both_extremes_are_present_because_the_anchor_had_both(self):
        got = model()["size_bands"]["_anchor"]["distribution"]
        self.assertGreater(got["XS"], 0)
        self.assertGreater(got["XL"], 0)


class TheDoubleCountIsVisible(unittest.TestCase):
    """All three delivered projects opened with a foundation epic and priced that work as
    ordinary stories — memorial-healthcare 1-1 Initialize Frontend, 1-3 Configure Local
    Development Environment, 1-4 Set Up CI/CD Pipeline; EPP 1-1 Monorepo scaffold; easyterms
    1-2 service shell, 1-8 CI regression gate. The cost model then billed `standing_work` for
    the same thing on top.

    Nothing here re-fits a number. Making the overlap visible is what this change does; moving
    it would need evidence from a project that actually reached production, which is precisely
    what none of the three anchors is.
    """

    def check(self):
        import importlib.util
        path = (Path(__file__).resolve().parents[3]
                / "est-scope-extract" / "scripts" / "inventory-check.py")
        spec = importlib.util.spec_from_file_location("inventory_check", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def overlaps(self, name, applies=("repo_scaffold", "ci_pipeline", "environments")):
        check = self.check()
        inv = dict(inventory(name))
        inv["standing_scope"] = {"catalogue": "cost-model standing_work", "selected": [
            {"key": k, "applies": True, "why": "claimed, to see whether a story covers it"}
            for k in applies]}
        catalogue = check.load_standing_catalogue()[0]
        findings, warnings, report = check.check_standing_overlap(inv, catalogue)
        return findings, warnings, report

    def test_memorial_healthcare_names_the_stories_it_would_pay_for_twice(self):
        findings, warnings, report = self.overlaps("memorial-healthcare")
        self.assertEqual(findings, [], "this is advisory — it must never fail an inventory")
        hit = {o["key"] for o in report["overlaps"]}
        self.assertIn("ci_pipeline", hit)
        self.assertIn("environments", hit)
        self.assertTrue(any("pays for it twice" in w for w in warnings))

    def test_epp_names_its_monorepo_scaffold(self):
        report = self.overlaps("epp")[2]
        matched = [s for o in report["overlaps"] if o["key"] == "repo_scaffold"
                   for s in o["stories"]]
        self.assertTrue(any("onorepo scaffold" in s for s in matched), matched)

    def test_declining_the_overlapping_items_silences_it(self):
        """The fix, exercised: name the story in covered_by and the advisory goes quiet."""
        check = self.check()
        inv = dict(inventory("memorial-healthcare"))
        inv["standing_scope"] = {"catalogue": "cost-model standing_work", "selected": [
            {"key": k, "applies": False, "why": "delivered as a story in epic 1"}
            for k in check.load_standing_catalogue()[0]]}
        findings, warnings, _ = check.check_standing_overlap(
            inv, check.load_standing_catalogue()[0])
        self.assertEqual(findings, [])
        self.assertEqual(warnings, [])

    def test_the_pinned_size_of_standing_work_has_not_moved(self):
        """Guards the whole change: if selection logic altered pricing, this is where it shows."""
        without = sum(roles("epp").values())
        self.assertGreater(sum(roles("epp", standing=True).values()) / without, 1.10)


class TheDeliveryStructureIsRecorded(unittest.TestCase):
    """The fixtures are delivered projects, so their build order is the record rather than a
    judgement — which makes them the one place the sequencing check can be run against fact."""

    def test_every_anchor_carries_an_ordered_epic_list(self):
        for name in ANCHORS:
            epics = inventory(name).get("epics") or []
            self.assertTrue(epics, name)
            self.assertEqual([e["sequence"] for e in epics],
                             list(range(1, len(epics) + 1)), name)

    def test_the_delivered_order_validates_against_the_dependency_graph(self):
        import importlib.util
        path = (Path(__file__).resolve().parents[3]
                / "est-scope-extract" / "scripts" / "inventory-check.py")
        spec = importlib.util.spec_from_file_location("inventory_check", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for name in ANCHORS:
            self.assertEqual(mod.check_sequence(inventory(name))[0], [], name)

    def test_the_structure_costs_nothing(self):
        """Adding epics to the fixtures must not have moved a single hour, or the backtest
        above is measuring the change rather than the model."""
        self.assertAlmostEqual(sum(roles("epp").values()), 654, delta=25)


class TheSizingBiasIsGone(unittest.TestCase):
    """The mechanism, measured. Band assignment carried roughly eight times the weight the
    delivered record supports, and the review step then pushed on that over-weighted variable
    from both directions — priming the classifier with a distribution and then flagging it for
    deviating from the same one."""

    def price_all(self, features):
        m = model()
        m["planning"]["split_factor"] = {"lo": 1.0, "likely": 1.0, "hi": 1.0}
        inv = dict(inventory("epp"), features=features)
        options = {
            "mode": "presale", "team": m["team_profiles"]["balanced"], "team_name": "balanced",
            "stack": "standard_saas", "qa_platform": "web", "engagement": "standard",
            "team_size": 3, "no_standing_work": True, "granularity": "project",
            "input_completeness": 0.85, "inventory_path": "x", "generated": "",
            "inventory_warnings": [],
        }
        return est.build_estimate(inv, m, options)["total_hours"]["likely"]

    def test_shifting_a_tenth_of_the_inventory_up_a_band_barely_moves_the_number(self):
        """The 2.x arithmetic moved 17% on this shift. That sensitivity is what made the
        anchor-distribution nudge so consequential, and it is what 3.0 removed."""
        base = inventory("epp")["features"]
        shifted = json.loads(json.dumps(base))
        moved = 0
        for f in shifted:
            if f["tags"]["size_band"]["value"] == "M" and moved < len(base) * 0.12:
                f["tags"]["size_band"]["value"] = "L"
                moved += 1
        self.assertGreater(moved, 5)
        delta = self.price_all(shifted) / self.price_all(base) - 1
        self.assertLess(abs(delta), 0.06, f"a 12% M->L shift moved the estimate {delta:.1%}")

    def test_one_band_of_error_is_a_third_not_three_times(self):
        bands = model()["size_bands"]
        self.assertAlmostEqual(bands["L"]["likely"] / bands["M"]["likely"], 1.35, delta=0.15)
        self.assertAlmostEqual(bands["XL"]["likely"] / bands["XS"]["likely"], 4.8, delta=1.0)

    def test_the_premium_is_what_makes_a_provider_story_expensive(self):
        """What actually separates EPP's expensive stories from its cheap ones. Two of its
        three XL stories are the Stripe ones, and the residual analysis puts a money rail at
        +0.75 points over what its surface count predicts."""
        m = model()
        plain = est.price_feature(
            {"id": "A", "name": "a", "tags": {k: {"value": v} for k, v in
             (("size_band", "M"), ("compressibility", "high"), ("review_tier", "sensitive"),
              ("clarity", "high"), ("novelty", "standard"))}, "surfaces": ["backend"]},
            m, m["team_profiles"]["balanced"])
        rail = est.price_feature(
            {"id": "B", "name": "b", "manual_effort": ["money_rail"],
             "tags": {k: {"value": v} for k, v in
             (("size_band", "M"), ("compressibility", "high"), ("review_tier", "sensitive"),
              ("clarity", "high"), ("novelty", "standard"))}, "surfaces": ["backend"]},
            m, m["team_profiles"]["balanced"])
        ratio = est.pert(rail["total"])[0] / est.pert(plain["total"])[0]
        self.assertGreater(ratio, 1.15)
        self.assertLess(ratio, 1.45)


if __name__ == "__main__":
    unittest.main()
