#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""The capability layer: the catalogue, the platform profiles, and the map from a capability
to the stories it would implement.

Everything downstream rests on that map. The sourcing layer reads it for the work at stake,
the diagram reads it for each component's `serves`, and `architecture-check.py` reads it to
prove the scope did not move while an architecture was being chosen.

**The map is built by keyword signal and says so.** A signal match is weak evidence and is
labelled `how: "signal"` on every entry, with the phrase that matched. An operator confirming
or correcting one promotes it to `how: "operator"`, and the check reports the split — because
a map that looks authoritative and was built by substring search is exactly the kind of
confident wrong artefact this module exists to avoid.

    uv run scripts/capabilities.py <feature-inventory.json> [--estimate estimate.json]
"""

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "assets"
SEED = ASSETS / "architecture-model.seed.json"
PLATFORM_DIR = ASSETS / "platforms"

# The two capabilities that ARE the project rather than a choice about it. They take every
# story on the matching surface, because that is literally where those stories run.
PROJECT_CAPABILITIES = {"application": "backend", "web_client": "frontend"}


def memory_dir(start=None):
    """`{project-root}/_bmad/memory/est`, found by walking up from the working directory.

    The scripts are run from anywhere and are given no project root, so the module's own memory
    has to be discovered. Returns None when there is none, which is the fixture and first-run
    case.
    """
    here = Path(start or Path.cwd()).resolve()
    for directory in [here, *here.parents]:
        candidate = directory / "_bmad" / "memory" / "est"
        if candidate.is_dir():
            return candidate
    return None


def load_model(path=None):
    """The scoring model: `{memory}/architecture-model.json` when it exists, the seed otherwise.

    The seed is only ever a seed. Once copied into memory it is the company's own model — its
    weights are what the company says matters — and editing the asset to change one project
    would change every future project silently.

    It resolves memory FIRST. It used to default straight to the seed, so a company that had
    answered its own weights was scored against the shipped ones unless every caller remembered
    `--model`; a run found that the hard way. `_loaded_from` records which file won, because a
    score computed against the wrong weights is indistinguishable from one computed against the
    right ones.
    """
    if path:
        chosen = Path(path)
    else:
        memory = memory_dir()
        mine = (memory / "architecture-model.json") if memory else None
        chosen = mine if mine and mine.exists() else SEED
    model = json.loads(Path(chosen).read_text(encoding="utf-8"))
    model["_loaded_from"] = str(chosen)
    return model


def capabilities(model):
    return {k: v for k, v in model["capabilities"].items() if not k.startswith("_")}


def load_platforms(directory=None):
    """Every platform profile in the directory, keyed by id.

    Needs PyYAML. Without it this raises rather than falling back to a partial catalogue: a
    platform set scored against three of seventeen candidates is worse than no answer, because
    nothing in the output would say which fourteen were never considered.
    """
    try:
        import yaml
    except ImportError as exc:                                  # pragma: no cover - env-specific
        raise SystemExit("platform profiles need PyYAML: uv run --with pyyaml") from exc

    if directory:
        sources = [Path(directory)]
    else:
        # Shipped assets first, the company's own memory second, so memory OVERRIDES a shipped
        # profile of the same id and adds any the catalogue lacks. Either-or was the earlier
        # behaviour and it lost six hand-written profiles a run had put in memory: nothing read
        # them, and the scoring silently ran against a three-platform catalogue.
        memory = memory_dir()
        sources = [PLATFORM_DIR] + ([memory / "platforms"] if memory else [])

    out = {}
    for source in sources:
        if not Path(source).is_dir():
            continue
        for path in sorted(Path(source).glob("*.yaml")):
            profile = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(profile, dict) or not profile.get("id"):
                continue
            profile["_path"] = str(path)
            out[profile["id"]] = profile
    return out


def serves_natively(profile, capability):
    """Whether a platform offers this capability at all.

    A `serves` entry with no `service` is a deliberate recorded absence — Supabase's `cache`
    says out loud that there is no managed cache — and is not the same as the capability being
    missing from the file, which would mean nobody considered it.
    """
    entry = (profile.get("serves") or {}).get(capability)
    return bool(entry and entry.get("service"))


def story_text(feature):
    parts = [feature.get("name") or "", feature.get("description") or ""]
    for task in feature.get("tasks") or []:
        parts.append(task.get("text") or task.get("name") or "")
        for citation in task.get("citations") or []:
            parts.append(citation.get("quote") or "")
    return " ".join(parts).lower()


def _signal_hit(text, signal):
    """Substring match, but bounded at the front so `ai` does not match `said`.

    The earlier version was a plain `in` test, and on a real backlog `ai` matched `maintain`,
    `available` and `email` — which put model inference on eleven stories that had nothing to
    do with it and would have put a box on the diagram for all of them.
    """
    return re.search(r"(?<![a-z0-9])" + re.escape(signal), text) is not None


def story_hours_by_id(estimate):
    hours = {}
    for row in (estimate or {}).get("features") or []:
        value = (row.get("by_role") or {}).get("_total") or row.get("hours")
        if isinstance(value, dict):
            value = value.get("likely")
        hours[row["id"]] = float(value or 0.0)
    return hours


def apply_overrides(mapping, overrides, inventory, estimate=None):
    """The operator's corrections to the keyword map, applied on top of it.

    `overrides` is `{capability: {"set"|"add"|"remove": [story ids], "why": "..."}}`. `set`
    replaces the capability's stories outright (an empty list drops the capability); `add` and
    `remove` adjust the signal matches. Every story the operator touched is recorded as
    `how: "operator"` with their reason, and the capability is marked `confirmed`, so the check's
    signal/operator split reports how much of the map a human actually read.

    Why this exists: `build_map` rebuilds the map from keyword signals on every run, so without
    this there was no way for a human's correction to survive. On a real 89-story backlog the
    signal pass put `error_tracking` on 81 stories (every PRD feature has an "error states"
    section), `identity` on 45, and `ai_inference` on 29 — all of which had to be corrected
    before any of it could be scored.
    """
    if not overrides:
        return mapping
    features = [f for f in inventory.get("features") or []
                if f.get("origin") != "standing" and f.get("epic_id")]
    known = {f["id"] for f in features}
    total = len(features)
    hours = story_hours_by_id(estimate)
    for cap_id, rule in overrides.items():
        if cap_id.startswith("_"):
            continue
        why = rule.get("why") or "operator correction, no reason recorded"
        entry = mapping.get(cap_id) or {"stories": [], "basis": []}
        basis = {b["story"]: b for b in entry.get("basis") or []}
        if "set" in rule:
            keep = set(rule["set"])
            basis = {s: {"story": s, "how": "operator", "detail": why} for s in keep}
        for s in rule.get("remove") or []:
            basis.pop(s, None)
        for s in rule.get("add") or []:
            basis[s] = {"story": s, "how": "operator", "detail": why}
        unknown = sorted(set(basis) - known)
        if unknown:
            raise SystemExit(f"capability_overrides.{cap_id} names stories not in the inventory: "
                             f"{', '.join(unknown)}")
        stories = [f["id"] for f in features if f["id"] in basis]
        if not stories:
            mapping.pop(cap_id, None)
            continue
        mapping[cap_id] = {
            "stories": stories,
            "basis": [basis[s] for s in stories],
            "confirmed": True,
            "confirmed_why": why,
            "story_hours": round(sum(hours.get(s, 0.0) for s in stories), 1) if hours else None,
            "share_of_backlog": round(len(stories) / total, 4) if total else 0.0,
        }
    return mapping


def build_map(inventory, model, estimate=None):
    """capability id -> {stories, basis, share_of_backlog, story_hours}.

    Only priced, epic-carrying stories count: standing work is the module's own catalogue and
    is attributed through `standing_scope`, not through a keyword hit.
    """
    caps = capabilities(model)
    features = [f for f in inventory.get("features") or []
                if f.get("origin") != "standing" and f.get("epic_id")]
    total = len(features)
    hours = story_hours_by_id(estimate)

    out = {}
    for cap_id, spec in caps.items():
        hits = {}
        surface = PROJECT_CAPABILITIES.get(cap_id)
        for feature in features:
            if surface:
                if surface in (feature.get("surfaces") or []):
                    hits[feature["id"]] = {"story": feature["id"],
                                           "how": "capability_is_the_project",
                                           "detail": f"tagged surface `{surface}`"}
                continue
            text = story_text(feature)
            for signal in spec.get("signals") or []:
                if _signal_hit(text, signal):
                    hits[feature["id"]] = {"story": feature["id"], "how": "signal",
                                           "detail": f"matched `{signal}`"}
                    break
        if not hits:
            continue
        # Inventory order, never sorted: `sorted()` puts F10 before F9, and every reader of
        # this map — the sourcing table, the diagram's `serves`, the report — shows the stories
        # in the order the client's own document put them in.
        stories = [f["id"] for f in features if f["id"] in hits]
        out[cap_id] = {
            "stories": stories,
            "basis": [hits[s] for s in stories],
            "confirmed": False,
            "story_hours": round(sum(hours.get(s, 0.0) for s in stories), 1) if hours else None,
            "share_of_backlog": round(len(stories) / total, 4) if total else 0.0,
        }
    return out


def is_live(cap_id, entry, model):
    """Whether a sourcing decision is worth scoring, and the reason either way.

    A settled capability never becomes live: nobody builds a CDN, and putting one in the table
    to look thorough is the theatre the liveness test exists to prevent.
    """
    spec = capabilities(model)[cap_id]
    settled = spec.get("settled")
    if settled:
        return False, f"settled: {settled['why']}"
    rule = model["sourcing_liveness"]
    n, share = len(entry["stories"]), entry["share_of_backlog"] or 0.0
    if n < rule["min_stories"] and share < rule["min_share_of_backlog"]:
        return False, (f"not material: {n} story/stories, {share:.1%} of the backlog, under both "
                       f"the {rule['min_stories']}-story and "
                       f"{rule['min_share_of_backlog']:.0%} thresholds")
    return True, f"{n} stories, {share:.1%} of the backlog"



def revision(root=None):
    """A short hash over this installation's scripts and data files.

    A project installs the module by COPY. A real run was reviewed against the repository's
    behaviour for a day before anyone noticed it had executed a copy three weeks old — no icon
    resolver, seven platform profiles instead of twenty — so every finding about the output was a
    finding about code nobody was looking at. Stamping the revision on the artefact turns that
    into one line.

    Content, not a version number: a version number is something somebody remembers to change.
    """
    import hashlib
    base = Path(root or HERE.parent)
    digest = hashlib.sha256()
    files = sorted(path for pattern in ("scripts/*.py", "scripts/*.mjs", "assets/*.json",
                                        "assets/platforms/*.yaml", "references/*.md",
                                        "SKILL.md")
                   for path in base.glob(pattern)
                   # Resolved artwork and its manifest are fetched, not source; they change on
                   # every run and would make the revision meaningless.
                   if path.name != "icons.resolved.json")
    for path in files:
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return {"skill": base.name, "revision": digest.hexdigest()[:12], "files": len(files)}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inventory", nargs="?")
    ap.add_argument("--estimate")
    ap.add_argument("--model")
    ap.add_argument("-o", "--output")
    ap.add_argument("--revision", action="store_true",
                    help="print this installation's content revision and exit — the stamp that "
                         "lands on every architecture.json, so a project running a stale copy "
                         "can be told apart from one running the module")
    args = ap.parse_args()

    if args.revision:
        print(json.dumps(revision(), indent=2))
        return 0
    if not args.inventory:
        ap.error("give a feature-inventory.json, or --revision")

    inventory = json.loads(Path(args.inventory).read_text(encoding="utf-8"))
    estimate = (json.loads(Path(args.estimate).read_text(encoding="utf-8"))
                if args.estimate else None)
    model = load_model(args.model)
    mapping = build_map(inventory, model, estimate)
    report = {"capability_map": mapping,
              "live": {k: is_live(k, v, model)[1] for k, v in mapping.items()
                       if is_live(k, v, model)[0]}}
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
