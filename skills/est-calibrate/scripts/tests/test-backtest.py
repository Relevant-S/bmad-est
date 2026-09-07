#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Tests for backtest.py — the trust mechanism.

The property that matters most is the asymmetry in the verdict: a change to band width
leaves every central figure untouched, so an error-only judgement calls a harmful change
neutral. Behavioural recovery lives in evals/ground-truth.py.
"""

import importlib.util
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fixtures import entry, feature, model  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "backtest", Path(__file__).resolve().parent.parent / "backtest.py")
bt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bt)


class TestInventoryReconstruction(unittest.TestCase):
    """History is re-priced through est-estimate's engine, so the scope must round-trip."""

    def test_tags_are_rebuilt_in_the_shape_pricing_expects(self):
        inv = bt.inventory_from(entry(features=[feature("F1", tier="sensitive")]))
        tags = inv["features"][0]["tags"]
        self.assertEqual(tags["review_tier"]["value"], "sensitive")
        self.assertIn("why", tags["review_tier"])
        self.assertIn("status", tags["review_tier"])

    def test_citations_survive_so_the_repriced_scope_stays_traceable(self):
        inv = bt.inventory_from(entry(features=[feature("F1")]))
        self.assertEqual(inv["features"][0]["citations"][0]["location"], "§1")

    def test_dependencies_are_rebuilt(self):
        f = feature("F2")
        f["depends_on"] = ["F1"]
        inv = bt.inventory_from(entry(features=[feature("F1"), f]))
        self.assertEqual(inv["features"][1]["depends_on"][0]["feature_id"], "F1")

    def test_granularity_and_project_carry_over(self):
        inv = bt.inventory_from(entry())
        self.assertEqual(inv["project"], "Alpha")
        self.assertEqual(inv["granularity"], "project")


class TestApplyProposal(unittest.TestCase):
    def test_a_factor_proposal_scales_the_family(self):
        m = model()
        candidate = bt.apply_proposal(m, {"coefficient": "size_bands.*", "kind": "factor",
                                          "proposed": 1.5})
        self.assertAlmostEqual(candidate["size_bands"]["M"]["likely"],
                               m["size_bands"]["M"]["likely"] * 1.5, places=3)

    def test_an_absolute_proposal_sets_the_value(self):
        candidate = bt.apply_proposal(model(), {"coefficient": "uncertainty.model_risk",
                                                "kind": "absolute", "proposed": 0.4})
        self.assertEqual(candidate["uncertainty"]["model_risk"], 0.4)

    def test_the_model_passed_in_is_never_mutated(self):
        m = model()
        before = m["size_bands"]["M"]["likely"]
        bt.apply_proposal(m, {"coefficient": "size_bands.*", "kind": "factor", "proposed": 2.0})
        self.assertEqual(m["size_bands"]["M"]["likely"], before)


class TestEngineDependency(unittest.TestCase):
    """The write path depends absolutely on est-estimate's engine now that the unbacktested
    override is gone, so its absence must be recoverable rather than a dead end."""

    def test_the_default_location_is_the_sibling_skill(self):
        self.assertTrue(str(bt.DEFAULT_ENGINE).endswith("est-estimate/scripts/estimate.py"))

    def test_a_missing_engine_refuses_with_the_path_it_looked_at(self):
        with self.assertRaises(SystemExit) as ctx:
            bt.engine("/nonexistent/estimate.py")
        message = str(ctx.exception)
        self.assertIn("/nonexistent/estimate.py", message)
        self.assertIn("--engine", message)
        self.assertIn("propose nothing", message)

    def test_an_explicit_path_is_honoured_for_a_non_sibling_install(self):
        module = bt.engine(str(bt.DEFAULT_ENGINE))
        self.assertTrue(hasattr(module, "build_estimate"))


class TestVerdictAsymmetry(unittest.TestCase):
    """A band that is too narrow promises precision the model lacks; too wide is merely dull."""

    def verdict(self, before_hit, after_hit, improved=0, worsened=0, samples=8):
        before = {"samples": samples, "median_abs_error_pct": 20.0, "band_hit_rate": before_hit,
                  "entries": [{"abs_error_pct": 20.0} for _ in range(samples)]}
        after = {"samples": samples, "median_abs_error_pct": 20.0, "band_hit_rate": after_hit,
                 "entries": [{"abs_error_pct": 20.0} for _ in range(samples)]}
        # Drive compare() through its own scoring shape without re-pricing anything.
        original = bt.score
        bt.score = lambda entries, m, e: before if m is SENTINEL_BEFORE else after
        try:
            result = bt.compare([], SENTINEL_BEFORE, {"id": "P1", "coefficient": "x"}, None)
        finally:
            bt.score = original
        return result

    def test_coverage_falling_below_target_is_harmful_even_with_no_error_change(self):
        global SENTINEL_BEFORE
        SENTINEL_BEFORE = object()
        bt.apply_proposal = lambda m, p: object()
        result = self.verdict(0.71, 0.14)
        self.assertEqual(result["verdict"], "makes past estimates worse")
        self.assertIn("promise precision", result["detail"])

    def test_overshooting_above_target_is_not_called_harmful(self):
        global SENTINEL_BEFORE
        SENTINEL_BEFORE = object()
        bt.apply_proposal = lambda m, p: object()
        result = self.verdict(0.71, 1.0)
        self.assertNotEqual(result["verdict"], "makes past estimates worse")
        self.assertIn("wider than it needs", result["detail"])

    def test_coverage_moving_toward_target_is_an_improvement(self):
        global SENTINEL_BEFORE
        SENTINEL_BEFORE = object()
        bt.apply_proposal = lambda m, p: object()
        result = self.verdict(0.30, 0.65)
        self.assertEqual(result["verdict"], "improves past estimates")


if __name__ == "__main__":
    unittest.main()
