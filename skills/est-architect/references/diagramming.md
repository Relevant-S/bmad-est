# Diagramming

The diagram is a **required output**. Not optional, not skipped with a note, not degraded to a
text fallback: `est-setup`'s job is to prepare everything the module needs and the renderer is
part of everything. A run that quietly produced no diagram would move the failure to the first
artefact a client sees.

## The renderer

`@eraserlabs/diagrams-cli`, **pinned to 0.2.0**, MIT, driven from `check-renderer.py`. It is
Eraser's own renderer, open-sourced — so the output is the quality bar rather than an
approximation of it.

It needs Node ≥22.12 and a Chromium-family browser, neither of which it bundles. `est-setup`
provisions both and **proves them by rendering a fixture and reading the bytes back**; a setup
that reports success while the renderer is absent has only moved the failure downstream.

The package was six weeks old when this module was built and is explicitly closed to outside
contribution, which is why the version is pinned, the icons are cached to disk, and
`architecture.json` stays renderer-agnostic: the eraser document is *generated from* it by
`layout.py`, so a second adapter is a swap rather than a rewrite.

## It positions nothing

The renderer routes connections and measures text. **Every entity needs authored `x`/`y`.**
That is the trade this module accepted, and it is the right one here: the reference diagram's
quality *is* its composition, and a layout engine would produce a generic graph instead.

So `layout.py` computes the whole thing bottom-up from a box model:

```
icon  ->  tier group  ->  platform band  ->  canvas
```

Deterministic, so the same architecture draws the same diagram every run and two readings of one
project can be diffed months apart. A model hand-placing forty nodes at pixel coordinates could
not offer that, which is why it does not.

## What the composition says

- **A platform earns a band** by hosting the application or serving three or more capabilities.
  A vendor that provides one thing shares the third-party band, the way the reference does it.
  Giving every vendor its own boundary produced eight bands on a 4378x614 canvas — 7:1, five of
  them holding one or two icons.
- **Inside a band, two tier rows**: the request path (`edge`, `application`) along the top and
  what it reaches (`services`, `data`, `external`) below. Declared in the model's `tiers.rows`,
  so it is data. Laid out as one long line instead, the application's five edges had to cross
  every tier between them, and the router — which avoids obstacles but cannot invent a corridor —
  ran them straight through.
- **Outside the platform boundaries, one tier per row.** Side by side, the third-party band hid
  its Integrations tier behind Platform services and an edge from the application had to cross
  one to reach the other.
- **Bands sit side by side** up to a generous width budget. Wrapping them into canvas rows too
  eagerly is what forced every outgoing edge to leave downward through the tier row underneath.
- **Users on the left, third parties on the right**, each outside every platform boundary.
- **Built and adopted components sit inside the platform that hosts them.** Giving them a band
  of their own claimed the database floats outside the cloud and stretched every application
  edge across the whole canvas.

## A runtime contains the software that runs in it

A thing the team writes and the thing that runs it are **two items**. "Django on Fargate" was one
box carrying both names, and its icon was a coin toss between a framework and a cloud service.

So a component whose mode is `build` or `adopt` and whose platform names a `runtime` is drawn as
a **group titled with the runtime**, carrying the runtime's official icon, with the software's own
icon inside it. Two products, two official icons, and the containment is visible rather than
implied by a preposition.

The split is a field, not a parse: the framework comes from the stack layer and the runtime from
`serves.<capability>.runtime` in the platform profile. `runtime` exists because `service` is a
description and sometimes a choice — AWS answers `application` with *"AWS App Runner, ECS Fargate
or Lambda"*, which is three services and not a runtime — so a profile that hosts code names the
one it means and lists the rest in `runtime_alternatives`.

`architecture-check.py` reports a `build`/`adopt` component on a platform with no runtime named,
and reports a label that repeats its own runtime — *"Django on Fargate"* drawn inside *"AWS
Fargate"* is the collapse this undid, arriving again by way of an operator override.

## Edges join groups, not icons

An application touching nine components draws nine near-parallel lines across the canvas: a
picture of the fan-out rather than of the system. Aggregating each edge to the group its
endpoints sit in collapsed twenty-one edges to a handful — and took one render from **eighty
seconds to three hundred milliseconds**, because obstacle-aware routing is where the renderer
spends its time. The component-level graph is still in `architecture.json` for anyone who wants
it.

## No connector runs over anything, and that is checked

The router is obstacle-aware — orthogonal, container-aware, unlimited repair budget — but it
**falls back to a straight line when no corridor exists**. 34px between tier groups is not a
corridor, and the first real diagram had **nineteen** segments crossing components that were not
their endpoints.

So `render.mjs` drives the renderer's library rather than its CLI, because `outputs: { json: true }`
returns the measured document — final boxes and every connection's routed points — and
`routing-check.py` tests every segment against every box it has no business touching. An edge may
overlap its own endpoints and their containers; everything else is a finding. Crossing a `Group`
is reported; crossing an `Icon` **fails the run**, because a group is a boundary a reader can
follow through and an icon is the thing they were trying to identify.

What got it to zero, measured one change at a time rather than assumed:

| Change | Effect on this architecture |
| --- | --- |
| Two tier rows per band | load-bearing — one row leaves 3 crossings and a 2496x2516 canvas |
| Bands side by side rather than stacked | load-bearing — stacking leaves 3 crossings |
| Actors point at the `edge` tier, not the application | removes the longest edge on the canvas |
| Wider corridors (80/120/80 rather than 34/80/34) | not load-bearing here; 34px is narrower than the router's own corner radius, so it is margin rather than decoration |
| A clear lane inside each band | not load-bearing here; it is what a band needs when bands *do* wrap and an edge has to leave downward |
| Authored `fromPort`/`toPort` | **made it worse** — removed |

That last row is the useful one. Pinning the faces from the two boxes' positions looks obviously
right and cost one edge: given real corridors the router chooses better faces than a bounding-box
heuristic can. Corridors are this module's job; faces are the router's.

## Icons are resolved, never bundled

There are **2,693 official cloud-service SVGs alone** and the vendors revise them quarterly, so
a copy vendored into this repository is stale the day it lands. `scripts/icons.py` looks each
one up when a diagram needs it and writes it into the renderer's icon cache — which serves any
name it finds there, so the catalogue the renderer ships with is a floor rather than a ceiling.

Three sources, ranked deliberately:

| Rank | Source | What it is for |
| --- | --- | --- |
| 100 | **The vendors' own architecture icons** (AWS, Azure, GCP via `tf2d2/icons`) | The only source with art for an individual cloud SERVICE rather than the provider's corporate logo, and what the reference diagram is drawn from. |
| 90 | **SVGL** | A curated, full-colour catalogue of modern product logos, icon-only variants included. |
| 80 | **Iconify** | 300,000 icons across 200+ sets, for the long tail. |

**The ranking is explicit because search cannot be trusted.** Iconify's own results put
`mdi:railway` — a train — above the Railway logo, an insect above Fly.io, and a pixel-art glyph
above Cloudflare. Six things make the difference between that and official art:

- **Only a named product is ever looked up.** A component carries a `product` when the design
  chose a concrete thing, and nothing when it kept its capability's own label. That label is not a
  product: searching *"Identity and access"* found **Ping Identity's** logo and *"Model inference"*
  found **Model Context Protocol's** — another company's mark on a box the team is going to write.
- **Aliases.** AWS publishes `Amazon-Simple-Storage-Service.svg` and never `S3`, so the name
  everybody says finds nothing without the table in `icon-sources.json`.
- **Coverage, and which word matched.** `Amazon RDS for PostgreSQL` has to find `Amazon-RDS.svg`,
  which carries one of its words; extra words in the candidate count against it, which is how
  `Amazon-S3-on-Outposts` loses to the plain service icon. But coverage does not care *which* word
  matched, so the head word must appear too — without that rule *"Stripe Connect Express + Stripe
  Billing"* won AWS's `Amazon-Connect.svg` at 118 against a floor of 110.
- **A floor under a match**, and a narrowing that is safe. Below the floor the resolver returns
  nothing. Above it, a name that matched nothing is retried on its **head** word, because product
  names lead: *Celery worker + beat* narrows to *Celery*. Narrowing to the tail is what once drew
  an arcade game for *"Fly Machines (static or SSR)"*, and a head that is a common noun —
  `object`, `secrets`, `machines` — narrows to nothing at all.
- **Measured colour.** `simple-icons:celery` and `thesvg-color:celery` are the same drawing and
  only one of them is green: `simple-icons` paints with `fill="currentColor"` and renders flat.
  Colour is read off the fetched bytes, greyscale does not count, and a coloured candidate beats a
  monochrome one.
- **Measured shape.** `logos:supabase` is 512x99 and renders as an illegible sliver;
  `logos:supabase-icon` is square. Stripe publishes no square variant at all, so a coloured lockup
  up to 3.3:1 is still accepted — and past 4:1 nothing is, because the capability's own glyph
  beats a strip.

The acceptance ladder, in order: coloured and square, coloured lockup, monochrome and square, then
whatever measured.

**Every icon is normalised before it is cached**, through the renderer's own
`normalizeFetchedIcon` rather than a reimplementation of it. The renderer normalises what *it*
fetches and returns a cache hit verbatim, so the icons we inject are the only ones that would skip
it — and every official AWS SVG declares `<rect id="Rectangle">`, so several on one page collide
and a `url(#id)` gradient resolves to whichever icon loaded first.

**A vendor's logo may appear twice.** A vendor that serves two capabilities draws its mark twice,
because that is what is true of the system. The earlier rule gave the logo to one component and
sent the rest to a grey glyph, which cost *Sentry Uptime + Web Vitals* its Sentry mark — a
substitute where official art exists, which is the one thing the brief forbids.

Every resolution is recorded in `assets/icons.resolved.json` with its source, id, URL, licence
and the date — so a diagram's iconography can be audited the way its numbers are, and a stale
one can be re-fetched. **Offline, every component falls back to its capability glyph**, which
ships with the renderer: the diagram is a required output and still renders.

## Colour

A vendor logo brings its own. The glyphs that do not — `key`, `shield`, `server`, `user` — are
given one **by tier**, from the brand palette, so the colour carries meaning: a reader sees the
shape of the system before reading a word. The palette comes from `est-estimate/scripts/brand.py`,
so the diagram and the workbook are one visual identity rather than two; a missing `brand.json`
falls back to the renderer's own tokens, because a diagram in the wrong blue is worth shipping and
one that does not render is not.

The prop is **`color`**. `Icon`'s schema is `{icon, size, texts, typeface, color, fontSize,
badge}`; `iconProps` belongs to `Shape` and to a group's title. An earlier version set `iconProps`
on an `Icon` — which the renderer neither rejects nor reads — so the tinting did nothing at all,
and every glyph rendered as the flat grey line-art the reference beats most obviously.

## What the diagram does not say

There are no **built / adopted / bought** badges and no legend. Whether a component is written or
rented is a sourcing decision with a scored table and a gate of its own; stamping it on the
artwork gave every node a second label and cost the diagram a corner to a key nobody needed. It
is in `architecture.md`, in the sourcing gate and in `architecture.json`.

Composite labels are left alone. *ACM TLS + Shield* and *Stripe Connect Express + Stripe Billing*
each keep one node with the head product's official icon and the full label, because splitting
free text would invent structure the profiles do not carry — and an `or` list is a choice rather
than a composition.

## Three things that fail the run rather than degrade

- **An unknown icon.** The renderer's default is a placeholder glyph plus a warning — a required
  output degrading in the one way nobody notices until a client does. Names are checked against
  `assets/icons.verified.json` before the browser boots, and `--unknown-icon error` catches
  anything that slips past.
- **A connector over an icon.** Checked against the measured geometry, not by eye.
- **Overlapping siblings.** `layout.overlaps()` checks the authored geometry. Rendered geometry
  can exceed authored geometry — a long service name grows its box — so a clean result there is
  necessary and not sufficient; `routing-check.py` runs against what the browser measured.

A repeated logo is a **note**, not a failure — see above.

## Provenance

`architecture.json` and the render report carry `produced_by`: a short content hash over this
installation's scripts and data. A project installs the module by copy, and one real run was
reviewed for a day against the repository's behaviour before anyone noticed it had executed a
copy three weeks old — no icon resolver, seven platform profiles instead of twenty. Every finding
about that output was a finding about code nobody was reading.
