#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""Tests for merge-config.py.

Run with `uv run --python 3.11 --with pyyaml python test-merge-config.py` — both this file
and the script under test need tomllib, the same 3.11 requirement BMad's own
resolve_config.py carries.

The stock template writes YAML into a file this BMad installation does not read, so the whole
point of this script is that what it writes comes back out of BMad's own resolver. The cases
that matter are the ones where a write looks successful and is not: a value that lands in an
unparseable file, a rerun that leaves two copies for the resolver to choose between, and a
comment a human wrote that a rerun quietly deletes.
"""

import json
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "est-setup" / "scripts" / "merge-config.py"
MODULE_YAML = ROOT / "est-setup" / "assets" / "module.yaml"

CUSTOM_SEED = """# Team / enterprise overrides for _bmad/config.toml.
# Committed to the repo.
#
# [agents.bmad-agent-pm]
# description = "Prefers short PRDs."
"""


def run(tmp, answers, custom=None, user=None):
    tmp = Path(tmp)
    (tmp / "answers.json").write_text(json.dumps({"module": answers}), encoding="utf-8")
    custom = custom or tmp / "config.toml"
    user = user or tmp / "config.user.toml"
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--module-yaml", str(MODULE_YAML),
         "--answers", str(tmp / "answers.json"),
         "--custom-config", str(custom), "--custom-user-config", str(user)],
        capture_output=True, text=True)
    return proc.returncode, json.loads(proc.stdout or "{}"), custom


def table(path):
    return (tomllib.loads(Path(path).read_text(encoding="utf-8")).get("modules") or {}).get("est")


class Writing(unittest.TestCase):
    def test_defaults_are_written_when_nothing_is_answered(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, result, custom = run(tmp, {})
            self.assertEqual(code, 0, result)
            values = table(custom)
            self.assertEqual(values["est_default_fidelity"], "presale")
            self.assertEqual(len(values), 10)

    def test_an_answer_overrides_its_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, custom = run(tmp, {"est_default_fidelity": "delivery"})
            self.assertEqual(table(custom)["est_default_fidelity"], "delivery")

    def test_types_survive_the_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, custom = run(tmp, {"est_min_calibration_samples": 5,
                                     "est_show_manual_baseline": True,
                                     "est_output_formats": ["md", "html"]})
            values = table(custom)
            self.assertIsInstance(values["est_min_calibration_samples"], int)
            self.assertIs(values["est_show_manual_baseline"], True)
            self.assertEqual(values["est_output_formats"], ["md", "html"])

    def test_a_project_root_token_is_written_literally(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, custom = run(tmp, {})
            self.assertTrue(table(custom)["est_output_folder"].startswith("{project-root}/"))

    def test_the_file_is_created_with_a_header_when_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, custom = run(tmp, {})
            self.assertIn("Team / enterprise overrides", Path(custom).read_text())


class ResultTemplate(unittest.TestCase):
    """`result` is a documented module.yaml feature; untested code is code that stops working."""

    def custom_module(self, tmp, spec):
        path = Path(tmp) / "module.yaml"
        path.write_text("code: est\nname: T\n" + spec, encoding="utf-8")
        return path

    def merge(self, tmp, module_yaml, answers):
        (Path(tmp) / "answers.json").write_text(json.dumps({"module": answers}), encoding="utf-8")
        custom = Path(tmp) / "config.toml"
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--module-yaml", str(module_yaml),
             "--answers", str(Path(tmp) / "answers.json"), "--custom-config", str(custom),
             "--custom-user-config", str(Path(tmp) / "u.toml")],
            capture_output=True, text=True)
        return proc.returncode, custom

    def test_a_result_template_transforms_the_answer(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = 'est_docs:\n  prompt: "Where?"\n  default: "docs"\n  result: "{project-root}/{value}"\n'
            code, custom = self.merge(tmp, self.custom_module(tmp, spec), {"est_docs": "notes"})
            self.assertEqual(code, 0)
            self.assertEqual(table(custom)["est_docs"], "{project-root}/notes")

    def test_a_variable_without_a_result_is_written_verbatim(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = 'est_docs:\n  prompt: "Where?"\n  default: "docs"\n'
            _, custom = self.merge(tmp, self.custom_module(tmp, spec), {"est_docs": "notes"})
            self.assertEqual(table(custom)["est_docs"], "notes")

    def test_a_user_setting_goes_to_the_gitignored_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = ('est_shared:\n  prompt: "S"\n  default: "a"\n'
                    'est_mine:\n  prompt: "M"\n  default: "b"\n  user_setting: true\n')
            self.merge(tmp, self.custom_module(tmp, spec), {})
            shared = tomllib.loads((Path(tmp) / "config.toml").read_text())["modules"]["est"]
            personal = tomllib.loads((Path(tmp) / "u.toml").read_text())["modules"]["est"]
            self.assertEqual(sorted(shared), ["est_shared"])
            self.assertEqual(sorted(personal), ["est_mine"])


class Rerunning(unittest.TestCase):
    def seeded(self, tmp):
        custom = Path(tmp) / "config.toml"
        custom.write_text(CUSTOM_SEED, encoding="utf-8")
        return custom

    def test_a_rerun_leaves_exactly_one_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            custom = self.seeded(tmp)
            for _ in range(3):
                run(tmp, {"est_default_fidelity": "quick"}, custom=custom)
            self.assertEqual(custom.read_text().count("[modules.est]"), 1)
            self.assertEqual(table(custom)["est_default_fidelity"], "quick")

    def test_a_rerun_does_not_accumulate_its_own_comment(self):
        with tempfile.TemporaryDirectory() as tmp:
            custom = self.seeded(tmp)
            for _ in range(4):
                run(tmp, {}, custom=custom)
            self.assertEqual(custom.read_text().count("written by est-setup"), 1)

    def test_a_removed_answer_reverts_to_the_default_rather_than_persisting(self):
        """Anti-zombie: the old value must not survive underneath the new table."""
        with tempfile.TemporaryDirectory() as tmp:
            custom = self.seeded(tmp)
            run(tmp, {"est_sprint_length_days": 20}, custom=custom)
            run(tmp, {}, custom=custom)
            self.assertEqual(table(custom)["est_sprint_length_days"], 10)

    def test_pre_existing_content_survives(self):
        with tempfile.TemporaryDirectory() as tmp:
            custom = self.seeded(tmp)
            run(tmp, {}, custom=custom)
            text = custom.read_text()
            self.assertIn("Team / enterprise overrides", text)
            self.assertIn("bmad-agent-pm", text)

    def test_another_modules_table_is_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            custom = Path(tmp) / "config.toml"
            custom.write_text(CUSTOM_SEED + '\n[modules.bmm]\nproject_knowledge = "docs"\n',
                              encoding="utf-8")
            run(tmp, {}, custom=custom)
            parsed = tomllib.loads(custom.read_text())
            self.assertEqual(parsed["modules"]["bmm"]["project_knowledge"], "docs")
            self.assertIn("est", parsed["modules"])

    def test_a_human_comment_above_the_table_is_never_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            custom = self.seeded(tmp)
            run(tmp, {}, custom=custom)
            custom.write_text(custom.read_text().replace(
                "[modules.est]", "# Ostap: 10 days because our clients demo fortnightly.\n[modules.est]"))
            run(tmp, {}, custom=custom)
            run(tmp, {}, custom=custom)
            text = custom.read_text()
            self.assertIn("Ostap: 10 days", text)
            self.assertEqual(text.count("written by est-setup"), 1)


class Refusals(unittest.TestCase):
    def test_an_unresolved_project_root_in_a_path_argument_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "answers.json").write_text('{"module": {}}', encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), "--module-yaml", str(MODULE_YAML),
                 "--answers", str(Path(tmp) / "answers.json"),
                 "--custom-config", "{project-root}/_bmad/custom/config.toml",
                 "--custom-user-config", str(Path(tmp) / "u.toml")],
                capture_output=True, text=True)
            self.assertEqual(proc.returncode, 1)
            self.assertIn("literal token", proc.stdout)

    def test_an_answer_for_an_undeclared_setting_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, result, _ = run(tmp, {"est_daily_rate": 90})
            self.assertEqual(code, 1)
            self.assertIn("est_daily_rate", result["message"])

    def test_nothing_is_written_when_an_answer_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            custom = Path(tmp) / "config.toml"
            run(tmp, {"est_daily_rate": 90}, custom=custom)
            self.assertFalse(custom.exists())


class ReadBack(unittest.TestCase):
    """The whole point: BMad's own resolver must see what was written."""

    def test_the_installed_resolver_reads_the_values_back(self):
        resolver = Path("/Users/Ostap/Projects/bmad-estimation/_bmad/scripts/resolve_config.py")
        if not resolver.exists():
            self.skipTest("resolver not present")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "_bmad" / "custom").mkdir(parents=True)
            (root / "_bmad" / "scripts").mkdir(parents=True)
            for name in ("resolve_config.py", "config_utils.py"):
                (root / "_bmad" / "scripts" / name).write_text(
                    (resolver.parent / name).read_text(encoding="utf-8"), encoding="utf-8")
            (root / "_bmad" / "config.toml").write_text('[core]\nproject_name = "t"\n',
                                                        encoding="utf-8")
            run(tmp, {"est_default_fidelity": "delivery"},
                custom=root / "_bmad" / "custom" / "config.toml",
                user=root / "_bmad" / "custom" / "config.user.toml")
            proc = subprocess.run(
                [sys.executable, str(root / "_bmad" / "scripts" / "resolve_config.py"),
                 "-p", str(root), "-k", "modules.est.est_default_fidelity"],
                capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(json.loads(proc.stdout)["modules.est.est_default_fidelity"], "delivery")


if __name__ == "__main__":
    unittest.main(verbosity=1)
