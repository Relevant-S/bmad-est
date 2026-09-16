#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""The shapes a delivery can take, as policies over when work may start.

Each archetype is one function answering one question — given a story, when is the earliest
its first component may begin? Everything else about the simulation is identical, which is
the point: two archetypes differ in their sequencing discipline and in nothing else, so a
difference in the answer is attributable.

They are ordered by how much they overlap, which is also the order of rising risk:

  sequential   BA finishes the whole scope, then UX, then the architect, then dev. The
               longest calendar and the lowest rework, and the baseline every other option is
               scored against. Nobody builds against a spec that is still moving.
  foundation   The epics everything else reads — data model, auth, design system — complete
               first, in order. The rest pipelines behind them. The middle ground, and the
               one that usually wins, because the drift a pipeline causes is concentrated in
               the epics that are depended upon.
  pipelined    BA finishes epic 1, the whole team starts epic 1 while BA moves to epic 2.
               The shortest calendar and the most rework exposure.

The foundation cut is not a taste call: an epic is foundational when other epics depend on
it, which the inventory already records in `depends_on_epics` and in the story-level
dependencies rolled up to epic level. est-scope-extract's own ordering rule
(references/story-synthesis.md) puts repo and config, then data model and auth, then the
design system, then the capability everything reads — this reads that order off the graph
rather than restating it.
"""

import collections

COMPONENT_STAGE = {"spec": 0, "build": 1, "review": 2, "rework": 3}

NAMES = ("sequential", "foundation", "pipelined")


def epic_dependency_counts(estimate):
    """How many other epics wait on each epic, from the story graph rolled up.

    Story-level `depends_on` is where most of this lives; `depends_on_epics` adds the
    ordering no story records. Both are validated upstream by inventory-check.py, so this
    reads a graph somebody already checked rather than deducing one.
    """
    epic_of = {f["id"]: f.get("epic_id") for f in estimate.get("features", [])}
    waiters = collections.defaultdict(set)
    for feature in estimate.get("features", []):
        mine = feature.get("epic_id")
        for dep in feature.get("depends_on") or []:
            theirs = epic_of.get(dep)
            if theirs and mine and theirs != mine:
                waiters[theirs].add(mine)
    for epic in estimate.get("epics") or []:
        for row in epic.get("depends_on_epics") or []:
            target = row.get("epic_id") if isinstance(row, dict) else row
            if target and target != epic.get("id"):
                waiters[target].add(epic.get("id"))
    return {epic: len(who) for epic, who in waiters.items()}


def foundation_epics(estimate):
    """The epics the rest of the work stands on.

    An epic is foundational when at least one other epic waits on it. Where nothing depends
    on anything — a flat inventory with no recorded dependencies — the first epic in the
    stated build order is taken, because `sequence` is itself a claim about what comes first
    and ignoring it would make this archetype identical to the pipelined one.
    """
    counts = epic_dependency_counts(estimate)
    depended_on = {epic for epic, n in counts.items() if n > 0}
    if depended_on:
        return depended_on
    ordered = sorted((e for e in estimate.get("epics") or []),
                     key=lambda e: (e.get("sequence") is None, e.get("sequence") or 0))
    return {ordered[0]["id"]} if ordered else set()


def sequential(estimate, model):
    """Nothing is built until everything is specified.

    Staged by component: every story's spec is stage 0, every build stage 1, review 2, rework
    3. The barrier between stages is what makes this the archetype it claims to be — the whole
    backlog's specification closes before a line of it is built, so drift is zero by
    construction rather than by good behaviour.
    """
    def policy(feature, component):
        return COMPONENT_STAGE[component]
    return policy


def pipelined(estimate, model):
    """One stage. The only constraints are the dependency graph and who is free.

    Epic k+1 is specified while epic k is built, which is what buys the calendar back. What it
    costs is measured rather than asserted: the simulator counts every build hour booked
    before the specification it rests on had settled, and that number is this option's drift.
    """
    def policy(feature, component):
        return 0
    return policy


def foundation(estimate, model):
    """The epics everything stands on complete first; the rest pipelines behind them.

    Two stages, cut on the dependency graph rather than on taste: stage 0 is every epic that
    another epic waits on, stage 1 is everything else. Within each stage the pass is free, so
    the foundation itself is built as concurrently as its own dependencies allow — the barrier
    is between the ground and the building, not inside the ground.
    """
    base = foundation_epics(estimate)

    def policy(feature, component):
        return 0 if feature.get("epic_id") in base else 1
    return policy


POLICIES = {"sequential": sequential, "foundation": foundation, "pipelined": pipelined}

DESCRIPTIONS = {
    "sequential": ("BA specifies the entire scope, then UX, then the architect sets the "
                   "project up, then the team builds. The longest calendar and the lowest "
                   "risk — nobody builds against a moving specification."),
    "foundation": ("The epics everything else depends on are completed first and in order; "
                   "the remaining features pipeline behind them. Buys most of the calendar "
                   "a pipeline buys, and concentrates the discipline where rework is "
                   "expensive."),
    "pipelined": ("The team starts each epic as soon as that epic is specified, while the BA "
                  "moves on to the next. The shortest calendar, the highest coordination "
                  "load, and real exposure to rework and architectural drift."),
}

RISKS = {
    "sequential": [
        ("The client sees nothing running until late.",
         "Demo the foundational epic as soon as its build closes, even though the plan does "
         "not need it reviewed yet — the schedule can carry a demo it does not depend on."),
        ("A specification written months before it is built goes stale.",
         "Re-read each epic's stories at the point its build starts, and book the re-read as "
         "part of that epic rather than discovering it as rework."),
    ],
    "foundation": [
        ("The foundation is on the critical path, so slipping it slips everything.",
         "Staff the foundation epics with the people who already know the stack, and hold the "
         "added headcount back until the foundation closes — which is what this plan does."),
        ("Work that pipelines behind the foundation can still drift from it.",
         "Freeze the foundation's interfaces at its build close and treat a change to them as "
         "scope, not as a fix."),
    ],
    "pipelined": [
        ("Build starts against specifications that are still moving — the drift hours below "
         "are the measured exposure.",
         "Cap the overlap: let no epic start building until the epic it depends on has closed "
         "review, which is the foundation archetype and costs the calendar shown there."),
        ("Architectural decisions get made per epic rather than once.",
         "Book the architect's setup in full before epic 1 builds, and hold a standing "
         "decision record — the architect line in this plan already pays for the weekly "
         "presence this needs."),
        ("The coordination load is highest here and lands on the people delivering.",
         "Keep the epic teams stable: reassigning a person between epics mid-flight pays the "
         "ramp again in everything but name."),
    ],
}
