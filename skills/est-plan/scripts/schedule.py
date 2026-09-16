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
        self.items = []

    def reset(self, rate):
        """Put this person back at week zero at a new rate, for the second pass."""
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
        self.blocked += max(0.0, earliest - self.ready)
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
                  "ramp_until_week": round(p.ramp_until, 3),
                  "starts_week": round(min([i["start_week"] for i in p.items], default=0.0), 3),
                  "finishes_week": round(p.ready, 2),
                  "utilisation": round(p.busy / (span * effective), 3) if span and effective else 0.0,
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
