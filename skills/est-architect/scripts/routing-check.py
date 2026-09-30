#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Does any connector run over something it is not connected to?

The renderer's router is obstacle-aware — orthogonal, container-aware, unlimited repair budget —
but it **falls back to a straight line when no corridor exists**. A layout that leaves 34px
between two tier groups gives it nowhere to go, and the fallback is an arrow straight through
whatever is in the way. Looking at a PNG catches that late, once, and by eye.

So this reads the MEASURED document — `render.mjs` with `outputs: { json: true }`, which returns
each connection's routed points in the geometry the browser actually laid out — and tests every
segment against every box it has no business touching.

A connector may legitimately overlap:

  * its own two endpoints, and
  * any ancestor of either endpoint — an edge from a tier group to a tier group in another band
    has to cross both bands to get there.

Everything else is a finding. Crossing an `Icon` is worse than crossing a `Group`: a group is a
boundary an arrow can plausibly pass through, an icon is a thing a reader is trying to read.

    uv run scripts/routing-check.py measured.json

Exit 0 when nothing crosses, 1 when something does, 2 when the input is not a measured document.
"""

import argparse
import json
import sys
from pathlib import Path

# Half a stroke plus a hair. An orthogonal route that runs along a box's edge shares coordinates
# with it by construction, and a shared edge is not a crossing.
TOLERANCE = 2.0


def boxes(document):
    """Every measured entity as an absolute box, with its container."""
    out = {}
    for entity in document.get("entities") or []:
        if entity.get("width") is None or entity.get("height") is None:
            continue
        out[entity["id"]] = {
            "id": entity["id"], "tag": entity.get("tag"),
            "x": float(entity.get("x") or 0), "y": float(entity.get("y") or 0),
            "width": float(entity["width"]), "height": float(entity["height"]),
            "container": entity.get("containerId"),
            "label": (entity.get("title") or {}).get("text")
                     or " ".join(t.get("text", "") for t in entity.get("texts") or []),
        }
    return out


def ancestors(box_id, all_boxes):
    seen, current = set(), all_boxes.get(box_id, {}).get("container")
    while current and current not in seen:
        seen.add(current)
        current = all_boxes.get(current, {}).get("container")
    return seen


def segments(connection):
    """Absolute segments. Points are relative to the connection's own origin."""
    ox, oy = float(connection.get("x") or 0), float(connection.get("y") or 0)
    points = [(ox + float(p["x"]), oy + float(p["y"]))
              for p in connection.get("points") or [] if isinstance(p, dict)]
    return list(zip(points, points[1:]))


def crosses(segment, box, tolerance=TOLERANCE):
    """Liang-Barsky: does the segment enter the box's interior?

    The box is shrunk by the tolerance on every side, so an arrow drawn along an edge — which an
    orthogonal router does constantly — is not reported.
    """
    (x0, y0), (x1, y1) = segment
    left, right = box["x"] + tolerance, box["x"] + box["width"] - tolerance
    top, bottom = box["y"] + tolerance, box["y"] + box["height"] - tolerance
    if right <= left or bottom <= top:
        return False
    dx, dy = x1 - x0, y1 - y0
    enter, leave = 0.0, 1.0
    for delta, start, low, high in ((dx, x0, left, right), (dy, y0, top, bottom)):
        if delta == 0:
            if start <= low or start >= high:
                return False
            continue
        near, far = (low - start) / delta, (high - start) / delta
        if near > far:
            near, far = far, near
        enter, leave = max(enter, near), min(leave, far)
        if enter >= leave:
            return False
    return True


def overlaps(rect, box, tolerance=TOLERANCE):
    return (rect["x"] < box["x"] + box["width"] - tolerance
            and box["x"] + tolerance < rect["x"] + rect["width"]
            and rect["y"] < box["y"] + box["height"] - tolerance
            and box["y"] + tolerance < rect["y"] + rect["height"])


def check(document):
    """Findings, plus the denominator. A checker that compared nothing also reports no findings."""
    all_boxes = boxes(document)
    connections = [c for c in document.get("connections") or [] if c.get("points")]
    report = {
        "connections": len(connections),
        "unrouted": len([c for c in document.get("connections") or [] if not c.get("points")]),
        "boxes": len(all_boxes),
        "findings": [],
    }
    for index, connection in enumerate(connections):
        source, target = connection.get("from"), connection.get("to")
        allowed = {source, target} | ancestors(source, all_boxes) | ancestors(target, all_boxes)
        name = connection.get("id") or f"{source} -> {target}"
        lines = segments(connection)
        for box_id, box in all_boxes.items():
            if box_id in allowed:
                continue
            hit = next((s for s in lines if crosses(s, box)), None)
            if hit:
                report["findings"].append({
                    "kind": "icon_crossed" if box["tag"] == "Icon" else "group_crossed",
                    "connection": name, "over": box_id, "what": box["label"],
                    "segment": [[round(v, 1) for v in hit[0]], [round(v, 1) for v in hit[1]]],
                })
        placement = connection.get("labelPlacement")
        if placement and placement.get("width") and placement.get("height"):
            rect = {"x": float(connection.get("x") or 0) + float(placement["x"]),
                    "y": float(connection.get("y") or 0) + float(placement["y"]),
                    "width": float(placement["width"]), "height": float(placement["height"])}
            for box_id, box in all_boxes.items():
                if box_id in allowed or box["tag"] != "Icon":
                    continue
                if overlaps(rect, box):
                    report["findings"].append({
                        "kind": "label_over_icon", "connection": name,
                        "over": box_id, "what": box["label"]})
    report["ok"] = not report["findings"]
    report["checked"] = (f"{report['connections']} routed connections against {report['boxes']} "
                         f"measured boxes, excluding each edge's own endpoints and their "
                         f"containers")
    if report["unrouted"]:
        report["checked"] += (f"; {report['unrouted']} connection(s) carried no routed points and "
                             f"were NOT checked")
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("measured", help="a measured document from render.mjs (outputs.json)")
    ap.add_argument("-o", "--output")
    args = ap.parse_args()

    document = json.loads(Path(args.measured).read_text(encoding="utf-8"))
    if not isinstance(document, dict) or "entities" not in document:
        print(f"{args.measured} is not a measured diagram document", file=sys.stderr)
        return 2
    report = check(document)
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
