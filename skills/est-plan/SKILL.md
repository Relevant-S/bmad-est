---
name: est-plan
description: Turns a priced estimate into staffed, scored delivery options with a Gantt. Use when user says "plan this", "how do we deliver it", "what team do we need", "how long with three developers", "can we hit sixteen weeks", or "show me the options". Supports headless (-H) for batch runs.
---

# est-plan

## Overview

Takes a finished estimate and answers the question the estimate cannot: **who delivers this, in what order, and what does that version cost.** It never re-extracts scope and never re-classifies a story — the priced scope is one fact, and what this produces is a set of readings of it.

Act as a delivery lead sizing a team, not as a scheduler filling a chart. The output is a small set of complete plan-and-cost pairs a salesperson can put in front of a client and defend line by line.

`module-code: est`

## Resolution rules

- `{skill-root}` — this skill's directory
- `{project-root}` — the repository root
- `{output_folder}` / `{estimates}` — from `modules.est.est_output_folder`
- `{workspace}` — `{estimates}/{project-slug}`, the folder est-scope-extract created and est-estimate priced
- `{memory}` — `{project-root}/_bmad/memory/est`

## The bar

**Every schedule offered has to be deliverable in the real world.** Nobody works on blocked work, nobody joins and delivers the same morning, nobody exceeds a full week, and no plan beats its own dependency chain. An option that fails any of those is reported as not deliverable and is never recommended.

**Every headcount decision states its justification.** A person is added because the dependency graph gives them work that fills their time and does not put them on somebody else's seam — with the hours named. A person is refused the same way, with the idle hours and the colliding stories named. A refusal nobody can check is a refusal nobody can argue with.

**Every option carries its own estimate.** Not one set of numbers re-presented under three timelines.

## Input boundary

Consumes `{workspace}/estimate.json` and nothing else. If the estimate does not exist, run `/est-estimate` — planning a scope nobody has priced would mean inventing the hours, and this skill has no way to price a story.

The estimate must carry `dependencies` and per-story `by_role`, which means it must not have been produced in `quick` mode. It must also carry a cost model with a `staffing` block (schema 3.2 or later); an older one is migrated with `est-estimate/scripts/migrate-cost-model.py`.

## Planning

**Settle the inputs first**, in two sentences. **Headcount is an output of this workflow, not an input to it** — the default assumption is that the company can hire, and the whole point is to show the option space so somebody can choose. Ask only for what genuinely constrains: whether a team is *already on this project* (`--team dev=2,qa=1`, a floor rather than a ceiling), and whether there is a target span (`--deadline 16`, in **weeks** — this module does not take dates). Say plainly that a supplied roster may be added to, and may be reported as larger than the backlog can occupy.

**Then look at the graph before you look at the schedule.** `estimate.json` carries `dependencies.chain` and every story's `depends_on`, validated upstream by `inventory-check.py` — `check_sequence` refuses a build order that contradicts a stated dependency, and `find_cycles` refuses a loop. If the inventory's check reported sequence violations, fix those first: a plan built over a contradicted ordering is a plan that reads correctly and cannot be run. A backlog with **no** recorded dependencies at all is worth a sentence to the user, because every archetype then collapses towards the same answer and the differences below stop being informative.

**Compute.** `uv run {skill-root}/scripts/plan.py {workspace}/estimate.json -o {workspace}/plan.json [--team dev=2] [--deadline 16] [--archetype pipelined]` (`--help` for the interface). It sweeps team shapes, simulates each archetype over the dependency graph, re-prices every combination through est-estimate's own engine, checks feasibility and scores what survives.

**Read the staffing decisions before the options.** `plan.json`'s `staffing.decisions` is where the argument is. Each entry names the role, the headcount, whether it was allowed, the utilisation it rests on, and — for a refusal — the idle hours or the dependency edges that cross the split. `staffing.oversized_roster` fires when the team the user already has is larger than this scope can keep busy; that one is worth raising immediately rather than burying in a document, because somebody is being billed for sitting still.

**Then read the options.** Each carries `schedule` (per person, per week), its own `estimate` (the full role table), `score.parts` (six sub-scores, each with the number it rests on), `risks` (named, each with a mitigation) and `feasibility`. The recommendation is the highest-scoring option that passed feasibility; `score.weights` comes from the cost model, so anyone who weighs duration against cost differently can re-run it rather than argue.

**Render.** `uv run {skill-root}/scripts/render-plan.py {workspace}/plan.json --workbook {workspace}/estimate.xlsx` writes `plan.md` and **appends** the `Options` tab and one `Gantt — <Archetype>` tab per schedule offered to the workbook est-estimate already produced. There is deliberately no second workbook: a client should not have to read a plan beside an estimate to see which stories a bar covers, and every bar's row links to its row on the `Stories` tab.

**Present the options as pairs, never as calendars.** Lead with what the client is choosing between — a team shape and a number — and give the span second. Quote each role's own range; the module's rule that role bands are not summed holds here exactly as it does in an estimate.

## Headless

`-H`/`--headless`, no TTY, or every input supplied up front: take no roster and no deadline unless they were passed, run every archetype, and return `{"plan": <path>, "options": n, "recommended": <id>, "refused": [...], "oversized_roster": [...]}`. Never invent a roster — an unconstrained sweep is the honest default and is what a caller who supplied nothing asked for.

## Gotchas

- **Weeks are relative, and this module does not produce dates.** Bars are `W1..Wn`. The standing rule across est-estimate and est-agent-estimator is that duration must not harden into a date, and a Gantt is exactly where that happens. Week 1 is whenever the project starts; converting it to a calendar is the client's decision and their risk.
- **The options differ in their hours, and that is the point.** The architect is `setup + a capped weekly rate` and ceremony is `rate x weeks x people`, so a longer plan genuinely costs more. Story hours, planning and QA never move — they are properties of the scope. If two options ever differ in a story's hours, something has re-priced the work while claiming to re-price the calendar.
- **Overhead is multiplied by the average number of people on the project, not by the roster.** A developer who joins in week 12 did not attend the first eleven weeks of ceremony.
- **There is no PM role in this model.** `role_weights` says so outright: the architect absorbs PM responsibilities. A plan that reports "PM hours" would be reporting a role nothing prices.
- **A second architect is never proposed.** The architect is priced as setup plus a capped weekly presence, so the model has no way to price a second one. That is a limit of the model, not a claim about delivery.
- **The staffing coefficients are asserted, not measured.** `ramp_hours` and `coordination_drag` rest on no delivered project of this company's — none recorded who was on it in which week. Confidence 3/10 on the levels, 7/10 on the shape. Say so if a client asks why a fourth developer was refused, and never quote the drag figure as a finding.
- **Drift is a measured number, not an adjective.** `schedule.drift_hours` is the build hours booked while the specification around them was still moving. Sequential scores zero by construction; that is what the archetype is, and it is the baseline the others are read against.
- **The plan does not write back into `estimate.json`.** The estimate stays the ledger-recorded record of the priced scope. Each option's hours live in `plan.json` and are labelled as that option's.
