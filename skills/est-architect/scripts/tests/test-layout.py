#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Tests for layout.py and render-diagram.py.

The renderer positions nothing, so the layout is this module's own code and its failures are
this module's failures: boxes that overlap, an icon name that silently becomes a placeholder,
a component drawn outside the platform that hosts it. Each of those shipped at least once
while this was being built, which is why each has a test.
"""

import json
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fixtures as F  # noqa: E402

arch = F.load("architect", F.ARCH / "scripts" / "architect.py")
layout = F.load("layout", F.ARCH / "scripts" / "layout.py")
rd = F.load("render_diagram", F.ARCH / "scripts" / "render-diagram.py")


def architecture(**kw):
    return arch.build_architecture(F.clinical(), F.model(), F.caps.load_platforms(),
                                   {"house_platforms": ["aws"]}, **kw)


def document(**kw):
    return layout.document(architecture(**kw), F.model(), F.caps.load_platforms())


class TheLayoutPlacesBoxesThatDoNotCollide(unittest.TestCase):
    def test_no_sibling_boxes_overlap(self):
        self.assertEqual([], layout.overlaps(document()))

    def test_it_is_deterministic(self):
        """Two readings of one project have to be diffable months apart."""
        self.assertEqual(json.dumps(document(), sort_keys=True),
                         json.dumps(document(), sort_keys=True))

    def test_content_clears_the_group_title(self):
        """The title is a chip drawn inside the top of its group, and content placed a nominal
        title's distance below it landed on top of the chip in the first rendered diagram."""
        doc = document()
        groups = {e["id"]: e for e in doc["entities"] if e["tag"] == "Group"}
        for entity in doc["entities"]:
            parent = groups.get(entity.get("containerId") or "")
            if parent:
                self.assertGreaterEqual(entity["y"], parent["y"] + layout.TITLE_H,
                                        f"{entity['id']} sits on its group's title")


class TheCompositionMatchesTheDesign(unittest.TestCase):
    def setUp(self):
        self.arch = architecture()
        self.doc = layout.document(self.arch, F.model(),
                                   F.caps.load_platforms(F.ARCH / "assets" / "platforms"))
        self.bands = [e for e in self.doc["entities"]
                      if e["tag"] == "Group" and not e.get("containerId")]

    def test_users_are_on_the_left_and_third_parties_on_the_right(self):
        titles = [b["title"]["text"] for b in self.bands]
        self.assertEqual("USERS", titles[0])
        self.assertEqual("THIRD-PARTY", titles[-1])

    def test_the_hosting_platform_gets_its_own_titled_boundary_band(self):
        """Asserted structurally rather than on a vendor name: the catalogue is broad now and
        which platform wins is the scoring's business, not this test's."""
        host = next(c["platform"] for c in self.arch["components"]
                    if c["capability"] == "application")
        expected = F.caps.load_platforms(F.ARCH / "assets" / "platforms")[host]["name"].upper()
        self.assertIn(expected, [b["title"]["text"] for b in self.bands])

    def test_a_single_capability_vendor_shares_the_third_party_band(self):
        """Eight bands on a 7:1 canvas, five of them holding one or two icons, is what giving
        every vendor its own boundary looked like."""
        import collections
        reach = collections.Counter(c["platform"] for c in self.arch["components"]
                                    if c.get("platform"))
        host = next(c["platform"] for c in self.arch["components"]
                    if c["capability"] == "application")
        small = [p for p, n in reach.items() if n < layout.BAND_MIN_CAPABILITIES and p != host]
        titles = [b["title"]["text"] for b in self.bands]
        platforms = F.caps.load_platforms(F.ARCH / "assets" / "platforms")
        for pid in small:
            self.assertNotIn(platforms[pid]["name"].upper(), titles,
                             f"{pid} serves {reach[pid]} capability and got its own band")

    def test_built_components_sit_inside_the_platform_that_hosts_them(self):
        """Drawing them in a band of their own claimed the database floats outside the cloud,
        and stretched every application edge across the whole canvas."""
        self.assertNotIn("BUILT BY THIS PROJECT", [b["title"]["text"] for b in self.bands])
        groups = {e["id"]: e for e in self.doc["entities"] if e["tag"] == "Group"}
        store = next(e for e in self.doc["entities"] if e.get("id") == "relational_store")
        self.assertTrue(groups[store["containerId"]]["containerId"].endswith("aws"))

    def test_bands_do_not_overlap(self):
        for i, a in enumerate(self.bands):
            for b in self.bands[i + 1:]:
                apart = (b["x"] >= a["x"] + a["width"] or a["x"] >= b["x"] + b["width"]
                         or b["y"] >= a["y"] + a["height"] or a["y"] >= b["y"] + b["height"])
                self.assertTrue(apart, f"{a['id']} and {b['id']} overlap")

    def test_the_canvas_is_not_one_long_strip(self):
        """4378x614 — 7:1 — is unreadable at any zoom that fits a page."""
        width = max(e["x"] + e.get("width", 0) for e in self.doc["entities"])
        height = max(e["y"] + e.get("height", 0) for e in self.doc["entities"])
        self.assertLess(width / height, 4.0, f"{width}x{height} is still a strip")

    def test_a_generic_glyph_is_coloured_rather_than_left_as_grey_line_art(self):
        """21 of the 70 verified icons have no colour of their own. Uncoloured, a diagram of
        them is exactly what the reference beats most obviously."""
        generic = [e for e in self.doc["entities"]
                   if e.get("icon") in layout.GENERIC_ICONS]
        self.assertTrue(generic, "no generic glyph in this diagram — the test proves nothing")
        for entity in generic:
            self.assertTrue(entity.get("color"), f"{entity['icon']} has no colour")

    def test_the_colour_prop_is_the_one_an_icon_actually_has(self):
        """`Icon`'s schema is {icon, size, texts, typeface, color, fontSize, badge}. `iconProps`
        belongs to `Shape` and to a group's title — the renderer neither rejects it on an Icon nor
        reads it, so setting it there tinted nothing at all and every glyph stayed grey."""
        for entity in self.doc["entities"]:
            if entity.get("tag") == "Icon":
                self.assertNotIn("iconProps", entity)

    def test_a_vendor_logo_is_left_its_own_colour(self):
        for entity in self.doc["entities"]:
            if entity.get("icon") and entity["icon"] not in layout.GENERIC_ICONS:
                self.assertNotIn("color", entity)

    def test_the_brand_palette_is_used_rather_than_a_hardcoded_hex(self):
        brand = json.loads((F.ROOT / "est-estimate" / "assets" / "brand.json")
                           .read_text(encoding="utf-8"))["palette"]["light"]
        colours = {e.get("color") for e in self.doc["entities"]}
        self.assertIn(brand["brand"], colours)


class AMultiPlatformSetDrawsMultipleBoundaries(unittest.TestCase):
    """The honest picture of a combination. Untested until an excluded-platform run forced one,
    which is also how the enumeration bug that made combinations unreachable was found."""

    def setUp(self):
        self.architecture = arch.build_architecture(
            F.clinical(), F.model(), F.caps.load_platforms(),
            {"constraints": [{"id": "C1", "kind": "excluded_platform", "detail": "aws",
                              "basis": "stated"}]})
        self.doc = layout.document(self.architecture, F.model(), F.caps.load_platforms())
        self.bands = [e for e in self.doc["entities"]
                      if e["tag"] == "Group" and not e.get("containerId")]

    def test_every_platform_that_earns_a_band_gets_one(self):
        """Earns it by hosting the application or serving several capabilities. A vendor that
        provides one thing shares the third-party band — eight bands on a 7:1 canvas, five of
        them nearly empty, is what the alternative looked like."""
        import collections
        reach = collections.Counter(c["platform"] for c in self.architecture["components"]
                                    if c.get("platform"))
        host = next((c["platform"] for c in self.architecture["components"]
                     if c["capability"] == "application"), None)
        platforms = F.caps.load_platforms()
        titles = [b["title"]["text"] for b in self.bands]
        earned = [p for p, n in reach.items()
                  if p == host or n >= layout.BAND_MIN_CAPABILITIES]
        self.assertTrue(earned, "no platform earned a band — the test proves nothing")
        for pid in earned:
            self.assertIn(platforms[pid]["name"].upper(), titles)

    def test_the_bands_still_do_not_overlap(self):
        self.assertEqual([], layout.overlaps(self.doc))
        for i, a in enumerate(self.bands):
            for b in self.bands[i + 1:]:
                apart = (b["x"] >= a["x"] + a["width"] or a["x"] >= b["x"] + b["width"]
                         or b["y"] >= a["y"] + a["height"] or a["y"] >= b["y"] + b["height"])
                self.assertTrue(apart, f"{a['id']} and {b['id']} overlap")

    def test_users_and_third_parties_stay_outside_every_platform(self):
        titles = [b["title"]["text"] for b in self.bands]
        self.assertEqual("USERS", titles[0])
        self.assertIn("THIRD-PARTY", titles)

    @unittest.skipUnless(shutil.which("npx") and rd.renderer.find_chromium()[0],
                         "no renderer on this machine")
    def test_it_really_renders(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            report, _, code = rd.render(self.architecture, Path(tmp) / "multi.png",
                                        F.model(), F.caps.load_platforms(),
                                        resolve_icons=False)
        self.assertEqual(0, code, report["findings"])
        self.assertGreater(report["bytes"], 10_000)

    @unittest.skipUnless(shutil.which("npx") and rd.renderer.find_chromium()[0],
                         "no renderer on this machine")
    def test_no_connector_runs_over_a_component(self):
        """Measured, not looked at. The router avoids obstacles but falls back to a straight
        line when no corridor exists, and the first real diagram had nineteen crossings."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            measured = Path(tmp) / "measured.json"
            report, _, code = rd.render(self.architecture, Path(tmp) / "m.png", F.model(),
                                        F.caps.load_platforms(), resolve_icons=False,
                                        measured_path=measured)
            self.assertEqual(0, code, report["findings"])
            if report.get("routing") is None:
                self.skipTest("no measured geometry; the pinned local renderer is not installed")
            self.assertEqual([], report["routing"]["findings"])
            self.assertGreater(report["routing"]["connections"], 0,
                               "nothing was routed, so nothing was checked")


class EdgesAreDrawnBetweenGroups(unittest.TestCase):
    def test_every_connection_joins_two_tier_groups(self):
        """An application touching nine components produces nine near-parallel lines across the
        canvas — a picture of the fan-out rather than of the system. It also took the render
        from a third of a second to eighty seconds."""
        doc = document()
        ids = {e["id"] for e in doc["entities"] if e["tag"] == "Group"}
        for edge in doc["connections"]:
            self.assertIn(edge["from"], ids)
            self.assertIn(edge["to"], ids)

    def test_there_are_far_fewer_edges_than_component_pairs(self):
        arch_doc = architecture()
        doc = layout.document(arch_doc, F.model(), F.caps.load_platforms())
        self.assertLess(len(doc["connections"]), len(arch_doc["connections"]) / 2)

    def test_no_edge_loops_back_to_its_own_group(self):
        for edge in document()["connections"]:
            self.assertNotEqual(edge["from"], edge["to"])


class TheDiagramDoesNotDoubleAsABuyBuildMap(unittest.TestCase):
    """Whether a component is written or rented is a sourcing decision with a scored table and a
    gate of its own. Stamping it on the artwork gave every node a second label and cost the
    diagram a corner to a key nobody needed."""

    def test_no_component_carries_a_mode_badge(self):
        self.assertFalse([e for e in document()["entities"] if e.get("badge")])

    def test_there_is_no_legend(self):
        self.assertFalse([e for e in document()["entities"] if e["tag"] == "Legend"])


class ARuntimeContainsTheSoftwareThatRunsInIt(unittest.TestCase):
    """"Django on Fargate" was one box carrying two products, and its icon was a coin toss
    between a framework and a cloud service."""

    def built(self):
        design = architecture()
        for component in design["components"]:
            if component["capability"] == "application":
                component["name"] = "Django"
                component["product"] = "Django"
                component["runs_on"] = {"service": "AWS Fargate", "platform": "aws"}
        return layout.document(design, F.model(), F.caps.load_platforms(),
                               {"application:runtime": "aws-fargate"})

    def test_the_runtime_is_a_group_and_the_software_is_inside_it(self):
        doc = self.built()
        group = next(e for e in doc["entities"] if e["id"] == "runtime-application")
        self.assertEqual("Group", group["tag"])
        self.assertEqual("AWS Fargate", group["title"]["text"])
        icon = next(e for e in doc["entities"] if e["id"] == "application")
        self.assertEqual("runtime-application", icon["containerId"])

    def test_the_runtime_carries_its_own_official_icon(self):
        group = next(e for e in self.built()["entities"] if e["id"] == "runtime-application")
        self.assertEqual("aws-fargate", group["title"]["icon"])

    def test_a_component_with_no_runtime_is_still_a_bare_icon(self):
        doc = self.built()
        self.assertFalse([e for e in doc["entities"]
                          if e["tag"] == "Group" and e["id"].startswith("runtime-")
                          and e["id"] != "runtime-application"])

    def test_the_runtime_group_does_not_overlap_its_siblings(self):
        self.assertEqual([], layout.overlaps(self.built()))


class AnUnverifiedIconIsCaughtBeforeTheBrowserBoots(unittest.TestCase):
    def test_every_icon_this_module_ships_is_in_the_verified_manifest(self):
        self.assertEqual([], rd.unverified(document()))

    def test_an_unknown_name_is_reported_with_what_to_do_about_it(self):
        doc = document()
        doc["entities"][-1]["icon"] = "not-a-real-icon"
        bad = rd.unverified(doc)
        self.assertEqual(["not-a-real-icon"], bad)

    def test_the_manifest_records_when_it_was_checked(self):
        manifest = json.loads((F.ARCH / "assets" / "icons.verified.json")
                              .read_text(encoding="utf-8"))
        self.assertTrue(manifest["checked"])
        self.assertIn("W_UNKNOWN_ICON", manifest["_what"])


class TheRenderRefusesRatherThanDegrades(unittest.TestCase):
    def test_an_unverified_icon_fails_the_render_before_chromium_is_touched(self):
        """Checked with resolution OFF: with it on, the resolver replaces the component's icon
        with an official one and the bad name never reaches the renderer — which is the point
        of the resolver, and would make this guard untestable through it."""
        import tempfile
        bad = architecture()
        bad["components"][1]["icon"] = "not-a-real-icon"
        with tempfile.TemporaryDirectory() as tmp:
            report, _, code = rd.render(bad, Path(tmp) / "x.png", F.model(),
                                        F.caps.load_platforms(), resolve_icons=False)
        self.assertEqual(1, code)
        self.assertEqual("unverified_icon", report["findings"][0]["kind"])
        self.assertIn("nobody looks", report["findings"][0]["detail"])

    def test_a_missing_chromium_is_a_failure_and_names_est_setup(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            report, _, code = rd.render(architecture(), Path(tmp) / "x.png", F.model(),
                                        F.caps.load_platforms(),
                                        chromium="/nonexistent/chromium",
                                        resolve_icons=False)
        if code == 2:
            self.assertIn("/est-setup", report["findings"][0]["detail"])
        else:
            self.assertEqual(0, code, "a real Chromium was auto-detected, so this path is moot")

    @unittest.skipUnless(shutil.which("npx") and rd.renderer.find_chromium()[0],
                         "no renderer on this machine")
    def test_it_really_renders_a_png(self):
        """The diagram is a required output. A test that only checks the document would let a
        broken pipeline ship."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "architecture.png"
            report, _, code = rd.render(architecture(), out, F.model(),
                                        F.caps.load_platforms(), resolve_icons=False)
        self.assertEqual(0, code, report["findings"])
        self.assertGreater(report["bytes"], 10_000)
        self.assertIn("unknown icons treated as errors", report["checked"])

    @unittest.skipUnless(shutil.which("npx") and rd.renderer.find_chromium()[0],
                         "no renderer on this machine")
    def test_it_renders_with_official_icons_resolved(self):
        """The whole point: a diagram drawn with the vendors' own art rather than glyphs.

        The four icon APIs are stubbed. What is under test is the wiring — that a resolved name
        reaches the document, that its bytes reach the renderer's cache, and that the render
        accepts a name no catalogue ships — and a suite that fails when somebody else's CDN is
        slow tests none of that."""
        import json as _json
        import tempfile
        art = (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
               b'<path fill="#37814a" d="M2 2h20v20H2z"/></svg>')

        def stub(url, timeout=20):
            if "iconify.design/search" in url:
                # Answer with a brand named after what was asked for, so the head-token rule —
                # which is what stops one company's logo landing on another's box — still applies.
                import urllib.parse
                query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("query", [""])
                head = (query[0].split() or ["x"])[0].lower()
                return _json.dumps({"icons": [f"logos:{head}-stubbrand"]}).encode()
            if "svgl.app" in url:
                return b"[]"
            return art

        original = rd.icons._get
        rd.icons._get = stub
        try:
            with tempfile.TemporaryDirectory() as tmp:
                report, doc, code = rd.render(architecture(), Path(tmp) / "a.png", F.model(),
                                              F.caps.load_platforms(), resolve_icons=True)
        finally:
            rd.icons._get = original
        self.assertEqual(0, code, report["findings"])
        self.assertGreater(report.get("icons_resolved", 0), 0,
                           "nothing was resolved; the diagram is all fallback glyphs")
        self.assertTrue([e for e in doc["entities"]
                         if str(e.get("icon", "")).endswith("-stubbrand")],
                        "a resolved name never reached the document")
        self.assertGreater(report["icons"]["official"], 0)


if __name__ == "__main__":
    unittest.main()
