#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Tests for profile-scaffold.py — adding a researched solution to the catalogue.

The catalogue that ships is a starting point, not a boundary. What matters is that a researched
profile is held to the SAME standard as a shipped one: it cannot claim a certification it
cannot cite, cannot serve a capability nobody has defined, and cannot host an application
without saying what its runtime can do.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fixtures as F  # noqa: E402

scaffold = F.load("profile_scaffold", F.ARCH / "scripts" / "profile-scaffold.py")


def researched(**over):
    spec = {
        "id": "upstash", "name": "Upstash", "kind": "saas",
        "what": "Serverless Redis billed per request. Single-capability, so it appears beside "
                "a host.",
        "serves": {"cache": {"service": "Upstash Redis", "managed": True,
                             "interface": "standard",
                             "interface_why": "Redis protocol; a move is a connection string."}},
        "pricing": {"model": "per_request", "default_url": "https://upstash.com/pricing"},
        "researched_on": "2026-09-29", "sources": ["https://upstash.com/pricing"],
    }
    spec.update(over)
    return spec


class AResearchedProfileIsACatalogueProfile(unittest.TestCase):
    def test_a_complete_description_scaffolds_cleanly(self):
        profile, problems = scaffold.scaffold(researched(), F.model())
        self.assertEqual([], problems)
        self.assertEqual("upstash", profile["id"])
        self.assertEqual("Upstash Redis", profile["serves"]["cache"]["service"])

    def test_it_records_that_it_was_researched_and_where_from(self):
        profile, _ = scaffold.scaffold(researched(), F.model())
        self.assertEqual("2026-09-29", profile["researched"]["on"])
        self.assertEqual(["https://upstash.com/pricing"], profile["researched"]["sources"])

    def test_an_icon_is_not_required(self):
        """Icons are resolved from the vendors' own catalogues at render time, so a researched
        profile names a service and the artwork follows."""
        profile, problems = scaffold.scaffold(researched(), F.model())
        self.assertEqual([], problems)
        self.assertNotIn("icon", profile["serves"]["cache"])

    def test_every_shipped_profile_passes_the_same_check(self):
        """A researched profile is held to the module's standard, not a lower one — and the
        shipped catalogue has to meet it too, or the standard is decorative."""
        findings = scaffold.check(F.ARCH / "assets" / "platforms", F.model())
        self.assertEqual([], findings)


class ItRefusesWhatItCannotSource(unittest.TestCase):
    def test_a_certification_with_no_date_and_url_is_refused(self):
        _, problems = scaffold.scaffold(
            researched(volatile={"certifications": {"value": "SOC 2 Type 2"}}), F.model())
        self.assertTrue(any("compliance statement nobody checked" in p for p in problems))

    def test_a_cited_and_dated_certification_is_kept(self):
        profile, problems = scaffold.scaffold(
            researched(volatile={"certifications": {
                "value": "SOC 2 Type 2", "checked": "2026-09-29",
                "url": "https://upstash.com/trust"}}), F.model())
        self.assertEqual([], problems)
        self.assertEqual("SOC 2 Type 2", profile["volatile"]["certifications"]["value"])

    def test_an_unverified_field_says_it_is_not_evidence_of_absence(self):
        profile, _ = scaffold.scaffold(researched(), F.model())
        note = profile["volatile"]["certifications"]["note"]
        self.assertIn("NOT evidence of absence", note)
        self.assertIsNone(profile["volatile"]["certifications"]["checked"])

    def test_a_capability_nobody_has_defined_is_refused(self):
        _, problems = scaffold.scaffold(
            researched(serves={"blockchain": {"service": "X", "interface": "standard"}}),
            F.model())
        self.assertTrue(any("not in the capability catalogue" in p for p in problems))

    def test_an_unclassified_interface_is_refused(self):
        """It drives the reversibility sub-score; a missing one would score as proprietary by
        accident."""
        _, problems = scaffold.scaffold(
            researched(serves={"cache": {"service": "Upstash Redis"}}), F.model())
        self.assertTrue(any("reversibility" in p for p in problems))

    def test_a_profile_serving_nothing_is_refused(self):
        _, problems = scaffold.scaffold(researched(serves={}), F.model())
        self.assertTrue(any("serves nothing" in p for p in problems))

    def test_a_host_must_state_what_its_runtime_can_do(self):
        """An unstated runtime capability is treated as absent, so an unresearched field makes
        the platform lose unfairly."""
        _, problems = scaffold.scaffold(
            researched(serves={"application": {"service": "Upstash Functions",
                                               "interface": "proprietary"}}), F.model())
        self.assertTrue(any("long_running" in p for p in problems))

    def test_a_host_that_states_its_runtime_is_accepted(self):
        profile, problems = scaffold.scaffold(
            researched(serves={"application": {"service": "Upstash Functions",
                                               "interface": "proprietary"}},
                       runtime={"long_running": False, "background_jobs": True,
                                "websockets": False,
                                "long_running_why": "request-scoped handlers"}), F.model())
        self.assertEqual([], problems)
        self.assertIn("long_running_why", profile["runtime"])


class ARecordedAbsenceIsKept(unittest.TestCase):
    def test_a_capability_the_platform_does_not_serve_is_written_down(self):
        """'This platform has no managed cache' is a fact worth keeping, and it is not the same
        as the capability being missing from the file."""
        profile, problems = scaffold.scaffold(
            researched(serves={"cache": {"service": "Upstash Redis", "interface": "standard"},
                               "relational_store": {"serves_natively": False,
                                                    "note": "No relational tier."}}),
            F.model())
        self.assertEqual([], problems)
        self.assertIn("relational_store", profile["serves"])
        self.assertFalse(profile["serves"]["relational_store"]["serves_natively"])
        self.assertIsNone(profile["serves"]["relational_store"]["service"])


class ItLandsWhereTheScoringLooks(unittest.TestCase):
    def test_a_written_profile_is_loaded_and_merges_over_the_shipped_catalogue(self):
        import os
        import tempfile
        import yaml
        profile, _ = scaffold.scaffold(researched(), F.model())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            memory = root / "_bmad" / "memory" / "est" / "platforms"
            memory.mkdir(parents=True)
            (memory / "upstash.yaml").write_text(
                yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")
            (root / "work").mkdir()
            cwd = os.getcwd()
            try:
                os.chdir(root / "work")
                found = F.caps.load_platforms()
            finally:
                os.chdir(cwd)
        self.assertIn("upstash", found)
        self.assertIn("aws", found, "the shipped catalogue was replaced instead of extended")
        self.assertTrue(F.caps.serves_natively(found["upstash"], "cache"))


if __name__ == "__main__":
    unittest.main()
