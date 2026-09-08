#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Move a cost model from schema 1.x to 2.0.

Three things changed shape, and none of them can be carried across by arithmetic:

  role_weights   Roles are now conditional on a story's surfaces, and the architect has left
                 per-story work entirely. A flat weight table encodes the structure that
                 change exists to remove, so its numbers cannot be preserved without
                 preserving the thing being fixed.
  overhead_rate  Was a share of the subtotal; is now hours per person per week. There is no
                 conversion between a proportion and a rate — the old value says nothing
                 about how long a status call takes.
  env_infra      One opaque per-stack number became `standing_work`: itemised setup, pipeline,
                 environment and release work, priced through the same engine as a story.

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
REPLACED = ("role_weights", "overhead_rate", "surfaces", "standing_work", "phase_map")


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
            notes.append(f"{key} replaced with the 2.0 seed — its shape changed, so the old "
                         f"values could not be carried across.")
        out[key] = seed[key]
    out["schema_version"] = "2.0"
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

    if str(model.get("schema_version", "1.0")).startswith("2"):
        print(json.dumps({"ok": True, "migrated": False,
                          "note": f"already schema {model['schema_version']}"}, indent=2))
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
