#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Tests for render-report.py.

Static by design: skill #2's report recomputes in the browser and that duplicated logic
drifted twice, so nothing here recalculates anything. These check that the report says
what the analysis found, including when the finding is "nothing".
"""

import importlib.util
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

_spec = importlib.util.spec_from_file_location(
    "render", Path(__file__).resolve().parent.parent / "render-report.py")
rr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rr)


def analysis(**over):
    base = {
        "analysis_mode": "calibration", "samples": 5,
        "accuracy": {"samples": 5, "band_hit_rate": 0.6, "band_hit_target": 0.68,
                     "median_error_pct": 12.0, "error_spread_pct": 6.0,
                     "direction": "under-estimating", "residual_spread": 1.1,
                     "residual_spread_debiased": 1.4,
                     "entries": [{"id": "E1", "project": "Alpha", "low": 300, "likely": 400,
                                  "high": 500, "actual": 450, "inside_band": True,
                                  "error_pct": 12.5}]},
        "phase_deltas": {"qa": {"samples": 4, "median_ratio": 1.4, "spread": 0.1,
                                "outliers_excluded": 1, "sufficient": True}},
        "regression": {"ready": False, "reason": "too similar in composition"},
        "proposals": [], "skipped": [], "readiness": {},
    }
    base.update(over)
    return base


class TestVerdict(unittest.TestCase):
    def test_low_coverage_is_called_out_as_over_precise(self):
        text = rr.verdict_line(analysis()["accuracy"] | {"band_hit_rate": 0.3})
        self.assertIn("too narrow", text)
        self.assertIn("more precision than the model has", text)

    def test_high_coverage_is_called_out_as_uninformative(self):
        self.assertIn("wider than they need", rr.verdict_line(analysis()["accuracy"] | {"band_hit_rate": 1.0}))

    def test_on_target_coverage_is_stated_plainly(self):
        self.assertIn("about right", rr.verdict_line(analysis()["accuracy"] | {"band_hit_rate": 0.7}))


class TestMarkdown(unittest.TestCase):
    def test_delivered_projects_show_range_actual_and_whether_it_landed(self):
        md = rr.markdown(analysis())
        self.assertIn("300–500", md)
        self.assertIn("Alpha", md)

    def test_no_proposals_is_reported_as_a_result_not_an_absence(self):
        md = rr.markdown(analysis())
        self.assertIn("Either the model is behaving", md)

    def test_a_weak_signal_is_labelled(self):
        md = rr.markdown(analysis(proposals=[{
            "id": "P1", "coefficient": "qa", "current": 1.0, "proposed": 1.2, "samples": 3,
            "evidence": "qa ran hot", "needs": "phase-level actuals", "weak_signal": True}]))
        self.assertIn("weak signal", md)

    def test_shrinkage_is_explained_where_it_applies(self):
        md = rr.markdown(analysis(proposals=[{
            "id": "P1", "coefficient": "size_bands.*", "current": 1.0, "proposed": 1.12,
            "point_estimate": 1.3, "shrinkage_weight": 0.45, "samples": 5,
            "evidence": "under by 30%", "needs": "project totals only"}]))
        self.assertIn("the data alone points at 1.3", md)
        self.assertIn("45%", md)

    def test_skipped_entries_explain_why_they_were_left_out(self):
        md = rr.markdown(analysis(skipped=[{"id": "E9", "reason": "scope_delivered is unknown"}]))
        self.assertIn("Not comparable", md)
        self.assertIn("rather than averaged in", md)

    def test_backtest_verdicts_are_shown_beside_their_proposal(self):
        md = rr.markdown(
            analysis(proposals=[{"id": "P1", "coefficient": "qa", "current": 1.0, "proposed": 1.2,
                                 "samples": 5, "evidence": "e", "needs": "phase-level actuals"}]),
            {"backtests": [{"proposal": "P1", "verdict": "improves past estimates",
                            "detail": "improved 4 of 5"}]})
        self.assertIn("improves past estimates", md)

    def test_readiness_mode_lists_what_to_capture(self):
        md = rr.markdown({"analysis_mode": "readiness", "message": "Nothing comparable yet.",
                          "proposals": [],
                          "readiness": {"ledger_entries": 3, "with_actuals": 0, "usable": 0,
                                        "blocked": [], "granularity_mix": {},
                                        "unlocks": [{"capture": "A single total", "unlocks": "band width",
                                                     "why": "no attribution needed", "have": 0, "need": 4}],
                                        "advice": "Capture delivery_hours on every closed project."}})
        self.assertIn("What capturing actuals would unlock", md)
        self.assertIn("A single total", md)


class TestBrief(unittest.TestCase):
    """The stable distillate skill #3 speaks from, rather than parsing prose or internals."""

    def test_a_calibration_brief_carries_the_headline_figures(self):
        b = rr.brief(analysis())
        self.assertTrue(b["calibrated"])
        self.assertEqual(b["band_hit_rate"], 0.6)
        self.assertEqual(b["direction"], "under-estimating")
        self.assertIn("60%", b["verdict"])
        self.assertNotIn("**", b["verdict"])   # markdown emphasis stripped for a JSON consumer

    def test_pending_proposals_are_listed_without_the_internals(self):
        b = rr.brief(analysis(proposals=[{
            "id": "P1", "coefficient": "qa", "current": 1.0, "proposed": 1.2, "samples": 5,
            "evidence": "long evidence string", "needs": "phase-level actuals",
            "weak_signal": False}]))
        self.assertEqual(b["pending_proposals"][0]["id"], "P1")
        self.assertNotIn("evidence", b["pending_proposals"][0])

    def test_a_readiness_brief_says_it_is_not_calibrated_and_what_is_awaited(self):
        b = rr.brief({"analysis_mode": "readiness", "message": "Nothing yet.", "proposals": [],
                      "readiness": {"ledger_entries": 4, "with_actuals": 0, "usable": 0,
                                    "blocked": [], "granularity_mix": {}, "unlocks": [],
                                    "chase": [{"id": "E1", "project": "Alpha", "status": "won"}],
                                    "advice": "Capture delivery_hours."}})
        self.assertFalse(b["calibrated"])
        self.assertEqual(b["state"], "readiness")
        self.assertEqual(b["awaiting_actuals"][0]["project"], "Alpha")

    def test_the_brief_is_far_smaller_than_the_analysis(self):
        import json as _json
        a = analysis()
        self.assertLess(len(_json.dumps(rr.brief(a))), len(_json.dumps(a)))


class TestChaseSection(unittest.TestCase):
    def test_readiness_leads_with_the_chase_list(self):
        md = rr.markdown({"analysis_mode": "readiness", "message": "Nothing yet.", "proposals": [],
                          "readiness": {"ledger_entries": 2, "with_actuals": 0, "usable": 0,
                                        "blocked": [], "granularity_mix": {}, "unlocks": [],
                                        "chase": [{"id": "E1", "project": "Alpha", "status": "won",
                                                   "estimated": 400, "generated": "2026-01-01"}],
                                        "advice": "Capture delivery_hours."}})
        self.assertIn("Projects to chase", md)
        self.assertIn("Alpha", md)
        self.assertLess(md.index("Projects to chase"), md.index("What capturing actuals"))


class TestHtml(unittest.TestCase):
    def test_tables_and_headings_survive_the_conversion(self):
        html = rr.to_html(rr.markdown(analysis()), "Accuracy")
        self.assertIn("<table>", html)
        self.assertIn("<h1>", html)

    def test_content_is_escaped(self):
        html = rr.to_html("# <script>alert(1)</script>", "T")
        self.assertNotIn("<script>alert", html)

    def test_the_page_embeds_no_model_and_recomputes_nothing(self):
        html = rr.to_html(rr.markdown(analysis()), "Accuracy")
        self.assertNotIn("cost_model_snapshot", html)
        self.assertNotIn("function compute", html)


if __name__ == "__main__":
    unittest.main()
