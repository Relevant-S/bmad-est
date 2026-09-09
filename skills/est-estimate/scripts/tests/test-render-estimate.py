#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["openpyxl>=3.1"]
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

try:
    import openpyxl  # noqa: F401
    _HAS_XLSX = True
except ImportError:
    _HAS_XLSX = False


def estimate_for(features=None, **opt):
    inv = inventory(features)
    opt.setdefault("granularity", inv.get("granularity", "project"))
    return est.build_estimate(inv, model(), options(**opt))


class TestMarkdown(unittest.TestCase):
    def test_the_headline_is_the_role_table_and_there_is_no_grand_total(self):
        """Adding up the story rows gave 1,752 h against a 2,414 h headline, because planning,
        QA and overhead touch no story. Summing across roles answers no question anyone asks,
        so the number that could not be reconciled is simply not reported."""
        est = estimate_for()
        md = render.markdown(est)
        self.assertIn("## Hours by role", md)
        self.assertNotIn("hours  ·  range", md)
        for key in ("low", "likely", "high"):
            self.assertNotIn(f"{est['total_hours'][key]:,.0f} hours", md)

    def test_every_role_is_a_range_with_its_two_sources_shown(self):
        md = render.markdown(estimate_for())
        self.assertIn("| Role | Low | Likely | High | On stories | Project-level |", md)
        self.assertIn("architect", md)

    def test_every_story_row_carries_a_range_not_a_point(self):
        md = render.markdown(estimate_for([feature("F1", "Login")]))
        self.assertIn("| Low | Likely | High |", md)
        row = [ln for ln in md.splitlines() if ln.startswith("| F1 |")][0]
        cells = [c.strip() for c in row.split("|")]
        lo, likely, hi = (float(cells[7]), float(cells[8]), float(cells[9]))
        self.assertLess(lo, likely)
        self.assertLess(likely, hi)

    def test_every_role_cell_on_a_story_is_a_range_too(self):
        md = render.markdown(estimate_for([feature("F1", "Login")]))
        row = [ln for ln in md.splitlines() if ln.startswith("| F1 |")][0]
        priced = [c.strip() for c in row.split("|") if "–" in c and c.strip()[0].isdigit()]
        self.assertTrue(priced, "no role cell rendered as a range")
        for cell in priced:
            lo, likely, hi = (float(x) for x in cell.split("–"))
            self.assertLessEqual(lo, likely)
            self.assertLessEqual(likely, hi)

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

    def test_no_grand_total_row_is_written(self):
        names = [r["name"] for r in self.rows(estimate_for())]
        for gone in ("[total] likely", "[total] low", "[total] high"):
            self.assertNotIn(gone, names)

    def test_every_row_carries_its_range_and_every_role_carries_one(self):
        est = estimate_for([feature("F1", "Login")])
        rows = {r["id"]: r for r in self.rows(est)}
        row = rows["F1"]
        self.assertLess(float(row["hours_low"]), float(row["hours_high"]))
        roles = [r for r in est["by_role"] if f"{r}_low" in row]
        self.assertTrue(roles, "no per-role columns in the sheet")
        for role in roles:
            self.assertLessEqual(float(row[f"{role}_low"]), float(row[f"{role}_high"]))


class ExtendsTheInventory(unittest.TestCase):
    """The estimate sheets are the inventory sheets with more columns on them.

    The old estimate.csv re-derived its own 23 columns and lost description, epic name,
    surfaces, task ids, open questions, locations and quotes — and every task. The columns
    here come from est-scope-extract's own row builders, so a column added there arrives
    without anyone remembering to add it.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.inv = inventory([feature("F1", "Login")])
        self.inv["epics"] = [{"id": "E1", "name": "Access", "origin": "source"}]
        self.inv["features"][0]["epic_id"] = "E1"
        self.inv["features"][0]["tasks"] = [
            {"id": "F1-T1", "name": "Sign in",
             "citations": [{"source_id": "S1", "location": "§1", "quote": "Users must log in."}]}]
        self.est = est.build_estimate(self.inv, model(), options(granularity="project"))

    def tearDown(self):
        self.tmp.cleanup()

    def inventory_columns(self):
        inv_mod = render.inventory_renderer()
        return list(inv_mod.STORY_COLUMNS), list(inv_mod.TASK_COLUMNS)

    def test_no_inventory_story_column_is_dropped(self):
        story_columns, _ = self.inventory_columns()
        target = self.dir / "estimate.csv"
        render.write_csv(self.est, target, self.inv)
        with target.open(encoding="utf-8-sig") as fh:
            got = next(csv.reader(fh))
        for column in story_columns:
            self.assertIn(column, got, f"est-scope-extract wrote {column} and the estimate lost it")

    def test_no_inventory_task_column_is_dropped(self):
        _, task_columns = self.inventory_columns()
        target = self.dir / "estimate.tasks.csv"
        render.write_tasks_csv(self.est, target, self.inv)
        with target.open(encoding="utf-8-sig") as fh:
            got = next(csv.reader(fh))
        for column in task_columns:
            self.assertIn(column, got)

    def test_the_inventory_content_arrives_not_just_the_headers(self):
        target = self.dir / "estimate.csv"
        render.write_csv(self.est, target, self.inv)
        with target.open(encoding="utf-8-sig") as fh:
            row = next(iter(csv.DictReader(fh)))
        self.assertEqual(row["epic_name"], "Access")
        self.assertEqual(row["description"],
                         self.inv["features"][0]["description"],
                         "the description est-scope-extract wrote did not survive the join")
        self.assertEqual(row["task_ids"], "F1-T1")

    def test_a_task_id_a_story_names_resolves_to_a_row(self):
        render.write_csv(self.est, self.dir / "estimate.csv", self.inv)
        render.write_tasks_csv(self.est, self.dir / "estimate.tasks.csv", self.inv)
        with (self.dir / "estimate.csv").open(encoding="utf-8-sig") as fh:
            story = next(iter(csv.DictReader(fh)))
        with (self.dir / "estimate.tasks.csv").open(encoding="utf-8-sig") as fh:
            tasks = {r["task_id"] for r in csv.DictReader(fh)}
        for tid in story["task_ids"].split("; "):
            self.assertIn(tid, tasks)

    def test_a_story_priced_but_absent_from_the_inventory_still_appears(self):
        """Standing work is priced and is in no inventory. Dropping it from the sheet would
        price less on the page than the estimate does."""
        target = self.dir / "estimate.csv"
        render.write_csv(self.est, target, self.inv)
        with target.open(encoding="utf-8-sig") as fh:
            ids = {r["id"] for r in csv.DictReader(fh)}
        priced = {f["id"] for f in self.est["features"]}
        self.assertTrue(priced <= ids, sorted(priced - ids))

    def test_without_the_inventory_it_still_renders_and_says_what_is_missing(self):
        est_copy = json.loads(json.dumps(self.est))
        est_copy["inventory"] = "nowhere/feature-inventory.json"
        inv, problem = render.load_inventory(est_copy)
        self.assertIsNone(inv)
        self.assertIn("inventory not found", problem)
        target = self.dir / "estimate.csv"
        render.write_csv(est_copy, target, None)
        with target.open(encoding="utf-8-sig") as fh:
            row = next(iter(csv.DictReader(fh)))
        self.assertEqual(row["id"], "F1")
        self.assertTrue(float(row["hours_high"]) > 0)


@unittest.skipUnless(_HAS_XLSX, "openpyxl not importable")
class Workbook(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.inv = inventory([feature("F1", "Login")])
        self.inv["features"][0]["tasks"] = [
            {"id": "F1-T1", "name": "Sign in",
             "citations": [{"source_id": "S1", "location": "§1", "quote": "Users must log in."}]}]
        self.est = est.build_estimate(self.inv, model(), options(granularity="project"))
        self.target = self.dir / "estimate.xlsx"
        self.assertTrue(render.write_xlsx(self.est, self.target, self.inv))

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_same_two_tabs_the_inventory_workbook_has(self):
        from openpyxl import load_workbook
        self.assertEqual(load_workbook(self.target).sheetnames, ["Stories", "Tasks"])

    def test_the_priced_columns_are_on_the_stories_tab_as_ranges(self):
        from openpyxl import load_workbook
        ws = load_workbook(self.target)["Stories"]
        header = [c.value for c in ws[1]]
        for column in ("hours_low", "hours_likely", "hours_high"):
            self.assertIn(column, header)
        for role in self.est["by_role"]:
            if f"{role}_low" in header:
                break
        else:
            self.fail("no per-role columns on the workbook")

    def test_a_story_still_clicks_through_to_its_tasks(self):
        from openpyxl import load_workbook
        wb = load_workbook(self.target)
        ws, ts = wb["Stories"], wb["Tasks"]
        col = [c.value for c in ws[1]].index("task_ids") + 1
        cell = ws.cell(row=2, column=col)
        self.assertIsNotNone(cell.hyperlink)
        at = int(cell.hyperlink.location.split("!A")[1])
        self.assertEqual(ts.cell(row=at, column=1).value, "F1-T1")

    def test_without_openpyxl_the_render_still_succeeds_and_says_the_workbook_was_skipped(self):
        saved = sys.modules.get("openpyxl")
        sys.modules["openpyxl"] = None
        try:
            self.assertFalse(render.write_xlsx(self.est, self.dir / "x.xlsx", self.inv))
        finally:
            if saved is None:
                sys.modules.pop("openpyxl", None)
            else:
                sys.modules["openpyxl"] = saved


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
