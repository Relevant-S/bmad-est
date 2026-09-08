#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Tests for render-estimate.py.

The load-bearing property: the interactive HTML must reproduce the engine's arithmetic,
including the project overheads that shrink when scope is cut. A negotiation tool that
shows a saving the client will not actually get is worse than no tool.
"""

import csv
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fixtures import feature, inventory, model, options  # noqa: E402

SCRIPTS = Path(__file__).resolve().parent.parent


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


est = load("estimate", "estimate.py")
render = load("render_estimate", "render-estimate.py")


def estimate_for(features=None, **opt):
    inv = inventory(features)
    opt.setdefault("granularity", inv.get("granularity", "project"))
    return est.build_estimate(inv, model(), options(**opt))


class TestMarkdown(unittest.TestCase):
    def test_headline_range_is_present(self):
        md = render.markdown(estimate_for())
        self.assertIn("hours  ·  range", md)

    def test_every_feature_row_carries_its_source(self):
        md = render.markdown(estimate_for([feature("F1", "Login")]))
        self.assertIn("S1 §1", md)

    def test_an_uncalibrated_model_is_declared(self):
        """The shipped model is now fitted to one project, so the banner has to be provoked
        rather than assumed — and the thing worth protecting is that a model without a
        calibration history never renders without saying so."""
        e = estimate_for()
        e["cost_model_snapshot"] = {k: v for k, v in e["cost_model_snapshot"].items()
                                    if k != "calibration_history"}
        self.assertIn("Uncalibrated model", render.markdown(e))

    def test_a_calibrated_model_does_not_carry_the_banner(self):
        self.assertNotIn("Uncalibrated model", render.markdown(estimate_for()))

    def test_planning_review_is_called_out_as_the_anchor(self):
        self.assertIn("defended hardest", render.markdown(estimate_for()))

    def test_risk_quadrant_is_surfaced_when_present(self):
        md = render.markdown(estimate_for([
            feature("F1", "Legacy payments bridge", compressibility="low", review_tier="critical")]))
        self.assertIn("Where the risk is", md)
        self.assertIn("Legacy payments bridge", md)

    def test_no_risk_section_when_nothing_is_in_that_quadrant(self):
        # Standing work is off here because environment and release work is genuinely
        # low-compressibility and sensitive, so it always populates the quadrant — which is
        # true, and would make this test about the catalogue rather than about the section.
        md = render.markdown(estimate_for([
            feature("F1", "Marketing page", compressibility="high", review_tier="routine")],
            no_standing_work=True))
        self.assertNotIn("Where the risk is", md)

    def test_the_feature_table_shows_who_does_the_work(self):
        """A row reading "9h" invites a haggle; a row reading "dev 6.1, ba 1.5" invites a
        conversation about who is on it — and the dash against ux is the visible half of
        the fix, since a reader has to be able to see that a role was excluded rather than
        rounded away."""
        md = render.markdown(estimate_for([
            feature("F1", "Nightly reconciliation job", surfaces=["backend"]),
            feature("F2", "Onboarding screens", surfaces=["frontend", "design"])]))
        header = next(l for l in md.split("\n") if l.startswith("| ID | Feature"))
        columns = [c.strip() for c in header.split("|")]
        self.assertIn("dev", columns)
        self.assertIn("ux", columns)
        backend = next(l for l in md.split("\n") if l.startswith("| F1 |"))
        design = next(l for l in md.split("\n") if l.startswith("| F2 |"))
        ux = columns.index("ux")
        self.assertEqual(backend.split("|")[ux].strip(), "—")
        self.assertNotEqual(design.split("|")[ux].strip(), "—")

    def test_standing_work_is_not_labelled_as_something_the_client_can_decline(self):
        md = render.markdown(estimate_for([feature("F1", "Marketing page")]))
        row = next(l for l in md.split("\n") if "SW-ci_pipeline" in l)
        self.assertIn("standing work", row)
        self.assertNotIn("outside agreed scope", row)

    def test_build_compression_is_internal_only(self):
        e = estimate_for()
        self.assertNotIn("Build compression", render.markdown(e, show_manual_baseline=False))
        self.assertIn("Build compression", render.markdown(e, show_manual_baseline=True))

    def test_scope_table_shows_both_apportioned_and_standalone(self):
        md = render.markdown(estimate_for([
            feature("F1", "Agreed"),
            feature("F2", "Extra", scope_status="outside_agreed_scope")]))
        self.assertIn("Share of this project", md)
        self.assertIn("Cost on its own", md)
        self.assertIn("will not save the apportioned figure", md)

    def test_traceability_findings_are_shown_not_hidden(self):
        md = render.markdown(estimate_for([feature("F1", citations=[])]))
        self.assertIn("no citation", md)


class TestCsv(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def rows(self, e):
        target = self.dir / "estimate.csv"
        render.write_csv(e, target)
        with target.open(encoding="utf-8-sig") as fh:
            return list(csv.DictReader(fh))

    def test_feature_rows_carry_the_cost_model_axes_and_components(self):
        row = self.rows(estimate_for([feature("F1", "Login", review_tier="sensitive")]))[0]
        self.assertEqual(row["review_tier"], "sensitive")
        self.assertTrue(float(row["review"]) > 0)
        self.assertTrue(float(row["build"]) > 0)

    def test_project_components_appear_as_their_own_lines(self):
        names = [r["name"] for r in self.rows(estimate_for())]
        self.assertTrue(any("[project] planning review" in n for n in names))
        self.assertTrue(any("[project] qa" in n for n in names))

    def test_totals_are_included_for_a_sales_sheet(self):
        names = [r["name"] for r in self.rows(estimate_for())]
        for expected in ("[total] likely", "[total] low", "[total] high"):
            self.assertIn(expected, names)


class TestBrief(unittest.TestCase):
    """What a conversational agent needs to defend a number, without the ledger payload."""

    def test_every_tag_keeps_the_reason_it_was_given(self):
        f = feature("F1", "Refunds", review_tier="sensitive")
        f["tags"]["review_tier"]["why"] = "handles refunds against a customer card"
        b = render.brief(estimate_for([f]))
        self.assertEqual(b["features"][0]["why"]["review_tier"]["why"],
                         "handles refunds against a customer card")

    def test_the_verbatim_quote_survives_to_the_brief(self):
        b = render.brief(estimate_for([feature("F1", "Login")]))
        self.assertIn("Login is required", b["features"][0]["source"]["quote"])

    def test_the_dominant_cost_driver_is_named_per_feature(self):
        b = render.brief(estimate_for([feature("F1", "Payments", review_tier="critical")]))
        self.assertEqual(b["features"][0]["dominant_component"], "review")

    def test_the_brief_can_answer_who_does_this_work(self):
        """Nadia's rule is that no number is asserted that cannot be decomposed on demand.
        A per-story figure with no role split decomposes to hours and stops exactly where
        the question usually goes next."""
        b = render.brief(estimate_for([feature("F1", "Reconciliation", surfaces=["backend"])]))
        row = next(f for f in b["features"] if f["id"] == "F1")
        self.assertEqual(sorted(row["by_role"]), ["ba", "dev"])

    def test_the_brief_drops_the_cost_model_snapshot(self):
        b = render.brief(estimate_for())
        self.assertNotIn("cost_model_snapshot", b)
        self.assertIn("calibrated", b)

    def test_the_brief_is_far_smaller_than_the_ledger_payload(self):
        e = estimate_for([feature(f"F{i}") for i in range(1, 6)])
        self.assertLess(len(json.dumps(render.brief(e))), len(json.dumps(e)) / 3)


class TestInteractiveHtml(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def build(self, features=None):
        e = estimate_for(features)
        target = self.dir / "estimate.html"
        render.write_html(e, target, {"stack": "standard_saas", "qa_platform": "web",
                                      "engagement": "standard"})
        return e, target.read_text(encoding="utf-8")

    def embedded(self, html):
        start = html.index('<script id="estimate-data" type="application/json">') + \
            len('<script id="estimate-data" type="application/json">')
        end = html.index("</script>", start)
        return json.loads(html[start:end].replace("<\\/", "</"))

    def test_the_estimate_survives_embedding_intact(self):
        e, html = self.build()
        self.assertAlmostEqual(self.embedded(html)["total_hours"]["likely"],
                               e["total_hours"]["likely"])

    def test_the_cost_model_travels_with_the_page_so_it_can_recompute(self):
        _, html = self.build()
        data = self.embedded(html)
        self.assertIn("planning", data["cost_model_snapshot"])
        self.assertIn("overhead_rate", data["cost_model_snapshot"])
        self.assertIn("_render_options", data)

    def test_a_closing_script_tag_in_the_data_cannot_break_the_page(self):
        """A feature named with a closing tag would otherwise end the script element early."""
        _, html = self.build([feature("F1", "Report </script> injection")])
        self.assertNotIn("</script> injection", html)
        self.assertEqual(self.embedded(html)["features"][0]["name"], "Report </script> injection")

    def test_the_page_carries_its_own_recompute_self_check(self):
        _, html = self.build()
        self.assertIn("Recompute mismatch", html)

    def test_the_self_check_covers_the_whole_interval_not_just_the_mean(self):
        """A mean-only check is blind to band divergence, which is the module's headline claim
        and the thing that actually drifted."""
        _, html = self.build()
        self.assertIn("['low', 'likely', 'high']", html)

    def test_citations_reach_the_page_for_every_feature(self):
        _, html = self.build([feature("F1", "Login")])
        self.assertEqual(self.embedded(html)["features"][0]["citations"][0]["location"], "§1")


if __name__ == "__main__":
    unittest.main()
