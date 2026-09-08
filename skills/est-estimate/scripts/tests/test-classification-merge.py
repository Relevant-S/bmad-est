#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Tests for classification-merge.py — where a human's judgement is protected now.

Before the split this rule lived in `inventory-diff.protected_tags`, because a re-extraction
could revert a tag a human had confirmed. It cannot any more; what it can still do is renumber
the story a judgement belonged to, and an orphaned judgement is the same loss in a new shape.
"""

import importlib.util
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fixtures import feature, inventory  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "classification_merge", Path(__file__).resolve().parent.parent / "classification-merge.py"
)
merge = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(merge)

DIFF = merge.matcher()


def scope(fid, name, description=None):
    f = feature(fid, name)
    f.pop("tags")
    if description:
        f["description"] = description
    return f


def classification(rows):
    return {"schema_version": "1.0", "features": rows}


def tags(value="M", status="inferred", why="because"):
    return {axis: {"value": value if axis == "size_band" else "x", "why": why, "status": status}
            for axis in ("size_band", "compressibility", "review_tier", "clarity", "novelty")}


class Rekey(unittest.TestCase):
    def remap(self, old, new, rows):
        return merge.remap(classification(rows), inventory(features=old),
                           inventory(features=new), DIFF)

    def test_a_renumbered_story_keeps_its_judgement(self):
        out, needs, orphans, unclassified, renumbered = self.remap(
            [scope("F1", "User login")], [scope("F90", "User login")], {"F1": tags("L")})
        self.assertEqual(out["features"]["F90"]["size_band"]["value"], "L")
        self.assertEqual((orphans, unclassified), ([], []))
        self.assertEqual(renumbered[0]["from"], "F1")

    def test_a_wholesale_renumber_is_counted_not_queued(self):
        """364 identical 'this moved' prompts would bury the two that need a person."""
        old = [scope(f"F{i}", f"Thing {i}") for i in range(1, 21)]
        new = [scope(f"F{i + 500}", f"Thing {i}") for i in range(1, 21)]
        _, needs, _, _, renumbered = self.remap(old, new, {f["id"]: tags() for f in old})
        self.assertEqual(len(renumbered), 20)
        self.assertEqual(needs, [])

    def test_a_human_tag_over_a_rewritten_story_is_raised_not_trusted(self):
        out, needs, _, _, _ = self.remap(
            [scope("F1", "Checkout")],
            [scope("F1", "Checkout", "Completely rewritten: now a read-only order summary.")],
            {"F1": tags("L", status="confirmed")})
        self.assertEqual([n["kind"] for n in needs], ["human_tag_over_changed_source"] * 5)
        self.assertEqual(out["features"]["F1"]["size_band"]["value"], "L",
                         "carried forward — a machine must not overwrite a person silently")

    def test_an_inferred_tag_over_a_rewritten_story_is_not_a_question(self):
        _, needs, _, _, _ = self.remap(
            [scope("F1", "Checkout")],
            [scope("F1", "Checkout", "Completely rewritten: now a read-only order summary.")],
            {"F1": tags("L")})
        self.assertEqual(needs, [])

    def test_a_judgement_with_nowhere_to_go_is_listed_never_dropped(self):
        out, _, orphans, _, _ = self.remap(
            [scope("F1", "Login"), scope("F2", "Route prediction")],
            [scope("F1", "Login")], {"F1": tags(), "F2": tags("L")})
        self.assertEqual(orphans, ["F2"])
        self.assertNotIn("F2", out["features"])

    def test_a_new_story_is_reported_as_needing_classification(self):
        _, _, _, unclassified, _ = self.remap(
            [scope("F1", "Login")], [scope("F1", "Login"), scope("F2", "Tracking page")],
            {"F1": tags()})
        self.assertEqual(unclassified, ["F2"])

    def test_it_matches_the_way_the_diff_does_rather_than_its_own_way(self):
        """Two definitions of 'the same story' that drift apart would re-key some judgements
        and orphan others, with nothing reporting the disagreement. So this imports the diff's
        matcher rather than reimplementing it, and a renamed story is still matched by name."""
        self.assertEqual(merge.matcher().__file__, DIFF.__file__)
        self.assertTrue(str(DIFF.__file__).endswith("inventory-diff.py"))
        out, _, orphans, _, renumbered = self.remap(
            [scope("F1", "User login")], [scope("F9", "User login flow")], {"F1": tags("L")})
        self.assertEqual(orphans, [])
        self.assertTrue(renumbered[0]["matched_by"].startswith("name~"))
        self.assertEqual(out["features"]["F9"]["size_band"]["value"], "L")

    def test_how_records_what_happened_to_it(self):
        out, _, _, _, _ = self.remap([scope("F1", "Login")], [scope("F1", "Login")],
                                     {"F1": tags()})
        self.assertIn("re-keyed onto a re-extraction", out["how"])


if __name__ == "__main__":
    unittest.main()
