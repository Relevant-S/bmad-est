#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""The semantic graph, laid out by ELK, written as a renderer document.

This file used to compute every coordinate itself, from a box model that grew a constant per
defect: `TIER_GAP`, `BAND_GAP`, `ROW_GAP`, `LANE`, `ROW_WIDTH_BUDGET`. It produced a 2x3 grid
with no reading direction, containers half empty, and nodes in one group sitting at four
different heights. Language models are bad at geometry and so are hand-written box models.

So nothing here decides where anything goes. `graph.py` says WHAT, `elk.mjs` says WHERE, and this
file is the adapter between them and the renderer:

  * it sizes a cell, because ELK needs leaf dimensions and the renderer measures text only after
    it has already been placed;
  * it snaps the result to the 8px grid;
  * it writes the eraser document — every entity's box, every connection's ROUTE.

That last one is the change that matters. An authored polyline that is strictly orthogonal and
clears every non-endpoint box is adopted by the renderer verbatim and never routed
(`render/dist/browser/route.js`), so ELK's routing is what gets drawn. It also means the renderer's
own router does no work at all, which is what makes node-level edges affordable: aggregating edges
to their groups existed because obstacle-aware routing of twenty-one edges took eighty seconds,
and it was also what hid a false graph behind six plausible arrows.

    uv run scripts/layout.py <architecture.json> [-o diagram.json]
"""

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import importlib.util            # noqa: E402

import graph as semantic          # noqa: E402
import theme as design            # noqa: E402


def _sibling(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


check = _sibling("diagram_check", "diagram-check.py")

# Step 5: "If any check fails, adjust the input and re-run the layout, up to 3 iterations."
# The checks that matter here — bends, edge crossings, a line over a box — are all computable
# from the AUTHORED document, so an iteration costs an ELK call rather than a browser boot and
# the loop can actually run on every diagram instead of being a thing the docs promise.
VARIANTS = (
    {},
    {"elk.layered.nodePlacement.strategy": "BRANDES_KOEPF"},
    {"elk.layered.crossingMinimization.strategy": "LAYER_SWEEP",
     "elk.layered.thoroughness": "30"},
    {"elk.layered.crossingMinimization.semiInteractive": "true",
     "elk.layered.thoroughness": "50"},
    {"elk.layered.nodePlacement.strategy": "LINEAR_SEGMENTS",
     "elk.layered.thoroughness": "30"},
)

GRID = 8

# C2/C8. One cell size for the whole diagram, so a node never changes size because its name is
# long. G7's answer to a long name is to wrap it, and then to shorten it.
CELL_W = design.CELL_W
WRAP_W = CELL_W - GRID
# G7: two lines, "3 only as an exception". `Stripe Connect Express + Stripe Billing` is that
# exception — a composite label the profiles carry as one product — and clipping it would be a
# worse answer than a slightly taller cell.
MAX_NAME_LINES = 2
NAME_LINE_CEILING = 3

# Roughly how wide a character is, as a fraction of the font size. The renderer measures text in
# Chromium and will not tell anybody beforehand — there is no exported measurement helper — and
# ELK needs a size before the browser has ever booted. So this estimates, the cell is fixed so an
# estimate cannot move a box, and `diagram-check.py` verifies the real line count against the
# geometry the browser actually produced.
_NARROW = set("iljItf.,:;'`|!()[]{}/\\ ")
_WIDE = set("mwMW@")


def text_width(text, px):
    total = 0.0
    for ch in text:
        total += px * (0.30 if ch in _NARROW else 0.86 if ch in _WIDE else 0.55)
    return total


def wrap(text, px, width=WRAP_W):
    """Greedy wrap at the cell width. Returns the lines it would take."""
    lines, current = [], ""
    for word in (text or "").split():
        trial = f"{current} {word}".strip()
        if current and text_width(trial, px) > width:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    return lines or [""]


def cell_height(t, nodes=()):
    """Icon, gap, name lines, role line — ONE size for the whole diagram.

    C8 says a node's size may not depend on how long its own name is, so this is computed from
    the longest name on the canvas and then applied to every cell. Two lines is the target and
    the floor; a third is G7's stated exception and buys a taller row rather than a clipped
    label. Anything past that is a name the design should shorten, and `name_overflow` says so.
    """
    longest = max((len(wrap(n.get("name", ""), t["type"]["node_name"]["px"])) for n in nodes),
                  default=MAX_NAME_LINES)
    lines = min(max(longest, MAX_NAME_LINES), NAME_LINE_CEILING)
    return snap(t["cell"]["icon"] + t["cell"]["gap"] + lines * design.NAME_LINE
                + design.ROLE_LINE)


def name_overflow(nodes, t=None):
    """Names that need more lines than G7 allows even as an exception."""
    t = t or design.tokens()
    return sorted(n["name"] for n in nodes
                  if len(wrap(n.get("name", ""), t["type"]["node_name"]["px"]))
                  > NAME_LINE_CEILING)


def snap(value):
    """Step 4. Every coordinate on the 8px grid.

    Boxes and route points are snapped by the SAME function, which is what keeps an arrowhead on
    its box: a route point that sits exactly on a node's edge shares that edge's coordinate, so
    the two land on the same grid line. An axis-aligned segment stays axis-aligned for the same
    reason — both of its ends carry the identical coordinate to snap.

    The cost is up to 4px of the clearance ELK reserved, which is why `elk.spacing.edgeNode` is
    asked for 24 rather than D3's 16.
    """
    return int(round(float(value) / GRID) * GRID)


def elk_layout(request, renderer_dir=None, timeout=120):
    """Run `elk.mjs`. Returns None when Node or elkjs is absent, so a caller can say so."""
    node = shutil.which("node")
    script = HERE / "elk.mjs"
    directory = Path(renderer_dir) if renderer_dir else (HERE.parent / "assets" / "renderer")
    entry = directory / "node_modules" / "elkjs"
    if not (node and script.exists() and entry.exists()):
        return None
    payload = dict(request, elkPath=str(entry))
    try:
        done = subprocess.run([node, str(script)], input=json.dumps(payload), text=True,
                              capture_output=True, timeout=timeout, cwd=str(directory))
    except (OSError, subprocess.SubprocessError) as error:
        return {"ok": False, "error": str(error)}
    try:
        return json.loads(done.stdout or "{}")
    except ValueError:
        return {"ok": False, "error": (done.stderr or done.stdout or "")[:400]}


def elk_request(g, t):
    """The semantic graph, sized, in ELK's shape."""
    height = cell_height(t, g["nodes"])
    nodes = [dict(node, width=CELL_W, height=height) for node in g["nodes"]]
    edges = []
    for i, edge in enumerate(g["edges"]):
        label = edge.get("label") or ""
        lines = wrap(label, t["type"]["edge_label"]["px"], 148) if label else []
        edges.append(dict(edge, id=f"edge-{i}",
                          labelWidth=int(max((text_width(l, t["type"]["edge_label"]["px"])
                                              for l in lines), default=0)) + 8 if lines else 0,
                          labelHeight=int(len(lines) * t["type"]["edge_label"]["px"] * 1.4) + 4
                          if lines else 0))
    return {"graph": {"zones": g["zones"], "groups": g["groups"], "nodes": nodes, "edges": edges,
                      "padding": t["padding"],
                      "spacing": {"cellX": t["cell"]["gap_x"], "cellY": t["cell"]["gap_y"]}},
            "options": {"elk.spacing.nodeNode": str(t["cell"]["gap_x"]),
                        # D3 asks for 16px clearance; the 8px snap can spend 4 of it, so ELK is
                        # asked for 24 and the check still measures what actually happened.
                        "elk.spacing.edgeNode": "24",
                        # D1 allows three bends. ELK will happily spend more, and every one of
                        # them is a corner the reader has to follow.
                        "elk.layered.unnecessaryBendpoints": "true",
                        "elk.layered.nodePlacement.favorStraightEdges": "true"}}


def _group_entity(item, box, t, container=None, zone=False):
    ty = t["type"]["zone_title" if zone else "group_title"]
    entity = {
        "tag": "Group", "id": item["id"],
        "title": {"text": item["title"], "bgColor": t["chip_fill"], "border": True,
                  "color": t["ink"], "fontSize": ty["px"], "hAlign": "left", "width": "snug"},
        # E2/E3/E4/E7 are real props on the renderer's own schema, so they are authored rather
        # than styled: a renderer upgrade cannot silently drop them.
        "bgColor": t["zone_fill"] if zone else t["group_fill"],
        "borderColor": t["zone_border"] if zone else t["group_border"],
        "borderWidth": 1 if zone else 1.25,
        "cornerRadius": [t["radius"]] * 4,
        "styleMode": "plain" if zone else "shadow",
        "x": box["x"], "y": box["y"], "width": box["width"], "height": box["height"],
    }
    if container:
        entity["containerId"] = container
    if item.get("icon"):
        entity["title"]["icon"] = item["icon"]
        entity["title"]["iconProps"] = {"color": t["glyph"], "size": "sm"}   # F3: 12px, monochrome
    return entity


def _node_entity(node, box, t, icon_names=None, official=None):
    icon_names = icon_names or {}
    ty = t["type"]
    icon = icon_names.get(node["id"], node.get("icon") or "box")
    entity = {
        "tag": "Icon", "id": node["id"], "icon": icon,
        "x": box["x"], "y": box["y"], "width": box["width"], "height": box["height"],
        # A5. Two runs, two sizes, two inks — the product, then what it is. The renderer supports
        # per-run colour and size natively; what it does not support is weight, which the theme's
        # stylesheet supplies.
        "texts": [
            {"text": node["name"], "color": t["ink"], "fontSize": ty["node_name"]["px"]},
            {"text": node["role"], "color": t["muted"], "fontSize": ty["node_role"]["px"]},
        ],
    }
    # F2. Colour belongs to a vendor's own artwork; everything else — a capability nobody bought,
    # an actor, a product with no published mark — is one outline set in one ink.
    #
    # The test is whether the resolver found OFFICIAL art, not whether it returned a name: an
    # unresolved product still gets a name, its capability's glyph, so keying on the name counted
    # three grey glyphs as vendor logos.
    if not official or icon not in official:
        entity["color"] = t["glyph"]
    runtime_icon = icon_names.get(f"{node['id']}:runtime")
    if node.get("runtime"):
        # A3. The runtime is a badge, never a box. Two official icons, one node, and no second
        # container repeating the same name on the far side of the canvas.
        entity["badge"] = {"icon": runtime_icon or "server", "shape": "circle",
                           "placement": "top-right", "bgColor": t["chip_fill"], "padding": 2}
    return entity


# A step shorter than this is a jog rather than a turn: ELK routes around obstacles and leaves 2px
# and 9px steps behind that nobody can see and that D1 counts as bends. The threshold can be
# generous — five grid steps, well past the 24px clearance — because straightening is PROVED
# against every obstacle before it is kept, so the guarantee comes from the check and not from
# the number being small.
JOG = 6 * GRID

# D6. A final segment shorter than this does not read as entering the box.
MIN_FINAL = 24


def _cuts(a, b, box, tolerance=2.0):
    """Does the segment a-b enter the box's interior? Axis-aligned only, which is all we make."""
    left, right = box["x"] + tolerance, box["x"] + box["width"] - tolerance
    top, bottom = box["y"] + tolerance, box["y"] + box["height"] - tolerance
    if right <= left or bottom <= top:
        return False
    lo_x, hi_x = min(a["x"], b["x"]), max(a["x"], b["x"])
    lo_y, hi_y = min(a["y"], b["y"]), max(a["y"], b["y"])
    return lo_x < right and left < hi_x and lo_y < bottom and top < hi_y


def _clear(points, obstacles):
    return not any(_cuts(a, b, box) for a, b in zip(points, points[1:]) for box in obstacles)


def simplify(points, jog=JOG, obstacles=()):
    """Drop what is not a turn: duplicates, collinear points, and invisible jogs.

    The first measured route from NestJS to Stripe had eleven points and three visible corners.
    D1's "at most 3 bends" is a statement about what a reader has to follow, so the count has to
    be of corners rather than of vertices, and the honest way to make that true is to remove the
    vertices that are not corners rather than to loosen the rule.

    Every straightening is PROVED before it is kept. Removing a jog moves a line sideways, and a
    first version of this moved six of them into boxes — which the renderer then silently
    rejected and re-routed, turning a tidy-up into a layout nobody authored. A step that would
    cut an obstacle is reverted and the jog stays.
    """
    pts = [dict(p) for p in points]

    def collapse(seq):
        out = []
        for p in seq:
            if out and abs(out[-1]["x"] - p["x"]) < 0.5 and abs(out[-1]["y"] - p["y"]) < 0.5:
                continue
            if len(out) >= 2:
                a, b = out[-2], out[-1]
                if ((abs(a["x"] - b["x"]) < 0.5 and abs(b["x"] - p["x"]) < 0.5)
                        or (abs(a["y"] - b["y"]) < 0.5 and abs(b["y"] - p["y"]) < 0.5)):
                    out[-1] = p
                    continue
            out.append(p)
        return out

    pts = _uncurl(collapse(pts), collapse, obstacles)
    changed = True
    while changed and len(pts) > 3:
        changed = False
        for i in range(1, len(pts) - 2):
            a, b, c, d = pts[i - 1], pts[i], pts[i + 1], pts[i + 2]
            step = abs(b["x"] - c["x"]) + abs(b["y"] - c["y"])
            if step >= jog:
                continue
            a_horizontal = abs(a["y"] - b["y"]) < 0.5
            c_horizontal = abs(c["y"] - d["y"]) < 0.5
            if a_horizontal != c_horizontal:
                continue
            # Both neighbours run the same way, so the step between them is a jog. Straighten it
            # onto the longer of the two, which is the one the eye is already following.
            # Move one whole RUN onto the other, never the two vertices between them: setting
            # b and c alone leaves a-b diagonal, because a shares b's coordinate by definition.
            # The longer run stays put — it is the one the eye is already following.
            axis = "y" if a_horizontal else "x"
            along = "x" if a_horizontal else "y"
            first, second = abs(b[along] - a[along]), abs(d[along] - c[along])
            movers, target = ((c, d), a[axis]) if first >= second else ((a, b), d[axis])
            # A terminal vertex sits on its node's edge, so moving it slides the arrow along that
            # edge. A short slide is fine; a long one would take the arrowhead off the box.
            terminal = movers[0] is pts[0] or movers[-1] is pts[-1]
            if terminal and abs(movers[0][axis] - target) > 2 * GRID:
                continue
            keep = [dict(p) for p in pts]
            for mover in movers:
                mover[axis] = target
            candidate = collapse(pts)
            if obstacles and not _clear(candidate, obstacles):
                pts = keep
                continue
            pts = candidate
            changed = True
            break
    return _lengthen_ends(_uncurl(pts, collapse, obstacles), obstacles)


def _uncurl(points, collapse, obstacles):
    """Cut the excursion out of an out-and-back.

    A route that leaves a node rightwards, runs 320px further right, steps up, and then runs
    776px back to the LEFT has spent four bends going nowhere. It is what a layered router does
    with a back edge — the browser redirecting to an identity provider that sits in the first
    column — and it reads as a mistake because it is one.

    The shape is three segments: out, across, back, with the last reversing the first. Cutting it
    means turning across at the point the route started from instead of further along. Verified
    against the obstacles like every other straightening, and reverted if it would cut one.
    """
    pts = [dict(p) for p in points]
    changed = True
    while changed and len(pts) >= 4:
        changed = False
        for i in range(len(pts) - 3):
            a, b, c, d = pts[i], pts[i + 1], pts[i + 2], pts[i + 3]
            horizontal = abs(a["y"] - b["y"]) < 0.5 and abs(c["y"] - d["y"]) < 0.5
            vertical = abs(a["x"] - b["x"]) < 0.5 and abs(c["x"] - d["x"]) < 0.5
            along = "x" if horizontal else "y" if vertical else None
            if along is None:
                continue
            out = b[along] - a[along]
            back = d[along] - c[along]
            if out == 0 or back == 0 or (out > 0) == (back > 0):
                continue
            across = "y" if horizontal else "x"
            corner = {along: a[along], across: c[across]}
            candidate = collapse(pts[:i + 1] + [corner] + pts[i + 3:])
            if _clear(candidate, obstacles):
                pts = candidate
                changed = True
                break
    return pts


def _lengthen_ends(points, obstacles):
    """D6: the last segment enters the target perpendicularly and is long enough to read as one.

    A route that turns a few pixels short of its target leaves the arrowhead sitting on a corner.
    Pulling the turn back is safe in exactly the same way straightening is — it is tried and
    reverted if it would cut something.
    """
    if len(points) < 3:
        return points
    for index, neighbour in ((len(points) - 1, len(points) - 2), (0, 1)):
        tip, turn = points[index], points[neighbour]
        span = abs(tip["x"] - turn["x"]) + abs(tip["y"] - turn["y"])
        if span >= MIN_FINAL or span == 0:
            continue
        keep = [dict(p) for p in points]
        axis = "x" if abs(tip["x"] - turn["x"]) > abs(tip["y"] - turn["y"]) else "y"
        direction = 1 if turn[axis] > tip[axis] else -1
        beyond = points[neighbour + (1 if index == 0 else -1)]
        turn[axis] = beyond[axis] = tip[axis] + direction * MIN_FINAL
        if not _clear(points, obstacles):
            points = keep
    return points


def _label_spot(points, width, height):
    """Centred on the longest horizontal run, sitting just above the line.

    Horizontal by preference because the text is: a label beside a vertical segment has to be
    read across the arrow it belongs to. Returns None when there is no horizontal run long
    enough to hold the words, and the caller keeps what the layout engine suggested.
    """
    best = None
    for a, b in zip(points, points[1:]):
        if a["y"] != b["y"]:
            continue
        span = abs(b["x"] - a["x"])
        if span >= width + GRID and (best is None or span > best[0]):
            best = (span, (a["x"] + b["x"]) / 2, a["y"])
    if best is None:
        return None
    _, centre, line = best
    return {"x": int(centre - width / 2), "y": int(line - height - 4),
            "width": width, "height": height}


def _orthogonalise(before, after):
    """Force every segment back onto an axis after snapping.

    The renderer adopts an authored route only if it is STRICTLY orthogonal — one coordinate
    identical at both ends of every segment — and otherwise discards it and routes the connection
    itself, silently. ELK emits a vertical segment as x=982.0 and x=982.4, which reads as vertical
    everywhere except here: snapped independently those two land on different grid lines, and six
    routes were thrown away without a word. So the orientation is decided from the geometry BEFORE
    snapping, and the shared coordinate is then copied rather than rounded twice.
    """
    out = [dict(p) for p in after]
    for i in range(len(out) - 1):
        vertical = abs(before[i]["x"] - before[i + 1]["x"]) <= abs(before[i]["y"] - before[i + 1]["y"])
        if vertical:
            out[i + 1]["x"] = out[i]["x"]
        else:
            out[i + 1]["y"] = out[i]["y"]
    return out


def _polyline(points, obstacles=()):
    """Absolute route -> the renderer's element-relative `points`, with the origin it belongs to."""
    if not points:
        return None, None
    points = simplify(points, obstacles=obstacles)
    # Forcing segments back onto an axis creates new collinear runs and even duplicate points —
    # three vertices sharing a y where two did before. So simplify again AFTER snapping, which is
    # safe because the jog pass only ever equalises a coordinate and cannot tilt a segment.
    snapped = _orthogonalise(points, [{"x": snap(p["x"]), "y": snap(p["y"])} for p in points])
    snapped = simplify(snapped, obstacles=obstacles)
    origin = snapped[0]
    return origin, [{"x": p["x"] - origin["x"], "y": p["y"] - origin["y"]} for p in snapped]


def document(architecture, model=None, platforms=None, icon_names=None,
             renderer_dir=None, official=None):
    """`architecture.json` -> the renderer's document, with routes already decided.

    Runs the layout up to three times with different ELK strategies and keeps the best result
    measured against section H. Never a hand-drawn workaround edge: what changes between
    iterations is what ELK is asked, not what it answered.
    """
    t = design.tokens()
    g = semantic.build(architecture, model, platforms)
    request = elk_request(g, t)

    attempts, best, best_score = [], None, None
    for index, extra in enumerate(VARIANTS):
        trial = dict(request, options={**request["options"], **extra})
        laid = elk_layout(trial, renderer_dir)
        if not laid or not laid.get("ok"):
            if index == 0:
                raise LayoutUnavailable((laid or {}).get("error")
                                        or "elkjs is not installed; run /est-setup")
            continue
        candidate = _assemble(g, t, laid, icon_names, official)
        verdict = check.check(candidate)
        aspect = laid.get("aspect") or 0
        band = check.ASPECT
        # Ordered deliberately. Nothing broken comes first. Then SHAPE, because a canvas a
        # reader cannot take in at a glance is the defect that opened this work, and it outranks
        # one more four-bend edge. Notes break the remaining ties.
        distance = (0 if band[0] <= aspect <= band[1]
                    else min(abs(aspect - band[0]), abs(aspect - band[1])))
        score = (len([f for f in verdict["findings"] if f.get("severity") == "fail"]),
                 round(distance, 1),
                 len(verdict.get("notes") or []))
        attempts.append({"variant": extra or "contract defaults", "fatal": score[0],
                         "off_band": score[1], "notes": score[2],
                         "aspect": laid.get("aspect")})
        if best_score is None or score < best_score:
            best, best_score, best_laid = candidate, score, laid
        if score[0] == 0:
            break

    best["_layout"] = {"aspect": best_laid.get("aspect"), "attempts": best_laid.get("attempts"),
                       "iterations": attempts, "scene": best_laid.get("scene"), "graph": g,
                       "longest_edge": best_laid.get("longestEdge")}
    return best


def _assemble(g, t, laid, icon_names=None, official=None):
    """One ELK result, written as a renderer document."""
    boxes = {k: {"x": snap(v["x"]), "y": snap(v["y"]),
                 "width": snap(v["width"]), "height": snap(v["height"])}
             for k, v in laid["boxes"].items()}

    entities = []
    for zone in g["zones"]:
        if zone["id"] in boxes:
            entities.append(_group_entity(zone, boxes[zone["id"]], t, zone=True))
    for group in g["groups"]:
        if group["id"] in boxes:
            entities.append(_group_entity(group, boxes[group["id"]], t, container=group["zoneId"]))
    for node in g["nodes"]:
        if node["id"] in boxes:
            entity = _node_entity(node, boxes[node["id"]], t, icon_names, official)
            entity["containerId"] = node["groupId"] or node["zoneId"]
            entities.append(entity)

    parents = {n["id"]: (n["groupId"] or n["zoneId"]) for n in g["nodes"]}
    zone_of_group = {gr["id"]: gr["zoneId"] for gr in g["groups"]}

    def obstacles_for(edge):
        """Everything this edge may not touch: every box but its endpoints and their containers."""
        allowed = set()
        for end in (edge["from"], edge["to"]):
            allowed.add(end)
            parent = parents.get(end)
            while parent:
                allowed.add(parent)
                parent = zone_of_group.get(parent)
        return [boxes[k] for k in boxes if k not in allowed]

    connections = []
    for i, edge in enumerate(g["edges"]):
        routed = (laid.get("edges") or {}).get(f"edge-{i}") or {}
        origin, points = _polyline(routed.get("points") or [], obstacles_for(edge))
        connection = {
            "from": edge["from"], "to": edge["to"], "label": edge.get("label", ""),
            "endArrowhead": "triangle", "connectorStyle": "elbow", "cornerStyle": "elbow",
            "color": t["edge"], "labelColor": t["edge"],
            "lineWidth": t["line_width"], "fontSize": t["type"]["edge_label"]["px"],
        }
        if edge.get("style") == "async":
            connection["lineStyle"] = "dashed"
        if points and len(points) >= 2:
            connection["x"], connection["y"] = origin["x"], origin["y"]
            connection["points"] = points
            label = routed.get("label")
            if label and connection["label"]:
                # D7: the centre of the longest horizontal segment. NOT where ELK put it — that
                # position belongs to the route ELK returned, and simplification has since cut
                # the excursions out of it, which left one label sitting alone in empty space
                # a long way from its own arrow.
                place = _label_spot(points, int(label["width"]), int(label["height"]))
                connection["labelPlacement"] = place or {
                    "x": snap(label["x"]) - connection["x"],
                    "y": snap(label["y"]) - connection["y"],
                    "width": int(label["width"]), "height": int(label["height"])}
        connections.append(connection)

    return {"entities": entities, "connections": connections}


class LayoutUnavailable(RuntimeError):
    """ELK is a build requirement, not a nicety. Without it there is no diagram to degrade to."""


def overlaps(doc):
    """Siblings that collide in the AUTHORED geometry. Rendered geometry can still exceed it."""
    boxes = {}
    for entity in doc["entities"]:
        if entity.get("width") and entity.get("height"):
            boxes[entity["id"]] = entity
    found = []
    ids = list(boxes)
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            ea, eb = boxes[a], boxes[b]
            if ea.get("containerId") != eb.get("containerId"):
                continue
            if (ea["x"] < eb["x"] + eb["width"] and eb["x"] < ea["x"] + ea["width"]
                    and ea["y"] < eb["y"] + eb["height"] and eb["y"] < ea["y"] + ea["height"]):
                found.append((a, b))
    return found


def repeated_icons(components):
    """A note, not a failure: a vendor serving two capabilities draws its mark twice."""
    seen = {}
    for component in components:
        icon = component.get("icon")
        if icon:
            seen[icon] = seen.get(icon, 0) + 1
    return sorted(icon for icon, count in seen.items() if count > 1)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("architecture")
    ap.add_argument("-o", "--output")
    ap.add_argument("--platforms")
    args = ap.parse_args()

    import capabilities as caps
    architecture = json.loads(Path(args.architecture).read_text(encoding="utf-8"))
    platforms = json.loads(Path(args.platforms).read_text(encoding="utf-8")) if args.platforms \
        else caps.load_platforms()
    doc = document(architecture, caps.load_model(), platforms)
    text = json.dumps(doc, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
