#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Tests for ingest-actuals.py — tolerant about column names, strict about the three
fields that silently invalidate a comparison."""

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

_spec = importlib.util.spec_from_file_location(
    "ingest", Path(__file__).resolve().parent.parent / "ingest-actuals.py")
ing = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ing)


class TestColumnDetection(unittest.TestCase):
    def test_hours_column_is_found_under_the_names_real_trackers_use(self):
        for name in ("Hours", "duration", "TIME SPENT", "hrs", "Logged Time",
                     "Hours Worked", "Total Hours", "Billable Hours"):
            self.assertIsNotNone(ing.find_column(["Date", name, "Who"], ing.HOURS_COLUMNS),
                                 f"failed on {name}")

    def test_a_timestamp_column_is_not_mistaken_for_hours(self):
        """Substring matching would take 'timestamp' as an hours column and sum dates."""
        self.assertIsNone(ing.find_column(["Timestamp", "Sprint"], ing.HOURS_COLUMNS))
        self.assertIsNone(ing.find_column(["Start Time Zone"], ing.HOURS_COLUMNS))

    def test_phase_column_is_found_under_various_names(self):
        for name in ("Phase", "Activity", "work type"):
            self.assertIsNotNone(ing.find_column(["Date", name], ing.PHASE_COLUMNS))

    def test_an_unknown_column_is_not_matched(self):
        self.assertIsNone(ing.find_column(["Date", "Sprint"], ing.HOURS_COLUMNS))


class TestPhaseMapping(unittest.TestCase):
    def test_common_tracker_names_map_onto_bmad_phases(self):
        for raw, expected in (("Development", "build"), ("code review", "review"),
                              ("Testing", "qa"), ("standup", "overhead"), ("DevOps", "environments")):
            self.assertEqual(ing.PHASE_ALIASES[raw.lower()], expected)

    def test_an_unrecognised_activity_is_reported_not_guessed(self):
        rows = [["Activity", "Hours"], ["build", "10"], ["client workshop", "5"]]
        agg = ing.aggregate(rows)
        self.assertEqual(agg["by_phase"], {"build": 10.0})
        self.assertEqual(agg["unmapped"], ["client workshop"])
        self.assertEqual(agg["total"], 15.0)   # counted in the total, not attributed


class TestAggregation(unittest.TestCase):
    def test_hours_sum_by_phase(self):
        rows = [["Phase", "Hours"], ["build", "10"], ["build", "5"], ["qa", "3"]]
        agg = ing.aggregate(rows)
        self.assertEqual(agg["by_phase"], {"build": 15.0, "qa": 3.0})

    def test_hours_sum_by_feature_and_role(self):
        rows = [["Ticket", "Member", "Hours"], ["F1", "Dev A", "8"], ["F1", "Dev B", "2"]]
        agg = ing.aggregate(rows)
        self.assertEqual(agg["by_feature"], {"F1": 10.0})
        self.assertEqual(agg["by_role"], {"dev a": 8.0, "dev b": 2.0})

    def test_comma_decimals_are_accepted(self):
        agg = ing.aggregate([["Phase", "Hours"], ["build", "10,5"]])
        self.assertEqual(agg["total"], 10.5)

    def test_unparseable_rows_are_skipped_not_fatal(self):
        agg = ing.aggregate([["Phase", "Hours"], ["build", "10"], ["build", "n/a"]])
        self.assertEqual(agg["total"], 10.0)

    def test_a_missing_hours_column_fails_with_a_useful_message(self):
        with self.assertRaises(SystemExit) as ctx:
            ing.aggregate([["Phase", "Sprint"], ["build", "3"]])
        self.assertIn("no hours column", str(ctx.exception))


class TestSchemaValidation(unittest.TestCase):
    """The schema is the contract analyze.py reads. A typo here surfaces months later as a
    project silently missing from a calibration sample."""

    def valid(self, **over):
        base = {"granularity": "project", "delivery_hours": 500.0,
                "scope_delivered": "as_estimated", "source": "Toggl", "captured": "2026-06-01"}
        base.update(over)
        return base

    def test_a_well_formed_record_passes(self):
        self.assertEqual(ing.validate(self.valid()), [])

    def test_a_missing_required_field_is_caught(self):
        record = self.valid()
        del record["scope_delivered"]
        self.assertTrue(any("scope_delivered" in p for p in ing.validate(record)))

    def test_a_value_outside_the_enum_is_caught(self):
        problems = ing.validate(self.valid(scope_delivered="mostly"))
        self.assertTrue(any("mostly" in p for p in problems))

    def test_an_unknown_field_is_caught(self):
        problems = ing.validate(self.valid(delivery_hrs=500))
        self.assertTrue(any("delivery_hrs" in p for p in problems))

    def test_a_wrong_type_is_caught(self):
        self.assertTrue(any("expected a number" in p
                            for p in ing.validate(self.valid(delivery_hours="500"))))

    def test_optional_fields_are_accepted(self):
        self.assertEqual(ing.validate(self.valid(confidence="reconstructed", excluded_hours=40.0,
                                                 excluded_why="client delay",
                                                 by_phase={"build": 100.0})), [])


class TestFileReading(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_csv_with_a_semicolon_delimiter_is_read(self):
        path = self.dir / "export.csv"
        path.write_text("Phase;Hours\nbuild;12\n", encoding="utf-8")
        self.assertEqual(ing.aggregate(ing.read_rows(path))["total"], 12.0)

    def test_an_unsupported_format_is_refused_clearly(self):
        path = self.dir / "export.pdf"
        path.write_bytes(b"%PDF")
        with self.assertRaises(SystemExit) as ctx:
            ing.read_rows(path)
        self.assertIn("unsupported export format", str(ctx.exception))


class PerRoleTotals(unittest.TestCase):
    """The one attribution a delivery lead can give without a time-tracking export."""

    def test_role_hours_are_parsed_from_the_flag(self):
        self.assertEqual(ing.parse_roles("dev=280,ux=120,qa=40"),
                         {"dev": 280.0, "ux": 120.0, "qa": 40.0})

    def test_whitespace_and_case_do_not_matter(self):
        self.assertEqual(ing.parse_roles(" Dev = 280 , UX=120 "),
                         {"dev": 280.0, "ux": 120.0})

    def test_nothing_given_is_an_empty_split_not_an_error(self):
        self.assertEqual(ing.parse_roles(None), {})
        self.assertEqual(ing.parse_roles(""), {})

    def test_a_malformed_pair_is_refused_rather_than_dropped(self):
        """Silently discarding a role would understate exactly the evidence being captured."""
        with self.assertRaises(SystemExit):
            ing.parse_roles("dev=280,ux")
        with self.assertRaises(SystemExit):
            ing.parse_roles("dev=lots")


if __name__ == "__main__":
    unittest.main()
