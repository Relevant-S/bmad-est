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

Every story carries five tags plus an optional `manual_effort` list. They are the inputs to the cost model, so a wrong tag is a wrong estimate — and each needs a one-line `why`, because this module ships no coefficient a human cannot interrogate. `surfaces` is the field the model reads that is *not* set here: which kinds of work a story touches is an observation the extractor makes. It decides which roles are billed, and it is also the strongest single predictor of size in the anchor — so read it before you band anything.

**Where the weight actually sits, so you spend your attention in the right place.** The band spread is 4.8x, so one band of error moves a story about a third. The story count moves the whole estimate one-for-one, and it varies threefold between projects writing the same kind of scope. Read `inventory-check.py`'s `granularity` block first; it is worth more than any individual band.

Tag from the evidence in front of you. When the source does not say, tag what it implies and say so in the `why` ("no volume given; assumed single-tenant"). Guessing silently is the failure; guessing visibly is the job.

## size_band

The **delivered hours** for this **story**, across every role billed to story work. NOT a
manual-equivalent baseline — the 3.0 model stopped pricing one, because no delivered project
ever recorded it. What all three recorded is delivered time, and that is what these bands hold.

**Read the calibrated bands before you tag anything:**

```
uv run {project-root}/skills/est-scope-extract/scripts/inventory-check.py --bands \
  --cost-model {project-root}/_bmad/memory/est/cost-model.json
```

That prints the hour ranges, the worked exemplars for each band, and the shape of the delivered
project the bands were fitted against. The exemplars live in the cost model beside the hours they
illustrate, so they move when the hours move — a table copied into your head from a previous run
is a table that has drifted.

| Band | pts | Delivered h | Anchor exemplar |
| --- | --- | --- | --- |
| `XS` | 1 | ~1.6 | *Pre-Epic-4 hardening* — a cleanup batch, no feature surface |
| `S` | 2 | ~3.0 | *Suspended / deactivated member state* — two terminal states reusing a gate already built |
| `M` | 3 | ~4.6 | *Monorepo scaffold & shared contracts* — multi-surface, no domain logic |
| `L` | 4 | ~6.2 | *Login / logout & persistent session* — DB, API, Redis and Web; refresh-token rotation in Redis Lua |
| `XL` | 5 | ~7.7 | *Paid recurring membership* — Stripe Subscriptions, `invoice.paid` lifecycle, credit grant |

**The spread is 4.8x, and that is the single most important thing on this page.** Under the 2.x
model the bands ran 1 h to 90 h, so one band of error moved a story's cost 3.0x. The delivered
record says the step from M to L is **1.34x**. Getting a band wrong is a real error and a small
one — which means two things for how you work. You do not need to agonise over M-versus-L. And
you must not let the band become the place you express everything else you noticed about a story,
because it no longer has the range to carry it.

**What actually separates the bands: how many distinct surfaces the story touches.** Median
surfaces per band across the anchor's 75 stories run 1 / 2 / 3 / 3 / 4. Median acceptance-criterion
count runs 5 / 7 / 8.5 / 8 / 12 — which cannot tell M from L at all. Ask what the story has to
touch, not how much was written about it.

**The question that still separates `M` from `L`: does this introduce a capability the codebase
does not yet have?** The first OIDC integration is `L` — a new protocol, on every client. The
second thing that signs in through it is `M`. The first real-time transport is `L`; the ninth
screen that subscribes to it is `M`.

**Centrality is not size. Neither is risk — and this is now measured, not argued.** Holding the
anchor's own record: sensitive stories average **3.24 points against routine 3.08**. That is
**1.05x**, and 1.06x with every provider-touching story excluded so the money premium cannot
flatter it. Criticality does not make a story bigger. It is priced in `review_tier`, and if you
also raise the band for it the estimate bills the same fact twice.

The tell is in the `why` you are about to write. *"The aggregation every customer-facing answer
depends on"*, *"lands in the schema before any screen exists"*, *"read by every quote and every
availability response"* — every one of those argues from blast radius, and every one of those is a
reason to raise the review tier, not the band.

**And it is not the row count.** In the anchor the first-OIDC story carries **4** acceptance
criteria and is `L`, while a routine configuration screen carries **7** and is `M`.

Three calls that are made wrong most often:

- **CRUD over one entity is `M`**, however central the entity is to the product.
- **A list plus its detail view is `M`**, however many other features read from it.
- **A story you cannot describe without naming a protocol, a transport or an external system is
  `L`**, even when the source states it in one line.

**`XS` and `XL` are both real, and both were denied by the 2.x model.** It claimed the anchor had
neither and warned on the first tag of each — so the checker was pushing small work up a band and
large work down one. The anchor's own record has **2.7% XS** and **4.0% XL**. Tag them when they
are true. `XL` is still worth a second look for a split, and `est-estimate` prices a narrowing
question for each one, but it is not an error.

### The anchor's shape, and what it is not

The delivered mix is **XS 3% · S 17% · M 45% · L 31% · XL 4%**.

**This is not a target, and `inventory-check.py` will not ask you to move toward it.** That
matters because of how the 2.x pipeline went wrong: this page told the classifier to expect 64% M
before it judged anything, and the checker then flagged it for deviating from the same figure. The
prior was injected and then enforced, so the distribution stopped carrying any information about
the project — and all the real variance went into the story count, which nothing checked at all.

Read the shape to notice something you did not intend, then argue with it. A data-migration
engagement or a design-led build legitimately sits elsewhere.

### The thing that does move the number: how finely the inventory is sliced

Everything downstream is linear in the story count, and the story count is a property of whoever
wrote the document. Across the three delivered projects the same kind of scope was written at
**9.2, 2.9 and 3.1 hours per delivered story** — a 3.2-fold spread. The bands are fitted to the
first of those.

`inventory-check.py` reports `granularity`: surfaces per story against the anchor's 2.29. Below it
and the estimate runs high; above it and it runs low. That is the number to read before you worry
about a band.

## manual_effort

**Not a tag — a list, and often empty.** Work on this story whose cost is not the code: provider
dashboards, credentials, store review, console clicking, and verification an agent cannot perform.
It is priced as **additive hours**, because it does not scale with how big the story is. Setting
up a payment provider is the same console work behind a small story as a large one.

Measured on the anchor as the residual over what a story's surface count predicts:

| Value | Residual | Apply when |
| --- | --- | --- |
| `money_rail` | **+0.75 pts** | A payment or billing provider is integrated — account and product setup, webhook endpoints and signing secrets, test-mode reconciliation |
| `external_idp` | **+0.73 pts** | An external identity provider is configured — app registration, redirect URIs, client secrets, tenant consent |
| `native_release` | **+0.41 pts** | A device build or a store channel — signing identities, provisioning profiles, native toolchain linkage, hardware-only verification |
| `provisioning` | **unpriced** | Real environments, credentials, DNS and TLS against a live cloud account |

A story touching nothing external scores **−0.07** — that row is the control, and it is what makes
the other three believable.

Two of the anchor's three `XL` stories are its Stripe ones, and its epic-3 retrospective records
four CRITICAL money/race bugs found in one of them. The native pair sit at 4 points on only **two**
surfaces — the highest points-per-surface ratio in the project — and the epic-5 retrospective names
why: *"native-build verification is invisible to the planning loop."*

**`provisioning` is deliberately unpriced.** None of the three anchors paid for it: all three
deferred real infrastructure, and the anchor's `Infra` stories score 0.51 points *below*
prediction because its observability story is marked "seams only, IaC deferred". Tagging it raises
an open question rather than a number, which is the honest answer until a project that actually
reached production reports actuals.

## compressibility

How much BMad compresses **building** this. **REPORTED ONLY since 3.0 — no priced hour depends on it.** In 2.x it was the divisor that turned a manual-equivalent baseline into build hours; nobody had measured a manual baseline on any delivered project, so the division was arithmetic over a construct. It now runs the other way: `manual_equivalent = delivered x compressibility`, which is the client-facing "this would have cost X by hand" sentence and nothing else.

Tag it accurately anyway — it is the number a client argues with, and it is the module's whole claim about why the estimate is what it is. But if you get it wrong, only that sentence moves.

| Value | Compresses | Because |
| --- | --- | --- |
| `high` | ~16× | CRUD, greenfield web/SaaS screens, scaffolding, well-documented third-party APIs, test generation, docs, config, mechanical refactors |
| `medium` | ~9× | Conventional business logic, common integrations, standard mobile screens, moderate data transformation |
| `low` | ~5× | Undocumented legacy or client-proprietary systems, bespoke algorithms, migration of real dirty data, pixel-level design craft, environment and deployment plumbing |
| `none` | ~1× | Client workshops, approvals, compliance sign-off, third-party lead times, experimental ML iteration — work where no code is the deliverable |

The question that decides it: **how much of what this needs is already in the model's world?** A Stripe integration is `high` because Stripe is thoroughly documented and thoroughly represented. An integration with the client's fifteen-year-old ERP over an undocumented SOAP endpoint is `low` — the same word "integration", an order of magnitude apart.

Where the company has an automated capability that changes the answer, say so in the `why`. Mobile QA run through the mobile MCP server compresses far more than the industry default assumes, and an estimate that ignores that is wrong in the company's disfavour.

## review_tier

**A real difference in kind, and a small one in hours** — which is the opposite of what the 2.x
model said, and the correction is measured rather than argued. Review effort is a step function of
what the feature *touches*: a one-line change to a pricing calculation gets read line by line, a
large but routine CRUD screen gets a spot-check. But under this delivery model, with a
fresh-context agent review pass before a human reads anything, that difference costs **1.05x** on
the anchor's own record — not the 1.9x the 2.x coefficients implied.

So tag it accurately and do not expect it to move the number much. It decides who reviews, it
shifts where the hours are reported, and it is the right home for every "this is read everywhere"
instinct that would otherwise inflate a band. What genuinely makes a sensitive story expensive is
the provider behind it, and that is `manual_effort`.

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
