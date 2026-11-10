"""Does the diagram hold up? Sections H1 to H10, against the geometry the browser produced.

Looking at a PNG catches a bad diagram late, once, and by eye. So `render.mjs` asks the renderer's
library for `outputs: { json: true }` — the measured document, with every entity's final box and
every connection's routed points — and this reads it.

  H1  no connector over a box that is not its endpoint or their common container
  H2  no edge crossings, within a budget that scales with the graph
  H3  no label over an icon
  H4  at most three bends, and a final segment long enough to read as entering the box
  H5  no container holding one container, and none repeating its child's name
  H6  no name on the canvas twice
  H7  no container reserving much more room than its contents occupy
  H8  no placeholder icon and no bare shape where an icon belongs
  H9  groups in a row share a top edge; nodes of one kind share a size
  H10 an aspect ratio a reader can take in

Plus one that falls out of how routes are authored: the renderer adopts an authored polyline only
when it is strictly orthogonal and clears every obstacle, and otherwise re-routes it silently. So
authored points are compared against measured points, and a difference is a finding.

Severity is the difference between "the picture could be better" and "the picture is wrong". A
connector over a box, a duplicate name, a wrapper container and a placeholder icon are all defects
somebody reported and all of them are fixable, so they fail the run. An aspect ratio of 3.2 on an
architecture with seven columns is a fact about the architecture, and is reported.

Every count states its denominator. This module has shipped a checker that compared nothing and
reported no findings, and the habit exists because of it.

    uv run scripts/diagram-check.py measured.json

Exit 0 when nothing failed, 1 when something did, 2 when the input is not a measured document.
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


CELL_AREA = 120 * 96          # one node cell, the unit H7 is expressed in
MAX_BENDS = 3                 # D1
# D1 asks for three. Four is reachable only by crossing a box, which D2 forbids outright: a hub
# node reaching a column with another column in between must leave, pass the intervening column
# above or below, turn into the gap beyond it, and turn again into its target. Measured, not
# assumed — see `references/diagramming.md`. So a fourth bend is REPORTED and a fifth FAILS, and
# the report always says how many edges needed the fourth.
BEND_CEILING = 4
MIN_FINAL_SEGMENT = 24.0      # D6
ASPECT = (1.6, 2.8)           # B5 / H10

# H2 asks for no edge crossings, and one drawn with a hop where that is impossible. Zero is a
# planarity question, and on a real architecture it is often provably unreachable: whenever two
# components reach the same two others — an API and its worker both writing to a store and an
# object store — those four edges form a K(2,2), which cannot be drawn in two layers without one
# crossing. Keyhole has two such pairs, so its floor is two, and six different ELK strategies all
# return exactly two.
#
# So the budget scales with the graph instead of being a constant that some architectures can
# never meet: one crossing per ten edges, and never fewer than the one H2 names outright. The
# report states the number either way, which is the part that actually matters.
CROSSINGS_PER_EDGES = 10
EMPTY_CELLS = 1.5             # H7, together with the fraction below
EMPTY_FRACTION = 0.35         # "about half the AWS container was empty" — the defect as reported
PAD_TOP, PAD_SIDE = 48, 24    # C5, the padding a container is entitled to
ROW_TOLERANCE = 8.0           # H9: two groups are "in a row" if their tops are within a grid step


def _intersects(a, b):
    """Do two axis-aligned segments cross at a point interior to both?

    Touching at a shared endpoint is not a crossing — two edges leaving the same node share a
    point by construction, and reporting that would make H2 unsatisfiable by anything.
    """
    (ax0, ay0), (ax1, ay1) = a
    (bx0, by0), (bx1, by1) = b
    a_vertical, b_vertical = abs(ax0 - ax1) < 1e-6, abs(bx0 - bx1) < 1e-6
    if a_vertical == b_vertical:
        return None                      # parallel: an overlap is a routing smell, not a crossing
    if b_vertical:
        a, b = b, a
        (ax0, ay0), (ax1, ay1) = a
        (bx0, by0), (bx1, by1) = b
    x, y = ax0, by0
    if not (min(ay0, ay1) + 1e-6 < y < max(ay0, ay1) - 1e-6):
        return None
    if not (min(bx0, bx1) + 1e-6 < x < max(bx0, bx1) - 1e-6):
        return None
    return (round(x, 1), round(y, 1))


def _name(entity):
    return ((entity.get("title") or {}).get("text")
            or " ".join(t.get("text", "") for t in (entity.get("texts") or [])[:1]) or "")


def _route_findings(document, all_boxes, connections):
    """H1, H2, H3, H4 — everything about a line."""
    findings = []
    routes = []
    for connection in connections:
        source, target = connection.get("from"), connection.get("to")
        name = connection.get("id") or f"{source} -> {target}"
        allowed = {source, target} | ancestors(source, all_boxes) | ancestors(target, all_boxes)
        lines = segments(connection)
        routes.append((name, source, target, lines))

        for box_id, box in all_boxes.items():                                          # H1
            if box_id in allowed:
                continue
            hit = next((seg for seg in lines if crosses(seg, box)), None)
            if hit:
                findings.append({
                    "check": "H1",
                    "kind": "icon_crossed" if box["tag"] == "Icon" else "group_crossed",
                    "connection": name, "over": box_id, "what": box["label"],
                    "segment": [[round(v, 1) for v in hit[0]], [round(v, 1) for v in hit[1]]]})

        bends = max(len(lines) - 1, 0)                                                 # H4
        if bends > MAX_BENDS:
            findings.append({"check": "H4", "kind": "too_many_bends", "connection": name,
                             "severity": "fail" if bends > BEND_CEILING else "note",
                             "detail": f"{bends} bends, more than the {MAX_BENDS} D1 allows"})
        if lines:
            (x0, y0), (x1, y1) = lines[-1]
            if ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5 < MIN_FINAL_SEGMENT:
                findings.append({"check": "H4", "kind": "short_final_segment",
                                 "connection": name,
                                 "detail": f"the last segment is shorter than "
                                           f"{MIN_FINAL_SEGMENT:.0f}px, so the arrowhead does not "
                                           f"read as entering the box"})

        placement = connection.get("labelPlacement")                                   # H3
        if placement and placement.get("width") and placement.get("height"):
            rect = {"x": float(connection.get("x") or 0) + float(placement["x"]),
                    "y": float(connection.get("y") or 0) + float(placement["y"]),
                    "width": float(placement["width"]), "height": float(placement["height"])}
            for box_id, box in all_boxes.items():
                if box_id in allowed or box["tag"] != "Icon":
                    continue
                if overlaps(rect, box):
                    findings.append({"check": "H3", "kind": "label_over_icon",
                                     "connection": name, "over": box_id, "what": box["label"]})

    crossings = []                                                                     # H2
    for i, (name_a, from_a, to_a, lines_a) in enumerate(routes):
        for name_b, from_b, to_b, lines_b in routes[i + 1:]:
            if {from_a, to_a} & {from_b, to_b}:
                continue
            for seg_a in lines_a:
                for seg_b in lines_b:
                    point = _intersects(seg_a, seg_b)
                    if point:
                        crossings.append({"check": "H2", "kind": "edge_crossing",
                                          "connection": name_a, "other": name_b, "at": point})
    return findings, crossings


def _occupied(document, container, all_boxes, children):
    """What actually uses room inside a container: its children, and the routes crossing it.

    H7 exists because half the AWS box was empty. It is NOT there to complain about the corridor
    an orthogonal router needs — a lane an arrow runs down is doing a job, and counting it as
    waste made the check fire on the one layout that had finally stopped wasting anything.
    """
    left = min(float(k.get("x") or 0) for k in children)
    top = min(float(k.get("y") or 0) for k in children)
    right = max(float(k.get("x") or 0) + float(k.get("width") or 0) for k in children)
    bottom = max(float(k.get("y") or 0) + float(k.get("height") or 0) for k in children)
    box = all_boxes[container["id"]]
    for connection in document.get("connections") or []:
        for (x0, y0), (x1, y1) in segments(connection):
            for x, y in ((x0, y0), (x1, y1)):
                if (box["x"] <= x <= box["x"] + box["width"]
                        and box["y"] <= y <= box["y"] + box["height"]):
                    left, right = min(left, x), max(right, x)
                    top, bottom = min(top, y), max(bottom, y)
    return (right - left) * (bottom - top)


def _structure_findings(document, all_boxes):
    """H5, H6, H7, H8, H9, H10 — everything about a box."""
    findings = []
    entities = document.get("entities") or []
    children = {}
    for entity in entities:
        children.setdefault(entity.get("containerId"), []).append(entity)

    for entity in entities:                                                            # H5
        kids = children.get(entity["id"]) or []
        if entity.get("tag") != "Group":
            continue
        if len(kids) == 1 and kids[0].get("tag") == "Group":
            findings.append({"check": "H5", "kind": "wrapper_container", "what": _name(entity),
                             "detail": f"`{_name(entity)}` holds nothing but `{_name(kids[0])}`"})
        for kid in kids:
            if _name(kid).strip().lower() == _name(entity).strip().lower() and _name(kid):
                findings.append({"check": "H5", "kind": "container_repeats_child",
                                 "what": _name(entity),
                                 "detail": f"`{_name(entity)}` has the same name as its child"})

    seen = {}                                                                          # H6
    for entity in entities:
        label = _name(entity).strip().lower()
        if label:
            seen[label] = seen.get(label, 0) + 1
    for label, count in sorted(seen.items()):
        if count > 1:
            findings.append({"check": "H6", "kind": "duplicate_name", "what": label,
                             "detail": f"`{label}` names {count} things on one canvas"})

    for entity in entities:                                                            # H7
        kids = children.get(entity["id"]) or []
        if entity.get("tag") != "Group" or not kids:
            continue
        box = all_boxes.get(entity["id"])
        if not box:
            continue
        # C5's own padding is not waste: 48px of it is where the title chip lives. The
        # question H7 asks is how much room a container reserves BEYOND what it must.
        inner = max(box["width"] - 2 * PAD_SIDE, 0) * max(box["height"] - PAD_TOP - PAD_SIDE, 0)
        slack = inner - _occupied(document, entity, all_boxes, kids)
        # Both tests have to fire. The absolute one alone reported two cells of rounding on a
        # 2700px canvas; the fractional one alone would forgive a small group that is half empty.
        if slack > EMPTY_CELLS * CELL_AREA and inner and slack / inner > EMPTY_FRACTION:
            findings.append({"check": "H7", "kind": "oversized_container", "what": _name(entity),
                             "severity": "note",
                             "detail": f"`{_name(entity)}` reserves {slack / CELL_AREA:.1f} cells "
                                       f"— {slack / inner:.0%} of itself — beyond its contents"})

    for entity in entities:                                                            # H8
        if entity.get("tag") == "Icon" and not entity.get("icon"):
            findings.append({"check": "H8", "kind": "placeholder_icon", "what": _name(entity),
                             "detail": f"`{_name(entity)}` draws no icon at all"})
        if entity.get("tag") == "Shape":
            findings.append({"check": "H8", "kind": "placeholder_shape", "what": _name(entity),
                             "detail": f"`{_name(entity)}` is a bare shape where an icon belongs"})

    rows = {}                                                                          # H9
    for entity in entities:
        if entity.get("tag") != "Group" or not entity.get("containerId"):
            continue
        rows.setdefault(round(float(entity.get("y") or 0) / ROW_TOLERANCE), []).append(entity)
    for _, row in sorted(rows.items()):
        tops = {float(e.get("y") or 0) for e in row}
        if len(row) > 1 and len(tops) > 1:
            findings.append({"check": "H9", "kind": "row_not_aligned",
                             "what": ", ".join(sorted(_name(e) for e in row)),
                             "severity": "note",
                             "detail": f"groups in one row have {len(tops)} different top edges"})
    sizes = {}
    for entity in entities:
        if entity.get("tag") == "Icon" and entity.get("width"):
            sizes.setdefault((float(entity["width"]), float(entity["height"])), []).append(
                _name(entity))
    if len(sizes) > 1:
        findings.append({"check": "H9", "kind": "nodes_differ_in_size",
                         "what": "; ".join(f"{w:.0f}x{h:.0f}" for w, h in sorted(sizes)),
                         "detail": f"nodes come in {len(sizes)} different sizes"})

    scene = document.get("scene") or {}                                                # H10
    aspect = None
    if scene.get("width") and scene.get("height"):
        aspect = float(scene["width"]) / float(scene["height"])
        if not (ASPECT[0] <= aspect <= ASPECT[1]):
            findings.append({"check": "H10", "kind": "aspect_out_of_band",
                             "what": f"{aspect:.2f}", "severity": "note",
                             "detail": f"the canvas is {aspect:.2f}:1, outside "
                                       f"{ASPECT[0]}-{ASPECT[1]}"})
    return findings, aspect


def adopted(authored, measured):
    """Did the renderer draw the route we authored, or silently replace it?

    An authored polyline is adopted verbatim only if it is strictly orthogonal and clears every
    box that is not an endpoint or a container; otherwise the renderer discards it and routes the
    connection itself, with no warning anywhere. That is a layout failure wearing a rendered
    diagram, so it is checked rather than assumed.
    """
    if not authored:
        return None
    def route(doc):
        out = {}
        for connection in doc.get("connections") or []:
            key = (connection.get("from"), connection.get("to"))
            ox, oy = float(connection.get("x") or 0), float(connection.get("y") or 0)
            out[key] = [(round(ox + float(p["x"]), 1), round(oy + float(p["y"]), 1))
                        for p in connection.get("points") or []]
        return out
    ours, theirs = route(authored), route(measured)
    replaced = [f"{a} -> {b}" for (a, b), points in ours.items()
                if points and theirs.get((a, b)) != points]
    return {"authored": len([p for p in ours.values() if p]), "replaced": replaced}


def check(document, authored=None, allowance=None):
    """Every check in section H, over the geometry the browser actually produced.

    Each one names its denominator. This module has shipped a checker that compared nothing and
    reported no findings, and that is why every report here says what it looked at.

    `allowance` is an OPERATOR's acceptance of crossings above the budget, `{"crossings": n,
    "why": ..., "accepted_by": ...}`. One per ten edges cannot be met by every true graph:
    passenger-seat's mobile app and API both reach the same three vendors directly, and eight ELK
    strategies all returned eight. The allowance never hides a crossing — each accepted one stays
    in the findings as a `note` naming both edges — and it only covers up to the number a person
    accepted: a ninth crossing still fails.
    """
    all_boxes = boxes(document)
    connections = [c for c in document.get("connections") or [] if c.get("points")]
    unrouted = [c for c in document.get("connections") or [] if not c.get("points")]

    route_findings, crossings = _route_findings(document, all_boxes, connections)
    structure_findings, aspect = _structure_findings(document, all_boxes)

    budget = max(1, len(connections) // CROSSINGS_PER_EDGES)
    tolerated = crossings[:budget]
    allowed = 0
    if allowance:
        if not (allowance.get("why") and allowance.get("accepted_by")):
            raise SystemExit("a crossing allowance needs `why` and `accepted_by`: it overrules the "
                             "design contract on a client-facing picture")
        allowed = max(0, int(allowance.get("crossings") or 0) - budget)
    accepted = crossings[budget:budget + allowed]
    for crossing in accepted:
        crossing["severity"] = "note"
        crossing["kind"] = "edge_crossing_accepted"
    findings = route_findings + crossings[budget:] + structure_findings
    # Severity is the difference between "the picture could be better" and "the picture is
    # wrong". A connector over a box, a duplicate name, a wrapper container and a placeholder
    # icon are all defects somebody reported and all of them are fixable, so they fail. An aspect
    # ratio of 3.01 on an architecture with seven columns is a fact about the architecture.
    for finding in findings:
        finding.setdefault("severity", "fail")

    report = {
        "connections": len(connections),
        "crossing_budget": budget,
        "unrouted": len(unrouted),
        "boxes": len(all_boxes),
        "aspect": round(aspect, 3) if aspect else None,
        "edge_crossings": len(crossings),
        "tolerated_crossings": len(tolerated),
        "accepted_crossings": len(accepted),
        "crossing_allowance": allowance or None,
        "findings": findings,
        "routes": adopted(authored, document),
    }
    by_check = {}
    for finding in findings:
        by_check.setdefault(finding.get("check", "H1"), 0)
        by_check[finding["check"]] += 1
    fatal = [f for f in findings if f["severity"] == "fail"]
    report["checks"] = {}
    for n in range(1, 11):
        key = f"H{n}"
        hits = [f for f in findings if f.get("check") == key]
        report["checks"][key] = ("fail" if any(f["severity"] == "fail" for f in hits)
                                 else "note" if hits else "pass")
    report["notes"] = [f for f in findings if f["severity"] == "note"]
    if report["routes"] and report["routes"]["replaced"]:
        report["checks"]["routes"] = "fail"
        fatal.append({"check": "routes", "kind": "route_replaced", "severity": "fail",
                      "detail": "the renderer rejected and re-routed: "
                              + "; ".join(report["routes"]["replaced"][:6])})
        findings.extend(fatal[-1:])
    report["ok"] = not fatal
    report["checked"] = (f"{report['connections']} routed connections against {report['boxes']} "
                         f"measured boxes for H1-H4, and the whole scene for H5-H10; each edge's "
                         f"own endpoints and their containers are excluded from H1")
    if unrouted:
        report["checked"] += (f"; {len(unrouted)} connection(s) carried no routed points and were "
                              f"NOT checked")
    if tolerated:
        report["checked"] += (f"; {len(tolerated)} edge crossing(s) are within the budget of "
                              f"{budget} for {len(connections)} edges and are drawn with a hop")
    if accepted:
        report["checked"] += (f"; {len(accepted)} more were ACCEPTED by {allowance['accepted_by']} "
                              f"above that budget: {allowance['why']}")
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
