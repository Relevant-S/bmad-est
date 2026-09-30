#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""Turn a researched solution into a platform profile the scoring can use.

**The catalogue is a starting point, not a boundary.** Twenty profiles ship with this module;
the space of things a project might sensibly run on is far larger, and a workflow that can only
choose from what somebody hardcoded will keep recommending the same seven vendors. When the
right answer for a project is a platform the catalogue has never heard of, research it and add
it — here — and the scoring treats it exactly like a shipped one.

A profile is a data file and nothing else. If a platform ever needs code, the capability
boundary is in the wrong place, and that is the test this design has to keep passing.

Written into `{memory}/platforms/`, which merges over the shipped assets: a company's own
catalogue overrides and extends the module's without forking it.

    uv run scripts/profile-scaffold.py --id upstash --name Upstash --kind saas \\
        --serves cache=Upstash Redis --out {memory}/platforms
    uv run scripts/profile-scaffold.py --from researched.json --out {memory}/platforms
    uv run scripts/profile-scaffold.py --check {memory}/platforms

Exit 0 when the profile is valid, 1 when it is not.
"""

import argparse
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

RUNTIME_FIELDS = ("languages", "containers", "long_running", "background_jobs", "websockets",
                  "scheduled_jobs", "native_dependencies", "cold_start")
VOLATILE_FIELDS = ("regions", "certifications", "residency")
KINDS = ("iaas", "paas", "baas", "saas", "self-hosted")

UNVERIFIED = ("Never verified by this installation. NOT evidence of absence — a certification "
              "or residency gate against this is reported unevaluated. Research it, write the "
              "value, the URL and the date.")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


caps = _load("capabilities", HERE / "capabilities.py")


def scaffold(spec, model=None):
    """A complete profile from a researched description. Refuses to invent anything."""
    model = model or caps.load_model()
    catalogue = caps.capabilities(model)
    problems = []

    pid = (spec.get("id") or "").strip().lower()
    if not pid or not pid.replace("-", "").replace("_", "").isalnum():
        problems.append("`id` must be a short lowercase slug, e.g. `upstash`")
    if spec.get("kind") not in KINDS:
        problems.append(f"`kind` must be one of {', '.join(KINDS)}")
    if not spec.get("what"):
        problems.append("`what` must say what this platform IS and what it trades away — a "
                        "profile a reader cannot judge is a profile nobody can argue with")

    serves = {}
    for capability, entry in (spec.get("serves") or {}).items():
        if capability not in catalogue:
            problems.append(f"`{capability}` is not in the capability catalogue; add it to "
                            f"architecture-model.json first, or use an existing one")
            continue
        if isinstance(entry, str):
            entry = {"service": entry}
        if entry.get("serves_natively") is False or not entry.get("service"):
            # A recorded absence: "this platform has no managed cache" is a fact worth keeping,
            # and it is not the same as the capability being missing from the file.
            serves[capability] = {"service": None, "managed": None, "serves_natively": False,
                                  "note": entry.get("note") or "No offering for this capability."}
            continue
        interface = entry.get("interface")
        if interface not in ("standard", "proprietary"):
            problems.append(f"`serves.{capability}.interface` must be `standard` or "
                            f"`proprietary` — it drives the reversibility sub-score")
        serves[capability] = {
            "service": entry["service"],
            "managed": bool(entry.get("managed", True)),
            "interface": interface,
        }
        if entry.get("interface_why"):
            serves[capability]["interface_why"] = entry["interface_why"]
        # `icon` is deliberately optional: icons are resolved from the vendors' own catalogues
        # at render time, so a researched profile never has to name one.
        if entry.get("icon"):
            serves[capability]["icon"] = entry["icon"]

    if not serves:
        problems.append("a profile that serves nothing cannot be bound to anything")

    runtime = {}
    hosts = any(c in serves for c in ("application", "web_client"))
    for field in RUNTIME_FIELDS:
        if field in (spec.get("runtime") or {}):
            runtime[field] = spec["runtime"][field]
            why = spec["runtime"].get(f"{field}_why")
            if why:
                runtime[f"{field}_why"] = why
    if hosts:
        missing = [f for f in ("long_running", "background_jobs", "websockets")
                   if f not in runtime]
        if missing:
            problems.append(f"this platform hosts an application tier, so the runtime-fit "
                            f"sub-score needs {', '.join(missing)} — an unstated capability "
                            f"is treated as absent and the platform will lose unfairly")

    volatile = {}
    for field in VOLATILE_FIELDS:
        given = (spec.get("volatile") or {}).get(field) or {}
        if given.get("value") and not (given.get("checked") and given.get("url")):
            problems.append(f"`volatile.{field}` has a value with no `checked` date and `url`. "
                            f"A certification claim nobody can re-check is a compliance "
                            f"statement nobody checked.")
        volatile[field] = ({"value": given["value"], "checked": given["checked"],
                            "url": given["url"]}
                           if given.get("value") and given.get("checked") and given.get("url")
                           else {"value": None, "checked": None, "note": UNVERIFIED})

    profile = {
        "id": pid, "name": spec.get("name") or pid, "kind": spec.get("kind"),
        "what": spec.get("what"),
        "serves": serves, "runtime": runtime,
        "pricing": {"model": (spec.get("pricing") or {}).get("model") or "unknown",
                    "default_url": (spec.get("pricing") or {}).get("default_url")},
        "volatile": volatile,
        "researched": {"by": "est-architect", "on": spec.get("researched_on"),
                       "sources": spec.get("sources") or []},
    }
    if spec.get("note"):
        profile["note"] = spec["note"]
    return profile, problems


def check(directory, model=None):
    """Validate every profile in a directory the way the scaffold validates a new one."""
    findings = []
    for path in sorted(Path(directory).glob("*.yaml")):
        import yaml
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or not raw.get("id"):
            findings.append({"file": path.name, "detail": "not a profile"})
            continue
        _, problems = scaffold(raw, model)
        findings += [{"file": path.name, "detail": p} for p in problems]
    return findings


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="source", help="a researched profile as JSON")
    ap.add_argument("--check", help="validate every profile in a directory")
    ap.add_argument("--id")
    ap.add_argument("--name")
    ap.add_argument("--kind", choices=KINDS)
    ap.add_argument("--what")
    ap.add_argument("--serves", action="append", default=[],
                    help="capability=Service name, repeatable")
    ap.add_argument("--out", help="directory to write the profile into")
    args = ap.parse_args()

    model = caps.load_model()
    if args.check:
        findings = check(args.check, model)
        print(json.dumps({"ok": not findings, "checked": args.check,
                          "profiles": len(list(Path(args.check).glob("*.yaml"))),
                          "findings": findings}, indent=2))
        return 0 if not findings else 1

    if args.source:
        spec = json.loads(Path(args.source).read_text(encoding="utf-8"))
    else:
        spec = {"id": args.id, "name": args.name, "kind": args.kind, "what": args.what,
                "serves": dict(s.split("=", 1) for s in args.serves if "=" in s)}

    profile, problems = scaffold(spec, model)
    if problems:
        print(json.dumps({"ok": False, "findings": problems}, indent=2))
        return 1

    import yaml
    text = yaml.safe_dump(profile, sort_keys=False, allow_unicode=True, width=98,
                          default_flow_style=False)
    if args.out:
        target = Path(args.out)
        target.mkdir(parents=True, exist_ok=True)
        (target / f"{profile['id']}.yaml").write_text(text, encoding="utf-8")
        print(json.dumps({"ok": True, "written": str(target / f"{profile['id']}.yaml"),
                          "serves": sorted(profile["serves"])}, indent=2))
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
