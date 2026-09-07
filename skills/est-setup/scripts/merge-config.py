#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""Merge this module's configuration into BMad's TOML config, without disturbing anything else.

The stock template writes `_bmad/config.yaml`. This installation reads a four-layer TOML stack
through `_bmad/scripts/resolve_config.py`, so a YAML write here would report success and
configure nothing — every `est_*` setting would sit in a file nothing opens.

The target is `_bmad/custom/config.toml`, not `_bmad/config.toml`. The base layer carries a
header saying it is regenerated on every install and must be treated as read-only; the custom
layer is the one the installer never touches, so settings written here survive a reinstall.
Personal values go to `custom/config.user.toml`, which that directory's .gitignore already
excludes.

Editing is a text splice rather than a parse-and-rewrite, because the file is hand-editable and
carries comments a round-trip through a serializer would silently delete.

Exit codes: 0=written, 1=validation error, 2=runtime error.
"""

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

try:
    import yaml
except ImportError:
    print("Error: pyyaml is required (PEP 723 dependency)", file=sys.stderr)
    raise SystemExit(2)

CUSTOM_HEADER = """# Team / enterprise overrides for _bmad/config.toml.
# Committed to the repo — applies to every developer on the project.
# Tables deep-merge over base config; keyed entries merge by key.
"""

USER_HEADER = """# Personal overrides. Gitignored — yours alone.
"""


def toml_value(value):
    """Serialise the value types a module.yaml variable can hold."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json.dumps(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(toml_value(v) for v in value) + "]"
    return json.dumps(str(value), ensure_ascii=False)


MARKER = "written by {code}-setup"


def strip_table(text, table, marker=None):
    """Remove `[table]` and everything under it, up to the next top-level header.

    Anti-zombie: a value removed from module.yaml must not survive in the file, and a rerun
    must not leave two copies of the same key for the resolver to pick between.
    """
    # Also consume this script's own comment line above the header — without that, every rerun
    # orphans the previous one and the file accumulates them. Matched on the marker rather than
    # on "any comment", so a note a human wrote above the table is never eaten.
    own_comment = (r"(?:^[ \t]*#[^\n]*" + re.escape(marker) + r"[^\n]*\n)?") if marker else ""
    pattern = re.compile(
        own_comment + r"^\[" + re.escape(table) + r"(?:\.[^\]]+)?\][ \t]*$.*?(?=^\[|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    stripped, count = pattern.subn("", text)
    if marker:
        # A note someone wrote between our comment and the table breaks the contiguity above,
        # which would leave the old marker line stranded. Sweep any line carrying the marker —
        # that exact text is ours, so this can only ever remove what this script wrote.
        stripped = "\n".join(line for line in stripped.split("\n") if marker not in line)
    return stripped.rstrip() + ("\n" if stripped.strip() else ""), count


def render_table(table, values, comment=None):
    lines = []
    if comment:
        lines.append(f"# {comment}")
    lines.append(f"[{table}]")
    for key, value in values.items():
        lines.append(f"{key} = {toml_value(value)}")
    return "\n".join(lines) + "\n"


def merge_into(path: Path, table: str, values: dict, header: str, comment=None, marker=None):
    """Splice one table into a TOML file, creating it if absent. Returns (action, removed)."""
    existing = path.read_text(encoding="utf-8") if path.exists() else header
    body, removed = strip_table(existing, table, marker)
    if not body.endswith("\n"):
        body += "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body + "\n" + render_table(table, values, comment), encoding="utf-8")
    return ("updated" if removed else "added"), removed


def apply_result(spec, value):
    """A variable may carry a `result` template that transforms the answer."""
    template = spec.get("result") if isinstance(spec, dict) else None
    if not template or not isinstance(value, str):
        return value
    return template.replace("{value}", value)


def main():
    ap = argparse.ArgumentParser(
        description="Merge module config into BMad's TOML layers, preserving comments.")
    ap.add_argument("--module-yaml", required=True, help="the module definition")
    ap.add_argument("--answers", required=True, help="JSON file of collected answers")
    ap.add_argument("--custom-config", required=True,
                    help="path to _bmad/custom/config.toml (team, committed)")
    ap.add_argument("--custom-user-config", required=True,
                    help="path to _bmad/custom/config.user.toml (personal, gitignored)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    for name, value in (("--custom-config", args.custom_config),
                        ("--custom-user-config", args.custom_user_config)):
        if "{project-root}" in value:
            print(json.dumps({"status": "error", "message":
                              f"{name} still contains the literal token {{project-root}}. Resolve "
                              f"it to the real project root before running — the token belongs in "
                              f"config values, never in a filesystem path argument."}), file=sys.stdout)
            return 1

    try:
        module = yaml.safe_load(Path(args.module_yaml).read_text(encoding="utf-8"))
        answers = json.loads(Path(args.answers).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "message": str(exc)}))
        return 2

    code = module.get("code")
    if not code:
        print(json.dumps({"status": "error", "message": "module.yaml has no `code`"}))
        return 1

    known = {k: v for k, v in module.items()
             if isinstance(v, dict) and "prompt" in v}
    supplied = answers.get("module") or {}
    unknown = sorted(set(supplied) - set(known))
    if unknown:
        print(json.dumps({"status": "error", "message":
                          f"answers contain keys that are not in module.yaml: {unknown}. A setting "
                          f"nothing declares is a setting nothing reads."}))
        return 1

    shared, personal = {}, {}
    for key, spec in known.items():
        value = apply_result(spec, supplied.get(key, spec.get("default")))
        (personal if spec.get("user_setting") else shared)[key] = value

    result = {"status": "success", "module_code": code, "written": {}}
    if shared:
        action, removed = merge_into(
            Path(args.custom_config), f"modules.{code}", shared, CUSTOM_HEADER,
            comment=f"{module.get('name', code)} — {MARKER.format(code=code)}. Team-shared.",
            marker=MARKER.format(code=code))
        result["written"]["custom_config"] = {"path": args.custom_config, "action": action,
                                              "keys": sorted(shared), "replaced": removed}
    if personal:
        action, removed = merge_into(
            Path(args.custom_user_config), f"modules.{code}", personal, USER_HEADER,
            comment=f"{module.get('name', code)} — {MARKER.format(code=code)}. Personal.",
            marker=MARKER.format(code=code))
        result["written"]["custom_user_config"] = {"path": args.custom_user_config,
                                                  "action": action, "keys": sorted(personal),
                                                  "replaced": removed}

    # Verify by reading back through the same parser the resolver uses. A config that was
    # written but does not parse is worse than one that was never written.
    for path in (args.custom_config, args.custom_user_config):
        target = Path(path)
        if not target.exists():
            continue
        try:
            parsed = tomllib.loads(target.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as exc:
            print(json.dumps({"status": "error", "message":
                              f"{path} does not parse after the merge ({exc}). Nothing downstream "
                              f"would read it. Restore the file and report this."}))
            return 2
        section = (parsed.get("modules") or {}).get(code)
        if section is not None:
            result.setdefault("verified", {})[path] = sorted(section)

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
