#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Diff two Feature Inventories — the scope-creep detector behind update mode.

Matches features by id first, then by name similarity, because a re-extraction of a
revised document renumbers freely. Reports what was added, removed, and changed.

The load-bearing output is `protected`: every tag a human confirmed or overrode in the
old inventory that the re-extraction would silently revert to a machine guess. Those
must be carried forward, not applied. Losing a human's classification correction is the
one failure that makes people stop trusting the tool.
"""

import argparse
import json
import sys
from difflib import SequenceMatcher
from pathlib import Path

AXES = ["size_band", "compressibility", "review_tier", "clarity", "novelty"]
NAME_MATCH_THRESHOLD = 0.72


def tag(feature, axis, field="value"):
    return (feature.get("tags", {}).get(axis) or {}).get(field)


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

    for axis in AXES:
        if tag(old, axis) != tag(new, axis):
            changes.append({
                "field": f"tags.{axis}",
                "from": tag(old, axis), "to": tag(new, axis),
                "old_status": tag(old, axis, "status"), "new_status": tag(new, axis, "status"),
            })

    old_deps = {d.get("feature_id") for d in old.get("depends_on", [])}
    new_deps = {d.get("feature_id") for d in new.get("depends_on", [])}
    if old_deps != new_deps:
        changes.append({
            "field": "depends_on",
            "added": sorted(new_deps - old_deps), "removed": sorted(old_deps - new_deps),
        })
    return changes


def protected_tags(old, new):
    """Human decisions the re-extraction would silently discard."""
    out = []
    for axis in AXES:
        old_status = tag(old, axis, "status")
        if old_status not in ("confirmed", "overridden"):
            continue
        if tag(new, axis, "status") == "inferred" or tag(old, axis) != tag(new, axis):
            out.append({
                "feature": old.get("id"),
                "axis": axis,
                "human_value": tag(old, axis),
                "human_status": old_status,
                "human_why": tag(old, axis, "why"),
                "reextracted_value": tag(new, axis),
                "action": "carry the human value forward; do not apply the re-extracted one without asking",
            })
    return out


def summarize_tier_shift(pairs, added, removed):
    def count(features):
        return {t: sum(1 for f in features if tag(f, "review_tier") == t)
                for t in ("routine", "sensitive", "critical")}
    return {"added": count(added), "removed": count(removed),
            "retiered": [
                {"feature": n.get("id"), "from": tag(o, "review_tier"), "to": tag(n, "review_tier")}
                for o, n, _ in pairs if tag(o, "review_tier") != tag(n, "review_tier")
            ]}


def build_merge(old_inv, new_inv, pairs, added, removed):
    """Produce the merged inventory deterministically, and list what a human must still decide.

    The new pass is the base, because it reflects the current documents. Onto it are restored
    every human classification the diff marked protected, and the stable feature ids from the
    old inventory — a ledger entry elsewhere may already reference them. Cases the prompt is
    explicitly told not to decide alone come back as needs_decision rather than being decided.
    """
    merged = json.loads(json.dumps(new_inv))          # deep copy, no shared state
    by_identity = {id(n): (o, how) for o, n, how in pairs}
    needs_decision, restored = [], []

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

        # A human's classification outranks a fresh inference — restore it.
        for entry in protected_tags(old, feature):
            axis = entry["axis"]
            feature["tags"][axis] = json.loads(json.dumps(old["tags"][axis]))
            restored.append({"feature": feature["id"], "axis": axis,
                             "value": entry["human_value"], "status": entry["human_status"]})
            # If the source text behind the feature changed, the human's call may no longer hold.
            if similarity(old.get("description"), feature.get("description")) < 0.95:
                needs_decision.append({
                    "feature": feature["id"], "kind": "protected_tag_over_changed_source",
                    "detail": (f"{axis} was set to '{entry['human_value']}' by a human, but this "
                               f"feature's description changed in the new sources. The human value "
                               f"was carried forward — confirm it still holds."),
                })
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
    return merged, needs_decision, restored


def main():
    ap = argparse.ArgumentParser(
        description="Diff two Feature Inventories and flag human classifications at risk of being overwritten.",
        epilog="Exit codes: 0 no differences, 1 differences found, 2 unreadable input.",
    )
    ap.add_argument("old", help="the existing feature-inventory.json")
    ap.add_argument("new", help="the freshly extracted feature-inventory.json")
    ap.add_argument("-o", "--output", help="write the JSON diff here instead of stdout")
    ap.add_argument("--merge", metavar="OUT",
                    help="also write the merged inventory here: the new pass with every human "
                         "classification restored and stable feature ids preserved")
    args = ap.parse_args()

    try:
        old_inv = json.loads(Path(args.old).read_text(encoding="utf-8"))
        new_inv = json.loads(Path(args.new).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2

    pairs, added, removed = match_features(old_inv.get("features", []), new_inv.get("features", []))

    changed, protected = [], []
    for o, n, how in pairs:
        diffs = compare(o, n)
        if diffs:
            changed.append({"old_id": o.get("id"), "new_id": n.get("id"),
                            "name": n.get("name"), "matched_by": how, "changes": diffs})
        protected.extend(protected_tags(o, n))

    result = {
        "ok": True,
        "old": args.old,
        "new": args.new,
        "summary": {
            "added": len(added), "removed": len(removed),
            "changed": len(changed), "unchanged": len(pairs) - len(changed),
            "protected_tags": len(protected),
        },
        "added": [{"id": f.get("id"), "name": f.get("name"),
                   "review_tier": tag(f, "review_tier"), "size_band": tag(f, "size_band")} for f in added],
        "removed": [{"id": f.get("id"), "name": f.get("name"),
                     "review_tier": tag(f, "review_tier"), "size_band": tag(f, "size_band")} for f in removed],
        "changed": changed,
        "protected": protected,
        "review_tier_shift": summarize_tier_shift(pairs, added, removed),
    }

    if args.merge:
        merged, needs_decision, restored = build_merge(old_inv, new_inv, pairs, added, removed)
        Path(args.merge).write_text(
            json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        result["merge"] = {"written": args.merge, "restored_tags": restored,
                           "needs_decision": needs_decision}

    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)

    return 1 if (added or removed or changed) else 0


if __name__ == "__main__":
    sys.exit(main())
