# Classification Guide

Tag the **story**, not the source rows under it. A story built from ten workbook lines
describing one screen is one screen: size it as the screen, not as the sum of the lines.

**A `why` is about this story or it is not a `why`.** The same sentence on two hundred tags is
a default rule with a justification stapled to it, and it is what turned a workbook into a
project — `inventory-check.py` reports any justification shared across more than a fifth of
the inventory, and `est-estimate` prints that report in the estimate's own assumptions. Write
what decided *this* one, quoting the source where you can.

Every story in a Feature Inventory carries five tags plus `surfaces`. They are the inputs to the cost model in `est-estimate`, so a wrong tag is a wrong estimate — and each tag needs a one-line `why`, because this module ships no coefficient a human cannot interrogate.

Tag from the evidence in front of you. When the source does not say, tag what it implies and say so in the `why` ("no volume given; assumed single-tenant"). Guessing silently is the failure; guessing visibly is the job.

## size_band

The **manual-equivalent** effort — what this would have cost a human team writing it by hand. Not the BMad effort. The cost model derives BMad hours from this band; conflating the two double-counts the compression.

| Band | Manual-equivalent | Looks like |
| --- | --- | --- |
| `XS` | under 4h | A config change, a copy edit, one field added to an existing form |
| `S` | 4–16h | A single endpoint, a simple form, a static page, one report column |
| `M` | 16–60h | A CRUD resource with its UI, a documented third-party integration, a multi-step flow |
| `L` | 60–160h | A subsystem: authentication, a payments flow, a reporting module, an admin area |
| `XL` | over 160h | A product area, not a feature |

An `XL` tag is a signal to split. A feature that large hides too much variance to estimate as one item, and the range it produces will be uselessly wide. Split it into the parts the source describes and note the split in `assumptions`. Only leave it `XL` when the source genuinely gives nothing to split on — and then say so in the `why`, because that is itself an open question worth asking the client.

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

## surfaces

Which kinds of work the story actually touches. Unlike the five axes above, this one does not
scale the hours — it decides **which roles are billed to the story at all**. A role whose
surface is absent is dropped from the split and the rest renormalise, so the story still costs
what it costs; the hours simply go to the people doing the work.

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
