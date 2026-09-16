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

COMPONENTS = ("spec", "build", "review", "rework")

# The roles that carry each component, in the cost model's own terms. Read from role_weights
# at run time rather than duplicated here — this tuple is only the ORDER, which is the one
# thing role_weights does not state.
COMPONENT_ORDER = {name: i for i, name in enumerate(COMPONENTS)}


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
        self.items = []

    def take(self, hours, earliest, label, story_id=None, epic_id=None, component=None):
        """Book `hours` of this person's time, not starting before `earliest`."""
        start = max(self.ready, earliest)
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


def simulate(estimate, model, team, policy, staffing=None):
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
    size = len(team)
    effective = rate * max(0.25, 1.0 - drag * max(0, size - 1))
    for person in team:
        person.rate = effective

    features = [f for f in estimate.get("features", []) if f.get("origin") != "standing"]
    epic_seq = {e.get("id"): e.get("sequence") or 0 for e in estimate.get("epics") or []}
    order = sorted(features, key=lambda f: (epic_seq.get(f.get("epic_id"), 0), str(f["id"])))
    known = {f["id"] for f in features}

    prefix_weeks, prefix_roles = plan_prefix(estimate, team, model, effective)
    for person in team:
        if person.role in prefix_roles:
            person.ready = max(person.ready, prefix_weeks)
    barrier = 0.0

    items = []
    for n, feature in enumerate(order):
        cells = story_role_hours(feature, model)
        for component in COMPONENTS:
            owners = [(role, hours) for (comp, role), hours in cells.items() if comp == component]
            if owners:
                items.append({"stage": policy(feature, component), "order": n,
                              "feature": feature, "component": component,
                              "owners": sorted(owners)})

    finished = {}          # (story_id, component) -> finish week
    spec_done = {}         # story_id -> when its specification stopped moving
    story_done = {}        # story_id -> build finish, what dependants actually wait for
    unresolved = []
    scheduled = set()

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
                # Dependencies gate the BUILD, not the specification. A BA can write F102 while
                # F101 is still being built — what F102 cannot do is be built against an F101
                # that does not exist. Gating spec too made the pipelined archetype come out
                # SLOWER than the sequential one, because sequential's spec stage had no
                # dependants in flight to wait for and the pipeline's did.
                if item["component"] != "spec":
                    for dep in item["feature"].get("depends_on") or []:
                        if dep in story_done:
                            earliest = max(earliest, story_done[dep])
                        elif dep in known and dep != fid and (dep, "build") in in_stage:
                            waiting = True
                if waiting:
                    continue
                ready.append((earliest, item["order"], COMPONENT_ORDER[item["component"]], item))
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
                ready = [(barrier, i["order"], COMPONENT_ORDER[i["component"]], i) for i in pending]

            earliest, _, _, item = min(ready, key=lambda r: (r[0], r[1], r[2]))
            feature, component = item["feature"], item["component"]
            fid, epic = feature["id"], feature.get("epic_id")
            ends = []
            for role, hours in item["owners"]:
                person = _pick(team, role)
                if person is None:
                    continue
                start, end = person.take(hours, earliest, feature.get("name") or fid,
                                         fid, epic, component)
                ends.append(end)
            if ends:
                finished[(fid, component)] = max(ends)
                stage_end = max(stage_end, max(ends))
                if component == "spec":
                    spec_done[fid] = max(ends)
                if component == "build":
                    story_done[fid] = max(ends)
            scheduled.add((fid, component))
            pending.remove(item)
        barrier = stage_end
        for person in team:
            person.ready = max(person.ready, barrier)

    schedule_qa(estimate, team, features, finished, barrier)
    drift_hours = drift(team, features, spec_done)

    for feature in features:
        story_done.setdefault(feature["id"], finished.get((feature["id"], "spec"), 0.0))

    span = max([p.ready for p in team] + [prefix_weeks, 0.0])
    return {
        "weeks": round(span, 2),
        "planning_prefix_weeks": round(prefix_weeks, 2),
        "effective_hours_per_person_week": round(effective, 2),
        "coordination_drag_applied": round(drag * max(0, size - 1), 4),
        "stages": len({i["stage"] for i in items}),
        "team": [{"role": p.role, "name": p.name, "on_project": p.on_project,
                  "delivered_hours": round(p.busy, 1), "ramp_hours": round(p.ramp, 1),
                  "ramp_until_week": round(p.ramp_until, 3),
                  "starts_week": round(min([i["start_week"] for i in p.items], default=0.0), 3),
                  "finishes_week": round(p.ready, 2),
                  "utilisation": round(p.busy / (span * effective), 3) if span and effective else 0.0,
                  "items": p.items}
                 for p in team],
        "drift_hours": round(drift_hours, 1),
        "unresolved_dependencies": unresolved,
    }


def schedule_qa(estimate, team, features, finished, barrier):
    """QA, per epic, trailing that epic's build.

    QA is priced as a share of the story total, so its hours live on `project_components`
    rather than on any story — which meant the QA engineer was staffed, counted in the team,
    charged coordination drag, and given nothing to do. The guardrail caught it by refusing a
    second QA engineer on the grounds that the first one delivered zero hours.

    It is scheduled rather than merely added because QA runs on the calendar alongside the
    build: `duration()` in estimate.py makes the same point, having once left QA out and put
    EPP at 5.7 weeks against a recorded 7. Allocated per epic in proportion to that epic's
    story hours, and gated on that epic's last build, because that is when there is something
    to test.
    """
    component = (estimate.get("project_components") or {}).get("qa")
    if not component:
        return
    hours = component.get("hours") or 0.0
    if hours <= 0:
        return
    weight, built = {}, {}
    for feature in features:
        epic = feature.get("epic_id") or "—"
        weight[epic] = weight.get(epic, 0.0) + (feature.get("hours") or 0.0)
        end = finished.get((feature["id"], "build"), finished.get((feature["id"], "spec")))
        if end is not None:
            built[epic] = max(built.get(epic, 0.0), end)
    total = sum(weight.values())
    if not total:
        return
    for role, row in (component.get("by_role") or {}).items():
        share = (row.get("hours") or 0.0)
        for epic, w in sorted(weight.items(), key=lambda kv: built.get(kv[0], 0.0)):
            person = _pick(team, role)
            if person is None or not w:
                continue
            person.take(share * w / total, max(barrier, built.get(epic, 0.0)),
                        f"QA · {epic}", None, epic, "qa")


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
    """The soonest-free person in this role. Nobody is idle while work in their role waits."""
    candidates = [p for p in team if p.role == role]
    return min(candidates, key=lambda p: p.ready) if candidates else None


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
