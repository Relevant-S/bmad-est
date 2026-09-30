#!/usr/bin/env node
/**
 * ELK, driven from the semantic graph. One request on stdin, one report on stdout.
 *
 * Language models are bad at geometry, and the previous version of this module proved it: every
 * coordinate was computed by hand in Python from a box model that grew a constant per defect.
 * ELK is a layout engine; it is given sizes and a graph and it answers with positions and
 * orthogonal routes. Nothing in this file decides where anything goes.
 *
 * What it does do, because ELK alone does not:
 *
 *   1. FLATTEN. ELK reports every child relative to its parent, and every edge section relative
 *      to the node that contains the edge. The renderer wants absolute scene coordinates, so the
 *      tree is walked once with an accumulated offset. Getting this wrong is invisible on a flat
 *      graph and catastrophic on a nested one, which is why it is here and not in the caller.
 *   2. WRAP. B5 wants an aspect ratio between 1.6 and 2.8 and a flow that wraps into a second row
 *      when it would otherwise run too wide. That is `elk.layered.wrapping.strategy` plus
 *      `elk.aspectRatio` — ELK's own answer — so the wrap is a re-run with different options
 *      rather than a second layout algorithm written here.
 *
 *   echo '{"graph":…,"options":…}' | node elk.mjs
 */

import { createRequire } from "node:module";
import { readFileSync } from "node:fs";

const TARGET_ASPECT = { min: 1.6, max: 2.8 };

function read() {
  return JSON.parse(readFileSync(0, "utf8"));
}

/** The brief's option block. Written out rather than merged, so what ELK is asked is readable. */
const BASE_OPTIONS = {
  "elk.algorithm": "layered",
  "elk.direction": "RIGHT",
  "elk.edgeRouting": "ORTHOGONAL",
  "elk.hierarchyHandling": "INCLUDE_CHILDREN",
  "elk.layered.nodePlacement.strategy": "NETWORK_SIMPLEX",
  "elk.layered.spacing.nodeNodeBetweenLayers": "112",
  "elk.spacing.nodeNode": "32",
  "elk.spacing.edgeNode": "16",
  "elk.spacing.edgeEdge": "12",
  "elk.edgeLabels.placement": "CENTER",
  "elk.padding": "[top=48,left=20,bottom=20,right=20]",
};

/** Absolute scene coordinates, and edge sections joined into one polyline per edge. */
function flatten(root) {
  const boxes = {};
  const offsets = new Map([[root.id ?? "root", { x: 0, y: 0 }]]);

  const walk = (node, ox, oy) => {
    for (const child of node.children ?? []) {
      const x = ox + (child.x ?? 0);
      const y = oy + (child.y ?? 0);
      boxes[child.id] = { x, y, width: child.width ?? 0, height: child.height ?? 0 };
      offsets.set(child.id, { x, y });
      walk(child, x, y);
    }
  };
  walk(root, 0, 0);

  const edges = {};
  const collect = (node) => {
    for (const edge of node.edges ?? []) {
      // An edge's geometry is expressed inside whichever node ELK chose to hang it on. That is
      // `edge.container` when it says so, and otherwise the node we found it under.
      const frame = offsets.get(edge.container ?? node.id) ?? { x: 0, y: 0 };
      const points = [];
      for (const section of edge.sections ?? []) {
        const run = [section.startPoint, ...(section.bendPoints ?? []), section.endPoint];
        for (const p of run) {
          const abs = { x: frame.x + p.x, y: frame.y + p.y };
          const last = points[points.length - 1];
          if (!last || last.x !== abs.x || last.y !== abs.y) points.push(abs);
        }
      }
      const label = (edge.labels ?? [])[0];
      edges[edge.id] = {
        points,
        label: label
          ? { x: frame.x + (label.x ?? 0), y: frame.y + (label.y ?? 0),
              width: label.width ?? 0, height: label.height ?? 0 }
          : null,
      };
    }
    for (const child of node.children ?? []) collect(child);
  };
  collect(root);

  return { boxes, edges, scene: { x: 0, y: 0, width: root.width ?? 0, height: root.height ?? 0 } };
}

/** The longest edge, as a Manhattan run. A wrap that lengthens this has not helped anybody. */
function longestEdge(root) {
  let longest = 0;
  const visit = (node) => {
    for (const edge of node.edges ?? []) {
      let run = 0;
      for (const section of edge.sections ?? []) {
        const pts = [section.startPoint, ...(section.bendPoints ?? []), section.endPoint];
        for (let i = 1; i < pts.length; i += 1) {
          run += Math.abs(pts[i].x - pts[i - 1].x) + Math.abs(pts[i].y - pts[i - 1].y);
        }
      }
      longest = Math.max(longest, run);
    }
    for (const child of node.children ?? []) visit(child);
  };
  visit(root);
  return longest;
}


function toElk(graph, options) {
  const byGroup = new Map();
  const byZone = new Map();
  for (const node of graph.nodes) {
    const child = {
      id: node.id, width: node.width, height: node.height,
      layoutOptions: { "elk.portConstraints": "FREE" },
    };
    if (node.groupId) {
      if (!byGroup.has(node.groupId)) byGroup.set(node.groupId, []);
      byGroup.get(node.groupId).push(child);
    } else {
      if (!byZone.has(node.zoneId)) byZone.set(node.zoneId, []);
      byZone.get(node.zoneId).push(child);
    }
  }
  for (const group of graph.groups) {
    if (!byZone.has(group.zoneId)) byZone.set(group.zoneId, []);
    byZone.get(group.zoneId).push({
      id: group.id,
      children: byGroup.get(group.id) ?? [],
      layoutOptions: {
        "elk.padding": graph.padding.group,
        "elk.spacing.nodeNode": String(graph.spacing.cellY),
        // B2: "groups in the same layer share a column". Layering follows edges, so a group
        // whose members are consumed at different depths — an identity provider the browser
        // redirects to AND the API validates against — stretches across several layers, and
        // every edge into it then loops around the stretched box. Partitioning is ELK's own
        // mechanism for pinning a layer, and it applies among SIBLINGS, which is why it is here
        // on the groups inside a zone rather than on the nodes inside different groups.
        ...(group.layerConstraint
              ? { "elk.layered.layering.layerConstraint": group.layerConstraint } : {}),
      },
    });
  }
  const children = graph.zones.map((zone) => ({
    id: zone.id,
    children: byZone.get(zone.id) ?? [],
    layoutOptions: {
      "elk.padding": graph.padding.zone,
      ...(zone.layerConstraint
            ? { "elk.layered.layering.layerConstraint": zone.layerConstraint } : {}),
    },
  }));

  const edges = graph.edges.map((edge, i) => ({
    id: edge.id ?? `e${i}`,
    sources: [edge.from], targets: [edge.to],
    ...(edge.labelWidth
      ? { labels: [{ text: edge.label ?? "", width: edge.labelWidth, height: edge.labelHeight }] }
      : {}),
  }));

  return { id: "root", layoutOptions: { ...BASE_OPTIONS, ...options }, children, edges };
}

async function main() {
  const request = read();
  const require = createRequire(import.meta.url);
  const ELK = require(request.elkPath ?? "elkjs");
  const elk = new ELK();

  // ELK is asked for a slightly tighter band than the contract wants, because the RENDERED scene
  // is a few percent wider than the laid-out one: the renderer grows the scene box by each
  // element's ink. Aiming at 2.8 exactly lands at 3.08 on the other side of the check.
  const TARGET = { min: 1.7, max: 2.7 };
  const distance = (aspect) =>
    aspect < TARGET.min ? TARGET.min - aspect : aspect > TARGET.max ? aspect - TARGET.max : 0;

  const attempts = [];
  const candidates = [];
  let options = { ...(request.options ?? {}) };

  for (let pass = 0; pass < 4; pass += 1) {
    const laid = await elk.layout(toElk(request.graph, options));
    const aspect = (laid.height ?? 0) > 0 ? (laid.width ?? 0) / laid.height : 0;
    attempts.push({ pass, options: { ...options }, width: laid.width, height: laid.height,
                    aspect: Number(aspect.toFixed(3)) });
    candidates.push({ laid, aspect, reach: longestEdge(laid) });
    if (distance(aspect) === 0) break;

    if (aspect > TARGET.max) {
      // Too wide: fold the layer sequence into another row. B5, and ELK's own mechanism for it.
      options = { ...options, "elk.aspectRatio": "2.2",
                  "elk.layered.wrapping.strategy": "MULTI_EDGE",
                  "elk.layered.wrapping.additionalEdgeSpacing": "24" };
    } else if (options["elk.layered.wrapping.strategy"]) {
      // Wrapping overshot into a tall stack. Ask for a wider target rather than switching it off,
      // which is what made an earlier version oscillate between 2.9 and 1.2 and then KEEP the
      // worst of the two because it happened to be last.
      const current = Number(options["elk.aspectRatio"] ?? 2.2);
      options = { ...options, "elk.aspectRatio": String(Number((current + 0.8).toFixed(2))) };
    } else {
      options = { ...options, "elk.layered.spacing.nodeNodeBetweenLayers": "128" };
    }
  }

  // The best attempt, not the last one — and "best" is not aspect alone. Layer wrapping folds
  // the sequence into a second row by moving whole zones, and the edges that used to join them
  // then run the full width of the canvas and back. On Keyhole that traded an aspect of 2.9 for
  // two 2000px arrows, which is a worse picture by the standard the aspect rule exists to serve.
  // So a wrap that leaves an edge longer than the scene it is meant to have compacted is refused.
  const sane = candidates.filter((c) => c.reach <= (c.laid.width ?? 0));
  const pool = sane.length > 0 ? sane : candidates;
  let best = pool[0];
  for (const candidate of pool) {
    if (distance(candidate.aspect) < distance(best.aspect)) best = candidate;
  }
  const laid = best.laid;

  const flat = flatten(laid);
  process.stdout.write(JSON.stringify({
    ok: true, ...flat, attempts,
    aspect: Number(best.aspect.toFixed(3)),
    aspectTarget: TARGET,
    longestEdge: Math.round(best.reach),
  }));
}

main().catch((error) => {
  process.stdout.write(JSON.stringify({ ok: false, error: String(error?.stack ?? error) }));
  process.exitCode = 1;
});
