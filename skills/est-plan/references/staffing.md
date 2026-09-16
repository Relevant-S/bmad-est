# Deciding headcount, and refusing it

**Headcount is an output.** The default assumption is that the company can hire, so the sweep explores the option space and reports what each shape costs. A roster the user supplies is a **floor**: the sweep keeps those people, may add to them, and says so when the roster is larger than the backlog can occupy.

## The two gates

A proposed person must pass both.

### 1. The independent-work floor

Can the dependency graph give this person work that fills their time without putting them on somebody else's seam?

The backlog is partitioned by **epic**, because an epic is the grain at which people actually collide — two developers in one epic are in the same files, two developers in different epics usually are not. Assignment is greedy longest-first onto the lightest person: the standard makespan heuristic, and one whose result a reader can reproduce by hand from the epic list.

Then the candidate shape is **actually simulated** and two numbers come out of the schedule:

- **the split** — how much of the role's work the least-loaded person in it receives. Below `staffing.utilisation_floor` (0.75) of an even share, the graph will not divide the work: two developers on a strict chain look fine on hours and come out 26 h and 18 h once the pass is walked.
- **cut share** — the dependencies crossing a partition boundary, as a share of all of them. Above `staffing.collision_threshold` (0.25) the two people are working the same seam: parallelism on paper, blocked mornings in practice.

Both refusals name their numbers — the hours each person would get, the crossing stories.

**Why a simulation and not a formula.** The first version of this gate compared a role's hours against `count x rate x span`, where the span was itself derived from the bottleneck role — so the bottleneck came back at exactly 100% occupied in every case, and the one role anybody ever wants more of could never be refused. It approved a fourth developer for a backlog holding two person-weeks of development. A gate whose arithmetic guarantees its own answer is not a gate.

### 2. The coordination cost

Every person costs something before they deliver anything, and something to everyone else once they arrive.

- **`ramp_hours`** (16 h likely) is charged once, out of that person's own capacity, *before* their first delivery week. Charged anywhere else, a plan could add a body in the final fortnight and book their whole output. Somebody already on the project pays nothing — they have ramped.
- **`coordination_drag`** (3.5% likely) is throughput lost per additional person, applied to each person's own rate: a team of *n* delivers `n x (1 - drag x (n-1))`. This is what lets the sweep return a **larger team that finishes later for more money**, which a guardrail that only counted hours could never produce.

**The ramp is also the yardstick for the marginal gate.** A person is refused when they shorten the plan by less calendar than they spend arriving — *"a third developer would take 0.5 weeks to come up to speed and shorten the plan by 0.3"*. That is the honest form of the question. An earlier version compared the ramp against a share of the role's backlog and suppressed itself when the role was "over-subscribed", a condition measured by the same circular utilisation described above; once that was fixed the guard never fired and the gate refused everybody.

## What the sweep will not do

- **It will not propose a second architect.** The architect is priced as setup plus a capped weekly presence, so the model has no way to price one. That is a limit of the model and is stated as one.
- **It will not retry a refused role.** The backlog does not get wider on the second ask.
- **It will not exceed `calendar.max_useful_parallelism` in one role.** That coefficient's own `why` says "beyond roughly six people on **one workstream**", and it is read here as what it says. Note the discrepancy honestly if it comes up: `est-estimate` applies the same number to the whole delivery team when it divides hours by people. Resolving it would mean changing a measured-adjacent coefficient to suit a new consumer, which this module does not do quietly.

## The confidence to quote

`ramp_hours` and `coordination_drag` rest on **no delivered project of this company's**. All three anchors recorded role totals and none recorded who was on the project in which week. Confidence is **3/10 on the levels and 7/10 on the shape**.

What is defensible: that a person costs something before they deliver, and that keeping people aligned costs more as there are more of them. The external agreement claimed is narrow — communication paths grow `n(n-1)/2`, and QSM's project database puts the productive band at 3–7 people, which is where this curve turns over. Neither measured this company, this stack, or a team working through BMad agents, which is the whole variable the rest of the model exists to capture.

Raise it with one project that records its team composition over time. Until then, say "refused because the backlog holds 82 independent hours for them and they need 180" — which is measured — rather than "refused because of coordination drag", which is not.
