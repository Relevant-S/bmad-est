#!/usr/bin/env python3
"""Tests for anchor-project.py.

The failure that matters here is silent under-counting. A story dropped because its Status
line carried a trailing comment shrinks the delivered scope the whole calibration is anchored
on — and it shrinks it in the direction that makes the model look more accurate than it is.
"""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("anchor", SCRIPTS / "anchor-project.py")
anchor = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(anchor)

EPICS = """# Epic Breakdown

## Epic 1: Foundation
### Story 1.1: Monorepo scaffold
### Story 1.2: Design system
## Epic 2: Events
### Story 2.1: Create an event
"""


def project(tmp, stories=None, epics=EPICS, subdir="_bmad-output/planning-artifacts"):
    root = Path(tmp)
    plan = root / subdir
    plan.mkdir(parents=True, exist_ok=True)
    (plan / "epics.md").write_text(epics, encoding="utf-8")
    impl = root / "_bmad-output" / "implementation-artifacts" / "phase-1"
    impl.mkdir(parents=True, exist_ok=True)
    for name, body in (stories or {}).items():
        (impl / name).write_text(body, encoding="utf-8")
    return root


def story(number, name, status="done", tasks=0):
    body = f"# Story {number}: {name}\n\nStatus: {status}\n"
    for i in range(tasks):
        body += f"\n### Task {i+1} — something\n"
    return body


class Shape(unittest.TestCase):
    def run_on(self, root, **kw):
        epics, stories, _ = anchor.read_epics(root)
        anchor.read_story_files(root, stories)
        keep = anchor.parse_range(kw.get("epics"))
        status = kw.get("status", "done")
        return [s for s in stories.values()
                if (keep is None or s["epic"] in keep)
                and (status == "any" or (s["status"] or "") == status)]

    def test_it_finds_the_delivered_stories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = project(tmp, {
                "1-1-monorepo-scaffold.md": story("1.1", "Monorepo scaffold", tasks=3),
                "1-2-design-system.md": story("1.2", "Design system"),
                "2-1-create-an-event.md": story("2.1", "Create an event"),
            })
            self.assertEqual(len(self.run_on(root)), 3)

    def test_a_status_with_a_trailing_comment_still_counts_as_delivered(self):
        """Real story files carry 'Status: done  <!-- reviewed -->' and 'Status: done (AC1
        deferred)'. Dropping those understates what shipped."""
        with tempfile.TemporaryDirectory() as tmp:
            root = project(tmp, {
                "1-1-a.md": "# Story 1.1: A\n\nStatus: done  <!-- code-reviewed 2026-08-08 -->\n",
                "1-2-b.md": "# Story 1.2: B\n\nStatus: done (AC1 BLOCKED, see deferred-work.md)\n",
            })
            self.assertEqual(len(self.run_on(root)), 2)

    def test_work_still_in_review_is_not_counted_as_delivered(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = project(tmp, {
                "1-1-a.md": story("1.1", "A"),
                "1-2-b.md": story("1.2", "B", status="review"),
            })
            self.assertEqual(len(self.run_on(root)), 1)
            self.assertEqual(len(self.run_on(root, status="any")), 3)   # 2.1 has no file

    def test_epics_can_be_restricted_to_the_phase_that_shipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = project(tmp, {
                "1-1-a.md": story("1.1", "A"),
                "2-1-b.md": story("2.1", "B"),
            })
            self.assertEqual([s["number"] for s in self.run_on(root, epics="1")], ["1.1"])

    def test_superseded_and_template_plans_are_ignored(self):
        """A re-planned epic list describes scope nobody delivered; anchoring on it inflates
        the shape the calibration divides real hours across."""
        with tempfile.TemporaryDirectory() as tmp:
            root = project(tmp, {"1-1-a.md": story("1.1", "A")})
            old = root / "_bmad-output" / "planning-artifacts" / "superseded"
            old.mkdir(parents=True)
            (old / "epics-v1.md").write_text(
                "## Epic 9: Abandoned\n### Story 9.1: Never built\n", encoding="utf-8")
            (root / "_bmad-output" / "planning-artifacts" / "epics-template.md").write_text(
                "## Epic 8: {{name}}\n### Story 8.1: {{story}}\n", encoding="utf-8")
            epics, stories, files = anchor.read_epics(root)
            self.assertNotIn("9", epics)
            self.assertNotIn("8", epics)
            self.assertEqual(len(files), 1)


class Skeleton(unittest.TestCase):
    def build(self, tmp):
        root = project(tmp, {"1-1-a.md": story("1.1", "Monorepo scaffold", tasks=2),
                             "2-1-b.md": story("2.1", "Create an event")})
        epics, stories, _ = anchor.read_epics(root)
        anchor.read_story_files(root, stories)
        selected = [s for s in stories.values() if (s["status"] or "") == "done"]
        return anchor.skeleton("Test", epics, selected)

    def test_no_tag_is_guessed(self):
        """A script that invented size bands would be manufacturing the evidence the
        calibration is supposed to weigh."""
        with tempfile.TemporaryDirectory() as tmp:
            for f in self.build(tmp)["features"]:
                for axis, tag in f["tags"].items():
                    self.assertIsNone(tag["value"], axis)
                    self.assertEqual(tag["status"], "unclassified")

    def test_every_story_keeps_a_pointer_back_to_its_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            for f in self.build(tmp)["features"]:
                self.assertTrue(f["citations"][0]["location"])

    def test_epics_carry_through_so_planning_is_not_re_derived(self):
        with tempfile.TemporaryDirectory() as tmp:
            skel = self.build(tmp)
            self.assertEqual({e["id"] for e in skel["epics"]}, {"E1", "E2"})
            self.assertEqual({f["epic_id"] for f in skel["features"]}, {"E1", "E2"})

    def test_it_says_out_loud_that_this_is_not_an_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(any("delivered project" in a
                                for a in self.build(tmp)["assumptions"]))


class Ranges(unittest.TestCase):
    def test_parses_the_forms_people_actually_type(self):
        self.assertEqual(anchor.parse_range("1-3"), {"1", "2", "3"})
        self.assertEqual(anchor.parse_range("1,5"), {"1", "5"})
        self.assertEqual(anchor.parse_range("1-2,7"), {"1", "2", "7"})
        self.assertIsNone(anchor.parse_range(None))


class Refusals(unittest.TestCase):
    def test_an_empty_project_explains_what_it_looked_for(self):
        with tempfile.TemporaryDirectory() as tmp:
            import subprocess
            import sys
            proc = subprocess.run([sys.executable, str(SCRIPTS / "anchor-project.py"), tmp],
                                  capture_output=True, text=True)
            self.assertEqual(proc.returncode, 1)
            self.assertIn("--status any", json.loads(proc.stdout)["error"])


if __name__ == "__main__":
    unittest.main()
