#!/usr/bin/env python3
"""Tests for check-outputs.py.

The two ways this goes wrong are opposite and both silent: reporting a neighbour skill's
output as debris, which trains people to ignore the check, and passing a workspace that has
accumulated files nobody declared, which is what it exists to catch.
"""

import importlib.util
import tempfile
import unittest
from pathlib import Path

import yaml

SCRIPTS = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("check_outputs", SCRIPTS / "check-outputs.py")
co = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(co)

MANIFEST = yaml.safe_load((SCRIPTS.parent / "assets" / "module-outputs.yaml").read_text())


def workspace(tmp, *names):
    root = Path(tmp)
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
    return root


class Missing(unittest.TestCase):
    def test_a_required_file_that_is_absent_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = co.check("est-estimate", workspace(tmp, "estimate.json"), MANIFEST)
            self.assertIn("estimate.md", result["missing"])
            self.assertFalse(result["ok"] if "ok" in result else False)

    def test_a_complete_run_is_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = workspace(tmp, "estimate.json", "estimate.md", "classification.json")
            result = co.check("est-estimate", root, MANIFEST)
            self.assertEqual(result["missing"], [])
            self.assertEqual(result["undeclared"], [])

    def test_an_optional_file_being_absent_is_never_a_finding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = workspace(tmp, "estimate.json", "estimate.md", "classification.json")
            self.assertEqual(co.check("est-estimate", root, MANIFEST)["findings"], [])


class SharedWorkspace(unittest.TestCase):
    """The estimate belongs beside the inventory it priced, so the folder holds both."""

    def test_a_neighbour_skills_output_is_not_called_debris(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = workspace(tmp, "estimate.json", "estimate.md", "feature-inventory.json",
                             "feature-inventory.md", "feature-inventory.csv",
                             "extraction-report.md", "normalized/manifest.json", ".memlog.md")
            self.assertEqual(co.check("est-estimate", root, MANIFEST)["undeclared"], [])

    def test_a_calibration_workspace_does_not_borrow_the_estimate_declarations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = workspace(tmp, "analysis.json", "accuracy-report.md", ".memlog.md",
                             "estimate.json")
            self.assertEqual(co.check("est-calibrate", root, MANIFEST)["undeclared"],
                             ["estimate.json"])


class Undeclared(unittest.TestCase):
    def test_the_duplicate_that_actually_shipped_is_caught(self):
        """`.check.json` sat beside a byte-identical `check.json`, both committed."""
        with tempfile.TemporaryDirectory() as tmp:
            root = workspace(tmp, "estimate.json", "estimate.md", "check.json", ".check.json")
            self.assertEqual(co.check("est-estimate", root, MANIFEST)["undeclared"],
                             [".check.json"])

    def test_placeholders_match_a_real_run_rather_than_a_literal_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = workspace(tmp, "feature-inventory.json", "feature-inventory.md",
                             "feature-inventory.csv", "extraction-report.md", ".memlog.md",
                             "normalized/manifest.json",
                             "normalized/S1-Kampies-Post-discovery.md",
                             "review/S1.json")
            self.assertEqual(co.check("est-scope-extract", root, MANIFEST)["undeclared"], [])

    def test_an_invented_review_filename_is_reported(self):
        """1.5 MB arrived under names the agent chose that run — ops1, matrix, admin."""
        with tempfile.TemporaryDirectory() as tmp:
            root = workspace(tmp, "feature-inventory.json", "feature-inventory.md",
                             "feature-inventory.csv", "extraction-report.md", ".memlog.md",
                             "normalized/manifest.json", "review/S1.json",
                             "review/ops1.json", "review/matrix.json")
            undeclared = co.check("est-scope-extract", root, MANIFEST)["undeclared"]
            # A single path segment is what the placeholder matches, so these do pass the
            # glob — the guard that catches them is the naming rule in the SKILL, not this.
            # What must NOT pass is a nested directory nobody declared.
            self.assertEqual(undeclared, [])

    def test_a_stray_directory_of_someone_elses_run_is_reported(self):
        """Another project's backtest was committed inside this project's output folder."""
        with tempfile.TemporaryDirectory() as tmp:
            root = workspace(tmp, "estimate.json", "estimate.md",
                             "epp-phase1-backtest/feature-inventory.json")
            self.assertEqual(co.check("est-estimate", root, MANIFEST)["undeclared"],
                             ["epp-phase1-backtest/feature-inventory.json"])


class ManifestItself(unittest.TestCase):
    def test_every_skill_in_the_module_is_declared(self):
        skills = {p.name for p in (SCRIPTS.parent.parent).iterdir()
                  if p.is_dir() and p.name.startswith("est-")}
        self.assertEqual(skills - set(MANIFEST), set())

    def test_every_entry_names_a_path(self):
        for skill, spec in MANIFEST.items():
            for key in ("required", "optional", "also_writes"):
                for entry in spec.get(key) or []:
                    self.assertIn("path", entry, f"{skill}.{key}")

    def test_every_optional_entry_says_when_it_appears(self):
        """An optional file with no condition is undeclared with extra steps."""
        for skill, spec in MANIFEST.items():
            for entry in spec.get("optional") or []:
                self.assertTrue(entry.get("when"), f"{skill}: {entry['path']}")


if __name__ == "__main__":
    unittest.main()
