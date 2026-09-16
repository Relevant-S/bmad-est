#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""How many people, and the refusal when the backlog cannot keep them busy.

Headcount is an OUTPUT of this module, not an input. The default assumption is that the
company can hire, so the sweep explores the option space and reports what each team shape
costs. A roster the user supplies is a starting point rather than a ceiling: the sweep may add
to it, and it says so plainly when the roster is larger than the work can occupy.

Two gates stand between a proposed person and a plan that includes them, and both must pass:

  the independent-work floor  Can the dependency graph give this person a set of stories that
                              fills their time, without putting them on the same seam as
                              somebody else? Measured off the graph the inventory already
                              carries and validates. No new coefficient.
  the coordination cost       Every added person costs ramp before they deliver and slows
                              everyone already there. This is what lets the sweep return a
                              LARGER team that finishes LATER for more money, which is the
                              answer a guardrail that only counted hours could never give.

Refusals name their numbers: the idle hours, the colliding stories, the week the person would
first deliver. A headcount decision nobody can check is a headcount decision nobody can argue
with, and the whole point of this module is that a salesperson can defend the line.
"""

import collections

# Roles whose hours are a share of the story work, so more of them can in principle be run in
# parallel. `architect` is deliberately absent: it is priced as setup plus a capped weekly
# presence, so a second architect buys nothing the model can price.
PARALLELISABLE = ("dev", "ba", "ux", "qa", "devops")

ROLE_LABEL = {"ba": "BA", "ux": "UX", "dev": "developer", "qa": "QA engineer",
              "devops": "DevOps engineer", "architect": "architect"}

ORDINAL = {2: "second", 3: "third", 4: "fourth", 5: "fifth", 6: "sixth"}


def role_demand(estimate):
    """Delivery hours by role on the stories, ignoring the project-level components.

    Project-level hours are not parallelisable by adding a body: planning is a serial prefix,
    QA is a share, overhead and architect are priced on the calendar. Sizing a team against a
    total that includes them is how a plan ends up with a developer whose work is somebody
    else's meeting.
    """
    out = collections.Counter()
    for feature in estimate.get("features", []):
        if feature.get("origin") == "standing":
            continue
        for role, row in (feature.get("by_role") or {}).items():
            out[role] += row.get("hours", 0.0)
    qa = estimate.get("project_components", {}).get("qa")
    if qa:
        for role, row in (qa.get("by_role") or {}).items():
            out[role] += row.get("hours", 0.0)
    return dict(out)


def partition(estimate, role, count):
    """Split the backlog between `count` people in one role, minimising the shared seam.

    Epics are the unit, because an epic is the grain at which people actually collide: two
    developers in one epic are in the same files, and two developers in different epics
    usually are not. Assignment is greedy longest-first onto the lightest person: the standard
    makespan heuristic, and the one whose result a reader can reproduce by hand from the epic
    list.

    This is the plan's HUMAN-READABLE answer to "who takes what", and that is all it is now.
    It used to be load-bearing: `cut_share` gated headcount on how many dependency edges
    crossed these buckets, which refused a second developer who split the work evenly and
    saved six weeks. The gate is `blocked_share` and it reads the simulation. Note that the
    scheduler does not honour this partition — `_pick` assigns by soonest-free — so treat it
    as a suggested division of labour, not as a description of the plan.
    """
    hours = collections.Counter()
    epic_of = {}
    for feature in estimate.get("features", []):
        if feature.get("origin") == "standing":
            continue
        epic = feature.get("epic_id") or "—"
        epic_of[feature["id"]] = epic
        hours[epic] += (feature.get("by_role") or {}).get(role, {}).get("hours", 0.0)

    buckets = [{"epics": set(), "hours": 0.0} for _ in range(max(1, count))]
    for epic, weight in sorted(hours.items(), key=lambda kv: -kv[1]):
        target = min(buckets, key=lambda b: b["hours"])
        target["epics"].add(epic)
        target["hours"] += weight

    owner = {epic: i for i, b in enumerate(buckets) for epic in b["epics"]}
    cut, crossing = 0, []
    for feature in estimate.get("features", []):
        if feature.get("origin") == "standing":
            continue
        mine = owner.get(epic_of.get(feature["id"]))
        for dep in feature.get("depends_on") or []:
            theirs = owner.get(epic_of.get(dep))
            if theirs is not None and mine is not None and theirs != mine:
                cut += 1
                if len(crossing) < 8:
                    crossing.append({"story": feature["id"], "waits_on": dep})
    edges = sum(len(f.get("depends_on") or []) for f in estimate.get("features", [])
                if f.get("origin") != "standing")
    return {
        "buckets": [{"epics": sorted(b["epics"]), "hours": round(b["hours"], 1)} for b in buckets],
        "cut_edges": cut,
        "total_edges": edges,
        "cut_share": round(cut / edges, 3) if edges else 0.0,
        "crossing": crossing,
    }


def delivered_by(sched, role):
    """Hours each person in a role actually received in a simulated schedule."""
    return [p["delivered_hours"] for p in sched["team"] if p["role"] == role]


def blocked_share(sched, role):
    """The share of this role's elapsed time spent free and unable to start.

    This replaced `cut_share`, which counted dependency edges crossing a hypothetical partition
    of the EPICS. Three things were wrong with that. It was non-monotonic in the epic count —
    one epic scored 0% and the gate was vacuous, two scored ~50% and it refused everything. It
    judged a partition the scheduler never makes, because `_pick` assigns by soonest-free and
    ignores epics entirely. And on a real plan it refused a second developer who split the work
    264 h / 264 h and saved 5.9 weeks, on the grounds that 50% of the dependencies crossed a
    boundary that existed only inside the check.

    Waiting is the thing that metric was trying to proxy, and it is right here in the schedule.
    """
    people = [p for p in sched["team"] if p["role"] == role]
    weeks = sched["weeks"] or 1.0
    if not people:
        return 0.0
    # Elapsed time ON THE PROJECT. People now arrive when the demand justifies them rather than
    # all in week one, so dividing by the whole span for everybody would dilute a late joiner's
    # waiting across weeks they were not here — and this gate refuses headcount on that number.
    present = sum(max(weeks - p.get("join_week", 0.0), 1e-9) for p in people)
    return sum(p.get("blocked_weeks", 0.0) for p in people) / present


def judge(estimate, model, role, count, sched, on_project=0, before=None):
    """May this role run `count` people? The verdict, and the numbers behind it.

    Judged against a REAL simulation of the candidate shape, not against an analytic span. The
    first version derived the span from the bottleneck role and then measured that role against
    it, so the bottleneck came back at exactly 100% occupied every time and the gate could never
    refuse the one role anybody ever wants more of. It approved a fourth developer on a backlog
    holding two person-weeks of development.

    The question a gate can answer is **is there independent work for this person** — does the
    schedule actually hand them a share of their role's hours, and does that share sit apart
    from everybody else's. How occupied the whole team is across the calendar is a different
    question, and it belongs in the fit score where it can be traded against the calendar
    rather than silently deciding it.
    """
    cfg = model.get("staffing") or {}
    rate = sched["effective_hours_per_person_week"]
    span = sched["weeks"]
    floor = float((cfg.get("utilisation_floor") or {}).get("likely") or 0.75)
    ceiling = float((cfg.get("collision_threshold") or {}).get("likely") or 0.25)
    ramp = float((cfg.get("ramp_hours") or {}).get("likely") or 0.0)
    label = ROLE_LABEL.get(role, role)

    got = delivered_by(sched, role)
    delivered = sum(got)
    split = partition(estimate, role, count)
    # Does the work split N ways? Measured as hours delivered PER WEEK ON THE PROJECT, not as
    # a share of the total. People now arrive when their role's demand justifies them, so a
    # developer who joins in week 5 of a nine-week plan carries less of the total by
    # construction — comparing them against an even share would refuse them for arriving late,
    # which is a decision this same function already made for them.
    here = [p for p in sched["team"] if p["role"] == role]
    present = [max(span - p.get("join_week", 0.0), 1e-9) for p in here] or [span or 1.0]
    pace = sorted(h / w for h, w in zip(got, present)) or [0.0]
    slowest = pace[0]
    typical = sum(pace) / len(pace)
    smallest = min(got) if got else 0.0
    # Capacity is counted from each person's arrival, not from week one. Charging a developer
    # who joins in week 7 for the six weeks before they existed reported them as half-occupied
    # when they were booked solid, and the utilisation floor below would then refuse somebody
    # the backlog genuinely needed.
    weeks_present = sum(present) if here else (count * span)
    capacity = rate * weeks_present if span else 0.0
    utilisation = delivered / capacity if capacity else 0.0
    newcomers = max(0, count - on_project)

    reasons, refusals = [], []
    if count > 1 and typical and slowest < floor * typical:
        refusals.append(
            f"the work does not split {count} ways — the least-loaded {label} clears only "
            f"{slowest:.0f} h per week on the project against {typical:.0f} h across the role, "
            f"for {smallest:.0f} h of the {delivered:.0f} h of {label} work in total. The "
            f"dependency graph, not the hours, is what limits this.")
    if count > 1 and smallest <= ramp:
        refusals.append(
            f"a {ORDINAL.get(count, f'{count}th')} {label} would deliver {smallest:.0f} h "
            f"after spending {ramp:.0f} h arriving. They would cost more than they carry.")
    # The MARGINAL waiting this person introduces, not the total. A story's build always waits
    # for its own specification and its dependencies' builds, at any headcount — charging that
    # to the newcomer refused every addition on every backlog shape, including one that split
    # evenly and saved two and a half weeks. What the newcomer is answerable for is the waiting
    # that did not exist before they arrived.
    waiting = blocked_share(sched, role)
    was = blocked_share(before, role) if before else 0.0
    added = max(0.0, waiting - was)
    if count > 1 and added > ceiling:
        refusals.append(
            f"a {ORDINAL.get(count, f'{count}th')} {label} would add {added:+.0%} to the time "
            f"this role spends waiting ({was:.0%} -> {waiting:.0%}), above the {ceiling:.0%} "
            f"threshold — they would be working the same seam, and the dependency graph will "
            f"not let them run side by side. "
            + (", ".join(f"{c['story']}→{c['waits_on']}" for c in split["crossing"][:4])
               or "the chain runs through most of the backlog"))
    # Does this person actually shorten the plan by more than they spend arriving? The
    # marginal test, and the only honest form of the ramp gate: an earlier version compared
    # the ramp against a share of the role's backlog and suppressed itself when the role was
    # "over-subscribed", a condition measured by a utilisation that was pinned at 100% by its
    # own arithmetic. Once that was fixed the guard never fired and the gate refused everybody.
    saving = (before["weeks"] - sched["weeks"]) if before else None
    ramp_weeks = (ramp / rate) if rate else 0.0
    if count > 1 and newcomers and saving is not None and saving < ramp_weeks:
        refusals.append(
            f"a {ORDINAL.get(count, f'{count}th')} {label} would take {ramp_weeks:.1f} weeks "
            f"to come up to speed and shorten the plan by "
            f"{max(saving, 0.0):.1f} — they cost more calendar than they buy.")

    refusals = [r[0].upper() + r[1:] if r else r for r in refusals]
    if not refusals:
        reasons.append(
            f"{count} {label}{'s' if count > 1 else ''}: {delivered:.0f} h of {label} work "
            f"splits {'/'.join(f'{g:.0f}' for g in got)} h over {span:.1f} weeks, with "
            f"{split['cut_share']:.0%} of dependencies crossing the split.")
        if count > 1:
            for i, bucket in enumerate(split["buckets"], start=1):
                reasons.append(f"  {label} {i} takes {', '.join(bucket['epics']) or 'nothing'} "
                               f"({bucket['hours']:.0f} h)")
    return {
        "role": role, "count": count, "allowed": not refusals,
        "demand_hours": round(delivered, 1),
        "capacity_hours": round(capacity, 1),
        "span_weeks": round(span, 2),
        "delivered_each": [round(g, 1) for g in got],
        "utilisation": round(utilisation, 3),
        "idle_hours": round(max(0.0, capacity - delivered), 1),
        "newcomers": newcomers,
        "ramp_hours": round(newcomers * ramp, 1),
        "weeks_saved": round(saving, 2) if saving is not None else None,
        "blocked_share": round(waiting, 3),
        "blocked_share_added": round(added, 3),
        "cut_share": split["cut_share"],
        "partition": split["buckets"],
        "justification": reasons,
        "refusals": refusals,
    }


def oversized_roster(estimate, model, roster, span_weeks):
    """Flag a supplied roster the backlog cannot keep busy.

    The roster is never treated as a ceiling — the sweep may still add to it — but a roster
    that is already too large is the one thing a plan must not quietly absorb. Somebody is
    being billed for sitting still, and it will be discovered late.
    """
    cfg = model.get("staffing") or {}
    floor = float((cfg.get("utilisation_floor") or {}).get("likely") or 0.75)
    rate = model["calendar"]["hours_per_person_week"]
    demand = role_demand(estimate)
    out = []
    for role, count in sorted(roster.items()):
        if not count:
            continue
        capacity = count * rate * span_weeks
        used = demand.get(role, 0.0)
        if capacity and used / capacity < floor:
            out.append({
                "role": role, "supplied": count,
                "utilisation": round(used / capacity, 3),
                "idle_hours": round(capacity - used, 1),
                "sustainable_count": max(1, int(used / (rate * span_weeks * floor))) if span_weeks else 1,
                "note": (f"The roster has {count} {ROLE_LABEL.get(role, role)}(s); this scope "
                         f"holds {used:.0f} h of "
                         f"{ROLE_LABEL.get(role, role)} work, which occupies {used / capacity:.0%} of them. "
                         f"{capacity - used:.0f} hours are idle."),
            })
    return out


def sweep(estimate, model, roster=None, simulate=None):
    """Every team shape worth pricing, with each headcount decision already justified.

    `simulate(shape) -> schedule` is supplied by the caller so the guardrail judges a candidate
    against a real pass over the dependency graph rather than an analytic proxy. plan.py hands
    in the most permissive archetype: refusing a shape on its best case is a strong refusal,
    and approving one on its worst case would refuse people the plan could have used.

    The roster, when supplied, sets the FLOOR for each role rather than the cap — people
    already on the project are kept, and the sweep proposes what to add on top.
    """
    cfg = model.get("staffing") or {}
    rate = model["calendar"]["hours_per_person_week"]
    # `max_useful_parallelism` is read here as what its own `why` says it is — a bound on ONE
    # WORKSTREAM, "beyond roughly six people on one workstream". est-estimate applies the same
    # number to the whole delivery team when it divides hours by people, which is a looser
    # reading of the same coefficient; the discrepancy is named rather than resolved, because
    # resolving it would mean changing a measured-adjacent number to suit a new consumer.
    # Applied whole-team it would end this sweep after one addition: five roles seeded at one
    # person each already spend five of the six.
    per_role_cap = min(int(model["calendar"]["max_useful_parallelism"]),
                       int((cfg.get("max_added_per_role") or {}).get("likely") or 4))
    roster = {k: int(v) for k, v in (roster or {}).items() if v}

    demand = role_demand(estimate)
    active = [r for r in PARALLELISABLE if demand.get(r, 0.0) > 0.5 or roster.get(r)]
    floor_weeks = ((estimate.get("dependencies") or {}).get("hours") or 0.0) / rate

    def fallback(shape):
        """Used only when no simulator is supplied — tests and direct callers.

        Bounded by the BOTTLENECK ROLE, not by the total over everybody. Dividing all the work
        by the whole headcount modelled a second developer as speeding up the BA too, which
        understated what they buy by roughly the number of roles on the project and made the
        marginal gate refuse every addition. plan.py always passes a real simulation; this is
        the honest approximation for a caller that cannot.
        """
        weeks = max([floor_weeks] + [demand.get(r, 0.0) / (n * rate)
                                     for r, n in shape.items() if n])
        return {"weeks": weeks, "effective_hours_per_person_week": rate,
                "team": [{"role": r, "delivered_hours": demand.get(r, 0.0) / n}
                         for r, n in shape.items() for _ in range(n)]}

    run = simulate or fallback
    shapes, decisions = [], []
    base = {role: max(1, roster.get(role, 0)) for role in active}
    shapes.append(dict(base))
    current = dict(base)
    exhausted = set()
    # Grow until every role is either at its cap or has been refused. The guardrail is what
    # stops this, not an arbitrary team size — which is the whole point of headcount being an
    # output. A role that is refused is not retried: the backlog does not get wider.
    while len(exhausted) < len(active):
        pressure = {r: demand.get(r, 0.0) / current[r] for r in active
                    if r not in exhausted and current[r] < per_role_cap}
        if not pressure:
            break
        role = max(pressure, key=pressure.get)
        candidate = dict(current, **{role: current[role] + 1})
        verdict = judge(estimate, model, role, current[role] + 1, run(candidate),
                        roster.get(role, 0), before=run(current))
        decisions.append(verdict)
        if not verdict["allowed"]:
            exhausted.add(role)
            continue
        current[role] += 1
        shapes.append(dict(current))
        if current[role] >= per_role_cap:
            exhausted.add(role)

    base_span = run(base)["weeks"]
    return {"shapes": shapes, "decisions": decisions, "roster": roster,
            "span_hint_weeks": round(base_span, 2),
            "oversized": (oversized_roster(estimate, model, roster, base_span)
                          if roster else [])}
