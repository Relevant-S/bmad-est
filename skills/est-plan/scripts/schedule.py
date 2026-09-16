#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Turn a priced estimate into a schedule somebody could actually run.

A resource-constrained forward pass over the dependency graph. Every unit of work has an
owner and a start time, and a start time is only ever `max(predecessors finished, owner
free)` — which is what makes the output deliverable rather than arithmetic. Nobody is ever
scheduled onto blocked work here, because blocked work has no start time to be assigned to.

The ordering of roles inside a story is NOT invented. `component_shares` and `role_weights`
in the cost model already say that a story's spec is BA, UX and dev; its build is dev, UX and
devops; its review and rework are dev and devops. Spec before build before review before
rework is that statement read as a schedule. Inventing a second opinion about who blocks whom
would have put two orderings in the module that could disagree.

Time is measured in WEEKS from zero, never in dates. The module's standing rule is that
duration must not harden into a date, and a plan that says "week 3" keeps that rule while a
plan that says "20 October" quietly breaks it.
"""

import collections
import importlib.util
from pathlib import Path

# The epic ordering graph lives in archetypes.py, beside the other epic-level reading of the
# dependency data, and is loaded rather than duplicated so the scheduler and the archetypes
# cannot disagree about what the graph is. archetypes imports nothing from here, so there is
# no cycle; this is the same by-path load render-plan.py uses for brand.py.
_SPEC = importlib.util.spec_from_file_location(
    "est_archetypes", Path(__file__).resolve().parent / "archetypes.py")
archetypes = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(archetypes)

COMPONENTS = ("spec", "build", "review", "rework")

# The roles that carry each component, in the cost model's own terms. Read from role_weights
# at run time rather than duplicated here — this tuple is only the ORDER, which is the one
# thing role_weights does not state.
COMPONENT_ORDER = {name: i for i, name in enumerate(COMPONENTS)}

# The share of QA held back for a regression pass over the whole scope, after the last build.
# A per-epic sweep alone asserts that every defect is found inside the epic that caused it,
# which is the assumption integration testing exists because nobody believes. Asserted, not
# measured: no anchor recorded when its QA hours were spent.
REGRESSION_SHARE = 0.25


class Assignee:
    """One person: a role, a name, and the weeks they are already committed to.

    `ready` is when they can next pick something up. `ramp` is charged once, before their
    first delivery, because a person who joins on Monday is not delivering on Monday — and a
    plan that assumes otherwise is the specific kind of optimism this module exists to refuse.
    """

    def __init__(self, role, name, hours_per_week, ramp_hours=0.0, on_project=False):
        self.role = role
        self.name = name
        self.rate = hours_per_week
        self.ramp = 0.0 if on_project else ramp_hours
        self.on_project = on_project
        self.ready = 0.0
        self.busy = 0.0          # delivered hours, ramp excluded
        self.ramp_charged = False
        self.ramp_until = 0.0    # the week they become able to deliver at all
        self.blocked = 0.0       # weeks spent free but unable to start: waiting on somebody
        # The week this person arrives on the project. Zero for the first person in a role and
        # for anyone already on the roster; measured for everyone else — see `join_weeks()`.
        self.join_week = 0.0
        self.items = []

    def reset(self, rate):
        """Put this person back at week zero at a new rate, for the second pass.

        `join_week` deliberately survives: it is what the second pass is FOR. Pass one measures
        the demand with everybody available from week zero, pass two schedules against the
        arrival dates that measurement produced.
        """
        self.rate = rate
        self.ready = 0.0
        self.busy = 0.0
        self.ramp_charged = False
        self.ramp_until = 0.0
        self.blocked = 0.0
        self.items = []

    def take(self, hours, earliest, label, story_id=None, epic_id=None, component=None):
        """Book `hours` of this person's time, not starting before `earliest`."""
        # Time this person was free and could not start. It is the honest measure of whether
        # the backlog really splits: two developers whose work interleaves cleanly wait for
        # nobody, and two working the same seam spend the plan watching each other.
        # Measured from when this person could next have started, which is the later of being
        # free and having arrived. Counting the weeks before someone joined as time they spent
        # blocked would be nonsense, and it would be consequential nonsense: staffing.judge()
        # refuses headcount on marginal blocked time, so a late joiner would be refused for the
        # weeks they were not yet here.
        available = max(self.ready, self.join_week)
        self.blocked += max(0.0, earliest - available)
        start = max(available, earliest)
        if not self.ramp_charged and self.ramp:
            # The ramp is real occupancy: it fills the person's calendar and delays their
            # first delivery. Charging it as a lump of hours somewhere else would let a plan
            # add a body in the final week and book their full output.
            start += self.ramp / self.rate
            self.ramp_charged = True
            self.ramp_until = start
        finish = start + (hours / self.rate if self.rate else 0.0)
        self.ready = finish
        self.busy += hours
        self.items.append({"label": label, "story_id": story_id, "epic_id": epic_id,
                           "component": component, "hours": round(hours, 2),
                           # When the work itself became startable, as opposed to when this
                           # person got to it. `join_weeks()` reads this to build the demand
                           # profile, and it is the only honest source for it: `start_week`
                           # already has the team's own availability baked in.
                           "ready_week": round(earliest, 3),
                           "start_week": round(start, 3), "finish_week": round(finish, 3)})
        return start, finish


def story_role_hours(feature, model):
    """Per (component, role) hours for one priced story, from what estimate.json already holds.

    `features[].component_hours` is the mean split of the story, and `by_role` is the same
    story split by role. The product of the two shares reconstructs the cell without needing
    the cost model's renormalisation logic a second time — and it reconciles, which the tests
    assert rather than assume.
    """
    comp = feature.get("component_hours") or {}
    roles = feature.get("by_role") or {}
    total = sum(comp.values())
    out = {}
    for component, hours in comp.items():
        if hours <= 0:
            continue
        share = hours / total if total else 0.0
        for role, row in roles.items():
            portion = row.get("hours", 0.0) * share
            if portion > 0.005:
                out[(component, role)] = portion
    return out


def plan_prefix(estimate, people, model, rate):
    """Planning: the serial prefix that has to exist before there is anything to build.

    Capped at two people, which is not a choice made here — `duration()` in estimate.py has
    always treated planning that way, on the grounds that writing a brief and a PRD does not
    parallelise across a big team. Reusing the rule keeps one answer in the module.
    """
    hours = sum(estimate["project_components"][k]["hours"]
                for k in ("planning_agent", "planning_review")
                if k in estimate["project_components"])
    roles = collections.OrderedDict()
    for key in ("planning_agent", "planning_review"):
        if key not in estimate["project_components"]:
            continue
        for role, row in (estimate["project_components"][key].get("by_role") or {}).items():
            roles[role] = roles.get(role, 0.0) + row.get("hours", 0.0)
    if not roles:
        return 0.0, []
    # Two people at most, so the prefix is the hours over min(available in those roles, 2).
    seats = min(2, max(1, sum(1 for r in roles if any(p.role == r for p in people))))
    return hours / (rate * seats) if rate else 0.0, list(roles)


def join_weeks(team, first_pass, rate, ramp):
    """When each person arrives, measured from the demand their role actually faces.

    The plan used to start everybody on the same Monday. A real run put four developers who had
    never seen the codebase at `ramp_until` 2.587, 2.590, 2.592 and 2.597 — inside a hundredth
    of a week of each other — ramping in parallel against a repository that did not exist yet.
    Nothing prevented it: ramp was paid out of the newcomer's own capacity and every clock was
    lifted to the same planning barrier, so headcount was a flat line from week one in all three
    archetypes. Two places in the module already promised otherwise and were simply wrong:
    `archetypes.RISKS["foundation"]` offered "hold the added headcount back until the foundation
    closes — which is what this plan does", and `mean_concurrent_headcount` justified itself on
    a stagger that never happened.

    The rule, in one sentence: a person joins when there is more work ready in their role than
    the people already there can clear, by at least enough to repay what the newcomer costs to
    arrive.

      backlog(t) = ready_hours(t) - SUM over those already here of max(0, t - join_k) * rate

    and person k joins at the first arrival week w where `backlog(w + d) >= ramp`, with
    `d = ramp / rate`: the week they would actually become productive, not the week somebody
    decided to hire them. Asking at w itself instead put everybody in week one again — at week
    zero nobody present has cleared anything yet, so the backlog is the whole of the first
    chunk of work and any newcomer looks justified. The question worth asking is whether the
    work is still there once the newcomer can do it.

    `ready_hours(t)` comes from the first simulation pass — every newcomer available from week
    zero, which is precisely the UNCONSTRAINED demand profile — read off each item's
    `ready_week`, when the work became startable rather than when somebody got to it.

    No new coefficient. `ramp_hours` is the existing one, and its own `why` already calls it
    "the yardstick the marginal gate uses"; this applies the same yardstick to arrival as
    staffing.judge() applies to headcount. Person one of every role, and anybody on the supplied
    roster, joins at zero — they are already here.

    `backlog` only falls between arrivals, so it is enough to evaluate it at each arrival. Where
    the threshold is never met the person is not demanded at any point: they join at the tightest
    moment the role ever has, which is the most useful week they could possibly arrive, and the
    sweep's marginal gate is left to decide whether they were worth adding at all.
    """
    joins = {}
    by_role = collections.OrderedDict()
    for person in team:
        by_role.setdefault(person.role, []).append(person)
    booked = {}
    for row in first_pass["team"]:
        booked.setdefault(row["role"], []).extend(row["items"])

    for role, people in by_role.items():
        arrivals = sorted((it.get("ready_week", 0.0), it["hours"])
                          for it in booked.get(role, []))
        here = []
        for n, person in enumerate(people):
            if n == 0 or person.on_project or not arrivals:
                here.append(0.0)
                continue
            delay = ramp / rate if rate else 0.0
            best, best_at = None, None
            for week, _ in arrivals:
                productive = week + delay
                waiting = sum(h for w, h in arrivals if w <= productive)
                served = sum(max(0.0, productive - j) for j in here) * rate
                backlog = waiting - served
                if backlog >= ramp:
                    best_at = week
                    break
                if best is None or backlog > best:
                    best, best_at = backlog, week
            here.append(max(here[-1], best_at or 0.0))
        joins[role] = here
    return joins


def simulate(estimate, model, team, policy, staffing=None, concurrency=None):
    """The forward pass. Returns the schedule and everything a plan needs to be judged.

    `team` is a list of Assignee. `policy` is the archetype: it answers, for one unit of work,
    which STAGE it belongs to. Stages run strictly in order — everything in stage 0 finishes
    before anything in stage 1 starts — and inside a stage the pass is free, constrained only
    by the dependency graph and by who is available.

    That single idea expresses every archetype without a branch in here. Sequential stages by
    component, so the whole backlog is specified before anything is built. Foundation stages by
    epic, so the ground is laid before the rest overlaps. Pipelined has one stage and is
    constrained by dependencies alone.
    """
    rate = model["calendar"]["hours_per_person_week"]
    cfg = staffing or model.get("staffing") or {}
    drag = float((cfg.get("coordination_drag") or {}).get("likely") or 0.0)

    # Coordination drag is realised as reduced throughput per person, so it is applied to the
    # rate rather than added as a lump of hours. A team of n loses drag x (n-1) each, which is
    # how a bigger team can finish later: every extra pair of hands slows every other pair.
    #
    # `n` is the people actually WORKING AT ONCE, not the roster. Charging it to the roster
    # billed a five-role team 14% each on a plan where four of those roles sat under 20%
    # utilisation — a DevOps engineer with 39 h of work across forty weeks was being counted as
    # a full coordination partner for everybody. And concurrency is an output of the schedule,
    # not an input, so it takes two passes: measure it at the nominal rate, then charge against
    # what was measured. The second pass is the one that is returned.
    if concurrency is None:
        first = simulate(estimate, model, team, policy, staffing, concurrency=len(team) or 1)
        concurrency = max(1.0, mean_concurrent_headcount(first))
        # Arrival dates are the other thing the first pass is for. Measured before the reset,
        # because `reset()` clears the items they are read from — and kept through it, because
        # they are the input the second pass exists to schedule against.
        ramp = float(((model.get("staffing") or {}).get("ramp_hours") or {}).get("likely") or 0.0)
        arrivals = join_weeks(team, first, rate, ramp)
        seen = collections.defaultdict(int)
        for person in team:
            weeks = arrivals.get(person.role) or [0.0]
            person.join_week = weeks[min(seen[person.role], len(weeks) - 1)]
            seen[person.role] += 1
        for person in team:
            person.reset(rate)

    effective = rate * max(0.25, 1.0 - drag * max(0.0, concurrency - 1))
    for person in team:
        person.rate = effective

    features = [f for f in estimate.get("features", []) if f.get("origin") != "standing"]
    setup = [f for f in estimate.get("features", []) if f.get("origin") == "standing"]
    epic_seq = {e.get("id"): e.get("sequence") or 0 for e in estimate.get("epics") or []}
    order = sorted(features, key=lambda f: (epic_seq.get(f.get("epic_id"), 0), str(f["id"])))
    known = {f["id"] for f in features}

    prefix_weeks, prefix_roles = plan_prefix(estimate, team, model, effective)
    # Planning is BOOKED, not merely waited out. Modelling it as a delay left 46 h of priced
    # BA and UX time on nobody's calendar — the Gantt accounted for 68% of the hours the deal
    # was being sold on, and a reader adding up the chart got a different number from the one
    # on the estimate. It is still a serial prefix: nothing else starts until it closes.
    for key in ("planning_agent", "planning_review"):
        component = (estimate.get("project_components") or {}).get(key) or {}
        for role, row in sorted((component.get("by_role") or {}).items()):
            person = _pick(team, role)
            if person is not None and (row.get("hours") or 0.0) > 0:
                person.take(row["hours"], 0.0, key.replace("_", " "), None, None, "planning")
    for person in team:
        if person.role in prefix_roles:
            person.ready = max(person.ready, prefix_weeks)
    # The planning prefix gates ALL story work, not only the roles performing it. Lifting
    # `ready` for BA and UX alone left dev — which carries `spec` at w=0.28 — starting at week
    # zero: a real plan had the developer writing story specifications in week 0.6 and the BA
    # arriving in week 2.9. Until there is a brief and a PRD there is nothing to specify
    # against, and what dev can legitimately do first is project setup, which is standing work.
    # Standing work — the repository, the pipeline, the environments, the release process —
    # goes FIRST and is not gated by the planning prefix. It is what a developer can honestly
    # do while the analyst is still writing, and it is the answer to "dev has nothing to do
    # until BA finishes". It was previously filtered out of the schedule entirely: priced,
    # billed, and assigned to nobody on any calendar.
    for feature in sorted(setup, key=lambda f: -(f.get("hours") or 0.0)):
        for (component, role), hours in sorted(story_role_hours(feature, model).items()):
            person = _pick(team, role)
            if person is not None:
                person.take(hours, 0.0, feature.get("name") or feature["id"],
                            feature["id"], None, component)
    barrier = max(prefix_weeks, 0.0)
    qa = QaPasses(estimate, team, features)

    items = []
    for n, feature in enumerate(order):
        cells = story_role_hours(feature, model)
        for component in COMPONENTS:
            owners = [(role, hours) for (comp, role), hours in cells.items() if comp == component]
            if owners:
                items.append({"stage": policy(feature, component), "order": n,
                              "feature": feature, "component": component,
                              "owners": sorted(owners)})

    # The epic ordering graph. A cross-epic story dependency is a claim about the two EPICS,
    # and treating it as story-local is what let a real plan build epic 23 before epic 3 while
    # violating no story edge at all: only a fraction of an epic's stories carry a cross-epic
    # gate, so the rest floated to whoever was idle.
    epic_pred, epic_cycles = archetypes.epic_predecessors(estimate)
    epic_stories = collections.defaultdict(set)
    for feature in features:
        if feature.get("epic_id"):
            epic_stories[feature["epic_id"]].add(feature["id"])
    # Which stories in each epic actually carry each component. A story whose surfaces leave it
    # with no owner for a component has no item for it, and must not hold its epic open.
    epic_needs = collections.defaultdict(set)
    for item in items:
        if item["feature"].get("epic_id"):
            epic_needs[(item["feature"]["epic_id"], item["component"])].add(item["feature"]["id"])

    finished = {}          # (story_id, component) -> finish week
    spec_done = {}         # story_id -> when its specification stopped moving
    story_done = {}        # story_id -> build finish, what dependants actually wait for
    epic_spec_done = {}    # epic_id -> when the LAST of its stories was specified
    epic_built = {}        # epic_id -> when the last of its stories finished building
    unresolved = [dict(row, story=None, waits_on=row["waits_on"]) for row in epic_cycles]
    scheduled = set()

    def epic_gate(epic, table, earliest):
        """Push `earliest` out past every predecessor epic, or say we are still waiting.

        Returns `(earliest, waiting)`. A predecessor that has not finished the component we are
        gating on is a wait rather than a zero — `max` over a missing entry would read an epic
        that has not started as one that finished in week zero, which is the exact shape of the
        bug this replaces.
        """
        waiting = False
        for before in epic_pred.get(epic) or ():
            if not epic_stories.get(before):
                continue                       # an epic with no stories gates nothing
            if before in table:
                earliest = max(earliest, table[before])
            else:
                waiting = True
        return earliest, waiting

    for stage in sorted({i["stage"] for i in items}):
        pending = [i for i in items if i["stage"] == stage]
        in_stage = {(i["feature"]["id"], i["component"]) for i in pending}
        stage_end = barrier
        while pending:
            # List scheduling over the READY set, not over story order. Taking the items in
            # document order instead looked reasonable and was not: with two developers it
            # handed the idle one a story's review, which cannot start until that same story's
            # build finishes, while the next story's specification — which could have started
            # immediately — waited its turn. The team serialised itself, and the sequential
            # archetype came out FASTER than the pipelined one, which is impossible.
            ready = []
            for item in pending:
                fid = item["feature"]["id"]
                previous = _previous(item["component"])
                if previous and (fid, previous) in in_stage and (fid, previous) not in scheduled:
                    continue
                earliest = max(barrier, finished.get((fid, previous), 0.0))
                waiting = False
                mine = item["feature"].get("epic_id")
                # Dependencies gate the BUILD, not the specification. A BA can write F102 while
                # F101 is still being built — what F102 cannot do is be built against an F101
                # that does not exist. Gating spec on story-level BUILD completion made the
                # pipelined archetype come out SLOWER than the sequential one, because
                # sequential's spec stage had no dependants in flight to wait for and the
                # pipeline's did.
                if item["component"] != "spec":
                    for dep in item["feature"].get("depends_on") or []:
                        if dep in story_done:
                            earliest = max(earliest, story_done[dep])
                        elif dep in known and dep != fid and (dep, "build") in in_stage:
                            waiting = True
                    # And the epic the story sits in waits for the epics it stands on. Without
                    # this the plan built `Phase 2 AI — Module 2` in week 5.3 and the
                    # prerequisites epic it is recorded as depending on in week 9.3.
                    if mine:
                        earliest, blocked = epic_gate(mine, epic_built, earliest)
                        waiting = waiting or blocked
                elif mine:
                    # Specification is ordered by the epic graph too, but against the
                    # predecessors' SPECIFICATION rather than their build — so Phase 2 analysis
                    # cannot start before the Phase 2 prerequisites are written down, and no
                    # analyst ever waits on a developer. Before this every one of 23 epics
                    # began its specification inside the same fifth of a week, which is what a
                    # reader saw as "Phase 2 starts alongside Phase 1".
                    earliest, blocked = epic_gate(mine, epic_spec_done, earliest)
                    waiting = waiting or blocked
                if waiting:
                    continue
                # `earliest` is bucketed to the tenth of a week before `order` is consulted, so
                # an epic the inventory sequences first is not beaten by one that happens to
                # come free four minutes sooner. Comparing raw floats made `order` — the only
                # place `sequence` appears — a tiebreak that never actually decided anything.
                ready.append((round(earliest, 1), item["order"],
                              COMPONENT_ORDER[item["component"]], earliest, item))
            if not ready:
                # Everything left is waiting on something that will never arrive in this stage:
                # a dependency the stated epic sequence puts after its own dependant. The
                # inventory's checker rejects cycles, so this is an ordering contradiction
                # rather than a loop. Record it and schedule the rest rather than hanging.
                for item in pending:
                    for dep in item["feature"].get("depends_on") or []:
                        if dep in known and dep not in story_done and dep != item["feature"]["id"]:
                            unresolved.append({"story": item["feature"]["id"], "waits_on": dep,
                                               "why": "dependency is sequenced after this story"})
                    mine = item["feature"].get("epic_id")
                    table = epic_spec_done if item["component"] == "spec" else epic_built
                    for before in epic_pred.get(mine) or ():
                        if epic_stories.get(before) and before not in table:
                            unresolved.append({
                                "story": item["feature"]["id"], "waits_on": before,
                                "why": "the epic this story stands on does not complete in "
                                       "this stage — the archetype's staging contradicts the "
                                       "epic ordering"})
                ready = [(barrier, i["order"], COMPONENT_ORDER[i["component"]], barrier, i)
                         for i in pending]

            *_, earliest, item = min(ready, key=lambda r: (r[0], r[1], r[2]))
            feature, component = item["feature"], item["component"]
            fid, epic = feature["id"], feature.get("epic_id")
            ends = []
            # Within a story's SPECIFICATION the analyst leads and the others read what they
            # wrote. `role_weights.spec` puts ba at 0.42, dev at 0.28 and ux at 0.30, and
            # booking all three from the same instant had a developer specifying a story
            # nobody had written a line of yet. The ordering is applied to spec only: a build
            # is genuinely concurrent across the surfaces it touches.
            owners = item["owners"]
            if component == "spec":
                owners = sorted(owners, key=lambda o: (o[0] != "ba", o[0]))
            leader_done = None
            for role, hours in owners:
                person = _pick(team, role)
                if person is None:
                    continue
                at = earliest if leader_done is None else max(earliest, leader_done)
                start, end = person.take(hours, at, feature.get("name") or fid,
                                         fid, epic, component)
                if component == "spec" and role == "ba":
                    leader_done = end
                ends.append(end)
            if ends:
                finished[(fid, component)] = max(ends)
                stage_end = max(stage_end, max(ends))
                if component == "spec":
                    spec_done[fid] = max(ends)
                if component == "build":
                    story_done[fid] = max(ends)
                    # Sweep as each epic closes, not only at stage boundaries. The pipelined
                    # archetype has ONE stage, so a stage-end sweep put its QA after the last
                    # build in the backlog — the very archetype that is supposed to overlap
                    # most. `sweep` is idempotent per epic, so calling it often is free.
                    qa.sweep(finished, barrier)
            scheduled.add((fid, component))
            pending.remove(item)
            # An epic completes a component when the LAST of its stories does, which is what a
            # dependant epic waits for. `epic_needs` is the set of stories that actually carry
            # this component — a story whose surfaces give it no owner for one has no item and
            # must not hold its epic open forever.
            if epic and component in ("spec", "build"):
                want = epic_needs.get((epic, component)) or set()
                if want and all((s, component) in scheduled for s in want):
                    table = epic_spec_done if component == "spec" else epic_built
                    table[epic] = max(finished[(s, component)] for s in want
                                      if (s, component) in finished)
        barrier = stage_end
        for person in team:
            person.ready = max(person.ready, barrier)
        # QA for every epic this stage finished building — inside the loop, on that epic's own
        # build finish. Called once after the loop with the final barrier, as it was, QA could
        # not start before the last story in the backlog was built, in any archetype: one run
        # put the first QA hour in week 36 of 41. Late QA is not a presentation problem. It
        # lets a defect propagate through everything built after it, architectural ones
        # included, which are the most expensive to undo.
        qa.sweep(finished, barrier)

    qa.regression(barrier)
    drift_hours = drift(team, features, spec_done)

    for feature in features:
        story_done.setdefault(feature["id"], finished.get((feature["id"], "spec"), 0.0))

    span = max([p.ready for p in team] + [prefix_weeks, 0.0])
    return {
        "weeks": round(span, 2),
        "planning_prefix_weeks": round(prefix_weeks, 2),
        "effective_hours_per_person_week": round(effective, 2),
        "nominal_hours_per_person_week": rate,
        "concurrent_people_charged": round(concurrency, 2),
        "coordination_drag_applied": round(drag * max(0.0, concurrency - 1), 4),
        "stages": len({i["stage"] for i in items}),
        "team": [{"role": p.role, "name": p.name, "on_project": p.on_project,
                  "delivered_hours": round(p.busy, 1), "ramp_hours": round(p.ramp, 1),
                  "blocked_weeks": round(p.blocked, 3),
                  "join_week": round(p.join_week, 3),
                  "ramp_until_week": round(p.ramp_until, 3),
                  "starts_week": round(min([i["start_week"] for i in p.items], default=0.0), 3),
                  "finishes_week": round(p.ready, 2),
                  # Measured over the time this person was ON the project, not over the whole
                  # plan. A developer who joins in week 7 of a ten-week plan and is booked solid
                  # is 100% occupied, and reading them as 30% would tell the sweep to refuse a
                  # person who was fully used.
                  "utilisation": (round(p.busy / (max(span - p.join_week, 1e-9) * effective), 3)
                                  if span and effective else 0.0),
                  "items": p.items}
                 for p in team],
        "drift_hours": round(drift_hours, 1),
        "unresolved_dependencies": unresolved,
    }


class QaPasses:
    """QA as passes against completed slices, not as a tail bolted onto the end.

    One pass per epic, run as soon as that epic's build closes, sized by that epic's share of
    the story work — so the number of passes scales with the scope, because a larger scope has
    more epics. Then a regression pass over everything, last.

    It replaced a single call made after the stage loop with the FINAL barrier, which floored
    every epic's QA — including the first epic's — at the finish of all story work. QA could
    not overlap the build in any archetype, and a real run put the first QA hour in week 36 of
    41 while the function's own docstring claimed it ran "alongside the build". Late QA is not
    a scheduling nicety: it lets a defect propagate through everything built after it, and the
    architectural ones are the most expensive to undo.

    QA's hours are priced as a share of the story total and live on `project_components`, not
    on any story, which is why they have to be placed here rather than falling out of the
    per-story pass.
    """

    def __init__(self, estimate, team, features):
        self._epic_of = {f["id"]: (f.get("epic_id") or "—") for f in features}
        self._stories = {}
        for feature in features:
            self._stories.setdefault(feature.get("epic_id") or "—", []).append(feature["id"])
        component = (estimate.get("project_components") or {}).get("qa") or {}
        self.by_role = {r: (row.get("hours") or 0.0)
                        for r, row in (component.get("by_role") or {}).items()}
        self.team = team
        self.weight, self.done = {}, set()
        for feature in features:
            epic = feature.get("epic_id") or "—"
            self.weight[epic] = self.weight.get(epic, 0.0) + (feature.get("hours") or 0.0)
        self.total = sum(self.weight.values())
        # Held back for the regression pass. A per-epic sweep alone says every defect is found
        # inside the epic that caused it, which is the assumption integration testing exists
        # because nobody believes.
        self.regression_share = float(REGRESSION_SHARE)

    def _book(self, epic, share_of_total, earliest, label):
        for role, hours in self.by_role.items():
            person = _pick(self.team, role)
            if person is None or not hours:
                continue
            person.take(hours * share_of_total, earliest, label, None, epic, "qa")

    def sweep(self, finished, barrier):
        """QA every epic whose build has closed and which has not been tested yet."""
        if not self.total:
            return
        built = {}
        for (story_id, component), end in finished.items():
            if component != "build":
                continue
            epic = self._epic_of.get(story_id)
            if epic is not None:
                built[epic] = max(built.get(epic, 0.0), end)
        for epic in sorted(built, key=lambda e: built[e]):
            if epic in self.done or epic not in self.weight:
                continue
            if not self._fully_built(epic, finished):
                continue
            self.done.add(epic)
            share = (self.weight[epic] / self.total) * (1.0 - self.regression_share)
            self._book(epic, share, built[epic], f"QA pass · {epic}")

    def regression(self, barrier):
        """The last pass, over everything, after the final build."""
        if not self.total:
            return
        # Anything never swept — an epic with no build, or one the stages finished together —
        # is picked up here rather than dropped. Hours that are priced and scheduled to nobody
        # are the failure this whole area is being corrected for.
        missed = sum(self.weight[e] for e in self.weight if e not in self.done)
        share = self.regression_share + (missed / self.total if self.total else 0.0) \
            * (1.0 - self.regression_share)
        self._book(None, share, barrier, "QA regression pass")

    def _fully_built(self, epic, finished):
        return all((story, "build") in finished or (story, "spec") in finished
                   for story in self._stories.get(epic, ()))


def drift(team, features, spec_done):
    """Build hours booked while the specification around them was still moving.

    This is the price of overlapping, counted rather than characterised — the number a risk
    paragraph quotes instead of an adjective. It is measured per EPIC: a story built while
    another story in its own epic, or in an epic it depends on, is still being specified was
    built against a shape that could still change.

    The obvious narrower definition — build starting before the spec of a story it directly
    depends on — is vacuous, because a build already waits for its dependency's BUILD, which
    is strictly later than that dependency's spec. It scored every archetype at zero, which
    is how it was caught: an archetype whose whole cost is rework cannot cost nothing.

    Sequential scores zero by construction: its barrier finishes every specification before
    any build starts, which is what the archetype is.
    """
    epic_of = {f["id"]: f.get("epic_id") for f in features}
    settles = {}
    for fid, when in spec_done.items():
        epic = epic_of.get(fid)
        settles[epic] = max(settles.get(epic, 0.0), when)
    upstream = {}
    for feature in features:
        mine = feature.get("epic_id")
        for dep in feature.get("depends_on") or []:
            theirs = epic_of.get(dep)
            if theirs and theirs != mine:
                upstream.setdefault(mine, set()).add(theirs)

    total = 0.0
    for person in team:
        for item in person.items:
            if item["component"] != "build":
                continue
            epic = item["epic_id"]
            watch = {epic} | upstream.get(epic, set())
            latest = max([settles.get(e, 0.0) for e in watch] or [0.0])
            # Tolerance exceeds the 3-decimal rounding on start_week; without it a sequential
            # plan scored a couple of hours of drift purely from the rounding, which would have
            # quietly broken the "zero by construction" claim the baseline rests on.
            if item["start_week"] + 1e-3 < latest:
                total += item["hours"]
    return round(total, 1)


def _previous(component):
    """The component that must finish before this one. None for the first, and None for work
    that is not part of the per-story chain at all — QA trails an epic's build rather than a
    story's rework, and asking what precedes it has no answer in these terms."""
    i = COMPONENT_ORDER.get(component)
    return COMPONENTS[i - 1] if i else None


def _pick(team, role):
    """The soonest-AVAILABLE person in this role. Nobody is idle while work in their role waits.

    Available is the later of free and arrived. Sorting on `ready` alone handed work to a
    developer who had not joined yet while one who had sat idle — `take()` would have delayed
    the start correctly, but the queue would already have been given to the wrong person.
    """
    candidates = [p for p in team if p.role == role]
    return min(candidates, key=lambda p: max(p.ready, p.join_week)) if candidates else None


def chain_floor_weeks(estimate, model, rate):
    """The shortest calendar the dependency chain permits, in this model's own terms.

    `estimate.json`'s `dependencies.hours` is the chain measured in TOTAL story hours, which
    divided by one person's rate assumes a single person performs every role on every story in
    the chain, one after another. That is not what the cost model says happens: a story's spec
    is BA, UX and dev working at the same time, and only the COMPONENTS are ordered.

    So the honest floor is the chain's elapsed duration — for each story on it, the sum over
    components of the largest single role's hours, since the others finish alongside. Using the
    raw hours instead reported a perfectly deliverable plan as beating its own critical path by
    a tenth of a week, which is the kind of failure that teaches a reader to ignore the check.
    """
    chain = (estimate.get("dependencies") or {}).get("chain") or []
    if not chain or not rate:
        return 0.0
    by_id = {f["id"]: f for f in estimate.get("features", [])}
    weeks = 0.0
    for story_id in chain:
        feature = by_id.get(story_id)
        if not feature:
            continue
        cells = story_role_hours(feature, model)
        for component in COMPONENTS:
            same = [hours for (comp, _), hours in cells.items() if comp == component]
            if same:
                weeks += max(same) / rate
    return weeks


def mean_concurrent_headcount(schedule):
    """What overhead must actually be multiplied by.

    `overhead = rate x weeks x people`, and using the team's headcount would bill ceremony for
    a developer who joins in week 12 across all twelve weeks before they arrived. The honest
    multiplier is delivered person-weeks over elapsed weeks — the average number of people on
    the project at any moment, which on a staggered plan is materially below the roster.

    That last clause was a hope until `join_weeks()` existed: every plan started everybody in
    week one, so the average and the roster were the same number by construction.
    """
    weeks = schedule["weeks"]
    if not weeks:
        return 0.0
    rate = schedule["effective_hours_per_person_week"]
    person_weeks = sum((p["delivered_hours"] + p["ramp_hours"]) / rate for p in schedule["team"]) if rate else 0.0
    return round(person_weeks / weeks, 2)


def span_for_pricing(schedule, model, basis):
    """The span in the shape estimate.py's `check_span` demands.

    Three-point rather than a single number, because architect and overhead multiply it and
    collapsing it here would hand them a certainty the schedule does not have. The width is
    the model's own uncertainty on the work, not a new coefficient: a schedule is as uncertain
    as the hours it is made of.
    """
    weeks = schedule["weeks"]
    people = mean_concurrent_headcount(schedule)
    return {
        "weeks": round(weeks, 1),
        "weeks_range": [round(weeks * 0.85, 1), round(weeks * 1.3, 1)],
        "weeks_three_point": (weeks * 0.85, weeks, weeks * 1.3),
        "assumed_team_size": people,
        "basis": basis,
    }
