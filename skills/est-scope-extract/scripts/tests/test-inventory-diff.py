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
    def test_detects_commitment_change(self):
        new = feature(commitment="speculative")
        self.assertIn("commitment", [c["field"] for c in diff.compare(feature(), new)])

    def test_detects_dependency_changes(self):
        new = feature(depends_on=[{"feature_id": "F2", "inferred": True}])
        change = next(c for c in diff.compare(feature(), new) if c["field"] == "depends_on")
        self.assertEqual(change["added"], ["F2"])

    def test_identical_features_report_no_changes(self):
        self.assertEqual(diff.compare(feature(), feature()), [])


class TestMerge(unittest.TestCase):
    """The merge is deterministic; only what a human must decide comes back as a question."""

    def merge(self, old_features, new_features):
        old, new = inventory(features=old_features), inventory(features=new_features)
        pairs, added, removed = diff.match_features(old["features"], new["features"])
        return diff.build_merge(old, new, pairs, added, removed)

    def merged(self, old_features, new_features):
        return self.merge(old_features, new_features)[0]

    def test_stable_feature_ids_survive_renumbering(self):
        merged = self.merged([feature("F1", "User login")], [feature("F90", "User login")])
        self.assertEqual([f["id"] for f in merged["features"]], ["F1"])

    def test_new_feature_gets_an_id_that_collides_with_nothing(self):
        merged = self.merged([feature("F1", "User login"), feature("F2", "Export")],
                             [feature("F1", "User login"), feature("F9", "Tracking page")])
        ids = [f["id"] for f in merged["features"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertNotIn("F2", ids[1:])

    def test_removed_feature_is_raised_as_a_decision_not_dropped_silently(self):
        _, needs = self.merge([feature("F1", "Login"), feature("F2", "Route prediction")],
                              [feature("F1", "Login")])
        self.assertEqual([n["kind"] for n in needs], ["feature_absent_from_new_sources"])
        self.assertEqual(needs[0]["feature"], "F2")

    def test_dependencies_are_remapped_to_the_stable_ids(self):
        old = [feature("F1", "User login"), feature("F2", "User profile page")]
        new = [feature("F80", "User login"),
               feature("F81", "User profile page", depends_on=[{"feature_id": "F80", "inferred": True}])]
        merged = self.merged(old, new)
        self.assertEqual(merged["features"][1]["depends_on"][0]["feature_id"], "F1")

    def test_identical_features_are_not_confused_for_one_another(self):
        old = [feature("F1", "Alpha report"), feature("F2", "Alpha report")]
        new = [feature("F1", "Alpha report"), feature("F2", "Alpha report")]
        merged = self.merged(old, new)
        self.assertEqual([f["id"] for f in merged["features"]], ["F1", "F2"])

    def test_stable_ids_are_what_stops_a_re_extraction_orphaning_a_judgement(self):
        """The merge no longer carries tags — it carries ids. That is now the whole protection:
        classification.json keys onto feature ids, so a renumber that the merge undoes is a
        renumber that never reaches the judgements."""
        def scope(fid, name):                      # what an inventory holds after the split
            f = feature(fid, name)
            del f["tags"]
            return f

        merged, needs = self.merge([scope("F1", "Checkout"), scope("F2", "Refunds")],
                                   [scope("F70", "Checkout"), scope("F71", "Refunds")])
        self.assertEqual([f["id"] for f in merged["features"]], ["F1", "F2"])
        self.assertNotIn("tags", merged["features"][0])
        self.assertEqual(needs, [], "a renumber alone is not a question for a human")


if __name__ == "__main__":
    unittest.main()
