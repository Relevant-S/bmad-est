#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Prove the diagram renderer works, at install time rather than at delivery time.

The infrastructure diagram is a REQUIRED output of est-architect, so the renderer is not an
optional extra that a run can skip with a note — it is a dependency, and `est-setup`'s job is
to prepare everything. A setup that reports success while the renderer is absent has only
moved the failure to the first artefact a client sees.

So this does not check that three commands exist. It renders a real fixture through the real
pipeline and looks at the bytes that come back.

    uv run scripts/check-renderer.py            # verify, report JSON
    uv run scripts/check-renderer.py --install  # install the pinned CLI first, then verify

Exit 0 when a diagram rendered, 1 when the toolchain is present but the render failed,
2 when a prerequisite is missing.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "assets"

# PINNED. The package was six weeks old at the time this module was built and is explicitly
# closed to outside contribution, which makes "whatever npm resolves today" the wrong default:
# a required output must not change shape because an upstream minor shipped overnight.
CLI_PACKAGE = "@eraserlabs/diagrams-cli"
CLI_VERSION = "0.2.0"

# The layout engine. `@eraserlabs/layout` routes connections and explicitly "treats entity
# placement as input", so without this nothing decides where a box goes. Pinned for the same
# reason as the renderer: a required output must not change shape because an upstream minor
# shipped overnight. Dual-licensed EPL-2.0 OR GPL-3.0-or-later; we take EPL-2.0, install it at
# setup time into this gitignored directory, and never vendor it — the same posture as the
# MIT-licensed renderer beside it.
LAYOUT_PACKAGE = "elkjs"
LAYOUT_VERSION = "0.12.0"
LAYOUT_LICENCE = "EPL-2.0"

MIN_NODE = (22, 12)

CHROMIUM_CANDIDATES = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable", "/snap/bin/chromium",
)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

FIXTURE = {
    "entities": [
        {"tag": "Group", "id": "g", "title": {"text": "Fixture"}, "color": "blue",
         "x": 20, "y": 20, "width": 360, "height": 150},
        {"tag": "Icon", "id": "api", "icon": "server", "size": "md", "x": 60, "y": 80,
         "containerId": "g", "texts": [{"text": "API"}]},
        {"tag": "Icon", "id": "db", "icon": "postgres", "size": "md", "x": 260, "y": 80,
         "containerId": "g", "texts": [{"text": "Postgres"}]},
    ],
    "connections": [{"from": "api", "to": "db", "label": "SQL", "endArrowhead": "triangle"}],
}


def node_version():
    node = shutil.which("node")
    if not node:
        return None, None
    try:
        raw = subprocess.run([node, "--version"], capture_output=True, text=True,
                             timeout=30).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return node, None
    parts = raw.lstrip("v").split(".")
    try:
        return node, tuple(int(p) for p in parts[:2])
    except ValueError:
        return node, None


def find_chromium(explicit=None):
    for candidate in (explicit, os.environ.get("CHROMIUM_PATH")):
        if candidate and Path(candidate).exists():
            return candidate, "given"
    for candidate in CHROMIUM_CANDIDATES:
        if Path(candidate).exists():
            return candidate, "auto-detected"
    found = shutil.which("chromium") or shutil.which("google-chrome")
    return (found, "found on PATH") if found else (None, None)


def layout_engine(directory):
    """Is the pinned layout engine installed? Without it there is no diagram to degrade to."""
    entry = Path(directory) / "node_modules" / LAYOUT_PACKAGE
    if not entry.exists():
        return None
    try:
        version = json.loads((entry / "package.json").read_text(encoding="utf-8")).get("version")
    except (OSError, ValueError):
        version = None
    return {"package": LAYOUT_PACKAGE, "version": version, "pinned": LAYOUT_VERSION,
            "licence": LAYOUT_LICENCE, "path": str(entry)}


def install(directory):
    """Install the pinned CLI and layout engine so neither version can drift under the module."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    existing = directory / "package.json"
    if existing.exists():
        # An install from before the layout engine existed has a package.json without it.
        try:
            spec = json.loads(existing.read_text(encoding="utf-8"))
        except ValueError:
            spec = {}
        deps = spec.setdefault("dependencies", {})
        if deps.get(LAYOUT_PACKAGE) != LAYOUT_VERSION or deps.get(CLI_PACKAGE) != CLI_VERSION:
            deps[CLI_PACKAGE] = CLI_VERSION
            deps[LAYOUT_PACKAGE] = LAYOUT_VERSION
            existing.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    if not (directory / "package.json").exists():
        (directory / "package.json").write_text(
            json.dumps({"name": "est-architect-renderer", "private": True,
                        "dependencies": {CLI_PACKAGE: CLI_VERSION,
                                         LAYOUT_PACKAGE: LAYOUT_VERSION}}, indent=2) + "\n",
            encoding="utf-8")
    result = subprocess.run(["npm", "install", "--no-audit", "--no-fund"],
                            cwd=directory, capture_output=True, text=True, timeout=600)
    return result.returncode == 0, (result.stderr or result.stdout)[-2000:]


def cli_command(directory):
    """The pinned local install if there is one, `npx` at the pinned version otherwise."""
    local = Path(directory) / "node_modules" / ".bin" / "eraser-diagrams"
    if local.exists():
        return [str(local)], "local pinned install"
    if shutil.which("npx"):
        return ["npx", "--yes", f"{CLI_PACKAGE}@{CLI_VERSION}"], "npx at the pinned version"
    return None, None


def render(document, out_path, chromium, directory, icon_cache=None, fmt="png", timeout=180):
    """Render one document. Returns (ok, detail)."""
    command, _ = cli_command(directory)
    if not command:
        return False, "no way to invoke the renderer: no local install and no npx"
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "diagram.json"
        source.write_text(json.dumps(document), encoding="utf-8")
        argv = command + ["render", str(source), "--format", fmt,
                          "--chromium-path", chromium, "-o", str(out_path)]
        if icon_cache:
            Path(icon_cache).mkdir(parents=True, exist_ok=True)
            argv += ["--icon-cache-dir", str(icon_cache)]
        try:
            result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return False, f"the renderer did not finish within {timeout}s"
        except OSError as exc:
            return False, f"could not start the renderer: {exc}"
    if result.returncode != 0:
        return False, (result.stderr or result.stdout or "").strip()[-2000:]
    return True, (result.stderr or "").strip()[-600:]


def verify(chromium=None, directory=None, do_install=False, icon_cache=None):
    directory = Path(directory or (ASSETS / "renderer"))
    report = {"ok": False, "pinned": f"{CLI_PACKAGE}@{CLI_VERSION}", "findings": []}

    node, version = node_version()
    report["node"] = {"path": node, "version": ".".join(map(str, version)) if version else None}
    if not node:
        report["findings"].append({"kind": "node_missing",
                                   "detail": "Node is not installed. The renderer needs Node "
                                             f"{MIN_NODE[0]}.{MIN_NODE[1]} or newer."})
        return report, 2
    if version and version < MIN_NODE:
        report["findings"].append({
            "kind": "node_too_old",
            "detail": f"Node {'.'.join(map(str, version))} is older than the "
                      f"{MIN_NODE[0]}.{MIN_NODE[1]} the renderer requires."})
        return report, 2

    path, how = find_chromium(chromium)
    report["chromium"] = {"path": path, "how": how}
    if not path:
        report["findings"].append({
            "kind": "chromium_missing",
            "detail": "No Chromium-family browser found. The renderer does not bundle one. "
                      "Install Chrome or Chromium, or set CHROMIUM_PATH / est_chromium_path."})
        return report, 2

    if do_install:
        ok, detail = install(directory)
        report["install"] = {"ok": ok, "detail": detail if not ok else "installed"}
        if not ok:
            report["findings"].append({"kind": "install_failed", "detail": detail})
            return report, 2

    # The diagram is a required output and ELK decides where every box goes, so its absence is
    # a missing prerequisite rather than a degraded picture.
    report["layout_engine"] = layout_engine(directory)
    if not report["layout_engine"]:
        report["findings"].append({
            "kind": "layout_engine_missing",
            "detail": f"{LAYOUT_PACKAGE}@{LAYOUT_VERSION} is not installed, so nothing can decide "
                      f"where a component goes. Run this with --install."})
        return report, 2

    command, invoked_by = cli_command(directory)
    report["cli"] = {"invocation": " ".join(command) if command else None, "how": invoked_by}
    if not command:
        report["findings"].append({
            "kind": "cli_missing",
            "detail": f"{CLI_PACKAGE} is not installed and npx is unavailable. "
                      f"Run this with --install."})
        return report, 2

    # The part that makes this a proof rather than a survey.
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "fixture.png"
        ok, detail = render(FIXTURE, out, path, directory,
                            icon_cache=icon_cache or (ASSETS / "icon-cache"))
        size = out.stat().st_size if out.exists() else 0
        head = out.read_bytes()[:8] if out.exists() else b""
    report["fixture_render"] = {"ok": bool(ok and head == PNG_MAGIC and size > 0),
                                "bytes": size, "detail": detail}
    if not report["fixture_render"]["ok"]:
        report["findings"].append({
            "kind": "render_failed",
            "detail": f"the toolchain is present but the fixture did not render: {detail}"})
        return report, 1

    report["ok"] = True
    # Stamped here as well as on every architecture, because a project installs the module by
    # COPY: setup is where an operator can still be told which revision they are about to run.
    try:
        caps = __import__("importlib.util", fromlist=["util"])
        spec = caps.spec_from_file_location("capabilities", HERE / "capabilities.py")
        module = caps.module_from_spec(spec)
        spec.loader.exec_module(module)
        report["produced_by"] = module.revision()
    except Exception:                               # noqa: BLE001 - never fail setup on a stamp
        report["produced_by"] = None
    report["checked"] = (f"Node {report['node']['version']}, Chromium at {path} ({how}), "
                         f"{CLI_PACKAGE}@{CLI_VERSION} via {report['cli']['how']}, and a "
                         f"{size}-byte PNG rendered from a fixture with a group, two icons and "
                         f"a routed connection")
    return report, 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--install", action="store_true",
                    help="install the pinned CLI before verifying")
    ap.add_argument("--chromium-path")
    ap.add_argument("--dir", help="where the pinned install lives")
    ap.add_argument("--icon-cache")
    ap.add_argument("-o", "--output")
    args = ap.parse_args()

    report, code = verify(args.chromium_path, args.dir, args.install, args.icon_cache)
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return code


if __name__ == "__main__":
    sys.exit(main())
