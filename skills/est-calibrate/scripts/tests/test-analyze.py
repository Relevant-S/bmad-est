#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Tests for analyze.py — the loading rules and robust statistics.

Behavioural recovery against known ground truth lives in evals/ground-truth.py; these
cover the pieces that decide what counts as evidence in the first place.
"""

import importlib.util
import sys
import tempfile
import json
import shutil
import subprocess
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fixtures import actuals, entry, feature, model  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "analyze", Path(__file__).resolve().parent.parent / "analyze.py")
an = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(an)


class TestRobustStatistics(unittest.TestCase):
    def test_median_ignores_an_extreme_value(self):
        self.assertEqual(an.median([10, 11, 12, 13, 900]), 12)

    def test_mad_is_scaled_to_compare_with_a_standard_deviation(self):
        self.assertAlmostEqual(an.mad([10, 12, 14]), 1.4826 * 2, places=3)

    def test_mad_of_identical_values_is_zero(self):
        self.assertEqual(an.mad([5, 5, 5, 5]), 0.0)

    def test_outliers_are_found_by_distance_from_the_median(self):
        self.assertEqual(an.outliers([10, 10.5, 11, 10.2, 90]), {4})

    def test_no_outliers_in_a_tight_cluster(self):
        self.assertEqual(an.outliers([10, 10.1, 10.2, 9.9]), set())


class TestWhatCountsAsEvidence(unittest.TestCase):
    """A project that cannot be compared like-for-like is not evidence, at any sample size."""

    def test_an_entry_with_no_actuals_is_not_usable(self):
        ok, reason = an.usable(entry(actual=None))
        self.assertFalse(ok)
        self.assertIn("no actuals", reason)

    def test_unknown_scope_is_refused(self):
        e = entry()
        e["ledger"]["actuals"]["scope_delivered"] = "unknown"
        ok, reason = an.usable(e)
        self.assertFalse(ok)
        self.assertIn("like is being compared with like", reason)

    def test_reduced_scope_without_a_feature_list_is_refused(self):
        e = entry()
        e["ledger"]["actuals"].update({"scope_delivered": "reduced", "scope_note": "cut two"})
        ok, reason = an.usable(e)
        self.assertFalse(ok)
        self.assertIn("features_delivered", reason)

    def test_reduced_scope_with_a_feature_list_is_usable(self):
        e = entry()
        e["ledger"]["actuals"].update({"scope_delivered": "reduced", "scope_note": "cut two",
                                       "features_delivered": ["F1"]})
        self.assertTrue(an.usable(e)[0])

    def test_excluded_hours_without_a_reason_are_refused(self):
        e = entry()
        e["ledger"]["actuals"]["excluded_hours"] = 40
        ok, reason = an.usable(e)
        self.assertFalse(ok)
        self.assertIn("interrogate", reason)

    def test_excluded_hours_with_a_reason_are_fine(self):
        e = entry()
        e["ledger"]["actuals"].update({"excluded_hours": 40, "excluded_why": "client delay"})
        self.assertTrue(an.usable(e)[0])


class TestAccuracy(unittest.TestCase):
    def test_inside_band_is_judged_against_the_quoted_range(self):
        acc = an.accuracy([entry(low=300, likely=400, high=500, actual=450)], model())
        self.assertTrue(acc["entries"][0]["inside_band"])

    def test_outside_band_is_reported(self):
        acc = an.accuracy([entry(low=300, likely=400, high=500, actual=620)], model())
        self.assertFalse(acc["entries"][0]["inside_band"])
        self.assertEqual(acc["band_hit_rate"], 0.0)

    def test_direction_names_under_estimation(self):
        entries = [entry(f"E{i}", likely=400, actual=520) for i in range(4)]
        self.assertEqual(an.accuracy(entries, model())["direction"], "under-estimating")

    def test_direction_names_over_estimation(self):
        entries = [entry(f"E{i}", likely=400, actual=300) for i in range(4)]
        self.assertEqual(an.accuracy(entries, model())["direction"], "over-estimating")

    def test_no_bias_is_reported_as_none(self):
        entries = [entry(f"E{i}", likely=400, actual=a) for i, a in enumerate([395, 405, 400, 402])]
        self.assertEqual(an.accuracy(entries, model())["direction"], "no systematic bias")

    def test_the_measured_bias_is_reported_separately_from_the_spread(self):
        """Estimates all wrong by the same amount are consistent, not uncertain: the error is
        bias, which the sizing scale fixes, and the band must not be judged on it."""
        entries = [entry(f"E{i}", likely=400, sd=50, actual=500) for i in range(5)]
        acc = an.accuracy(entries, model())
        self.assertAlmostEqual(acc["measured_bias"], 0.25, places=2)
        self.assertAlmostEqual(an.spread_after_correction(acc, 1.25), 0.0, places=2)
        self.assertEqual(acc["entries"][0]["sd"], 50.0)   # carried, not re-derived


class TestDegenerateSpread(unittest.TestCase):
    """MAD returns exactly zero whenever more than half a sample shares a value — routine
    below ten projects. Unguarded it clears any tolerance and drives the band to no width."""

    def test_mad_is_zero_when_most_values_agree(self):
        self.assertEqual(an.mad([1.0, 1.0, 1.0, 1.4, 0.6]), 0.0)

    def test_a_degenerate_spread_proposes_no_band_change(self):
        acc = {"samples": 6, "band_hit_rate": 0.5, "band_hit_target": 0.68,
               "median_error_pct": 0.0, "entries": []}
        self.assertIsNone(an.propose_model_risk(acc, model(), 3, 0.0))

    def test_a_real_spread_still_proposes(self):
        acc = {"samples": 8, "band_hit_rate": 0.25, "band_hit_target": 0.68,
               "median_error_pct": 0.0,
               "entries": [{"sd": 50.0, "likely": 400.0, "actual": 500.0} for _ in range(8)]}
        self.assertIsNotNone(an.propose_model_risk(acc, model(), 3, 2.2))


class TestEntriesWithoutAnSd(unittest.TestCase):
    """An entry whose sd was never recorded is absent evidence, not evidence of zero."""

    def test_such_entries_are_dropped_rather_than_counted_as_zero(self):
        acc = {"samples": 6, "band_hit_rate": 0.2, "band_hit_target": 0.68,
               "median_error_pct": 0.0,
               "entries": [{"sd": 50.0, "likely": 400.0, "actual": 500.0} for _ in range(5)]
                          + [{"sd": 0.0, "likely": 400.0, "actual": 500.0}]}
        proposal = an.propose_model_risk(acc, model(), 3, 2.0)
        self.assertIsNotNone(proposal)
        self.assertGreater(proposal["proposed"], 0.15)   # not dragged toward zero


class TestBandIsSizedForTheCorrectionActuallyApplied(unittest.TestCase):
    def rows(self, bias=0.25, n=6):
        return {"entries": [{"sd": 40.0, "likely": 400.0, "actual": 400.0 * (1 + bias)}
                            for _ in range(n)]}

    def test_removing_the_applied_correction_leaves_no_spread(self):
        acc = self.rows(bias=0.25)
        self.assertAlmostEqual(an.spread_after_correction(acc, 1.25), 0.0, places=2)

    def test_removing_only_part_of_the_bias_leaves_the_rest_for_the_band(self):
        """Sizing the band for a full correction that is only shrunk-applied leaves it narrow."""
        acc = self.rows(bias=0.25)
        partial = an.spread_after_correction(acc, 1.12)
        self.assertEqual(partial, 0.0)   # identical rows: spread is zero either way
        residuals = [(r["actual"] - r["likely"] * 1.12) / r["sd"] for r in acc["entries"]]
        self.assertGreater(abs(residuals[0]), 1.0)   # but the offset remains, and is real

    def test_no_correction_means_nothing_is_removed(self):
        acc = {"entries": [{"sd": 40.0, "likely": 400.0, "actual": 400.0 + d}
                           for d in (-80, -40, 0, 40, 80)]}
        with_none = an.spread_after_correction(acc, 1.0)
        self.assertGreater(with_none, 0.5)


class TestBandTarget(unittest.TestCase):
    """The target coverage is a function of the model's own z, never an assumed 68%."""

    def test_the_default_z_gives_the_familiar_target(self):
        self.assertAlmostEqual(an.band_target(model()), 0.683, places=2)

    def test_widening_z_raises_the_target(self):
        m = model()
        m["uncertainty"]["z"] = 1.28
        self.assertAlmostEqual(an.band_target(m), 0.80, places=2)

    def test_a_correctly_calibrated_wide_band_is_not_judged_too_wide(self):
        """The bug this replaced: a company taking the cost model's own advice to widen to an
        80% band had its correct ranges called far too wide, and narrowing proposed."""
        m = model()
        m["uncertainty"]["z"] = 1.28
        entries = [entry(f"E{i}", low=300, likely=400, high=500, actual=a)
                   for i, a in enumerate([320, 350, 400, 450, 480])]
        acc = an.accuracy(entries, m)
        self.assertAlmostEqual(acc["band_hit_target"], 0.80, places=2)
        self.assertEqual(acc["band_hit_rate"], 1.0)
        self.assertIn("1.28", acc["band_hit_target_why"])


class TestShrinkage(unittest.TestCase):
    def test_the_shrinkage_constant_is_overridable(self):
        strong, weight = an.shrink(1.0, 2.0, 6, k=1.0)
        self.assertGreater(weight, 0.8)
        self.assertGreater(strong, 1.8)

    def test_a_small_sample_moves_only_part_of_the_way(self):
        value, weight = an.shrink(1.0, 1.4, 6)
        self.assertAlmostEqual(weight, 0.5, places=2)
        self.assertAlmostEqual(value, 1.2, places=2)

    def test_a_large_sample_moves_most_of_the_way(self):
        value, weight = an.shrink(1.0, 1.4, 54)
        self.assertGreater(weight, 0.85)
        self.assertGreater(value, 1.33)

    def test_shrinkage_never_overshoots_the_target(self):
        for n in (1, 5, 20, 100, 1000):
            value, _ = an.shrink(1.0, 1.5, n)
            self.assertLessEqual(value, 1.5)


class TestRegressionGate(unittest.TestCase):
    def make(self, shares):
        entries = []
        for i, share in enumerate(shares):
            n = 10
            sensitive = round(n * share)
            feats = [feature(f"F{j}", "sensitive" if j <= sensitive else "routine", hours=50.0)
                     for j in range(1, n + 1)]
            entries.append(entry(f"E{i}", features=feats))
        return entries

    def test_too_few_projects_is_refused_by_count(self):
        result = an.regression_readiness(self.make([0.1, 0.9]), model(), 8)
        self.assertFalse(result["ready"])
        self.assertIn("at least 8", result["reason"])

    def test_identical_shapes_are_refused_however_many_there_are(self):
        result = an.regression_readiness(self.make([0.4] * 12), model(), 8)
        self.assertFalse(result["ready"])
        self.assertIn("similar in composition", result["reason"])

    def test_the_threshold_is_the_expected_range_of_noise_not_one_deviation_of_it(self):
        """The range of pure noise grows with sample count; a fixed threshold lets more
        projects of the same shape look varied."""
        self.assertGreater(an.expected_noise_range(12), an.expected_noise_range(6))
        self.assertGreater(an.expected_noise_range(6), an.expected_noise_range(3))

    def test_the_refusal_reports_what_noise_alone_would_have_produced(self):
        result = an.regression_readiness(self.make([0.4] * 12), model(), 8)
        self.assertIn("noise_only_range", result)
        self.assertIn("required_range", result)
        self.assertIn("sampling noise alone", result["reason"])

    def test_genuinely_varied_shapes_are_accepted(self):
        result = an.regression_readiness(self.make([0.0, 0.2, 0.5, 0.8, 1.0] * 2), model(), 8)
        self.assertTrue(result["ready"])

    def test_the_reason_reports_the_span_that_was_measured(self):
        result = an.regression_readiness(self.make([0.4] * 12), model(), 8)
        self.assertIn("mix_range", result)


class TestReadiness(unittest.TestCase):
    def test_readiness_lists_what_each_level_of_data_unlocks(self):
        r = an.readiness([entry(actual=None)])
        captures = [u["capture"] for u in r["unlocks"]]
        self.assertTrue(any("total" in c for c in captures))
        self.assertTrue(any("per feature" in c for c in captures))

    def test_blocked_entries_are_named_with_their_reason(self):
        e = entry()
        e["ledger"]["actuals"]["scope_delivered"] = "unknown"
        r = an.readiness([e])
        self.assertEqual(len(r["blocked"]), 1)
        self.assertIn("scope", r["blocked"][0]["reason"])

    def test_the_chase_list_names_the_projects_worth_asking_about(self):
        """A have/need table reads the same every month; the specific asks do not."""
        sent = entry("EST-1", actual=None)
        sent["ledger"]["status"] = "won"
        draft = entry("EST-2", actual=None)
        draft["ledger"]["status"] = "draft"
        chase = an.chase_list([sent, draft])
        self.assertEqual([c["id"] for c in chase], ["EST-1"])
        self.assertIn("ingest-actuals.py", chase[0]["command"])

    def test_projects_that_already_have_actuals_are_not_chased(self):
        done = entry("EST-3", actual=500.0)
        done["ledger"]["status"] = "delivered"
        self.assertEqual(an.chase_list([done]), [])

    def test_the_chase_list_is_oldest_first(self):
        a = entry("EST-A", actual=None, generated="2026-03-01T00:00:00Z")
        b = entry("EST-B", actual=None, generated="2026-01-01T00:00:00Z")
        for e in (a, b):
            e["ledger"]["status"] = "sent"
        self.assertEqual([c["id"] for c in an.chase_list([a, b])], ["EST-B", "EST-A"])

    def test_an_empty_ledger_still_advises(self):
        self.assertIn("delivery_hours", an.readiness([])["advice"])


BMAD_SCRIPTS = Path(__file__).resolve().parents[4] / "_bmad" / "scripts"
# resolve_config.py imports config_utils as a sibling, so a fixture that copies only the one
# file gets ModuleNotFoundError and an empty stdout — which is indistinguishable from "no
# setting configured" unless the test looks.
RESOLVER_FILES = ("resolve_config.py", "config_utils.py")


class ConfiguredThreshold(unittest.TestCase):
    """est_min_calibration_samples was collected by est-setup and read by nothing.

    These tests copy in BMad's REAL resolver and write real TOML, because the first version
    of them stubbed it with a flat dict — which was the author's assumption about the output
    shape, not the resolver's actual behaviour. It returns a nested config unless asked for a
    single key, so the flat lookup matched nothing and every project silently got the default.
    The test passed throughout, because it was asserting the assumption back to itself. A
    stub can only ever confirm what its author already believed about the other side.
    """

    def project(self, tmp, value):
        root = Path(tmp)
        scripts = root / "_bmad" / "scripts"
        scripts.mkdir(parents=True)
        for name in RESOLVER_FILES:
            shutil.copyfile(BMAD_SCRIPTS / name, scripts / name)
        (root / "_bmad" / "config.toml").write_text(
            '[core]\nproject_name = "test"\n', encoding="utf-8")
        (root / "_bmad" / "custom").mkdir()
        table = "" if value is None else (
            f"\n[modules.est]\nest_min_calibration_samples = "
            f"{json.dumps(value) if not isinstance(value, str) else json.dumps(value)}\n")
        (root / "_bmad" / "custom" / "config.toml").write_text(
            f'# est settings{table}', encoding="utf-8")
        return root

    def test_the_resolver_really_does_answer_flat_only_when_asked_for_one_key(self):
        """The assumption the stub encoded, checked against the thing itself."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self.project(tmp, 5)
            key = "modules.est.est_min_calibration_samples"
            full = json.loads(subprocess.run(
                [sys.executable, str(root / "_bmad/scripts/resolve_config.py"), "-p", str(root)],
                capture_output=True, text=True).stdout)
            one = json.loads(subprocess.run(
                [sys.executable, str(root / "_bmad/scripts/resolve_config.py"), "-p", str(root),
                 "-k", key], capture_output=True, text=True).stdout)
            self.assertIsNone(full.get(key), "a full dump is nested; a dotted key matches nothing")
            self.assertEqual(full["modules"]["est"]["est_min_calibration_samples"], 5)
            self.assertEqual(one[key], 5)

    def test_the_configured_value_is_the_one_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(an.configured_min_samples(self.project(tmp, 5)), 5)

    def test_a_project_without_the_setting_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(an.configured_min_samples(self.project(tmp, None)), 3)

    def test_a_nonsense_value_falls_back_rather_than_disabling_the_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(an.configured_min_samples(self.project(tmp, "lots")), 3)

    def test_zero_cannot_switch_the_evidence_bar_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(an.configured_min_samples(self.project(tmp, 0)), 1)

    def test_no_resolver_at_all_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(an.configured_min_samples(tmp), 3)

    def test_a_resolver_that_cannot_run_falls_back_rather_than_crashing(self):
        """It exits non-zero with an empty stdout, which must not read as a configured value."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self.project(tmp, 5)
            (root / "_bmad" / "scripts" / "config_utils.py").unlink()
            self.assertEqual(an.configured_min_samples(root), 3)


if __name__ == "__main__":
    unittest.main()
