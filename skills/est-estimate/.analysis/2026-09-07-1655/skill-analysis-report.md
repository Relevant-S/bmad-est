# Analysis Report: skills/est-estimate

Generated: 2026-09-07 · Schema: 2

**Grade: Excellent**

> All twenty-two findings resolved, including two criticals that had the client-facing report showing half the real range and every range-narrowing question reporting a phantom saving.

est-estimate's arithmetic, cost model and traceability are sound, and the lenses confirmed no script infers meaning and no prompt does arithmetic. Its real weakness was duplication: the interactive report reimplements the aggregation in JavaScript so scope can be cut against a live number, and that copy had silently drifted — omitting the systematic model-risk term and rendering a band roughly half the document's, beneath a headline that included it. A mean-only runtime self-check could not see it and no test executed the JavaScript, so 73 unit tests and 8 adversarial cases all passed. The same divergence had corrupted the sensitivity analysis, making every question's value the gap between two formulas rather than the worth of an answer. Both are fixed at the root by a single shared band definition, and an executed parity harness now guards the boundary — it found a second drift within an hour. 90 unit tests now pass.

| Severity | Count |
| --- | --- |
| Critical | 2 |
| High | 8 |
| Medium | 9 |
| Low | 3 |

## Themes

### 1. Duplicated model logic drifted, and nothing was watching the boundary

- Root cause: The report re-implements the aggregation in a second language so a presale lead can negotiate against a live number. That is a real capability, but the copy was guarded only by a runtime self-check comparing means — blind to the band, which is the module's headline claim — and by a test that string-matched the check's own error message. Two independent drifts were found within an hour of writing an executed check.
- Fix: Keep one definition of every computed quantity, mirror it explicitly where it must be duplicated, and verify the boundary by executing both sides rather than asserting parity in prose.
- Findings:
  - `determinism-1` The interactive report rendered half the real band, and its self-check could not see it — `assets/report-template.html (compute) vs scripts/estimate.py`
  - `determinism-3` Cross-language parity was asserted by string match; no test ever executed the JavaScript — `scripts/tests/test-render-estimate.py; assets/report-template.html`
  - `architecture-1` The render step dropped the profile inputs, so the live recompute used industry defaults — `SKILL.md (Render and record); scripts/render-estimate.py`

### 2. A second formula for the same quantity corrupted the sensitivity analysis

- Root cause: narrowing_questions re-derived the band by hand instead of calling the same function as the headline, so every reported reduction was the difference between two definitions. It is the same root cause as the JavaScript drift, in pure Python and inside one file.
- Fix: band_half_width() is now the single definition; a regression test asserts a no-op change removes no band, which is what the old tests could not detect.
- Findings:
  - `determinism-2` Every range-narrowing question reported a phantom saving; the ranking was noise — `scripts/estimate.py (narrowing_questions)`

### 3. Wiring gaps left a correct run dependent on the agent guessing

- Root cause: The workspace token was used and never defined, the cost-model guide was never routed to, the render step dropped the profile inputs, the memlog was appended to but never created, and the one blocking dependency named no fallback. Each is small; together they meant a correct run relied on inference rather than instruction.
- Fix: Bind every token used, route every carved file from its point of use, let artifacts carry their own inputs downstream, and give the one blocking dependency a stated fallback.
- Findings:
  - `architecture-2` {workspace} was used six times and never defined; {output_folder} was declared and never used — `SKILL.md (Resolution rules, Estimating)`
  - `architecture-3` references/cost-model-guide.md was orphaned — nothing ever loaded it — `SKILL.md`
  - `architecture-5` The memlog was referenced by the headless path but owned by no one — `SKILL.md; references/headless.md`
  - `enhancement-1` headless.md appended assumptions to a memlog nothing ever created — `SKILL.md; references/headless.md`
  - `enhancement-3` The one blocking dependency was hard-pathed with no fallback — `SKILL.md (Validate before pricing)`
  - `customization-1` {output_folder} declared but unwired under a declined-customization build — `SKILL.md (Resolution rules)`

### 4. Reasoning was dropped on the way to the number

- Root cause: The module demands a `why` on every judgement input, then discarded them when pricing — along with the verbatim quotes — leaving skill #3 unable to defend a figure without re-joining the inventory by hand.
- Fix: Carry the reasoning through, and give the conversational consumer a distillate rather than the ledger payload.
- Findings:
  - `enhancement-2` The estimate discarded every tag's reasoning and the verbatim quotes — `scripts/estimate.py (price_feature)`

### 5. The entry file carried content its references already owned

- Root cause: Argument that belongs where it becomes actionable — beside a coefficient someone is about to edit — sat in the always-paid entry file, partly because the file that should have owned it was never loaded.
- Fix: Route the reference from its points of use, then let it own the argument and keep only the clause that changes a move.
- Findings:
  - `leanness-1` The bar re-taught arithmetic the script owns, in the most expensive file — `SKILL.md (The bar)`
  - `leanness-2` The ledger-snapshot gotcha changed no move the model makes — `SKILL.md (Gotchas)`
  - `leanness-3` The guide's profiles section restated the seed's own why fields — `references/cost-model-guide.md`
  - `leanness-4` 'Uncalibrated' was stated three times across two files — `SKILL.md; references/cost-model-guide.md`
  - `leanness-5` The estimate.py capability enumeration was meta-explanation — `SKILL.md (Compute)`
  - `leanness-6` headless.md restated its own trigger and re-argued its why three times — `references/headless.md`

## Strengths

- The central modelling insight is protected by tests that fail loudly if anyone 'simplifies' it: review_h is a share of manual_baseline, so compression shrinks the build and leaves review untouched, and a payments feature stays expensive while CRUD collapses without a line of special-casing.
- Band width is computed from the inventory's completeness score rather than chosen, so a thin brief is structurally incapable of producing a narrow range — verified across the full completeness sweep.
- The planning-review anchor is demonstrated rather than asserted: it carries the tightest relative band of any phase, and the coefficients were tightened when a test showed the original claim did not hold at scale.
- Two honest corrections that a plausible-looking model would have shipped: build compression is reported separately from project compression, and systematic model error is added in quadrature so the band does not collapse as features multiply.
- The whole cost model is snapshotted into every ledger entry, so a later coefficient change can never rewrite the past and calibration can attribute a delta to the estimate rather than the model.
- Every coefficient carries its own `why` in cost-model.json, which the customization lens confirmed is a legitimate memory-seeded dataset rather than a customization surface in disguise.

## Recommendations

1. No outstanding work. Carry the executed-parity discipline into skill #3, and keep check-parity.py in the render step.

## Experience

- **Presale estimate** — Validate the inventory, settle team/stack/QA/engagement, compute, read the risk quadrant and scope split, render four projections, record a draft ledger entry, present the range with the completeness score that set its width.
- **Client scope negotiation** — Open the interactive report in the call and untick features until the range meets the budget — project overheads shrink with the scope, and standalone_hours says what dropping it really saves.
- **Go/no-go** — quick mode: totals, splits and risk quadrant in minutes, skipping dependencies, duration and sensitivity.
- **Batch presale triage** — Headless across many inventories; needs_attention says which of twenty estimates a human actually has to look at.
- Headless: Specified in references/headless.md: detection, a conservative default at each of seven gates including two hard stops, a memlog assumption per defaulted profile input, and a JSON return whose needs_attention field carries the scope share, risk-quadrant features and assumptions made.

## Findings

### Critical (2)

#### determinism-1 — The interactive report rendered half the real band, and its self-check could not see it

- Lens: determinism
- Location: `assets/report-template.html (compute) vs scripts/estimate.py`
- Evidence: The engine combines feature variance with a systematic model-risk term in quadrature; the JavaScript computed feature variance alone. Reproduced on a six-feature fixture: the file said 402–608–813 while the page rendered 501–608–714 — 52% of the real range, under a headline that included it. The runtime self-check compared only the mean, which matched exactly, so it never fired. model_risk was added to the engine after the template was written, and the manual node check had been run before that change.
- Recommendation: APPLIED. Fixed at the root rather than in both copies: band_half_width() in estimate.py is now the single definition of the band, the JS mirrors it explicitly, and the self-check compares low, likely and high rather than the mean alone. A second, smaller drift surfaced immediately afterwards — the JS was reading the display-rounded band multiplier back out of the confidence block — and it now derives the multiplier from the model's own formula.

#### determinism-2 — Every range-narrowing question reported a phantom saving; the ranking was noise

- Lens: determinism
- Location: `scripts/estimate.py (narrowing_questions)`
- Evidence: The sensitivity analysis computed its baseline with a different formula from the headline — without the model-risk term — so every reported reduction carried that whole term. Measured: a no-op mutation reported a 198h (48.3%) saving, and all six real questions reported an identical 205h (49.9%) against a true value near 6h. The output told a presale lead that answering any one question would halve the band. The existing tests passed trivially: identical values still sort descending, and phantom hours are still greater than zero.
- Recommendation: APPLIED. Both sides now call band_half_width(), so there is one definition. Question values on the same fixture dropped from 205h (49.9%) to 17.5h (4.3%), and on the real Northwind inventory they now differentiate properly — 50.5h for the ML feature's acceptance criteria against 10.6h for confirming a payment tier. Added a regression test asserting a no-op change removes no band, and one asserting no single question exceeds 25% of it.

### High (8)

#### determinism-3 — Cross-language parity was asserted by string match; no test ever executed the JavaScript

- Lens: determinism
- Location: `scripts/tests/test-render-estimate.py; assets/report-template.html`
- Evidence: The test called JS/Python parity the load-bearing property and then asserted the template contained the literal string 'Recompute mismatch'. Nothing ran the JS, which is precisely why determinism-1 survived 73 unit tests and 8 adversarial end-to-end cases: the JavaScript reimplements plan_volume, planning_cost, project_components, by_phase, by_role and the PERT aggregation with no executable check on any of it.
- Recommendation: APPLIED. scripts/check-parity.py extracts the report's own computation block between PARITY markers — the same source the browser runs, not a copy — executes it under node, and compares the full interval plus every phase and role total. Verified it fails on the real defect: reintroducing the model_risk omission produces a 99h drift. Wired into the render step and covered by test-check-parity.py, including a test that the harness itself can fail.

#### architecture-1 — The render step dropped the profile inputs, so the live recompute used industry defaults

- Lens: architecture
- Location: `SKILL.md (Render and record); scripts/render-estimate.py`
- Evidence: render-estimate.py took --stack, --qa-platform and --engagement and embedded them for the report's client-side recompute, but SKILL.md's render command passed none, so they fell back to standard_saas/web/standard. A run that settled mobile_mcp_automated — the case SKILL.md explicitly calls out — would print a headline from the real profile above a live recompute using the industry default. Unticking one feature in front of a client would have exposed the contradiction.
- Recommendation: APPLIED, by removing the need to pass them twice. estimate.json now records the inputs that produced it and render-estimate.py reads them back, with the flags demoted to an override. Verified end to end with a mobile profile.

#### enhancement-2 — The estimate discarded every tag's reasoning and the verbatim quotes

- Lens: enhancement
- Location: `scripts/estimate.py (price_feature)`
- Evidence: price_feature kept each tag's value and status but dropped its `why`, and reduced citations to source id and location — losing the quote. The module requires a `why` on every judgement input everywhere else, and skill #3 exists to explain and defend these numbers; it would have had to reopen feature-inventory.json and re-join by id to say why a feature costs what it does. estimate.json is also the fattest artifact, carrying the whole cost-model snapshot, so it is the ledger payload rather than a distillate.
- Recommendation: APPLIED. Tag reasoning and quotes now survive into the priced record, and estimate-brief.json is a fourth projection carrying exactly the defence chain — hours, the dominant cost driver, each tag with its reason, and the client's own sentence — at 6.7KB against the ledger payload's 24KB.

#### architecture-2 — {workspace} was used six times and never defined; {output_folder} was declared and never used

- Lens: architecture
- Location: `SKILL.md (Resolution rules, Estimating)`
- Evidence: Resolution rules declared {output_folder} but the body never used it, while an undeclared <workspace> appeared in every command and again in headless.md. Under a declined-customization build the output destination must be genuinely hardcoded; it was neither hardcoded nor derivable, so check.json, estimate.json and the renders would land wherever each run invented.
- Recommendation: APPLIED. {workspace} is defined as {output_folder}/estimates/{project-slug}/ — the folder est-scope-extract already created — so the estimate lands beside the inventory it prices and the scope, its sources and the number stay together.

#### architecture-3 — references/cost-model-guide.md was orphaned — nothing ever loaded it

- Lens: architecture
- Location: `SKILL.md`
- Evidence: The guide's only appearance in SKILL.md was as the illustrative example inside the Resolution rules boilerplate. No section routed to it, so 1,200 tokens carrying the module's core judgement — why review_rate divides manual_baseline, the three questions before editing a coefficient, why the seed is uncalibrated — were never read. The gotcha instructing the reader to edit cost-model.json pointed at nothing.
- Recommendation: APPLIED. Routed from three points of use: the first-run seed step, the bar, and the coefficient-editing gotcha.

#### enhancement-1 — headless.md appended assumptions to a memlog nothing ever created

- Lens: enhancement
- Location: `SKILL.md; references/headless.md`
- Evidence: headless.md told the run to append typed assumptions to {workspace}/.memlog.md and returned its path, but nothing anywhere inited it. Interactively it was worse: the four profile inputs each move the number, each may be defaulted, and none was recorded — so skill #4 reconciling actuals could not tell whether a figure assumed a senior team or a junior one.
- Recommendation: APPLIED. The memlog is inited where the profile inputs are settled, with one assumption entry per input taken by default, threaded into the flow rather than added as a section.

#### enhancement-3 — The one blocking dependency was hard-pathed with no fallback

- Lens: enhancement
- Location: `SKILL.md (Validate before pricing)`
- Evidence: The sibling's inventory-check.py was referenced by a literal path that does not survive every installation layout. If absent, the command fails and the run dead-ends — even though estimate.py exposes --completeness and the extraction report carries the score.
- Recommendation: APPLIED. The step now says to find the checker under the project's skills directory if it is not at that path, and if it genuinely is not installed, to pass --completeness from the extraction report and record that the inventory went unvalidated — because the traceability guarantee is then unverified rather than merely unchecked. Tightened further on the lens's follow-up: --completeness must never be supplied from judgement, since the score is computed under fixed weights precisely so a thin input cannot be made to look certain. The fallback now reuses an existing check.json, then globs for the checker, then stops.

#### enhancement-4 — The ledger write was unconfirmed, and a same-day re-estimate destroyed the earlier entry

- Lens: enhancement
- Location: `SKILL.md (Render and record); scripts/ledger.py`
- Evidence: The write ran unconditionally in the same breath as rendering, with no confirmation, on the module's one irreversible record. The entry id is EST-<date>-<project-slug>, so a second estimate of the same project on the same day — the normal presale case after a client pushes back — collided, and the only offered recovery was --replace, which destroyed the first entry and the coefficient snapshot skill #4 needs to reconcile against.
- Recommendation: APPLIED. A --revision flag records alongside the original as -r2, -r3 and so on, keeping the history of how a number moved. A draft may still be replaced deliberately; an entry already sent, won, lost or delivered is a commercial fact and is now refused outright. The collision message names the recovery. quick mode records nothing at all, and the step now shows what will be written and asks first.

### Medium (9)

#### customization-1 — {output_folder} declared but unwired under a declined-customization build

- Lens: customization
- Location: `SKILL.md (Resolution rules)`
- Evidence: The one declared path placeholder was orphaned and the real destination was left for each run to invent. Under a declined-customization build the destination must be genuinely hardcoded.
- Recommendation: APPLIED, together with architecture-2: {workspace} binds {output_folder} to the sibling's project folder and every command uses the token.

#### leanness-1 — The bar re-taught arithmetic the script owns, in the most expensive file

- Lens: leanness
- Location: `SKILL.md (The bar)`
- Evidence: A 90-token paragraph explained that band width derives from completeness and that review_h shares manual_baseline. Neither is a move the model makes — estimate.py computes both — and the same argument was made at length in the cost-model guide and in the seed's own `why` fields, which is where it becomes actionable. The entry carried the guide's content precisely because nothing loaded the guide.
- Recommendation: APPLIED. Cut to the one clause that changes how the model reads its own output — that high review hours on a sensitive feature are the model working, not a fault — with the argument left to the guide, which is now routed to.

#### leanness-2 — The ledger-snapshot gotcha changed no move the model makes

- Lens: leanness
- Location: `SKILL.md (Gotchas)`
- Evidence: It described a property estimate.json already had and ledger.py already recorded, giving the reader no action. The one real behaviour it could have guarded — hand-writing a ledger entry instead of running the script — was not stated.
- Recommendation: APPLIED. Cut, with the operative half folded into the record step where the action is.

#### leanness-3 — The guide's profiles section restated the seed's own why fields

- Lens: leanness
- Location: `references/cost-model-guide.md`
- Evidence: Three of four bullets paraphrased `why` strings already in cost-model.seed.json, which is open in front of anyone reading that section. Only the overhead_rate bullet added a thought the data does not carry.
- Recommendation: APPLIED. Cut to the one thought the data cannot express — that overhead_rate is a commercial choice as much as a delivery one — with a pointer to the `why` fields for the rest.

#### architecture-4 — The mode table promised per-mode behaviour the instructions and scripts do not implement

- Lens: architecture
- Location: `SKILL.md (Modes)`
- Evidence: Only quick/not-quick is real: estimate.py treats delivery exactly as presale, --team-size is accepted in any mode, and the render and ledger steps are unconditional despite the table implying they are presale-only. Nothing instructs the agent to choose a mode at all.
- Recommendation: APPLIED (see enhancement-5, the same finding from a second lens): quick renders markdown only and records nothing; delivery requires the team size it claimed to fit against.

#### architecture-5 — The memlog was referenced by the headless path but owned by no one

- Lens: architecture
- Location: `SKILL.md; references/headless.md`
- Evidence: Same defect as enhancement-1, found independently by a second lens: the working-state choice was otherwise right — estimate.json is the structured artifact and the ledger is module memory, neither ceremonial — but the memlog appeared only in headless.md, which appended to it and returned its path without ever creating it.
- Recommendation: APPLIED with enhancement-1.

#### determinism-5 — Every range-narrowing question was priced on the favourable answer

- Lens: determinism
- Location: `scripts/estimate.py (narrowing_questions)`
- Evidence: Each counterfactual assumed the answer that helps: clarity becomes high, an XL splits into Ls, an inferred sensitive tier comes back routine. Confirming a tier as genuinely sensitive removes no band and may widen it, yet the question was priced as though the answer would be routine — a mild intelligence leak, since the script was deciding what the answer would be.
- Recommendation: APPLIED. Each question now carries an `assumes` field naming the answer its figure is priced on, rendered beside the hours in the markdown and the HTML. The tier question says outright that a confirmed tier narrows nothing.

#### determinism-6 — The prompt was asked to filter the risk quadrant and judge the outside-scope share

- Lens: determinism
- Location: `SKILL.md (Read the output before rendering it)`
- Evidence: The model was told to identify features that are both low-compressibility and sensitive or critical, and to judge whether the outside-scope share was large — a filter and a percentage, both of which the script already had the data for.
- Recommendation: APPLIED. estimate.py now emits `risk_quadrant` and a `share_of_total_pct` per scope group; SKILL.md points at both, so the model interprets rather than filters.

#### enhancement-5 — The mode table promised behaviour the flow never honoured

- Lens: enhancement
- Location: `SKILL.md (Modes, Estimating)`
- Evidence: Found independently by two lenses. quick was not quick — it rendered every format and wrote a ledger entry a go/no-go should never create — and delivery was presale with an optional flag, since nothing asked for the team it claimed to fit against.
- Recommendation: APPLIED, by wiring rather than cutting. quick renders markdown only and records no ledger entry; delivery makes team size a required input. The table now describes what the skill does.

### Low (3)

#### leanness-4 — 'Uncalibrated' was stated three times across two files

- Lens: leanness
- Location: `SKILL.md; references/cost-model-guide.md`
- Evidence: The presentation step, a gotcha and the guide each said it. Restated fact across sections.
- Recommendation: APPLIED. The gotcha keeps it, since it carries the shape-versus-absolute-figures distinction that is the actual content; the trailing clause of the presentation step is cut. The guide's version stays — different branch.

#### leanness-5 — The estimate.py capability enumeration was meta-explanation

- Lens: leanness
- Location: `SKILL.md (Compute)`
- Evidence: A seven-item list of what the script does changed no move — the script runs the same either way — and the one nudge inside it, not to recompute anything by hand, was never actually stated.
- Recommendation: APPLIED. Truncated to the nudge; the flag list and --help pointer stay, since a precise script invocation is the kind of exact procedure the canon reserves procedure for.

#### leanness-6 — headless.md restated its own trigger and re-argued its why three times

- Lens: leanness
- Location: `references/headless.md`
- Evidence: 'Recognising it' repeated SKILL.md's trigger condition almost verbatim, though the model has already recognised headless mode or it would not be reading the file. Two further passages re-argued the same point about logging assumptions.
- Recommendation: APPLIED. Reduced to the one line with new content — that headless holds for the whole run — and the duplicated arguments cut.
