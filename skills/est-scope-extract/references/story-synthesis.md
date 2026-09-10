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

## Ordering the epics

Grouping says what belongs together. **Ordering says what gets built first**, and an inventory
that answers only the first question is a catalogue rather than a delivery plan. Every epic
carries a `sequence` running `1..N` with no gaps, and a `sequence_why` naming what it must
follow or what waits on it.

The order that keeps being right, in rough priority:

1. **The repository and its shared configuration.** Everything after it inherits those choices.
2. **The data model**, and the authentication skeleton if there is one. Almost every later epic
   reads from both, so putting them anywhere but near the front creates rework that no
   dependency in the source will have told you about.
3. **A design system before the screens that consume it.** This is the classic ordering no
   story records — the screens do not "depend on" it in any sentence the client wrote, but
   building them first means building them twice.
4. **The capability everything else reads.** In a booking product that is the booking; in a
   marketplace it is the listing. Consumers after producers.
5. **Integrations after the thing they integrate with.** A payment rail has nothing to charge
   for until there is a thing to buy.
6. **Reporting, admin and moderation last.** They read what the rest of the system writes, and
   they are also what a cut-line conversation reaches for first.

Two mechanics matter. A story in one epic depending on a story in another **is** an ordering
fact, and `inventory-check.py` rolls those up on its own — you do not restate them. What you
do state is `depends_on_epics`, for the ordering no story records: the design-system case
above is exactly what it is for. And **the array order of `epics` is not the sequence**. The
two are allowed to disagree, every projection sorts on `sequence`, and the checker validates
the order you state against the dependency graph rather than believing it. A stated order that
contradicts a stated dependency is a finding — which means the ordering is the one judgement
in this file that something other than a reader can catch you getting wrong.

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

Every source row still appears, as a `task` under its story, **carrying the row's own text**.
A task has an `id`, a `name` and a citation, and the citation's `quote` is where the text
lives — there is no separate description field, because a quote is checked against the
document and a paraphrase is not.

The text is the point, and it is the part that goes missing. A real run gave all 912 of its
tasks a citation quoting the task's own title:

```json
{"id": "F1-TO9", "name": "Enforce domain access by grant state",
 "citations": [{"location": "sheet 'Ops' row 9", "quote": "Enforce domain access by grant state"}]}
```

The row it came from was a 490-word paragraph setting out a three-state permission grant, and
none of it survived. Rows 9 and 10 described *different* grant models and both reduced to the
same six words, so the inventory could no longer tell them apart. Every check passed, because
the title is genuinely in the document — it is the column next door.

Quote the row, not its label. The whole cell, to its end. Two readers depend on it: the
classifier in `est-estimate` sizes the story against these words and nothing else, and a
reviewer is meant to check the inventory against the client's document **without opening it**.
`inventory-check.py` now compares each quote against the rest of the cell it came from, and a
task quoting its own name is a finding rather than a pass.

A task belongs to exactly one story — `inventory-check.py` rejects a task id used twice,
because a row in two stories is work counted twice.

Size the **story**, not the sum of its rows. Ten rows describing one screen is one screen.

## Surfaces

Each story carries `surfaces` — which kinds of work it actually touches. This is the one
classification-shaped field extraction still sets, because it is an observation rather than a
judgement about cost. It does two jobs, and the second one was only discovered when the cost
model was rebuilt against three delivered projects.

**It decides which roles are billed to the story at all.** A role whose surface is absent is
dropped from the split and the rest renormalise, so the story still costs what it costs and the
hours go to the people doing it.

**And it is the strongest single predictor of a story's SIZE that anything in this pipeline
records.** Across the delivery anchor's 75 stories, median surfaces per band run **1 / 2 / 3 / 3 /
4**, while median acceptance-criterion counts run 5 / 7 / 8.5 / 8 / 12 — which cannot tell M from
L at all. The classifier reads this field before it bands anything, so an untagged inventory costs
it its best signal.

**It is also the one granularity check the extraction cannot satisfy by re-slicing.** Everything
downstream is linear in the story count, and the story count is a property of whoever wrote the
document: the three delivered projects wrote the same kind of scope at 9.2, 2.9 and 3.1 hours per
story. Both sanity ratios that existed before divided by numbers extraction chooses — the citation
count and the story count — so both could always be satisfied by slicing differently. Surfaces per
story cannot be, and `inventory-check.py` now reports it against the anchor's **2.29**: materially
below and the estimate will run high, above and it will run low. That comparison moves the number
more than any individual band does.

| Surface | The work |
| --- | --- |
| `backend` | Server-side logic, data model, APIs, background jobs, third-party integrations |
| `frontend` | Screens, client state, forms, tables — implementing a design that exists |
| `design` | Visual or interaction design: new screens, a design-system component, an accessibility or microcopy pass |
| `infra` | Environments, pipelines, deployment, observability, secrets, migrations against real systems |
| `data` | Schema migration, import and export, backfills, reporting queries |

Most stories carry two. A nightly reconciliation job is `[backend]` and bills no designer. A
new onboarding flow is `[frontend, design]` and often `[backend]` too. A CSV importer is
`[backend, data]`.

`frontend` is not `design`. Building a screen from an existing design system is frontend work;
`design` means someone is deciding what it looks like. Tagging every screen `design` puts a
designer on the whole project, which is how a role split stops meaning anything.

**Omitting the field is not a way to say "none".** An untagged story keeps every role, because
silence must not quietly discount. If you cannot tell, leave it off and let the full split
stand — then say in the extraction report that surfaces were not classified.

## Before you finish

- Rows the source marked removed are `not_scope`, not stories.
- A change-log tab (`REPLACE row 300`, `INSERT`) is applied to the sheet it edits, never
  extracted alongside it.
- `Priority` and `Client Phase` columns travel with the story; they are what a cut-line
  conversation runs on later.
- If the story count is within a factor of two of the row count, you have almost certainly
  transliterated rather than synthesised. Say so in the extraction report if it is genuinely
  correct — some backlogs really are story-grained — but check first.
- **Read `inventory-check.py`'s `granularity` block before you finish, and put the figure in the
  extraction report.** Surfaces per story against the anchor's 2.29 is the check on whether this
  inventory is sliced the way the cost model's bands assume. A ratio near 0.5 means roughly twice
  as many stories for the same scope, and the estimate will read roughly twice as high — which is
  a real finding about the extraction, not a rounding note for the estimator to absorb.
