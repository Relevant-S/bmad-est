#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Tests for ledger.py.

The ledger is what makes calibration possible later, so the properties that matter are
that an entry keeps the cost model that produced it, that entries are immutable, and
that the index is derived rather than maintained.
"""

import importlib.util
import json
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
ledger = load("ledger", "ledger.py")


def estimate_for(features=None, **opt):
    inv = inventory(features)
    opt.setdefault("granularity", inv.get("granularity", "project"))
    return est.build_estimate(inv, model(), options(**opt))


class TestLedger(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_recording_stores_the_cost_model_snapshot(self):
        e = estimate_for()
        e["generated"] = "2026-09-07T10:00:00Z"
        result = ledger.record(e, self.dir, "draft")
        self.assertTrue(result["ok"])
        stored = json.loads(Path(result["entry"]).read_text(encoding="utf-8"))
        self.assertIn("cost_model_snapshot", stored)
        self.assertEqual(stored["ledger"]["status"], "draft")

    def test_a_draft_may_be_deliberately_replaced(self):
        e = estimate_for()
        e["generated"] = "2026-09-07T10:00:00Z"
        ledger.record(e, self.dir, "draft")
        again = ledger.record(e, self.dir, "draft")
        self.assertFalse(again["ok"])
        self.assertEqual(again["existing_status"], "draft")
        self.assertTrue(ledger.record(e, self.dir, "sent", replace=True)["ok"])

    def test_a_committed_entry_is_never_overwritten(self):
        """Once a number has gone to a client it is a commercial fact, not a draft."""
        e = estimate_for()
        e["generated"] = "2026-09-07T10:00:00Z"
        eid = ledger.record(e, self.dir, "draft")["id"]
        ledger.set_status(self.dir, eid, "sent")
        refused = ledger.record(e, self.dir, "draft", replace=True)
        self.assertFalse(refused["ok"])
        self.assertIn("Use --revision", refused["error"])

    def test_re_estimating_the_same_project_same_day_keeps_both(self):
        """The normal presale case after a client pushes back — it must not destroy the first."""
        e = estimate_for()
        e["generated"] = "2026-09-07T10:00:00Z"
        first = ledger.record(e, self.dir, "draft")["id"]
        second = ledger.record(e, self.dir, "draft", revision=True)["id"]
        self.assertNotEqual(first, second)
        self.assertTrue(second.endswith("-r2"))
        self.assertEqual(len(ledger.reindex(self.dir)), 2)

    def test_a_third_revision_does_not_collide_with_the_second(self):
        e = estimate_for()
        e["generated"] = "2026-09-07T10:00:00Z"
        ledger.record(e, self.dir, "draft")
        ledger.record(e, self.dir, "draft", revision=True)
        third = ledger.record(e, self.dir, "draft", revision=True)["id"]
        self.assertTrue(third.endswith("-r3"))
        self.assertEqual(len(ledger.reindex(self.dir)), 3)

    def test_the_collision_message_names_the_recovery(self):
        e = estimate_for()
        e["generated"] = "2026-09-07T10:00:00Z"
        ledger.record(e, self.dir, "draft")
        self.assertIn("--revision", ledger.record(e, self.dir, "draft")["error"])

    def test_the_index_is_rebuilt_from_the_entries_so_it_cannot_drift(self):
        e = estimate_for()
        e["generated"] = "2026-09-07T10:00:00Z"
        ledger.record(e, self.dir, "draft")
        (self.dir / "index.json").write_text('{"entries": []}', encoding="utf-8")
        rows = ledger.reindex(self.dir)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "draft")

    def test_status_can_be_advanced_as_the_deal_moves(self):
        e = estimate_for()
        e["generated"] = "2026-09-07T10:00:00Z"
        eid = ledger.record(e, self.dir, "draft")["id"]
        self.assertTrue(ledger.set_status(self.dir, eid, "won")["ok"])
        self.assertEqual(ledger.reindex(self.dir)[0]["status"], "won")

    def test_the_index_carries_what_calibration_will_need_to_match_on(self):
        e = estimate_for()
        e["generated"] = "2026-09-07T10:00:00Z"
        ledger.record(e, self.dir, "draft")
        row = ledger.reindex(self.dir)[0]
        for field in ("likely_hours", "input_completeness", "features", "has_actuals"):
            self.assertIn(field, row)

    def test_entry_ids_are_stable_and_readable(self):
        e = estimate_for()
        e["generated"] = "2026-09-07T10:00:00Z"
        e["project"] = "Northwind Depot Portal"
        self.assertEqual(ledger.entry_id(e), "EST-20260907-northwind-depot-portal")


if __name__ == "__main__":
    unittest.main()
