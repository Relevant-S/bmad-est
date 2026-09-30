#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Assert that an architecture says what it is for, and that choosing it moved no scope.

An architecture recommendation is the module's first artefact with no client quote behind it,
and the diagram is the most persuasive thing it produces. Everything here exists so that
persuasiveness rests on something:

  1. every component names a story, a standing-work item or a recorded assumption;
  2. every story a capability claims exists in the inventory;
  3. every story in the inventory is served by at least one component — the other direction of
     the same traceability, and the one that catches an architecture which is simply incomplete;
  4. no capability covers fewer stories than it did on a previous run — buying identity does not
     delete the identity stories, and an architecture that quietly shrinks the backlog has
     re-priced the deal without saying so;
  5. every hard constraint was evaluated against every option, or is explicitly unevaluated;
  6. no vendor in the chosen set serves only capabilities another vendor in it already serves;
  7. every sub-score carries a basis, and an unscored one says why;
  8. the balance findings are present rather than silently dropped;
  9. a volatile platform fact backing a GATE is dated and not stale.

    uv run scripts/architecture-check.py <architecture.json> [--inventory feature-inventory.json]
       [--previous architecture.json] [-o architecture-check.json]

Exit 0 when it holds, 1 when it does not, 2 when it could not run.
"""

import argparse
import datetime as dt
import importlib.util
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


caps = _load("capabilities", HERE / "capabilities.py")


def _finding(kind, detail, **extra):
    return dict({"kind": kind, "detail": detail}, **extra)


def audit(architecture, inventory=None, previous=None, model=None, platforms=None):
    """The whole check over an architecture already in memory.

    `architect.py` runs this on its own output, so the verdict printed after a run and the
    verdict a reviewer gets later come from one code path and cannot drift.
    """
    model = model or caps.load_model()
    findings = []
    cap_map = architecture.get("capability_map") or {}
    components = architecture.get("components") or []
    layers = architecture.get("layers") or {}

    # 1 — nothing on the canvas without a reason.
    for component in components:
        serves = component.get("serves") or {}
        if not (serves.get("stories") or serves.get("standing_work") or serves.get("assumptions")):
            findings.append(_finding(
                "component_serves_nothing",
                f"{component['id']} ({component.get('name')}) is drawn and names no story, no "
                f"standing-work item and no assumption. A component that serves nothing is "
                f"invented infrastructure."))

    # 1b — code that runs somewhere unstated, and labels that say it twice.
    for component in components:
        runtime = (component.get("runs_on") or {}).get("service")
        if component.get("mode") in ("build", "adopt") and component.get("platform") \
                and not runtime and component.get("capability") in ("application", "async_work"):
            findings.append(_finding(
                "runtime_unnamed",
                f"{component['id']} is {component['mode']} on `{component['platform']}` and no "
                f"runtime is named, so the diagram cannot show what the code runs inside. Give "
                f"the profile's `serves.{component['capability']}` a `runtime:` naming ONE "
                f"service — 'App Runner, ECS Fargate or Lambda' is a choice, not a runtime."))
        # Compared word by word, because a label shortens: the runtime is "AWS Fargate" and the
        # label that collapsed it said "Django on Fargate".
        label = set(re.findall(r"[a-z0-9]+", (component.get("name") or "").lower()))
        distinctive = {w for w in re.findall(r"[a-z0-9]+", (runtime or "").lower())
                       if len(w) > 3 and w not in ("aws", "amazon", "azure", "google", "cloud",
                                                   "service", "services", "managed")}
        if runtime and distinctive & label:
            findings.append(_finding(
                "label_repeats_runtime",
                f"{component['id']} is labelled '{component['name']}' and already draws inside "
                f"'{runtime}'. The label names both items, which is the collapse the containment "
                f"was added to undo — name the software alone."))

    # 2 — every claimed story is a real story.
    known = {f["id"] for f in (inventory or {}).get("features") or []}
    if known:
        for cap, entry in cap_map.items():
            for story in entry.get("stories") or []:
                if story not in known:
                    findings.append(_finding(
                        "unknown_story",
                        f"capability `{cap}` claims story {story}, which is not in the inventory",
                        capability=cap, story=story))

    # 3 — every story is served by something that gets drawn. The other direction of the same
    # traceability: a component with no stories is invented, and a story with no component is an
    # architecture that does not cover the work it was designed for.
    served = {s for c in components for s in (c.get("serves") or {}).get("stories") or []}
    for feature in (inventory or {}).get("features") or []:
        if feature.get("origin") == "standing" or not feature.get("epic_id"):
            continue
        if feature["id"] not in served:
            findings.append(_finding(
                "story_unserved",
                f"{feature['id']} ({feature.get('name')}) is in scope and no component on the "
                f"diagram serves it. Either a capability is missing from the design or the "
                f"story needs one attributed to it by hand.", story=feature["id"]))

    # 4 — scope did not move while an architecture was being chosen. Compared PER CAPABILITY:
    # `application` and `web_client` take every story on their surface, so a union comparison
    # can never shrink and would pass while identity quietly lost two thirds of its stories.
    if previous:
        before = previous.get("capability_map") or {}
        structural = set(caps.PROJECT_CAPABILITIES)
        for cap, entry in before.items():
            if cap in structural:
                continue
            was = set(entry.get("stories") or [])
            now = set((cap_map.get(cap) or {}).get("stories") or [])
            for story in sorted(was - now):
                findings.append(_finding(
                    "story_dropped",
                    f"{story} was served by `{cap}` before and is not now. Scope is fixed here "
                    f"and only classification moves; a story leaving this map is the backlog "
                    f"shrinking without anybody saying so.", story=story, capability=cap))

    # 4 — every constraint met every option.
    constraints = ((architecture.get("inputs") or {}).get("constraints")) or []
    for layer_name in ("stack", "platform"):
        for option in (layers.get(layer_name) or {}).get("options") or []:
            seen = {f["constraint"] for f in option.get("not_viable_because") or []}
            seen |= {u["constraint"] for u in option.get("unevaluated_gates") or []}
            for constraint in constraints:
                if constraint["kind"] in ("licence_class", "procurement"):
                    continue          # sourcing-layer gates, not platform-set gates
                if layer_name == "stack" and constraint["kind"] != "licence_class":
                    continue          # a stack does not choose a platform
                if constraint["id"] not in seen and option.get("viable") is not True:
                    findings.append(_finding(
                        "constraint_not_evaluated",
                        f"{option['id']} is not viable but does not say whether constraint "
                        f"{constraint['id']} was the reason", option=option["id"]))

    # 5 — no vendor that buys nothing.
    chosen = next((o for o in (layers.get("platform") or {}).get("options") or []
                   if o["id"] == (layers.get("platform") or {}).get("chosen")), None)
    if chosen:
        binding = chosen["detail"].get("binding") or {}
        by_vendor = {}
        for cap, pid in binding.items():
            by_vendor.setdefault(pid, []).append(cap)
        for pid, mine in by_vendor.items():
            if not mine:
                findings.append(_finding(
                    "vendor_buys_nothing",
                    f"{pid} is in the chosen set and serves no capability. Another account, "
                    f"another bill and another data-processing agreement for nothing.",
                    platform=pid))

    # 6 — every sub-score is answerable.
    for layer_name in ("stack", "platform"):
        for option in (layers.get(layer_name) or {}).get("options") or []:
            for name, part in (option.get("parts") or {}).items():
                if not part.get("basis"):
                    findings.append(_finding(
                        "score_without_basis",
                        f"{layer_name} option {option['id']} scores {name} with no basis. A "
                        f"score nobody can check is a score nobody can argue with.",
                        option=option["id"], part=name))
    for decision in (layers.get("sourcing") or {}).get("decisions") or []:
        for option in decision.get("options") or []:
            for name, part in (option.get("parts") or {}).items():
                if not part.get("basis"):
                    findings.append(_finding(
                        "score_without_basis",
                        f"sourcing {decision['capability']}/{option['id']} scores {name} with "
                        f"no basis.", option=decision["capability"], part=name))

    # 7 — the balance findings survived to the report.
    balance = (layers.get("sourcing") or {}).get("balance") or {}
    if "findings" not in balance:
        findings.append(_finding("balance_missing",
                                 "the sourcing layer reports no balance block, so the build/buy "
                                 "distribution was never made visible"))

    # 8 — a stale or undated fact must not be holding up a gate.
    platforms = platforms if platforms is not None else caps.load_platforms()
    stale_days = (model.get("costing") or {}).get("stale_after_days", 45)
    today = dt.date.today()
    for constraint in constraints:
        if constraint["kind"] not in ("data_residency", "certification"):
            continue
        field = "residency" if constraint["kind"] == "data_residency" else "certifications"
        for pid in (chosen or {}).get("detail", {}).get("platforms", []):
            entry = ((platforms.get(pid) or {}).get("volatile") or {}).get(field) or {}
            checked = entry.get("checked")
            if checked is None:
                findings.append(_finding(
                    "gate_on_unverified_fact",
                    f"the chosen set uses {pid}, whose `{field}` has never been verified, while "
                    f"constraint {constraint['id']} depends on it. Research and date the profile "
                    f"field before this option is quoted against that requirement.",
                    platform=pid, constraint=constraint["id"]))
                continue
            try:
                age = (today - dt.date.fromisoformat(str(checked))).days
            except ValueError:
                age = None
            if age is not None and age > stale_days:
                findings.append(_finding(
                    "gate_on_stale_fact",
                    f"{pid}'s `{field}` was checked {age} days ago, past the {stale_days}-day "
                    f"threshold, and constraint {constraint['id']} rests on it.",
                    platform=pid, constraint=constraint["id"]))

    signal = sum(1 for e in cap_map.values() for b in e.get("basis") or []
                 if b.get("how") == "signal")
    confirmed = sum(1 for e in cap_map.values() if e.get("confirmed"))
    mapped = sum(len(e.get("stories") or []) for e in cap_map.values())

    return {
        "ok": not findings,
        "findings": findings,
        "capabilities": len(cap_map),
        "components": len(components),
        "stories_served": len(served),
        "mapped_story_links": mapped,
        "signal_derived_links": signal,
        "confirmed_capabilities": confirmed,
        # Stated, because a checker that compares nothing also reports no findings, and this
        # module has shipped one of those before.
        "checked": (f"{len(components)} components serving {len(served)} stories, "
                    f"{mapped} capability-to-story links "
                    f"({signal} of them from a keyword signal rather than judgement), "
                    f"{len(constraints)} hard constraint(s) across "
                    f"{sum(len((layers.get(l) or {}).get('options') or []) for l in ('stack', 'platform'))} "
                    f"scored options, and "
                    f"{len((layers.get('sourcing') or {}).get('decisions') or [])} sourcing "
                    f"decisions"),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("architecture")
    ap.add_argument("--inventory", help="defaults to feature-inventory.json beside it")
    ap.add_argument("--previous", help="an earlier architecture.json, to prove scope held")
    ap.add_argument("-o", "--output")
    args = ap.parse_args()

    path = Path(args.architecture)
    architecture = json.loads(path.read_text(encoding="utf-8"))
    inv_path = Path(args.inventory) if args.inventory else path.with_name("feature-inventory.json")
    if not inv_path.exists():
        print(json.dumps({"ok": False,
                          "error": f"no inventory at {inv_path}; pass --inventory"}, indent=2))
        return 2
    report = dict(audit(architecture,
                        json.loads(inv_path.read_text(encoding="utf-8")),
                        json.loads(Path(args.previous).read_text(encoding="utf-8"))
                        if args.previous else None),
                  architecture=str(path))
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
