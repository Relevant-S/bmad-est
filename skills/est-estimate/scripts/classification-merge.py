#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Re-key a classification onto a re-extracted Feature Inventory.

Before the split, a re-extraction could silently revert a tag a human had confirmed, and
`inventory-diff.py` existed largely to stop it. Now a re-extraction cannot touch a judgement at
all — the judgements live here, in their own file. What it can still do is renumber the feature
a judgement belonged to, and an orphaned classification is the same loss wearing a different
shape: the story gets re-classified from scratch and the human's correction is gone.

So this carries that rule across. It matches features the way the diff does — by id, then by
name similarity — and refuses the two calls the diff also refused to make alone:

- a `confirmed` or `overridden` tag whose story's description materially changed. The human
  judged different text. Carried forward, and reported, because the alternative is a machine
  quietly overwriting a person.
- a classification with nowhere to go. Listed, never dropped.

    uv run classification-merge.py <classification.json> --old <old-inventory> --new <new-inventory>

Exit 0 on a clean re-key, 1 when something needs a human, 2 on unreadable input.
"""

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Correct while both skills sit under one parent, which is the normal install. --matcher
# recovers any other layout. Importing rather than reimplementing matters here: two
# definitions of "the same story" that drift apart would re-key some judgements and orphan
# others, and nothing would report the disagreement.
DEFAULT_MATCHER = (Path(__file__).resolve().parent.parent.parent
                   / "est-scope-extract" / "scripts" / "inventory-diff.py")

CHANGED_DESCRIPTION = 0.95


def matcher(path=None):
    target = Path(path or DEFAULT_MATCHER)
    if not target.exists():
        raise SystemExit(json.dumps({
            "ok": False,
            "error": f"cannot find inventory-diff.py at {target}; pass --matcher",
        }, indent=2))
    spec = importlib.util.spec_from_file_location("inventory_diff", target)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def remap(classification, old_inv, new_inv, diff):
    """Returns (classification, needs_decision, orphans, unclassified, renumbered)."""
    def stories(inv):
        return list(inv.get("features") or []) + list(inv.get("implicit_scope") or [])

    # Implicit scope is matched alongside features on purpose: it is priced identically, so a
    # renumbered I3 orphans its judgement exactly as a renumbered F3 would.
    pairs, _, _ = diff.match_features(stories(old_inv), stories(new_inv))
    rows = (classification or {}).get("features") or {}
    new_by_id = {f.get("id"): f for f in stories(new_inv)}

    moved, needs_decision, renumbered = {}, [], []
    for old, new, how in pairs:
        old_id, new_id = old.get("id"), new.get("id")
        tags = rows.get(old_id)
        if not tags:
            continue
        moved[new_id] = tags
        if old_id != new_id:
            # Counted, not queued. A re-extraction renumbers wholesale, and 364 identical
            # "this moved" prompts would bury the two that need a person.
            renumbered.append({"from": old_id, "to": new_id, "matched_by": how})
        if diff.similarity(old.get("description"), new.get("description")) >= CHANGED_DESCRIPTION:
            continue
        for axis, tag in tags.items():
            if (tag or {}).get("status") in ("confirmed", "overridden"):
                needs_decision.append({
                    "feature": new_id, "kind": "human_tag_over_changed_source",
                    "detail": (f"{axis} was set to '{tag.get('value')}' by a human, but this "
                               f"story's description changed in the new sources. The human value "
                               f"was carried forward — confirm it still holds."),
                })

    # Anything still keyed to a feature that survived unrenumbered comes across untouched.
    for fid, tags in rows.items():
        if fid in new_by_id and fid not in moved:
            moved[fid] = tags

    orphans = sorted(set(rows) - {old.get("id") for old, _, _ in pairs} - set(new_by_id))
    unclassified = sorted(fid for fid in new_by_id if fid not in moved)

    out = json.loads(json.dumps(classification))
    out["features"] = moved
    out["generated"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    out["how"] = (f"{out.get('how', 'classified')} — re-keyed onto a re-extraction "
                  f"({len(moved)} carried, {len(orphans)} orphaned, {len(unclassified)} new)")
    return out, needs_decision, orphans, unclassified, renumbered


def main():
    ap = argparse.ArgumentParser(
        description="Re-key a classification onto a re-extracted Feature Inventory.",
        epilog="Exit codes: 0 clean, 1 a human must decide something, 2 unreadable input.",
    )
    ap.add_argument("classification", help="the existing classification.json")
    ap.add_argument("--old", required=True, help="the inventory it was classified against")
    ap.add_argument("--new", required=True, help="the re-extracted inventory")
    ap.add_argument("-o", "--output", help="write the re-keyed classification here "
                                           "(default: overwrite in place)")
    ap.add_argument("--matcher", help="path to inventory-diff.py, if the skills are not siblings")
    args = ap.parse_args()

    try:
        classification = json.loads(Path(args.classification).read_text(encoding="utf-8"))
        old_inv = json.loads(Path(args.old).read_text(encoding="utf-8"))
        new_inv = json.loads(Path(args.new).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 2

    out, needs_decision, orphans, unclassified, renumbered = remap(
        classification, old_inv, new_inv, matcher(args.matcher))

    target = Path(args.output or args.classification)
    target.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(json.dumps({
        "ok": not (needs_decision or orphans),
        "written": str(target),
        "carried": len(out["features"]),
        "renumbered": len(renumbered),
        "renumbered_sample": renumbered[:5],
        "orphans": orphans,
        "unclassified": unclassified,
        "needs_decision": needs_decision,
        "next": ("classify the unclassified ids and answer each needs_decision before pricing"
                 if (unclassified or needs_decision) else "ready to price"),
    }, indent=2, ensure_ascii=False))
    return 1 if (needs_decision or orphans) else 0


if __name__ == "__main__":
    sys.exit(main())
