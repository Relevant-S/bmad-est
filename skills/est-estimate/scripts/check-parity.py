#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Verify the interactive report's JavaScript reproduces the Python engine exactly.

The report re-implements the aggregation so a presale lead can cut scope against a live
number. That is duplicated model logic in a second language, and duplicated logic drifts:
the JS once omitted the systematic model-risk term and rendered a band half the real
width, under a headline that included it. Nothing caught it, because no test ran the JS.

This executes the page's own computation block — extracted between the PARITY markers, so
it is the same source the browser runs, not a copy — and compares the full interval plus
every phase and role total.

    uv run scripts/check-parity.py <estimate.json>

Exit 0 when they agree, 1 when they drift, 2 when node is unavailable or input unreadable.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "assets" / "report-template.html"
# Loose enough to absorb the engine rounding its published figures to one decimal, tight
# enough that any real divergence is orders of magnitude larger — the model_risk omission
# this harness was written for showed up as 99 hours.
TOLERANCE = 0.15


def parity_block():
    text = TEMPLATE.read_text(encoding="utf-8")
    match = re.search(r"/\* PARITY-BLOCK-START.*?\*/(.*?)/\* PARITY-BLOCK-END \*/", text, re.S)
    if not match:
        raise SystemExit("report-template.html is missing its PARITY markers")
    return match.group(1)


def run_js(estimate, options):
    # The page reads its options off E, so put them there rather than declaring a second
    # binding the extracted block would collide with.
    payload = dict(estimate)
    payload["_render_options"] = options
    script = f"""
const E = {json.dumps(payload)};
const M = E.cost_model_snapshot;
{parity_block()}
const r = compute(new Set(E.features.map(f => f.id)));
console.log(JSON.stringify({{low: r.low, likely: r.mean, high: r.high,
                            phases: r.phases, roles: r.roles}}));
"""
    # Handed to node as a file, never as `node -e`. The script embeds the whole estimate, and
    # a story-grained inventory runs to megabytes of JSON — well past the OS argv ceiling, which
    # fails as `OSError: Argument list too long` before node is even reached. That turned the
    # parity check into a no-op on exactly the large estimates it most needs to guard.
    handle = tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8", delete=False)
    try:
        with handle:
            handle.write(script)
        result = subprocess.run(["node", handle.name], capture_output=True, text=True, timeout=60)
    finally:
        os.unlink(handle.name)
    if result.returncode != 0:
        raise SystemExit(f"node failed: {result.stderr.strip()[:400]}")
    return json.loads(result.stdout)


def compare(estimate, js):
    drift = []
    for key in ("low", "likely", "high"):
        a, b = estimate["total_hours"][key], js[key]
        if abs(a - b) > TOLERANCE:
            drift.append({"field": f"total_hours.{key}", "engine": round(a, 2),
                          "browser": round(b, 2), "delta": round(b - a, 2)})
    for phase, row in estimate["by_phase"].items():
        b = js["phases"].get(phase)
        if b is None or abs(row["hours"] - b) > TOLERANCE:
            drift.append({"field": f"by_phase.{phase}", "engine": row["hours"],
                          "browser": None if b is None else round(b, 2)})
    for role, hours in estimate["by_role"].items():
        b = js["roles"].get(role)
        if b is None or abs(hours - b) > TOLERANCE:
            drift.append({"field": f"by_role.{role}", "engine": hours,
                          "browser": None if b is None else round(b, 2)})
    return drift


def main():
    ap = argparse.ArgumentParser(description="Check JS/Python parity for the interactive report.")
    ap.add_argument("estimate", help="path to estimate.json")
    args = ap.parse_args()

    if not shutil.which("node"):
        print(json.dumps({"ok": False, "error": "node is not available; parity cannot be checked"},
                         indent=2))
        return 2
    try:
        estimate = json.loads(Path(args.estimate).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 2

    recorded = estimate.get("inputs", {})
    options = {"stack": recorded.get("stack", "standard_saas"),
               "qa_platform": recorded.get("qa_platform", "web"),
               "engagement": recorded.get("engagement", "standard"),
               "team_size": recorded.get("team_size")}
    drift = compare(estimate, run_js(estimate, options))
    print(json.dumps({"ok": not drift, "checked": ["total_hours", "by_phase", "by_role"],
                      "drift": drift}, indent=2))
    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(main())
