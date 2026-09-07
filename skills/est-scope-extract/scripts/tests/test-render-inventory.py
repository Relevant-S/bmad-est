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

    def test_markdown_marks_sensitive_features(self):
        self.assertIn("⚠ sensitive", render.render_markdown(inventory()))

    def test_markdown_renders_tag_justifications(self):
        md = render.render_markdown(inventory())
        self.assertIn("| size_band | **M** | because | inferred |", md)

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

    def test_csv_row_carries_the_cost_model_axes(self):
        target = self.dir / "feature-inventory.csv"
        render.render_csv(inventory(), target)
        with target.open(encoding="utf-8-sig") as fh:
            row = next(iter(csv.DictReader(fh)))
        self.assertEqual(row["size_band"], "M")
        self.assertEqual(row["review_tier"], "sensitive")
        self.assertEqual(row["compressibility"], "high")
        self.assertEqual(row["id"], "F1")

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


if __name__ == "__main__":
    unittest.main()
