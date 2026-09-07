---
title: 'Module Plan: BMad Delivery Estimator'
status: 'complete'
module_name: 'BMad Delivery Estimator'
module_code: 'est'
module_description: 'Turns any project input (transcript, PRD, SOW, RFP, spreadsheet) into a reasoned, ranged hour estimate for delivery with the BMad method.'
architecture: 'Hybrid — 3 workflows (automatable spine) + 1 agent (conversational front door, model curator)'
standalone: true
expands_module: ''
skills_planned: ['est-scope-extract', 'est-estimate', 'est-calibrate', 'est-agent-estimator']
skills_built: ['est-scope-extract', 'est-estimate', 'est-calibrate', 'est-agent-estimator']
config_variables: ['est_default_team_profile', 'est_report_calendar_duration', 'est_output_folder', 'est_default_fidelity', 'est_output_formats', 'est_show_manual_baseline', 'est_roles', 'est_knowledge_pack_source', 'est_min_calibration_samples', 'est_sprint_length_days']
created: '2026-09-07'
updated: '2026-09-07'
---

# Module Plan

## Vision

<!-- Drafted from the user's opening brief; to be refined in Phase 1-2 -->

An outsourcing company running many parallel projects — some in iterative delivery, some at presale — needs every project estimated in hours before it can be proposed. Inputs are wildly uneven: a 60-page SOW on one desk, two paragraphs from a discovery call on another.

This module ingests whatever exists, extracts the feature scope, and produces a defensible **ranged hour estimate** for building it **with the BMad method** — i.e. agent-driven delivery where the human cost profile is dominated by specification, review, and correction rather than hand-typing code.

## Architecture

**Decision: Hybrid — three workflows forming an automatable spine, plus one agent as the conversational front door and model curator.**

**Rationale.** The literal ask was "an automated workflow", and the company runs many projects in parallel — so the estimation engine must be batchable and headless-capable. That argues for workflows. But three of the four confirmed consumers (presale defence, delivery planning, gut-check) involve a human arguing with the number, and the module owns evolving state (a cost model, a comparables library) that needs an owner. That argues for an agent. Splitting them gets both: the workflows are deterministic, testable and unattended; the agent is where judgement, challenge and curation live.

The agent is **not** a pure coordinator — it produces tangible output of its own (revised estimates, what-if scenarios, negotiation positions, a curated cost model), which is the test for whether an agent earns its place.

**Deployment: installed into each project repo** (user decision), with a two-layer memory split to prevent ledger fragmentation — see below.

**Skills:**

| Skill | Type | Role |
| ----- | ---- | ---- |
| `est-scope-extract` | workflow | Any input, any format → traceable Feature Inventory |
| `est-estimate` | workflow | Feature Inventory → ranged, role-split, phase-decomposed estimate |
| `est-calibrate` | workflow | Actuals (messy/partial) → evidence-backed coefficient adjustments |
| `est-agent-estimator` | agent | Conversational intake, explanation, defence, what-ifs, model curation |

### Memory Architecture

**Pattern: single shared module memory, split into a project-local layer and a portable knowledge pack.**

All four skills read and write one shared memory folder — the cost model, company profile and comparables are useless if siloed per skill. The split below reconciles per-project installation with cross-portfolio learning.

```
{project-root}/_bmad/memory/est/
├── index.md                      # orientation; what exists, last updated, recent activity
│
├── ── PORTABLE KNOWLEDGE PACK (syncs across projects) ──
├── cost-model.md                 # THE coefficients. Human-readable, human-editable.
├── company-profile.md            # team shape, stack, BMad adoption depth, QA capabilities
├── comparables.md                # past features/epics/projects: estimated vs actual
│
├── ── PROJECT-LOCAL ──
├── ledger/
│   └── EST-YYYYMMDD-{slug}.md    # one per estimate: inputs, coefficients used, output, status
├── calibration-log.md            # what coefficient changed, when, why, on what evidence
└── daily/YYYY-MM-DD.md           # append-only session log, tagged by skill
```

**Why the cost model lives in memory rather than inside skill logic:** the user's hard constraint — *no black box coefficients*. Every number the estimator uses must be a line in a file a human can read, question and override. This is also what makes calibration mechanically possible: `est-calibrate` edits a data file, not prompt text.

**Knowledge pack sync.** `est-setup` fetches the current pack from a configured shared source (`est_knowledge_pack_source` — a git repo, shared folder, or unset for local-only). `est-calibrate` publishes accepted coefficient changes back. If unset, the module runs fully self-contained on seeded defaults.

### Memory Contract

| File | Purpose | Read by | Written by |
| ---- | ------- | ------- | ---------- |
| `index.md` | Orientation. What curated files exist, when last updated, recent activity. Every skill reads first, then selectively loads. | all | all |
| `cost-model.md` | Compressibility classes and factors; review-tier multipliers; spec/review/rework formulas; BMad phase overheads; role-split ratios; uncertainty-band rules. Seeded from module defaults at setup. | `est-estimate`, `est-calibrate`, agent | `est-calibrate` (approved changes only), agent (explicit user edits) |
| `company-profile.md` | Team shape and seniority mix, stack strengths, BMad adoption depth per team, QA capabilities (incl. mobile-MCP automated QA), typical client engagement model. | `est-estimate`, agent | agent, setup |
| `comparables.md` | Past features/epics/projects with classification, estimate and (where known) actual. The anchoring corpus. | `est-estimate`, agent | `est-calibrate`, agent |
| `ledger/EST-*.md` | One record per estimate: source inputs, feature inventory reference, coefficients used (snapshot), output range, assumptions, status (draft/sent/won/lost/delivered). | `est-calibrate`, agent | `est-estimate`, agent, `est-calibrate` (status + actuals) |
| `calibration-log.md` | Audit trail of every coefficient change: old value, new value, evidence, sample size, date, who approved. | agent | `est-calibrate` |
| `daily/YYYY-MM-DD.md` | Timestamped append-only entries tagged by skill name. Raw session history. | agent | all |

**Coefficient snapshotting is mandatory.** Each ledger entry records the coefficient values used at estimate time. Without this, calibration cannot tell whether a delta came from a bad estimate or from a model that has since changed.

### Cross-Agent Patterns

Single agent, so the patterns are agent↔workflow and workflow↔workflow:

- **The agent is the router.** `est-agent-estimator` invokes the workflows and interprets their output. Users can also run any workflow directly and headlessly — the workflows never depend on the agent being present.
- **Pipeline handoff:** `est-scope-extract` → Feature Inventory (a file, not conversation state) → `est-estimate` → estimate + ledger entry → later → `est-calibrate` reads the ledger entry. Every handoff is a durable artefact, so any stage can be re-run, inspected or corrected independently.
- **Shared memory is the coupling.** Skills never call each other implicitly; they coordinate through `_bmad/memory/est/`.
- **Feedback loop:** `est-calibrate` writes to `cost-model.md` and `comparables.md`, which `est-estimate` reads on its next run. This is the only loop in the module and it is human-gated at the approval step.

## Cost Model Specification

This is the module's core IP. It lives as editable data in `_bmad/memory/est/cost-model.md`, **never** as logic buried inside a skill — the user's hard constraint is that every coefficient is inspectable and overridable.

### Per-feature calculation

Each extracted feature carries four tags: **size band**, **compressibility class**, **review tier**, and **clarity score**.

```
manual_baseline = size_band → hours range          (XS/S/M/L/XL lookup, three-point)

build_h   = manual_baseline / compression_factor(compressibility_class)
spec_h    = manual_baseline × spec_rate(clarity)
review_h  = manual_baseline × review_rate(review_tier)
rework_h  = (build_h + review_h) × rework_rate(clarity, novelty)

feature_h = build_h + spec_h + review_h + rework_h
```

**The critical detail: `review_h` is driven by `manual_baseline`, not by `build_h`.**

Review effort scales with the *volume of output produced*, not with the time taken to produce it. Under BMad the agent generates roughly the code a human would have written, but in a fraction of the time — so compression shrinks `build_h` and leaves `review_h` untouched. This single modelling choice reproduces the user's lived experience automatically:

- Routine CRUD feature — compression 8×, review_rate 0.08 → build collapses, review is trivial, feature is cheap.
- Payments feature — compression 5×, review_rate 0.35 → build still collapses, but line-by-line review now dominates the total. Compression barely helps.

No special-casing required. The behaviour falls out of the formula, which is what makes it defensible when a client asks why two similar-looking features are priced differently.

### Coefficient tables (seed values — to be calibrated)

| Compressibility class | Examples | Compression factor (lo/likely/hi) |
| --- | --- | --- |
| **High** | CRUD, greenfield web/SaaS screens, scaffolding, standard documented APIs, tests, docs, config | 5 / 8 / 12 |
| **Medium** | Conventional business logic, common third-party integrations, standard mobile screens | 3 / 4.5 / 6 |
| **Low** | Undocumented legacy, client-proprietary systems, bespoke algorithms, dirty-data migration, pixel-level design craft | 1.5 / 2.5 / 3.5 |
| **None** | Client workshops, approvals, compliance sign-off, physical/manual dependencies, experimental ML iteration | 1 / 1 / 1.2 |

| Review tier | Trigger signals | review_rate (share of manual_baseline) |
| --- | --- | --- |
| **Routine** | No money, no PII, no auth. Spot-review of DB migrations, tests, CI/CD only. | 0.05 / 0.08 / 0.12 |
| **Sensitive** | Money, PII, authentication/authorization, permissions, audit trails. Line-by-line human review. | 0.25 / 0.35 / 0.50 |
| **Critical** | Regulated data (GDPR/HIPAA/PCI), irreversible financial side effects, safety. Line-by-line plus external/compliance sign-off. | 0.45 / 0.60 / 0.85 |

| Clarity score | Meaning | spec_rate | rework_rate |
| --- | --- | --- | --- |
| **High** | Acceptance criteria present, data model implied, edge cases named | 0.08 | 0.10 |
| **Medium** | Feature described in prose, intent clear, details absent | 0.15 | 0.20 |
| **Low** | One line in a transcript, or inferred from context | 0.25 | 0.40 |

Rationale for `spec_rate` rising as clarity falls: under BMad, ambiguity is no longer resolved by a developer asking a question — it gets *confidently implemented*. Vagueness costs more than it did in manual delivery, not less.

### Project-level components

```
planning_agent_h   = BMad workflow execution (compressed): product brief, PRD, UX, architecture, epics & stories
planning_review_h  = artefact_volume × read_review_rate        ← THE FLOOR: 100% human review, no exceptions
env_infra_h        = stack/deployment lookup (largely uncompressed)
qa_h               = platform lookup; mobile uses the mobile-MCP automated-QA coefficient
overhead_h         = (subtotal) × overhead_rate(engagement model)   # ceremony, demos, client comms
```

`planning_review_h` is the module's **high-confidence anchor**. Because the company reviews 100% of planning artefacts without exception, this component is a predictable function of scope volume rather than a guess. The estimator should report it with a visibly narrower band than everything else — it is the part of the number that can be defended hardest.

### Producing the range

Three-point values per coefficient, aggregated with PERT rather than naive summation:

```
mean = (lo + 4×likely + hi) / 6
sd   = (hi − lo) / 6
project_mean = Σ component_means
project_sd   = √(Σ component_sd²)          # independent variance, so ranges don't balloon linearly
reported range = project_mean ± z × project_sd
```

Then a **systematic uncertainty multiplier** derived from the **input completeness score** is applied to the band width (not summed in — it is correlated risk, not independent noise). Input completeness is scored from: document type, presence of acceptance criteria, named integrations, specified stack, stated NFRs, data model detail, and how many features required inference rather than extraction.

This is what mechanically enforces the "no fake precision" constraint: **a two-paragraph input cannot produce a narrow range, because the band width is computed from the input, not chosen.**

### Team and seniority sensitivity

The same feature does not cost the same for every team. A senior-heavy team specifies more precisely, reviews faster, and converges in fewer rework loops; a junior team does the opposite — and under BMad this gap *widens*, because the human contribution is concentrated in exactly the judgement-heavy activities (spec precision, review, knowing when generated code is wrong).

Applied as modifiers on the human-effort components only. `build_h` is largely seniority-independent — the agent writes the code either way.

| Team profile | spec_rate | review_rate | rework_rate | Notes |
| --- | --- | --- | --- | --- |
| **Senior-heavy** | ×0.8 | ×0.8 | ×0.7 | Fewer loops, sharper specs, faster sensitive-tier review |
| **Balanced** (default) | ×1.0 | ×1.0 | ×1.0 | Baseline |
| **Junior-heavy** | ×1.3 | ×1.4 | ×1.6 | Review is slower and less reliable; more loops to converge |
| **New to BMad** | ×1.2 | ×1.2 | ×1.5 | Independent of seniority — a learning-curve modifier that decays over the first projects |

Team composition is an optional input to `est-estimate`, defaulting to the profile in `company-profile.md`. When the assigned team is unknown (typical at presale), the default is used and the assumption is stated explicitly in the output.

### Dependencies, sequencing and calendar duration

**Scope note:** the original decision was hours split by role, no calendar. Adding dependency and sequencing analysis extends that — total hours alone cannot answer "when", because dependent features cannot be parallelized. Calendar duration is therefore produced as a **derived, clearly-labelled secondary output**, not as a commitment. Hours remain the primary deliverable.

- `est-scope-extract` captures **feature dependencies** where the source states or implies them (auth before anything user-specific, data model before reporting, integration before the flows that use it).
- `est-estimate` builds a dependency graph, identifies the **critical path**, and computes **parallelizability** — the maximum useful team width before people start waiting on each other.
- Calendar duration = critical path hours ÷ effective parallel capacity, with an explicit statement of the assumed team shape. Presented as a range, always accompanied by the assumptions that produced it.
- Dependency structure also feeds the **MVP cut-line finder**: dropping a feature that three others depend on is not a saving, and the module must say so.

### Manual-equivalent baseline (internal only)

`Σ manual_baseline` is reported alongside the BMad estimate in internal output, so the team can sanity-check against pre-BMad intuition and legacy actuals. Stripped from client-facing renders by default (`est_show_manual_baseline` config).

### Role allocation

Hours split across **Architect / Dev / QA / BA / UX**. No PM role — PM responsibilities are absorbed by the Architect during the planning phase (company-specific, recorded in `company-profile.md`).

| Component | Default role weights |
| --- | --- |
| `spec_h` | BA 0.5, Architect 0.3, UX 0.2 |
| `build_h` | Dev 1.0 |
| `review_h` (routine) | Dev 0.7, Architect 0.3 |
| `review_h` (sensitive/critical) | Architect 0.6, Dev 0.4 |
| `rework_h` | Dev 0.8, Architect 0.2 |
| `planning_review_h` | Architect 0.5, BA 0.3, UX 0.2 |
| `qa_h` | QA 1.0 |
| `overhead_h` | Architect 0.5, BA 0.5 |


## Skills

Each brief below is self-contained — a builder agent with zero conversation context should be able to work from it alone.

---

### est-scope-extract

**Type:** workflow

**Purpose:** Turn any project input, in any common format, into a normalized **Feature Inventory** in which every line item is traceable back to the source text it came from.

**Core Outcome:** A reviewer can open the Feature Inventory next to the original document and verify, item by item, that nothing was invented and nothing was lost.

**The Non-Negotiable:** **Traceability in both directions.** Every extracted feature cites its source (file, location, verbatim quote). Every part of the source that did *not* become a feature is accounted for in an explicit "not treated as scope" list with a reason. Silent invention and silent omission are the failure modes that kill trust in the whole module.

**Capabilities:**

| Capability | Outcome | Inputs | Outputs |
| --- | --- | --- | --- |
| Ingest and normalize | Any supported file becomes clean markdown with provenance preserved | File(s) or folder: docx, pdf, md, txt, xlsx, csv, pptx, html, email exports | Normalized markdown per source in a working folder, each with a provenance header |
| Multi-tab workbook handling | Spreadsheet backlogs and feature lists keep their structure instead of being flattened to prose | xlsx/csv, multi-tab | Per-tab extraction with headers, row identity and tab names retained |
| Document type recognition | Extraction strategy adapts to what the document actually is | Normalized markdown | Classification: transcript / PRD / SOW / RFP / backlog sheet / brief / mixed |
| Feature extraction | Discrete, estimable features with source citations | Normalized markdown + doc type | Feature Inventory rows: id, name, description, source ref + quote |
| Cross-document dedupe and merge | One inventory from several overlapping documents; conflicts surfaced not silently resolved | Multiple feature sets | Merged inventory with a conflicts list |
| Feature classification | Each feature tagged on the axes the cost model needs | Feature Inventory + `cost-model.md` | size band, compressibility class, review tier, clarity score, novelty flag — each with a one-line justification |
| Sensitive-tier detection | Money / PII / auth / regulated features are caught from document language and flagged for human confirmation | Feature descriptions | Review-tier tags with the triggering phrases quoted, presented for confirmation |
| Gap and ambiguity report | The reviewer sees what the document failed to say | Feature Inventory + doc type | Open questions, unstated assumptions, missing NFRs, unnamed integrations |
| Coverage accounting | Nothing in the source is silently dropped | Source + inventory | "Not treated as scope" list with reasons; input completeness score (0–1) |
| Scope diff | Detect what changed when the client sends v2 of a document | Two Feature Inventories | Added / removed / changed features, with estimate-impact flags |
| Dependency capture | Sequencing constraints are captured while the source is still in view | Normalized markdown + Feature Inventory | Per-feature `depends_on` links, each with the stating or implying evidence, plus inferred-dependency flags for confirmation |
| Agreed-scope classification | Work the sources raise but the contract does not cover is priced separately rather than folded into the agreed number | Feature Inventory + contractual sources | `scope_status` per feature: in_agreed_scope / outside_agreed_scope / no_agreed_scope_defined, operator-confirmed |
| Non-English input handling | Client documents in any language are usable without a manual translation step | Source documents in any language | Feature Inventory in `{document_output_language}`, with the **original-language quote preserved** alongside the translation in every source citation |

**Outputs (files):** `feature-inventory.md` (human review), `feature-inventory.csv` (machine handoff and sales use), `extraction-report.md` (coverage, gaps, open questions, completeness score).

**Memory:** Reads `index.md`, `cost-model.md` (for classification vocabulary), `company-profile.md` (stack familiarity affects compressibility tagging). Writes a `daily/` entry tagged `est-scope-extract`.

**Activation Modes:** Both. Headless for batch presale triage; interactive for confirming sensitive-tier tags and resolving conflicts. The headless contract — detection, a conservative default at each human gate, memlog assumption logging, and a JSON return whose `needs_confirmation` field lets a batch of twenty presale extractions be triaged in minutes — is specified in the built skill's `references/headless.md` and is the pattern the remaining skills should follow.

**Status:** BUILT. `skills/est-scope-extract/` — 4 scripts, 96 unit tests, an 8-document adversarial fixture corpus, and a completed Analyze pass (all 19 findings resolved). The Feature Inventory schema at `assets/feature-inventory.schema.json` is the contract `est-estimate` consumes.

**Tool Dependencies:** Document conversion — `markitdown` (primary, covers docx/pptx/html/pdf), `openpyxl` (per-tab xlsx, already present), `pdftotext` (present, PDF fallback), `python-docx` (docx fallback). Claude's native PDF reading as final fallback for scanned or heavily visual PDFs. Setup skill installs the missing ones.

**Design Notes:**
- Ship the format conversion as a standalone script (`scripts/convert-input.py`) so it is unit-testable and degrades gracefully when a dependency is absent, rather than being inline workflow prose.
- Transcripts need different handling from specifications: features appear as intent and speculation ("they mentioned wanting notifications eventually"), so extraction must record **commitment level**, which feeds the clarity score.
- Spreadsheet backlogs are the highest-signal input shape in presale and deserve dedicated handling — a client-supplied feature list with existing estimates is nearly a finished inventory.
- Classification justifications are one line each and must be in the output. A tag without a reason is a black box, which the user explicitly rejected.
- **Non-English sources: never discard the original.** Traceability means a reviewer who speaks the source language can verify the extraction. Store the original-language quote next to the translation in every citation. Also flag terms that are ambiguous in translation — they are clarity-score inputs, not just linguistic noise.
- **A SOW or RFP defines the agreed scope.** A feature the other sources raise but the contract does not cover (the problem described at length on a call and absent from the scope section) is still extracted and still estimated — the work is real — but carries `scope_status: outside_agreed_scope` so `est-estimate` reports it as an addition. This is a commercial call, not an extraction call: the workflow stops and asks the operator, presenting the feature, its evidence and the three options. Deciding it silently either inflates the agreed price or gives the work away.
- Dependencies are captured here rather than in the estimator because the evidence for them lives in the source text ("once login is in place, users can..."), and it is gone by the time the inventory reaches the estimator. Inferred dependencies must be marked as inferred and confirmed by a human.

**Relationships:** First in the pipeline. Produces the sole input to `est-estimate`. Independently useful — a traceable scope inventory has value even when no estimate follows.

---

### est-estimate

**Type:** workflow

**Purpose:** Turn a Feature Inventory into a defensible, ranged, role-split estimate decomposed along the real BMad delivery phases.

**Core Outcome:** A number a presale lead can put in front of a client and defend line by line, or a delivery lead can plan a sprint against.

**The Non-Negotiable:** **The range must be a consequence of the input, never a choice.** Band width is computed from the input completeness score. Thin input produces a wide range and a loud list of questions — the workflow must be structurally incapable of returning false precision.

**Capabilities:**

| Capability | Outcome | Inputs | Outputs |
| --- | --- | --- | --- |
| Fidelity modes | One engine serves gut-check, presale and delivery use | mode: `quick` \| `presale` \| `delivery` | Estimate at matching resolution and depth |
| Feature-level costing | Per-feature hours from the four-tag classification | Feature Inventory + `cost-model.md` | Per feature: build / spec / review / rework, three-point |
| Project-level costing | The costs no feature list contains | Inventory totals + `company-profile.md` | Planning (agent + 100% human review floor), env/infra, QA, overhead |
| BMad phase decomposition | The estimate explains itself in the process actually used | All components | Hours per phase: brief, PRD, UX, architecture, epics/stories, spec, build, review, QA, retro |
| Role split | Hours allocated to Architect / Dev / QA / BA / UX | Component totals + role weights | Role-by-role hour ranges |
| Range aggregation | Statistically honest totals rather than summed worst cases | Three-point components | PERT mean and sd, variance-summed; band widened by input completeness |
| Manual-equivalent baseline | Sanity check against pre-BMad intuition | Σ manual_baseline | Internal-only comparison and implied compression ratio |
| Risk quadrant flagging | The dangerous work is named, not averaged away | Classified features | Explicit callout of low-compressibility + sensitive/critical features |
| Agreed vs additional split | The client sees one number for what was agreed and a separate one for what was not | `scope_status` per feature | Two subtotals with their own ranges, never silently merged |
| Assumptions and exclusions | What protects the number when challenged | Inventory gaps, config, profile | Structured assumptions list and explicit exclusions list |
| Range-narrowing questions | A thin brief becomes a client follow-up agenda | Gaps + sensitivity analysis | Ranked questions, each with the band-narrowing it would buy |
| Comparables anchoring | The estimate cites your own history | `comparables.md` + classified features | Cited analogues with estimated vs actual, and how they influenced the number |
| Team/seniority sensitivity | The estimate reflects who will actually do the work | Team composition (or `company-profile.md` default) | Modified spec/review/rework hours, with the assumed team profile stated |
| Dependency graph & critical path | Sequencing constraints made visible and priced | Feature `depends_on` links | Dependency graph, critical path, parallelizability ceiling |
| Calendar duration (derived) | Answers "when", clearly separated from "how much" | Critical path + assumed team shape | Elapsed-weeks range, labelled derived, with assumptions stated |
| Sprint capacity fit | Delivery mode answers "does this fit" | Estimate + team shape + sprint length | Fit assessment, overflow, suggested cut lines |
| Ledger write | Every estimate is reproducible later | Full estimate + coefficient snapshot | `ledger/EST-YYYYMMDD-{slug}.md` |
| Multi-format render | Lands wherever it is needed | Estimate model | Markdown doc, CSV/XLSX line items, **interactive HTML report** |

**Outputs (files):** `estimate-{slug}.md`, `estimate-{slug}.csv`, `estimate-{slug}.html`, ledger entry. Optionally writes hour estimates onto generated BMad epics/stories.

**Memory:** Reads `index.md`, `cost-model.md`, `company-profile.md`, `comparables.md`. Writes `ledger/EST-*.md` and a `daily/` entry tagged `est-estimate`.

**Activation Modes:** Both. Headless matters — parallel presales should be batch-estimable overnight.

**Tool Dependencies:** `openpyxl` for XLSX output. HTML report is self-contained, no external runtime.

**Design Notes:**
- **Snapshot the coefficients into the ledger entry.** Without this, calibration cannot distinguish a bad estimate from a model that has since changed.
- `quick` mode must genuinely be fast — coarse size bands, skip comparables retrieval, skip HTML, return an order-of-magnitude band with a stated confidence. Its job is a go/no-go call in minutes.
- The HTML report should be **interactive**: toggle features on and off and watch the range recompute. That turns the estimate into a live scope-negotiation and MVP-cut-line tool rather than a static PDF.
- Every hour in the output traces to a feature, and every feature traces to source text. The chain from client sentence → line item must be unbroken.
- **Calendar duration is a derived secondary output, never the headline.** Hours are the deliverable; duration depends on team shape the module cannot know at presale. Always render it with its assumptions attached, never as a bare date.
- The MVP cut-line finder must be dependency-aware: dropping a feature that others depend on is not a saving.
- Render the `planning_review_h` band visibly tighter than the rest — it is the most defensible component and showing that builds trust in the whole number.

**Relationships:** Consumes `est-scope-extract` output. Feeds `est-calibrate` via the ledger. Orchestrated by `est-agent-estimator`, but fully usable standalone.

---

### est-calibrate

**Type:** workflow

**Purpose:** Turn real spent hours — however messy or partial — into evidence-backed adjustments to the cost model.

**Core Outcome:** The estimator gets measurably better after every project, and can show exactly why a coefficient changed.

**The Non-Negotiable:** **No silent model drift.** Every coefficient change is human-approved, logged with its evidence and sample size, and reversible. The model is the company's asset; it must never mutate behind their back.

**Capabilities:**

| Capability | Outcome | Inputs | Outputs |
| --- | --- | --- | --- |
| Ingest actuals | Whatever time data exists becomes usable | Time-tracking exports (csv/xlsx), Jira exports, retro notes, or a typed project total | Normalized actuals with a stated granularity level |
| Partial-data reconciliation | Works when only project-level totals exist | Actuals + ledger entry | Allocation of the total across components using estimated proportions, flagged as inferred |
| Delta analysis | Where the model was wrong, specifically | Actuals vs ledger snapshot | Per-phase, per-compressibility-class, per-review-tier deltas |
| Systematic bias detection | Distinguish a pattern from a bad project | Deltas across ledger entries | Bias findings with sample size and confidence; outliers separated |
| Coefficient proposals | Concrete, justified, reviewable changes | Bias findings | Proposed old → new values with evidence and expected effect on past estimates |
| Human approval gate | Nothing changes without a decision | Proposals | Accepted / rejected / deferred, each recorded |
| Model and log update | The change is applied and auditable | Approved proposals | Updated `cost-model.md`, appended `calibration-log.md` |
| Comparables capture | Closed projects become anchors for future estimates | Ledger entry + actuals | New `comparables.md` entries |
| Backtest | Sanity-check a change before accepting it | Proposed model + past ledger entries | How past estimates would have scored under the new coefficients |
| Estimate-vs-actual report | The retro artefact | Ledger + actuals | Shareable HTML/markdown accuracy report |

**Memory:** Reads `ledger/`, `cost-model.md`, `comparables.md`. Writes `cost-model.md` (approved only), `calibration-log.md`, `comparables.md`, `daily/` tagged `est-calibrate`.

**Activation Modes:** Interactive only by default — the approval gate requires a human. A headless `--report-only` variant produces the analysis without touching the model.

**Design Notes:**
- Must be **useful on day one with almost nothing**. The company has messy, partial, sometimes project-level-only actuals. A calibrator that demands story-level time tracking will simply never be run.
- **Backtesting is the trust mechanism.** "This change would have improved 7 of your last 9 estimates" is what makes someone click approve.
- Guard against overfitting to a single unusual project — always report sample size, and require a configurable minimum before proposing a change as anything other than a weak signal.
- Natural pairing with `bmad-retrospective`; the retro is when actuals are freshest and someone is already reflecting.

**Relationships:** Reads the ledger est-estimate writes. Feeds `est-agent-estimator` through `accuracy-brief.json`.

**Status:** BUILT. `skills/est-calibrate/` — 6 scripts, 140 unit tests, 15 ground-truth recovery cases, and a completed Analyze pass.

**Two doors into the cost model, one directory.** `apply.py` moves a coefficient on backtested actuals and refuses anything less. `curate.py` carries the change that bar cannot: a coefficient a delivery lead knows is wrong before any project has closed, so no backtest can exist. It takes the same backup, the same log, the same TTY-only approval and the same mandatory reason, stamps the entry `judgement` rather than calibrated, and re-prices the entire ledger first so the effect on estimates already sent to clients is visible before anyone accepts it. Refusing that change would not have prevented it — it would have sent someone to a text editor, where there is no backup, no provenance and no way back. Both writers live in one directory so the claim "only this writes the cost model" stays verifiable by looking.

**Validated by recovery, not by waiting.** The original plan said this skill could not be validated until real projects closed. That turned out to be avoidable: `evals/ground-truth.py` perturbs a copy of the cost model, generates actuals from the perturbed model, runs the calibrator over ledger entries priced with the *unperturbed* one, and asserts it recovers the bias in the right coefficient and direction. Because the answer is known in advance this is stronger evidence than a handful of real projects would give, and it tests the failure directions that matter more than the successes — that a correct model produces no proposals, that one outlier moves nothing, and that a harmful change is visibly harmful.

**Four statistical defects that validation caught before they could reach a real project:**

1. **Band-width detection was chasing its own noise.** The residual-spread statistic is itself noisy at small samples — over eight projects an observed 1.13 is indistinguishable from 1.0 — and the original fixed dead-band ignored sample size. It now scales as `max(0.15, 1.5/√n)`.
2. **Bias and band width were double-counting.** Estimates all wrong by the same +23% produce *very consistent* residuals, so measuring spread naively concluded the band was too wide and proposed narrowing it — making a systematically biased model confidently biased. Spread is now measured on debiased residuals.
3. **The backtest called a harmful change neutral.** Narrowing a band leaves every central figure untouched, so an error-only verdict missed a change that would have collapsed band coverage from 71% to 14%. The verdict now weighs band movement, asymmetrically: too narrow promises precision the model lacks, too wide is merely uninformative.
4. **The band-hit target was hardcoded at 68%** while being a function of the model's own `uncertainty.z` — which the cost model explicitly invites raising to 1.28 for an 80% band. Anyone taking that advice would have had correctly calibrated ranges judged far too wide. It is now derived as `erf(z/√2)`.

**What it can and cannot learn, by data granularity.** This is the module's real constraint and worth stating plainly to anyone asking why per-tier calibration is not available yet:

| Capture | Unlocks |
| --- | --- |
| One `delivery_hours` total per closed project | Band width and overall sizing scale |
| Hours by BMad phase | planning review, planning, environments, QA and overhead coefficients |
| Hours per feature | Review tier and compressibility — the module's core IP |
| Hours per role | The role-weight split |

Separating review tier and compressibility from project totals alone requires projects of genuinely different shape — a payments-heavy one and a CRUD-heavy one — not simply more of the same. Twelve identical projects carry the information of one, so the regression gate is a range check on tier mix rather than a sample-size check.

---

### est-agent-estimator

**Type:** agent

**Persona:** A seasoned delivery lead who has estimated outsourcing projects for years and now runs them with BMad. Numerate, direct, and allergic to false precision. Will say "that input doesn't support a number that tight" and then tell you exactly which three questions would fix it. Treats the client's challenge as a normal part of the job, not an attack. Never pads silently — if there is risk, it is a named line item.

**Core Outcome:** A human leaves the conversation with a number they understand well enough to defend to someone who does not want to hear it.

**The Non-Negotiable:** **Never assert a number without being able to decompose it on demand.** Every figure must break down to features, coefficients and source text within one follow-up question.

**Capabilities:**

| Capability | Outcome | Inputs | Outputs |
| --- | --- | --- | --- |
| Conversational intake | Scope that exists only in someone's head becomes estimable | Verbal description, no documents | A structured Feature Inventory built through targeted questioning |
| Pipeline orchestration | One request runs extract → estimate end to end | Files, folder, or conversation | Full estimate with the intermediate artefacts preserved |
| Explain any line item | Trust through decomposition | A question about any number | The chain: hours → coefficients → classification → source quote |
| Defend under challenge | Rehearse the client conversation before having it | "The client says this should be half" | Where the give genuinely is, where it is not, and the consequence of each cut |
| What-if scenarios | Scope decisions made with numbers attached | Proposed changes (drop a feature, change tier, change team) | Recomputed range plus what shifted and why |
| MVP cut-line finder | The cheapest coherent subset that still ships | Inventory + target budget or date | Recommended subset, what is deferred, dependency warnings |
| Model curation | The cost model stays the company's own | User corrections and observations | Edits to `cost-model.md` / `company-profile.md`, with a `calibration-log.md` entry |
| Presale triage | Attention goes to the right deal first | Several pending inputs | Ranked by effort-to-estimate, deal risk, and danger-quadrant content |
| Bid / no-bid signal | Dangerous deals are visible before they are won | Completed estimate | Risk read: danger-quadrant share, uncertainty width, unresolved dependencies |
| Sanity challenge | A second opinion on someone's gut number | A human estimate | Where the model disagrees and which of them is more likely wrong |

**Memory:** Reads `index.md` on activation, then loads selectively — `cost-model.md` and `company-profile.md` for any estimation work, `comparables.md` when anchoring, `ledger/` when discussing a specific past estimate. Writes `daily/` tagged `est-agent-estimator`; curates the portable pack files on explicit user instruction.

**Init Responsibility:** On first run, verify `_bmad/memory/est/` exists and is seeded. If `company-profile.md` is still at defaults, run a short profile interview (team shape and seniority, dominant stacks, BMad adoption depth per team, QA capabilities including mobile-MCP automated QA, typical client engagement model) — because generic industry numbers are one of the four things the user said would make them abandon the tool.

**Activation Modes:** Interactive primarily. Headless supported for "estimate this folder and report" batch runs.

**Tool Dependencies:** Same document-parsing chain as `est-scope-extract`, invoked through that workflow rather than reimplemented.

**Design Notes:**
- The agent orchestrates but is never required — every workflow runs standalone and headless. The agent must not become a bottleneck for batch presale processing.
- The **defend-under-challenge** capability is the one most likely to be used daily and least likely to be anticipated. It is where an estimate stops being a spreadsheet output and becomes usable in a commercial conversation.
- When the model and the human disagree, the agent's job is to locate the disagreement precisely, not to win. A human who has run twenty of these projects often knows something the coefficients do not — and that is a calibration input, not an error.

**Relationships:** Front door to all three workflows. Built last — it needed all three to exist before it had anything to orchestrate, explain or curate.

**Status:** BUILT. `skills/est-agent-estimator/` — Nadia, Delivery Estimator. Stateless, 2 scripts, 61 unit tests, 10 adversarial eval cases, and a completed Analyze pass.

**Stateless, deliberately.** The module already owns durable state at `_bmad/memory/est/`, written under audit by the three workflows. A sanctum would have been a second memory surface holding the same facts, and the one nobody audits is the one that drifts. The agent's continuity comes from the ledger, not from remembering.

**The two scripts exist because the alternative is arithmetic.** `scenario.py` re-prices every what-if — a dropped feature, a retagged review tier, a senior team, a change request, a budget target — through est-estimate's own engine, and refuses outright unless it can first reproduce the estimate's own headline from its own snapshot. On the module's own end-to-end fixture, dropping one 58.8-hour feature changes the project by 89.4 hours, because planning review, QA and overhead scale with the scope that remains: a 52% error, in the direction that reads plausible, and one a conversational agent would make every time. `portfolio.py` reports the state of every workspace and ledger entry in one pass — what is stale, what was quoted before the scope changed, which won project never came back with hours.

**The cut-line finder went through three versions before it was honest.** The first overshot, taking a cheap outside-scope cut and then a large one that would have sufficed alone — so a client was asked to give something up for nothing; a prune pass now puts back everything the budget did not need. The second reached for the biggest saving first and proposed cutting payments to reach a number three peripheral features would have covered. The third judged candidates on savings measured against the untouched baseline, which overstate what a candidate still buys once its dependency closure is partly gone. Every decision figure is now a real re-price of the current scope, and the invariant is tested: putting any proposed cut back breaks the budget.

---

## Configuration

Collected by the module setup skill (`est-setup`) and written to the `est` section of the BMad config.

| Variable | Prompt | Default | Result Template | User Setting |
| --- | --- | --- | --- | --- |
| `est_output_folder` | Where should estimates be written? | `{output_folder}/estimates` | path | yes |
| `est_default_fidelity` | Default estimate depth when not specified | `presale` | `quick` \| `presale` \| `delivery` | yes |
| `est_output_formats` | Which formats to render by default | `md,csv,html` | comma list | yes |
| `est_show_manual_baseline` | Include the human-only comparison in client-facing renders? | `false` | boolean | yes |
| `est_roles` | Roles to split hours across | `architect,dev,qa,ba,ux` | comma list | yes |
| `est_knowledge_pack_source` | Shared location for the portable cost model (blank = local only) | *(blank)* | git URL or path | yes |
| `est_min_calibration_samples` | Minimum matching projects before a coefficient change is proposed as more than a weak signal | `3` | integer | yes |
| `est_sprint_length_days` | Default sprint length for delivery-mode capacity fitting | `10` | integer | yes |
| `est_default_team_profile` | Team seniority profile assumed when the assigned team is unknown | `balanced` | `senior-heavy` \| `balanced` \| `junior-heavy` | yes |
| `est_report_calendar_duration` | Include derived calendar duration alongside hours | `true` | boolean | yes |

**Note on `est_knowledge_pack_source`:** the user chose local-only for now. The sync mechanism ships but is unconfigured by default; the module is fully self-contained on seeded coefficients until someone points it at a shared source.

**No commercial configuration.** Rates, currency and margin are deliberately out of scope — the module outputs hours split by role and nothing more. Pricing stays with the sales team.

## External Dependencies

Document parsing. The user chose **auto-install at setup**.

| Dependency | Purpose | Status on this machine | Setup action |
| --- | --- | --- | --- |
| `markitdown` | Primary converter: docx, pptx, html, pdf → markdown | missing | install via `uv`/`pip` |
| `python-docx` | docx fallback with better structural fidelity | missing | install |
| `pdfplumber` or `pypdf` | PDF text and table extraction | missing | install |
| `openpyxl` | Per-tab xlsx extraction preserving workbook structure | **present** | verify only |
| `pdftotext` (poppler) | PDF fallback | **present** | verify only |
| Claude native PDF reading | Final fallback for scanned or heavily visual PDFs | built in | none |

Setup detects, installs what is missing, and records which converters are available so `est-scope-extract` can degrade gracefully rather than fail.

**Not a dependency, but relevant:** the company uses a **mobile MCP server** for automated mobile QA. The module does not call it — it encodes its effect as a QA coefficient in `cost-model.md`. Setup should ask whether mobile automated QA is in use, since it materially changes mobile estimates.

## UI and Visualization

**Interactive HTML estimate report** — the module's main visual surface, produced by `est-estimate`, self-contained and shareable.

Contents:
- Headline range with confidence, and the input completeness score that produced the band width
- Feature breakdown, sortable and filterable by compressibility class and review tier
- **BMad phase decomposition** — brief, PRD, UX, architecture, epics/stories, spec, build, review, QA — which is what makes the number legible to a client
- Role split across Architect / Dev / QA / BA / UX
- **Risk quadrant view** — low-compressibility × sensitive/critical features called out visually rather than averaged into the total
- Assumptions and exclusions
- Ranked range-narrowing questions with the band-tightening each would buy
- Traceability: every line item expandable to the source quote it came from
- Dependency graph with the critical path highlighted, and the derived calendar-duration range with its assumptions
- Manual-equivalent comparison (internal renders only, per `est_show_manual_baseline`)

**The interactive element is the point.** Toggling features on and off recomputes the range live, which turns the report from a static document into a scope-negotiation and MVP-cut-line tool that a presale lead can drive in a client call.

`est-calibrate` produces a second, simpler report: estimate-vs-actual accuracy over time, per phase and per feature class.

Both are good candidates for publishing as shareable artifacts.

## Setup Extensions

Beyond writing config, `est-setup` must:

1. **Scaffold and seed memory** — create `_bmad/memory/est/` with `index.md`, the default `cost-model.md` (from a module asset, so defaults are versioned and diffable), an empty `comparables.md`, `calibration-log.md`, and `ledger/`.
2. **Run the company profile interview** — team shape and seniority mix, dominant stacks, BMad adoption depth per team, QA capabilities (explicitly asking about mobile-MCP automated QA), typical client engagement model, and the confirmed fact that the Architect absorbs PM responsibilities. Writes `company-profile.md`. This directly answers the user's "ignoring our context" failure mode.
3. **Install and verify parsing dependencies**, recording what is available.
4. **Optionally pull the knowledge pack** if `est_knowledge_pack_source` is configured; otherwise seed locally.
5. **Create the estimates output folder.**

## Integration

**Standalone module.** It provides value with no other BMad module present — point it at an RFP, get a traceable scope inventory and a ranged estimate.

**But it is designed to sit in front of the BMM pipeline.** The Feature Inventory is deliberately shaped to feed `bmad-prd` and `bmad-create-epics-and-stories`, and `est-estimate` can write hour estimates directly onto generated epics and stories. The natural end-to-end flow:

```
RFP / transcript / SOW
   → est-scope-extract   → Feature Inventory
   → est-estimate        → ranged estimate  →  proposal
   → (deal won)
   → bmad-product-brief → bmad-prd → bmad-architecture → bmad-create-epics-and-stories
   → est-estimate (delivery mode, now with real epics)  → refined per-epic hours
   → bmad-spec → bmad-build → bmad-review
   → bmad-retrospective + est-calibrate → model improves
```

The loop closing through `bmad-retrospective` into `est-calibrate` is what makes the module compound in value rather than plateau.

## Creative Use Cases

- **Live scope negotiation.** Open the interactive HTML report in the client call and toggle features until the range meets the budget. The conversation stops being "your number is too high" and becomes "which of these do you want".
- **MVP cut-line finder.** Cheapest coherent subset that still ships, with dependency warnings for features that cannot be dropped alone.
- **Scope-creep detection.** Re-run `est-scope-extract` on v2 of a client document and diff the inventories. Added scope becomes visible and priceable instead of absorbed silently — a recurring outsourcing wound.
- **Bid / no-bid signal.** A deal whose scope is dominated by the low-compressibility × sensitive quadrant is a deal where BMad's advantage is smallest. Worth knowing before winning it.
- **Presale portfolio triage.** Several pending inputs ranked by effort-to-estimate and deal risk, so attention goes to the right one first.
- **Estimator training.** A junior produces a gut estimate, then compares against the model's decomposition. The disagreements are the lesson.
- **Change-request pricing mid-delivery.** Single-feature mode against an in-flight project, anchored on that project's own actuals.
- **Sprint capacity fitting.** Delivery mode answers "does this fit in the next sprint" with a range and a cut list rather than a yes.
- **Proving the BMad case internally.** Accumulated estimate-vs-actual data across projects becomes the evidence that the method works — or the honest signal about where it does not.
- **Post-mortem on a lost deal.** Compare the estimate against the competitor's winning price to learn where the model or the positioning was off.

## Build Standards (established while building skill #1)

These emerged from building and analysing `est-scope-extract` and apply to every remaining skill.

**1. Analyze is a build gate, not an option.** `est-scope-extract` passed lint, 54 unit tests and a real-input eval while carrying a critical defect: workbook citations pointed at the wrong row, because the converter renumbered rows after filtering blanks and promoted a title banner to the header. The eval missed it because the output *read* correctly. Run the five Analyze lenses over every skill before it ships.

**2. Adversarial fixtures, not just realistic ones.** A realistic fixture confirms the happy path; an adversarial one targets output that reads correctly while being wrong. The corpus lives at `skills/est-scope-extract/evals/` (generated by `build-fixtures.py`, so it stays diffable) and is reusable: the inventories it produces are the natural input fixtures for `est-estimate`, and its contradictions and thin briefs are exactly the cases where an estimate's band width should visibly move.

**3. Verify the guarantee, do not assert it.** Any claim a skill makes about its own output must be checked mechanically against the source. In `est-scope-extract` that meant re-opening the converted documents to verify every quote, resolve every structured location against an anchor the file really has, list unreferenced regions, and reconcile the conversion manifest against the inventory. `est-estimate` has the analogous obligation: every hour must trace to a feature, and every feature to a citation — checked, not assumed.

**4. Judgement inputs are held to the same standard as coefficients.** The completeness score was described as immune to judgement while most of its weight came from unexplained model-set signals. Every input that moves a number carries a one-line `why`, enforced by script. `est-estimate` will face this repeatedly, since the whole cost model is coefficients over judgement calls.

**5. Every human gate needs a stated unattended default.** A check that will not clear until a human decides something, beside a rule forbidding the agent from deciding it, deadlocks a batch run — or worse, gets resolved silently. Each gate names its conservative default, logs it as a memlog `assumption`, and surfaces it in `needs_confirmation`.

**6. Deterministic work goes in scripts, including the merge.** If a script already computes what a prompt is about to reconstruct, have the script emit it. `inventory-diff --merge` exists because the model was otherwise retyping verbatim quotes by hand on every update run — over exactly the strings the traceability guarantee depends on.

**7. Never let two pieces of code compute the same quantity.** In skill #2 the sensitivity analysis re-derived the estimate band with a different formula from the headline, so every reported figure became the gap between two formulas rather than the value it claimed to measure. The interactive report's JavaScript separately drifted from the engine and rendered half the real range. Both were fixed by making one definition and verifying the boundary by execution. Where duplication is unavoidable — a browser recompute — an executed parity harness guards it.

**8. Enforce a guarantee in the tooling, not in prose.** "Headless never writes to the cost model" was true only while the agent still carried the sentence saying so; `apply.py` now refuses to run without a terminal, with no override. A rule a compaction can drop is not a guarantee.

**9. Validate statistical claims against synthetic ground truth.** Perturb a model, generate data from it, and check the analysis recovers the perturbation — and equally that it proposes nothing when there is nothing to find. Four real defects in skill #4 surfaced this way, none of which a realistic-looking test would have caught.

**10. A refusal that does not prevent the act makes it worse.** "The agent may never change a coefficient" reads like a safety rule and functions as a hole: with no actuals to backtest against, the seed model cannot be corrected, so someone opens `cost-model.json` in an editor and the change lands with no backup, no reason and no way back. The rule that survives contact is a second door held to the same standard as the first — logged, backed up, reversible, and labelled `judgement` so nobody later mistakes it for evidence.

**11. Every re-price goes through the engine, including the ones inside a heuristic.** A search that proposes cuts to reach a budget makes dozens of intermediate decisions, and the temptation is to rank candidates on figures computed once against the original scope. Those figures stop being true the moment anything is dropped. Both the reported numbers and the decisions behind them have to be genuine re-prices, or the search picks a cut on a number that is no longer real.

**12. Test the invariant, not the output.** The cut-line's tests do not assert a particular set of features; they assert that the budget is met, that no proposed cut can be restored without breaking it, and that every step's cumulative figure equals an independent re-price of the remaining scope. Three separate ordering bugs shipped through tests that checked totals; the invariants caught all three.

## Build Roadmap

**Recommended order, with rationale:**

**1. `est-scope-extract`** — Everything downstream consumes its output, so it is the schema-setting decision. It is also the most testable in isolation (feed it a real RFP, check the inventory against the document by hand) and delivers standalone value immediately: a traceable scope inventory is useful even before any estimate exists. Building it first also forces the Feature Inventory format to be settled before anything depends on it.

**2. `est-estimate`** — The core value and the module's whole reason for existing. Needs the inventory format from step 1 and defines the seed `cost-model.md` that everything else reads. Build `quick` and `presale` modes first; `delivery` mode and sprint fitting can follow once real epics exist to test against.

**3. `est-agent-estimator`** — Needs both workflows to exist before it has anything to orchestrate or explain. Its highest-value capabilities (explain, defend, what-if) only make sense against real estimates produced by step 2.

**4. `est-calibrate`** — Necessarily last. It cannot be validated until the ledger has real entries and at least a few projects have closed with actuals. Building it earlier would mean building against imagined data.

**Suggested proving ground:** once steps 1 and 2 are built, run them against two or three genuinely different past inputs — a thorough SOW, a thin transcript, and a multi-tab backlog workbook — and compare the output to what those projects actually cost. That is the fastest route to knowing whether the seed coefficients are in the right neighbourhood, and it is also the first real data for step 4.

**What was actually built, and in what order.** 1, 2, 4, 3 — `est-calibrate` came third rather than last. The roadmap put it last on the grounds that it could not be validated until real projects closed, and that turned out to be avoidable: perturbing the model and checking the calibrator recovers the perturbation is stronger evidence than a handful of real projects, and it tests the failure directions that matter more than the successes. `est-agent-estimator` moved to last for a better reason than the plan gave — it needed `est-calibrate` to exist so its model-curation capability had somewhere to route rather than somewhere to reimplement.

**Module packaged.** `skills/est-setup/` — 3 scripts, 18 tests. `module.yaml` carries the ten settings, the agent roster and the directories to create; `module-help.csv` registers eleven capabilities into `_bmad/_config/bmad-help.csv`.

**Two deviations from the module-builder template, both forced by this installation.** The stock `merge-config.py` writes `_bmad/config.yaml`, but BMad here reads a four-layer TOML stack through `resolve_config.py` — the scaffolded setup would have reported success and configured nothing. It was replaced with a TOML writer targeting `_bmad/custom/config.toml`, the layer the installer never regenerates, verified by reading the values back through BMad's own resolver. And `cleanup-legacy.py` was deleted rather than shipped: its documented invocation removes `_bmad/core/` and `_bmad/_config/`, and the second holds `bmad-help.csv` — the catalog the setup had just written into. There is no legacy here to migrate.

**Two validator findings are limitations of `validate-module.py`, not of the module.** It has no notion of `_meta` rows, though three installed modules ship one and `bmad-help` reads them for module documentation; and its `parse_yaml_minimal` strips indentation, so the nested `name:` in the agents roster overwrites the module's own — it reports the module as being called "Nadia". Both were confirmed against a real YAML parse and the installed catalog.

**Next steps:**

1. Run `est-setup` to register the module in this project.
2. Ask Nadia to run the company profile interview. Generic coefficients priced against the wrong team shape are the first thing that costs the tool its credibility.
3. Start capturing three fields on every closed project now: `delivery_hours`, `scope_delivered`, and `excluded_hours` with its reason. Nothing else in this module compounds until those exist, and reconstructing them later is what makes them never happen.
4. Run the proving ground above against two or three genuinely different past inputs, to find out whether the seed coefficients are in the right neighbourhood.
