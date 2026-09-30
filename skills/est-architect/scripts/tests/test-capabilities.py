#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Tests for capabilities.py — the map everything downstream rests on.

The claim under test is not that a map comes back. It is that the map is built from evidence
that is labelled as what it is, that it does not silently attach a capability to a story that
never mentioned it, and that the liveness test keeps settled decisions out of the tables.
"""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fixtures as F  # noqa: E402

caps = F.caps


class TheMapFindsWhatTheStoriesSay(unittest.TestCase):
    def setUp(self):
        self.model = F.model()
        self.map = caps.build_map(F.clinical(), self.model)

    def test_it_finds_the_capabilities_the_prose_describes(self):
        for cap in ("identity", "payments", "ai_inference", "email", "sms_push",
                    "analytics_store", "object_store", "async_work"):
            self.assertIn(cap, self.map, f"{cap} was never mapped")

    def test_identity_lands_on_the_identity_stories(self):
        self.assertEqual(["F1", "F2", "F3"], self.map["identity"]["stories"])

    def test_payments_does_not_leak_onto_clinical_stories(self):
        """The failure that matters: a capability attached to work that never mentioned it puts
        a box on a client-facing diagram for something nobody asked for."""
        self.assertEqual(["F9", "F10"], self.map["payments"]["stories"])

    def test_every_entry_says_how_it_got_there(self):
        for cap, entry in self.map.items():
            self.assertEqual(len(entry["stories"]), len(entry["basis"]))
            for basis in entry["basis"]:
                self.assertIn(basis["how"], ("signal", "surface", "operator",
                                             "capability_is_the_project"))
                self.assertTrue(basis["detail"], f"{cap} gave no detail for {basis['story']}")

    def test_story_order_follows_the_inventory_and_not_the_alphabet(self):
        """`sorted()` puts F10 before F9, which reorders every table a reader sees against the
        order the client's own document used."""
        ids = [f["id"] for f in F.clinical()["features"]]
        for entry in self.map.values():
            self.assertEqual([i for i in ids if i in set(entry["stories"])], entry["stories"])

    def test_a_signal_match_is_labelled_weak_rather_than_asserted(self):
        entry = self.map["payments"]
        self.assertTrue(all(b["how"] == "signal" for b in entry["basis"]))
        self.assertFalse(entry["confirmed"], "a keyword match must not start out confirmed")

    def test_the_project_capabilities_take_their_whole_surface(self):
        backend = [f["id"] for f in F.clinical()["features"] if "backend" in f["surfaces"]]
        self.assertEqual(backend, self.map["application"]["stories"])
        self.assertTrue(all(b["how"] == "capability_is_the_project"
                            for b in self.map["application"]["basis"]))

    def test_a_capability_nothing_mentions_is_absent_rather_than_empty(self):
        """An empty entry reads as 'considered and found nothing'. Absence is the honest shape,
        and it keeps the diagram from carrying a box with no stories behind it."""
        self.assertNotIn("cache", self.map)


class TheSubstringMatchIsBounded(unittest.TestCase):
    def test_ai_does_not_match_maintain_available_or_email(self):
        """A plain `in` test put model inference on eleven stories of a real backlog by matching
        `ai` inside `maintain`, `available` and `email`."""
        inv = F.inventory([F.story("F1", "Maintain availability",
                                   "The service must remain available and email the team.")])
        self.assertNotIn("ai_inference", caps.build_map(inv, F.model()))

    def test_it_still_matches_the_word_itself(self):
        inv = F.inventory([F.story("F1", "AI summary", "An AI model summarises the note.")])
        self.assertIn("ai_inference", caps.build_map(inv, F.model()))


class TheLivenessTest(unittest.TestCase):
    def setUp(self):
        self.model = F.model()
        self.map = caps.build_map(F.clinical(), self.model)

    def test_a_settled_capability_is_never_live(self):
        for cap in ("payments", "email", "sms_push"):
            live, why = caps.is_live(cap, self.map[cap], self.model)
            self.assertFalse(live, f"{cap} should be settled")
            self.assertTrue(why.startswith("settled:"))

    def test_an_arguable_capability_is_live_and_says_its_size(self):
        live, why = caps.is_live("identity", self.map["identity"], self.model)
        self.assertTrue(live)
        self.assertIn("3 stories", why)

    def test_an_immaterial_capability_is_not_live_and_names_both_thresholds(self):
        small = {"stories": ["F1"], "share_of_backlog": 0.005, "basis": []}
        live, why = caps.is_live("search", small, self.model)
        self.assertFalse(live)
        self.assertIn("not material", why)
        self.assertIn("2-story", why)

    def test_the_live_set_is_a_fraction_of_the_catalogue(self):
        """Forty-five scores nobody reads is the failure the liveness test exists to prevent.

        The claim is against the CATALOGUE, not against what happened to be mapped: a backlog
        that mentions many capabilities should still only argue about the ones worth arguing
        about. An earlier version of this test compared against the mapped count and failed a
        map that was behaving correctly — seven live decisions on a fifteen-story clinical
        platform is a readable table, and each of the seven has a real second option.
        """
        live = [c for c, e in self.map.items() if caps.is_live(c, e, self.model)[0]]
        catalogue = caps.capabilities(self.model)
        self.assertLess(len(live), len(catalogue) / 2, f"too many live: {live}")
        self.assertTrue(live, "nothing live at all is also wrong")
        settled = {c for c, s in catalogue.items() if s.get("settled")}
        self.assertFalse(settled & set(live), "a settled capability reached the scoring table")


class TheOperatorCanCorrectTheMap(unittest.TestCase):
    """The map is built by substring search and the first real run showed how badly that scales:
    `error_tracking` matched 81 of 89 stories because every feature had an "error states"
    section, `identity` matched 45, `ai_inference` 29. Without a correction path none of it
    could be scored."""

    def setUp(self):
        self.model = F.model()
        self.inventory = F.clinical()
        self.map = caps.build_map(self.inventory, self.model)

    def test_set_replaces_the_signal_matches_outright(self):
        out = caps.apply_overrides(dict(self.map),
                                   {"identity": {"set": ["F1"], "why": "only the sign-in story"}},
                                   self.inventory)
        self.assertEqual(["F1"], out["identity"]["stories"])
        self.assertTrue(out["identity"]["confirmed"])
        self.assertEqual("operator", out["identity"]["basis"][0]["how"])
        self.assertIn("only the sign-in story", out["identity"]["basis"][0]["detail"])

    def test_an_empty_set_drops_the_capability_entirely(self):
        self.assertIn("ai_inference", self.map)
        out = caps.apply_overrides(dict(self.map),
                                   {"ai_inference": {"set": [], "why": "all AI is out of scope"}},
                                   self.inventory)
        self.assertNotIn("ai_inference", out)

    def test_add_and_remove_adjust_the_signal_matches(self):
        out = caps.apply_overrides(
            dict(self.map),
            {"identity": {"remove": ["F3"], "add": ["F6"], "why": "F6 gates on the session"}},
            self.inventory)
        self.assertNotIn("F3", out["identity"]["stories"])
        self.assertIn("F6", out["identity"]["stories"])

    def test_a_story_that_does_not_exist_is_refused_rather_than_accepted(self):
        with self.assertRaises(SystemExit) as caught:
            caps.apply_overrides(dict(self.map),
                                 {"identity": {"add": ["F999"], "why": "typo"}}, self.inventory)
        self.assertIn("F999", str(caught.exception))

    def test_story_order_still_follows_the_inventory(self):
        out = caps.apply_overrides(
            dict(self.map), {"identity": {"set": ["F3", "F1", "F2"], "why": "any order"}},
            self.inventory)
        self.assertEqual(["F1", "F2", "F3"], out["identity"]["stories"])

    def test_no_overrides_leaves_the_map_untouched(self):
        self.assertEqual(self.map, caps.apply_overrides(dict(self.map), None, self.inventory))


class TheModelAndProfilesComeFromMemoryFirst(unittest.TestCase):
    """`load_model` defaulted to the shipped seed, so a company that had answered its own
    weights was scored against the shipped ones unless every caller passed --model. A run
    wrote six platform profiles into memory and nothing read them."""

    def test_the_model_records_which_file_it_loaded(self):
        model = caps.load_model()
        self.assertIn("_loaded_from", model)

    def test_an_explicit_path_still_wins(self):
        seed = F.ARCH / "assets" / "architecture-model.seed.json"
        self.assertEqual(str(seed), caps.load_model(seed)["_loaded_from"])

    def test_memory_profiles_merge_over_the_shipped_assets(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            memory = root / "_bmad" / "memory" / "est" / "platforms"
            memory.mkdir(parents=True)
            (memory / "acme.yaml").write_text(
                "id: acme\nname: Acme Cloud\nkind: iaas\nwhat: a test profile\n"
                "serves:\n  identity:\n    service: Acme Auth\n    managed: true\n"
                "    interface: standard\n    icon: lock\nruntime: {}\n"
                "pricing:\n  model: usage\n  default_url: null\n"
                "volatile:\n  regions:\n    value: null\n    checked: null\n",
                encoding="utf-8")
            (root / "work").mkdir()
            cwd = os.getcwd()
            try:
                os.chdir(root / "work")
                found = caps.load_platforms()
            finally:
                os.chdir(cwd)
        self.assertIn("acme", found, "a profile in module memory was not read")
        self.assertIn("aws", found, "memory replaced the shipped catalogue instead of adding")


class ThePlatformProfiles(unittest.TestCase):
    def setUp(self):
        self.platforms = caps.load_platforms()

    def test_the_catalogue_covers_the_whole_space_not_three_vendors(self):
        """A run scored eleven platform sets that all contained the same five vendors, because
        identity, email and error-tracking had exactly one candidate each. An architecture
        chosen from a catalogue of one is not chosen."""
        for pid in ("aws", "gcp", "azure", "vercel", "netlify", "cloudflare", "supabase",
                    "firebase", "heroku", "render", "fly", "railway", "planetscale", "neon",
                    "clerk", "auth0", "stripe", "resend", "sentry", "self-hosted"):
            self.assertIn(pid, self.platforms)

    def test_the_arguable_capabilities_have_more_than_one_candidate(self):
        for capability in ("identity", "relational_store", "object_store", "async_work",
                           "observability", "error_tracking", "email", "application"):
            serving = [p for p, profile in self.platforms.items()
                       if caps.serves_natively(profile, capability)]
            self.assertGreater(len(serving), 1,
                               f"{capability} has only {serving} — nothing to choose between")

    def test_they_stress_different_shapes(self):
        """Some platforms run long processes and some cannot. If that stops being true the
        enumeration stops producing combinations and the design is untested."""
        self.assertTrue(self.platforms["aws"]["runtime"]["long_running"])
        self.assertTrue(self.platforms["render"]["runtime"]["long_running"])
        self.assertFalse(self.platforms["vercel"]["runtime"]["long_running"])
        self.assertFalse(self.platforms["supabase"]["runtime"]["long_running"])
        self.assertFalse(self.platforms["firebase"]["runtime"]["long_running"])

    def test_a_platform_that_cannot_serve_a_capability_records_the_absence(self):
        """Firebase has no relational store. Recording that is what lets a project with a
        ledger see why it is not a candidate, instead of the capability silently going
        unserved."""
        self.assertIn("relational_store", self.platforms["firebase"]["serves"])
        self.assertFalse(caps.serves_natively(self.platforms["firebase"], "relational_store"))

    def test_a_recorded_absence_is_not_the_same_as_an_omission(self):
        self.assertIn("cache", self.platforms["supabase"]["serves"])
        self.assertFalse(caps.serves_natively(self.platforms["supabase"], "cache"))
        self.assertTrue(caps.serves_natively(self.platforms["aws"], "cache"))

    def test_every_volatile_fact_carries_a_checked_field(self):
        """A certification claim with no date is a compliance statement nobody checked."""
        for pid, profile in self.platforms.items():
            for field, entry in (profile.get("volatile") or {}).items():
                self.assertIn("checked", entry, f"{pid}.{field} has no checked date")

    def test_every_served_capability_exists_in_the_catalogue(self):
        known = set(caps.capabilities(F.model()))
        for pid, profile in self.platforms.items():
            for cap in profile.get("serves") or {}:
                self.assertIn(cap, known, f"{pid} serves unknown capability {cap}")


if __name__ == "__main__":
    unittest.main()
