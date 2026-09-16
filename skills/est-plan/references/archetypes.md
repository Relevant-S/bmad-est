# The archetypes, and what each one actually costs

Three shapes, and they differ in one thing only: **when a role is allowed to start.** Everything else about the simulation is identical, which is what makes a difference in the answer attributable rather than atmospheric.

Each is a policy that assigns every unit of work to a **stage**. Stages run strictly in order — everything in stage 0 finishes before anything in stage 1 begins — and inside a stage the pass is free, constrained only by the dependency graph and by who is available.

## Sequential

Staged by component. Every story's specification is stage 0, every build stage 1, review 2, rework 3.

The BA specifies the whole scope, then UX, then the architect stands the project up, then the team builds. Nobody ever builds against a specification that is still moving, so **drift is zero by construction** — not by good behaviour. That is why this is the baseline every other option is scored against.

**What it buys.** The lowest rework exposure available, and a plan that survives a client who changes their mind in week 2, because nothing has been built yet.

**What it costs.** The longest calendar, and a client who sees nothing running until late. On a backlog with no dependencies it is often not much slower than the alternatives — the component barriers still let the whole team work one component at once — which is worth checking before selling the risk reduction as expensive.

## Foundation-then-pipeline

Two stages, cut on the dependency graph rather than on taste. Stage 0 is every epic that another epic waits on; stage 1 is everything else.

Foundational epics are identified from the story-level `depends_on` rolled up to epic level, plus `depends_on_epics` for the ordering no story records. Where nothing depends on anything, the first epic in the stated build order is taken — otherwise this archetype would silently become the pipelined one and the plan would be offering the client two names for the same schedule.

**What it buys.** Most of the calendar a pipeline buys, with the discipline concentrated where rework is expensive: the code everything else stands on is finished before anything is built on top of it.

**What it costs.** The foundation sits on the critical path, so slipping it slips everything. And on a backlog with no real dependencies the barrier buys nothing and costs overlap — it can come out *slower* than sequential. The fit score will say so; that is the score working, not a bug.

## Pipelined

One stage. The only constraints are the dependency graph and who is free.

The team starts each epic as soon as it is specified while the BA moves on to the next.

**What it buys.** The shortest calendar, and a client who sees something running early.

**What it costs.** Measured, not asserted. `schedule.drift_hours` counts the build hours booked while the specification around them was still moving — a story built while another story in its own epic, or in an epic it depends on, was still being written. That number is the option's rework exposure and it is what the risk paragraph quotes.

## What the drift number means, and what it does not

It is **hours of build at risk of rework**, not hours of rework. Some of it will cost nothing; the specification will settle exactly where the builder assumed. It is an exposure, and it is reported as one.

The narrower definition — build starting before the spec of a story it *directly* depends on — was tried and is vacuous: a build already waits for its dependency's *build*, which is strictly later than that dependency's spec. It scored every archetype at zero. An archetype whose whole cost is rework exposure cannot cost nothing, and that is how the definition was caught.

## Reading the three together

The span order is **not** guaranteed. Pipelined is never slower than sequential — the barriers can only delay work — but foundation can land either side of sequential depending on how much the backlog actually depends on itself. The **risk** order is guaranteed: sequential 0 drift, then foundation, then pipelined.

If all three come out within a week of each other, say so. It means the backlog has little internal dependency, the sequencing discipline is nearly free, and the choice should be made on team shape instead.
