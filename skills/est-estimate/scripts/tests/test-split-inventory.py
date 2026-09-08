#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Tests for split-inventory.py — moving a legacy inventory's tags into their own file."""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fixtures import feature, inventory, model  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "split_inventory", Path(__file__).resolve().parent.parent / "split-inventory.py"
)
split = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(split)

_est = importlib.util.spec_from_file_location(
    "estimate", Path(__file__).resolve().parent.parent / "estimate.py"
)
est = importlib.util.module_from_spec(_est)
_est.loader.exec_module(est)


class Split(unittest.TestCase):
    def setUp(self):
        self.inv = inventory(features=[feature("F1", "Login", size="L", review_tier="sensitive"),
                                       feature("F2", "Export", size="S")])

    def test_scope_keeps_what_the_source_said(self):
        scope, _, _ = split.split(self.inv, "inv.json")
        for f in scope["features"]:
            self.assertNotIn("tags", f)
            self.assertEqual(f["commitment"], "committed")
            self.assertTrue(f["citations"][0]["quote"])
            self.assertTrue(f["surfaces"], "surfaces is scope, not cost — it stays")

    def test_every_judgement_crosses_over_intact(self):
        """A human's confirmed tag surviving the move matters more than it sounds: losing a
        classification correction is the one failure that makes people stop trusting the tool."""
        self.inv["features"][0]["tags"]["review_tier"] = {
            "value": "critical", "why": "PCI confirmed with the client", "status": "overridden"}
        _, classification, _ = split.split(self.inv, "inv.json")
        carried = classification["features"]["F1"]["review_tier"]
        self.assertEqual((carried["value"], carried["status"], carried["why"]),
                         ("critical", "overridden", "PCI confirmed with the client"))

    def test_it_does_not_mutate_what_it_was_given(self):
        split.split(self.inv, "inv.json")
        self.assertIn("tags", self.inv["features"][0])

    def test_implicit_scope_is_classified_in_the_same_keyspace(self):
        """Implicit scope is priced identically, so its judgements belong in the same file."""
        inv = inventory(features=[feature("F1")], implicit_scope=[
            dict(feature("I1", "Data migration"), rationale="ten years of bookings")])
        _, classification, _ = split.split(inv, "inv.json")
        self.assertEqual(sorted(classification["features"]), ["F1", "I1"])

    def test_a_surfaces_tag_is_moved_back_onto_the_story(self):
        """It was half-migrated into a tag block that is about to stop existing."""
        inv = inventory(features=[feature("F1", surfaces=None)])
        inv["features"][0]["tags"]["surfaces"] = {
            "value": ["backend"], "why": "server-side only", "status": "inferred"}
        scope, classification, notes = split.split(inv, "inv.json")
        self.assertEqual(scope["features"][0]["surfaces"], ["backend"])
        self.assertNotIn("surfaces", classification["features"]["F1"])
        self.assertTrue(any("surfaces moved" in n for n in notes))

    def test_a_partial_tag_block_is_reported_not_padded(self):
        inv = inventory(features=[feature("F1")])
        del inv["features"][0]["tags"]["novelty"]
        _, classification, notes = split.split(inv, "inv.json")
        self.assertNotIn("novelty", classification["features"]["F1"])
        self.assertTrue(any("no novelty" in n for n in notes))

    def test_the_round_trip_prices_to_the_same_number(self):
        """The whole point: this is a move, not a re-judgement."""
        m = model()
        options = est.options_from({"inputs": {}, "granularity": "project", "mode": "presale",
                                    "confidence": {"input_completeness": 0.8}}, m)
        before = est.build_estimate(self.inv, m, options)["total_hours"]["likely"]
        scope, classification, _ = split.split(self.inv, "inv.json")
        joined, missing, orphans = est.load_scope(scope, classification)
        self.assertEqual((missing, orphans), ([], []))
        self.assertEqual(est.build_estimate(joined, m, options)["total_hours"]["likely"], before)


class CLI(unittest.TestCase):
    def test_an_already_split_inventory_is_refused_rather_than_emptied(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "inv.json"
            scope, _, _ = split.split(inventory(features=[feature("F1")]), "inv.json")
            path.write_text(json.dumps(scope))
            _, classification, _ = split.split(json.loads(path.read_text()), str(path))
            self.assertEqual(classification["features"], {})


if __name__ == "__main__":
    unittest.main()
