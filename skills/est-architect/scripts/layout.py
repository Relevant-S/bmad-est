#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Turn an architecture into a positioned diagram document.

The renderer routes connections and measures text, and positions **nothing**: every entity
needs authored `x`/`y`. That is the trade this module accepted, and it is the right one here,
because the reference diagram's quality is its composition — bands, tiers, deliberate grouping
— and a layout engine would give a generic graph instead.

So the layout is computed, bottom-up, from a small box model:

    icon  ->  [runtime group]  ->  tier group  ->  tier row  ->  platform band  ->  canvas

Deterministic on purpose. The same architecture draws the same diagram every run, which is what
lets two readings of one project be diffed months apart. A model hand-placing forty nodes at
pixel coordinates could not offer that.

Two of those levels exist for reasons worth stating:

  * **a runtime group** — a thing the team writes and the thing that runs it are two items, and
    the diagram shows one inside the other. "Django on Fargate" was one box where there are two.
  * **a tier row** — the request path on one line and what it reaches on the next, so an edge
    from the application to a datastore is short and vertical. Laid out as one long line, the
    application's five edges had to cross every tier between them and the router, which avoids
    obstacles but cannot invent a corridor, ran them straight through.

    uv run scripts/layout.py <architecture.json> [-o diagram.json]
"""

import argparse
import collections
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BRAND = HERE.parent.parent / "est-estimate" / "assets" / "brand.json"

ICON_W, ICON_H, ICON_GAP = 168, 120, 22
GROUP_PAD = 30
# The title is a chip drawn INSIDE the top of its group, and the renderer measures text rather
# than trusting authored height — so content placed a nominal title's distance below the top
# lands on top of the chip. Measured against a rendered diagram rather than guessed: 72 clears
# a one-line title at the stock font with room for the group's own border and padding.
TITLE_H = 72
# Corridors. The renderer's router is obstacle-aware but falls back to a STRAIGHT LINE when no
# corridor exists, and a straight line through three components is the defect these numbers fix.
# 34px between tier groups was not a corridor; 80 is. Verified by `routing-check.py` against the
# measured geometry rather than by eye.
TIER_GAP, BAND_GAP, ROW_GAP = 80, 120, 80
# A clear lane along the bottom AND the right-hand side inside every band, so an edge leaving a
# band has a corridor to reach its boundary through. Without the right-hand lane the widest tier
# row ended 30px from the band's edge, and an edge from the application to a vendor outside turned
# down early and crossed the tier that happened to be in the corner.
LANE = 64
MARGIN = 60
MAX_COLUMNS = 2

# A platform earns its own boundary band by hosting the application or by serving several
# capabilities. A vendor that provides one thing is drawn in the shared third-party band, the
# way the reference diagram does it. Giving every vendor a full-height band produced eight
# bands on a 7:1 canvas, five of them holding one or two icons.
BAND_MIN_CAPABILITIES = 3

# Bands wrap into canvas rows past this width. One long strip is unreadable at any zoom — but
# wrapping too eagerly is worse: with the third-party band stacked BELOW the cloud band, every
# edge from the application had to leave through the row of tiers underneath it, and the router
# ran them over the datastore. Three bands side by side is the shape the reference uses and the
# shape whose edges have somewhere to go.
ROW_WIDTH_BUDGET = 3200

# Glyphs with no colour of their own. A vendor logo brings its own; these render as thin grey
# line-art unless they are told what colour to be, and a diagram of grey line-art is what the
# reference beats most obviously. Coloured BY TIER, so the colour carries meaning rather than
# decoration.
#
# The prop is `color`. `Icon`'s schema is {icon, size, texts, typeface, color, fontSize, badge}
# and `iconProps` belongs to `Shape` and to a group's title — an earlier version set `iconProps`
# on an Icon, which is not rejected and not read either, so the tinting did nothing at all.
GENERIC_ICONS = {
    "box", "bug", "chart", "chrome", "database", "file", "folder", "globe", "key", "laptop",
    "lock", "mail", "monitor", "phone", "search", "server", "shield", "smartphone", "sparkles",
    "user", "users",
}


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


caps = _load("capabilities", HERE / "capabilities.py")


def palette():
    """The company's own colours, so the diagram and the workbook are one identity.

    `tier_ink` gives each diagram column its own hue; generic glyphs are drawn in it, which is
    where the reference gets most of its colour. Falls back to the renderer's palette tokens if
    brand.json has moved — a diagram in the wrong blue is worth shipping; one that does not
    render is not.
    """
    try:
        light = json.loads(BRAND.read_text(encoding="utf-8"))["palette"]["light"]
        return {"band": light["brand"], "host_band": light["brand"],
                "other_band": light["line_strong"], "tier": light["brand_tint"],
                "runtime": light["line_strong"],
                "outside": light["line_strong"], "ink": light["ink"],
                "tier_ink": {"actors": light["brand"], "edge": light["danger"],
                             "application": light["brand"], "services": light["warn"],
                             "data": light["ok"], "external": light["brand_hover"]}}
    except (OSError, KeyError, ValueError):                     # pragma: no cover - env-specific
        grey = "black"
        return {"band": "blue", "host_band": "blue", "other_band": grey, "tier": "white",
                "runtime": grey, "outside": grey, "ink": grey,
                "tier_ink": {t: grey for t in
                             ("actors", "edge", "application", "services", "data", "external")}}


def grid(count):
    """Columns x rows for `count` icons. Two columns keeps a band narrow enough to read."""
    columns = min(MAX_COLUMNS, max(1, count))
    rows = -(-count // columns)
    return columns, rows


def cell_size(components):
    """One cell of a tier's grid. Uniform across the tier, sized to its largest occupant.

    A component drawn inside its runtime needs room for a titled group around the icon. Sizing
    every cell in the tier the same keeps the grid — and therefore the overlap guarantee —
    arithmetic rather than a packing problem.
    """
    if any(c.get("runs_on") for c in components):
        return GROUP_PAD * 2 + ICON_W, GROUP_PAD * 2 + TITLE_H + ICON_H
    return ICON_W, ICON_H


def tier_box(components):
    columns, rows = grid(len(components))
    width, height = cell_size(components)
    return (GROUP_PAD * 2 + columns * width + (columns - 1) * ICON_GAP,
            GROUP_PAD * 2 + TITLE_H + rows * height + (rows - 1) * ICON_GAP)


def repeated_icons(components):
    """Logos used more than once. A note, not a failure.

    A vendor that serves two capabilities draws its mark twice, because that is what is true of
    the system. The earlier rule sent the loser to a grey glyph, which cost `Sentry Uptime + Web
    Vitals` its Sentry mark — a substitute where official art exists.
    """
    counts = collections.Counter(c.get("icon") for c in components if c.get("icon"))
    return sorted(icon for icon, n in counts.items() if n > 1)


def tier_rows(model):
    """Which tiers share a row inside a band, left to right.

    The request path on the first row and what it reaches on the second. Declared in the model
    so it is data rather than a rule buried in the renderer.
    """
    declared = (model.get("tiers") or {}).get("rows")
    if declared:
        return [list(row) for row in declared]
    return [list((model.get("tiers") or {}).get("order") or [])]


def plan(architecture, model=None, icon_names=None):
    """Bands, their tier rows, their tier groups and every cell — measured, not yet placed."""
    model = model or caps.load_model()
    order = (model.get("tiers") or {}).get("order") or []
    tier_label = (model.get("tiers") or {}).get("labels") or {}
    rows_of = tier_rows(model)

    components = [dict(c) for c in architecture.get("components") or []]
    for component in components:
        if not icon_names:
            continue
        # The resolver hands back one icon per drawn thing, and a runtime is a drawn thing of its
        # own: two keys, two official icons, because they are two different products.
        if component["id"] in icon_names:
            component["icon"] = icon_names[component["id"]]
        runtime_key = f"{component['id']}:runtime"
        if component.get("runs_on") and runtime_key in icon_names:
            component["runs_on"] = dict(component["runs_on"], icon=icon_names[runtime_key])

    host = next((c.get("platform") for c in components
                 if c["capability"] == "application" and c.get("platform")), None)
    if host is None:
        host = next((c.get("platform") for c in components if c.get("platform")), None)
    reach = collections.Counter(c["platform"] for c in components if c.get("platform"))

    def band_of(component):
        if component["tier"] == "actors":
            return "_actors", "Users"
        pid = component.get("platform")
        if pid and (pid == host or reach[pid] >= BAND_MIN_CAPABILITIES):
            return pid, None
        if pid:
            # A vendor providing one or two things shares the third-party band. Eight bands on a
            # 7:1 canvas, five of them nearly empty, is what the alternative looked like.
            return "_external", "Third-party"
        if component["tier"] == "external":
            return "_external", "Third-party"
        # Built and adopted components are not floating in space: they run on whatever hosts
        # the application tier, and drawing them outside it stretched every edge across the
        # whole canvas while claiming the database sat outside the cloud.
        return (host, None) if host else ("_project", "Built by this project")

    bands = {}
    for component in components:
        key, label = band_of(component)
        band = bands.setdefault(key, {"id": key, "label": label, "tiers": {}, "platform": None})
        if key not in ("_actors", "_external", "_project"):
            band["platform"] = key
        band["tiers"].setdefault(component["tier"], []).append(component)

    laid = []
    for key, band in bands.items():
        rows = []
        placed = set()
        # Outside the platform boundaries a band stacks its tiers one per row. Side by side, the
        # third-party band hid its own Integrations tier behind Platform services, so an edge from
        # the application had to cross one to reach the other; stacked, both face the incoming
        # side. The platform bands keep the two-row request/reach arrangement, which is what
        # makes their internal edges short.
        band_rows = ([[t] for t in order if t in band["tiers"]]
                     if key in ("_actors", "_external", "_project") else rows_of)
        for row in band_rows:
            present = [t for t in row if t in band["tiers"]]
            if present:
                rows.append([(t, band["tiers"][t]) for t in present])
                placed.update(present)
        leftover = [t for t in order if t in band["tiers"] and t not in placed]
        leftover += [t for t in band["tiers"] if t not in placed and t not in leftover]
        if leftover:
            rows.append([(t, band["tiers"][t]) for t in leftover])
        measured = []
        for row in rows:
            boxes = [tier_box(items) for _, items in row]
            measured.append({
                "tiers": row, "boxes": boxes,
                "width": GROUP_PAD * 2 + sum(b[0] for b in boxes) + TIER_GAP * (len(boxes) - 1),
                "height": max(b[1] for b in boxes),
            })
        width = max((r["width"] for r in measured), default=GROUP_PAD * 2)
        # The lane is for TRAVERSAL, and nothing traverses a band outside the platform
        # boundaries: edges start in Users and terminate in Third-party. Giving those a lane
        # anyway left a third of each one empty.
        lane = 0 if key in ("_actors", "_external", "_project") else LANE
        height = (GROUP_PAD * 2 + TITLE_H + sum(r["height"] for r in measured)
                  + ROW_GAP * (len(measured) - 1) + lane)
        laid.append(dict(band, rows=measured, width=width, height=height,
                         is_host=(band["id"] == host)))

    return order_bands(laid, architecture, host), tier_label


def order_bands(bands, architecture, host):
    """Users first, third parties last, and the rest by how much they talk to the host.

    Alphabetical put the most connected band wherever its name fell, which lengthened every edge
    that mattered. Traffic decides instead, and ties break on the id so the order stays stable.
    """
    where = {}
    for band in bands:
        for tier, items in [(t, i) for row in band["rows"] for t, i in row["tiers"]]:
            for component in items:
                where[component["id"]] = band["id"]
    weight = collections.Counter()
    for edge in architecture.get("connections") or []:
        source, target = where.get(edge["from"]), where.get(edge["to"])
        if source and target and source != target:
            weight[source] += 1
            weight[target] += 1

    by_id = {b["id"]: b for b in bands}
    middle = sorted((k for k in by_id if k not in ("_actors", "_external", "_project")),
                    key=lambda k: (k != host, -weight[k], k))
    keys = ([k for k in ("_actors",) if k in by_id] + middle
            + [k for k in ("_project", "_external") if k in by_id])
    return [by_id[k] for k in keys]


def document(architecture, model=None, platforms=None, icon_names=None):
    """The eraser document: entities and connections.

    No badges and no legend. Whether a component is built, adopted or bought is a sourcing
    decision with a scored table and a gate of its own; stamping it on the artwork made every
    node carry a second label and cost the diagram a corner to a key nobody needed.
    """
    model = model or caps.load_model()
    platforms = platforms if platforms is not None else {}
    pal = palette()
    bands, tier_label = plan(architecture, model, icon_names)

    entities, connections = [], []
    group_of = {}

    # Bands wrap into canvas rows rather than running off to the right. A real run produced eight
    # bands on a 4378x614 canvas — 7:1, unreadable at any zoom that fits a page.
    packed, current, run = [], [], 0
    for band in bands:
        if current and run + band["width"] + BAND_GAP > ROW_WIDTH_BUDGET:
            packed.append(current)
            current, run = [], 0
        current.append(band)
        run += band["width"] + BAND_GAP
    if current:
        packed.append(current)

    cursor = MARGIN
    for strip in packed:
        tallest = max(band["height"] for band in strip)
        x = MARGIN
        for band in strip:
            name = band["label"] or (platforms.get(band["id"], {}).get("name") or band["id"])
            outside = band["id"] in ("_actors", "_external", "_project")
            y = cursor + (tallest - band["height"]) // 2
            entities.append({
                "tag": "Group", "id": f"band-{band['id']}",
                "title": {"text": name.upper()},
                "color": (pal["outside"] if outside else
                          pal["host_band"] if band.get("is_host") else pal["other_band"]),
                "styleMode": "plain" if outside else "shadow",
                "x": x, "y": y, "width": band["width"], "height": band["height"],
            })
            ty = y + GROUP_PAD + TITLE_H
            for row in band["rows"]:
                tx = x + GROUP_PAD
                for (tier, items), (bw, bh) in zip(row["tiers"], row["boxes"]):
                    gid = f"tier-{band['id']}-{tier}"
                    entities.append({
                        "tag": "Group", "id": gid,
                        "title": {"text": tier_label.get(tier, tier)}, "color": pal["tier"],
                        "containerId": f"band-{band['id']}", "styleMode": "plain",
                        "x": tx, "y": ty, "width": bw, "height": bh,
                    })
                    columns, _ = grid(len(items))
                    cw, ch = cell_size(items)
                    for index, component in enumerate(items):
                        group_of[component["id"]] = gid
                        col, line = index % columns, index // columns
                        cx = tx + GROUP_PAD + col * (cw + ICON_GAP)
                        cy = ty + GROUP_PAD + TITLE_H + line * (ch + ICON_GAP)
                        entities += cell(component, gid, cx, cy, cw, ch, tier, pal)
                    tx += bw + TIER_GAP
                ty += row["height"] + ROW_GAP
            x += band["width"] + BAND_GAP
        cursor += tallest + BAND_GAP

    # Edges are drawn BETWEEN TIER GROUPS, not between icons. The reference diagram does the
    # same, and for the same reason: an application that touches nine components produces nine
    # near-parallel lines crossing the whole canvas, which is a picture of the fan-out rather
    # than of the system. Aggregating to the group a component sits in collapsed 21 edges to a
    # handful here, and took the render from 80 seconds to a few.
    seen = {}
    for edge in architecture.get("connections") or []:
        source, target = group_of.get(edge["from"]), group_of.get(edge["to"])
        if not source or not target or source == target:
            continue
        seen.setdefault((source, target), []).append(edge.get("label", ""))
    for (source, target), labels in seen.items():
        label = max(set(labels), key=labels.count) if labels else ""
        # No authored `fromPort`/`toPort`. Pinning the faces from the two boxes' positions was
        # tried and measurably made things worse: given real corridors the router chooses better
        # faces than a bounding-box heuristic can, and the one hint that looked obviously right —
        # leave right, enter left — sent the application's longest edge down through the tier in
        # the corner. Corridors are this module's job; faces are the router's.
        connections.append({"from": source, "to": target, "label": label,
                            "endArrowhead": "triangle", "connectorStyle": "elbow",
                            "cornerStyle": "elbow"})

    return {"entities": entities, "connections": connections}


def cell(component, container, x, y, width, height, tier, pal):
    """One grid cell: an icon, or a runtime group with the icon inside it."""
    ink = pal["tier_ink"].get(tier, pal["ink"])

    def glyph(icon, label, cx, cy, parent):
        entity = {"tag": "Icon", "id": component["id"], "icon": icon or "box", "size": "md",
                  "containerId": parent, "x": cx, "y": cy, "texts": [{"text": label}]}
        # A vendor logo brings its own colour; a generic glyph has none and renders as thin grey
        # line-art. Coloured BY TIER, so the colour carries meaning — which is where the
        # reference diagram gets most of its legibility.
        if entity["icon"] in GENERIC_ICONS:
            entity["color"] = ink
        return entity

    runtime = component.get("runs_on") or {}
    if not runtime.get("service"):
        # Centre a bare icon in a cell that may have been sized for a runtime group.
        return [glyph(component.get("icon"), component["name"],
                      x + (width - ICON_W) // 2, y + (height - ICON_H) // 2, container)]

    gid = f"runtime-{component['id']}"
    group = {"tag": "Group", "id": gid,
             "title": {"text": runtime["service"]},
             "color": pal["runtime"], "containerId": container, "styleMode": "plain",
             "x": x, "y": y, "width": width, "height": height}
    if runtime.get("icon"):
        group["title"]["icon"] = runtime["icon"]
        if runtime["icon"] in GENERIC_ICONS:
            group["title"]["iconProps"] = {"color": ink}
    return [group, glyph(component.get("icon"), component["name"],
                         x + GROUP_PAD, y + GROUP_PAD + TITLE_H, gid)]


def overlaps(doc):
    """Sibling boxes that intersect. The layout's own check on itself.

    Rendered geometry can exceed authored geometry — a long service name grows its box — so a
    clean result here is necessary and not sufficient; `render-diagram.py` re-checks against
    what the browser actually measured, and `routing-check.py` checks the edges.
    """
    boxes = [e for e in doc["entities"] if e.get("width") and e.get("height")]
    clashes = []
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            if a.get("containerId") != b.get("containerId"):
                continue
            if (a["x"] < b["x"] + b["width"] and b["x"] < a["x"] + a["width"]
                    and a["y"] < b["y"] + b["height"] and b["y"] < a["y"] + a["height"]):
                clashes.append((a["id"], b["id"]))
    return clashes


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("architecture")
    ap.add_argument("-o", "--output")
    ap.add_argument("--platforms")
    args = ap.parse_args()

    architecture = json.loads(Path(args.architecture).read_text(encoding="utf-8"))
    doc = document(architecture, caps.load_model(), caps.load_platforms(args.platforms))
    clashes = overlaps(doc)
    if clashes:
        print(f"layout produced overlapping siblings: {clashes}", file=sys.stderr)
        return 1
    text = json.dumps(doc, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
