#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Tests for icons.py — resolving the official icon for any service, on demand.

The network is stubbed throughout: a suite that depends on four external APIs fails for
reasons that have nothing to do with the code. What is tested is the judgement — the aliasing,
the ranking, the floor under a match and the fallback — because every bad icon this resolver
produced came from that layer, not from the fetching.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fixtures as F  # noqa: E402

icons = F.load("icons", F.ARCH / "scripts" / "icons.py")
caps = F.caps

SQUARE = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256"><path d="M0 0"/></svg>'
WIDE = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 99"><path d="M0 0"/></svg>'
# Stripe's real proportions: a lockup, but a legible one.
LOCKUP = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 239 100"><path d="M0 0"/></svg>'
COLOURED = (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">'
            b'<path fill="#37814a" d="M0 0"/></svg>')
MONO = (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">'
        b'<path fill="currentColor" d="M0 0"/></svg>')


class Stub:
    """Stands in for the three icon APIs. Records what was asked for."""

    def __init__(self, iconify=(), svgl=(), svgs=None):
        self.iconify, self.svgl = list(iconify), list(svgl)
        self.svgs, self.asked = svgs or {}, []

    def __call__(self, url, timeout=20):
        self.asked.append(url)
        if "api.iconify.design/search" in url:
            return json.dumps({"icons": self.iconify}).encode()
        if "api.svgl.app" in url:
            return json.dumps([{"title": t, "route": {"light": f"https://svgl/{t}.svg"}}
                               for t in self.svgl]).encode()
        return self.svgs.get(url, SQUARE)


def with_stub(stub, fn):
    original = icons._get
    icons._get = stub
    try:
        return fn()
    finally:
        icons._get = original


class TheNamesVendorsActuallyPublish(unittest.TestCase):
    """AWS ships `Amazon-Simple-Storage-Service.svg` and never `S3`, so the name everybody
    says finds nothing without the alias table."""

    def test_an_abbreviation_expands_to_the_official_words(self):
        cfg = icons.config()
        self.assertEqual(["simple", "storage"], icons._tokens("Amazon S3", cfg))
        self.assertEqual(["simple", "queue"], icons._tokens("Amazon SQS", cfg))

    def test_the_vendor_word_is_stripped(self):
        cfg = icons.config()
        self.assertEqual(["cognito"], icons._tokens("Amazon Cognito", cfg))
        self.assertEqual(["cosmos"], icons._tokens("Azure Cosmos DB", cfg))

    def test_noise_words_do_not_count_against_a_match(self):
        """`Amazon RDS for PostgreSQL` has to be able to find `Amazon-RDS.svg`."""
        cfg = icons.config()
        self.assertNotIn("for", icons._tokens("Amazon RDS for PostgreSQL", cfg))


class TheMatchIsCoverageNotEquality(unittest.TestCase):
    def test_a_candidate_carrying_one_of_two_words_still_matches(self):
        self.assertIsNotNone(icons._match(["rds", "postgresql"], ["rds"]))

    def test_extra_words_cost_it(self):
        exact = icons._match(["simple", "storage"], ["simple", "storage"])
        padded = icons._match(["simple", "storage"], ["simple", "storage", "glacier"])
        self.assertGreater(exact, padded)

    def test_nothing_in_common_is_no_match_at_all(self):
        self.assertIsNone(icons._match(["cognito"], ["lambda"]))


class TheFloorUnderAMatch(unittest.TestCase):
    """Without it the resolver reached for whatever was closest: an arcade game for
    'machines static or ssr', and the Auth.js logo for 'auth orgs' — a different company's
    brand on someone else's box."""

    def test_a_weak_match_resolves_to_nothing(self):
        stub = Stub(iconify=["streamline-pixel:entertainment-game-machines-arcade"])
        found = with_stub(stub, lambda: icons.resolve("machines static or ssr"))
        self.assertIsNone(found)

    def test_a_strong_match_resolves(self):
        stub = Stub(iconify=["logos:clerk"])
        found = with_stub(stub, lambda: icons.resolve("Clerk"))
        self.assertIsNotNone(found)
        self.assertEqual("logos:clerk", found["id"])

    def test_a_ui_glyph_set_is_never_preferred_to_a_brand_set(self):
        """Iconify ranks `mdi:railway` — a TRAIN — above the Railway logo."""
        stub = Stub(iconify=["mdi:railway", "logos:railway"])
        found = with_stub(stub, lambda: icons.resolve("Railway"))
        self.assertEqual("logos:railway", found["id"])


class ASquareMarkBeatsAWordmark(unittest.TestCase):
    """`logos:supabase` has a viewBox of 512x99 — 5.17:1 — and renders as an illegible sliver
    in a 50px icon slot."""

    def test_the_icon_variant_is_preferred_by_name(self):
        stub = Stub(iconify=["logos:supabase", "logos:supabase-icon"])
        found = with_stub(stub, lambda: icons.resolve("Supabase"))
        self.assertEqual("logos:supabase-icon", found["id"])

    def test_a_wordmark_is_skipped_outright(self):
        stub = Stub(iconify=["devicon:supabase-wordmark"])
        self.assertIsNone(with_stub(stub, lambda: icons.resolve("Supabase")))

    def test_a_wide_svg_is_rejected_after_measuring_it(self):
        """Name heuristics miss the brands that publish no square variant, so the top candidate
        is fetched and measured before it is accepted."""
        stub = Stub(iconify=["logos:widebrand", "logos:widebrand-icon"],
                    svgs={"https://api.iconify.design/logos/widebrand.svg": WIDE,
                          "https://api.iconify.design/logos/widebrand-icon.svg": SQUARE})
        found = with_stub(stub, lambda: icons.resolve("widebrand"))
        self.assertEqual("logos:widebrand-icon", found["id"])
        self.assertLessEqual(found["aspect"], icons.config()["max_aspect"])

    def test_a_brand_with_no_square_variant_is_kept_and_recorded(self):
        """Stripe publishes no `-icon`. Taking the 2.39:1 lockup is the right answer; pretending
        it is square is not."""
        stub = Stub(iconify=["logos:stripe"],
                    svgs={"https://api.iconify.design/logos/stripe.svg": LOCKUP})
        found = with_stub(stub, lambda: icons.resolve("Stripe"))
        self.assertEqual("logos:stripe", found["id"])
        self.assertGreater(found["aspect"], icons.config()["max_aspect"])
        self.assertLess(found["aspect"], icons.config()["reject_aspect"])

    def test_a_strip_is_refused_outright(self):
        """Past the ceiling there is no icon, only a strip — and the capability's own glyph beats
        a strip. `thesvg-color:ping-identity` is 5.73:1 and was accepted for want of anything
        better, which put another company's wordmark on a built identity capability."""
        stub = Stub(iconify=["logos:verywide"],
                    svgs={"https://api.iconify.design/logos/verywide.svg": WIDE})
        self.assertIsNone(with_stub(stub, lambda: icons.resolve("verywide")))


class ColourIsMeasuredNotAssumed(unittest.TestCase):
    """`simple-icons:celery` and `thesvg-color:celery` are the same drawing and only one of them
    is green: the set a candidate came from does not settle it."""

    def test_currentcolor_is_not_colour(self):
        self.assertFalse(icons.colourful(MONO))
        self.assertTrue(icons.colourful(COLOURED))

    def test_a_hardcoded_black_is_not_colour_either(self):
        self.assertFalse(icons.colourful(
            b'<svg viewBox="0 0 10 10"><path fill="#000000"/></svg>'))

    def test_a_coloured_candidate_beats_a_monochrome_one(self):
        stub = Stub(iconify=["simple-icons:celery", "thesvg-color:celery"],
                    svgs={"https://api.iconify.design/simple-icons/celery.svg": MONO,
                          "https://api.iconify.design/thesvg-color/celery.svg": COLOURED})
        found = with_stub(stub, lambda: icons.resolve("Celery"))
        self.assertEqual("thesvg-color:celery", found["id"])
        self.assertTrue(found["colour"])

    def test_monochrome_is_still_better_than_nothing(self):
        stub = Stub(iconify=["simple-icons:celery"],
                    svgs={"https://api.iconify.design/simple-icons/celery.svg": MONO})
        found = with_stub(stub, lambda: icons.resolve("Celery"))
        self.assertEqual("simple-icons:celery", found["id"])
        self.assertFalse(found["colour"])


class TheHeadWordHasToMatch(unittest.TestCase):
    """Coverage says how much of a name matched; it does not say WHICH part did."""

    def test_a_single_shared_word_is_not_enough(self):
        """`Stripe Connect Express + Stripe Billing` matched AWS's `Amazon-Connect.svg` at 118
        against a floor of 110 — one company's logo on another company's box."""
        index = {"paths": ["aws/service/Business-Applications/64/Amazon-Connect.svg"]}
        stub = Stub()
        found = with_stub(stub, lambda: icons.resolve(
            "Stripe Connect Express + Stripe Billing", "aws", index=index))
        self.assertIsNone(found)

    def test_the_head_word_alone_is_enough(self):
        """`Amazon RDS for PostgreSQL` still has to find `Amazon-RDS.svg`."""
        index = {"paths": ["aws/service/Database/64/Amazon-RDS.svg"]}
        found = with_stub(Stub(), lambda: icons.resolve(
            "Amazon RDS for PostgreSQL", "aws", index=index))
        self.assertEqual("aws/service/Database/64/Amazon-RDS.svg", found["id"])


class NarrowingGoesToTheHeadNeverTheTail(unittest.TestCase):
    def test_a_product_name_leads(self):
        self.assertEqual("celery", icons.narrowed("Celery worker + beat", icons.config()))
        self.assertEqual("fly", icons.narrowed("Fly Machines (static or SSR)", icons.config()))

    def test_a_common_noun_narrows_to_nothing(self):
        """Narrowing to the tail is what once drew an arcade game for "machines static or ssr"."""
        for label in ("Object storage", "Background workers", "Secrets and configuration"):
            self.assertIsNone(icons.narrowed(label, icons.config()), label)

    def test_a_full_name_that_matched_nothing_retries_on_its_head(self):
        stub = Stub(iconify=["thesvg-color:celery"],
                    svgs={"https://api.iconify.design/thesvg-color/celery.svg": COLOURED})
        found = with_stub(stub, lambda: icons.resolve("Celery worker + beat"))
        self.assertEqual("thesvg-color:celery", found["id"])


class TheOfficialCloudIconsWin(unittest.TestCase):
    def index(self):
        return {"paths": [
            "aws/service/Storage/64/Amazon-Simple-Storage-Service.svg",
            "aws/service/Storage/64/Amazon-Simple-Storage-Service-Glacier.svg",
            "aws/service/Storage/16/Amazon-Simple-Storage-Service.svg",
            "aws/resource/Storage/Amazon-Simple-Storage-Service_Bucket.svg",
            "aws/service/Database/64/Amazon-RDS.svg",
            "aws/service/Database/64/Amazon-RDS-on-VMware.svg"]}

    def test_the_service_set_beats_the_resource_set_and_the_biggest_size_wins(self):
        cfg = icons.config()
        hits = icons.search_cloud(cfg, "Amazon S3", "aws", self.index())
        self.assertEqual("aws/service/Storage/64/Amazon-Simple-Storage-Service.svg",
                         hits[0]["id"])

    def test_a_composite_loses_to_the_plain_service(self):
        cfg = icons.config()
        hits = icons.search_cloud(cfg, "Amazon RDS", "aws", self.index())
        self.assertEqual("aws/service/Database/64/Amazon-RDS.svg", hits[0]["id"])

    def test_a_non_cloud_provider_gets_nothing_from_this_source(self):
        self.assertEqual([], icons.search_cloud(icons.config(), "Clerk", "clerk", self.index()))


class OnlyANamedProductIsLookedUp(unittest.TestCase):
    """A capability's own label is not a product. Searching one finds somebody else's brand:
    "Identity and access" resolves to PING IDENTITY and "Model inference" to Model Context
    Protocol — another company's mark on a box the team is going to write."""

    def components(self):
        return [{"id": "app", "product": "Fly Machines", "name": "Fly Machines",
                 "capability": "application", "platform": "fly", "mode": "build",
                 "runs_on": {"service": "Fly Machines", "platform": "fly"}},
                {"id": "db", "product": "Supabase Postgres", "name": "Supabase Postgres",
                 "capability": "relational_store", "platform": "supabase", "mode": "buy"},
                {"id": "files", "product": "Supabase Storage", "name": "Supabase Storage",
                 "capability": "object_store", "platform": "supabase", "mode": "buy"},
                {"id": "seek", "product": None, "name": "Search", "capability": "search",
                 "mode": "build"},
                {"id": "who", "name": "Landlord", "capability": "_actor", "mode": "actor"}]

    def resolve(self):
        stub = Stub(iconify=["logos:supabase-icon", "logos:fly-icon"])
        catalogue = caps.capabilities(F.model())
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            names, manifest = with_stub(stub, lambda: icons.resolve_components(
                self.components(), catalogue, cache_dir=tmp, manifest={},
                index={"paths": []}))
        return names, manifest, stub

    def test_a_component_with_no_product_is_never_searched(self):
        names, manifest, stub = self.resolve()
        catalogue = caps.capabilities(F.model())
        self.assertEqual(catalogue["search"]["icon"], names["seek"])
        self.assertNotIn(names["seek"], manifest)
        self.assertFalse([u for u in stub.asked if "=Search" in u or "=search&" in u],
                         "a capability label was searched in a brand catalogue")

    def test_a_vendor_serving_two_capabilities_draws_its_mark_twice(self):
        """The earlier rule sent the loser to a grey glyph, which is a substitute where official
        art exists — the one thing the brief forbids."""
        names, manifest, _ = self.resolve()
        self.assertEqual(names["db"], names["files"])
        self.assertIn(names["db"], manifest)

    def test_a_runtime_is_resolved_as_a_thing_of_its_own(self):
        names, _, _ = self.resolve()
        self.assertIn("app:runtime", names)

    def test_an_actor_is_left_alone(self):
        names, _, _ = self.resolve()
        self.assertNotIn("who", names)

    def test_every_fetched_icon_records_where_it_came_from(self):
        _, manifest, _ = self.resolve()
        self.assertTrue(manifest)
        for name, record in manifest.items():
            for field in ("source", "id", "url", "licence", "fetched"):
                self.assertTrue(record.get(field), f"{name} has no {field}")


class TheCacheNameSaysWhereTheArtCameFrom(unittest.TestCase):
    def test_official_cloud_art_carries_its_provider(self):
        """`slug()` strips the vendor word, so AWS's and Azure's "Cloud Storage" would otherwise
        be one file and the second vendor would get the first one's artwork."""
        found = {"source": "cloud",
                 "id": "aws/service/Security-Identity-Compliance/64/AWS-Secrets-Manager.svg"}
        self.assertEqual("aws-secrets-manager", icons.cache_name(found, "aws"))

    def test_a_brand_logo_does_not(self):
        """`aws-django` for the Django mark says something untrue about where it came from."""
        self.assertEqual("django-icon",
                         icons.cache_name({"source": "iconify", "id": "logos:django-icon"}, "aws"))

    def test_the_name_is_one_the_renderer_will_accept(self):
        import re
        for found, provider in (({"source": "iconify", "id": "logos:stripe"}, "stripe"),
                                ({"source": "cloud", "id": "aws/service/Database/64/Amazon-RDS.svg"},
                                 "aws"),
                                ({"source": "svgl", "id": "Celery"}, None)):
            name = icons.cache_name(found, provider)
            self.assertRegex(name, re.compile(r"^[a-z0-9][a-z0-9-]*$"), found["id"])


class WithoutTheNetworkTheDiagramStillDraws(unittest.TestCase):
    def test_everything_falls_back_to_the_capability_glyphs(self):
        def dead(url, timeout=20):
            raise OSError("no network")
        catalogue = caps.capabilities(F.model())
        components = [{"id": "db", "name": "Supabase Postgres",
                       "capability": "relational_store", "platform": "supabase", "mode": "buy"}]
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            names, manifest = with_stub(dead, lambda: icons.resolve_components(
                components, catalogue, cache_dir=tmp, manifest={}, index={"paths": []}))
        self.assertEqual(catalogue["relational_store"]["icon"], names["db"])
        self.assertEqual({}, manifest)

    def test_the_fallbacks_are_all_names_the_renderer_already_knows(self):
        """The diagram is a required output: an offline run must still produce one."""
        verified = set(json.loads((F.ARCH / "assets" / "icons.verified.json")
                                  .read_text(encoding="utf-8"))["names"])
        for capability, spec in caps.capabilities(F.model()).items():
            self.assertIn(spec["icon"], verified, f"{capability} has no offline icon")


class TheManifestIsAnAuditTrail(unittest.TestCase):
    def test_a_stale_resolution_is_reported_with_its_age(self):
        stale = icons.stale({"old": {"fetched": "2020-01-01"},
                             "fresh": {"fetched": __import__("datetime").date.today().isoformat()}})
        self.assertEqual(["old"], [name for name, _ in stale])

    def test_an_unreadable_date_is_reported_rather_than_ignored(self):
        self.assertEqual([("broken", None)], icons.stale({"broken": {"fetched": "soon"}}))


if __name__ == "__main__":
    unittest.main()
