# Researching a solution

**The catalogue is a starting point, not a boundary.** Twenty platform profiles ship with this
module. The space of things a project might sensibly run on is far larger, and a workflow that
can only choose from what somebody hardcoded will keep recommending the same seven vendors
whatever the project is. A real run scored eleven platform sets that all contained the same five
names, because for identity, email and error-tracking there was exactly one candidate each.

**An architecture chosen from a catalogue of one is not chosen.**

So: research the space, and when the right answer is a platform the catalogue has never heard
of, add it. `scripts/profile-scaffold.py` turns a researched description into a profile the
scoring treats exactly like a shipped one, written into `{memory}/platforms/`, which merges
over the shipped assets.

## When to go looking

Every time, for every live capability — but specifically when any of these is true:

- A capability has **fewer than two** candidates in the catalogue. That is not a decision.
- The obvious candidate is **the one you already know**. Familiarity is a real advantage and it
  is already scored as team fit; it should not also be the reason the alternatives were never
  listed.
- The project's shape is unusual — heavy write throughput, hard residency, an offline client,
  a regulated domain. The general-purpose answer is likeliest to be wrong here.
- The inventory names a vendor. Check whether it is still the right one; a PRD's stack is a
  working assumption and often a year old.

## What to bring back

For each candidate, enough to score it — and nothing that cannot be sourced:

| Field | Why the scoring needs it |
| --- | --- |
| `serves` | Which capabilities, by concrete product name. The product name reaches the diagram and the cost table. |
| `interface` | `standard` or `proprietary`, per capability. Drives reversibility. A candidate behind OIDC, the S3 API or SQL is a reconnect; a proprietary one is a rewrite. |
| `managed` | Drives operational burden. "Fly Postgres" is an image you run, not a service with an SLA — say so. |
| `runtime` | Only if it hosts an application: `long_running`, `background_jobs`, `websockets`, `containers`, `native_dependencies`, `cold_start`. **An unstated capability is treated as absent**, so an unresearched field makes the platform lose unfairly. |
| `pricing.model` | The *shape* — per seat, per request, per MAU, usage. The figure itself is fetched later, in the cost breakdown, never here. |
| `volatile` | Certifications, regions, residency — each with a **value, a URL and a date, or nothing at all**. |

**Do not write a volatile fact you cannot cite.** `checked: null` means nobody looked, and a
gate against it is reported *unevaluated*. A certification typed in from memory is a compliance
statement nobody checked, and it will be believed.

**You do not need to find an icon.** Icons are resolved from the vendors' own catalogues at
render time — `references/diagramming.md` — so a researched profile names a service and the
artwork follows.

## What makes a candidate worth listing at all

Not every vendor with a landing page is a candidate. A listed option should be one you would
defend in front of the engineers who have to run it:

- **It is operable by this team.** A brilliant platform nobody on the project has run is a
  novelty cost the estimate will pay for, and `team_fit` will say so.
- **It has an exit.** Ask what replacing it costs before asking what it costs.
- **It is alive.** Last release, contributor count, and whether the company is funded to keep
  going. "Heroku has been in a sustaining engineering model since 2026-02" is exactly the kind
  of fact that belongs in a profile's `note`.
- **It serves more than the demo.** A free tier that ends at the project's month-three volume
  is a migration disguised as a saving. The cost table's `free_until` column exists for this.

## Adding it

```
uv run scripts/profile-scaffold.py --from researched.json --out {memory}/platforms
uv run scripts/profile-scaffold.py --check {memory}/platforms
```

The scaffold refuses an unknown capability, an interface it cannot classify, a runtime a hosting
platform did not state, and any volatile fact without a date and a URL. The twenty shipped
profiles pass the same check — a researched profile is held to the module's standard, not a
lower one.

If a capability genuinely does not exist in the catalogue, add it to
`{memory}/architecture-model.json` first, with its tier, its signals and its fallback icon.
`references/capability-catalogue.md` has the rule.

## Record what you checked, not only what you found

The same discipline as everywhere else in this module: the report states the denominator. How
many candidates were considered per capability, which sources were read, and what was rejected
and why. A recommendation that lists one option and no rejects has not been researched, however
confident it reads.
