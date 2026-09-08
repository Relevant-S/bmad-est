#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Tests for plan-beats.py — cutting sources into the units of parallel extraction."""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "plan_beats", Path(__file__).resolve().parent.parent / "plan-beats.py"
)
beats = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(beats)

HEADER = "| row | A | B |\n| --- | --- | --- |\n"


def sheet(name, rows):
    """`rows` as (row_no, first_cell, second_cell)."""
    out = [f"## sheet: {name}", "", HEADER.rstrip()]
    out += [f"| {n} | {a} | {b} |" for n, a, b in rows]
    return "\n".join(out) + "\n"


def workspace(tmp, text, source_id="S1"):
    d = Path(tmp) / "normalized"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{source_id}-doc.md").write_text(text, encoding="utf-8")
    return d


class Grouping(unittest.TestCase):
    def plan(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            got, _ = beats.plan(workspace(tmp, text), {"sources": [{"id": "S1"}]})
            return got

    def test_a_sparse_first_column_cuts_one_beat_per_group(self):
        """The value appears on the first row of a group and the rows beneath inherit it —
        the grouping a domain expert already did, which beats any this could invent."""
        rows = [(1, "Epic", "Name")]
        rows += [(n, "Bookings" if n == 2 else "", f"row {n}") for n in range(2, 16)]
        rows += [(n, "Fleet" if n == 16 else "", f"row {n}") for n in range(16, 30)]
        got = self.plan(sheet("Backlog", rows))
        self.assertEqual([b["title"].split(" · ")[1] for b in got], ["Bookings", "Fleet"])
        self.assertEqual([b["units"] for b in got], [14, 14])

    def test_a_dense_first_column_is_a_catalogue_and_stays_whole(self):
        """Sixty workspace-health checks are one story sized for the count, not sixty
        features. A value on every row is data, not a grouping column."""
        rows = [(1, "Rule", "Fires when")]
        rows += [(n, f"ALERT-{n}", f"condition {n}") for n in range(2, 42)]
        got = self.plan(sheet("Alert rules", rows))
        self.assertEqual(len(got), 1)
        self.assertIn("catalogue", got[0]["why"])
        self.assertEqual(got[0]["units"], 40)

    def test_no_grouping_column_falls_back_to_windows(self):
        rows = [(1, "", "Name")] + [(n, "", f"row {n}") for n in range(2, 130)]
        got = self.plan(sheet("Flat", rows))
        self.assertGreater(len(got), 1)
        self.assertTrue(all(b["units"] <= beats.MAX_ROWS_PER_BEAT for b in got))
        self.assertIn("window", got[0]["why"])

    def test_a_small_sheet_is_read_whole(self):
        rows = [(1, "Epic", "Name")] + [(n, f"E{n}", f"row {n}") for n in range(2, 8)]
        got = self.plan(sheet("Small", rows))
        self.assertEqual(len(got), 1)

    def test_an_oversized_group_is_windowed_rather_than_left_unreadable(self):
        rows = [(1, "Epic", "Name")]
        rows += [(n, "Bookings" if n == 2 else "", f"row {n}") for n in range(2, 150)]
        got = self.plan(sheet("Backlog", rows))
        self.assertGreater(len(got), 1)
        self.assertTrue(all(b["units"] <= beats.MAX_ROWS_PER_BEAT for b in got))
        self.assertTrue(all("Bookings" in b["title"] for b in got))


class Anchors(unittest.TestCase):
    def plan(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            got, _ = beats.plan(workspace(tmp, text), {"sources": [{"id": "S1"}]})
            return got

    def rows(self):
        out = [(1, "Epic", "Name")]
        out += [(n, "Bookings" if n == 2 else "", f"row {n}") for n in range(2, 16)]
        out += [(n, "Fleet" if n == 16 else "", f"row {n}") for n in range(16, 30)]
        return out

    def test_every_beat_is_a_contiguous_row_range(self):
        """A citation written inside a beat must anchor exactly as it would have in a single
        pass. A partition that reordered or skipped rows would break every location."""
        got = self.plan(sheet("Backlog", self.rows()))
        covered = []
        for b in got:
            lo, hi = b["rows"]
            self.assertLessEqual(lo, hi)
            covered += list(range(lo, hi + 1))
        self.assertEqual(covered, sorted(covered))
        self.assertEqual(len(covered), len(set(covered)), "no row is read twice")
        self.assertEqual(covered, list(range(2, 30)), "and none is skipped")

    def test_the_header_row_is_handed_to_every_beat_not_made_into_one(self):
        """A beat that cannot see the column names is reading unlabelled cells — but the
        header is not a unit of work of its own."""
        got = self.plan(sheet("Backlog", self.rows()))
        self.assertTrue(all(b["header_row"] == 1 for b in got))
        self.assertTrue(all(b["rows"][0] > 1 for b in got))

    def test_beat_ids_carry_the_source_they_came_from(self):
        got = self.plan(sheet("Backlog", self.rows()))
        self.assertTrue(all(b["beat_id"].startswith("S1-b") for b in got))
        self.assertEqual(len({b["beat_id"] for b in got}), len(got))

    def test_prose_cuts_on_headings(self):
        text = "# Doc\n\nintro\n\n## Scope\n\nbody\n\n## Commercials\n\nrates\n"
        got = self.plan(text)
        self.assertEqual([b["title"] for b in got], ["Doc", "Scope", "Commercials"])
        self.assertTrue(all(b["rows"] is None for b in got))

    def test_a_source_missing_from_the_manifest_is_noted_not_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            got, notes = beats.plan(workspace(tmp, sheet("Backlog", self.rows())), {"sources": []})
            self.assertTrue(got)
            self.assertTrue(any("not in the manifest" in n for n in notes))


if __name__ == "__main__":
    unittest.main()
