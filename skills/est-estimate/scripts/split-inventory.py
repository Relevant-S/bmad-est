#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Split a legacy Feature Inventory into scope and classification.

Inventories written before the split carry their classification inline, which is how an
extraction skill ended up deciding what work costs. This moves the five axes into a
`classification.json` keyed by feature id and leaves the inventory holding what the source
actually said.

Nothing is judged here and nothing is dropped: every `value`, `why`, `status` and `triggers`
crosses over byte-for-byte, so a human's `confirmed` tag survives the move intact. That matters
more than it sounds — losing a human's classification correction is the one failure that makes
people stop trusting the tool.

There is deliberately no fallback in the engine for a legacy inventory. One code path, one
migration, run once per workspace.

    uv run split-inventory.py <inventory.json> [-o <classification.json>] [--in-place]

Exit 0 on a written split, 1 when the inventory carries no tags to move, 2 on unreadable input.
"""

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

AXES = ("size_band", "compressibility", "review_tier", "clarity", "novelty")


def split(inventory, inventory_path):
    """Returns (scope, classification, notes). Never mutates the input."""
    scope = json.loads(json.dumps(inventory))
    features, notes = {}, []

    for key in ("features", "implicit_scope"):
        for feature in scope.get(key) or []:
            tags = feature.pop("tags", None)
            if not isinstance(tags, dict):
                continue
            # `surfaces` was half-migrated into the tag block and is an observation about the
            # scope, not a judgement about effort. It goes back where the schema always had it.
            surfaces = tags.pop("surfaces", None)
            if surfaces is not None and not feature.get("surfaces"):
                value = surfaces.get("value") if isinstance(surfaces, dict) else surfaces
                if value:
                    feature["surfaces"] = value
                    notes.append(f"{feature.get('id')}: surfaces moved out of tags onto the feature")
            kept = {axis: tags[axis] for axis in AXES if axis in tags}
            missing = [axis for axis in AXES if axis not in kept]
            if missing:
                notes.append(f"{feature.get('id')}: no {', '.join(missing)} to move")
            for extra in set(tags) - set(AXES):
                notes.append(f"{feature.get('id')}: dropped unknown axis '{extra}'")
            if kept:
                features[feature["id"]] = kept

    classification = {
        "schema_version": "1.0",
        "generated": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "inventory": str(inventory_path),
        "how": "split out of an inventory that carried its tags inline; no judgement was re-made",
        "features": features,
    }
    return scope, classification, notes


def main():
    ap = argparse.ArgumentParser(
        description="Split a legacy Feature Inventory into scope and classification.",
        epilog="Exit codes: 0 split written, 1 nothing to split, 2 unreadable input.",
    )
    ap.add_argument("inventory", help="path to a feature-inventory.json carrying inline tags")
    ap.add_argument("-o", "--output", help="where to write classification.json "
                                           "(default: beside the inventory)")
    ap.add_argument("--in-place", action="store_true",
                    help="rewrite the inventory without its tags, keeping a .bak")
    args = ap.parse_args()

    path = Path(args.inventory)
    try:
        inventory = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": f"cannot read {path}: {exc}"}, indent=2))
        return 2

    scope, classification, notes = split(inventory, path)
    if not classification["features"]:
        print(json.dumps({
            "ok": False,
            "error": "no inline tags found — this inventory is already split, or it is empty",
        }, indent=2))
        return 1

    target = Path(args.output) if args.output else path.parent / "classification.json"
    target.write_text(json.dumps(classification, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")
    if args.in_place:
        shutil.copyfile(path, path.with_suffix(path.suffix + ".bak"))
        path.write_text(json.dumps(scope, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(json.dumps({
        "ok": True,
        "classification": str(target),
        "features_moved": len(classification["features"]),
        "inventory": str(path) if args.in_place else "unchanged — pass --in-place to strip the tags",
        "notes": notes,
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
