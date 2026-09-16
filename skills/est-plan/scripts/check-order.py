#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Assert that a plan's calendar respects the ordering the inventory records.

A schedule can honour every story-level dependency and still be unrunnable. A real Kitespire
plan did: 190 story edges, zero violated, and `Phase 2 AI — Module 2` still built in week 5.3
against a prerequisites epic that finished in week 9.3, with 94 of 253 epic pairs running
against the stated build order. The reason is that a cross-epic dependency binds the one story
that declares it and no other, and on that backlog only one of Authentication's eight stories
carried one.

So this checks the four claims a reader of the Gantt is entitled to make:

  1. no story is built before a story it depends on has been built;
  2. no epic is built before the epics it stands on have been built;
  3. no epic is specified before the epics it stands on have been specified;
  4. nothing is built before it has been specified.

Ordering is read from the same `archetypes.epic_predecessors` the scheduler uses, so this
cannot pass by measuring a different graph from the one that was scheduled. It reads the
emitted `plan.json` rather than re-simulating, so it is a check on the artefact that ships.

    uv run scripts/check-order.py <plan.json> [--estimate estimate.json] [-o check-order.json]

Exit 0 when every option holds, 1 when any does not.
"""

import argparse
import collections
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOLERANCE = 1e-6          # a thousandth of a working minute; rounding, not overlap


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


archetypes = _load("archetypes", HERE / "archetypes.py")


def windows(option, epic_of):
    """(start, finish) per story and per epic, per component, from the schedule as emitted."""
    story = collections.defaultdict(lambda: [1e9, 0.0])
    epic = collections.defaultdict(lambda: [1e9, 0.0])
    for person in option["schedule"]["team"]:
        for item in person["items"]:
            sid, component = item.get("story_id"), item.get("component")
            if not sid or sid not in epic_of or component not in ("spec", "build"):
                continue            # standing work and the calendar-priced components
            for table, key in ((story, (sid, component)), (epic, (epic_of[sid], component))):
                table[key][0] = min(table[key][0], item["start_week"])
                table[key][1] = max(table[key][1], item["finish_week"])
    return story, epic


def check_option(option, estimate, predecessors, epic_of):
    story, epic = windows(option, epic_of)
    findings = []

    def late(what, gate):
        return what[0] + TOLERANCE < gate[1]

    for feature in estimate.get("features", []):
        fid = feature["id"]
        if (fid, "build") not in story:
            continue
        for dep in feature.get("depends_on") or []:
            if (dep, "build") in story and late(story[(fid, "build")], story[(dep, "build")]):
                findings.append({
                    "kind": "story_dependency", "story": fid, "waits_on": dep,
                    "detail": f"{fid} builds at week {story[(fid, 'build')][0]:.2f} but {dep}, "
                              f"which it depends on, is not built until week "
                              f"{story[(dep, 'build')][1]:.2f}"})
        if (fid, "spec") in story and late(story[(fid, "build")], story[(fid, "spec")]):
            findings.append({
                "kind": "build_before_spec", "story": fid, "waits_on": fid,
                "detail": f"{fid} builds at week {story[(fid, 'build')][0]:.2f} against a "
                          f"specification that closes at week {story[(fid, 'spec')][1]:.2f}"})

    name = {e.get("id"): e.get("name") for e in estimate.get("epics") or []}
    for dependant, befores in sorted(predecessors.items()):
        for before, why in sorted(befores.items()):
            for component, label in (("build", "built"), ("spec", "specified")):
                here, there = (dependant, component), (before, component)
                if here in epic and there in epic and late(epic[here], epic[there]):
                    findings.append({
                        "kind": f"epic_{component}_order", "epic": dependant,
                        "waits_on": before, "why": why,
                        "detail": f"{dependant} ({name.get(dependant)}) is {label} from week "
                                  f"{epic[here][0]:.2f}, but {before} ({name.get(before)}), "
                                  f"which it stands on, is not {label} until week "
                                  f"{epic[there][1]:.2f} — {why}"})
    return findings


def audit(plan, estimate):
    """The whole check over a plan already in memory. `plan.py` runs this on its own output.

    Same code path as the command line, so the figure printed after a run and the figure a
    reviewer gets later cannot drift apart.
    """
    predecessors, broken = archetypes.epic_predecessors(estimate)
    epic_of = {f["id"]: f.get("epic_id") for f in estimate.get("features", [])
               if f.get("origin") != "standing" and f.get("epic_id")}

    options = list(plan.get("options") or [])
    baseline = plan.get("baseline")
    if baseline and not any(o["id"] == baseline["id"] for o in options):
        options.append(baseline)

    findings = []
    by_option = []
    for option in options:
        mine = check_option(option, estimate, predecessors, epic_of)
        by_option.append({"id": option["id"], "findings": len(mine)})
        findings += [dict(f, option=option["id"]) for f in mine]
    edges = sum(len(v) for v in predecessors.values())
    return {
        "ok": not findings,
        "epics_ordered": len(predecessors), "edges": edges,
        "cycles_broken": broken,
        "by_option": by_option, "findings": findings,
        # Stated, because a checker that compares nothing also reports no findings, and this
        # module has shipped one of those before.
        "checked": (f"{edges} epic edges and every story dependency across "
                    f"{len(options)} options"),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan", help="path to plan.json")
    ap.add_argument("--estimate", help="the estimate it was planned from; defaults to "
                                       "estimate.json beside the plan")
    ap.add_argument("-o", "--output", help="write the report here as well as to stdout")
    args = ap.parse_args()

    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    path = Path(args.estimate) if args.estimate else Path(args.plan).with_name("estimate.json")
    if not path.exists():
        print(json.dumps({"ok": False, "error": f"no estimate at {path}; pass --estimate"},
                         indent=2))
        return 2
    estimate = json.loads(path.read_text(encoding="utf-8"))

    report = dict(audit(plan, estimate), plan=str(args.plan))
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
