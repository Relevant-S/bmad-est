---
title: 'est-architect — architecture planning workflow'
status: 'complete'
module_name: 'BMad Delivery Estimator'
module_code: 'est'
module_description: 'Adds architecture design between scope extraction and pricing: a scored technology stack, a scored buy-vs-build decision per capability, a scored platform set, a rendered infrastructure diagram, and a cited run-cost breakdown.'
architecture: 'single workflow skill, added to an existing module'
standalone: false
expands_module: 'est'
skills_planned: ['est-architect']
config_variables: ['est_house_platform', 'est_diagram_renderer', 'est_chromium_path']
created: '2026-09-29'
updated: '2026-09-29'
revision: 4
---

# est-architect

## Vision

Once `est-scope-extract` has produced a Feature Inventory, the project is understood well
enough to design it. `est-architect` reads that inventory and answers the question that sits
between *what is in scope* and *what it costs*: **what are we building this on, what do we
write ourselves, and where does it run.**

Three scored decisions and one drawing:

1. **The technology stack** — language, frameworks, libraries, tooling.
2. **Sourcing, per capability** — build it in the project, adopt an existing open-source
   solution, or buy a managed one.
3. **The platform set** — where each capability runs, over the whole viable space and not three
   vendors. A platform set is frequently a *combination*.
4. **The infrastructure diagram** — one drawing of the decision actually taken, to the quality
   of the Eraser reference. A **required output**.
5. **The run-cost breakdown** — what the chosen architecture costs to operate, one row per
   service, **every figure fetched from a real pricing page and re-verifiable**.

Every option in every layer is scored 0–10 on sub-scores that each rest on a stated number.

## Where it sits in the chain

```
est-scope-extract  →  est-architect  →  est-estimate  →  est-plan
   what is in scope    what we build it on    what it costs   who delivers it
                       what we write ourselves
                       and where it runs
```

**Before `est-estimate`, not after.** The brief said "runs after `/est-scope-extract`", and the
strongest reading is *immediately* after — because `est-estimate` already takes an architecture
decision as an input and currently has nobody to ask.

Three couplings make this concrete. I traced the first two rather than assumed them:

1. **`--stack` selects standing work.** `estimate.py:208-227` reads `spec["stacks"]` on each
   `standing_work` item. The seed's values are `standard_saas` (the default), `multi_service`
   and `mobile_plus_backend`. Today a human guesses it; `est-architect` *derives* it — three
   deployable services means `multi_service`, and the items gated on that switch on with their
   hours. It is not a multiplier, and this plan must not claim it is one.
2. **`novelty` is where an unfamiliar stack costs money.** `novelty_rework_multiplier` is
   1.15× on the story total and 1.6× on the rework share, "new to the team or genuinely
   uncommon". A stack the company has never shipped makes stories novel. Recommending one and
   then pricing every story as `standard` is the failure this ordering prevents.
3. **Sourcing changes what a story is.** A story that integrates a bought identity provider is a
   different size band from one that builds session handling — and the band is what the whole
   estimate is built on. This is the strongest of the three couplings and it is why the sourcing
   layer belongs here rather than in a conversation nobody records.

Running it after the estimate would mean re-pricing, and `est-estimate` is the ledger-recorded
record of a priced scope — re-pricing because an architecture changed is exactly the
re-entrancy the module avoids elsewhere.

## The bar

**The non-negotiable: every box on the diagram says what it is there for.** An architecture
recommendation has no client quote behind it — this is the module's first artefact that is pure
judgement, and the diagram is the most persuasive thing it will ever put in front of a client.
So each component carries `serves`: the feature ids, the standing-work item, or the recorded
assumption that puts it on the canvas. A component that serves nothing is invented
infrastructure, which is the same failure as invented scope, and `architecture-check.py` fails
the run on it.

**A component is refused the way a headcount is refused.** `est-plan` will not add a developer
without naming the hours that fill their time. `est-architect` will not add a queue because a
system might one day need one, will not add a vendor that serves a capability another vendor in
the set already serves, and will not build a capability the scope does not ask for. Each
refusal is recorded with what was considered and why it was declined.

**Nothing is chosen blindly.** Not the language, not a framework, not a library, not a platform,
not a build-it-ourselves. Every choice is an option in a scored table with its reasoning, or it
is an explicitly recorded assumption. "Use Postgres because we always do" is a preference with a
weight, not a design, and it is written down as the former.

**Every score decomposes or it is theatre.** A bare "8/10, the pragmatic choice" is precisely
what this module refuses everywhere else. Six sub-scores per layer, each with the number it
rests on, and weights in a file so a reader who weighs lock-in differently re-runs rather than
argues.

**A hard constraint is a gate, not a penalty.** Data residency, a mandated platform, an
incompatible licence, a certification the client requires — an option that violates one is
reported **not viable** and is never recommended, however well it scores. This mirrors
`est-plan`'s feasibility check.

**Sourcing never changes the scope.** Buying identity does not delete the identity stories. The
work is still delivered; it is delivered differently, and what changes is its classification.
An architecture workflow that quietly shrinks the backlog is an architecture workflow that has
re-priced the deal without saying so.

## Input boundary

Consumes `{workspace}/feature-inventory.json` — the epics, the stories, their `surfaces`, their
`depends_on`, `implicit_scope`, `standing_scope`, `not_scope` and `open_questions`. It does not
re-extract scope and does not classify a story.

It reads `{workspace}/estimate.json` **if it happens to exist** — a re-run after pricing can then
express the hour-bearing sub-scores in hours rather than story counts and bands. It never writes
to it.

**It refuses to run without a working diagram renderer**, naming `/est-setup` — the way
`est-plan` names `/est-estimate` when the estimate is missing. See *The diagram is required*.

## What it asks, and when

Settled up front, in two sentences, before anything is designed — the same discipline as
est-scope-extract's "which source is contractual", and for the same reason: discovering a
constraint mid-run is how it gets applied inconsistently.

| Input | Default | Why it is asked first |
| --- | --- | --- |
| **Platform requirements** | none stated → the house preference breaks ties only | Whether the project has a mandated platform, an existing account or estate, a client who will inherit and operate it, or a data-residency requirement. Silence does **not** mean AWS wins — it means nothing is *gated*, and the scoring decides. |
| **Procurement and licence position** | ask | Whether the client will pay third-party subscriptions at all, who holds them after handover, and whether any licence class is excluded. This gates the entire sourcing layer, and discovering it after the scoring is done means scoring the wrong option set. |
| **Non-functional drivers** | from the inventory, then asked | Scale, latency, compliance regime, data residency, offline/edge, expected traffic shape. The inventory records scope, not NFRs — and the reference diagram is a clinical platform whose whole shape is driven by one compliance regime nobody wrote a user story for. Each is recorded with its `why`; each defaulted one is a `.memlog.md` assumption entry, exactly as `est-estimate` logs its four profile inputs. |
| **Hard constraints** | none | The gates above. Separated from preferences deliberately: a preference lowers a score, a constraint removes an option. |

### The house preference is a tiebreak, not a default

The original brief said "if none, default to AWS"; the platform correction says cover the whole
space and pick the best fit. Both are honoured by making the house position a **weight, not a
gate**:

- `est_house_platform` (default `aws`) adds a stated bonus to the team-fit and operational
  sub-scores of platforms the company already runs — real advantages, because an existing
  account, an existing pipeline and existing on-call knowledge genuinely cost less.
- It **cannot** make a non-viable option viable, and it cannot overturn a materially better fit.
  When a non-house platform set wins, the report says so and by how much.
- When the scoring does not materially separate the candidates, the house set wins on the
  tiebreak, and the report says *that* — "AWS chosen on the house preference; Vercel + Supabase
  scored within 0.3" is a much more useful sentence than a silent default.

## The three scored layers

Scored in order, because each constrains the next. Scoring them as one combined table would
multiply out into dozens of near-identical "options" and hide which axis actually drove the
answer.

```
Layer 1  stack        language, frameworks, libraries, tooling
             ↓         constrains: an OSS candidate must exist in this ecosystem
Layer 2  sourcing     per capability: build · adopt open-source · buy managed
             ↓         constrains: only what runs somewhere needs a platform
Layer 3  platform set capability → platform, possibly several platforms
```

**This ordering corrects the previous revision.** Sourcing and platform were conflated: binding
a capability to Clerk is two decisions wearing one coat — *buy this rather than build it*, and
*buy it from Clerk*. Separating them makes both auditable, and makes it possible to say "we
decided to buy identity; every platform in the set was then evaluated on whether it already
serves it" — which is how the sprawl term below stops the set growing a vendor per capability.

### Layer 1 — the technology stack

Language, frameworks, the libraries the scope actually needs, test tooling, build tooling. The
drivers come from the inventory: surfaces per epic, the shape of the stories, `implicit_scope`
(the migrations and backfills), and the NFRs.

**Three options that differ structurally.** Two options differing only in a library name are one
option written twice. Fewer than three is honest when the scope genuinely admits fewer; padding
the list to look thorough is the theatre this rule exists to prevent.

| Sub-score | Rests on |
| --- | --- |
| **Scope fit** | Stories whose surfaces and shape the stack serves natively, against the total; the ones needing an escape hatch, named. *"112 of 116; 4 need real-time push, which needs a second runtime."* |
| **Library coverage** | Capabilities in the scope with a maintained library in this ecosystem against those needing to be built. Each named, with the library and its current version. |
| **Ecosystem currency** | Researched, dated and sourced: current major version, release cadence, whether the named libraries are maintained. This is where `kindly-web-search` earns its place — a framework's state in 2026 is not something to recall. |
| **Team fit** | Named technologies with a delivered project behind them, from module memory. Scores `null` and says so when the memory is unanswered — never a default of 5. |
| **Estimate impact** | Which `stack` profile it implies and which standing-work items that switches on, with their hours; and how many stories it makes `novelty: novel` at 1.15× / 1.6×. |
| **Constraint compliance** | Hard constraints, each pass or fail. Any fail makes the option **not viable**. |

### Layer 2 — sourcing: build, adopt, or buy

For each capability, three modes:

- **Build** — written in the project, in the Layer-1 stack.
- **Adopt** — an existing open-source solution, either an embedded library or a self-run
  component.
- **Buy** — a managed third-party service.

**This is the layer with the strongest numbers in the whole workflow.** The other two layers
score fit and risk; this one converts more or less directly into hours, which is this module's
home ground. Building identity is a set of stories with size bands. Buying it is a smaller set
of integration stories plus configuration. Both sets are nameable from the inventory, which
means "adopting this saves roughly these stories" is a claim with story ids behind it rather
than a feeling.

**Score only the live decisions.** Nobody builds a CDN; nobody buys the domain-specific business
rules that are the reason the project exists. Each capability is first marked **settled** — with
a one-line reason — or **live**. Only live ones get a scored option table. A capability is live
when it has credible candidates in more than one mode *and* the work at stake is material,
measured in stories or hours from the inventory. This mirrors `est-estimate`'s reconcile loop,
which re-judges only what the checker flags, and it is what keeps the artefact readable rather
than producing forty-five scores nobody reads.

| Sub-score | Rests on |
| --- | --- |
| **Delivery effort** | The stories this capability requires if built, against the integration stories it requires if adopted or bought. Named story ids with their size bands; in hours where an estimate already exists. The single most defensible number this workflow produces. |
| **Requirement fit** | How much of what the scope actually asks for the candidate provides natively, and what it cannot do. Named: *"covers F12–F19; does not do per-tenant key rotation, which F42 requires."* A gap here is not fatal — it becomes build work on top, and that work is counted in the effort sub-score rather than wished away. |
| **Maintenance health** | For open-source above all: maintained, last release, contributor count, single-maintainer risk, CVE history. Researched, dated, sourced. Adopting an abandoned library is a liability the project inherits on day one, and unlike most things here it is straightforwardly checkable. |
| **Cost and licence shape** | For open-source: the licence and whether it is compatible with how the client will ship and sell this — an AGPL component in a commercial SaaS is a gate, not a preference. For paid: the *pricing model shape* (per-seat, per-MAU, usage) and **who holds the subscription after handover**. The figure itself is not guessed here — it is fetched and cited in the cost breakdown below, and this sub-score reads it. |
| **Escape cost** | What replacing it later costs. A candidate behind a standard interface — OIDC, the S3 API, SQL — scores far above one behind a proprietary one, even when both are third-party. |
| **Constraint compliance** | Licence class, procurement position, certification, and whether a bought service processes client data in a permitted region. Each pass or fail; any fail makes the option **not viable**. |

#### Finding the balance, rather than asserting it

Both extremes are real failure modes and each has a mechanism against it:

- **Build-everything** — the engineering default. It inflates the estimate and the calendar.
  Countered by the effort sub-score, which makes the avoided stories explicit, and by the rule
  that a mature adopted candidate covering most of a requirement must be *scored against*, never
  skipped.
- **Buy-everything** — eleven vendors, none quite fitting, with integration glue costing more
  than building would have. Countered by the requirement-fit gap feeding back into effort, by
  the escape-cost sub-score, and by Layer 3's sprawl term.

**No target ratio is hardcoded**, because there is no evidence for one and this module does not
ship asserted coefficients without labelling them. Instead the distribution is made visible:
the report carries a portfolio line — *N capabilities built, M adopted, K bought; these story
ids avoided; this many vendors added* — and `architecture-check.py` raises a finding at the
degenerate ends. A finding is not an error. It is a question the report has to answer, which is
the difference between a balance that was reasoned and one that just happened.

#### The operator verifies before the workflow proceeds

**One table, all live capabilities, accepted wholesale or corrected selectively.** Not a queue.
This is `est-scope-extract`'s confirmation-batch rule applied to sourcing, and for the same
stated reason: asking one at a time produces rubber-stamping exactly where accuracy matters
most, and a dozen capabilities asked in sequence is a dozen chances to stop reading.

The workflow **does not proceed to Layer 3 until the table is confirmed**, because the platform
layer's input is the set of capabilities that still need somewhere to run — running it against
unconfirmed sourcing means binding platforms to decisions that are about to change.

Every operator change is a `.memlog.md` `decision` entry naming what changed, from what, to what,
and their reason. Headless takes the recommended sourcing, proceeds, and **reports that it was
unconfirmed** in its return value — never silently.

### Layer 3 — the platform set

**A capability, not a vendor, is the unit.** The architecture is expressed in abstract
capabilities — identity, object store, managed relational store, async work, CDN, edge
protection, secrets, observability, analytics store, email, background scheduling — and a
**platform set** binds each capability that needs somewhere to run to a platform that serves it.

Layer 2 has already decided *what* is bought, adopted or built. Layer 3 decides *from whom*, and
is free to satisfy several bought capabilities with one platform — which is exactly what the
sprawl sub-score rewards. Sourcing says "buy identity"; the platform layer says "Supabase
already serves the database in this set, so it serves identity too: one vendor, not two."

**The candidate space is wide and open.** Not three vendors. The build ships profiles for at
least: AWS, GCP, Azure, Vercel, Netlify, Cloudflare, Supabase, Firebase, Heroku, Render, Fly.io,
Railway, PlanetScale, Neon, Clerk, Auth0, and a self-hosted / on-prem profile. Adding one is a
data file, never code — **if a platform ever needs code, the capability boundary is in the wrong
place**, and that is the test the design has to keep passing.

**A set may combine platforms, and combination has a price.** Frontend on Vercel, auth and
Postgres on Supabase, object store on S3, email on a fourth vendor is an ordinary and often
correct answer. It is also four accounts, four bills, four SLAs, four auth boundaries, four
failure domains and — under a compliance regime — four data-processing agreements.

| Sub-score | Rests on |
| --- | --- |
| **Capability coverage** | Capabilities served natively by the set, against those needing a self-run component or another vendor. Each gap named. |
| **Runtime fit** | Whether the set actually runs the Layer-1 stack and the Layer-2 self-run components: long-running processes, background jobs, websockets, cold starts, execution limits, native dependencies. Checked per component, not per platform. |
| **Vendor sprawl** | Distinct vendors, accounts, bills and DPAs the set creates, and what each additional one buys. The direct analogue of `est-plan`'s refusal to add a person who does not fill their time: a vendor serving one capability another platform in the set already serves is refused, with that stated. |
| **Operational burden** | Components the team runs itself against components a platform runs, and the resulting on-call surface. A count of people-cost, not money — the money is the cost breakdown's job, and the two are kept apart because a managed service that costs more per month and less per week is exactly the trade this sub-score exists to show. |
| **Constraint compliance** | Residency, certifications, the client's own estate. Each pass or fail; any fail makes the set **not viable**. Every platform profile carries its certification and residency fields, researched and **dated**, because these change and a stale claim here is a compliance statement nobody checked. |
| **Reversibility** | Platform-locked services on the critical path, and the capability each would have to be re-bound to. A set built on portable capabilities scores high even when it names specific vendors. |

### Weights, gates and the recommendation

Weights live in `{memory}/architecture-model.json`, seeded from the skill's asset on first run
and never overwritten after — the same convention as `cost-model.json`. Kept out of
`cost-model.json` on purpose: that file is hour coefficients fitted to delivered actuals, and
preference weights are neither fitted nor hours.

The recommendation is the highest-scoring **viable** combination across the three layers. A
non-viable option is still reported with the constraint it broke, so the operator can see what
the constraint cost them.

**If the winning stack is one the company has never shipped**, that is stated in the
recommendation and carried into the handoff, so `est-estimate` prices those stories as `novel`.

## The beats

1. **Read the inventory as an architect.** The drivers are already in the file and mostly unread
   today. Surfaces per epic say which tiers exist. `depends_on` rolled up to epics says where
   the seams are. `implicit_scope` is where the migrations live. `standing_scope.selected` says
   what platform work this project already pays for. `open_questions` and `conflicts` are where
   the design is being asked to absorb an unresolved commercial question, which it must not do
   silently.

2. **Map stories to capabilities.** The join everything downstream rests on: each capability
   names the stories it would implement. This is what gives the sourcing layer its hours and the
   diagram its `serves`, and it is recorded in `architecture.json` so both can be checked
   against it rather than re-derived.

3. **Research what is current.** Fan out one subagent per concern, each using
   **kindly-web-search**, each returning ONLY compact findings with their sources and dates.
   Concerns: the libraries this scope needs and whether they are maintained; a framework's
   current major version; candidate solutions per live capability and their licences; which
   platforms serve a capability in the required region; a platform's certification position.
   Research is for *what is true in 2026*, not for reading the product — the product is in the
   inventory. Every run records **what it checked**, not only what it found: this module has
   shipped a checker that compared nothing and reported no findings, and the habit of stating
   the denominator exists because of it.

4. **Score Layer 1.** Present, with the reasoning behind every sub-score.

5. **Score Layer 2 and stop.** The sourcing table goes to the operator as one batch. **Nothing
   proceeds until it is confirmed or corrected.**

6. **Score Layer 3 against the confirmed sourcing.** Present.

7. **Bind, lay out, render.** One diagram, of the decision actually taken.

8. **Price it.** Fan out one research subagent per vendor, build the cost table, re-verify it,
   and report what could not be priced.

## The diagram is required

Not optional, not skipped with a note, not degraded to a text fallback. `est-setup`'s job is to
prepare everything the module needs, and the renderer is part of everything.

- **`est-setup` provisions and verifies it**: Node ≥22.12, a Chromium-family browser, and the
  pinned `@eraserlabs/diagrams-cli`. It renders a fixture and checks the bytes come back. A
  setup that reports success while the renderer is absent has moved the failure to the first
  client deliverable.
- **`est-architect` refuses to start without it**, naming `/est-setup` — the same idiom as
  `est-plan` refusing an unpriced scope and `estimate.py` refusing an inventory with unresolved
  findings.
- **`architecture.png` is a `required` output** in `module-outputs.yaml`, so `check-outputs.py`
  reports its absence after a clean run.
- **A failed render fails the run.** Non-zero exit, the render report kept so it can be argued
  with — the shape `plan.py` already uses when its ordering audit fails.
- Mermaid stays in `architecture.md` as a **text form of the same graph**, for diffing and for
  reading in a terminal. It is no longer a fallback, because there is nothing to fall back from.

The consequence, stated plainly: **`eraser-diagrams` is load-bearing.** A six-week-old 0.2.0
package closed to outside contribution is a heavier bet when the run fails without it. Pinning
the exact version, vendoring the icon set, and keeping the renderer behind an adapter stop being
nice-to-haves and become build requirements.

### The diagram is also a buy/build map

Layer 2 gives the drawing something the other layers cannot: **a reader can see at a glance what
the team writes and what it rents.** Built components, adopted-and-self-run components and
bought services are visually distinct — eraser's first-class `Badge` carries the mode, third-party
services sit in their own band, and a `Legend` says what the grammar means. That is the single
most useful thing an infrastructure diagram can tell a client who is about to fund it, and it
falls out of a decision the workflow is making anyway.

### Layout

**Deterministic and computed in Python**, not placed by a model: tiers become columns (actors →
edge → application → services → data → external), **each platform in the set becomes its own
titled boundary band** — a multi-platform set draws multiple boundaries, which is the honest
picture of what it is — components become icon nodes on a grid inside their band, and
connections carry their labels. Reproducible run to run, which matters because this module's
artefacts get diffed and re-read months later. A model hand-placing forty nodes at pixel
coordinates is the version I would refuse.

Colours come from `est-estimate/scripts/brand.py`, so the diagram and the workbook are one
visual identity rather than two.

---

## Diagram tooling — research and recommendation

**Do not hand-roll a renderer** was the brief, and the research turned up a better answer than
expected.

### The finding

**Eraser open-sourced their renderer.** `eraser-diagrams` (`@eraserlabs/diagrams`,
`@eraserlabs/diagrams-cli`) is MIT-licensed on npm and GitHub — the data schema, rendering
engine, line routing, icon adapter and exporters. Not included: the GUI editor, the AI prompts
and the hosted product.

So "what open-source tool best reproduces Eraser's output quality and look" has a literal
answer: **Eraser's own renderer**. Not an approximation of the bar — the bar itself.

Verified against the npm registry rather than the marketing page: MIT, `0.2.0` published
2026-09-26, first release 2026-08-19, signed with SLSA provenance, published from CI.

### Candidates

| Tool | License | Score | Pros | Cons |
| --- | --- | --- | --- | --- |
| **eraser-diagrams** | MIT | **9/10** | It *is* the reference bar. JSON in → PNG / self-contained HTML / **measured JSON** out. Obstacle-aware orthogonal routing, first-class `Group` containment — which is what makes multi-platform boundary bands drawable — `Badge` and `Legend` tags, which is what makes the buy/build map drawable, icons by name (`aws-lambda`, `postgres`, `kubernetes`) against a hosted catalogue, rich text in nodes. Custom component library, own icon base URL, own fonts: fully brandable. The measured-JSON round-trip means a render can be **checked**, which is this module's habit. `--fail-on-warning` catches a misspelt icon. | **No layout engine** — every entity needs authored `x`/`y` (only routing is automatic). **Node ≥22.12 and a Chromium**, where every other script here is stdlib Python under `uv`. Network at render time for icons and fonts unless cached. **Six weeks old at 0.2.0**, and explicitly *"not open to contribution"*. |
| **D2** | MPL-2.0 | 7/10 | Single Go binary, no runtime. Genuinely automatic layout (dagre / ELK). `d2 in.d2 out.png\|svg\|pdf\|pptx`. Containers, hosted icons, designer themes. Mature and widely used. | The output is D2's look and does not reach the reference composition — icon-first nodes, tinted group bands with title chips, tight orthogonal routing with mid-line labels. The renderer owns composition: right for a wiki, wrong for a client deliverable. |
| **mingrammer/diagrams** | MIT | 6/10 | **Python**, this module's language. Official AWS / Azure / GCP / K8s icon sets — closest candidate on iconography. Clusters. | Graphviz layout gives the unmistakable "diagrams look": loose spacing, weak edge labels, no titled group bands, no rich text in a node. Needs the Graphviz binary. Closest on icons, furthest on composition. |
| **draw.io XML** | Apache-2.0 | 5/10 | The one output a solution architect can open and tweak afterwards. Mature AWS shape libraries. | Verbose and error-prone to generate; the format was designed as an editor's internal detail. Export needs the desktop app or its CLI. |
| **PlantUML + AWS icons / C4-PlantUML** | GPL / MIT icons | 4/10 | Very mature, large AWS icon set, C4 conventions built in. | Dated visual output, Java runtime, layout control is a fight. |
| **Mermaid** (`architecture-beta`) | MIT | 3/10 | Free, everywhere, renders natively in GitHub and in this module's markdown with no toolchain. | `architecture-beta` is immature and visually nowhere near the bar. Kept as the text form of the graph, not as the deliverable. |
| **Excalidraw (programmatic)** | MIT | 3/10 | Hand-drawn charm, scene JSON is writable. | No layout, no icon set, no containment semantics. Wrong tool for infrastructure. |

### Recommendation

**`eraser-diagrams`, with a deterministic Python layout pass in front of it.**

Its one real weakness — no layout engine — is the weakness that matters least here, because the
layout is the part this workflow should own anyway. The reference diagram's quality *is* its
composition: bands, tiers, deliberate grouping. Computing that from the component graph gives a
reproducible diagram; handing the job to a layout engine gives a D2 diagram.

Mitigations, each now a **build requirement** rather than a nice-to-have, because the diagram is
required:

- **Pin the exact version.** Re-check the package's state immediately before the build starts.
- **Keep `architecture.json` renderer-agnostic.** The eraser document is *generated from* it by
  an adapter. If the bet goes wrong, D2 is a second adapter, not a rewrite. Same separation as
  capability-then-platform, applied to the renderer.
- **Vendor the icons used** and cache to disk (`icons.cacheDir`). A required output that depends
  on a vendor's bucket being reachable is not a required output.
- **`est-setup` renders a fixture** and compares the result, so the dependency is proven at
  install time rather than discovered at delivery time.

---

## The run-cost breakdown

The last artefact: what the chosen architecture costs to operate. One row per service, naming
the concrete provider and tier.

**The rule is the module's founding rule, moved into a new domain.** Every hour in an estimate
traces to a quote in a client document. Every figure in this table traces to a quote from a
vendor's pricing page — the price, the tier's own wording, the URL, and the date it was fetched.
A price recalled from memory is the exact analogue of invented scope, and it is worse in one
respect: scope invented from a document can be argued with, while a wrong AWS figure looks
identical to a right one.

This reverses a position taken twice in earlier revisions of this plan — that the workflow would
report operational *burden* as a count and never a monthly figure, because "inventing a dollar
figure would be the first unsourced number the module has ever shipped." That objection was to
**inventing** the figure, not to reporting it. With every number fetched and re-verifiable the
objection dissolves, and the refusal was over-broad. The burden count stays, for a different
reason now: a managed service that costs more per month and less per week is precisely the trade
a reader needs both numbers to see.

### The format

The three columns from the example, in that order, with four extensions to the right — so a
reader who wants only `Item | Cost | Type` reads the first three and stops.

| Item | Cost | Type | Assumption | Free until | Source | Checked |
| --- | --- | --- | --- | --- | --- | --- |
| Managed Postgres — AWS RDS `db.t4g.micro`, Single-AZ, eu-west-1 | *fetched* | monthly | 1 instance, 20 GB gp3 | — | *pricing URL* | *date* |
| Auth — AWS Cognito, free tier | 0 | monthly | 25 MAU | **50,000 MAU** | *pricing URL* | *date* |
| Domain — `.com` | *fetched* | annually | 1 domain | — | *registrar URL* | *date* |

Totals per type at the bottom, exactly as in the example, plus one addition.

### What I propose changing, and why

**1. A `Source` column — essential, not optional.** The brief says every number must come from
actual research. The format as given has nowhere to record that, which means the constraint
cannot be checked by anyone afterwards, including the next run. A rule nobody can verify is a
rule that degrades on the first busy day. This is the same reasoning that put a verbatim `quote`
on every feature in the inventory.

**2. An `Assumption` column.** The example smuggles assumptions into the item text —
*"Stripe processing fees — 25 MVP users"*, *"Claude Sonnet API usage — MVP cap"* — which works
for a human and is unparseable for anything else. Its own column makes every usage-driven row
uniform, lets `cost-check.py` recompute `cost` from `rate × quantity`, and makes the whole table
re-runnable against a different assumption: *"what does this cost at 500 users"* becomes one
number changed rather than a rewrite.

**3. A `Free until` column — the most valuable addition.** Four rows in the example read `0` for
four completely different reasons: Cognito is free *at this volume*, SSL via ACM is free
*permanently*, the Corsano API is free *by assumption*, and cloud credits are not a cost at all.
A reader cannot tell them apart, and the dangerous one is invisible: Cognito at 25 users is 0 and
at 50,001 MAU is not, and nothing on the row says where the cliff is. Every free or discounted
row carries the threshold that ends it.

**4. A `TOTAL — Year 1` row**, under the three per-type totals: one-time + (12 × monthly) +
annually. The example's totals are correct and none of them is the number anyone actually asks
for. It is arithmetic on rows already present, so it costs nothing and it is what gets quoted.

**5. Cloud credits come out of the table.** *"Cloud credits — GCP/AWS/Azure startup programs,
~$1k–$5k available"* at `0` is three category errors in one row: it is an offset rather than a
cost, it is a range rather than a figure, and *available* is not *granted*. It belongs in a note
under the table — "credits may offset year one; not secured, not netted into any total" — where
it informs without quietly making a total wrong.

**6. Usage-driven rows carry a range.** The module's iron rule is that nothing is reported as a
point value, and here the reason is plain: a subscription is a contract and a point estimate is
honest, while Stripe fees, LLM API spend and CloudWatch ingest are whatever the month does.
Fixed rows stay points; usage-driven rows carry low / likely / high in adjacent columns, and the
totals carry the band. A single number for LLM usage is a forecast wearing a price tag.

**7. A `Payer` field in `costs.json`.** Layer 2 already asks who holds a subscription after
handover; the answer belongs against each row. Rendered only when the answers differ, so the
common case stays three columns wide.

### How the numbers are actually obtained

**Fan out one subagent per vendor, not per row** — a vendor's pricing page usually covers several
capabilities, and one fetch answers them together. Each is given the capabilities to price and
the usage assumptions, uses **kindly-web-search** and `get_content`, and returns ONLY structured
rows: `{capability, service, tier, rate, unit, currency, quote, url, fetched_at}`. The `quote` is
verbatim from the page, the way an extraction beat quotes a client document.

**`cost-check.py` re-fetches and re-verifies**, exactly as `inventory-check.py` re-opens sources
and checks every quote against the document it cites. Specifically:

- The quoted price string still appears on the cited page. **This is what makes "nothing
  invented" mechanical rather than aspirational**, and it is the single guard worth the most.
- `cost` recomputes from `rate × quantity` under the stated assumption — restating a figure is
  not the same as deriving one, and the module's rule is that arithmetic is never done by hand.
- Totals recompute per type, and Year 1 from them.
- Every priced capability in `architecture.json` has a row, and every row maps to a capability.
  Two-way, like the inventory's two-way traceability: a service nobody's architecture needs is
  as wrong as a capability nobody priced.
- `fetched_at` older than a configured age is a finding. Prices move.

**A price that cannot be fetched is recorded as `unpriced`, never guessed.** Pricing pages are
increasingly JavaScript-rendered, region-gated, or behind *contact sales*. This is the
`needs_native_read` case from est-scope-extract: the row appears in the table with its reason,
the totals say how many rows are unpriced, and nobody reads a total as complete when it is not.
**This is the point in the whole workflow where fabrication is most likely**, because a model
that has read a thousand AWS pricing pages will produce a plausible number faster than it will
admit it could not reach the page.

For AWS specifically, the published Price List API is a better source than scraping a page, and
the same row shape accepts it — the `url` becomes the API query. Worth using where a vendor
offers one.

**Every assumption has a basis.** *"25 MVP users"* is itself a number that can be invented. Each
assumption is cited to the inventory where a story states it, recorded as an operator answer
where they gave one, or defaulted and logged in `.memlog.md`. An assumption with no basis is the
cost table's version of a feature with no citation.

### Where it lives, and what it must never be added to

`costs.json` is the source of truth, carrying rate, quantity, formula, original currency, FX rate
and date, the verbatim quote, the URL and the fetch date. `cost-breakdown.csv` and the markdown
table in `architecture.md` are rendered from it.

**`est-estimate` gains a `Costs` tab** in the workbook it already builds, rendered from
`costs.json` when one exists. No second workbook — the module's standing rule — and the ordering
works because est-architect runs first and leaves the file for the workbook that comes later.

**Run-cost and delivery cost are never summed, and never rendered adjacent without a label.**
The estimate is hours; this is dollars per month, and it continues after the project ends.
Somebody will otherwise add twelve months of run-cost to a project quote. This is the same
standing rule that keeps agreed and additional scope from being merged into one figure, and it
belongs in the SKILL's gotchas in the same words.

## Contract

### Handoff to est-estimate

`architecture.json` carries a per-story **sourcing note**: this story integrates a bought
service, this one builds against an adopted library, this one is written from scratch. The
classification beat in `est-estimate` reads it as evidence.

**It is evidence, not a verdict.** `est-scope-extract` owns the inventory and `est-estimate`
owns classification; `est-architect` writes to neither. It says "this story now integrates a
managed identity provider"; the classifier still decides the band. Overstepping that would put
three skills in the business of deciding what a story costs, which is the split the module was
restructured to create.

### Outputs (to be declared in `est-setup/assets/module-outputs.yaml`)

```yaml
est-architect:
  workspace: "{est_output_folder}/{project-slug}"
  required:
    - path: architecture.json     # source of truth: three scored layers with their bases, the
                                  # capability→story map, the chosen stack, sourcing and
                                  # platform set, components with `serves` and sourcing mode
    - path: architecture.md       # the document a human reads
    - path: architecture.png      # the infrastructure diagram — required, not optional
    - path: diagram.json          # the eraser document, kept so a render is reproducible
    - path: costs.json            # every row with its rate, assumption, quote, URL and fetch date
  optional:
    - path: cost-breakdown.csv    # when csv is in est_output_formats
    - path: architecture.html     # when html is in est_output_formats
    - path: sourcing-batch.md     # the confirmation table, when an interactive run produced one
    - path: architecture-check.json
    - path: "research/{concern}.json"   # when a research subagent wrote rather than returned
```

`.memlog.md` gains `assumption` and `decision` entries; nothing else is written. It does **not**
touch `feature-inventory.json`, `classification.json`, `estimate.json`, `estimate.xlsx` or
`plan.json`.

### Files to build

```
skills/est-architect/
  SKILL.md
  references/
    capability-catalogue.md    # the abstract capabilities and what each is for
    stack-options.md           # how to build genuinely different stack options, and score them
    sourcing.md                # build vs adopt vs buy: what makes a decision live, how each
                               # sub-score is evidenced, and the confirmation batch
    platform-binding.md        # capability → platform → service → icon; how to add a platform
    costing.md                 # the row shape, the research protocol, what `unpriced` means
    diagramming.md             # the layout contract, the buy/build grammar, the eraser document
    headless.md
  assets/
    architecture-model.seed.json   # sub-score weights (three layers), capabilities, gates
    architecture.schema.json
    platforms/                     # one data file each, no code
      aws.yaml gcp.yaml azure.yaml
      vercel.yaml netlify.yaml cloudflare.yaml
      supabase.yaml firebase.yaml
      heroku.yaml render.yaml fly.yaml railway.yaml
      planetscale.yaml neon.yaml clerk.yaml auth0.yaml
      self-hosted.yaml
  scripts/
    architect.py               # inventory + inputs → three scored layers → architecture.json
    sourcing.py                # capability→story map, liveness test, effort deltas
    layout.py                  # component graph → positioned diagram document
    render-diagram.py          # → eraser JSON → PNG/HTML; non-zero exit on failure
    price.py                   # vendor research → costs.json; recomputes every total
    cost-check.py              # re-fetches each cited page and re-verifies the quoted price
    render-architecture.py     # → architecture.md, including the cost table
    architecture-check.py      # traceability, viability, sprawl and balance audit
    tests/
  evals/
    run-cases.py
```

### Registration

- `est-setup/assets/module-help.csv` — one row, menu code **`AD`** (`AR` is taken by Accuracy
  Report), `preceded-by: est-scope-extract:create`, `followed-by: est-estimate:estimate`.
- `est-setup/assets/module.yaml` — three config variables, plus the renderer in the post-install
  checks.
- **`est-setup/SKILL.md` gains the renderer provisioning step** and its fixture render. The
  largest change outside the new skill.
- `est-estimate/SKILL.md` — the stack input reads `architecture.json` when present rather than
  being guessed, and the classification beat reads the sourcing notes as evidence.
- `est-estimate/scripts/render-estimate.py` — a `Costs` tab when `costs.json` exists, and the
  gotcha that run-cost is never added to delivery hours.

### Naming

`est-architect`, invoked as `/est-architect`. A **workflow**, not an agent — the module's only
agent is Nadia, and nothing here needs a persona or a conversation that survives invocations.

## Configuration

| Variable | Prompt | Default |
| --- | --- | --- |
| `est_house_platform` | Platforms the company already runs, as a tiebreak weight (comma-separated, blank = no preference) | `aws` |
| `est_diagram_renderer` | Renderer for infrastructure diagrams | `eraser` |
| `est_chromium_path` | Chromium executable (blank = auto-detect) | `""` |

## External dependencies

| Dependency | Needed by | Handling |
| --- | --- | --- |
| Node ≥22.12 + pinned `@eraserlabs/diagrams-cli` | the diagram — **required** | `est-setup` installs, pins and proves it with a fixture render. `est-architect` refuses to run without it and names `/est-setup`. |
| A Chromium-family browser | the diagram — **required** | Auto-detected; `est_chromium_path` pins it. Verified by the same fixture render. |
| `kindly-web-search` MCP | research, **the sourcing layer, and every figure in the cost breakdown** | Absent → the run proceeds on the inventory and the model's own knowledge, and **the report states that no external research was done** and which sub-scores are therefore unsourced. Maintenance health and licence class are the ones that degrade hardest, and a sourcing recommendation resting on recalled library facts must say so. |

## Memory

`{memory}/architecture-model.json` — seeded from the asset on first run, never overwritten after.
Sub-score weights for all three layers, the capability catalogue, the viability gates.

`{memory}/architecture-preferences.md` — seeded with every section `UNANSWERED`, the same
convention as `company-profile.md`. What this company has delivered in, which platforms and
third-party services it already holds accounts, licences and certifications for, what it will
not run, what it will not buy, and which platforms are house. **This is what makes the team-fit
and cost sub-scores real**, and until it is answered they report `null` rather than a number — a
marker that is honest rather than a default that looks like a measurement.

Sourcing decisions accumulate here too: a component this company adopted before, and how it went,
is the closest thing the module will have to evidence on this layer.

## Risks

1. **Judgement with no citation.** The module's first artefact with no client quote behind it,
   and the most persuasive one it produces. The `serves` rule and `architecture-check.py` are
   the whole answer; without them, do not build this.
2. **`eraser-diagrams` is load-bearing.** Six weeks old, 0.2.0, closed to contribution, and the
   run fails without it. The adapter boundary, the exact pin, the vendored icons and the
   setup-time fixture render are what make that acceptable. Re-check the package before the
   build starts.
3. **Sourcing changing the scope by accident.** The most dangerous failure in this revision: an
   architecture workflow that "buys auth" and quietly drops the auth stories has re-priced the
   deal without telling anyone. The rule is that scope is fixed and classification moves, and
   `architecture-check.py` verifies the capability→story map still covers every story it
   covered before.
4. **Platform sprawl and vendor sprawl.** The consequence of opening both the platform space and
   the buy option. The sprawl sub-score, the vendor-refusal rule and the portfolio balance
   finding are the answer; without them this workflow will confidently propose architectures
   with nine bills.
5. **Stale third-party facts.** Certifications, regions, licences, pricing models and library
   maintenance all change. Every profile and every sourcing finding is dated, and
   `architecture-check.py` warns when a dated fact backing a *gating* decision is older than a
   stated age. A licence claim nobody re-checked is worse than none.
6. **Scoring theatre**, on any of three layers now. Answered by requiring each option to name
   its structural axis, by allowing fewer than three, and by the liveness test that keeps
   settled capabilities out of the tables entirely.
7. **Recommending an unfamiliar stack and pricing it as familiar.** The `novelty` coupling is
   the fix, and it only works if the handoff carries it.
8. **A fabricated price is the worst failure available here.** A model that has read a thousand
   AWS pricing pages will produce a confident, plausible, wrong number faster than it will admit
   it could not reach the page. Re-verification, `unpriced` rows and the fetch-date staleness
   check exist for this one risk; if only one guard from this revision gets built, build
   `cost-check.py`.
9. **Run-cost mistaken for delivery cost.** The table is dollars per month; the estimate is
   hours. Someone will add twelve months of run-cost to a project quote. They are never summed,
   never rendered adjacent without a label, and the report says so in its first line.

## Build roadmap

1. `architecture.schema.json`, the capability catalogue, the **capability→story map**, and
   **three platform profiles chosen to stress the shape** — AWS (IaaS), Vercel (PaaS) and
   Supabase (BaaS). The map comes first because both later layers rest on it.
2. `sourcing.py` and Layer 2 — the liveness test, the effort deltas, the confirmation batch.
   Built before Layer 3, because Layer 3 consumes its output, and before the diagram, because
   the buy/build grammar is a rendering requirement.
3. `architect.py` with all three scored layers, the viability gates, the sprawl and balance
   terms, plus `architecture-check.py`. At this point the workflow is useful with no diagram.
4. `est-setup` renderer provisioning and its fixture render — **before** the renderer is used in
   anger, because everything after this depends on it.
5. `layout.py` + `render-diagram.py`, proven against a reproduction of the attached reference,
   including the multi-platform boundary case and the buy/build grammar.
6. `price.py` and `cost-check.py`, with the re-verification pass built before the first table
   is rendered — a cost table that cannot be re-checked should never exist even once.
7. `render-architecture.py`, `SKILL.md`, the references, the tests and the evals.
8. The remaining platform profiles, the `est-estimate` handoff and its `Costs` tab.

## Ideas captured, not planned

- A second diagram at C4 container level, alongside the infrastructure one.
- Emitting a Terraform or Pulumi skeleton from the bound platform set.
- Feeding the chosen architecture into `est-plan` so an epic crossing a service boundary is a
  visible seam when a second developer is proposed.
- Re-binding an existing `architecture.json` to a different platform set as a first-class intent
  (`/est-architect rebind --platform azure`).
- **A cost sub-score in Layer 3**, once enough `costs.json` files exist to make a priced
  catalogue. Deliberately not in this revision: costing the chosen set is a few vendor lookups,
  costing every candidate set is that times the number of candidates, and the research budget is
  better spent verifying one set properly than half-verifying five.
- Feeding delivered projects back: `est-calibrate` already reconciles estimates against actuals,
  and an adopted component that cost three times its estimated integration is the first real
  evidence this layer could ever have.
