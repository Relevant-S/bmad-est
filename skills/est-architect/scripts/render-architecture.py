#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Render architecture.json into the document a human reads, plus the cost sheet.

Writes `architecture.md`, and `cost-breakdown.csv` when a costs file exists. The diagram is
rendered by `render-diagram.py` and referenced here; a Mermaid block carries the same graph as
text, for diffing and for reading in a terminal — not as a fallback, because the PNG is a
required output and there is nothing to fall back from.

    uv run scripts/render-architecture.py <architecture.json> [--costs costs.json] \\
        [--diagram architecture.png] [-o architecture.md]
"""

import argparse
import csv
import importlib.util
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


caps = _load("capabilities", HERE / "capabilities.py")
price = _load("price", HERE / "price.py")
graph = _load("graph", HERE / "graph.py")

# Every artefact this module produces says this, in these words, because somebody will
# otherwise add twelve months of run-cost to a project quote.
COST_BOUNDARY = ("**Run-cost is not delivery cost.** The figures below are what the system costs "
                 "to operate, per month and per year, continuing after the project ends. The "
                 "estimate is hours. The two are never summed.")


def _num(value):
    return "—" if value is None else (f"{value:g}" if isinstance(value, (int, float))
                                      else str(value))


def _parts_table(option):
    rows = ["| Sub-score | Score | Weight | Rests on |", "| --- | --- | --- | --- |"]
    for name, part in option.get("parts", {}).items():
        rows.append(f"| {name.replace('_', ' ')} | {_num(part.get('score'))} | "
                    f"{_num(part.get('weight'))} | {part.get('basis', '')} |")
    return "\n".join(rows)


def _layer(title, layer, intro):
    out = [f"## {title}", "", intro, ""]
    options = layer.get("options") or []
    if not options:
        out += ["*No option was scored — nothing was supplied to score.*", ""]
        return "\n".join(out)
    out += ["| Option | Varies | Score | Viable |", "| --- | --- | --- | --- |"]
    for option in options:
        mark = "yes" if option.get("viable") else "**no**"
        chosen = " ←" if option["id"] == layer.get("chosen") else ""
        out.append(f"| {option['name']}{chosen} | {option.get('axis', '')} | "
                   f"{_num(option.get('score'))} | {mark} |")
    out += ["", f"**{layer.get('chosen_why', '')}**", ""]
    for option in options:
        out += [f"### {option['name']}", "", _parts_table(option), ""]
        for dead in option.get("not_viable_because") or []:
            out.append(f"> **Not viable** — {dead['detail']}")
        for unknown in option.get("unevaluated_gates") or []:
            out.append(f"> **Could not be evaluated** — {unknown['detail']}")
        if option.get("not_viable_because") or option.get("unevaluated_gates"):
            out.append("")
    return "\n".join(out)


def _sourcing(layer):
    out = ["## Sourcing — build, adopt or buy", "",
           "The layer with the strongest numbers here: the stories at stake are named ids with "
           "real size bands. The ratio applied to them is an **asserted** coefficient with no "
           "delivered project behind it, and every basis line below says so.", ""]
    if not layer.get("confirmed"):
        out += ["> **Not confirmed by the operator.** The platform layer was scored against "
                "this table anyway; a correction here changes what follows.", ""]
    balance = layer.get("balance") or {}
    out += [f"**Balance** — {balance.get('build', 0)} built, {balance.get('adopt', 0)} adopted, "
            f"{balance.get('buy', 0)} bought across {balance.get('live_decisions', 0)} live "
            f"decisions. {balance.get('counted', '')}", ""]
    for finding in balance.get("findings") or []:
        out += [f"> **{finding['kind']}** — {finding['detail']}", ""]
    out += [layer.get("batch") or "", ""]
    for decision in layer.get("decisions") or []:
        if not decision.get("live"):
            continue
        out += [f"### {decision['name']}", "", decision["why"], ""]
        for option in decision.get("options") or []:
            out += [f"**{option['id']}** — score {_num(option.get('score'))}", "",
                    _parts_table(option), ""]
    return "\n".join(out)


def _safe(node_id):
    return re.sub(r"[^A-Za-z0-9_]", "_", node_id)


def mermaid(architecture, model=None, platforms=None):
    """The same graph as text. For diffing and for a terminal, never as a substitute.

    Both views are built from `graph.build`, so the picture and the prose cannot disagree about
    what is inside what. They used to share `layout.plan`, which tied the text form to a box
    model full of pixel constants; now they share the SEMANTIC graph, which is the thing they
    actually have in common.
    """
    g = graph.build(architecture, model or caps.load_model(), platforms or {})
    by_zone, by_group = {}, {}
    for node in g["nodes"]:
        (by_group.setdefault(node["groupId"], []) if node["groupId"]
         else by_zone.setdefault(node["zoneId"], [])).append(node)
    groups_of = {}
    for group in g["groups"]:
        groups_of.setdefault(group["zoneId"], []).append(group)

    lines = ["```mermaid", "flowchart LR"]
    for zone in g["zones"]:
        lines.append(f'  subgraph {_safe(zone["id"])}["{zone["title"]}"]')
        for node in by_zone.get(zone["id"]) or []:
            lines.append(f'    {_node_line(node)}')
        for group in groups_of.get(zone["id"]) or []:
            lines.append(f'    subgraph {_safe(group["id"])}["{group["title"]}"]')
            for node in by_group.get(group["id"]) or []:
                lines.append(f'      {_node_line(node)}')
            lines.append("    end")
        lines.append("  end")

    drawn = {_safe(n["id"]) for n in g["nodes"]}
    for edge in g["edges"]:
        source, target = _safe(edge["from"]), _safe(edge["to"])
        if source not in drawn or target not in drawn:
            continue
        label = edge.get("label") or ""
        lines.append(f'  {source} -->|{label}| {target}' if label
                     else f'  {source} --> {target}')
    lines.append("```")
    return "\n".join(lines)


def _node_line(node):
    """Name, role, and the runtime in words — a mermaid subgraph per runtime would put forty of
    them on the page, and the diagram now says it with a badge rather than a box."""
    text = node["name"].replace('"', "'")
    if node.get("runtime"):
        text += f" on {node['runtime']}".replace('"', "'")
    role = (node.get("role") or "").replace('"', "'")
    return f'{_safe(node["id"])}["{text}{f"<br/><i>{role}</i>" if role else ""}"]'


def cost_section(costs):
    if not costs:
        return ("## Run cost\n\n" + COST_BOUNDARY + "\n\n"
                "*No cost breakdown was produced for this architecture.*\n")
    header, body = price.to_rows(costs)
    out = ["## Run cost", "", COST_BOUNDARY, "", costs.get("stated", ""), "",
           "| " + " | ".join(header) + " |",
           "| " + " | ".join("---" for _ in header) + " |"]
    for row in body:
        if not any(str(c).strip() for c in row):
            continue
        out.append("| " + " | ".join(str(c) for c in row) + " |")
    out.append("")
    if costs.get("notes"):
        out += ["**Not costs, and not netted into any total:**", ""]
        out += [f"- {note}" for note in costs["notes"]] + [""]
    if costs.get("unpriced"):
        out += [f"> **{len(costs['unpriced'])} row(s) could not be priced** and are excluded "
                f"from every total: {', '.join(costs['unpriced'])}. A price that cannot be "
                f"fetched is recorded, never guessed.", ""]
    for finding in costs.get("findings") or []:
        out.append(f"> **{finding['kind']}** ({finding['row']}) — {finding['detail']}")
    return "\n".join(out)


def markdown(architecture, costs=None, diagram="architecture.png", check=None,
             model=None, platforms=None):
    layers = architecture["layers"]
    handoff = architecture["handoff"]
    out = [f"# Architecture — {architecture.get('project', '')}", "",
           f"*Generated {architecture.get('generated', '')} from "
           f"`{architecture.get('inventory_path', '')}`.*", ""]

    stack = next((o for o in layers["stack"]["options"]
                  if o["id"] == layers["stack"].get("chosen")), None)
    platform = next((o for o in layers["platform"]["options"]
                     if o["id"] == layers["platform"].get("chosen")), None)
    stack_line = f"{stack['name']} ({_num(stack['score'])})" if stack else "none scored"
    platform_line = (f"{platform['name']} ({_num(platform['score'])})" if platform
                     else "none viable")
    out += ["## The recommendation", "",
            f"- **Stack** — {stack_line}",
            f"- **Platforms** — {platform_line}",
            f"- **Priced against** — `{handoff['stack_profile']['value']}`; "
            f"{handoff['stack_profile']['why']}", ""]
    if handoff.get("novel_stack", {}).get("is_novel"):
        out += [f"> **This stack is new to this company.** {handoff['novel_stack']['why']} "
                f"est-estimate is told, so those stories price as `novel` rather than standard.",
                ""]

    out += ["## The diagram", "", f"![Infrastructure diagram]({diagram})", "",
            "Each platform is its own boundary band, the request path runs along the top row "
            "and what it reaches along the next, and a component that runs inside a platform "
            "runtime is drawn inside it. What is built, adopted and bought is the sourcing "
            "table below rather than a badge on the artwork.", "",
            "<details><summary>The same graph as text</summary>", "",
            mermaid(architecture, model, platforms), "", "</details>", ""]

    out += [_layer("Technology stack", layers["stack"],
                   "Language, frameworks, libraries and tooling. Every sub-score carries the "
                   "number it rests on; an unresearched one reports `—` rather than a default."),
            "", _sourcing(layers["sourcing"]), "",
            _layer("Platform set", layers["platform"],
                   "Where each capability runs. A set may combine platforms — that is often the "
                   "right answer — and the sprawl sub-score is what stops it becoming nine."),
            "", cost_section(costs), ""]

    if architecture.get("catalogue_gaps"):
        out += ["## Catalogue gaps", "",
                "Capabilities no platform profile serves, so no set could bind them. A gap in "
                "the catalogue, not in any option:", ""]
        out += [f"- **{g['capability']}** — {g['detail']}" for g in architecture["catalogue_gaps"]]
        out.append("")

    if architecture.get("refusals"):
        out += ["## Refused, and why", "",
                "A refusal nobody can check is a refusal nobody can argue with.", "",
                "| What | Kind | Why |", "| --- | --- | --- |"]
        out += [f"| {r['what']} | {r['kind']} | {r['why']} |" for r in architecture["refusals"]]
        out.append("")

    unsourced = (architecture.get("research") or {}).get("unsourced_subscores") or []
    if unsourced:
        out += ["## What rests on nothing", "",
                "Sub-scores with no evidence behind them. They are excluded from their option's "
                "score rather than counted as zero, and they are listed here so the reader knows "
                "which parts of this recommendation are unevidenced:", ""]
        out += [f"- `{u}`" for u in unsourced] + [""]

    if check:
        out += ["## Audit", "",
                f"{'PASSED' if check.get('ok') else 'FAILED'} — checked {check.get('checked')}.",
                ""]
        for finding in check.get("findings") or []:
            out.append(f"> **{finding['kind']}** — {finding['detail']}")
        out.append("")

    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("architecture")
    ap.add_argument("--costs")
    ap.add_argument("--diagram", default="architecture.png")
    ap.add_argument("-o", "--output")
    ap.add_argument("--csv", help="write cost-breakdown.csv here")
    args = ap.parse_args()

    architecture = json.loads(Path(args.architecture).read_text(encoding="utf-8"))
    costs = json.loads(Path(args.costs).read_text(encoding="utf-8")) if args.costs else None
    text = markdown(architecture, costs, args.diagram, architecture.get("check"),
                    caps.load_model(), caps.load_platforms())
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text)
    if args.csv and costs:
        header, body = price.to_rows(costs)
        with open(args.csv, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            writer.writerows(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
