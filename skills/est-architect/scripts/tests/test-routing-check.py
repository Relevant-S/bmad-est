#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Tests for routing-check.py — does any connector run over something it is not joined to?

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

routing = F.load("routing_check", F.ARCH / "scripts" / "routing-check.py")


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
        self.assertTrue(routing.check(self.document())["ok"])

    def test_an_icon_inside_an_endpoint_is_not_reported(self):
        report = routing.check(self.document())
        self.assertNotIn("deep", [f["over"] for f in report["findings"]])


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


if __name__ == "__main__":
    unittest.main(verbosity=1)
