#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Bring a cost model up to the shipped seed's schema.

Three things changed shape, and none of them can be carried across by arithmetic:

  role_weights   Roles are now conditional on a story's surfaces, and the architect has left
                 per-story work entirely. A flat weight table encodes the structure that
                 change exists to remove, so its numbers cannot be preserved without
                 preserving the thing being fixed.
  overhead_rate  Was a share of the subtotal; is now hours per person per week. There is no
                 conversion between a proportion and a rate — the old value says nothing
                 about how long a status call takes.
  env_infra      One opaque per-stack number became `standing_work`: itemised setup, pipeline,
                 environment and release work, with its own absolute hours rather than a size
                 band, so a band re-scale cannot silently re-price the catalogue.
  the unit       `size_bands` describes a STORY, not a feature. A 1.x model's bands are about
                 three times too large for the unit now being priced, and the rates that sat
                 alongside them were absorbing that error, so `compressibility`, `review_rate`,
                 `clarity` and `qa` come across with them or the model is internally inconsistent.

So those three are replaced with the shipped seed values and reported loudly. Everything a
calibration actually measured — size bands, compressibility, review rates, clarity, novelty,
team profiles, planning volume and rates, QA, uncertainty, calendar, and the whole
calibration_history — is carried across untouched.

    uv run scripts/migrate-cost-model.py <cost-model.json> [-o OUT] [--in-place]

Exit 0 on a written migration, 1 when the model is already 2.x, 2 on unreadable input.
"""

import argparse
import json
import shutil
import sys
from datetime import date
from pathlib import Path

SEED = Path(__file__).resolve().parent.parent / "assets" / "cost-model.seed.json"
REPLACED = ("role_weights", "overhead_rate", "surfaces", "standing_work", "phase_map",
            "size_bands", "compressibility", "review_rate", "clarity", "qa")

# Sub-keys, because the rest of `planning` is not unit-dependent. `agent_hours` and
# `review_hours` are hours per document, per epic and per story — real rates an operator may
# have calibrated, and replacing them wholesale to fix a counting rule would throw that away.
REPLACED_KEYS = {
    "planning": ("stories_per_feature", "stories_per_feature_why",
                 "features_per_epic", "features_per_epic_why"),
}


def migrate(model, seed):
    out, notes = {}, []
    for key, value in model.items():
        if key == "env_infra":
            notes.append(
                f"env_infra dropped (was {json.dumps(value.get('standard_saas', value))[:120]}) — "
                "replaced by standing_work, which itemises the same work as priced features. "
                "If that number was calibrated, re-decide the standing_work item sizes against it."
            )
            continue
        out[key] = value
    for key in REPLACED:
        if key in out:
            notes.append(f"{key} replaced with the shipped seed — its shape or its unit changed, "
                         f"so the old values could not be carried across.")
        out[key] = seed[key]
    for section, keys in REPLACED_KEYS.items():
        if section not in out:
            continue
        for key in keys:
            if key in seed.get(section, {}):
                out[section][key] = seed[section][key]
        notes.append(f"{section}.{{{', '.join(keys[::2])}}} replaced — they count the priced "
                     f"unit, and the priced unit is now a story. The rest of {section} is "
                     f"untouched.")

    out["schema_version"] = seed["schema_version"]

    # The replaced sections came from the seed, and the seed is fitted to a delivered project.
    # Adopting its numbers without its history would leave the model announcing itself
    # uncalibrated in every rendered estimate while carrying calibrated coefficients — the
    # contradiction this whole marker exists to prevent. An operator's own history is never
    # overwritten; theirs is the record of their projects, and it stays.
    if not out.get("calibration_history") and seed.get("calibration_history"):
        out["calibration_history"] = seed["calibration_history"]
        out["calibration_status"] = seed["calibration_status"]
        notes.append(
            "calibration_history adopted from the seed, because the replaced coefficients are "
            "the seed's and they are fitted to a delivered project. It is NOT a record of your "
            "projects — read calibration_status for whose, and how many.")
    out["migrated"] = {
        "on": date.today().isoformat(),
        "from": model.get("schema_version", "1.0"),
        "replaced": notes,
        "why": ("These sections were replaced rather than converted, because their shape "
                "changed. They are UNCALIBRATED again even if the rest of this model is not — "
                "re-curate them through est-calibrate/scripts/curate.py before quoting from "
                "them, and read the notes above for what the old values were."),
    }
    return out, notes


def main():
    ap = argparse.ArgumentParser(description="Migrate a cost model from schema 1.x to 2.0.")
    ap.add_argument("model", help="path to cost-model.json")
    ap.add_argument("-o", "--output", help="write here instead of stdout")
    ap.add_argument("--in-place", action="store_true",
                    help="rewrite the model, keeping a .pre-migration backup beside it")
    args = ap.parse_args()

    path = Path(args.model)
    try:
        model = json.loads(path.read_text(encoding="utf-8"))
        seed = json.loads(SEED.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 2

    # Compared against the shipped seed, not hard-coded to "starts with 2". 2.0 models exist
    # in the wild whose standing_work and role_weights predate the story-scale calibration,
    # and a guard that only knew about 1.x left them stranded on shapes the engine had moved past.
    def version(value):
        return tuple(int(part) for part in str(value).split(".") if part.isdigit())

    if version(model.get("schema_version", "1.0")) >= version(seed["schema_version"]):
        print(json.dumps({"ok": True, "migrated": False,
                          "note": f"already schema {model['schema_version']}; the shipped seed "
                                  f"is {seed['schema_version']}"}, indent=2))
        return 1

    migrated, notes = migrate(model, seed)
    text = json.dumps(migrated, indent=2, ensure_ascii=False) + "\n"

    if args.in_place:
        backup = path.with_suffix(".pre-migration.json")
        shutil.copy2(path, backup)
        path.write_text(text, encoding="utf-8")
        target, kept = str(path), str(backup)
    elif args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        target, kept = args.output, None
    else:
        sys.stdout.write(text)
        return 0

    print(json.dumps({"ok": True, "migrated": True, "written": target, "backup": kept,
                      "replaced": notes}, indent=2), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
