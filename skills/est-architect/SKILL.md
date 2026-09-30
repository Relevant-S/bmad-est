---
name: est-architect
description: Designs the architecture for an extracted scope — a scored technology stack, a build/adopt/buy decision per capability, a scored platform set, an infrastructure diagram and a cited run-cost breakdown. Use when user says "design this", "what should we build it on", "what stack", "buy or build", "which cloud", "draw the architecture" or "what will it cost to run". Supports headless (-H).
---

# est-architect

## Overview

Takes a Feature Inventory and answers the question between *what is in scope* and *what it
costs*: **what are we building this on, what do we write ourselves, and where does it run.**

Act as a solution architect who will have to defend this to the engineers who build it and to
the client who pays for it. The output is `architecture.json` plus an infrastructure diagram, a
run-cost breakdown, and a handoff that makes `est-estimate` price the decision rather than a
guess about it.

`module-code: est`

## Resolution rules

- Bare paths and `{skill-root}` resolve from this skill's installed directory.
- `{project-root}` → the project working directory.
- `{output_folder}` → `core.output_folder` via `uv run {project-root}/_bmad/scripts/resolve_config.py -p {project-root}`, defaulting to `{project-root}/_bmad-output`. Config is TOML here, so reading `config.yaml` finds nothing and defaults silently.
- `{estimates}` → `modules.est.est_output_folder` from the same resolved config, defaulting to `{output_folder}/estimates`.
- `{workspace}` → `{estimates}/{project-slug}/`, the folder `est-scope-extract` created.
- `{memory}` → `{project-root}/_bmad/memory/est/`, holding `architecture-model.json` and `architecture-preferences.md`.

## The bar

**The non-negotiable: every box on the diagram says what it is there for.** This is the
module's first artefact with no client quote behind it, and the diagram is the most persuasive
thing it will ever put in front of a client. Every component carries `serves` — the feature ids,
the standing-work item, or the recorded assumption that puts it on the canvas — and
`architecture-check.py` fails the run on one that serves nothing. Invented infrastructure is the
same failure as invented scope.

**A component is refused the way a headcount is refused.** est-plan will not add a developer
without naming the hours that fill their time. This will not add a queue because a system might
one day need one, will not add a vendor serving only what another vendor in the set already
serves, and will not build a capability the scope does not ask for. Every refusal is recorded
with what was considered and why.

**Nothing is chosen blindly** — not a language, a framework, a library, a platform, or a
build-it-ourselves. Every choice is an option in a scored table with its reasoning, or an
explicitly recorded assumption. "Use Postgres because we always do" is a preference with a
weight, and it is written down as one.

**Every score decomposes or it is theatre.** Sub-scores each carry the number they rest on. A
sub-score with no evidence reports `null` and says why — it is excluded from the composite
rather than counted as zero, because "we did not look" and "we looked and it was bad" are
different claims.

**A hard constraint is a gate, not a penalty.** An option violating one is reported **not
viable** and is never recommended, however well it scores.

**Sourcing never changes the scope.** Buying identity does not delete the identity stories. The
work is still delivered, differently; what changes is its classification, and that is
est-estimate's call and not this skill's.

## Input boundary

Consumes `{workspace}/feature-inventory.json` and nothing else is required. It does not
re-extract scope and does not classify a story. If the inventory does not exist, run
`/est-scope-extract`.

It reads `{workspace}/estimate.json` **if one already exists**, which lets the hour-bearing
sub-scores report hours rather than story counts. It never writes to it.

**It refuses to run without a working diagram renderer.** The diagram is a required output, so
`uv run {skill-root}/scripts/check-renderer.py` must pass; if it does not, run `/est-setup`.

## Designing

**First run only:** if `{memory}/architecture-model.json` does not exist, copy
`assets/architecture-model.seed.json` there, and `assets/architecture-preferences.seed.md` to
`{memory}/architecture-preferences.md`. Those are now the company's own; the assets are only
ever seeds. Never edit an asset to change one project's answer.

**Settle four things first**, in two sentences, before anything is designed — the same
discipline as est-scope-extract's "which source is contractual", and for the same reason:
discovering a constraint mid-run is how it gets applied inconsistently.

| Input | Default | Why now |
| --- | --- | --- |
| **Platform requirements** | none → the house preference breaks ties only | A mandated platform, an existing estate, a client who will inherit and operate it, a residency requirement. Silence does **not** mean AWS wins; it means nothing is *gated* and the scoring decides. |
| **Procurement and licence position** | ask | Whether the client will pay third-party subscriptions at all, who holds them after handover, and whether any licence class is excluded. This gates the whole sourcing layer. |
| **Non-functional drivers** | from the inventory, then ask | Scale, latency, compliance regime, residency, offline, traffic shape. The inventory records scope, not NFRs, and a compliance regime nobody wrote a story for is what decides the shape of the whole design. |
| **Hard constraints** | none | Separated from preferences deliberately: a preference lowers a score, a constraint removes an option. |

Init `{workspace}/.memlog.md` if absent and append one `assumption` entry per input you had to
default. Six months on, nobody will remember whether a residency requirement was stated or
assumed.

**Then read the inventory as an architect.** The drivers are already in the file and mostly
unread today: surfaces per epic say which tiers exist, `depends_on` rolled up says where the
seams are, `implicit_scope` is where the migrations live, `standing_scope.selected` says what
platform work this project already pays for, and `open_questions` is where the design is being
asked to absorb an unresolved commercial question — which it must not do silently.

**Map capabilities to stories.** `uv run {skill-root}/scripts/capabilities.py {workspace}/feature-inventory.json`
builds the first pass by keyword signal, and **labels every link as a signal match**, because a
map that looks authoritative and was built by substring search is exactly the confident wrong
artefact this module exists to avoid. Read it and correct it: a capability attached to work
that never mentioned it puts a box on a client-facing diagram for something nobody asked for.

**Research what is current** — this is where `kindly-web-search` earns its place. Fan out one
subagent per concern, each returning ONLY compact findings **with their sources and dates**:
the libraries this scope needs and whether they are maintained; a framework's current major
version; candidate solutions per live capability, with licences; which platforms serve a
capability in the required region. Research is for *what is true now*, not for reading the
product — the product is in the inventory. **Record what you checked, not only what you found.**
Without research, every sub-score that depends on it reports `null` and the report says which.

**Then score the three layers, in order**, because each constrains the next:

```
Layer 1  stack         an OSS candidate must exist in this ecosystem
Layer 2  sourcing      only what runs somewhere needs a platform
Layer 3  platform set  capability -> platform, possibly several
```

`uv run {skill-root}/scripts/architect.py {workspace}/feature-inventory.json -o {workspace}/architecture.json
[--estimate {workspace}/estimate.json] [--stacks stacks.json] [--candidates candidates.json]
[--inputs inputs.json] [--preferences {memory}/architecture-preferences.md]` (`--help` for the
interface). It scores every layer, evaluates the constraints, enumerates platform sets, computes
the components and audits its own output. **Exit 2 means the audit failed**: the file is still
written so it can be argued with, and it must not be sent.

### Three gates, and the run stops at each one

**Every layer is presented and verified before the next is scored.** `references/gates.md` is
the contract. `architect.py` **exits 3** at the first unconfirmed gate and writes
`gate-<layer>.md` beside the output — that is the normal outcome of the first three
invocations, not an error.

| Gate | Flag to continue | What the operator is choosing |
| --- | --- | --- |
| 1. Stack | `--stack-confirmed` | Language, frameworks, tooling. **If the winner contradicts a stack the sources record as decided, the gate says so** — that invalidates any estimate already priced on it, which is a commercial consequence and belongs at the moment of choosing. |
| 2. Sourcing | `--sourcing-confirmed` | Build, adopt or buy, per live capability. One table, accepted wholesale or corrected selectively — **not a queue**: asking one at a time produces rubber-stamping exactly where accuracy matters most. |
| 3. Platform set | `--platform-confirmed` | Where each capability runs, with sprawl, runtime fit and reversibility beside each set. |

Corrections come back as inputs, not as edits: `inputs.stack_choice`,
`inputs.sourcing_overrides`, `inputs.capability_overrides`. All three are echoed into
`architecture.json`, so the deliverable can reproduce the run.

**When you disagree with the scoring, say so in your own name.** Put it in
`inputs.model_counter_proposals` — it does not change the decision, and the gate presents it as
*the workflow's* proposal. A run once placed two of its own counter-proposals behind an option
labelled `(Recommended)`, the operator ticked it, and the log recorded them as operator
corrections. Both facts were true and the record told only one of them.

**Record every answer with `memlog.py append`**, never by appending to `.memlog.md` by hand and
never by editing its `updated:` stamp. A log written with a shell heredoc and a hand-pinned
timestamp is prose that looks like provenance: the same run left entries dated three hours
before the files they cite.

**Read three things before the options.** `layers.sourcing.balance` — the build/adopt/buy
distribution, with a finding at the degenerate ends that the report has to answer.
`research.unsourced_subscores` — which parts of this recommendation rest on nothing.
`catalogue_gaps` — capabilities no platform profile serves, which is a gap in the catalogue and
not in any option.

**Render the diagram.** `uv run {skill-root}/scripts/render-diagram.py {workspace}/architecture.json
-o {workspace}/architecture.png --document {workspace}/diagram.json --measured {workspace}/diagram.measured.json`.
A **required output**: an unknown icon is an error rather than a placeholder glyph, a connector
drawn over a component fails the run, and a failed render fails the run.

Read the report rather than the exit code alone.

- `routing.checks` is **H1 to H10** against the geometry the browser actually produced, each one
  `pass`, `note` or `fail`. A `note` is a shape the layout could not improve on this architecture
  — an aspect ratio, a fourth bend — and is reported rather than hidden. `routing: null` means
  **nobody looked**: the measured geometry needs the pinned local renderer, so run `/est-setup`
  rather than shipping an unchecked diagram.
- `routing.routes.replaced` should be empty. It names connectors whose authored route the renderer
  threw away and re-drew for itself, which is a layout failure wearing a finished picture.
- `routing.edge_crossings` against `routing.crossing_budget`. Zero crossings is a planarity
  question, not a setting: two components reaching the same two others form a K(2,2) and force
  one. The budget scales with the graph and the number is always stated.
- `layout.iterations` — up to five ELK strategies, scored on nothing-broken, then shape, then
  notes. `layout.aspect` is what was chosen.
- `graph` — sections A1, A2, A4 and A5 on the semantic graph: a wrapper container, a duplicate
  name, a node with no second label line.
- `icons.official` against `icons.glyph` says how much of the artwork is the vendors' own.

Icons are **resolved on demand from the vendors' own catalogues** — the official AWS, Azure and
GCP architecture sets, then SVGL, then Iconify — and cached. Nothing is bundled: there are 2,693
official cloud SVGs alone and they are revised quarterly. A researched profile therefore never
has to name an icon; it names a service and the artwork follows. Offline, every component falls
back to its capability glyph and the diagram still renders.

**Only a named product gets an official icon.** A component carries `product` when the design
chose a concrete thing and nothing when it kept its capability's own label — and a label is not
a product: *"Identity and access"* resolves to **Ping Identity's** logo if you let it. When a
capability you expected to be a named service comes out with a glyph, the fix is upstream: give
it a sourcing decision or a `component_overrides` entry, never a hand-picked icon name.

**A component that runs inside something says so.** `runs_on` makes the runtime a group with its
own official icon and the software an icon inside it, so "Django on Fargate" is two products
rather than one label. The runtime comes from `serves.<capability>.runtime` in the platform
profile; if `architecture-check.py` reports `runtime_unnamed`, add it to the profile rather than
writing it into the component's name. A label that repeats its own runtime is also reported.

**Then price it.** Fan out one research subagent **per vendor, not per row** — one pricing page
usually covers several capabilities. Each returns ONLY structured rows carrying `rate`, `unit`,
`currency`, a **verbatim `quote` from the page**, the `url` and `fetched_at`. Assemble with
`uv run {skill-root}/scripts/price.py {workspace}/architecture.json --rows rows.json -o {workspace}/costs.json`,
which recomputes every figure from `rate x quantity` and every total, then verify with
`uv run {skill-root}/scripts/cost-check.py {workspace}/costs.json`, which **re-fetches each
cited page and checks the quoted figure is still on it**. `references/costing.md` is required
reading before the first row is written.

**Render the document.** `uv run {skill-root}/scripts/render-architecture.py {workspace}/architecture.json
--costs {workspace}/costs.json -o {workspace}/architecture.md --csv {workspace}/cost-breakdown.csv`.

**Then check the workspace holds what the module declares.**
`uv run {skill-root}/../est-setup/scripts/check-outputs.py --skill est-architect --workspace {workspace}`.

**`{workspace}` is the only location.** Everything this skill writes goes there and nowhere
else. A run once copied six deliverables into a second presentation folder; the copy omitted the
inputs, so the folder a reader was handed could not reproduce what it described, and
`check-outputs` never saw it. If a presentation copy is wanted, copy the **whole** workspace.

**Present each gate as a choice, and the final report as a decision.** At a gate, lead with what
the operator is choosing between and the number each option rests on. In the finished report,
lead with what was chosen and why, and say plainly which sub-scores rest on nothing.

## Headless

`-H`/`--headless`, no TTY, or every input supplied up front: follow `references/headless.md`.
Take the recommendation at every gate, proceed, and **return all three confirmation flags as
false** — never silently. An unattended run may choose; it may not report a choice nobody made
as though somebody had made it.

## Gotchas

- **Run-cost is not delivery cost.** The breakdown is dollars per month and continues after the
  project ends; the estimate is hours. They are never summed and never rendered adjacent
  without a label. This is the same standing rule that keeps agreed and additional scope from
  being merged into one figure.
- **Nothing in the cost table may be invented.** Every figure traces to a verbatim quote from a
  vendor's pricing page, with the URL and the date. A price that cannot be fetched is `unpriced`
  with its reason. This is the point in the whole workflow where fabrication is most likely: a
  model that has read a thousand AWS pricing pages will produce a plausible number faster than
  it will admit it could not reach the page, and a wrong price looks exactly like a right one.
- **The sourcing effort ratios are asserted, not measured.** `sourcing_effort` says so outright
  and every basis line repeats it. The stories at stake are real; the ratio applied to them has
  no delivered project behind it. Confidence 2/10 on the levels. Say so if a client asks why
  building was recommended over buying.
- **An unresearched option is never recommended.** The delivery-effort sub-score structurally
  favours not building, so an option with one score and four blanks outranked `build` on every
  capability nobody had looked at — which is to say the workflow recommended buying things it
  had never examined. Only a fully evaluated option can win.
- **`checked: null` on a platform profile is not "no".** It means nobody verified it. A
  certification or residency gate against such a field is reported **unevaluated** — neither a
  pass nor a fail — and `architecture-check.py` raises a finding when a gate rests on one.
- **The house preference is a weight and never a gate.** It cannot make a non-viable set viable
  and cannot overturn a materially better fit. When it decides the answer, the report says so:
  "AWS chosen on the house preference; Vercel + Supabase scored within 0.3" is a far more useful
  sentence than a silent default.
- **A capability nobody argues about stays out of the tables.** Nobody builds a CDN; nobody buys
  the domain rules that are the reason the project exists. Those are `settled` with a one-line
  reason, and forty-five scores nobody reads is the failure that prevents.
- **Adding a platform is a data file, never code.** If a platform ever needs code, the
  capability boundary is in the wrong place — that is the test this design has to keep passing.
- **A vendor's logo is drawn once.** A platform profile names its own logo for every capability
  it serves, so a set hosting five things on one platform drew four Fly balloons and two Sentry
  marks — a picture of the vendor rather than of the system. The vendor keeps its logo on the
  application tier; every other component falls back to what the capability catalogue says it
  is, and a repeat that survives that fails the render.
- **Every option comes from research, not from the file.** The catalogue is twenty profiles
  because twenty is where it started, not because twenty is the space. If a capability has one
  candidate, that is a research gap and the report has to say so rather than presenting the
  single option as a choice.
- **An icon is never invented either.** The resolver has a floor under what counts as a match
  and returns nothing below it: without one it drew an arcade game for "Fly Machines (static or
  SSR)" and the Auth.js logo for "Clerk (auth + orgs)" — a different company's brand on someone
  else's box. Below the floor the component gets its capability's own glyph, which is the right
  answer and not a lesser one.
- **The platform catalogue lives in two places and merges.** Shipped profiles under
  `assets/platforms/`, the company's own under `{memory}/platforms/`, memory winning on a clash.
  A run wrote six profiles into memory and nothing read them, because the loader defaulted to
  the asset directory — so the scoring ran against a three-platform catalogue while nine were
  on disk.
- **The graph has to be true before the picture can be good.** Edges were once derived from
  tiers, which joined every component in the application tier to every component in services,
  data and external — so the browser was drawn talking straight to a secrets manager and a
  payment vendor, and aggregating edges to their groups hid it behind six plausible arrows. The
  catalogue declares `reaches` now. No layout engine rescues a false graph.
- **Nothing here computes a coordinate.** `graph.py` says what, ELK says where, `layout.py`
  adapts. The box model that preceded it grew a constant per defect and produced a 2x3 grid with
  no reading direction.
- **No connector runs over a component, and that is measured.** `render.mjs` asks the renderer
  for the laid-out geometry — final boxes and routed points — and `diagram-check.py` tests every
  segment against every box that is not an endpoint or its container. The first real diagram had
  nineteen such crossings; the second had two, was measured, was reported, and shipped anyway
  because a group crossing was only a note. It fails the run now.
- **A test never writes into `assets/icon-cache`.** A stubbed resolver that did put a green
  square in `aws-simple-email-service.svg`, and that square was drawn on a client's diagram.
  `render()` takes an `icon_cache`; the suite passes a temporary one.
- **`produced_by` says which copy of this skill ran.** A project installs the module by copy. One
  real run was reviewed for a day against this repository's behaviour before anyone noticed it
  had executed a copy three weeks old. If the revision in `architecture.json` does not match the
  module's, reinstall before reading anything else into the output.
- **Weeks, hours and dollars stay apart.** This skill produces no hours and no dates. The stack
  profile and the sourcing notes it hands to est-estimate are **evidence, not verdicts** — the
  classifier still decides every band.
