#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Tests for graph.py, layout.py and render-diagram.py — the diagram pipeline.

ELK decides where every box goes, so these do not test coordinates. They test the things the
pipeline is responsible for and that have each shipped broken at least once: a graph that says
something false, a container that wraps one container, a name on the canvas twice, a route the
renderer silently threw away, a cell whose size depended on how long its label happened to be,
and a test stub written into the icon cache a client's diagram is drawn from.
"""

import json
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fixtures as F  # noqa: E402

arch = F.load("architect", F.ARCH / "scripts" / "architect.py")
graph = F.load("graph", F.ARCH / "scripts" / "graph.py")
layout = F.load("layout", F.ARCH / "scripts" / "layout.py")
theme = F.load("theme", F.ARCH / "scripts" / "theme.py")
check = F.load("diagram_check", F.ARCH / "scripts" / "diagram-check.py")
rd = F.load("render_diagram", F.ARCH / "scripts" / "render-diagram.py")

HAS_ELK = (F.ARCH / "assets" / "renderer" / "node_modules" / "elkjs").exists() \
    and bool(shutil.which("node"))
needs_elk = unittest.skipUnless(HAS_ELK, "elkjs is not installed; run /est-setup")


def architecture(**kw):
    return arch.build_architecture(F.clinical(), F.model(), F.caps.load_platforms(),
                                   {"house_platforms": ["aws"]}, **kw)


def semantic(**kw):
    return graph.build(architecture(**kw), F.model(), F.caps.load_platforms())


def document(**kw):
    return layout.document(architecture(**kw), F.model(), F.caps.load_platforms())


class TheGraphSaysSomethingTrue(unittest.TestCase):
    """The defect no layout engine can fix. Edges used to be derived from TIERS — every component
    in the application tier joined to every component in services, data and external — so a
    browser was given authored edges to a secrets manager, a relational store and a payment
    vendor. Half the graph was false and it was invisible because the diagram aggregated every
    edge to its tier group before drawing it."""

    def test_the_browser_does_not_reach_the_back_end_directly(self):
        edges = {(e["from"], e["to"]) for e in architecture()["connections"]}
        for forbidden in ("secrets", "relational_store", "object_store", "payments",
                          "email", "observability"):
            self.assertNotIn(("web_client", forbidden), edges,
                             f"the browser is drawn talking straight to {forbidden}")

    def test_the_browser_reaches_the_api(self):
        edges = {(e["from"], e["to"]) for e in architecture()["connections"]}
        self.assertIn(("web_client", "application"), edges)

    def test_an_actor_touches_the_front_and_not_the_identity_provider(self):
        edges = [e for e in architecture()["connections"] if e["from"].startswith("actor-")]
        self.assertTrue(edges)
        for edge in edges:
            self.assertNotEqual("identity", edge["to"])

    def test_a_label_says_what_flows(self):
        labels = {e.get("label") for e in architecture()["connections"] if e.get("label")}
        self.assertTrue(labels)
        for label in labels:
            self.assertNotIn(label.lower(), {"uses", "calls", "admits"},
                             "a label that names no cargo is the defect, not the fix")
            self.assertLessEqual(len(label.split()), 5, label)

    def test_one_meaning_is_not_written_once_per_arrowhead(self):
        seen = {}
        for edge in architecture()["connections"]:
            if not edge.get("label"):
                continue
            self.assertNotIn(edge["label"], seen,
                             f"`{edge['label']}` is used for two different targets")
            seen[edge["label"]] = edge["to"]


class TheContainersAreNotRedundant(unittest.TestCase):
    """A2, A4, H5, H6 — defect 4 as reported: four levels of nesting, `USERS` wrapping `Users`,
    `THIRD-PARTY` wrapping `Integrations`, and the name `Integrations` on the canvas twice."""

    def test_no_zone_wraps_a_single_group(self):
        g = semantic()
        for zone in g["zones"]:
            children = [gr for gr in g["groups"] if gr["zoneId"] == zone["id"]]
            self.assertNotEqual(1, len(children),
                                f"`{zone['title']}` is a wrapper around one group")

    def test_every_name_is_unique(self):
        g = semantic()
        names = [z["title"] for z in g["zones"]] + [gr["title"] for gr in g["groups"]] \
            + [n["name"] for n in g["nodes"]]
        lowered = [n.strip().lower() for n in names]
        self.assertEqual(len(lowered), len(set(lowered)), sorted(lowered))

    def test_there_are_at_most_two_container_levels(self):
        g = semantic()
        groups = {gr["id"] for gr in g["groups"]}
        for group in g["groups"]:
            self.assertNotIn(group["zoneId"], groups, "a group is nested inside another group")

    def test_a_runtime_is_a_badge_and_never_a_container(self):
        """A3. Two products, two official icons, one node — and no second box repeating the
        runtime's name on the far side of the canvas."""
        g = semantic()
        hosted = [n for n in g["nodes"] if n.get("runtime")]
        self.assertTrue(hosted, "the fixture has nothing running on a named runtime")
        for name in (n["runtime"] for n in hosted):
            self.assertNotIn(name, [gr["title"] for gr in g["groups"]])

    def test_every_node_says_what_it_is(self):
        """A5: a name and a role, never one string carrying both."""
        for node in semantic()["nodes"]:
            self.assertTrue(node["role"], node["name"])
            self.assertNotIn(" on ", node["name"],
                             "the runtime is folded back into the label")

    def test_the_graph_validates(self):
        self.assertEqual([], graph.validate(semantic())["findings"])


class TheDiagramDoesNotDoubleAsABuyBuildMap(unittest.TestCase):
    @needs_elk
    def test_no_badge_carries_a_sourcing_mode(self):
        """The badge prop is used now — for the runtime — so this can no longer assert that
        nothing has one. What it asserts is that no badge says `build`, `buy` or `adopt`."""
        for entity in document()["entities"]:
            badge = entity.get("badge") or {}
            self.assertNotIn(str(badge.get("text", "")).lower(),
                             {"build", "buy", "adopt", "built", "bought", "adopted"})

    @needs_elk
    def test_there_is_no_legend(self):
        self.assertEqual([], [e for e in document()["entities"] if e.get("tag") == "Legend"])


class TheCellIsTheSameSizeWhateverItIsCalled(unittest.TestCase):
    """C2/C8, and defect 8. An Icon carried no authored size, so the renderer measured the
    caption against 1.8x the 50px glyph — the ~90px wrap width in the report — and every long
    name grew its own node."""

    def test_a_long_name_wraps_rather_than_widening_its_node(self):
        t = theme.tokens()
        lines = layout.wrap("AWS End User Messaging SMS", t["type"]["node_name"]["px"])
        self.assertGreater(len(lines), 1)
        self.assertLessEqual(len(lines), layout.MAX_NAME_LINES)

    def test_the_wrap_width_is_the_cell_not_the_glyph(self):
        self.assertEqual(theme.CELL_W - 8, layout.WRAP_W)
        self.assertGreater(layout.WRAP_W, 100)

    @needs_elk
    def test_every_node_is_the_same_size(self):
        sizes = {(e["width"], e["height"]) for e in document()["entities"]
                 if e.get("tag") == "Icon"}
        self.assertEqual(1, len(sizes), sizes)


class TheIconsAreOfficialOrTheyAreGlyphs(unittest.TestCase):
    """F1/F2. Colour belongs to a vendor's own artwork; a capability nobody bought, an actor and
    a product with no published mark all get one outline set in one ink."""

    @needs_elk
    def test_a_resolved_logo_keeps_its_own_colour(self):
        doc = layout.document(architecture(), F.model(), F.caps.load_platforms(),
                              icon_names={"relational_store": "aws-rds"},
                              official={"aws-rds"})
        entity = next(e for e in doc["entities"] if e["id"] == "relational_store")
        self.assertNotIn("color", entity)

    @needs_elk
    def test_an_unresolved_product_is_a_monochrome_glyph(self):
        """The signal is whether OFFICIAL art was found, not whether the resolver returned a
        name: an unresolved product still gets one, its capability's glyph."""
        doc = layout.document(architecture(), F.model(), F.caps.load_platforms(),
                              icon_names={"relational_store": "postgres"}, official=set())
        entity = next(e for e in doc["entities"] if e["id"] == "relational_store")
        self.assertEqual(theme.GLYPH_INK, entity.get("color"))

    @needs_elk
    def test_a_glyph_never_carries_iconprops(self):
        """`iconProps` belongs to Shape and to a group title. On an Icon the renderer neither
        rejects it nor reads it, so an earlier version tinted nothing at all."""
        for entity in document()["entities"]:
            if entity.get("tag") == "Icon":
                self.assertNotIn("iconProps", entity)


class TheRoutesAreAuthoredAndTheRendererKeepsThem(unittest.TestCase):
    @needs_elk
    def test_every_route_is_strictly_orthogonal(self):
        """The renderer adopts an authored polyline only if every segment is axis-aligned, and
        otherwise discards it and routes the connection itself without a word. Snapping two
        near-equal coordinates independently is what broke this."""
        for connection in document()["connections"]:
            points = connection.get("points") or []
            for a, b in zip(points, points[1:]):
                self.assertTrue(a["x"] == b["x"] or a["y"] == b["y"],
                                f"{connection['from']} -> {connection['to']} has a diagonal")

    @needs_elk
    def test_every_coordinate_is_on_the_grid(self):
        doc = document()
        for entity in doc["entities"]:
            for key in ("x", "y", "width", "height"):
                self.assertEqual(0, entity[key] % layout.GRID, f"{entity['id']}.{key}")

    @needs_elk
    def test_no_authored_route_cuts_a_box_it_is_not_joined_to(self):
        report = check.check(document())
        self.assertEqual([], [f for f in report["findings"] if f.get("check") == "H1"],
                         report["findings"])

    def test_a_jog_is_straightened_but_only_when_it_is_safe(self):
        # Both neighbours run the same way, so the 4px step between them is a jog rather
        # than a turn. A step between segments at right angles is a real corner and is kept.
        jog = [{"x": 0, "y": 0}, {"x": 100, "y": 0}, {"x": 100, "y": 4},
               {"x": 300, "y": 4}, {"x": 400, "y": 4}]
        def has_step(points):
            return any(a["y"] != b["y"] for a, b in zip(points, points[1:]))

        self.assertFalse(has_step(layout.simplify(jog)), "the jog should have been straightened")
        wall = [{"x": 20, "y": 0, "width": 60, "height": 40}]
        self.assertTrue(has_step(layout.simplify(jog, obstacles=wall)),
                        "a straightening that would cut a box must be reverted")

    def test_an_out_and_back_excursion_is_cut(self):
        """A route that leaves rightwards, runs further right, steps up and then runs back to
        the left has spent four bends going nowhere. It is what a layered router does with a
        back edge, and it reads as a mistake because it is one."""
        detour = [{"x": 0, "y": 0}, {"x": 400, "y": 0}, {"x": 400, "y": -60},
                  {"x": -200, "y": -60}, {"x": -200, "y": 80}]
        cut = layout.simplify(detour)
        self.assertLess(max(p["x"] for p in cut), 400,
                        "the excursion to the right is still in the route")
        self.assertLessEqual(len(cut) - 2, 3)

    def test_no_simplification_ever_puts_a_route_through_a_box(self):
        """The invariant, not one particular rewrite. Every straightening is tried and reverted
        if it would cut something — a first version moved six routes into boxes, which the
        renderer then rejected and re-routed, turning a tidy-up into a layout nobody authored."""
        detour = [{"x": 0, "y": 0}, {"x": 400, "y": 0}, {"x": 400, "y": -60},
                  {"x": -200, "y": -60}, {"x": -200, "y": 80}]
        for wall in ([{"x": -40, "y": -50, "width": 60, "height": 40}],
                     [{"x": -100, "y": -30, "width": 80, "height": 80}],
                     [{"x": 100, "y": -80, "width": 120, "height": 40}]):
            cut = layout.simplify(detour, obstacles=wall)
            for a, b in zip(cut, cut[1:]):
                self.assertFalse(layout._cuts(a, b, wall[0]),
                                 f"simplification drove {a}->{b} through {wall[0]}")

    def test_a_label_sits_on_the_longest_horizontal_run(self):
        """D7. ELK's own placement belongs to the route ELK returned, and simplification has
        since cut the excursions out of it — which left one label alone in empty space a long
        way from its own arrow."""
        points = [{"x": 0, "y": 0}, {"x": 40, "y": 0}, {"x": 40, "y": 100},
                  {"x": 400, "y": 100}]
        spot = layout._label_spot(points, 80, 18)
        self.assertEqual(220 - 40, spot["x"])
        self.assertLess(spot["y"], 100, "the label should sit above its line")

    def test_a_label_with_nowhere_horizontal_to_sit_defers(self):
        self.assertIsNone(layout._label_spot(
            [{"x": 0, "y": 0}, {"x": 0, "y": 200}], 80, 18))

    def test_collinear_points_are_not_bends(self):
        run = [{"x": 0, "y": 0}, {"x": 50, "y": 0}, {"x": 100, "y": 0}, {"x": 100, "y": 60}]
        self.assertEqual(3, len(layout.simplify(run)))


class TheRenderRefusesRatherThanDegrades(unittest.TestCase):
    @needs_elk
    def test_an_unverified_icon_is_caught_before_the_browser_boots(self):
        doc = document()
        self.assertEqual([], rd.unverified(doc, F.ARCH / "assets" / "icon-cache"))

    @needs_elk
    def test_a_missing_chromium_is_a_failure_and_names_est_setup(self):
        original = rd.renderer.find_chromium
        rd.renderer.find_chromium = lambda _=None: (None, None)
        try:
            report, _, code = rd.render(architecture(), Path("/tmp/none.png"), F.model(),
                                        F.caps.load_platforms(), resolve_icons=False)
        finally:
            rd.renderer.find_chromium = original
        self.assertEqual(2, code)
        self.assertIn("/est-setup", json.dumps(report["findings"]))

    def test_a_missing_layout_engine_is_a_prerequisite_not_a_degraded_picture(self):
        # render-diagram loads its own copy of layout, so the stub goes on that one.
        original = rd.layout.elk_layout
        rd.layout.elk_layout = lambda *a, **k: None
        try:
            report, _, code = rd.render(architecture(), Path("/tmp/none.png"), F.model(),
                                        F.caps.load_platforms(), resolve_icons=False)
        finally:
            rd.layout.elk_layout = original
        self.assertEqual(2, code)
        self.assertIn("est-setup", json.dumps(report["findings"]))

    @unittest.skipUnless(HAS_ELK and rd.renderer.find_chromium()[0], "no renderer")
    def test_it_really_renders_a_png(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "a.png"
            report, _, code = rd.render(architecture(), out, F.model(),
                                        F.caps.load_platforms(), resolve_icons=False,
                                        measured_path=Path(tmp) / "m.json")
        self.assertEqual(0, code, report["findings"])
        self.assertGreater(report["bytes"], 10_000)
        self.assertIn("unknown icons treated as errors", report["checked"])

    @unittest.skipUnless(HAS_ELK and rd.renderer.find_chromium()[0], "no renderer")
    def test_a_stubbed_resolver_never_writes_into_the_shipped_icon_cache(self):
        """A test that wrote its own fixture into `assets/icon-cache` put a green square in
        `aws-simple-email-service.svg` and a row for it in the audit manifest — and that square
        was then drawn on a client's diagram. The cache a test uses is its own."""
        import tempfile
        art = (b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
               b'<path fill="#37814a" d="M2 2h20v20H2z"/></svg>')

        def stub(url, timeout=20):
            if "iconify.design/search" in url:
                import urllib.parse
                query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get("query", [""])
                head = (query[0].split() or ["x"])[0].lower()
                return json.dumps({"icons": [f"logos:{head}-stubbrand"]}).encode()
            if "svgl.app" in url:
                return b"[]"
            return art

        shipped = F.ARCH / "assets" / "icon-cache"
        before = {p.name for p in shipped.glob("*.svg")} if shipped.is_dir() else set()
        original = rd.icons._get
        rd.icons._get = stub
        try:
            with tempfile.TemporaryDirectory() as tmp:
                report, doc, code = rd.render(architecture(), Path(tmp) / "a.png", F.model(),
                                              F.caps.load_platforms(), resolve_icons=True,
                                              icon_cache=Path(tmp) / "icons")
        finally:
            rd.icons._get = original
        self.assertEqual(0, code, report["findings"])
        self.assertGreater(report.get("icons_resolved", 0), 0)
        after = {p.name for p in shipped.glob("*.svg")} if shipped.is_dir() else set()
        self.assertEqual(before, after, "the suite wrote into the shipped icon cache")


if __name__ == "__main__":
    unittest.main()
