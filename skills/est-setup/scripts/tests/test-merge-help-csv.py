#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# ///
"""Tests for merge-help-csv.py.

This script writes into `_bmad/_config/bmad-help.csv`, a catalog shared with every other
installed module. The failure that matters is not "our rows are missing" — that is visible.
It is "another module's rows are gone", which nobody notices until someone asks bmad-help about
a skill that has quietly stopped existing.

The last class pins the hazard the setup SKILL.md warns about: `--legacy-dir` deletes
`{dir}/core/module-help.csv`, which in this installation belongs to BMad core.
"""

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import importlib.util

SCRIPT = Path(__file__).resolve().parents[1] / "merge-help-csv.py"
_spec = importlib.util.spec_from_file_location("merge_help_csv", SCRIPT)
registrar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(registrar)
PROJECT = Path(__file__).resolve().parents[4]
SOURCE = Path(__file__).resolve().parents[2] / "assets" / "module-help.csv"

HEADER = ("module,skill,display-name,menu-code,description,action,args,phase,"
          "preceded-by,followed-by,required,output-location,outputs")
OTHER = (HEADER + "\n"
         "BMad Method,bmad-prd,Create PRD,PR,Write a PRD.,create,,anytime,,,false,out,prd.md\n"
         "Core,bmad-help,Help,HE,Find a skill.,help,,anytime,,,false,,\n")


def merge(target, source=SOURCE, extra=()):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--target", str(target), "--source", str(source), *extra],
        capture_output=True, text=True)


def rows(path):
    with Path(path).open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


class Merging(unittest.TestCase):
    def test_rows_are_added_to_an_empty_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "bmad-help.csv"
            proc = merge(target)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(len(rows(target)), 11)

    def test_other_modules_survive(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "bmad-help.csv"
            target.write_text(OTHER, encoding="utf-8")
            merge(target)
            modules = {r["module"] for r in rows(target)}
            self.assertEqual(modules, {"BMad Method", "Core", "BMad Delivery Estimator"})

    def test_a_rerun_replaces_rather_than_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "bmad-help.csv"
            target.write_text(OTHER, encoding="utf-8")
            for _ in range(3):
                merge(target)
            ours = [r for r in rows(target) if r["module"] == "BMad Delivery Estimator"]
            self.assertEqual(len(ours), 11)
            self.assertEqual(len(rows(target)), 13)

    def test_a_removed_capability_does_not_survive_a_rerun(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "bmad-help.csv"
            merge(target)
            trimmed = Path(tmp) / "trimmed.csv"
            lines = SOURCE.read_text(encoding="utf-8").splitlines()
            trimmed.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
            merge(target, source=trimmed)
            self.assertEqual(len(rows(target)), 10)

    def test_the_header_matches_the_installed_catalog(self):
        installed = PROJECT / "_bmad" / "_config" / "bmad-help.csv"
        if not installed.exists():
            self.skipTest("no installed catalog")
        with installed.open(encoding="utf-8") as a, SOURCE.open(encoding="utf-8") as b:
            self.assertEqual(a.readline().strip(), b.readline().strip())

    def test_every_row_names_a_skill_that_exists(self):
        skills = Path(__file__).resolve().parents[3]
        for row in rows(SOURCE):
            if row["skill"] in ("", "_meta"):
                continue
            self.assertTrue((skills / row["skill"] / "SKILL.md").is_file(),
                            f"{row['skill']} is registered but not installed")

    def test_the_registrar_reports_a_row_whose_skill_it_cannot_find(self):
        """The catalogue promises the thing it names can be run. This was asserted here and
        nowhere at install time, which is how a menu entry ends up pointing at a path the
        install never created."""
        header, source_rows = registrar.read_csv_rows(str(SOURCE))
        self.assertEqual(registrar.locate_skills(header, source_rows), [])
        unresolved = registrar.locate_skills(header, source_rows, skills_dir="/nowhere")
        self.assertEqual(sorted({u["skill"] for u in unresolved}),
                         ["est-agent-estimator", "est-calibrate", "est-estimate",
                          "est-scope-extract", "est-setup"])
        self.assertTrue(all(u["looked_in"] == ["/nowhere"] for u in unresolved))

    def test_the_meta_row_is_not_expected_to_be_a_skill(self):
        header, rows_ = registrar.read_csv_rows(str(SOURCE))
        self.assertNotIn("_meta", [u["skill"] for u in registrar.locate_skills(header, rows_, "/nowhere")])

    def test_menu_codes_are_unique_within_the_module(self):
        codes = [r["menu-code"] for r in rows(SOURCE) if r["menu-code"]]
        self.assertEqual(len(codes), len(set(codes)))

    def test_no_menu_code_collides_with_an_installed_module(self):
        installed = PROJECT / "_bmad" / "_config" / "bmad-help.csv"
        if not installed.exists():
            self.skipTest("no installed catalog")
        # Rows this module already installed are not a collision with another module — they
        # are this module. Without the filter the test fails the moment est is installed into
        # the repo it is developed in, which is exactly when it is least informative.
        module = {r["module"] for r in rows(SOURCE)}
        theirs = {r["menu-code"] for r in rows(installed)
                  if r["menu-code"] and r["module"] not in module}
        ours = {r["menu-code"] for r in rows(SOURCE) if r["menu-code"]}
        self.assertEqual(ours & theirs, set())


class LegacyHazard(unittest.TestCase):
    """The setup SKILL.md forbids --legacy-dir. This is why."""

    def test_legacy_dir_deletes_another_modules_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            legacy = Path(tmp) / "_bmad"
            (legacy / "core").mkdir(parents=True)
            core_csv = legacy / "core" / "module-help.csv"
            core_csv.write_text(OTHER, encoding="utf-8")
            target = legacy / "_config" / "bmad-help.csv"
            target.parent.mkdir(parents=True)
            target.write_text(OTHER, encoding="utf-8")

            merge(target, extra=["--legacy-dir", str(legacy), "--module-code", "est"])
            self.assertFalse(core_csv.exists(),
                             "if this now survives, the SKILL.md warning can be relaxed")

    def test_the_documented_invocation_leaves_it_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            legacy = Path(tmp) / "_bmad"
            (legacy / "core").mkdir(parents=True)
            core_csv = legacy / "core" / "module-help.csv"
            core_csv.write_text(OTHER, encoding="utf-8")
            target = legacy / "_config" / "bmad-help.csv"
            target.parent.mkdir(parents=True)
            target.write_text(OTHER, encoding="utf-8")

            merge(target)
            self.assertTrue(core_csv.exists())
            self.assertEqual(len(rows(target)), 13)


if __name__ == "__main__":
    unittest.main(verbosity=1)
