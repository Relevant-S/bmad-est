#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Diff two Feature Inventories — the scope-creep detector behind update mode.

Matches features by id first, then by name similarity, because a re-extraction of a
revised document renumbers freely. Reports what was added, removed, and changed.

This diffs scope only. Classification lives in classification.json now, so a
re-extraction cannot revert a human's judgement — it can only orphan one by renumbering
the feature it belonged to. `est-estimate/scripts/classification-merge.py` re-keys it,
reusing `match_features` from here so the two agree on what "the same story" means.
Losing a human's classification correction is still the one failure that makes people
stop trusting the tool; the split moved where it is prevented, not whether it is.
"""

import argparse
import json
import sys
from difflib import SequenceMatcher
from pathlib import Path

NAME_MATCH_THRESHOLD = 0.72


def similarity(a, b):
    return SequenceMatcher(None, (a or "").lower(), (b or "").lower()).ratio()


def match_features(old, new):
    """Pair old and new features by id, then greedily by name similarity."""
    old_by_id = {f.get("id"): f for f in old}
    pairs, used_old, used_new = [], set(), set()

    for f in new:
        fid = f.get("id")
        if fid in old_by_id:
            pairs.append((old_by_id[fid], f, "id"))
            used_old.add(fid)
            used_new.add(id(f))

    candidates = []
    for o in old:
        if o.get("id") in used_old:
            continue
        for n in new:
            if id(n) in used_new:
                continue
            score = similarity(o.get("name"), n.get("name"))
            if score >= NAME_MATCH_THRESHOLD:
                candidates.append((score, o, n))

    for score, o, n in sorted(candidates, key=lambda c: -c[0]):
        if o.get("id") in used_old or id(n) in used_new:
            continue
        pairs.append((o, n, f"name~{score:.2f}"))
        used_old.add(o.get("id"))
        used_new.add(id(n))

    removed = [o for o in old if o.get("id") not in used_old]
    added = [n for n in new if id(n) not in used_new]
    return pairs, added, removed


def compare(old, new):
    changes = []
    if (old.get("name") or "").strip() != (new.get("name") or "").strip():
        changes.append({"field": "name", "from": old.get("name"), "to": new.get("name")})
    if similarity(old.get("description"), new.get("description")) < 0.95:
        changes.append({"field": "description", "from": old.get("description"), "to": new.get("description")})
    if old.get("commitment") != new.get("commitment"):
        changes.append({"field": "commitment", "from": old.get("commitment"), "to": new.get("commitment")})

    old_deps = {d.get("feature_id") for d in old.get("depends_on", [])}
    new_deps = {d.get("feature_id") for d in new.get("depends_on", [])}
    if old_deps != new_deps:
        changes.append({
            "field": "depends_on",
            "added": sorted(new_deps - old_deps), "removed": sorted(old_deps - new_deps),
        })
    return changes


def build_merge(old_inv, new_inv, pairs, added, removed):
    """Produce the merged inventory deterministically, and list what a human must still decide.

    The new pass is the base, because it reflects the current documents. Onto it go the stable
    feature ids from the old inventory — a ledger entry, and now a classification, may already
    reference them, and keeping them is what stops a re-extraction orphaning judgements it
    never touched. Cases the prompt is explicitly told not to decide alone come back as
    needs_decision rather than being decided.
    """
    merged = json.loads(json.dumps(new_inv))          # deep copy, no shared state
    by_identity = {id(n): (o, how) for o, n, how in pairs}
    needs_decision = []

    taken = {o.get("id") for o, _, _ in pairs}
    next_id = max([int(f["id"][1:]) for f in old_inv.get("features", []) + new_inv.get("features", [])
                   if str(f.get("id", "")).startswith("F") and f["id"][1:].isdigit()] or [0]) + 1

    remap = {}
    # Walk merged and new in lockstep: merged is a deep copy, so position n corresponds to
    # position n. Matching by value would pick the wrong feature whenever two are identical.
    for feature, source_feature in zip(merged.get("features", []), new_inv.get("features", [])):
        match = by_identity.get(id(source_feature))
        old = match[0] if match else None
        if old:
            remap[feature["id"]] = old["id"]
            feature["id"] = old["id"]
        else:
            while f"F{next_id}" in taken:
                next_id += 1
            remap[feature["id"]] = f"F{next_id}"
            feature["id"] = f"F{next_id}"
            taken.add(feature["id"])
            next_id += 1

        if not old:
            continue

        if old.get("scope_status") and not feature.get("scope_status"):
            feature["scope_status"] = old["scope_status"]

    for feature in merged.get("features", []):
        for dep in feature.get("depends_on", []):
            dep["feature_id"] = remap.get(dep["feature_id"], dep["feature_id"])

    for gone in removed:
        needs_decision.append({
            "feature": gone.get("id"), "kind": "feature_absent_from_new_sources",
            "detail": (f"'{gone.get('name')}' is not in the re-extracted inventory. Dropped scope, "
                       f"or simply absent because a different document was supplied? Not dropped "
                       f"automatically — decide and re-run."),
        })

    merged["generated"] = new_inv.get("generated")
    return merged, needs_decision


def main():
    ap = argparse.ArgumentParser(
        description="Diff two Feature Inventories and flag human classifications at risk of being overwritten.",
        epilog="Exit codes: 0 no differences, 1 differences found, 2 unreadable input.",
    )
    ap.add_argument("old", help="the existing feature-inventory.json")
    ap.add_argument("new", help="the freshly extracted feature-inventory.json")
    ap.add_argument("-o", "--output", help="write the JSON diff here instead of stdout")
    ap.add_argument("--merge", metavar="OUT",
                    help="also write the merged inventory here: the new pass with the old "
                         "inventory's stable feature ids preserved, so classification.json still "
                         "keys onto it")
    args = ap.parse_args()

    try:
        old_inv = json.loads(Path(args.old).read_text(encoding="utf-8"))
        new_inv = json.loads(Path(args.new).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2

    pairs, added, removed = match_features(old_inv.get("features", []), new_inv.get("features", []))

    changed = []
    for o, n, how in pairs:
        diffs = compare(o, n)
        if diffs:
            changed.append({"old_id": o.get("id"), "new_id": n.get("id"),
                            "name": n.get("name"), "matched_by": how, "changes": diffs})

    result = {
        "ok": True,
        "old": args.old,
        "new": args.new,
        "summary": {
            "added": len(added), "removed": len(removed),
            "changed": len(changed), "unchanged": len(pairs) - len(changed),
        },
        "added": [{"id": f.get("id"), "name": f.get("name")} for f in added],
        "removed": [{"id": f.get("id"), "name": f.get("name")} for f in removed],
        "changed": changed,
        # Ids that moved, so classification-merge.py can re-key judgements onto the new pass
        # without re-deriving the match this already computed.
        "matched": [{"old_id": o.get("id"), "new_id": n.get("id"), "matched_by": how}
                    for o, n, how in pairs],
    }

    if args.merge:
        merged, needs_decision = build_merge(old_inv, new_inv, pairs, added, removed)
        Path(args.merge).write_text(
            json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        result["merge"] = {"written": args.merge, "needs_decision": needs_decision}

    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)

    return 1 if (added or removed or changed) else 0


if __name__ == "__main__":
    sys.exit(main())
