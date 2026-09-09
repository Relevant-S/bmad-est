#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Tests for the company-profile seed — the shape of the module's one prose input.

Four of the cost model's coefficients are a choice between variants rather than a number, and
this file is where that choice is recorded. It went unwritten because nothing said what belonged
in it: the file did not exist, and "run the interview" is not a specification. So the seed is the
specification, and these hold it to the coefficients it claims to select.
"""

import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path

SEED = Path(__file__).resolve().parents[2] / "assets" / "company-profile.seed.md"
MODEL = (Path(__file__).resolve().parents[3]
         / "est-estimate" / "assets" / "cost-model.seed.json")

TEXT = SEED.read_text(encoding="utf-8")
MODEL_JSON = json.loads(MODEL.read_text(encoding="utf-8"))


class Shape(unittest.TestCase):
    def sections(self):
        return re.findall(r"^## (.+)$", TEXT, re.M)

    def test_every_input_est_estimate_would_default_has_a_section(self):
        """These are the four `estimate.py` takes from options, plus the per-team adoption
        depth that decides whether the new-to-bmad modifier applies."""
        headings = " ".join(self.sections()).lower()
        for want in ("team shape", "adoption depth", "stack", "qa capability", "engagement"):
            self.assertIn(want, headings, f"no section covers {want}")

    def test_each_of_those_sections_is_marked_unanswered(self):
        """The marker is the state. A seeded profile is not a written one, and a file that
        looked complete on arrival would be worse than no file — it would read as decided."""
        blocks = re.split(r"^## ", TEXT, flags=re.M)[1:]
        for block in blocks:
            title = block.splitlines()[0].strip().lower()
            if any(k in title for k in ("team shape", "adoption depth", "stack",
                                        "qa capability", "engagement")):
                self.assertIn("UNANSWERED", block, f"'{title}' is not marked unanswered")

    def test_it_says_nothing_parses_it(self):
        """It is prose. Someone who believes it is config will write config into it."""
        self.assertIn("Nothing parses this", TEXT)

    def test_commercials_are_kept_out(self):
        self.assertRegex(TEXT, r"(?i)rates and commercials")


class MatchesTheModel(unittest.TestCase):
    """Every coefficient the seed quotes has to be the one the model actually holds — a
    template that teaches the wrong number is worse than one that teaches none."""

    def test_team_profile_multipliers_are_the_models_own(self):
        senior = MODEL_JSON["team_profiles"]["senior-heavy"]
        self.assertEqual((senior["spec"], senior["review"], senior["rework"]), (0.8, 0.8, 0.7))
        junior = MODEL_JSON["team_profiles"]["junior-heavy"]
        self.assertEqual((junior["spec"], junior["review"], junior["rework"]), (1.3, 1.4, 1.6))
        for value in ("0.8", "0.7", "1.3", "1.4", "1.6"):
            self.assertIn(value, TEXT)

    def test_the_qa_spread_is_the_models_own(self):
        """Read off the model rather than pinned, so the seed cannot quote a stale rate. The
        levels moved in 3.0 because the basis did: a share of delivered story hours, not of a
        manual-equivalent baseline nobody ever measured."""
        qa = MODEL_JSON["qa"]
        for key in ("web", "mobile_manual", "mobile_mcp_automated"):
            self.assertIn(f"{qa[key]['likely'] * 100:.1f}%".replace(".0%", "%"), TEXT)
        self.assertGreater(qa["mobile_manual"]["likely"], qa["web"]["likely"])
        self.assertLess(qa["mobile_mcp_automated"]["likely"], qa["mobile_manual"]["likely"])

    def test_the_architect_formula_is_the_models_own(self):
        """The best-evidenced coefficient in the file — three projects, exact fit — and the one
        a reader is most likely to want to change for their own shop."""
        arch = MODEL_JSON["architect"]
        self.assertIn("setup", TEXT.lower())
        self.assertIn(str(int(arch["weekly_cap"])), TEXT)
        self.assertRegex(TEXT, r"(?i)architect setup and support")

    def test_it_says_only_one_anchor_staffed_all_six_roles(self):
        """The fixed six-role split is a decision, and it over-states two of the three
        calibration projects. A profile that let that be assumed away would be teaching the
        estimate to invent a QA line."""
        self.assertRegex(TEXT, r"(?i)no QA and no DevOps")
        self.assertRegex(TEXT, r"(?i)report hours nobody will book")

    def test_the_overhead_rates_are_the_models_own(self):
        rates = MODEL_JSON["overhead_rate"]
        self.assertEqual(rates["low_touch"]["likely"], 2.0)
        self.assertEqual(rates["standard"]["likely"], 3.5)
        self.assertIn("hours per person per week", TEXT)

    def test_the_new_to_bmad_modifier_is_the_models_own(self):
        mod = MODEL_JSON["team_profiles"]["new-to-bmad"]
        self.assertEqual((mod["spec"], mod["review"], mod["rework"]), (1.2, 1.2, 1.5))
        self.assertIn("new-to-bmad", TEXT)
        self.assertIn("decay", TEXT.lower())

    def test_the_stack_gated_standing_work_is_the_models_own(self):
        items = MODEL_JSON["standing_work"]["items"]
        gated = {k: v for k, v in items.items()
                 if isinstance(v, dict) and v.get("stacks") not in (None, "all")}
        self.assertEqual(sorted(gated), ["mobile_release", "service_integration_env"])
        for spec in gated.values():
            self.assertIn(str(int(spec["hours"]["likely"])), TEXT)

    def test_the_roles_match_the_configured_split(self):
        module_yaml = (Path(__file__).resolve().parents[3]
                       / "est-setup" / "assets" / "module.yaml").read_text(encoding="utf-8")
        self.assertIn("architect,dev,devops,qa,ba,ux", module_yaml)
        for role in ("architect", "dev", "devops", "qa", "ba", "ux"):
            self.assertIn(role, TEXT)


class Wiring(unittest.TestCase):
    def test_setup_seeds_it_and_says_a_seeded_profile_is_not_a_written_one(self):
        skill = (Path(__file__).resolve().parents[3]
                 / "est-setup" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("company-profile.seed.md", skill)
        self.assertIn("a seeded profile is not a written one", skill)

    def test_the_readers_know_an_unanswered_section_is_not_an_answer(self):
        for path in ("est-estimate/SKILL.md", "est-agent-estimator/SKILL.md"):
            text = (Path(__file__).resolve().parents[3] / path).read_text(encoding="utf-8")
            self.assertIn("UNANSWERED", text, path)

    def test_it_is_a_declared_output(self):
        manifest = (Path(__file__).resolve().parents[3]
                    / "est-setup" / "assets" / "module-outputs.yaml").read_text(encoding="utf-8")
        self.assertIn("{memory}/company-profile.md", manifest)


if __name__ == "__main__":
    unittest.main()
