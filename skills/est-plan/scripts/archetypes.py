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


def epic_predecessors(estimate):
    """The epic ordering graph: `{epic: {predecessor: why}}`, and the cycles it had to break.

    Returns `(predecessors, broken)`.

    A cross-epic story dependency is a claim about the two EPICS, not only about the two
    stories. Treating it as story-local is what let the plan build epic 23 before epic 3: on a
    real backlog only a fraction of an epic's stories carry a cross-epic edge — Kitespire's
    Authentication epic had one in eight, and Foundation had none in seven — so the rest float
    free and go to whichever developer is idle. Every declared story edge was honoured and the
    build order was still nonsense, with 95 of 253 epic pairs running against the stated
    sequence.

    So the edges are rolled up: if any story in E09 depends on any story in E06, E06 comes
    before E09 for all of E09. `depends_on_epics` adds the orderings no story records, and
    those were being read in exactly one place — `foundation_epics()` — and never scheduled
    against, so all three of Kitespire's declared orderings were violated in the shipped plan.

    `why` is kept per edge because the plan has to answer where a piece of work belongs and on
    what grounds. For a declared edge it is the inventory's own sentence; for a rolled-up one
    it names the story pair that caused it.
    """
    epic_of = {f["id"]: f.get("epic_id") for f in estimate.get("features", [])
               if f.get("origin") != "standing"}
    pred = collections.defaultdict(dict)
    weight = collections.Counter()
    for feature in estimate.get("features", []):
        if feature.get("origin") == "standing":
            continue
        mine = feature.get("epic_id")
        for dep in feature.get("depends_on") or []:
            theirs = epic_of.get(dep)
            if theirs and mine and theirs != mine:
                weight[(mine, theirs)] += 1
                pred[mine].setdefault(theirs, f"{feature['id']} depends on {dep}")
    for epic in estimate.get("epics") or []:
        for row in epic.get("depends_on_epics") or []:
            target = row.get("epic_id") if isinstance(row, dict) else row
            if target and target != epic.get("id"):
                # A declared edge outranks an inferred one, so it overwrites rather than
                # setdefault, and it carries the sentence somebody wrote for it.
                pred[epic["id"]][target] = (row.get("why") if isinstance(row, dict) else None) \
                    or f"{epic['id']} is recorded as depending on {target}"
                weight[(epic["id"], target)] += 1000
    return _break_cycles(pred, weight, estimate)


def _break_cycles(pred, weight, estimate):
    """Rolling story edges up can make an epic cycle out of an acyclic story graph.

    Two epics that each hold one story depending on the other are perfectly schedulable at the
    story level and a deadlock at the epic level. The scheduler must not hang on that, and it
    must not silently pick a winner either: the weaker edge is dropped — fewest underlying
    story edges, ties to the one whose dependant has the earlier `sequence`, since that is the
    direction the inventory already claims — and every drop is returned so the plan can report
    it the way `inventory-check.find_cycles` reports rather than repairs.
    """
    seq = {e.get("id"): e.get("sequence") or 0 for e in estimate.get("epics") or []}
    broken = []
    while True:
        cycle = _find_cycle(pred)
        if not cycle:
            return {k: dict(v) for k, v in pred.items() if v}, broken
        edges = [(cycle[i + 1], cycle[i]) for i in range(len(cycle) - 1)]  # (dependant, pred)
        loser = min(edges, key=lambda e: (weight[e], seq.get(e[0], 0)))
        broken.append({"epic": loser[0], "waits_on": loser[1],
                       "why": pred[loser[0]].get(loser[1]),
                       "dropped": "these two epics each hold a story depending on the other, "
                                  "so rolled up to the epic they deadlock. The edge resting on "
                                  "fewer stories was dropped; the story dependencies themselves "
                                  "are still scheduled."})
        del pred[loser[0]][loser[1]]


def _find_cycle(pred):
    """One cycle as a list of epic ids, predecessor-first, or None. Iterative — an epic graph
    is small but a recursive walk over a pathological one would blow the stack."""
    colour = {}
    for start in list(pred):
        if colour.get(start):
            continue
        stack = [(start, iter(list(pred.get(start, ()))))]
        colour[start], path = 1, [start]
        while stack:
            node, nxt = stack[-1]
            for child in nxt:
                if colour.get(child) == 1:
                    return path[path.index(child):] + [child]
                if not colour.get(child):
                    colour[child] = 1
                    path.append(child)
                    stack.append((child, iter(list(pred.get(child, ())))))
                    break
            else:
                colour[node] = 2
                stack.pop()
                path.pop()
    return None


def epic_dependency_counts(estimate):
    """How many other epics wait on each epic — the predecessor graph, inverted.

    Inverted rather than walked a second time, so `foundation_epics()` and the scheduler
    cannot end up disagreeing about what the graph is.
    """
    pred, _ = epic_predecessors(estimate)
    waiters = collections.defaultdict(set)
    for epic, befores in pred.items():
        for before in befores:
            waiters[before].add(epic)
    return {epic: len(who) for epic, who in waiters.items()}


def epic_phase(estimate):
    """`{epic_id: phase}`, read off the priced stories est-estimate already stamped.

    est-estimate resolves the phase once — stated by the inventory where the source gave one,
    derived from `commitment` where it did not — and stamps it on every priced row. Read rather
    than re-derived, so the scheduler, the renderer and the checker cannot disagree about which
    phase a piece of work is in.
    """
    out = {}
    for feature in estimate.get("features", []):
        if feature.get("epic_id"):
            out[feature["epic_id"]] = feature.get("phase") or 1
    return out


def foundation_epics(estimate):
    """The epics the rest of the work stands on, WITHIN THE FIRST DELIVERY PHASE.

    An epic is foundational when at least one other epic waits on it. Where nothing depends
    on anything — a flat inventory with no recorded dependencies — the first epic in the
    stated build order is taken, because `sequence` is itself a claim about what comes first
    and ignoring it would make this archetype identical to the pipelined one.

    Restricted to the earliest phase, and not for tidiness. The foundation set is "everything
    something else waits on", and on a real backlog that reaches across the phase boundary:
    Kitespire's E21 and E22 are both Phase 2 and both depended upon, so an unrestricted set put
    Phase 2 epics in stage 0 while Phase 1 sat in stage 1. The phase gate cannot be satisfied
    inside that staging — a Phase 2 build waits for Phase 1 to finish, and Phase 1 has not
    started — so the run either deadlocks or fills `unresolved_dependencies` with contradictions
    the inventory never contained. A foundation is the ground the CURRENT phase stands on.
    """
    counts = epic_dependency_counts(estimate)
    phase = epic_phase(estimate)
    first = min(phase.values(), default=1)
    depended_on = {epic for epic, n in counts.items()
                   if n > 0 and phase.get(epic, first) == first}
    if depended_on:
        return depended_on
    ordered = sorted((e for e in estimate.get("epics") or []
                      if phase.get(e.get("id"), first) == first),
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
         "Staff the foundation epics with the people who already know the stack. The plan "
         "already holds added headcount back until their role has more ready work than the "
         "people on it can clear — see each option's arrival table — but that is a measure of "
         "demand, not of risk, and the foundation is where a late arrival costs most."),
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
