#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Render the infrastructure diagram. A REQUIRED output, so a failure here fails the run.

Not optional, not skipped with a note, not degraded to a text fallback. `est-setup`'s job is to
prepare everything the module needs and the renderer is part of everything; a run that quietly
produced no diagram would move the failure to the first artefact a client sees.

Three things make the output trustworthy rather than merely present:

  * **an unknown icon is an error.** The renderer's default is a placeholder glyph and a
    warning, which is a required output degrading in the one way nobody notices until a client
    does. `--unknown-icon error` turns it into a failed run.
  * **the layout checks itself for overlap** before anything is rendered.
  * **the icons are cached to disk.** A required output that depends on a vendor's bucket being
    reachable is not a required output.

    uv run scripts/render-diagram.py <architecture.json> -o architecture.png

Exit 0 when a diagram was written, 1 when the render failed, 2 when the toolchain is missing.
"""

import argparse
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "assets"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


caps = _load("capabilities", HERE / "capabilities.py")
layout = _load("layout", HERE / "layout.py")
icons = _load("icons", HERE / "icons.py")
renderer = _load("check_renderer", HERE / "check-renderer.py")
routing = _load("diagram_check", HERE / "diagram-check.py")
theme = _load("theme", HERE / "theme.py")
graph = _load("graph", HERE / "graph.py")


def verified_icons():
    try:
        return set(json.loads((ASSETS / "icons.verified.json").read_text(encoding="utf-8"))["names"])
    except (OSError, KeyError, ValueError):                     # pragma: no cover - env-specific
        return set()


def unverified(doc, cache=None):
    """Icon names in this document that will not resolve to anything.

    A name is good if it is in the renderer's own catalogue (proved once, recorded in
    `icons.verified.json`) **or** if an official icon has been fetched into the cache for it.
    The cache is the mechanism that lets any service have its own art without bundling 2,693
    SVGs into this repository — the renderer serves any name it finds there.

    Checked before the browser boots, so the run says which name is wrong rather than producing
    a diagram full of placeholder glyphs and a warning nobody reads.
    """
    known = verified_icons()
    if not known:
        return []
    cached = set()
    directory = Path(cache or (ASSETS / "icon-cache"))
    if directory.is_dir():
        cached = {p.stem for p in directory.glob("*.svg")}
    return sorted({e["icon"] for e in doc["entities"]
                   if e.get("icon") and e["icon"] not in known and e["icon"] not in cached})


def api_render(doc, out_path, chromium, directory, cache, scale, fmt, measured_path):
    """Render through the renderer's LIBRARY, which the CLI cannot do for one output we need.

    `outputs: { json: true }` returns the measured document — final boxes and every connection's
    routed points — from the same browser pass that makes the PNG. Without it, "no arrow crosses
    a component" is something somebody says after looking at a picture.

    Returns (report, measured) or (None, None) when the API path is not available, in which case
    the caller falls back to the CLI and reports that nothing was checked.
    """
    import shutil
    import subprocess
    script = HERE / "render.mjs"
    entry = Path(directory) / "node_modules" / "@eraserlabs" / "diagrams" / "dist" / "index.js"
    if not script.exists() or not entry.exists() or not shutil.which("node"):
        return None, None
    request = {"mode": "render", "rendererDir": str(directory), "chromiumPath": chromium,
               "cacheDir": str(cache), "scale": scale, "unknownIcon": "error",
               # Sections E-G. Generated from the company palette rather than written here, so
               # the diagram and the workbook cannot drift into two visual identities.
               "theme": theme.render_config(),
               "document": doc, "json": str(measured_path)}
    request["png" if fmt == "png" else "html"] = str(out_path)
    try:
        result = subprocess.run(["node", str(script)], input=json.dumps(request),
                                capture_output=True, text=True, timeout=600)
        report = json.loads(result.stdout or "{}")
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return {"ok": False, "error": str(exc)}, None
    if not report.get("ok"):
        return report, None
    try:
        measured = json.loads(Path(measured_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        measured = None
    return report, measured


def render(architecture, out_path, model=None, platforms=None, chromium=None,
           directory=None, scale=2, fmt="png", doc_path=None, resolve_icons=True,
           measured_path=None, icon_cache=None, graph_path=None):
    model = model or caps.load_model()
    platforms = platforms if platforms is not None else caps.load_platforms()
    directory = Path(directory or (ASSETS / "renderer"))
    # A caller may point the icon cache somewhere else, and a test MUST. A stubbed resolver
    # writing into the shipped cache put a green square in `aws-simple-email-service.svg` and a
    # row for it in the audit manifest, and that square was then drawn on a client's diagram —
    # the "placeholder visuals" defect, authored by this repository's own test suite.
    cache = Path(icon_cache) if icon_cache else (ASSETS / "icon-cache")

    # Official icons first. Nothing is bundled: the vendors publish 2,693 architecture SVGs and
    # revise them quarterly, so they are fetched on demand into the renderer's cache. When the
    # network is unavailable every component falls back to its capability glyph, which ships
    # with the renderer — the diagram is a required output and still renders.
    resolution, manifest, lookup = {}, {}, {}
    report_note = None
    if resolve_icons:
        try:
            resolution, manifest = icons.resolve_components(
                architecture.get("components") or [], caps.capabilities(model),
                cache_dir=cache, renderer_dir=directory, stats=lookup)
            if not icon_cache:
                icons.save_manifest(manifest)
            if lookup.get("unresolved"):
                every = lookup["unresolved"] == lookup["looked_up"] and lookup["looked_up"] > 2
                report_note = (f"{lookup['unresolved']} of {lookup['looked_up']} products "
                               f"resolved to no official icon and drew their capability glyph"
                               + ("; the official-icon index was unreachable"
                                  if lookup.get("index") == "unreachable" else "")
                               + ("; EVERY lookup failed, which reads as no network rather than "
                                  "a gap in the catalogues" if every else ""))
        except Exception as exc:                    # noqa: BLE001 - never fail the diagram here
            resolution = {}
            report_note = (f"icon resolution unavailable ({type(exc).__name__}); using the "
                           f"capability glyphs")
    else:
        report_note = "icon resolution skipped"

    try:
        doc = layout.document(architecture, model, platforms, resolution, directory,
                              official={n for n in resolution.values() if n in manifest})
    except layout.LayoutUnavailable as exc:
        return ({"ok": False, "produced_by": caps.revision(), "findings": [{
            "kind": "layout_unavailable",
            "detail": f"{exc}. The layout engine is a build requirement, not a nicety: without "
                      f"it there is no diagram to degrade to. Run /est-setup."}]}, None, 2)
    plan = doc.pop("_layout", {})
    if graph_path and plan.get("graph"):
        # Step 1 of the pipeline, kept. The picture is an opinion about a graph; this is the
        # graph, and it is what the A-checks and the text form are both read from.
        staged = dict(plan["graph"], validation=graph.validate(plan["graph"]))
        Path(graph_path).write_text(json.dumps(staged, indent=2, ensure_ascii=False) + "\n",
                                    encoding="utf-8")

    drawn = [e for e in doc["entities"] if e.get("tag") == "Icon"]
    report = {"ok": False, "entities": len(doc["entities"]),
              "icon_lookup": lookup or None,
              "connections": len(doc["connections"]),
              # Only the ones that actually resolved. Counting the whole map counted the
              # capability glyphs too, so a run in which nothing resolved still reported a
              # number.
              "icons_resolved": len({n for n in resolution.values() if n in manifest}),
              "icons": {"official": sum(1 for e in drawn if not e.get("color")),
                        # F2: a glyph is the one that had to be tinted, because no vendor art
                        # exists for it. A vendor logo brings its own colour and is left alone.
                        "glyph": sum(1 for e in drawn if e.get("color")),
                        "raw": sorted(n for n, r in manifest.items()
                                      if r.get("normalised") is False)},
              "routing": None, "produced_by": caps.revision(),
              "layout": {"engine": "elk", "aspect": plan.get("aspect"),
                         "passes": len(plan.get("attempts") or []),
                         "iterations": plan.get("iterations"),
                         "longest_edge": plan.get("longest_edge"),
                         "graph": (plan.get("graph") or {}).get("notes")},
              "graph": graph.validate(plan["graph"]) if plan.get("graph") else None,
              "findings": []}
    if report_note:
        report["icons_note"] = report_note

    clashes = layout.overlaps(doc)
    if clashes:
        report["findings"].append({
            "kind": "layout_overlap",
            "detail": f"the layout placed overlapping siblings: {clashes}"})
        return report, doc, 1

    # A repeated logo is a NOTE. A vendor serving two capabilities draws its mark twice, because
    # that is what is true; the earlier rule sent the loser to a grey glyph, which is the one
    # thing the brief forbids — a substitute where official art exists.
    repeats = layout.repeated_icons(drawn)
    if repeats:
        report["repeated_icons"] = repeats

    bad = unverified(doc, cache)
    if bad:
        report["findings"].append({
            "kind": "unverified_icon",
            "detail": f"{', '.join(bad)} are not in assets/icons.verified.json. An icon that "
                      f"silently becomes a placeholder is a required output degrading where "
                      f"nobody looks — prove the name renders and add it to the manifest."})
        return report, doc, 1

    chromium_path, how = renderer.find_chromium(chromium)
    if not chromium_path:
        report["findings"].append({
            "kind": "chromium_missing",
            "detail": "no Chromium-family browser found; the diagram is a required output, so "
                      "run /est-setup to provision the renderer"})
        return report, doc, 2
    report["chromium"] = {"path": chromium_path, "how": how}

    if doc_path:
        Path(doc_path).write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                                  encoding="utf-8")

    cache.mkdir(parents=True, exist_ok=True)
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        measured_target = Path(measured_path or (Path(tmp) / "measured.json"))
        api, measured = api_render(doc, out_path, chromium_path, directory, cache, scale, fmt,
                                  measured_target)
        if api is None:
            code = cli_render(doc, out_path, chromium_path, directory, cache, scale, fmt, report)
            if code:
                return report, doc, code
            report["cli"] = {"how": "the pinned CLI; no measured geometry, so the routing of "
                                    "every connector is UNCHECKED"}
        elif not api.get("ok"):
            report["findings"].append({
                "kind": "render_failed",
                "detail": json.dumps(api.get("errors") or api.get("error") or api)[:2000]})
            return report, doc, 1
        else:
            report["cli"] = {"how": "the pinned renderer library", "pinned": renderer.CLI_VERSION}
            report["warnings"] = api.get("warnings") or []
            report["scene"] = api.get("scene")
            if measured:
                report["routing"] = routing.check(measured, authored=doc)

    path = Path(out_path)
    size = path.stat().st_size if path.exists() else 0
    head = path.read_bytes()[:8] if path.exists() else b""
    if (fmt == "png" and head != renderer.PNG_MAGIC) or not size:
        report["findings"].append({
            "kind": "render_failed",
            "detail": f"the renderer reported success but wrote {size} bytes"})
        return report, doc, 1

    # D2 is absolute: an edge may overlap its own endpoints and their containers, and nothing
    # else. A group crossing used to be a NOTE, which is exactly how a diagram whose third-party
    # edge ran through the Data group was measured, reported and shipped with exit 0.
    #
    # H2 is the one place a budget exists, because zero edge crossings is a planarity question
    # rather than a layout setting. `diagram-check` tolerates the first and fails on the rest.
    section_h = [f for f in ((report["routing"] or {}).get("findings") or [])
                 if f.get("severity", "fail") == "fail"]
    if section_h:
        by_check = {}
        for finding in section_h:
            by_check.setdefault(finding.get("check", "H1"), []).append(finding)
        report["findings"].append({
            "kind": "design_contract",
            "detail": "; ".join(
                f"{check}: " + ", ".join(
                    f.get("detail") or f"{f.get('connection', f.get('what'))} over "
                                       f"{f.get('what') or f.get('over')}"
                    for f in items[:3])
                for check, items in sorted(by_check.items()))})
        return report, doc, 1

    report["ok"] = True
    report["bytes"] = size
    report["checked"] = (
        f"{len(doc['entities'])} entities and {len(doc['connections'])} connections "
        f"rendered to a {size}-byte {fmt.upper()} at scale {scale}, with unknown icons treated as "
        f"errors; {report['icons']['official']} of {len(drawn)} icons are official art; "
        + ((report["routing"] or {}).get("checked") or "connector routing was NOT checked"))
    return report, doc, 0


def cli_render(doc, out_path, chromium_path, directory, cache, scale, fmt, report):
    """The pinned CLI. No measured geometry, so nothing can check the routing."""
    import subprocess
    import tempfile
    command, invoked_by = renderer.cli_command(directory)
    if not command:
        report["findings"].append({
            "kind": "cli_missing",
            "detail": f"{renderer.CLI_PACKAGE}@{renderer.CLI_VERSION} is not installed and npx "
                      f"is unavailable; run /est-setup"})
        return 2
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "diagram.json"
        source.write_text(json.dumps(doc), encoding="utf-8")
        argv = command + ["render", str(source), "--format", fmt,
                          "--chromium-path", chromium_path,
                          "--icon-cache-dir", str(cache),
                          "--unknown-icon", "error",
                          "--scale", str(scale), "-o", str(out_path)]
        try:
            result = subprocess.run(argv, capture_output=True, text=True, timeout=600)
        except (OSError, subprocess.SubprocessError) as exc:
            report["findings"].append({"kind": "render_failed", "detail": str(exc)})
            return 1
    if result.returncode != 0:
        report["findings"].append({
            "kind": "render_failed",
            "detail": (result.stderr or result.stdout or "no output").strip()[-2000:]})
        return 1
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("architecture")
    ap.add_argument("-o", "--output", default="architecture.png")
    ap.add_argument("--document", help="also write the eraser document here, so a render is "
                                       "reproducible without re-deriving it")
    ap.add_argument("--graph", help="write the semantic graph (step 1) beside the diagram")
    ap.add_argument("--measured", help="also write the measured document — final boxes and "
                                       "routed connector points — here")
    ap.add_argument("--format", default="png", choices=("png", "html"))
    ap.add_argument("--scale", type=int, default=2)
    ap.add_argument("--no-icon-resolution", action="store_true",
                    help="skip the official-icon lookup and draw the capability glyphs")
    ap.add_argument("--chromium-path")
    ap.add_argument("--platforms")
    ap.add_argument("--model")
    args = ap.parse_args()

    architecture = json.loads(Path(args.architecture).read_text(encoding="utf-8"))
    report, _, code = render(architecture, args.output, caps.load_model(args.model),
                             caps.load_platforms(args.platforms), args.chromium_path,
                             scale=args.scale, fmt=args.format, doc_path=args.document,
                             resolve_icons=not args.no_icon_resolution,
                             measured_path=args.measured, graph_path=args.graph)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
