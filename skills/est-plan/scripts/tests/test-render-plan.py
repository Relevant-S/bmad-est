#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["openpyxl>=3.1"]
# ///
"""Tests for render-plan.py — the markdown, and the Gantt tabs appended to the estimate's own
workbook.

The workbook round trip is the risk. est-plan opens a file another skill wrote and saves it
again, so the question that matters is not whether the Gantt is correct but whether the
Stories and Tasks tabs, and the hyperlinks between them, are still there afterwards. A plan
that quietly strips the estimate out of the estimate workbook would be discovered by a client.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fixtures as F  # noqa: E402

render = F.load("render_plan", F.PLAN / "render-plan.py")
render_estimate = F.load("render_estimate", F.EST / "scripts" / "render-estimate.py")

try:
    import openpyxl  # noqa: F401
    HAS_XLSX = True
except ImportError:
    HAS_XLSX = False


def a_plan(features=None):
    estimate = F.priced(features or F.wide(18, epics=3, size="L"))
    return estimate, F.plan_mod.build_plan(estimate, F.model())


class TheMarkdown(unittest.TestCase):
    def setUp(self):
        self.estimate, self.plan = a_plan()
        self.text = render.markdown(self.plan)

    def test_every_option_is_presented_with_its_own_hours_not_just_its_calendar(self):
        """A schedule without its cost is half an answer. The module's rule is that the reader
        compares plan-and-cost pairs, never calendars."""
        for option in self.plan["options"]:
            self.assertIn(f"{option['estimate']['total_hours']['likely']:.0f}", self.text)
        self.assertIn("| Role | Low | Likely | High |", self.text)

    def test_the_sub_scores_are_printed_not_just_the_total(self):
        self.assertIn("| Sub-score | /10 | What it rests on |", self.text)
        for name in ("Duration", "Cost", "Utilisation", "Coordination", "Drift", "Confidence"):
            self.assertIn(f"| {name} |", self.text)

    def test_every_headcount_decision_appears_with_its_reasoning(self):
        for decision in self.plan["staffing"]["decisions"]:
            needle = (decision["justification"] or decision["refusals"])[0].strip()
            self.assertIn(needle[:60], self.text)

    def test_each_option_names_its_risks_and_what_to_do_about_them(self):
        self.assertIn("**Risks**", self.text)
        for option in self.plan["options"]:
            for row in option["risks"]:
                self.assertIn(row["mitigation"][:50], self.text)

    def test_it_says_weeks_are_relative_and_carries_no_dates(self):
        import re
        self.assertIn("Weeks are relative", self.text)
        self.assertIsNone(re.search(r"\b\d{4}-\d{2}-\d{2}\b", self.text))

    def test_an_infeasible_option_is_marked_in_the_table_not_quietly_listed(self):
        plan = json.loads(json.dumps(self.plan))
        plan["options"][0]["feasibility"] = {"feasible": False, "checks": [],
                                             "failures": ["invented for the test"],
                                             "critical_path_weeks": 0.0}
        plan["recommended"] = None
        text = render.markdown(plan)
        self.assertIn("not deliverable", text)
        self.assertIn("No option is deliverable", text)


@unittest.skipUnless(HAS_XLSX, "openpyxl is not installed")
class TheWorkbookRoundTrip(unittest.TestCase):
    def setUp(self):
        self.estimate, self.plan = a_plan()
        self.dir = tempfile.TemporaryDirectory()
        self.book = Path(self.dir.name) / "estimate.xlsx"
        self.assertTrue(render_estimate.write_xlsx(self.estimate, self.book))
        self.addCleanup(self.dir.cleanup)

    def extend(self, per="archetype"):
        ok, result = render.extend_workbook(self.plan, self.book, per)
        self.assertTrue(ok, result)
        from openpyxl import load_workbook
        return load_workbook(self.book)

    def test_the_estimates_own_tabs_survive_being_extended(self):
        """The one thing that must not break. This opens a file est-estimate wrote."""
        from openpyxl import load_workbook
        before = load_workbook(self.book)
        rows, cols = before["Stories"].max_row, before["Stories"].max_column
        after = self.extend()
        self.assertEqual(after["Stories"].max_row, rows)
        self.assertEqual(after["Stories"].max_column, cols)
        self.assertIn("Tasks", after.sheetnames)
        self.assertEqual(after["Stories"].freeze_panes, before["Stories"].freeze_panes)

    def test_it_appends_rather_than_replacing(self):
        after = self.extend()
        self.assertEqual(after.sheetnames[:2], ["Stories", "Tasks"])
        self.assertIn("Options", after.sheetnames)
        self.assertTrue([n for n in after.sheetnames if n.startswith("Gantt")])

    def test_one_gantt_per_archetype_by_default_and_one_per_option_on_request(self):
        """Nine near-identical charts is not a more readable document than three, and
        readability is a requirement rather than a preference."""
        self.assertEqual(len([n for n in self.extend().sheetnames if n.startswith("Gantt")]),
                         len({o["archetype"] for o in self.plan["options"]}))
        every = self.extend("option")
        self.assertGreaterEqual(len([n for n in every.sheetnames if n.startswith("Gantt")]), 1)

    def test_rendering_twice_does_not_duplicate_the_tabs(self):
        self.extend()
        after = self.extend()
        self.assertEqual(len(after.sheetnames), len(set(after.sheetnames)))

    def test_every_story_row_on_a_gantt_links_back_to_the_stories_tab(self):
        after = self.extend()
        sheet = after[[n for n in after.sheetnames if n.startswith("Gantt")][0]]
        index = render.story_index(after)
        self.assertTrue(index)
        links = [c for row in sheet.iter_rows() for c in row if c.hyperlink]
        self.assertTrue(links, "no Gantt row linked to its work")
        for cell in links:
            self.assertTrue(cell.hyperlink.location.startswith("Stories!A"))
            target = int(cell.hyperlink.location.split("A")[1])
            self.assertIn(target, set(index.values()))

    def test_the_grid_has_one_column_per_week_and_freezes_the_labels(self):
        after = self.extend()
        name = [n for n in after.sheetnames if n.startswith("Gantt")][0]
        sheet, option = after[name], None
        for o in self.plan["options"]:
            if f"Gantt — {o['archetype'].title()}"[:31] == name:
                option = o
                break
        weeks = max(1, int(option["schedule"]["weeks"] + 0.999))
        self.assertEqual(sheet.cell(row=4, column=5).value, "W1")
        self.assertEqual(sheet.cell(row=4, column=4 + weeks).value, f"W{weeks}")
        self.assertEqual(sheet.freeze_panes, "E5")

    def test_the_rows_are_grouped_so_a_reader_sees_roles_before_stories(self):
        sheet = self.extend()[[n for n in self.extend().sheetnames if n.startswith("Gantt")][0]]
        levels = {sheet.row_dimensions[r].outlineLevel for r in range(5, sheet.max_row + 1)}
        self.assertEqual(levels, {0, 1, 2})

    def test_bars_are_painted_in_the_brand_colour_for_the_role(self):
        after = self.extend()
        sheet = after[[n for n in after.sheetnames if n.startswith("Gantt")][0]]
        brand = F.load("brand", F.EST / "scripts" / "brand.py")
        wanted = {brand._hex(c) for r, c in brand.load()["roles"].items() if not r.startswith("_")}
        painted = {sheet.cell(row=r, column=c).fill.fgColor.rgb
                   for r in range(5, sheet.max_row + 1) for c in range(5, sheet.max_column + 1)}
        painted = {p[2:] if isinstance(p, str) and len(p) == 8 else p for p in painted}
        self.assertTrue(wanted & painted, "no bar used a role colour from brand.json")

    def test_the_options_tab_carries_every_option_and_marks_the_recommendation(self):
        sheet = self.extend()["Options"]
        ids = [sheet.cell(row=r, column=1).value for r in range(5, sheet.max_row + 1)]
        self.assertEqual(len([i for i in ids if i]), len(self.plan["options"]))
        self.assertTrue(any(str(i).startswith("★") for i in ids))

    def test_a_missing_workbook_is_reported_rather_than_created(self):
        """est-plan extends the estimate's workbook. Creating one would hand a client a second
        file with a Gantt and no scope in it."""
        ok, why = render.extend_workbook(self.plan, Path(self.dir.name) / "absent.xlsx")
        self.assertFalse(ok)
        self.assertIn("does not exist", why)


if __name__ == "__main__":
    unittest.main()
