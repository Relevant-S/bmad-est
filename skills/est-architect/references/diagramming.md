# Diagramming

The diagram is a **required output**. Not optional, not skipped with a note, not degraded to a
text fallback: `est-setup`'s job is to prepare everything the module needs and the renderer is
part of everything. A run that quietly produced no diagram would move the failure to the first
artefact a client sees.

## The pipeline

Five stages, each checkable on its own. The version before this one went from `architecture.json`
straight to pixel coordinates, which meant two different mistakes were invisible in the same
place: a graph that was not true, and a composition that was not designed.

```
architecture.json → graph.py → elk.mjs → layout.py → render.mjs → diagram-check.py
   the decision      WHAT        WHERE     the document   the picture    did it hold
```

- **`graph.py`** — zones, groups, nodes and edges, with no geometry, validated against section A
  of the design contract before anything is placed.
- **`elk.mjs`** — ELK (`elkjs`, pinned) decides every coordinate and routes every edge. Language
  models are bad at geometry, and so was the box model this replaced.
- **`layout.py`** — the adapter: it sizes a cell, snaps to the 8px grid, simplifies routes and
  writes the renderer's document.
- **`render.mjs`** — the renderer's library, with our design tokens injected.
- **`diagram-check.py`** — H1 to H10 against the geometry the browser actually produced.

## The graph has to be true first

Edges used to be derived from **tiers**: every component in the application tier was joined to
every component in `services`, `data` and `external`. `web_client` lives in that tier, so the
browser was given authored edges to a secrets manager, a relational store, a payment vendor and
an SMS service. Roughly half of a real project's twenty-five connections were false.

It was invisible because the diagram aggregated every edge to its tier group before drawing it —
twenty-five collapsed to six, and six plausible arrows is what anybody looking at the picture saw.

So the catalogue declares the graph, as data:

- **`reaches`** — the capabilities this one talks to. An edge is drawn to every one the
  architecture actually contains.
- **`reaches_first`** — one edge, to the first that is present. This is what keeps the request
  path a path when an optional hop like a CDN is not in the set.
- **`edge_label`** — the verb-and-object phrase for an edge arriving **here**. Taken from the
  target, so a label says what flows rather than that something flows, and two edges cannot share
  one without sharing a destination. `uses`, `calls` twice and `admits` were the four string
  literals this replaced.

An actor reaches the **front** of the system — the first of edge protection, CDN, web client,
application that exists — and never the identity provider. A capability research added carries
none of these fields: it is reached from the application rather than left floating, labelled
after itself, and the edge is marked `defaulted` so the default is visible as one.

Several arrows converging on one box carry **one label between them**. That is what keeps D7's
"unique in the diagram" honest: a label may not mean two different things, but one meaning does
not need writing out once per arrowhead.

## ELK owns the geometry

`@eraserlabs/layout` routes connections and says so plainly in its own README — *"treats entity
placement as input"*. Nothing in the renderer decides where a box goes. `elkjs` 0.12.0 does,
under the option block the design contract specifies, and this module adds three things it does
not do on its own.

**Flattening.** ELK reports every child relative to its parent and every edge section relative to
the node that contains the edge. The renderer wants absolute scene coordinates. Getting this
wrong is invisible on a flat graph and catastrophic on a nested one.

**Shape.** B5 wants an aspect ratio between 1.6 and 2.8 and a flow that wraps into a second row
when it would otherwise run too wide — that is `elk.layered.wrapping.strategy` with
`elk.aspectRatio`. Two things had to be learned the hard way. The loop must keep the **best**
attempt rather than the last, or it oscillates between 2.9 and 1.2 and keeps whichever came last.
And a wrap is **refused** when it leaves an edge longer than the scene it was meant to compact:
folding moves whole zones, and on one architecture it traded an aspect of 2.9 for two arrows
running the full width of the canvas and back, which is a worse picture by the standard the rule
exists to serve.

**The two ends of the reading order.** Layering follows the edges and a group is placed as one
column, so a group holding both the first thing a request meets and something the application
calls back to is dragged to the later of the two. On a real architecture that put the WAF — the
very first hop — to the right of the API, because Amazon Cognito shares its group and is reached
from the browser and the backend both. `elk.layered.layering.layerConstraint` fixes the two ends
the contract names explicitly: actors in a column of their own ahead of everything, entry in the
first layer proper, third parties in the last. What happens between them stays the engine's
decision. `elk.partitioning` is the obvious alternative and is **inert in the pinned build** —
verified against it rather than assumed.

## Routes are authored, and the renderer keeps them

An authored polyline that is **strictly orthogonal** and clears every non-endpoint, non-container
box is adopted by the renderer verbatim and never routed (`render/dist/browser/route.js`).
Anything else it discards and re-routes itself, silently.

Two consequences. The eighty seconds that obstacle-aware routing of twenty-one edges used to cost
— the reason edges were aggregated to their groups in the first place — **disappears**, because a
pinned edge never reaches the router. And "the renderer drew what we authored" becomes a check:
`diagram-check.py` compares authored points to measured points, and a difference is a finding.

Three things had to be got right for adoption to hold:

- **Strict orthogonality after snapping.** ELK emits a vertical segment as `x=982.0` and
  `x=982.4`. Snapped independently those land on different grid lines, and six routes were thrown
  away without a word. The orientation is decided from the geometry *before* snapping and the
  shared coordinate is copied rather than rounded twice.
- **Simplification, proved.** ELK leaves 2px and 9px steps behind that nobody can see and that D1
  counts as bends — one route from an API to a payment vendor had eleven points and three visible
  corners. Collinear runs, duplicates and short jogs are removed, and **every straightening is
  tested against every obstacle before it is kept**: a first version moved six routes into boxes,
  which the renderer then rejected, turning a tidy-up into a layout nobody authored.
- **Cutting out-and-backs.** A route that leaves a node rightwards, runs 320px further right,
  steps up and then runs 776px back to the left has spent four bends going nowhere. It is what a
  layered router does with a back edge — a browser redirecting to an identity provider in the
  first column — and it reads as a mistake because it is one. Cutting the excursion took that
  edge from six bends to one.

## What the checks can and cannot promise

`diagram-check.py` runs H1 to H10 over the measured document and states its denominator. Severity
is the difference between "the picture could be better" and "the picture is wrong".

| Check | Verdict |
| --- | --- |
| **H1** a connector over a box that is not its endpoint or their container | **fails the run** |
| **H2** edge crossings | one per ten edges is tolerated and drawn with a hop; beyond that, **fails** |
| **H3** a label over an icon | **fails** |
| **H4** bends | four is **reported**, five **fails**; a short final segment **fails** |
| **H5/H6** a wrapper container, a duplicate name | **fails** |
| **H8** a placeholder icon or a bare shape | **fails** |
| **H7/H9/H10** an oversized container, an unaligned row, the aspect ratio | **reported** |

Two of these are properties of the graph rather than settings, and saying so is the point.

**H2 cannot be zero in general.** Whenever two components reach the same two others — an API and
its worker both writing to a relational store and an object store — those four edges form a
K(2,2), which cannot be drawn in two layers without a crossing. One real architecture has two
such pairs, so its floor is two, and six different ELK strategies all return exactly two. A
constant budget of one would mean a required output that some real architectures can never
produce, so the budget scales with the graph and the report always states the number.

**H4's three bends are not always reachable.** A hub node reaching a column with another column
in between must leave, pass the intervening column above or below, turn into the gap beyond it,
and turn again into its target. That is four, and the alternative is crossing a box, which D2
forbids outright. So a fourth bend is reported with a count and a fifth fails.

**H7 counts a corridor as content.** The check exists because half a cloud boundary was empty. It
is not there to complain about the lane an orthogonal router needs, and counting that as waste
made it fire on the first layout that had stopped wasting anything.

Step 5's retry is real rather than promised: the layout runs up to five ELK strategies and keeps
the best by (nothing broken, then shape, then note count). The checks that decide it are
computable from the **authored** document, so an iteration costs an ELK call rather than a browser
boot. What changes between iterations is what ELK is asked, never what it answered — there is no
hand-drawn workaround edge anywhere in this module.

## The design system

Sections E, F and G are a complete visual system, and the renderer turns out to be able to express
all of it — it had simply never been asked. `createRenderer` takes `library` (whose `baseCss` is
injected raw and unlinted), `overrides` and `fonts`.

**An authored prop beats a stylesheet.** Fill, border colour, border width, corner radius, style
mode, the title chip's background and border, font size and label colour are all real props on the
renderer's own schema, so they are authored per entity and survive an upgrade. `scripts/theme.py`
generates them from `est-estimate/assets/brand.json`, so the diagram, the workbook and the HTML
reports stay one visual identity rather than three palettes that drift.

CSS is used only where the renderer hardcodes a value with no prop behind it: title weight,
letter-spacing and case (all fixed at 400 / -0.01em / none), the shadow (`4px 4px 0 0 #e8e8e8`),
and the icon caption. Those rules carry `!important` because per-template CSS is injected after
`baseCss` inside an `@scope` block and would otherwise win.

**The caption is the one that mattered.** Stock CSS pins it to `position:absolute;
width:max-content; max-width:180%` of the figure — and with no authored bounds the figure *is* the
50px glyph, so labels wrapped at **1.8 x 50 = 90px**, which is the number in the defect report.
Worse, stock switches to `white-space:nowrap` the moment there are two caption lines, so a
name-and-role label would never have wrapped at all.

The face is the brand's own where the reader has it and Arial where they do not, which is the same
decision `brand.json` records for the HTML reports: PP Mori is licensed and cannot be embedded in
something handed to a client. The consequence is that two machines can produce different PNGs, so
the render report carries `degradedFonts` and names the face actually used rather than implying
the output is machine-independent.

## A runtime is a badge

A thing the team writes and the thing that runs it are **two items**, and "Django on Fargate" was
one box carrying both names with an icon that was a coin toss between them. Drawing the runtime as
a **container** fixed that and cost four levels of nesting, a redundant wrapper, and the name
`AWS Fargate` on the canvas twice.

So the software's own logo fills the node at 40px and the runtime's official icon rides in the
corner as an `Icon.badge`. Two products, two official icons, one node, one name. The split is
still a field and not a parse: the framework comes from the stack layer and the runtime from
`serves.<capability>.runtime` in the platform profile, which exists because `service` is sometimes
a *choice* — AWS answers `application` with *"AWS App Runner, ECS Fargate or Lambda"* — and a
choice is not something code can be drawn inside.

## Icons are resolved, never bundled

There are **2,693 official cloud-service SVGs alone** and the vendors revise them quarterly, so a
copy vendored into this repository is stale the day it lands. `scripts/icons.py` looks each one up
when a diagram needs it and writes it into the renderer's icon cache.

| Rank | Source | What it is for |
| --- | --- | --- |
| 100 | **The vendors' own architecture icons** (AWS, Azure, GCP via `tf2d2/icons`) | The only source with art for an individual cloud SERVICE rather than a corporate logo. |
| 90 | **SVGL** | A curated, full-colour catalogue of product logos, icon-only variants included. |
| 80 | **Iconify** | The long tail — but only its brand catalogues; see below. |

**The ranking is explicit because search cannot be trusted**, and every rule below was written
after a specific wrong picture:

- **Only a named product is ever looked up.** Searching *"Identity and access"* found **Ping
  Identity's** logo and *"Model inference"* found **Model Context Protocol's**.
- **An allow list, not a deny list.** Iconify indexes 300,000 icons across 200+ sets and only a
  handful are brand catalogues. Denying the ones that had embarrassed us was whack-a-mole —
  `mdi:railway` for Railway, then `bytesize:end` for *"AWS End User Messaging SMS"* — and each new
  one was found by somebody looking at a finished diagram.
- **A category icon is never a service icon.** `aws/category/64/End-User-Computing.svg` is a
  section header in AWS's own deck; it answered *"AWS End User Messaging SMS"* on the shared words
  `end` and `user` and drew a virtual-desktop glyph on a messaging box. AWS publishes no icon for
  that service, and the honest answer is the capability glyph.
- **The head word has to match.** Without it *"Stripe Connect Express + Stripe Billing"* won AWS's
  `Amazon-Connect.svg` at 118 against a floor of 110.
- **Narrowing goes to the head, never the tail**, and a head that is a common noun — `object`,
  `secrets`, `machines`, `end` — narrows to nothing at all.
- **Colour and shape are measured, not assumed.** `simple-icons:celery` and `thesvg-color:celery`
  are the same drawing and only one is green; `logos:supabase` is 512x99 and renders as a sliver.

**Colour belongs to a vendor's own artwork.** Everything else — a capability nobody bought, an
actor, a product with no published mark — is one outline set in one ink (F1/F2). The test is
whether the resolver found **official art**, not whether it returned a name: an unresolved product
still gets one, its capability's glyph, and keying on the name counted three grey glyphs as vendor
logos. The outline set is the one the renderer ships, deliberately: the fallback path has to work
with no network, and fetching a second icon set would put a network dependency on the branch that
exists for when there isn't one.

**A test must never write into the shipped cache.** A stubbed resolver that did put a green square
in `aws-simple-email-service.svg` and a row for it in the audit manifest — and that square was
drawn on a client's diagram. That is the "placeholder visuals" defect, authored by this
repository's own test suite. `render()` takes an `icon_cache` and the suite passes a temporary one.

Every resolution is recorded in `assets/icons.resolved.json` with its source, id, URL, licence,
measured aspect, measured colour and the date. **Offline, every component falls back to its
capability glyph**: the diagram is a required output and still renders.

## What the diagram does not say

There are no **built / adopted / bought** badges and no legend. Whether a component is written or
rented is a sourcing decision with a scored table and a gate of its own; stamping it on the artwork
gave every node a second label and cost the diagram a corner to a key nobody needed. It is in
`architecture.md`, in the sourcing gate and in `architecture.json`.

Composite labels are left alone. *ACM TLS + Shield* and *Stripe Connect Express + Stripe Billing*
each keep one node with the head product's official icon and the full label, because splitting free
text would invent structure the profiles do not carry — and an `or` list is a choice rather than a
composition. Such a name is the one place G7's third line is spent; the cell grows to fit the
longest label on that canvas and every cell then takes that size, so C8 still holds.

## Provenance

`architecture.json` and the render report carry `produced_by`: a short content hash over this
installation's scripts and data. A project installs the module by copy, and one real run was
reviewed for a day against the repository's behaviour before anyone noticed it had executed a copy
three weeks old. Compare it against `capabilities.py --revision` before reading anything into an
output.
