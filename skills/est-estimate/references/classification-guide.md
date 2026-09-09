# Classification Guide

**This is where an estimate is decided.** The Feature Inventory records what the client's
document says; every tag below is a judgement about what that work costs, which is why they
live in `classification.json` written by this skill rather than in the inventory written by
the extractor. Read the stories against their own quotes — that is not a second extraction,
it is the reading that makes a band defensible.

Tag the **story**, not the source rows under it. A story built from ten workbook lines
describing one screen is one screen: size it as the screen, not as the sum of the lines.

**Read the rows before you size.** A story's `tasks` carry the client's own sentences for
every line it was assembled from, and that is the evidence a band rests on — the story's
`description` is the extractor's summary of them. An earlier run had rows whose quote was
nothing but the row's title, and sizing against six-word labels is how a routine settings
screen and the first authorisation layer in a codebase come back in the same band. If the
rows under a story say no more than its name does, the inventory is defective: say so and
send it back rather than banding it anyway.

**A `why` is about this story or it is not a `why`.** The same sentence on two hundred tags is
a default rule with a justification stapled to it, and it is what turned a workbook into a
project — `inventory-check.py --classification` reports any justification shared across more than a
fifth of the inventory, and the estimate prints that report in its own assumptions. Write
what decided *this* one, quoting the source where you can.

Every story carries five tags. They are the inputs to the cost model, so a wrong tag is a wrong estimate — and each needs a one-line `why`, because this module ships no coefficient a human cannot interrogate. `surfaces` is the sixth field the model reads and the one that is *not* here: which kinds of work a story touches is an observation the extractor makes, and it decides which roles are billed rather than how many hours are.

Tag from the evidence in front of you. When the source does not say, tag what it implies and say so in the `why` ("no volume given; assumed single-tenant"). Guessing silently is the failure; guessing visibly is the job.

## size_band

The **manual-equivalent** effort — what this **story** would have cost a human team writing it by hand. Not the BMad effort. The cost model derives BMad hours from this band; conflating the two double-counts the compression.

**Read the calibrated bands before you tag anything:**

```
uv run {project-root}/skills/est-scope-extract/scripts/inventory-check.py --bands \
  --cost-model {project-root}/_bmad/memory/est/cost-model.json
```

That prints the hour ranges, the worked exemplars for each band, and the shape of the delivered project the bands were fitted against. The exemplars live in the cost model beside the hours they illustrate, so they move when the hours move — a table copied into your head from a previous run is a table that has drifted.

**The unit is a story.** These bands described a *feature* until they were fitted against a delivered project, and a story is roughly a third of one — which made every story-grained inventory price about three times too high. If a row you are tagging looks like "authentication" rather than "log in with email and password", it is an epic and it should have been split.

| Band | Manual-equivalent | Looks like |
| --- | --- | --- |
| `XS` | under 2h | A config change, a copy edit, one field added to an existing form — usually a task inside a story rather than a story |
| `S` | 2–7h | A single endpoint, a simple form, one static page, one report column, a language pack against a framework that already exists |
| `M` | 6–20h | An endpoint plus its screen, a second entity's CRUD and its config screen, a list and its detail view, another path through a flow that already exists |
| `L` | 20–55h | **The first of its kind in this codebase** — a protocol, a transport, an external system, a framework, or a foundation everything after it is built on |
| `XL` | over 55h | A story that should have been split — a subsystem tracked as one row |

**The question that separates `M` from `L`: does this introduce a capability the codebase does not yet have?** The first OIDC integration is `L` — a new protocol, on every client. The second thing that signs in through it is `M`. The first real-time transport is `L`; the ninth screen that subscribes to it is `M`. The exemplars in the cost model are all of this shape, and they are what you compare against.

**Centrality is not size, and neither is risk.** A derived read that every other feature depends on is sized as the query it is. That it is read everywhere is `review_tier`'s business, and `review_tier` charges for it — 0.04, 0.17 and 0.30 of the baseline across the three tiers. Size it for its reach as well and the estimate bills the same fact twice. This is not hypothetical: in one extraction, holding the source volume fixed at exactly one row so the content could not vary, the share of stories tagged `sensitive` or `critical` still climbed **41% at `S`, 68% at `M`, 78% at `L`** — the band was tracking how dangerous the story was, not how much of it there was.

The tell is in the `why` you are about to write. *"The aggregation every customer-facing answer depends on"*, *"lands in the schema before any screen exists"*, *"read by every quote and every availability response"* — every one of those argues from blast radius, and every one of those is a reason to raise the review tier, not the band.

**And it is not the row count.** Acceptance criteria and source rows do not decide the band: in the anchor, the first-OIDC story carries **4** acceptance criteria and is `L`, while a routine configuration screen carries **7** and is `M`. Volume of stated requirement is a real signal across a whole inventory — `inventory-check.py` compares yours against the anchor's rate — and it is not one story by story.

Three calls that are made wrong most often:

- **CRUD over one entity is `M`**, however central the entity is to the product. "Create, view, update and delete a vehicle type" is the same size whether the product rents vehicles or merely lists them.
- **A list plus its detail view is `M`**, however many other features read from it.
- **A story you cannot describe without naming a protocol, a transport or an external system is `L`**, even when the source states it in one line. A single row reading "sign in with Microsoft" is a `L`.

An `XL` tag is a signal to split. A story that large hides too much variance to estimate as one item, and the range it produces will be uselessly wide. Split it into the parts the source describes and note the split in `assumptions`. Only leave it `XL` when the source genuinely gives nothing to split on — and then say so in the `why`, because that is itself an open question worth asking the client. `est-estimate` prices a narrowing question for every `XL` rather than treating the band as an answer.

**Expect most of the inventory to be `M`.** In the delivered project the bands are fitted against, the split was 64% `M`, 25% `L`, 11% `S`, and nothing was `XS` or left `XL`. That is a reference class to argue with, not a quota — a data-migration engagement or a design-led build will legitimately sit elsewhere, and `inventory-check.py` reports the comparison rather than enforcing it. But an inventory where a third of the stories are `L` is claiming that a third of the product is a capability nobody has built before, and that is a claim worth making deliberately.

## compressibility

How much BMad compresses **building** this. This is the axis that separates an AI-delivery estimate from a conventional one, and it varies more than people expect.

| Value | Compresses | Because |
| --- | --- | --- |
| `high` | 5–12× | CRUD, greenfield web/SaaS screens, scaffolding, well-documented third-party APIs, test generation, docs, config, mechanical refactors |
| `medium` | 3–6× | Conventional business logic, common integrations, standard mobile screens, moderate data transformation |
| `low` | 1.5–3.5× | Undocumented legacy or client-proprietary systems, bespoke algorithms, migration of real dirty data, pixel-level design craft, environment and deployment plumbing |
| `none` | ~1× | Client workshops, approvals, compliance sign-off, third-party lead times, experimental ML iteration — work where no code is the deliverable |

The question that decides it: **how much of what this needs is already in the model's world?** A Stripe integration is `high` because Stripe is thoroughly documented and thoroughly represented. An integration with the client's fifteen-year-old ERP over an undocumented SOAP endpoint is `low` — the same word "integration", an order of magnitude apart.

Where the company has an automated capability that changes the answer, say so in the `why`. Mobile QA run through the mobile MCP server compresses far more than the industry default assumes, and an estimate that ignores that is wrong in the company's disfavour.

## review_tier

**The single highest-leverage tag.** Review effort is not proportional to how big a feature is; it is a step function of what the feature *touches*. A one-line change to a pricing calculation gets read line by line. A large but routine CRUD screen gets a spot-check of its migrations, tests and CI.

| Tier | Human review | Raised by |
| --- | --- | --- |
| `routine` | Delegate the feature whole; spot-review DB migrations, tests, CI/CD | Everything not below |
| `sensitive` | Line-by-line human verification | Money, personal data, authentication and authorization |
| `critical` | Line-by-line plus external or compliance sign-off | Regulated data, irreversible financial effects, safety |

Quote the phrases that raised the tier into the tag's `triggers` array. That is what lets a human confirm or dismiss the call in seconds rather than re-reading the document.

**What raises a tier.** You will infer most of these from meaning, so this is not a checklist to match against — it is the boundary, stated once, so two runs over the same document land on the same tier.

- **`sensitive`** — the feature handles money (payment, billing, refund, pricing, payout, tax, ledger), personal data (contact details, date of birth, identity documents, health, biometrics, uploaded photos, location), or access itself (login, SSO, MFA, session, role, permission, admin, API key).
- **`critical`** — a named compliance regime applies, and this is the firmer line because these are the words a client uses when an external auditor is involved: GDPR, HIPAA, PCI-DSS, SOC 2, KYC, AML. Also anything irreversible, anything safety-related, and anything whose output is a financial report.

Two distinctions worth getting right. **Displaying** personal data is `sensitive`; showing anonymized aggregates over it is `routine`. And a feature is tagged for what *it* touches, not for what its neighbours touch — a marketing page on a site that also takes payments is still `routine`.

## clarity

How precisely the source specifies this feature. It drives both the specification cost and the rework loops, and it is the axis most people skip.

| Value | The source gives you |
| --- | --- |
| `high` | Acceptance criteria or equivalent detail: the data involved, the edge cases, what "done" means |
| `medium` | A clear description in prose. Intent is unambiguous; the details are not there |
| `low` | A line in a transcript, a bullet in a list, or something you inferred from context |

Under BMad this axis costs more than it used to. Ambiguity is no longer resolved by a developer stopping to ask — it gets confidently implemented, reviewed, and then rebuilt. A `low` clarity tag is not a note about documentation quality; it is a real, priced risk, and it is also what generates the questions worth putting back to the client.

## novelty

`standard` when the team has built something of this shape before, `novel` when it is new to them or genuinely uncommon. Novelty drives rework loops rather than build effort — the first attempt at an unfamiliar shape rarely converges in one pass. When the source does not tell you what the team has done before, tag `standard` and say in the `why` that it is unverified.

## Commitment, which is not a tag

Separate from the five axes, every feature carries a `commitment` level: `committed` (the source states it as in scope), `implied` (it follows necessarily from something committed — an admin screen for a resource the client asked to manage), or `speculative` (raised as a possibility, a later phase, or an aspiration).

This matters most in transcripts, where all three appear in the same breath. "We'll need user accounts, and eventually maybe some kind of loyalty thing" is one `committed` feature and one `speculative` one. Recording both, correctly labelled, is what lets the estimate offer a phase-one number and a phase-two conversation instead of one inflated figure or one quiet omission.

## surfaces, which is not set here

`surfaces` decides which roles are billed to a story rather than how many hours it takes, and
it is an observation about the work rather than a judgement about its cost — so `est-scope-extract`
sets it while it still has the source open, and `references/story-synthesis.md` over there carries
the table. Read it off the inventory; do not re-decide it. If a story arrives untagged it keeps
every role, because silence must not quietly discount.
