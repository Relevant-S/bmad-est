#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""Assert a workspace holds the files the module declares, and nothing else.

A real workspace accumulated 8.5 MB for one 237 KB spreadsheet: a byte-identical `.check.json`
beside `check.json`, 1.5 MB of subagent findings under names invented that run, and another
project's backtest in the same folder. None of it was wrong exactly — it was undeclared, which
is worse, because nobody reading the folder could tell a current artefact from the wreckage of
an interrupted run.

    uv run scripts/check-outputs.py --skill est-estimate --workspace <dir>
    uv run scripts/check-outputs.py --skill est-estimate --workspace <dir> --strict

Exit 0 when the workspace matches, 1 when something is missing or undeclared, 2 on bad input.
Undeclared files are a finding; missing REQUIRED files are a finding; missing optional files
never are. `--strict` also fails on undeclared files, which is off by default so that a human
dropping a note in the folder does not fail a pipeline.
"""

import argparse
import fnmatch
import json
import re
import sys
from pathlib import Path

import yaml

MANIFEST = Path(__file__).resolve().parent.parent / "assets" / "module-outputs.yaml"
# `{...}` stands for one path segment the module fills in at run time — a source id, a slug,
# a date. Matching it as a literal would report every real file as undeclared.
PLACEHOLDER = re.compile(r"\{[^/}]*\}")


def to_glob(pattern):
    return PLACEHOLDER.sub("*", pattern)


def matches(path, patterns):
    return any(fnmatch.fnmatch(path, to_glob(p)) for p in patterns)


def check(skill, workspace, manifest):
    spec = manifest[skill]
    required = [e["path"] for e in spec.get("required") or []]

    # est-scope-extract, est-estimate and est-agent-estimator share one folder per project on
    # purpose — the estimate belongs beside the inventory it priced. So "undeclared" is judged
    # against everything the module declares for THIS workspace, not just the named skill's
    # own files, or every run would report its neighbour's output as debris.
    declared = list(required)
    for other, other_spec in manifest.items():
        if other_spec.get("workspace") != spec.get("workspace"):
            continue
        declared += [e["path"] for e in (other_spec.get("required") or [])]
        declared += [e["path"] for e in (other_spec.get("optional") or [])]

    present = sorted(
        str(p.relative_to(workspace)) for p in workspace.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    )

    missing = [p for p in required
               if not any(fnmatch.fnmatch(f, to_glob(p)) for f in present)]
    undeclared = [f for f in present if not matches(f, declared)]

    findings = []
    for path in missing:
        role = next((e.get("role", "") for e in (spec.get("required") or [])
                     if e["path"] == path), "")
        findings.append(f"missing: {path}" + (f" — {role}" if role else ""))
    for path in undeclared:
        findings.append(
            f"undeclared: {path} — either the module should not have written it, or "
            f"assets/module-outputs.yaml should say when it appears"
        )
    return {
        "skill": skill,
        "workspace": str(workspace),
        "files_present": len(present),
        "declared_required": len(required),
        "missing": missing,
        "undeclared": undeclared,
        "findings": findings,
    }


def main():
    ap = argparse.ArgumentParser(
        description="Verify a skill's workspace against the module's declared outputs.",
        epilog="Exit codes: 0 clean, 1 findings, 2 unreadable input.",
    )
    ap.add_argument("--skill", required=True, help="which est skill wrote this workspace")
    ap.add_argument("--workspace", required=True, help="the directory to check")
    ap.add_argument("--strict", action="store_true",
                    help="fail on undeclared files as well as missing required ones")
    ap.add_argument("--manifest", default=str(MANIFEST), help="override the manifest path")
    args = ap.parse_args()

    try:
        manifest = yaml.safe_load(Path(args.manifest).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        print(json.dumps({"ok": False, "error": f"cannot read manifest: {exc}"}, indent=2))
        return 2

    if args.skill not in manifest:
        print(json.dumps({"ok": False, "error": f"unknown skill '{args.skill}' — declared: "
                                                f"{sorted(manifest)}"}, indent=2))
        return 2

    workspace = Path(args.workspace)
    if not workspace.is_dir():
        print(json.dumps({"ok": False, "error": f"{workspace} is not a directory"}, indent=2))
        return 2

    result = check(args.skill, workspace, manifest)
    failing = bool(result["missing"]) or (args.strict and bool(result["undeclared"]))
    result["ok"] = not failing
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 1 if failing else 0


if __name__ == "__main__":
    raise SystemExit(main())
