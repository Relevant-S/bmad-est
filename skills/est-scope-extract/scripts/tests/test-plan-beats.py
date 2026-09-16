#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Tests for plan-beats.py — cutting sources into the units of parallel extraction."""

import importlib.util
import json
import sys
import subprocess
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
            got, _, _ = beats.plan(workspace(tmp, text), {"sources": [{"id": "S1"}]})
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
            got, _, _ = beats.plan(workspace(tmp, text), {"sources": [{"id": "S1"}]})
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
            got, notes, _ = beats.plan(workspace(tmp, sheet("Backlog", self.rows())), {"sources": []})
            self.assertTrue(got)
            self.assertTrue(any("not in the manifest" in n for n in notes))



class EveryLineLandsInABeat(unittest.TestCase):
    """The partition has to be a partition.

    Kitespire's PRD converted to 6,233 lines containing exactly two lines that matched the old
    heading pattern — both table header rows whose first cell was a `#` column marker. Two
    marks cleared the `len(marks) < 2` fallback, the document was cut into those two sections,
    and 97.4% of it was placed in no beat at all. Extraction reads beats, so that part of the
    document was never read: every story came back citing a single line, the classifier sized a
    whole product against those lines, and the estimate came out at roughly twice what the same
    two documents produced on a run that had partitioned them by hand.
    """

    def beats_for(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            got, _, coverage = beats.plan(workspace(tmp, text), {"sources": [{"id": "S1"}]})
            return got, coverage[0]

    def test_a_converted_table_header_is_not_a_heading(self):
        """The two real lines out of the Kitespire PRD, verbatim. Neither is a heading, and
        treating them as one is what cut 6,074 lines out of the reading."""
        for line in ("#    RISK                 IMPACT               LIKELIHOOD   MITIGATION",
                     "#     ASSUMPTION                               IMPLICATION IF WRONG"):
            self.assertIsNone(beats.is_heading(line), line)

    def test_a_real_heading_still_is_one(self):
        for line in ("# Overview", "## 06.2 Auth and Onboarding", "### F-001 Sign in"):
            self.assertTrue(beats.is_heading(line), line)

    def test_the_kitespire_shape_now_covers_the_whole_document(self):
        body = ["prose line %d" % i for i in range(6000)]
        body[5000] = "#    RISK                 IMPACT           LIKELIHOOD   MITIGATION"
        body[5100] = "#     ASSUMPTION                           IMPLICATION IF WRONG"
        got, coverage = self.beats_for("\n".join(body) + "\n")
        self.assertEqual(coverage["share"], 1.0)
        self.assertEqual(coverage["unplaced_line_ranges"], [])
        self.assertGreater(len(got), 2, "the document was cut into two sections again")

    def test_nothing_before_the_first_heading_is_dropped(self):
        """Even with real headings, the old cut started at the first mark — so a document's
        entire front matter was unreachable. Kitespire's was 6,074 lines of it."""
        text = "\n".join(["front matter"] * 30 + ["# Scope"] + ["scope"] * 10) + "\n"
        got, coverage = self.beats_for(text)
        self.assertEqual(coverage["share"], 1.0)
        self.assertEqual(got[0]["lines"][0], 1)
        self.assertIn("front matter", got[0]["title"].lower() + got[0]["why"].lower())

    def test_a_long_section_is_windowed_as_the_docstring_always_promised(self):
        text = "\n".join(["# One"] + ["line"] * 1500) + "\n"
        got, coverage = self.beats_for(text)
        self.assertGreater(len(got), 1)
        self.assertEqual(coverage["share"], 1.0)
        self.assertTrue(all(b["units"] <= beats.MAX_PROSE_LINES_PER_BEAT for b in got))
        self.assertTrue(all("lines" in b["title"] for b in got), [b["title"] for b in got])

    def test_a_headingless_document_is_windowed_rather_than_handed_over_whole(self):
        got, coverage = self.beats_for("\n".join(["line"] * 2000) + "\n")
        self.assertGreater(len(got), 1)
        self.assertEqual(coverage["share"], 1.0)

    def test_the_beats_never_overlap(self):
        """A line read by two beats is cited twice and priced twice."""
        text = "\n".join(["intro"] * 20 + ["# A"] + ["a"] * 900 + ["# B"] + ["b"] * 40) + "\n"
        got, _ = self.beats_for(text)
        seen = set()
        for b in got:
            span = set(range(b["lines"][0], b["lines"][1] + 1))
            self.assertFalse(seen & span, f"{b['beat_id']} overlaps an earlier beat")
            seen |= span

    def test_a_short_headed_section_keeps_the_documents_own_title(self):
        """A heading a reader can find in the source beats a line range every time; only a
        windowed section needs the range appended to tell its parts apart."""
        text = "\n".join(["# Scope"] + ["s"] * 5 + ["# Commercials"] + ["c"] * 5) + "\n"
        got, _ = self.beats_for(text)
        self.assertEqual([b["title"] for b in got], ["Scope", "Commercials"])


class APartitionThatDoesNotCoverIsRefused(unittest.TestCase):
    def test_coverage_is_reported_per_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, coverage = beats.plan(
                workspace(tmp, "\n".join(["# A"] + ["x"] * 40) + "\n"),
                {"sources": [{"id": "S1"}]})
        self.assertEqual(coverage[0]["source_id"], "S1")
        self.assertEqual(coverage[0]["share"], 1.0)
        self.assertIn("reachable", coverage[0])

    def test_a_workbooks_held_out_header_row_counts_as_read_not_as_a_gap(self):
        """The first row of a sheet is handed to every beat rather than being one, so counting
        it unplaced reported 97.2% on a workbook whose every data row was covered — the kind of
        false number that teaches a reader to ignore the check."""
        rows = [(1, "Epic", "Name")]
        rows += [(n, "Bookings" if n == 2 else "", f"row {n}") for n in range(2, 20)]
        with tempfile.TemporaryDirectory() as tmp:
            _, _, coverage = beats.plan(workspace(tmp, sheet("Backlog", rows)),
                                        {"sources": [{"id": "S1"}]})
        self.assertEqual(coverage[0]["share"], 1.0)

    def test_a_gap_is_found_and_reported_as_line_ranges(self):
        """The detector itself, against a partition with a hole in the middle. A reader who is
        told "97.4% unplaced" still needs to know which 97.4%."""
        placed, gaps = beats.coverage_of([("a", (0, 9)), ("b", (30, 39))], 40)
        self.assertEqual(placed, 20)
        self.assertEqual(gaps, [[11, 30]])

    def test_a_complete_partition_reports_no_gaps(self):
        placed, gaps = beats.coverage_of([("a", (0, 19)), ("b", (20, 39))], 40)
        self.assertEqual((placed, gaps), (40, []))

    def test_the_cli_exits_zero_on_a_partition_that_covers_its_source(self):
        """`plan-beats.py` is called by an agent about to fan subagents out over these beats,
        and it reads the exit code. A run that proceeds on a 2.6% partition is a run over a
        document nobody read."""
        with tempfile.TemporaryDirectory() as tmp:
            body = ["prose %d" % i for i in range(1200)]
            body[900] = "#    RISK       IMPACT        LIKELIHOOD   MITIGATION"
            d = workspace(tmp, "\n".join(body) + "\n")
            out = Path(tmp) / "beats.json"
            proc = subprocess.run(
                [sys.executable, str(Path(__file__).resolve().parent.parent / "plan-beats.py"),
                 str(d), "-o", str(out)], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            plan = json.loads(out.read_text(encoding="utf-8"))
        self.assertTrue(plan["ok"])
        self.assertEqual(plan["summary"]["coverage"], 1.0)
        self.assertEqual(plan["summary"]["sources_short_of_coverage"], [])
        self.assertGreater(plan["summary"]["beats"], 2)


if __name__ == "__main__":
    unittest.main()
