#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Tests for diagram-check.py — does any connector run over something it is not joined to?

The renderer's router avoids obstacles but falls back to a straight line when no corridor
exists, and the first real diagram had nineteen segments crossing components. Looking at a PNG
catches that late, once, and by eye; this reads the measured geometry.

Geometry is built by hand here rather than rendered: the point under test is the intersection
arithmetic and the rule about which boxes an edge is allowed to touch, and a browser in the loop
would make the suite slow and flaky without testing either.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fixtures as F  # noqa: E402

routing = F.load("diagram_check", F.ARCH / "scripts" / "diagram-check.py")


def box(eid, x, y, w, h, tag="Group", container=None, title=None):
    entity = {"tag": tag, "id": eid, "x": x, "y": y, "width": w, "height": h}
    if container:
        entity["containerId"] = container
    if title:
        entity["title"] = {"text": title}
    return entity


def edge(source, target, points, **kw):
    ox, oy = points[0]
    return dict({"from": source, "to": target, "x": ox, "y": oy,
                 "points": [{"x": px - ox, "y": py - oy} for px, py in points]}, **kw)


class ASegmentThroughABoxIsAFinding(unittest.TestCase):
    def document(self, points):
        return {"entities": [box("a", 0, 0, 100, 100), box("b", 400, 0, 100, 100),
                             box("wall", 200, 0, 100, 100, title="In the way")],
                "connections": [edge("a", "b", points)]}

    def test_a_straight_line_through_a_third_box_is_caught(self):
        report = routing.check(self.document([(100, 50), (400, 50)]))
        self.assertFalse(report["ok"])
        self.assertEqual(["wall"], [f["over"] for f in report["findings"]])
        self.assertEqual("In the way", report["findings"][0]["what"])

    def test_a_route_around_it_is_clean(self):
        report = routing.check(self.document(
            [(100, 50), (150, 50), (150, 150), (350, 150), (350, 50), (400, 50)]))
        self.assertTrue(report["ok"], report["findings"])

    def test_running_along_an_edge_is_not_a_crossing(self):
        """An orthogonal router shares coordinates with the boxes it skirts, by construction."""
        report = routing.check(self.document(
            [(100, 50), (200, 50), (200, 0), (300, 0), (300, 50), (400, 50)]))
        self.assertTrue(report["ok"], report["findings"])


class AnEdgeMayTouchItsOwnEndpointsAndTheirContainers(unittest.TestCase):
    def document(self):
        return {"entities": [
            box("band", 0, 0, 600, 300),
            box("left", 40, 40, 100, 100, container="band"),
            box("right", 400, 40, 100, 100, container="band"),
            box("deep", 60, 60, 20, 20, tag="Icon", container="left"),
        ], "connections": [edge("left", "right", [(140, 90), (400, 90)])]}

    def test_crossing_the_band_both_ends_sit_in_is_allowed(self):
        # H1 only. These fixtures are two boxes and a line, so the composition checks — a
        # container with one child, an aspect ratio, a row of one — have nothing to say about
        # them and would drown the thing under test.
        report = routing.check(self.document())
        self.assertEqual([], [f for f in report["findings"] if f.get("check") == "H1"])

    def test_an_icon_inside_an_endpoint_is_not_reported(self):
        report = routing.check(self.document())
        self.assertNotIn("deep", [f.get("over") for f in report["findings"]])


class CrossingAnIconIsWorseThanCrossingAGroup(unittest.TestCase):
    def document(self, tag):
        return {"entities": [box("a", 0, 0, 100, 100), box("b", 400, 0, 100, 100),
                             box("wall", 200, 0, 100, 100, tag=tag)],
                "connections": [edge("a", "b", [(100, 50), (400, 50)])]}

    def test_a_group_is_reported_as_a_group(self):
        report = routing.check(self.document("Group"))
        self.assertEqual("group_crossed", report["findings"][0]["kind"])

    def test_an_icon_is_reported_as_an_icon(self):
        report = routing.check(self.document("Icon"))
        self.assertEqual("icon_crossed", report["findings"][0]["kind"])


class ALabelOverAnIconIsAlsoAFinding(unittest.TestCase):
    def test_a_label_placed_on_top_of_a_component_is_caught(self):
        document = {
            "entities": [box("a", 0, 0, 100, 100), box("b", 400, 0, 100, 100),
                         box("mark", 200, 200, 60, 60, tag="Icon")],
            "connections": [edge("a", "b", [(100, 50), (150, 50), (150, 260), (400, 260)],
                                 labelPlacement={"x": 110, "y": 160, "width": 80,
                                                 "height": 30})]}
        report = routing.check(document)
        self.assertIn("label_over_icon", [f["kind"] for f in report["findings"]])


class ACheckerThatComparedNothingSaysSo(unittest.TestCase):
    def test_the_denominator_is_reported(self):
        report = routing.check({"entities": [box("a", 0, 0, 10, 10)], "connections": []})
        self.assertIn("0 routed connections", report["checked"])
        self.assertTrue(report["ok"])

    def test_an_unrouted_connection_is_counted_and_named_as_unchecked(self):
        """A connection the renderer never routed is not a clean connection."""
        report = routing.check({"entities": [box("a", 0, 0, 10, 10), box("b", 40, 0, 10, 10)],
                                "connections": [{"from": "a", "to": "b"}]})
        self.assertEqual(1, report["unrouted"])
        self.assertIn("NOT checked", report["checked"])


class TheRealDiagramRoutesCleanly(unittest.TestCase):
    """The layout's own output, measured by nothing but arithmetic: every authored box against
    every authored edge. The rendered check is in test-layout.py, which boots a browser."""

    def test_the_shipped_layout_authors_no_edge_that_cuts_a_box(self):
        layout = F.load("layout", F.ARCH / "scripts" / "layout.py")
        arch = F.load("architect", F.ARCH / "scripts" / "architect.py")
        design = arch.build_architecture(F.clinical(), F.model(), F.caps.load_platforms(),
                                         {"house_platforms": ["aws"]})
        doc = layout.document(design, F.model(), F.caps.load_platforms())
        self.assertEqual([], layout.overlaps(doc))


class SeverityIsTheDifferenceBetweenWrongAndImprovable(unittest.TestCase):
    """A connector over a box is a defect somebody reported and is fixable, so it fails. An
    aspect ratio of 3.2 on an architecture with seven columns is a fact about the architecture."""

    def document(self):
        return {"entities": [
            box("a", 0, 0, 100, 100, tag="Icon"),
            box("b", 400, 0, 100, 100, tag="Icon"),
            box("wall", 200, 0, 60, 100, tag="Icon"),
        ], "connections": [edge("a", "b", [(100, 50), (400, 50)])],
            "scene": {"x": 0, "y": 0, "width": 1000, "height": 100}}

    def test_a_connector_over_a_box_fails(self):
        report = routing.check(self.document())
        self.assertFalse(report["ok"])
        self.assertEqual("fail", report["checks"]["H1"])

    def test_an_aspect_ratio_is_reported_not_failed(self):
        doc = self.document()
        doc["entities"] = [dict(e, icon="server") for e in doc["entities"][:2]]
        doc["connections"] = []
        report = routing.check(doc)
        self.assertEqual("note", report["checks"]["H10"])
        self.assertTrue(report["ok"], report["findings"])

    def test_an_icon_with_no_artwork_at_all_fails(self):
        """H8. A node drawing nothing is the placeholder the brief rules out."""
        doc = self.document()
        doc["connections"] = []
        report = routing.check(doc)
        self.assertEqual("fail", report["checks"]["H8"])


class TheCrossingBudgetScalesWithTheGraph(unittest.TestCase):
    """Zero crossings is a planarity question. Two components reaching the same two others form
    a K(2,2), which cannot be drawn in two layers without one — so a constant budget of one
    would mean a required output some real architectures can never produce."""

    def document(self, edges):
        entities = [box(f"n{i}", i * 200, 0, 60, 60, tag="Icon") for i in range(8)]
        return {"entities": entities, "connections": edges,
                "scene": {"x": 0, "y": 0, "width": 1600, "height": 800}}

    def test_one_crossing_in_a_small_graph_is_tolerated(self):
        edges = [edge("n0", "n1", [(60, 30), (200, 30)])]
        report = routing.check(self.document(edges))
        self.assertEqual(1, report["crossing_budget"])

    def test_the_budget_grows_with_the_edge_count(self):
        edges = [edge("n0", "n1", [(60, i * 10), (200, i * 10)]) for i in range(20)]
        report = routing.check(self.document(edges))
        self.assertEqual(2, report["crossing_budget"])


class AnAcceptedCrossingIsStillReported(unittest.TestCase):
    """passenger-seat, 2026-11-10: a true graph whose floor was eight crossings against a budget of
    three. The operator may accept more, by number and with a reason; nothing is hidden and the
    first crossing past what they accepted still fails."""

    def document(self):
        entities = [box(f"n{i}", 900 + i * 80, 900, 40, 40, tag="Icon") for i in range(8)]
        edges = [edge("n0", "n1", [(0, 100), (500, 100)]), edge("n2", "n3", [(0, 200), (500, 200)]),
                 edge("n4", "n5", [(100, 0), (100, 300)]), edge("n6", "n7", [(300, 0), (300, 300)])]
        return {"entities": entities, "connections": edges,
                "scene": {"x": 0, "y": 0, "width": 1600, "height": 1000}}

    def test_without_an_allowance_the_excess_fails(self):
        report = routing.check(self.document())
        self.assertEqual(4, report["edge_crossings"])
        self.assertEqual("fail", report["checks"]["H2"])

    def test_an_allowance_covers_exactly_what_was_accepted(self):
        accepted = {"crossings": 3, "why": "true K(2,2)", "accepted_by": "operator"}
        report = routing.check(self.document(), allowance=accepted)
        self.assertEqual(2, report["accepted_crossings"])
        self.assertEqual("fail", report["checks"]["H2"], "the fourth crossing was never accepted")

    def test_a_full_allowance_passes_as_a_note_and_says_who(self):
        accepted = {"crossings": 4, "why": "true K(2,2)", "accepted_by": "operator"}
        report = routing.check(self.document(), allowance=accepted)
        self.assertEqual("note", report["checks"]["H2"])
        self.assertFalse([f for f in report["findings"]
                          if f.get("check") == "H2" and f["severity"] == "fail"])
        self.assertIn("ACCEPTED by operator", report["checked"])
        self.assertEqual(3, sum(1 for f in report["findings"]
                                if f.get("kind") == "edge_crossing_accepted"))

    def test_an_allowance_without_a_reason_is_refused(self):
        with self.assertRaises(SystemExit):
            routing.check(self.document(), allowance={"crossings": 4})


class TheRendererMustDrawWhatWasAuthored(unittest.TestCase):
    """An authored polyline is adopted only when it is strictly orthogonal and clears every
    obstacle; otherwise the renderer re-routes it and says nothing."""

    def test_a_replaced_route_is_a_finding(self):
        authored = {"entities": [], "connections": [edge("a", "b", [(0, 0), (100, 0)])]}
        measured = {"entities": [], "connections": [edge("a", "b", [(0, 0), (0, 80), (100, 80)])]}
        verdict = routing.adopted(authored, measured)
        self.assertEqual(["a -> b"], verdict["replaced"])

    def test_an_untouched_route_is_not(self):
        same = {"entities": [], "connections": [edge("a", "b", [(0, 0), (100, 0)])]}
        self.assertEqual([], routing.adopted(same, same)["replaced"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
