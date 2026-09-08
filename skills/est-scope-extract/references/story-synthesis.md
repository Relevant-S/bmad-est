# Story synthesis

Rows in, stories out. This is the step where an estimate stops being a transliteration of
someone's spreadsheet and starts being a statement about work.

## Why this step exists

A post-discovery workbook was extracted at one feature per row: 754 rows became 754 priced
features, averaging **1.6 hours each**, with hundreds rendering as `0`. The headline was
arguable; every line under it was not, and the module's whole claim is that a number can be
decomposed on demand.

Two things went wrong, and both are structural rather than careless:

- **Every downstream figure is linear in the count.** Planning is priced per epic and per
  story, QA is a share of the summed baseline, overhead follows the schedule. A three-fold
  granularity error is a three-fold estimate error, and it lands hardest on planning, which
  has no other input — the same workbook produced 99 epics and 833 stories where the BA had
  written 56 epics.
- **A row is an acceptance criterion.** `Sort people`, `Sort audit log`, `Sort customers` —
  twelve rows for one reusable list control. Priced separately they are twelve features; read
  honestly they are one component and eleven applications of it.

## Where the grouping comes from

**Look before you invent.** Most sources have already been grouped by someone who knew the
domain, and their grouping is better than yours:

| Source | Where the grouping is |
| --- | --- |
| Backlog workbook | A sparse-filled epic column — the value appears once and the rows beneath inherit it, often as merged cells |
| PRD | Section headings, and any FR numbering scheme |
| Existing backlog export | Epic/parent links |
| SOW or RFP | Numbered scope sections, priced line items |
| Transcript | Nothing usable. Synthesise, and say so |

An epic taken from the source is `origin: source`. One you made is `origin: synthesised` and
needs a `why` naming what it was grouped on. `inventory-check.py` enforces the `why`, and
enforces that either every story carries an `epic_id` or none does — a half-grouped inventory
prices planning against a count matching neither the source nor the stories.

Where you do have to synthesise, group by **user value**, not by technical layer: "File
management" with upload, status and permissions as stories, never "Database setup" then "API
layer" then "Screens". Consolidate epics that would all churn the same component.

## What becomes a story

A story is one coherent unit of delivery: something a developer could pick up, build and have
reviewed. Concretely, rows collapse into one story when they are:

- **The same capability over one surface.** Search, filter and sort on the leads list are one
  story. Search on leads and search on bookings are two — different data, different rules.
- **A capability and its own configuration.** A 59-row catalogue of workspace-health checks is
  not 59 features; it is one health-check story whose size reflects 59 rules. Likewise a
  50-row notification list is one fan-out story configured 50 ways. Record the count in the
  story's size `why`, so the number that drove the band is on the page.
- **CRUD faces of one resource.** Create, edit, view, archive on the same entity.

They stay separate when the review tier, the compressibility or the surfaces differ — those
are the axes the cost model prices on, so merging across them averages away the thing being
estimated. A payments row and a settings row do not belong in one story however similar the
verbs look.

**Repeated affordances get a shared component.** When the same control appears across nine
epics, make one story for building it and cheap instantiation tasks or stories for applying
it. Nine full-price copies is the single biggest inflation in a workbook-shaped input.

## What stays visible

Every source row still appears, as a `task` under its story, carrying its own citation. This
is not bookkeeping: the module's non-negotiable is that a reviewer can open the inventory
beside the client's document and check it line by line, and that is only possible while every
line is still represented. A task belongs to exactly one story — `inventory-check.py` rejects
a task id used twice, because a row in two stories is work counted twice.

Size the **story**, not the sum of its rows. Ten rows describing one screen is one screen.

## Surfaces

Each story carries `surfaces` — which of `backend`, `frontend`, `design`, `infra`, `data` the
work actually touches. This is not descriptive: it decides which roles are billed to the
story, and a role whose surface is absent is dropped from the split entirely. A nightly
reconciliation job tagged `[backend]` bills no designer.

Omitting the field is not a way to say "none". An untagged story keeps every role, because
silence must not quietly discount. Tag it, or accept the full split.

## Before you finish

- Rows the source marked removed are `not_scope`, not stories.
- A change-log tab (`REPLACE row 300`, `INSERT`) is applied to the sheet it edits, never
  extracted alongside it.
- `Priority` and `Client Phase` columns travel with the story; they are what a cut-line
  conversation runs on later.
- If the story count is within a factor of two of the row count, you have almost certainly
  transliterated rather than synthesised. Say so in the extraction report if it is genuinely
  correct — some backlogs really are story-grained — but check first.
