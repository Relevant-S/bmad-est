#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Tests for render-inventory.py — the human and sales projections.

The load-bearing property: a verbatim quote must survive the round trip intact. Pipes,
newlines and non-Latin text are exactly what a naive markdown table destroys, and
destroying the quote destroys the traceability the whole module rests on.
"""

import csv
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fixtures import feature, inventory  # noqa: E402

SCRIPTS = Path(__file__).resolve().parent.parent


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


render = load("render_inventory", "render-inventory.py")


class TestRender(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, inv):
        path = self.dir / "feature-inventory.json"
        path.write_text(json.dumps(inv), encoding="utf-8")
        return path

    def test_markdown_preserves_a_quote_containing_pipes_and_newlines(self):
        hostile = "Users can pay by card | bank transfer\nand receive a receipt."
        f = feature()
        f["citations"][0]["quote"] = hostile
        md = render.render_markdown(inventory(features=[f]))
        self.assertIn("Users can pay by card | bank transfer", md)

    def test_markdown_preserves_original_language_quote(self):
        f = feature()
        f["citations"][0]["quote_original"] = "Користувачі повинні входити в систему."
        f["citations"][0]["quote_language"] = "uk"
        md = render.render_markdown(inventory(features=[f]))
        self.assertIn("Користувачі повинні входити в систему.", md)

    def test_markdown_carries_scope_and_says_nothing_about_cost(self):
        """These views render what the client asked for. The classification a story is priced
        on lives in classification.json and renders through est-estimate, so a reviewer reading
        this is checking the scope against the source with no effort judgement mixed in."""
        md = render.render_markdown(inventory())
        for axis in ("size_band", "compressibility", "review_tier", "clarity", "novelty"):
            self.assertNotIn(f"| {axis} |", md)
        self.assertIn("Users must be able to log in", md)

    def test_markdown_includes_not_scope_section(self):
        md = render.render_markdown(inventory())
        self.assertIn("Not treated as scope", md)
        self.assertIn("commercial terms, not scope", md)

    def test_markdown_marks_a_feature_outside_the_agreed_scope(self):
        md = render.render_markdown(inventory(features=[feature(scope_status="outside_agreed_scope")]))
        self.assertIn("outside agreed scope", md)
        self.assertIn("estimated separately", md)

    def test_csv_defaults_scope_status_when_absent(self):
        target = self.dir / "feature-inventory.csv"
        render.render_csv(inventory(), target)
        with target.open(encoding="utf-8-sig") as fh:
            row = next(iter(csv.DictReader(fh)))
        self.assertEqual(row["scope_status"], "in_agreed_scope")

    def test_csv_row_carries_the_scope_columns_and_no_cost_axis(self):
        target = self.dir / "feature-inventory.csv"
        render.render_csv(inventory(), target)
        with target.open(encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            row = next(iter(reader))
            columns = reader.fieldnames
        self.assertEqual(row["id"], "F1")
        self.assertEqual(row["commitment"], "committed")
        for axis in ("size_band", "compressibility", "review_tier", "clarity", "novelty"):
            self.assertNotIn(axis, columns)

    def test_csv_survives_a_quote_containing_a_comma_and_newline(self):
        f = feature()
        f["citations"][0]["quote"] = "Users can log in, log out\nand reset a password."
        target = self.dir / "feature-inventory.csv"
        render.render_csv(inventory(features=[f]), target)
        with target.open(encoding="utf-8-sig") as fh:
            row = next(iter(csv.DictReader(fh)))
        self.assertIn("reset a password", row["primary_quote"])

    def test_render_writes_both_projections(self):
        import contextlib
        import io

        path = self.write(inventory())
        sys.argv = ["render-inventory.py", str(path)]
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(render.main(), 0)
        self.assertTrue((self.dir / "feature-inventory.md").exists())
        self.assertTrue((self.dir / "feature-inventory.csv").exists())


class Grouping(unittest.TestCase):
    """The counts a reader checks first: stories against epics against source rows."""

    def grouped(self):
        f = feature("F1", "Lead list: search, filter and sort", epic_id="E1",
                    surfaces=["backend", "frontend"],
                    tasks=[{"id": "T1", "name": "Search leads",
                            "citations": [{"source_id": "S1", "location": "row 181", "quote": "q"}]},
                           {"id": "T2", "name": "Filter leads",
                            "citations": [{"source_id": "S1", "location": "row 182", "quote": "q"}]}])
        return inventory(features=[f],
                         epics=[{"id": "E1", "name": "Lead", "origin": "source"}])

    def test_the_ratio_that_shows_grouping_happened_is_on_the_first_screen(self):
        md = render.render_markdown(self.grouped())
        self.assertIn("**1 stories**", md)
        self.assertIn("1 epics", md)
        self.assertIn("2 source rows", md)

    def test_every_source_row_is_still_named_under_its_story(self):
        """A reviewer checks the inventory against the client's own document line by line,
        which is only possible while every line is still on the page."""
        md = render.render_markdown(self.grouped())
        self.assertIn("`T1` Search leads", md)
        self.assertIn("row 182", md)

    def test_surfaces_say_which_roles_are_on_the_work(self):
        self.assertIn("only these roles are billed", render.render_markdown(self.grouped()))

    def test_implicit_scope_shows_its_reason_where_a_quote_would_be(self):
        inv = self.grouped()
        item = feature("I1", "Migrate ten years of bookings")
        del item["citations"]
        item["rationale"] = "The workbook says the bookings already exist."
        inv["implicit_scope"] = [item]
        md = render.render_markdown(inv)
        self.assertIn("no quote behind it", md)
        self.assertIn("bookings already exist", md)


if __name__ == "__main__":
    unittest.main()
