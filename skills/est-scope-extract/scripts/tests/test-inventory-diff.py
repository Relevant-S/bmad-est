#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Tests for inventory-diff.py — scope change detection and human-tag protection."""

import importlib.util
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fixtures import feature, inventory, tag  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "inventory_diff", Path(__file__).resolve().parent.parent / "inventory-diff.py"
)
diff = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(diff)


class TestMatching(unittest.TestCase):
    def test_matches_by_id(self):
        pairs, added, removed = diff.match_features([feature("F1", "Login")], [feature("F1", "Login")])
        self.assertEqual((len(pairs), added, removed), (1, [], []))
        self.assertEqual(pairs[0][2], "id")

    def test_matches_by_name_when_ids_were_renumbered(self):
        old = [feature("F1", "User login and session handling")]
        new = [feature("F7", "User login and session handling")]
        pairs, added, removed = diff.match_features(old, new)
        self.assertEqual((len(pairs), added, removed), (1, [], []))
        self.assertTrue(pairs[0][2].startswith("name~"))

    def test_unrelated_features_are_added_and_removed_not_matched(self):
        old = [feature("F1", "Bulk CSV import of historical orders")]
        new = [feature("F2", "Marketing newsletter signup")]
        pairs, added, removed = diff.match_features(old, new)
        self.assertEqual(len(pairs), 0)
        self.assertEqual((len(added), len(removed)), (1, 1))

    def test_each_old_feature_matches_at_most_once(self):
        old = [feature("F1", "User login")]
        new = [feature("F8", "User login"), feature("F9", "User login")]
        pairs, added, _ = diff.match_features(old, new)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(len(added), 1)


class TestCompare(unittest.TestCase):
    def test_detects_review_tier_change(self):
        old = feature()
        new = feature(tags={**feature()["tags"], "review_tier": tag("critical")})
        fields = [c["field"] for c in diff.compare(old, new)]
        self.assertIn("tags.review_tier", fields)

    def test_detects_commitment_change(self):
        new = feature(commitment="speculative")
        self.assertIn("commitment", [c["field"] for c in diff.compare(feature(), new)])

    def test_detects_dependency_changes(self):
        new = feature(depends_on=[{"feature_id": "F2", "inferred": True}])
        change = next(c for c in diff.compare(feature(), new) if c["field"] == "depends_on")
        self.assertEqual(change["added"], ["F2"])

    def test_identical_features_report_no_changes(self):
        self.assertEqual(diff.compare(feature(), feature()), [])


class TestProtection(unittest.TestCase):
    def test_confirmed_tag_reverted_to_inferred_is_protected(self):
        old = feature(tags={**feature()["tags"], "review_tier": tag("critical", status="confirmed")})
        new = feature(tags={**feature()["tags"], "review_tier": tag("routine", status="inferred")})
        protected = diff.protected_tags(old, new)
        self.assertEqual(len(protected), 1)
        self.assertEqual(protected[0]["human_value"], "critical")
        self.assertEqual(protected[0]["reextracted_value"], "routine")

    def test_overridden_tag_is_protected(self):
        old = feature(tags={**feature()["tags"], "size_band": tag("L", status="overridden")})
        new = feature(tags={**feature()["tags"], "size_band": tag("M", status="inferred")})
        self.assertEqual([p["axis"] for p in diff.protected_tags(old, new)], ["size_band"])

    def test_confirmed_tag_that_survives_unchanged_is_not_flagged(self):
        old = feature(tags={**feature()["tags"], "review_tier": tag("sensitive", status="confirmed")})
        new = feature(tags={**feature()["tags"], "review_tier": tag("sensitive", status="confirmed")})
        self.assertEqual(diff.protected_tags(old, new), [])

    def test_inferred_tag_changing_is_not_protected(self):
        old = feature(tags={**feature()["tags"], "clarity": tag("low", status="inferred")})
        new = feature(tags={**feature()["tags"], "clarity": tag("high", status="inferred")})
        self.assertEqual(diff.protected_tags(old, new), [])


class TestTierShift(unittest.TestCase):
    def test_reports_retiering_and_added_tiers(self):
        old = [feature("F1", "Checkout", tags={**feature()["tags"], "review_tier": tag("routine")})]
        new = [feature("F1", "Checkout", tags={**feature()["tags"], "review_tier": tag("critical")}),
               feature("F2", "Refunds", tags={**feature()["tags"], "review_tier": tag("sensitive")})]
        pairs, added, removed = diff.match_features(old, new)
        shift = diff.summarize_tier_shift(pairs, added, removed)
        self.assertEqual(shift["added"]["sensitive"], 1)
        self.assertEqual(shift["retiered"], [{"feature": "F1", "from": "routine", "to": "critical"}])


class TestMerge(unittest.TestCase):
    """The merge is deterministic; only what a human must decide comes back as a question."""

    def merge(self, old_features, new_features):
        old, new = inventory(features=old_features), inventory(features=new_features)
        pairs, added, removed = diff.match_features(old["features"], new["features"])
        return diff.build_merge(old, new, pairs, added, removed)

    def test_stable_feature_ids_survive_renumbering(self):
        merged, _, _ = self.merge([feature("F1", "User login")], [feature("F90", "User login")])
        self.assertEqual([f["id"] for f in merged["features"]], ["F1"])

    def test_human_tag_is_restored_with_its_reason_and_status(self):
        old = feature("F1", "Checkout", tags={**feature()["tags"],
                      "review_tier": tag("critical", "PCI confirmed with the client", "overridden")})
        new = feature("F1", "Checkout", tags={**feature()["tags"], "review_tier": tag("routine")})
        merged, _, restored = self.merge([old], [new])
        carried = merged["features"][0]["tags"]["review_tier"]
        self.assertEqual((carried["value"], carried["status"]), ("critical", "overridden"))
        self.assertEqual(carried["why"], "PCI confirmed with the client")
        self.assertEqual(len(restored), 1)

    def test_new_feature_gets_an_id_that_collides_with_nothing(self):
        merged, _, _ = self.merge([feature("F1", "User login"), feature("F2", "Export")],
                                  [feature("F1", "User login"), feature("F9", "Tracking page")])
        ids = [f["id"] for f in merged["features"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertNotIn("F2", ids[1:])

    def test_removed_feature_is_raised_as_a_decision_not_dropped_silently(self):
        _, needs, _ = self.merge([feature("F1", "Login"), feature("F2", "Route prediction")],
                                 [feature("F1", "Login")])
        self.assertEqual([n["kind"] for n in needs], ["feature_absent_from_new_sources"])
        self.assertEqual(needs[0]["feature"], "F2")

    def test_dependencies_are_remapped_to_the_stable_ids(self):
        old = [feature("F1", "User login"), feature("F2", "User profile page")]
        new = [feature("F80", "User login"),
               feature("F81", "User profile page", depends_on=[{"feature_id": "F80", "inferred": True}])]
        merged, _, _ = self.merge(old, new)
        self.assertEqual(merged["features"][1]["depends_on"][0]["feature_id"], "F1")

    def test_identical_features_are_not_confused_for_one_another(self):
        old = [feature("F1", "Alpha report"), feature("F2", "Alpha report")]
        new = [feature("F1", "Alpha report"), feature("F2", "Alpha report")]
        merged, _, _ = self.merge(old, new)
        self.assertEqual([f["id"] for f in merged["features"]], ["F1", "F2"])

    def test_protected_tag_over_changed_source_is_flagged_for_confirmation(self):
        old = feature("F1", "Checkout", tags={**feature()["tags"],
                      "review_tier": tag("critical", "handles refunds", "confirmed")})
        new = feature("F1", "Checkout", tags={**feature()["tags"], "review_tier": tag("routine")},
                      description="Completely rewritten in v2: now a read-only order summary.")
        _, needs, _ = self.merge([old], [new])
        self.assertIn("protected_tag_over_changed_source", [n["kind"] for n in needs])


if __name__ == "__main__":
    unittest.main()
