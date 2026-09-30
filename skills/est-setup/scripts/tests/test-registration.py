#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# ///
"""Every skill on disk is registered everywhere a skill has to be registered.

A skill can be complete, tested and green and still not install, because installation is driven
by `.claude-plugin/marketplace.json` and nothing cross-checks it against the source tree. That
is exactly what happened to `est-architect`: seven skill directories, six entries in the
manifest, a full test suite passing, and a skill that simply did not appear after install.

Nothing here tests behaviour. It tests that the four places a new skill has to be named agree
with each other, so the next one cannot be half-added:

  * `.claude-plugin/marketplace.json` — what the plugin installer actually reads
  * `est-setup/assets/module-help.csv` — the capability catalogue merged into BMad's help
  * `est-setup/assets/module-outputs.yaml` — what `check-outputs.py` holds a workspace to
  * the skill's own frontmatter — the `name` Claude Code routes on
"""

import csv
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SKILLS = ROOT / "skills"
ASSETS = ROOT / "skills" / "est-setup" / "assets"

# Not a skill: the module's planning documents live beside them.
NOT_A_SKILL = {"reports"}

# est-setup installs the module rather than producing a workspace, and Nadia is an agent who
# writes into whatever workspace she is pointed at. Both are declared in module-outputs.yaml;
# neither carries a `create`-style capability row of its own beyond what is already there.
NO_WORKSPACE = set()


def skill_dirs():
    return sorted(p for p in SKILLS.iterdir()
                  if p.is_dir() and p.name not in NOT_A_SKILL and (p / "SKILL.md").exists())


def frontmatter_name(path):
    text = (path / "SKILL.md").read_text(encoding="utf-8")
    match = re.search(r"^---\n(.*?)\n---", text, re.S)
    if not match:
        return None
    found = re.search(r"^name:\s*(\S+)\s*$", match.group(1), re.M)
    return found.group(1) if found else None


def frontmatter_description(path):
    text = (path / "SKILL.md").read_text(encoding="utf-8")
    match = re.search(r"^---\n(.*?)\n---", text, re.S)
    found = re.search(r"^description:\s*(.+?)\s*$", match.group(1), re.M) if match else None
    return found.group(1) if found else None


class EverySkillIsInstallable(unittest.TestCase):
    """The bug this file exists for: a skill absent from the manifest does not install,
    however complete it is."""

    def setUp(self):
        self.manifest = json.loads(
            (ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        self.plugin = self.manifest["plugins"][0]

    def test_every_skill_directory_is_in_the_marketplace_manifest(self):
        declared = {Path(entry).name for entry in self.plugin["skills"]}
        on_disk = {p.name for p in skill_dirs()}
        self.assertEqual(on_disk, declared,
                         "a skill on disk is missing from .claude-plugin/marketplace.json and "
                         "will not install")

    def test_no_manifest_entry_points_at_a_directory_that_does_not_exist(self):
        for entry in self.plugin["skills"]:
            path = ROOT / entry.lstrip("./")
            self.assertTrue((path / "SKILL.md").exists(), f"{entry} has no SKILL.md")

    def test_the_manifest_says_how_many_skills_it_ships(self):
        """The description is what a user reads in the plugin list, and it has been wrong by
        one every time a skill was added."""
        words = {5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"}
        expected = words[len(self.plugin["skills"])]
        self.assertIn(f"Ships {expected} skills", self.plugin["description"])


class EverySkillIsRoutable(unittest.TestCase):
    def test_the_frontmatter_name_matches_the_directory(self):
        for path in skill_dirs():
            self.assertEqual(path.name, frontmatter_name(path),
                             f"{path.name}'s frontmatter name does not match its directory")

    def test_every_skill_says_when_to_use_it(self):
        """Claude Code routes on the description. One that does not say when to use the skill
        is a skill nobody reaches."""
        for path in skill_dirs():
            description = frontmatter_description(path) or ""
            self.assertTrue(description, f"{path.name} has no description")
            self.assertIn("use when", description.lower(),
                          f"{path.name}'s description never says when to use it")


class EverySkillIsDeclared(unittest.TestCase):
    def test_every_skill_has_at_least_one_capability_row(self):
        rows = list(csv.DictReader((ASSETS / "module-help.csv").read_text(encoding="utf-8")
                                   .splitlines()))
        named = {row["skill"] for row in rows}
        for path in skill_dirs():
            self.assertIn(path.name, named,
                          f"{path.name} has no row in module-help.csv, so it is invisible to "
                          f"bmad-help")

    def test_every_capability_row_points_at_a_real_skill(self):
        rows = list(csv.DictReader((ASSETS / "module-help.csv").read_text(encoding="utf-8")
                                   .splitlines()))
        on_disk = {p.name for p in skill_dirs()} | {"_meta"}
        for row in rows:
            self.assertIn(row["skill"], on_disk, f"module-help.csv names {row['skill']}")

    def test_every_row_has_exactly_the_header_s_columns(self):
        """est-plan's row shipped with fourteen fields against a thirteen-field header from the
        day it was added: its `args` contained a comma and was written unquoted, so `phase`,
        `preceded-by`, `followed-by` and everything after slid left by one. bmad-help read its
        `preceded-by` as "anytime" for months, and nothing noticed because every consumer used
        DictReader, which silently drops the overflow into a None key."""
        rows = list(csv.reader((ASSETS / "module-help.csv").read_text(encoding="utf-8")
                               .splitlines()))
        header = rows[0]
        for row in rows[1:]:
            self.assertEqual(len(header), len(row),
                             f"{row[1] if len(row) > 1 else row} has {len(row)} fields against "
                             f"{len(header)} columns — a value containing a comma was written "
                             f"unquoted")

    def test_no_row_leaks_into_an_unnamed_column(self):
        rows = list(csv.DictReader((ASSETS / "module-help.csv").read_text(encoding="utf-8")
                                   .splitlines()))
        for row in rows:
            self.assertNotIn(None, row, f"{row.get('skill')} has more fields than the header")

    def test_every_menu_code_is_unique(self):
        rows = [r for r in csv.DictReader((ASSETS / "module-help.csv")
                                          .read_text(encoding="utf-8").splitlines())
                if r["menu-code"]]
        codes = [r["menu-code"] for r in rows]
        self.assertEqual(sorted(codes), sorted(set(codes)),
                         "two capabilities share a menu code")

    def test_every_skill_declares_its_outputs(self):
        import yaml
        declared = yaml.safe_load((ASSETS / "module-outputs.yaml").read_text(encoding="utf-8"))
        for path in skill_dirs():
            self.assertIn(path.name, declared,
                          f"{path.name} declares no outputs, so check-outputs.py cannot hold a "
                          f"workspace to anything")

    def test_every_declared_skill_exists(self):
        import yaml
        declared = yaml.safe_load((ASSETS / "module-outputs.yaml").read_text(encoding="utf-8"))
        on_disk = {p.name for p in skill_dirs()}
        for name in declared:
            self.assertIn(name, on_disk, f"module-outputs.yaml declares {name}, which is gone")

    def test_the_ordering_fields_name_skills_that_exist(self):
        """`preceded-by` and `followed-by` are how bmad-help recommends the next step; a
        dangling one sends a user to a skill that is not there."""
        rows = list(csv.DictReader((ASSETS / "module-help.csv").read_text(encoding="utf-8")
                                   .splitlines()))
        on_disk = {p.name for p in skill_dirs()}
        for row in rows:
            for field in ("preceded-by", "followed-by"):
                for ref in (row.get(field) or "").split("|"):
                    if not ref.strip():
                        continue
                    self.assertIn(ref.split(":")[0], on_disk,
                                  f"{row['skill']}.{field} names {ref}")


if __name__ == "__main__":
    unittest.main()
