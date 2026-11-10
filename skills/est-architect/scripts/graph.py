#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""The architecture as a SEMANTIC graph — zones, groups, nodes and edges, with no geometry.

Step 1 of the diagram pipeline, and the step the previous version did not have. It used to go
straight from `architecture.json` to pixel coordinates, which meant two different mistakes were
invisible in the same place: a graph that was not true, and a composition that was not designed.
Separating them makes each one checkable on its own.

    architecture.json  ->  graph.py  ->  elk.mjs  ->  layout.py  ->  render.mjs
       the decision         WHAT           WHERE       the document     the picture

Nothing here knows a pixel. What it does know is section A of the design contract:

  A1  at most two container levels: zone -> group -> node
  A2  no redundant wrapper — a container whose only child is another container, or one that
      repeats its child's name, is merged away
  A4  every zone, group and node name is unique in the diagram
  A5  a node is a NAME (the product) and a ROLE (what it is), never one string carrying both

`build()` returns the graph; `validate()` returns findings. They are separate because the
renderer needs the first and the checker needs the second, and a builder that silently repaired
its own input would hide exactly the defects this file exists to surface.

    uv run scripts/graph.py <architecture.json> [-o graph.json]
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent

# A vendor that serves this many capabilities has earned a boundary of its own. Below it, it
# shares the third-party zone — giving every vendor its own box produced eight boundaries on one
# canvas, five of them holding a single icon.
ZONE_MIN_CAPABILITIES = 3

ACTORS_ZONE = "_actors"
EXTERNAL_ZONE = "_external"
PROJECT_ZONE = "_project"


def _host(components):
    """The platform the application runs on. Its zone is the one the reader starts inside."""
    for component in components:
        if component.get("capability") == "application" and component.get("platform"):
            return component["platform"]
    for component in components:
        if component.get("platform"):
            return component["platform"]
    return None


def zone_of(component, host, reach, spec=None):
    """Which boundary a component is drawn inside.

    A capability may declare its own `zone` in the catalogue. Code the project writes and does
    NOT host — a mobile app on the learner's phone — has no platform, and fell through to the
    host's zone: a React Native app was drawn inside the AWS boundary on passenger-seat, which is
    false, and every edge from it to a third party then wove through the API's own fan-out.
    """
    if component.get("tier") == "actors":
        return ACTORS_ZONE
    declared = ((spec or {}).get("zone") or {}).get("id")
    if declared:
        return declared
    pid = component.get("platform")
    if pid and (pid == host or reach.get(pid, 0) >= ZONE_MIN_CAPABILITIES):
        return pid
    if pid or component.get("tier") == "external":
        return EXTERNAL_ZONE
    return host or PROJECT_ZONE


def _role(component, catalogue):
    """A5's second line. An `architecture.json` written before roles existed still draws: the
    catalogue answers for it. A capability research added and did not describe falls back to its
    own id, humanised — which is honest, and `build()` records that it had to."""
    spec = catalogue.get(component.get("capability")) or {}
    if component.get("mode") == "actor":
        return component.get("role") or "User"
    return (component.get("role") or spec.get("role") or spec.get("name")
            or (component.get("capability") or "").replace("_", " ").capitalize())


def kind_of(component, host):
    """`managed | custom | actor | external` — what the reader is being asked to trust."""
    if component.get("mode") == "actor":
        return "actor"
    pid = component.get("platform")
    if component.get("tier") == "external" and pid != host:
        return "external"
    return "managed" if component.get("mode") == "buy" else "custom"


def _constrain(zones, groups, tier_order):
    """B1/B3. Pin the two ends of the reading order and leave the middle to the layout engine.

    Layering follows the edges and a group is placed as ONE column, so a group holding both the
    first thing a request meets and something the application calls back to is dragged to the
    later of the two. On Keyhole that put the WAF — the very first hop — to the right of the API,
    because Amazon Cognito shares its group and is reached from the browser and the backend both.

    `layerConstraint` is ELK's own mechanism and it is applied only where the contract is
    explicit: actors in a column of their own ahead of everything, entry in the first layer
    proper, third parties in the last. Everything between them stays the engine's decision, which
    is the whole reason for having one. `elk.partitioning` is the obvious alternative and is inert
    in the pinned elkjs build — verified against it, not assumed.
    """
    first_tier = next((t for t in tier_order if t != "actors"), None)
    for group in groups:
        if group["tier"] == first_tier:
            group["layerConstraint"] = "FIRST"
        elif group["tier"] == tier_order[-1]:
            group["layerConstraint"] = "LAST"
    for zone in zones:
        if zone["id"] == ACTORS_ZONE:
            zone["layerConstraint"] = "FIRST_SEPARATE"
        elif zone["id"] == EXTERNAL_ZONE:
            zone["layerConstraint"] = "LAST_SEPARATE"



def build(architecture, model=None, platforms=None):
    """`architecture.json` -> `{zones, groups, nodes, edges, notes}`.

    Container structure only; A2's merges are applied here because they change what a container
    IS, not how it looks. Everything that is a judgement about quality stays in `validate()`.
    """
    components = architecture.get("components") or []
    model = model or {}
    platforms = platforms or {}
    catalogue = (model.get("capabilities") or {})
    tiers = (model.get("tiers") or {})
    tier_label = tiers.get("labels") or {}
    tier_order = tiers.get("order") or ["actors", "edge", "application", "services", "data",
                                        "external"]
    host = _host(components)
    reach = Counter(c["platform"] for c in components if c.get("platform"))

    zone_title = {ACTORS_ZONE: "Users", EXTERNAL_ZONE: "Third-party",
                  PROJECT_ZONE: "Built by this project"}
    for pid, profile in platforms.items():
        zone_title[pid] = profile.get("name") or pid

    for spec in catalogue.values():
        declared = (spec.get("zone") or {}) if isinstance(spec, dict) else {}
        if declared.get("id"):
            zone_title.setdefault(declared["id"], declared.get("title") or declared["id"])
    declared_zones = {z for z in zone_title if z not in (ACTORS_ZONE, EXTERNAL_ZONE, PROJECT_ZONE)
                      and z not in platforms}

    nodes, notes = [], []
    for component in components:
        zid = zone_of(component, host, reach, catalogue.get(component.get("capability")))
        nodes.append({
            "id": component["id"],
            "zoneId": zid,
            "groupId": f"{zid}::{component['tier']}",
            "name": component.get("name") or component["id"],
            # A5: the product on line one, what it IS on line two. Never one string carrying
            # both — "Django on Fargate" is the collapse this undoes.
            # An `architecture.json` written before roles existed still draws: the
            # catalogue answers for it rather than leaving the second line blank.
            "role": _role(component, catalogue),
            "icon": component.get("icon") or "box",
            "kind": kind_of(component, host),
            "runtime": (component.get("runs_on") or {}).get("service"),
            "tier": component.get("tier"),
        })

    for node, component in zip(nodes, components):
        spec = catalogue.get(component.get("capability")) or {}
        if not (component.get("role") or spec.get("role") or spec.get("name")
                or component.get("mode") == "actor"):
            notes.append({"kind": "role_defaulted", "detail":
                          f"`{node['name']}` is a capability the catalogue does not describe, so "
                          f"its second label line was made from its own id"})

    used_zones = {n["zoneId"] for n in nodes}
    zones = [{"id": z, "title": zone_title.get(z, z), "kind":
              "outside" if z in (ACTORS_ZONE, EXTERNAL_ZONE, PROJECT_ZONE) or z in declared_zones
              else "platform",
              "isHost": z == host}
             for z in sorted(used_zones, key=lambda z: _zone_rank(z, host, declared_zones))]

    groups = []
    for zone in zones:
        for tier in tier_order:
            gid = f"{zone['id']}::{tier}"
            if any(n["groupId"] == gid for n in nodes):
                groups.append({"id": gid, "zoneId": zone["id"],
                               "title": tier_label.get(tier, tier.replace("_", " ").title()),
                               "tier": tier})

    # B2/B3. The column each container sits in. The tier order is the declared reading order —
    # actors, then what the request passes through, then the application, then what it reaches —
    # so it is what "the longest path from the actors" resolves to on every architecture this
    # module produces, and it is data rather than a traversal that could answer differently on
    # two runs of the same design.
    _constrain(zones, groups, tier_order)

    zones, groups, nodes, merged = _merge_redundant(zones, groups, nodes)
    notes.extend(merged)
    notes.extend(_qualify_repeated_titles(zones, groups))

    edges = []
    for edge in architecture.get("connections") or []:
        edges.append({"from": edge["from"], "to": edge["to"], "label": edge.get("label", ""),
                      # Nothing in this module distinguishes a queue hop from a call yet, so the
                      # style is declared rather than guessed. D8's dashed variant waits for data
                      # that means it.
                      "style": "async" if edge.get("async") else "sync",
                      **({"defaulted": True} if edge.get("defaulted") else {})})

    return {"zones": zones, "groups": groups, "nodes": nodes, "edges": edges,
            "tier_order": tier_order, "host": host, "notes": notes}


def _zone_rank(zone, host, declared=()):
    """B3: actors first, third parties last, the host platform ahead of the other platforms.

    A zone a capability declares for itself (the user's device) sits between the actors and the
    platforms, because that is where a request starts after a person."""
    if zone == ACTORS_ZONE:
        return (0, "")
    if zone in declared:
        return (0, zone)
    if zone == EXTERNAL_ZONE:
        return (3, "")
    if zone == PROJECT_ZONE:
        return (2, "")
    return (1, "" if zone == host else zone)


def _merge_redundant(zones, groups, nodes, ):
    """A2. A container whose only child is another container is a wrapper, not a boundary.

    `USERS` holding one group called `Users`, and `THIRD-PARTY` holding one called
    `Integrations`, were both reported as redundant nesting — and the second one is also what put
    the name `Integrations` on the canvas twice. Merging keeps the ZONE's title, because the zone
    says who owns the thing and the group only says which tier it is; with one tier there is no
    tier to distinguish.

    A group holding a single NODE is left alone deliberately. It is not a wrapper — it is a
    labelled tier that happens to have one occupant — and dissolving it would drop the label.
    """
    notes = []
    by_zone = {}
    for group in groups:
        by_zone.setdefault(group["zoneId"], []).append(group)

    dissolved = {}
    for zone in zones:
        children = by_zone.get(zone["id"]) or []
        if len(children) == 1:
            group = children[0]
            dissolved[group["id"]] = zone["id"]
            notes.append({"kind": "container_merged", "detail":
                          f"zone `{zone['title']}` held only `{group['title']}`, so the two are "
                          f"drawn as one boundary"})

    groups = [g for g in groups if g["id"] not in dissolved]
    for node in nodes:
        if node["groupId"] in dissolved:
            node["groupId"] = None
    return zones, groups, nodes, notes


def _qualify_repeated_titles(zones, groups):
    """A6. A group is titled by its tier, and a tier recurs in more than one zone.

    On passenger-seat the AWS zone held `Integrations` (Bedrock, End User Messaging) and
    `Platform services` (SQS, CloudWatch), and so did the third-party zone (RevenueCat, Mixpanel
    | Sentry): four boxes, two names, and a failed render with nothing wrong in the design. The
    host zone keeps the bare tier label — it is where the reader starts — and every other
    occurrence is qualified with its zone's own title.
    """
    notes = []
    count = {}
    for group in groups:
        count[group["title"]] = count.get(group["title"], 0) + 1
    zone_by_id = {z["id"]: z for z in zones}
    for group in groups:
        if count[group["title"]] < 2:
            continue
        zone = zone_by_id.get(group["zoneId"]) or {}
        if zone.get("isHost"):
            continue
        bare = group["title"]
        group["title"] = f"{zone.get('title', group['zoneId'])} {bare[:1].lower()}{bare[1:]}"
        notes.append({"kind": "title_qualified", "detail":
                      f"`{bare}` appears in more than one zone, so the one in "
                      f"`{zone.get('title')}` is drawn as `{group['title']}`"})
    return notes


def validate(graph):
    """Sections A1, A2, A4, A5 — what has to be true before anything is laid out."""
    findings = []
    zones = {z["id"]: z for z in graph["zones"]}
    groups = {g["id"]: g for g in graph["groups"]}

    for group in graph["groups"]:                                               # A2
        if group["title"].strip().lower() == zones[group["zoneId"]]["title"].strip().lower():
            findings.append({"kind": "container_repeats_child", "what": group["title"],
                             "detail": f"group `{group['title']}` has the same name as the zone "
                                       f"it sits in"})

    titles = Counter()                                                          # A4
    for item in list(graph["zones"]) + list(graph["groups"]):
        titles[item["title"].strip().lower()] += 1
    for node in graph["nodes"]:
        titles[node["name"].strip().lower()] += 1
    for title, count in sorted(titles.items()):
        if count > 1:
            findings.append({"kind": "duplicate_name", "what": title,
                             "detail": f"`{title}` names {count} things on one canvas"})

    for node in graph["nodes"]:                                                 # A5
        if not node["role"]:
            findings.append({"kind": "node_without_role", "what": node["name"],
                             "detail": f"`{node['name']}` has no second label line, so the "
                                       f"diagram does not say what it is"})
        if node["groupId"] and node["groupId"] not in groups:
            findings.append({"kind": "orphan_node", "what": node["name"],
                             "detail": f"`{node['name']}` names a group that is not drawn"})

    ids = {n["id"] for n in graph["nodes"]}                                     # the graph itself
    for edge in graph["edges"]:
        for end in ("from", "to"):
            if edge[end] not in ids:
                findings.append({"kind": "dangling_edge", "what": edge[end],
                                 "detail": f"an edge names `{edge[end]}`, which is not a node"})
    joined = {e["from"] for e in graph["edges"]} | {e["to"] for e in graph["edges"]}
    for node in graph["nodes"]:
        if node["id"] not in joined:
            findings.append({"kind": "unconnected_node", "what": node["name"],
                             "detail": f"`{node['name']}` reaches nothing and nothing reaches it"})

    return {"findings": findings, "ok": not findings,
            "checked": (f"{len(graph['zones'])} zones, {len(graph['groups'])} groups, "
                        f"{len(graph['nodes'])} nodes and {len(graph['edges'])} edges against "
                        f"A1, A2, A4 and A5")}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("architecture")
    ap.add_argument("-o", "--output")
    ap.add_argument("--model")
    ap.add_argument("--platforms")
    args = ap.parse_args()

    sys.path.insert(0, str(HERE))
    import capabilities as caps

    architecture = json.loads(Path(args.architecture).read_text(encoding="utf-8"))
    model = json.loads(Path(args.model).read_text(encoding="utf-8")) if args.model \
        else caps.load_model()
    platforms = json.loads(Path(args.platforms).read_text(encoding="utf-8")) if args.platforms \
        else caps.load_platforms()

    graph = build(architecture, model, platforms)
    graph["validation"] = validate(graph)
    text = json.dumps(graph, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if graph["validation"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
