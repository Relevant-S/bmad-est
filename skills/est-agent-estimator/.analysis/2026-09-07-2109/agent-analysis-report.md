# Analysis Report: skills/est-agent-estimator

Generated: 2026-09-07 · Schema: 2

**Grade: Good**

> Nadia is a coherent, well-voiced agent whose scripts hold the module's hardest line — every hour comes from est-estimate's engine behind a parity gate — but the pass found nine high-severity defects, and the three worst were places where the agent contradicted a rule it states about itself. All 38 findings are addressed.

The pricing boundary and the persona are the strengths: no formula is reimplemented, every what-if is a real re-price, and the voice survives into all four references. The weakness was self-contradiction — scope extracted inline one row below a rule forbidding it, a number asserted that could not be decomposed, and a distillate read from a path where it is never written. Six lenses, 38 findings, 9 high; the fixes are in and every claim the references make about a script is now verified by executing it.

| Severity | Count |
| --- | --- |
| Critical | 0 |
| High | 9 |
| Medium | 18 |
| Low | 11 |

## Themes

### 1. The agent contradicted rules it states about itself

- Root cause: Three of the nine highs were self-contradiction rather than omission: SKILL.md forbade inline scope extraction one row above a reference that extracted scope inline; the non-negotiable promised decomposition on demand while scenario.py returned a headline that stopped at the phase split; triage.md claimed 'no separate calculation, only a read' and then named three ratios nothing exposes. A stated rule is not a guarantee until something enforces it.
- Fix: Every rule the agent states about itself was traced to the thing that would break it, and either the wiring or the rule was changed — intake now hands off to est-scope-extract, scenario.py returns per-feature hours, and bid/no-bid reads portfolio.py's computed shares.
- Findings:
  - `agent-cohesion-1` intake.md does inline scope extraction that SKILL.md forbids one row earlier, and does it to a lower bar than est-scope-extract — `skills/est-agent-estimator/references/intake.md; SKILL.md "What to load, and when" table`
  - `agent-cohesion-4` The non-negotiable holds for the priced estimate but not for scenario numbers — the numbers actually said out loud in a client call — `skills/est-agent-estimator/SKILL.md "The non-negotiable"; references/defend.md "What-if"; scripts/scenario.py `run()``
  - `determinism-1` Bid/no-bid asks the model to compute three shares that portfolio.py already computes — `references/triage.md:16-24 (against scripts/portfolio.py:118-134, 203-227)`

### 2. Cross-skill paths asserted rather than executed

- Root cause: The agent names files and commands in three sibling skills. Several were wrong in ways no reading catches: accuracy-brief.json was read from a path where est-calibrate never writes it, calibration runs sat inside the estimates folder and became a phantom project on every activation, inventory-check.py was named bare and without the two flags that make it verify anything, and doc_type was written to a file that has no such field.
- Fix: Calibration runs moved out of estimates/, portfolio.py requires a workspace marker and reports what it skipped, and every command and field name the references quote is now verified by executing it against a real workspace.
- Findings:
  - `architecture-1` accuracy-brief.json is routed to a path where it is never written — `SKILL.md:70 (routing table, "How accurate are we?")`
  - `architecture-2` The calibration folder is scanned as a project by the activation script — `SKILL.md:55 (On activation) with scripts/portfolio.py:252`
  - `architecture-3` intake.md's inventory-check.py invocation is unresolvable and drops the flags that make it do the promised work — `references/intake.md:3, :13, :45`
  - `architecture-4` Contract drift: doc_type is written to the wrong file — `references/intake.md:13`
  - `agent-cohesion-7` intake.md's `inventory-check.py` resolves to a path that does not exist — `skills/est-agent-estimator/references/intake.md (opening paragraph and "Then hand off")`
  - `determinism-6` Intake hand-authors normalized/manifest.json instead of running the script that produces it — `references/intake.md:13`

### 3. The deal lifecycle had no ends

- Root cause: The agent read out 'capture actuals' and 'which deal to work first' every session while holding no way to record an outcome, attach hours, quote a single figure for a proposal, hand over the rendered report, or land an observation a veteran made. The middle of the lifecycle was well covered and both ends dead-ended.
- Fix: ledger.py --set-status and ingest-actuals.py are wired in with the three fields that decide comparability; ledger status now gates re-pricing; comparables.md is read where a veteran would reach for it; the single-number answer and the artefact handoff are covered.
- Findings:
  - `agent-cohesion-2` The deal lifecycle dead-ends: Nadia chases outcomes and actuals every session but has no capability to record either — `skills/est-agent-estimator/SKILL.md "On activation" and routing table; references/triage.md "Reading the portfolio"`
  - `agent-cohesion-3` comparables.md is named as the anchoring corpus but no capability ever reads it — `skills/est-agent-estimator/SKILL.md:47 (conventions); references/curate.md:41`
  - `agent-cohesion-5` The change-request journey has an undocumented input and no durable output — `skills/est-agent-estimator/references/defend.md "What-if" (`--add-file change-request.json`)`
  - `agent-cohesion-6` Nothing Nadia produces in a defend session leaves the terminal, including the artefact she is told to send — `skills/est-agent-estimator/references/defend.md ("Cut lines", "Range-narrowing questions")`
  - `enhancement-1` Add: ledger status must gate the re-cut path — a `won` estimate is not re-priceable — `references/defend.md (What-if, Cut lines); SKILL.md (What to load, and when)`
  - `enhancement-3` Add: no answer to "the proposal needs one number" — the pressure that sends the user back to the spreadsheet — `SKILL.md (Communication style, Gotchas); references/defend.md`
  - `enhancement-4` Add: the rendered client-facing artefacts are invisible to the agent that should be handing them over — `SKILL.md (What to load, and when); references/defend.md (What-if)`
  - `enhancement-5` Add: capture-don't-interrupt has no destination — "capture it" dead-ends — `references/defend.md (Sanity-check a human's number); references/triage.md`

### 4. Definitions with more than one owner

- Root cause: Three quantities were computed independently in more than one place: the pricing options dict in three skills with divergent fallbacks, `calibrated` by prose-prefix match in three files while gating a client-facing claim, and band width three ways. Each worked; each was one edit from silently disagreeing.
- Fix: is_calibrated(), options_from() and confidence.band_width now live in estimate.py beside the pricing, and every consumer reads them. Mutation-tested: reintroducing the prose match or a silent balanced fallback fails the suites.
- Findings:
  - `determinism-2` The pricing options dict is rebuilt independently in three skills — `scripts/scenario.py:58-95 (`options_from`), vs est-estimate/scripts/estimate.py:630-641 and est-calibrate/scripts/backtest.py:51-63`
  - `determinism-3` `calibrated` is inferred by prose-prefix match, in three places, and gates a client-facing claim — `scripts/portfolio.py:131-132 (with est-estimate/scripts/render-estimate.py:35 and :138-139)`
  - `determinism-7` Definitions the engine owns are re-declared in the agent's scripts — `scripts/scenario.py:29, :169-172; scripts/portfolio.py:125`

### 5. References that could not stand alone

- Root cause: All four references used path tokens bound only in SKILL.md, and two routed to a third reference — so a reference loaded after the entry file dropped from context would resolve neither its paths nor its onward pointers.
- Fix: Each reference binds the tokens it uses in one line; cross-reference routing was replaced by inline commands or a hand-back to the routing table; the profile interview moved to the file that owns writes to memory.
- Findings:
  - `architecture-5` No reference binds the path tokens it uses; all four depend on SKILL.md surviving compaction — `references/defend.md, references/intake.md, references/triage.md, references/curate.md`
  - `architecture-6` Reference routes to another reference — `references/defend.md:33`
  - `agent-cohesion-8` The company profile is split across two references — created in triage.md, edited in curate.md — `skills/est-agent-estimator/references/triage.md "The company profile interview"; references/curate.md "What you can change freely"`
  - `leanness-4` Entry-file prose restated operationally by the reference that owns it — `skills/est-agent-estimator/SKILL.md — 'What to load, and when' lead paragraph; 'Gotchas' final bullet`

## Strengths

- The pricing boundary holds absolutely: scenario.py computes no pricing formula of its own, loads est-estimate's engine, and refuses outright unless it can first reproduce the estimate's recorded headline from its own snapshot — the defect that shipped twice in this module cannot recur here.
- The persona is a specific person rather than a house voice, and it survives into all four references. It was treated as investment throughout; the leanness lens returned four low findings and none touched the voice.
- The cut-line search reports only real re-prices, prunes cuts the budget did not need, and is guarded by an invariant test — putting any proposed cut back must break the budget — rather than by asserting a particular answer.
- Every claim a reference makes about a script's flags or output fields was verified by executing it against a real end-to-end workspace, not by reading the source.

## Recommendations

1. Enforce, in wiring, every rule the agent states about itself — the three worst defects were rules with nothing behind them. (resolves: agent-cohesion-1, agent-cohesion-4, determinism-1)
2. Execute every cross-skill path and field name a reference quotes; four were wrong in ways no amount of re-reading would have caught. (resolves: architecture-1, architecture-2, architecture-3, architecture-4, agent-cohesion-7, determinism-6)
3. Give the lifecycle its two ends: recording an outcome, and producing something that leaves the terminal. (resolves: agent-cohesion-2, agent-cohesion-5, enhancement-1, enhancement-3, enhancement-4)
4. Move every multi-owner definition into est-estimate beside the pricing, and mutation-test that the consumers really read it. (resolves: determinism-2, determinism-3, determinism-7)
5. Make each reference resolvable standing alone: bind its tokens, and never route to another reference. (resolves: architecture-5, architecture-6, leanness-4)

## Agent Profile

- Name: Nadia
- Title: Delivery Estimator
- Type: stateless
- Mission: The human leaves with a number they understand well enough to defend to someone who does not want to hear it.

## Capabilities

- **Explain, defend, re-price, cut to a budget** (prompt + script) — references/defend.md over scripts/scenario.py, which re-prices through est-estimate's engine.
- **Conversational intake** (prompt + handoff) — references/intake.md runs the elicitation and captures a citable transcript, then hands to est-scope-extract.
- **Portfolio triage, bid/no-bid, closing the loop** (prompt + script) — references/triage.md over scripts/portfolio.py, plus ledger.py --set-status and ingest-actuals.py.
- **Cost-model and profile curation** (prompt + external script) — references/curate.md routes to est-calibrate's apply.py (evidence) and curate.py (judgement).
- **Pipeline orchestration** (external skills) — Invokes est-scope-extract, est-estimate and est-calibrate; never reimplements them.

## Per-Lens Verdicts

- **leanness**: Passes the leanness bar: all four references survive the five-line-baseline test on real institutional content (script invocations, JSON field semantics, coefficients nobody volunteers), and no capability prompt is ceremony; four low-severity trims only.
- **architecture**: Topology, disclosure and routing are sound for a stateless agent and the script contracts largely hold — but three cross-skill paths are wrong or unresolvable, and the calibration folder collides with the activation script's project scan.
- **determinism**: The pricing boundary holds — scenario.py delegates every hour it reports to est-estimate's engine and adds a parity gate on top, so the module's two shipped defects are genuinely closed here; the leaks that remain are around the engine, not inside it: an options dict rebuilt in three skills, a `calibrated` flag inferred from prose in three files, and triage prose that asks the model to hand-compute shares portfolio.py already returns.
- **customization**: Stateless agent, metadata-only customize.toml, and it is the sole config mechanism present — about right in size, with no forbidden mechanism, no toggle, and no scalar/hardcode no-op possible; the decline is legitimate, but two of the three surfaces its stated reasoning leans on do not hold up as written.
- **enhancement**: The promised capability set is nearly all present and the persona is genuinely differentiated, but four real user paths dead-end — a `won` or `sent` estimate re-cut as if it were a draft, a `quick`-mode or estimate-less workspace whose brief does not exist, the presale lead who must put one number in a proposal, and a domain fact captured with nowhere to land — and the module's best client-facing artefact is invisible to the agent that should be handing it over.
- **agent-cohesion**: Nadia is an authentic, coherent character whose voice survives intact into all four references, but her capability set covers the middle of the estimating lifecycle and not its ends: she cannot record a deal outcome or actuals, cannot anchor a number against the comparables corpus she is told exists, and her conversational intake route contradicts the anti-inline-extraction rule stated two rows above it in her own routing table.

## Experience

- **Before a client call** — Activation reads the company profile → load estimate-brief.json → explain the chain → rehearse the challenges from risk_quadrant, outside-scope share, inferred tiers and calibrated:false → hand over estimate.html.
- **After a bad client call** — Check ledger status → find where the give is → price every proposed cut through scenario.py → --to-budget for a cut line → quote comparison.saving, never the feature's own hours.
- **Change request on a sold project** — Author the added feature with its citation → scenario.py against the ledger entry → quote the addition alone → record a --revision so the portfolio sees the divergence.
- **Scope that exists only in a conversation** — Elicit against the five axes → append verbatim blocks to conversation.md → run convert-input.py → hand to est-scope-extract → est-estimate.
- **First ever run** — No company profile → the interview in curate.md → written to {memory}/company-profile.md, which est-estimate then reads for its defaults.
- Headless: None, deliberately. Unattended batches belong to the three workflows, which carry -H contracts built for it; the agent's value is judgement, which an unattended run cannot use. triage.md carries the batch recipe and SKILL.md says so, so nobody wires the agent into a cron.

## Findings

### High (9)

#### architecture-1 — accuracy-brief.json is routed to a path where it is never written

- Lens: architecture
- Location: `SKILL.md:70 (routing table, "How accurate are we?")`
- Evidence: SKILL.md routes to `{workspace}/accuracy-brief.json`, and SKILL.md:49 binds `{workspace}` → `{output_folder}/estimates/{project-slug}/`. est-calibrate writes the brief into its own workspace: est-calibrate/SKILL.md:20 binds its `{workspace}` → `{output_folder}/estimates/calibration/{date}/`, and est-calibrate/scripts/render-report.py:278 writes `out_dir / "accuracy-brief.json"` with `--out-dir {workspace}` (est-calibrate/SKILL.md:60). The file therefore never exists at the path Nadia checks, so the routing row's own fallback fires and Nadia says the model is uncalibrated after every successful calibration — the exact overclaim-in-reverse the Gotchas section is built to prevent.
- Recommendation: Route to `{output_folder}/estimates/calibration/` and say to read the most recent dated run's `accuracy-brief.json` (the folder is one-per-run by design, so the row must name the latest-wins rule, not a fixed path). Bind a `{calibration_workspace}` token in Conventions if the path is used more than once.

#### architecture-2 — The calibration folder is scanned as a project by the activation script

- Lens: architecture
- Location: `SKILL.md:55 (On activation) with scripts/portfolio.py:252`
- Evidence: Activation runs `portfolio.py --estimates {output_folder}/estimates`. portfolio.py:252 iterates `sorted(p for p in root.iterdir() if p.is_dir())` and treats every subdirectory as a project workspace. est-calibrate writes its runs to `{output_folder}/estimates/calibration/{date}/` (est-calibrate/SKILL.md:20), so `calibration` sits as a sibling of the real project folders. It has no feature-inventory.json, so next_action(row) falls to `"extract"` (portfolio.py:191-192), it is counted in `summary.needing_action`, and it appears as a project named `calibration`. Nadia is told to "greet with what actually needs attention" — after the first calibration run, that greeting contains a phantom project needing scope extraction, on every activation, forever.
- Recommendation: Skip reserved names in portfolio.py's scan (a `RESERVED = {"calibration"}` filter at the iterdir, or require a `feature-inventory.json`/`normalized/` marker before treating a folder as a workspace) and state the exclusion in triage.md so the omission is not mistaken for a missing project.

#### architecture-3 — intake.md's inventory-check.py invocation is unresolvable and drops the flags that make it do the promised work

- Lens: architecture
- Location: `references/intake.md:3, :13, :45`
- Evidence: intake.md names `inventory-check.py` bare three times. SKILL.md:45 binds bare paths to this skill's directory, and est-agent-estimator ships no such script — the real one is `{project-root}/skills/est-scope-extract/scripts/inventory-check.py` (spelled in full by est-estimate/SKILL.md:49). Worse, intake.md promises the checker "re-opens it and verifies every quote exactly as it does for a client PDF", but that manifest reconciliation only runs when `--normalized <workspace>/normalized --manifest <workspace>/normalized/manifest.json` are passed (inventory-check.py:544, 585-586; est-scope-extract/SKILL.md:56). Bare `inventory-check.py <file>` skips it entirely, so the traceability guarantee intake.md's whole design rests on silently does not happen. The hand-off also never names where the inventory is written, while est-estimate requires `{workspace}/feature-inventory.json` (est-estimate/SKILL.md:49).
- Recommendation: Replace the bare mentions with the full command line, as est-estimate does: `uv run {project-root}/skills/est-scope-extract/scripts/inventory-check.py {workspace}/feature-inventory.json --normalized {workspace}/normalized --manifest {workspace}/normalized/manifest.json`, and state the output path `{workspace}/feature-inventory.json` in the hand-off section.

#### determinism-1 — Bid/no-bid asks the model to compute three shares that portfolio.py already computes

- Lens: determinism
- Location: `references/triage.md:16-24 (against scripts/portfolio.py:118-134, 203-227)`
- Evidence: triage.md says "Everything this needs is already in `estimate-brief.json` and `estimate.json`; there is no separate calculation, only a read" and then names four factors, three of which are ratios: risk-quadrant share, "band width relative to the number", and outside-agreed-scope share. None of those are readable. `brief()` (est-estimate/scripts/render-estimate.py:119-157) drops `risk_quadrant` entirely, and estimate.json publishes `risk_quadrant` as a list of features with no total — so the model must sum `risk_quadrant[].hours`, divide by `total_hours.likely`, and compute `(high - low) / likely` by hand. Meanwhile portfolio.py:125-130 already returns `band_width_pct`, `risk_quadrant_hours`, `risk_quadrant_pct` and `outside_agreed_scope_pct` per project, with thresholds attached in `attention` (lines 211-218). The instruction also sends the model into estimate.json for those figures, which SKILL.md:61 explicitly forbids: "`estimate.json` carries an entire cost-model snapshot … written for machines and neither belongs in a conversation."
- Recommendation: Determinism test: summing a list and dividing by a total yields the same answer every time and is unit-testable, so it is script work — and the script exists. Rewrite the bid/no-bid section to read the project's row from `portfolio.py` output (which already carries all three ratios and their thresholds) and spend the model's tokens on the recommendation sentence, which is the judgement. That also removes a large machine artefact from the conversation, restoring SKILL.md's own read-the-brief rule.

#### enhancement-1 — Add: ledger status must gate the re-cut path — a `won` estimate is not re-priceable

- Lens: enhancement
- Location: `references/defend.md (What-if, Cut lines); SKILL.md (What to load, and when)`
- Evidence: The expert-user journey: a delivery lead brings a change request against a sold project. `defend.md` says only that `scenario.py` "also runs against a ledger entry, which is how you price a change request against a project that is already sold" — one clause, with no consequence attached. Nothing tells the agent to read `ledger.status` first, and every downstream instruction (`comparison.saving`, `--to-budget` cut lines, "quote the saving out loud") is written for a draft. On a `won` or `delivered` entry those instructions produce a revised total for a number that is contractually fixed, and on `sent` they produce a second number the client has never seen. The same blind spot covers the two-estimates-for-one-project case: `est-estimate` keeps revisions with `--revision` and `defend.md` always loads `{workspace}/estimate-brief.json`, which is the latest local re-run and may not be the figure the client is holding. `portfolio.py` already returns per-entry `status` and `likely_hours`, so the data is present and unused.
- Recommendation: Add a short paragraph at the top of the What-if section of `defend.md`: read the ledger entry's `status` before pricing any change. On `draft`, proceed as written. On `sent`, a re-price is a re-quote — say what changed since the number went out and name both figures. On `won` or `delivered`, the total is fixed and a scenario is a change order: quote `standalone_hours` for the addition and never present a revised project total. When the workspace estimate's headline differs from the latest `sent`/`won` ledger entry, say which number the client actually holds before answering anything else.

#### enhancement-2 — Add: no branch for a project with no estimate, or one whose brief was never rendered

- Lens: enhancement
- Location: `references/defend.md (first line); SKILL.md routing table`
- Evidence: The accidental-intent user and the hostile-environment user both land here. `defend.md` opens 'Load `{workspace}/estimate-brief.json`' with no missing-file branch, and the routing table sends every explain/defend/challenge/what-if phrasing there — including the description's own trigger phrases ("explain this estimate", "the client says it's too expensive"), which a user will fire at a project that has an inventory but no estimate, or none of either. It is worse than a rare miss: `est-estimate`'s `quick` mode renders `--formats md` only and writes no `estimate-brief.json` and no ledger entry, so a completed go/no-go run is a workspace that looks finished and breaks `defend.md` on its first instruction. The user gets a missing-file error from a conversational agent whose whole promise is that the number is explainable.
- Recommendation: Give `defend.md` a two-line opening branch: if `estimate-brief.json` is absent, check what the workspace does have. No estimate at all — say so and route to the extract → estimate path rather than reading `estimate.json` for something to talk about. A `quick`-mode estimate — the markdown is the only artefact, there is no per-feature chain to walk and no ledger entry, so the honest answer is the go/no-go it was run for plus an offer to re-run in `presale` mode. Anything else in `estimate.json` but no brief — re-render with `render-estimate.py --formats brief` before answering.

#### enhancement-3 — Add: no answer to "the proposal needs one number" — the pressure that sends the user back to the spreadsheet

- Lens: enhancement
- Location: `SKILL.md (Communication style, Gotchas); references/defend.md`
- Evidence: Every path in the agent leads with a range, and the gotchas defend the band's width well. But the ordinary presale reality — a sales director or a proposal template that will carry exactly one figure, not '620 to 1,040' — has no covered response anywhere. The nearest thing is `triage.md`'s 'I would bid this, and I would not fix the price', which is a bid/no-bid read, not an answer to the person who has already decided to bid. Refusing the single number outright does not prevent it: someone picks one from the band on the way to the document, unrecorded, and that is precisely the spreadsheet behaviour this agent exists to replace. The material to answer well already exists — PERT mean and sd per component, the narrower-band `planning_review_h` anchor, and `uncertainty.z`.
- Recommendation: Add a short section to `defend.md`: a commit figure is a stated position on the band, not a replacement for it. Name the point being quoted and what it buys (the likely figure carries roughly even odds; a figure above it is buying cover, and the model can say how much), state the assumptions it rests on in the same breath, and record which figure went out so the ledger entry matches the proposal. Keep the existing refusal for the thing that is actually unsafe — a fixed price against a band this wide — rather than for the single number itself.

#### agent-cohesion-1 — intake.md does inline scope extraction that SKILL.md forbids one row earlier, and does it to a lower bar than est-scope-extract

- Lens: agent-cohesion
- Location: `skills/est-agent-estimator/references/intake.md; SKILL.md "What to load, and when" table`
- Evidence: The routing table's document row says: "Never extract scope inline — an unreviewed inventory produces a confident wrong number, and the extraction review is what catches invented scope." The row immediately above routes conversational scope to `references/intake.md`, which then builds `feature-inventory.json` inline. est-scope-extract already handles this input class explicitly — its overview names "call transcript" first, `references/source-type-playbook.md` covers transcripts specifically, and `evals/fixtures/discovery-call.md` is a conversation fixture. intake.md reproduces the pipeline but drops most of what makes it trustworthy: no `convert-input.py` / manifest generation (it tells Nadia to hand-register the source in `manifest.json`), no `not_scope` accounting, no `unreferenced_regions` coverage judgement, no per-source subagent invented/omitted review — the exact "extraction review" the table cites as the reason for the ban — no `render-inventory.py`, and no `extraction-report.md`. So intake.md's opening claim, "Nothing downstream gets a weaker artefact because the input was a conversation," is not true of what it actually instructs. The genuinely novel, persona-coupled half is the elicitation itself: drawing out the five axes, refusing to flatter clarity, pushing on the thin description. That half belongs to Nadia; the inventory construction does not.
- Recommendation: Split the capability at the artefact boundary. Keep intake.md as the conversational elicitation and the transcript-capture discipline: run the conversation, append verbatim blocks to `{workspace}/normalized/conversation.md`, probe the five axes, observe clarity honestly, capture dependencies as they surface. Then end it with a handoff — invoke `est-scope-extract` with `conversation.md` as the source, which already knows how to read a transcript, run the checker, run the review pass and write the report — instead of hand-building the inventory. That removes the contradiction with the routing table, restores the review pass, and leaves Nadia owning the part only she can do.

#### agent-cohesion-2 — The deal lifecycle dead-ends: Nadia chases outcomes and actuals every session but has no capability to record either

- Lens: agent-cohesion
- Location: `skills/est-agent-estimator/SKILL.md "On activation" and routing table; references/triage.md "Reading the portfolio"`
- Evidence: Every activation runs `portfolio.py`, whose `next_action` and `attention` fields are largely driven by ledger status: `next_action` surfaces `capture actuals` for entries where `status in ("won", "delivered")` and `has_actuals` is false, and the summary buckets `by_status`. triage.md instructs her to read that out and "Chase the oldest first." But status only ever becomes sent/won/lost/delivered through `est-estimate/scripts/ledger.py --set-status ID STATUS`, and actuals only land through `est-calibrate/scripts/ingest-actuals.py`. Neither appears anywhere in SKILL.md or any reference — grep for `set-status` and `ingest-actuals` across the agent returns nothing. est-estimate records `draft` and stops. The result: every entry stays `draft` forever, the `capture actuals` branch can never fire, and the chase list triage.md builds its urgency around is unreachable state. curate.md meanwhile says the evidence door "is the door that should be used most" — but nothing in the agent can supply the evidence it needs. The evals confirm the omission: none of the ten cases touches recording an outcome or actuals. The user hits this the moment they answer Nadia's own prompt with "we won it, here are the hours."
- Recommendation: Close the loop with a fifth capability, `references/close-the-loop.md`, routed from a new table row ("A deal moved — sent, won, lost, delivered — or actuals came back"). It owns two commands with their judgement: `ledger.py --set-status` for the deal transitions, and est-calibrate's `ingest-actuals.py` for the hours, carrying the three fields that decide comparability (`--scope`, `--exclude-hours` with its reason, `--confidence`) since Nadia is the one talking to the person who knows them. This is the natural place for a lost deal's price-versus-scope post-mortem too. Alternatively fold it into triage.md, which already owns the portfolio read — but a separate reference is the better grain, because recording an outcome is a different unit of work from deciding what to work on next.

### Medium (18)

#### architecture-4 — Contract drift: doc_type is written to the wrong file

- Lens: architecture
- Location: `references/intake.md:13`
- Evidence: intake.md says to register `conversation.md` "in `{workspace}/normalized/manifest.json` as a source of `doc_type: transcript`". The manifest is convert-input.py's own artefact, and its `sources[]` entries carry `id`, `path`, `converted_path`, `state` and `coverage_note` (convert-input.py:283, 319, 351-359; consumed at inventory-check.py:293-331) — there is no `doc_type` field there. `doc_type` with the `transcript` enum value belongs to the *inventory's* `sources[]` (est-scope-extract/assets/feature-inventory.schema.json:26) and is read as such at inventory-check.py:416. Followed literally, the tag lands where nothing reads it and the inventory's own source entry goes untyped.
- Recommendation: Split the instruction: add the conversation to the inventory's `sources[]` with `doc_type: transcript`, and add a matching manifest entry with `id`/`path`/`converted_path` pointing at `normalized/conversation.md` so reconcile_manifest passes.

#### architecture-5 — No reference binds the path tokens it uses; all four depend on SKILL.md surviving compaction

- Lens: architecture
- Location: `references/defend.md, references/intake.md, references/triage.md, references/curate.md`
- Evidence: defend.md uses `{workspace}` seven times, including the file it opens first at line 3; triage.md uses `{output_folder}` and `{memory}`; curate.md uses `{memory}` and `{project-root}`; intake.md uses `{workspace}` and `{project-root}`. Every binding lives only in SKILL.md:45-49. A carved capability prompt must stand alone because the entry context can drop mid-flow, and here the very first instruction of the most-used reference is an unresolvable path once it does. (`{project-slug}` at SKILL.md:49 is likewise bound nowhere, but it is self-evident from the surrounding clause and does not need a fix.)
- Recommendation: Put a one-line binding at the top of each reference for only the tokens that file uses — e.g. defend.md: "`{workspace}` = `{output_folder}/estimates/{project-slug}/`" — rather than repeating the whole Conventions block.

#### determinism-2 — The pricing options dict is rebuilt independently in three skills

- Lens: determinism
- Location: `scripts/scenario.py:58-95 (`options_from`), vs est-estimate/scripts/estimate.py:630-641 and est-calibrate/scripts/backtest.py:51-63`
- Evidence: estimate.py's `main()` assembles the options dict the engine prices on — `mode`, `team`, `team_name`, `stack`, `qa_platform`, `engagement`, `team_size`, `granularity`, `input_completeness`, `inventory_path`, `generated` — with its defaults ('balanced', 'standard_saas', 'web', 'standard'). scenario.py:83-95 re-declares that dict and those literals, and backtest.py:52-63 declares a third copy with *different* fallbacks: an unknown team profile silently falls back to `balanced` (scenario.py raises `Refused`), and a missing `input_completeness` defaults to `0.6` (scenario.py refuses, correctly, because band width cannot then be reproduced). The engine already carries the counter-example of how this should be done: `inventory_from` lives beside the pricing it inverts precisely so "there is exactly one definition… Two would silently disagree about a field neither owner noticed" (estimate.py:408-416).
- Recommendation: This is the module's binding standard applied to the pricing *inputs* rather than the pricing itself: one quantity, three derivations. Lift scenario.py's version (the strictest — it refuses rather than inventing a completeness score) into estimate.py as `options_from(estimate, model, overrides=None)`, next to `inventory_from` and for the same stated reason, and have scenario.py and backtest.py both call it. Note the parity gate at scenario.py:410-427 currently converts a divergence here into a refusal rather than a wrong number, which is the right failure — but its message blames "something has edited the estimate by hand, or the engine has moved", so a drift caused by a new option key the copy does not carry would be diagnosed as tampering.

#### determinism-3 — `calibrated` is inferred by prose-prefix match, in three places, and gates a client-facing claim

- Lens: determinism
- Location: `scripts/portfolio.py:131-132 (with est-estimate/scripts/render-estimate.py:35 and :138-139)`
- Evidence: portfolio.py derives `"calibrated": not (estimate.get("cost_model_snapshot") or {}).get("calibration_status", "").startswith("UNCALIBRATED")`. The identical expression appears twice in render-estimate.py — once to print the markdown warning banner, once to set the brief's `calibrated` flag. The field it matches is free prose: cost-model.seed.json:4 is a full sentence beginning "UNCALIBRATED. Every value below is a reasoned starting point…", and apply.py:175 replaces it with a differently-worded sentence when calibration lands. A regex/prefix deciding what content *means* rather than where a delimiter sits is the classic intelligence leak, and this one is load-bearing: SKILL.md:74 tells the agent to trust the flag, and evals/cases.json's `uncalibrated-claim` case fails the agent for claiming historical grounding. Reword the seed sentence to "Not yet calibrated…" and all three sites silently report every estimate as calibrated — the exact overclaim the module exists to prevent, with the agent behaving correctly on a wrong flag.
- Recommendation: Make the state structured rather than inferred: carry `calibration: {calibrated: false, status: "<prose>"}` in the cost model and expose one `is_calibrated(model)` helper in estimate.py, called by render-estimate.py's banner, `brief()`, and portfolio.py. One definition of the quantity, and no script reading meaning out of a sentence a human is free to rewrite.

#### determinism-4 — Triage's dependency factor asks for a determination the named artefacts cannot supply

- Lens: determinism
- Location: `references/triage.md:24 (against est-estimate/scripts/estimate.py:130 and scripts/portfolio.py:85-155)`
- Evidence: "Unresolved dependencies. A long critical path with inferred rather than confirmed links means the sequencing is a guess." But `price_feature` flattens dependencies to bare ids — `"depends_on": [d.get("feature_id") for d in feature.get("depends_on", [])]` (estimate.py:130) — so the `inferred` flag survives only in feature-inventory.json, and `estimate["dependencies"]` is `{hours, chain}` with no link provenance at all. To answer this the model must open a third artefact and join chain ids against the inventory's `depends_on` entries by hand, or state the read without evidence. portfolio.py already loads both files per workspace (`inventory, estimate = load(inventory_path), load(estimate_path)`, line 89) and then discards them at the call site (`row, _, _ = read_workspace(folder)`, line 253).
- Recommendation: Deterministic join, done once: have `read_workspace` emit `critical_path: {hours, length, inferred_links, confirmed_links}` by matching `estimate["dependencies"]["chain"]` against the inventory's `depends_on[].inferred`, and point triage.md at that field. Alternatively preserve the flag through pricing. Either way the model reads a count and judges what it means, which is the split the lens asks for.

#### determinism-5 — Activation makes the model parse and merge two YAML files and stat a memory file by hand, every session

- Lens: determinism
- Location: `SKILL.md:53-57`
- Evidence: "Load config from `{project-root}/_bmad/config.yaml` and `config.user.yaml` (root level and the `est` section)… If neither file exists, carry on with defaults", then a separate existence check — "If `{memory}/company-profile.md` does not exist, say so before estimating anything" — then `uv run scripts/portfolio.py`. Reading two files, merging user over base, merging section over root, and applying the `{output_folder}` default is parsing plus precedence resolution: same input, same output, unit-testable. The file-existence check is the Structure-checks category verbatim. No script in the module reads config.yaml — all four SKILL.md files hand the job to the model — so this cost is paid on every activation of every skill.
- Recommendation: Pre-pass JSON pattern. Give portfolio.py `--config-dir {project-root}/_bmad`, let it resolve the config layering and the `{output_folder}`/`{memory}` paths itself, and add a `memory` block reporting the presence of company-profile.md, cost-model.json, comparables.md and calibration-log.md. Activation then becomes one command whose JSON already answers "is the profile missing" and "what needs attention", instead of four reads and a merge the model narrates each time.

#### determinism-6 — Intake hand-authors normalized/manifest.json instead of running the script that produces it

- Lens: determinism
- Location: `references/intake.md:13`
- Evidence: "Then register it in `{workspace}/normalized/manifest.json` as a source of `doc_type: transcript`, so `inventory-check.py` re-opens it and verifies every quote." Two problems. `doc_type` is not a manifest field — it is a required field of feature-inventory.json's `sources[]` (est-scope-extract/assets/feature-inventory.schema.json:22-26); the manifest's entries carry `id`, `path`, `converted_path`, `converter`, `needs_native_read`, `warning`. And the producer exists and handles this input: convert-input.py accepts `.md` (`TEXT_SUFFIXES`), emits the manifest with anchors, and est-scope-extract's own SKILL.md:48 always runs it. A hand-written entry that omits `converted_path` silently disables portfolio.py's `sources_changed` staleness signal (portfolio.py:139-140 reads exactly that key), and one whose `path` disagrees with the inventory trips `reconcile_manifest` (inventory-check.py:293-331).
- Recommendation: Signal-verb scan: "register", "as a source" is structured emission, not judgement. Replace the hand edit with `uv run {project-root}/skills/est-scope-extract/scripts/convert-input.py {workspace}/normalized/conversation.md --out-dir {workspace}/normalized -o {workspace}/normalized/manifest.json`, and move the `doc_type: transcript` instruction to where it belongs — the inventory's `sources[]` entry. The model keeps the part that is genuinely its own: writing the conversation down verbatim so the quotes verify.

#### customization-1 — The justification routes house rules to a file this agent never reads

- Lens: customization
- Location: `customize.toml:9 (header comment); SKILL.md:57; references/triage.md:41, references/curate.md:39`
- Evidence: The comment declining the override surface says "House rules belong in company-profile.md, where est-estimate reads them too." But this agent never loads company-profile.md — SKILL.md:57 only tests for its existence and warns if missing, and it is listed in the `{memory}` conventions without a load instruction. Its documented consumers are est-estimate ("default profile inputs") and est-calibrate (learning-curve decay), and triage.md's six-item interview defines its content as domain facts: team shape, stacks, BMad adoption depth, QA capability, engagement model, the Architect-absorbs-PM confirmation. A house rule about the agent's own conduct — a mandatory non-binding disclaimer on any figure that leaves the building, "never present a fixed-price read without legal sign-off", a required framing on client-facing text — is not a profile input, would be noise to est-estimate's profile parsing if written there, and would never reach Nadia's context at all. That is the one concrete thing declining costs a team, and it is squarely `activation_steps_append` territory in a domain (presale numbers going to clients) where compliance preloads are ordinary. The decline itself remains legitimate per the stateless default, so this is the reasoning, not the decision.
- Recommendation: Either opt in minimally — add `activation_steps_prepend = []` and `activation_steps_append = []` (leave `persistent_facts` out; shipped agents carry none) so an org has a home for a conduct or compliance step — or, if staying metadata-only, correct the comment: house rules that change what Nadia *says* have no home today, and the honest sentence is that estimating inputs belong in company-profile.md while conduct rules would need the override surface. Do not resolve this by telling the agent to load company-profile.md as behavior — that conflates a profile input file read by three siblings with an agent-conduct surface.

#### customization-2 — The `est` config.yaml surface cited as reason #1 is undefined anywhere in the repo

- Lens: customization
- Location: `customize.toml:5-6; SKILL.md:53`
- Evidence: The decline rests on "three configuration surfaces that reach it", the first being "the `est` section of _bmad/config.yaml (ten est_* variables)". Nothing in the repo defines them: no `_bmad/est/config.yaml` exists (installed modules are core, bmm, bmb), no `{est_*}` variable is referenced by any of the four est skills (grep for `\{est_[a-z_]+\}` across skills/ returns nothing), and the three sibling skills touch config.yaml only for `{output_folder}`. SKILL.md:53 names "the `est_*` settings" generically and points at `est-setup` to configure them, but no such skill exists under skills/ (est-agent-estimator, est-calibrate, est-estimate, est-scope-extract, reports). Two of the three cited surfaces are real and verifiable — cost-model.json with its two audited doors, and company-profile.md — so the argument is not empty, but as written it counts a surface that has no schema, no named variables, and no author.
- Recommendation: Either name the actual variables in the comment once the est module config is authored (that authoring belongs to the module builder, not here — do not add a config.yaml to this agent), or drop the parenthetical count and cite only what exists. The "a fourth surface is where the four begin to disagree" argument still carries on cost-model.json plus company-profile.md alone; overstating the inventory is what makes it look like the decline was rationalized rather than reasoned.

#### enhancement-4 — Add: the rendered client-facing artefacts are invisible to the agent that should be handing them over

- Lens: enhancement
- Location: `SKILL.md (What to load, and when); references/defend.md (What-if)`
- Evidence: `est-estimate` writes an interactive HTML report in which unticking a feature recomputes the whole estimate live, including the overheads that shrink with it, plus a CSV explicitly 'for sales'. That is the single most useful thing a presale lead could carry into a client call, and it is the closest thing the module has to a reason to reach for this agent rather than a spreadsheet. Nadia never mentions either artefact in any route: the whole what-if section is terminal `scenario.py` invocations whose results live and die in the scrollback. The user finishes a defend session holding chat history and has to rebuild the position by hand for the call — while a live-recompute version of the same model sits unmentioned in their workspace.
- Recommendation: In the What-if section of `defend.md`, name the rendered report as the handoff: the terminal scenarios are for working out the position, the HTML is what goes into the room, and when a scenario is agreed, re-run `render-estimate.py` so the artefact matches what was decided rather than the pre-conversation number. Point the `{document_output_language}` config the agent already loads at that render, since the report is the one thing a client reads.

#### enhancement-5 — Add: capture-don't-interrupt has no destination — "capture it" dead-ends

- Lens: enhancement
- Location: `references/defend.md (Sanity-check a human's number); references/triage.md`
- Evidence: `defend.md` correctly identifies the highest-value moment in the whole agent — the veteran who knows something the coefficients do not — and ends the paragraph with 'that is a calibration input, not an error — capture it.' Nowhere is captured to. The module plan assigned the agent a `daily/` session log; no such file exists anywhere in the module, and the SKILL.md conventions list does not mention one. The same gap hits `triage.md`, where a bid/no-bid conversation surfaces facts about a client's behaviour, and the profile interview, which lands in `company-profile.md` only when it is run as an interview rather than heard in passing. The result is that the observations most worth keeping survive exactly as long as the session does — and the model that was supposed to accumulate the company's knowledge learns nothing from the conversations it was built for.
- Recommendation: Name the landing places in one line where the capture instruction appears, using files that already exist: a fact about how the company works goes to `{memory}/company-profile.md` (which `curate.md` already says is freely editable and which `est-estimate` reads); a delivered-hours anchor a user quotes from memory goes to `{memory}/comparables.md` with its source; a disagreement about a coefficient with no evidence behind it yet goes to the calibration conversation in `curate.md`. Write it as it is heard rather than at session end — a call rehearsal rarely gets a tidy close.

#### enhancement-6 — Add: intake in the client's language breaks the traceability contract the module holds everywhere else

- Lens: enhancement
- Location: `references/intake.md (Write the conversation down as a source)`
- Evidence: `intake.md` demands verbatim capture — 'a citation has to be verbatim or the checker will reject it' — and registers `conversation.md` as a real source that `inventory-check.py` re-opens. It never mentions language. The rest of the module handles this deliberately: the feature-inventory schema carries `quote` (translated into the working language) plus `quote_original` and `quote_language`, and `est-scope-extract` states that traceability a native reader cannot verify is not traceability. A conversational intake held in the client's language — the normal case for an outsourcing presale — falls between the two: the agent either writes translated text into `conversation.md` and calls it verbatim, or writes the original and produces an inventory a `document_output_language` reader cannot check. The agent loads `{communication_language}` and `{document_output_language}` on activation and then uses neither.
- Recommendation: Two lines in the capture section of `intake.md`: when the conversation is not in the working language, `conversation.md` holds what was actually said, and each feature's citation carries the original in `quote_original` with `quote_language` set and the translation in `quote` — the same contract `est-scope-extract` honours for a client PDF. Add the note that terms ambiguous in translation are clarity-score inputs, not just noise, which is already the module's stated position for documents.

#### enhancement-7 — Remove: the portfolio scan fires on every activation, including when the opening already names the target

- Lens: enhancement
- Location: `SKILL.md (On activation)`
- Evidence: The on-activation block runs `portfolio.py` across every workspace and every ledger entry before the first reply, then greets with what needs attention. That is right for the cold open. It is ceremony for the invocations the agent's own description advertises — 'explain this estimate', 'the client says it's too expensive', 'what if we drop X', 'what fits in 600 hours' — where the user has already named the target and the correct first move is to load that brief. In a company running many parallel projects the scan returns a portfolio-wide JSON whose attention signals are about other people's deals, and the greeting protocol ('greet with what actually needs attention') has nothing to attach to when the user opened with a question.
- Recommendation: Make the scan conditional in one clause: run it when the opening is unspecific, and when the user arrives naming a project or a number, go straight to that workspace and scan only if what they named is not there or is stale. Nothing is lost — the bearings the scan provides are worth having exactly when the user has not supplied a target, and the staleness signals that matter for a named project (`re-estimate: scope changed`) are still reached by the fallback.

#### enhancement-8 — Add: the batch loop the plan promised has no owner — but a headless activation mode is the wrong shape for it

- Lens: enhancement
- Location: `SKILL.md (whole); references/triage.md`
- Evidence: The plan promises 'Headless supported for "estimate this folder and report" batch runs' and warns the agent 'must not become a bottleneck for batch presale processing'. The agent has no headless story at all, which is the right call for a conversational front door — a `-H` contract here would duplicate the `-H` contracts the three workflows already carry, and the agent's value (judgement, challenge, curation) is exactly what an unattended run cannot use. The genuine gap is narrower: nothing in the module owns the loop of N pending inputs → N extractions → N estimates → one ranked read. `est-scope-extract`'s headless return was built for precisely this ('lets a batch of twenty presale extractions be triaged by a human in minutes'), and `portfolio.py` already runs unattended with `-o`, so the pieces exist unassembled. Today the presale lead facing a folder of eight pending deals gets no help from the one skill whose stated purpose is deciding which deal to work first.
- Recommendation: Do not add a headless activation mode. Add a short batch recipe to `triage.md`: run `est-scope-extract -H` then `est-estimate -H` over each input folder, collect the `needs_confirmation` lists, then `portfolio.py -o` for the ranked read — and then do the part only the agent can do, which is reading the pooled `needs_confirmation` and attention signals back as a decision about where the next hour goes. Note in SKILL.md that unattended batches are the workflows' job so nobody wires the agent into a cron.

#### agent-cohesion-3 — comparables.md is named as the anchoring corpus but no capability ever reads it

- Lens: agent-cohesion
- Location: `skills/est-agent-estimator/SKILL.md:47 (conventions); references/curate.md:41`
- Evidence: `{memory}/comparables.md` appears exactly twice in the agent: once in the path conventions, once in curate.md as "the anchoring corpus" that `est-calibrate` writes to and Nadia may append to. Nothing reads it. Yet the persona is a fifteen-year veteran, and the first instinct of such a person facing any number is what the last three projects of this shape actually came in at. Three places obviously want it: defend.md's "Sanity-check a human's number" (which anchors only on `manual_equivalent.build_hours`, a synthetic baseline, when a delivered comparable is far more persuasive to a sceptic), defend.md's defence under challenge ("we quoted this shape at 900 and delivered at 1,050" beats any coefficient argument with a client), and triage.md's bid/no-bid read. A user asks "have we done anything like this before?" — an obvious question for this persona — and the agent has nowhere to go.
- Recommendation: Add a read of `{memory}/comparables.md` to defend.md, in the sanity-check section and in "Defend under challenge", with the honesty guard the module's voice demands: a comparable is an anchor, not evidence, and it is worth quoting only with its scope shape and how far its actual landed from its estimate. Add one line to triage.md's bid/no-bid so a similar delivered project informs the recommendation. Keep the write path in curate.md where it already is.

#### agent-cohesion-4 — The non-negotiable holds for the priced estimate but not for scenario numbers — the numbers actually said out loud in a client call

- Lens: agent-cohesion
- Location: `skills/est-agent-estimator/SKILL.md "The non-negotiable"; references/defend.md "What-if"; scripts/scenario.py `run()``
- Evidence: The chain is hours → phase or feature → the coefficient → the tag → the client's sentence. For the base estimate it is genuinely enforceable: `estimate-brief.json` carries `features[].hours`, `why.<axis>.value`, `why.<axis>.why`, `why.<axis>.status` and `source.quote`, and defend.md walks it. Two links do not hold. (a) The coefficient step has no source on Nadia's reading list: the brief omits the cost model, and defend.md explicitly restricts `estimate.json` reads to `scope_split[].standalone_hours`, `dependencies`, `duration` and `project_components` — `cost_model_snapshot` and `features[].component_hours` are not among them. (b) `scenario.py` returns `scenario_estimate` as `total_hours`, `by_phase`, `by_role` and `features_priced` only — no per-feature breakdown of the variant. For `--drop` a user can mostly re-derive from the brief, but under `--retag` and `--set team_profile=senior-heavy` every feature's hours change and there is no feature-level output at all, so "830 under a senior-heavy team" decomposes one level to phase and then stops. Those are precisely the numbers said in a live negotiation, so the rule is weakest exactly where it matters most.
- Recommendation: Two small changes make the slogan real. Name the coefficient's location in defend.md's chain (`features[].component_hours` in `estimate.json` for the split, `cost_model_snapshot` for the rate that produced it) and add it to the short list of fields the brief deliberately leaves out — or, if the coefficient is deliberately out of scope for a conversation, drop that link from SKILL.md's chain rather than promising it. And have `scenario.py` return the variant's per-feature hours (id, hours, delta) so a re-priced figure walks down the same chain; where that is not worth the token cost, say explicitly in defend.md that a scenario headline decomposes to phase and role and that the feature chain must be walked on the baseline.

#### agent-cohesion-5 — The change-request journey has an undocumented input and no durable output

- Lens: agent-cohesion
- Location: `skills/est-agent-estimator/references/defend.md "What-if" (`--add-file change-request.json`)`
- Evidence: Pricing a change request against a sold project is one of the agent's headline journeys, and defend.md flags it ("It also runs against a ledger entry, which is how you price a change request against a project that is already sold"). But `--add-file change-request.json` is listed as a bare command with nothing said about what the file must contain. `scenario.py`'s `apply_mutations` takes the features as given; the added feature needs the five axes, a `why` per tag and, by the module's own traceability bar, a citation — none of which is stated anywhere, and intake.md covers building a whole inventory rather than authoring one feature to that bar. Then the result goes nowhere: the re-price is terminal JSON, no revision is recorded against the ledger entry, so the next `portfolio.py` run shows the sold project exactly as before and the agreed number and the quoted number silently diverge — the scope-creep case triage.md says the module exists to catch.
- Recommendation: Give the change-request path its own short subsection in defend.md: what the added feature file must carry (the five tags each with a one-line why, a `commitment`, and a quote from the client's request — the request email is a citable source), the command against the ledger entry, and what happens afterwards. Say explicitly how the outcome is recorded — a `--revision` ledger entry via est-estimate, or an appended source and re-run — so the portfolio sees it. Pair this with agent-cohesion-2, which owns the ledger-writing commands.

#### agent-cohesion-6 — Nothing Nadia produces in a defend session leaves the terminal, including the artefact she is told to send

- Lens: agent-cohesion
- Location: `skills/est-agent-estimator/references/defend.md ("Cut lines", "Range-narrowing questions")`
- Evidence: The mission is that the human leaves with a number they can defend to someone who is not in the room — but every defend-session output dies in the conversation. defend.md says of `narrowing_questions`: "it is the right thing to send a client instead of a tighter number" — and then gives no way to produce a sendable thing. The cut-line table, `candidates`, `restored_as_unnecessary` and the dependency warnings are the substance of a follow-up email and exist only as stdout JSON (`scenario.py -o` writes JSON, which is not client-facing). Meanwhile est-estimate renders an interactive HTML report where "unticking a feature recomputes the whole estimate live — including the project overheads that shrink with it" — exactly the artefact for the scope-cutting conversation — and defend.md never mentions it exists. A presale lead ends the session with a screenful they must retype.
- Recommendation: Point defend.md at the HTML report as the thing to send when the conversation is about dropping scope, and add a closing beat to the what-if and cut-line sections: write a short markdown note into `{workspace}` — the scenario, the honest saving with `saving_vs_own_hours` in its own words, the dependency warnings, and the ranked narrowing questions with their `assumes` — so the answer survives the conversation and can be pasted into a client email. This is an opportunity rather than a defect, but it is the difference between the mission being stated and being delivered.

### Low (11)

#### leanness-1 — defend.md restates persona stance it already inherits

- Lens: leanness
- Location: `skills/est-agent-estimator/references/defend.md — 'Defend under challenge' opening; 'Sanity-check a human's number' opening`
- Evidence: Two sentences in defend.md re-state stance SKILL.md's persona already establishes, and the reference inherits it for free. defend.md: "'The client says this should be half' is not an attack, it is the next part of the job." against SKILL.md Identity: "You treat a client's challenge as a normal part of the job rather than an attack." And defend.md: "your job is to locate the disagreement, not to win it" against SKILL.md Communication style: "Locate the disagreement precisely instead of defending the number." This is the repetition case the lens spec names (identity text copy-pasted into a capability prompt that inherits it), not a voice finding — it adds no character, and cutting it removes nothing from the persona, which stays intact in SKILL.md.
- Recommendation: Delete both stance clauses from defend.md and open each section on its operational content — 'Work the challenge in the order below' and 'Compare their figure against by_phase and ask where they differ.' Absence cost: none. The stance is already loaded at activation and is not re-derivable only from defend.md.

#### leanness-2 — 'Work it in this order' asserts a sequence that is three independent obligations

- Lens: leanness
- Location: `skills/est-agent-estimator/references/defend.md — 'Defend under challenge'`
- Evidence: The section says "Work it in this order" over four bolded steps: find where the give is, name where there is no give, price every proposed cut, and route coefficient challenges to curate.md. Only the third guards a named failure ("A cut that looks like 80 hours is routinely 120 or 45"), and the fourth is routing, not a step. Sorting features by hours and reading risk_quadrant are independent reads of the same artefact with no dependency between them; the only ordering claim is conversational ("saying so early is more persuasive than defending the total afterwards"), which is advice about the client call rather than a constraint on the model's process. Per Test 3, an asserted order makes the model march the steps rather than adapt to what the challenge actually was.
- Recommendation: Drop 'Work it in this order' and demote the first two bolded items to bullets, keeping the persuasion clause on the no-give bullet. Keep 'Price every proposed cut before you agree to it' with its why as a standing rule, not step three. Absence cost of the ordering: nothing — the failure it appears to guard is already guarded by the pricing rule and the non-negotiable in SKILL.md.

#### leanness-3 — Company-profile interview list is half re-teach

- Lens: leanness
- Location: `skills/est-agent-estimator/references/triage.md — 'The company profile interview'`
- Evidence: Six bulleted items, each with its own rationale (~210 tokens). Three carry knowledge the model cannot infer: the mobile MCP server question ("nobody volunteers it", and the industry default overstates mobile), the new-to-BMad learning-curve modifier and that it decays, and the confirmation that the Architect absorbs PM responsibilities deliberately. The other three — team shape and seniority mix, dominant stacks, typical client engagement model — are what any capable model asked to profile a delivery org for cost purposes would ask about unprompted, and their attached whys ("a stack the team has shipped five times compresses more") explain a mechanism the reader infers from the axis names. The consumer statement (est-estimate reads it for profile defaults, est-calibrate reads it for modifier retirement) is the line doing the real work and it sits last.
- Recommendation: Lead with the two consumers, keep the three non-inferable items named explicitly, and let the obvious coverage follow from the outcome rather than a bulleted bank. See proposed_smallest.
- Proposed smallest: ## The company profile interview

Run this the first time `{memory}/company-profile.md` is missing; every estimate afterwards rests on it, and generic coefficients priced against the wrong team shape are the fastest way to lose credibility on the first number.

Interview conversationally and write prose a person can edit. `est-estimate` reads it for its default profile inputs and `est-calibrate` reads it to decide whether a team's learning-curve modifier has served its purpose — so cover team shape and seniority, dominant stacks, BMad adoption depth per team and the client engagement model that sets the overhead rate. Ask by name about the two nobody volunteers: whether the mobile MCP server does the QA testing (the industry default overstates mobile badly), and which teams are still new to BMad (that modifier is real and it decays, so record who is inside it). Confirm the Architect absorbs PM responsibilities during planning — the absence of a PM role in the split is deliberate.
- Predicted delta: None material. Both downstream consumers, all three non-inferable items and the credibility why survive; what is lost is the per-bullet rationale for seniority, stacks and engagement model, which a model reconstructs from the axis names. Saves roughly 90 tokens on a reference that fires on first activation. Route to variant eval to confirm — the one dimension worth watching is whether the shorter form still gets adoption-depth asked per team rather than once for the company.

#### leanness-4 — Entry-file prose restated operationally by the reference that owns it

- Lens: leanness
- Location: `skills/est-agent-estimator/SKILL.md — 'What to load, and when' lead paragraph; 'Gotchas' final bullet`
- Evidence: Two facts are stated in full in SKILL.md, which is paid on every invocation, and then stated again in operational form where they are used. (1) 'Read the brief, not the full artefact' plus three sentences on why estimate.json and analysis.json are machine-written, against defend.md's opening: "Load {workspace}/estimate-brief.json. It is the distillate built for this conversation... Reach for estimate.json only for scope_split[…].standalone_hours, dependencies, duration and project_components" — the reference version is strictly better because it names the exceptions. (2) 'A wide band is information, not a failure. It is computed from input completeness' appears in three references with a different action attached each time: defend.md quotes confidence.why, intake.md pairs it with narrowing_questions, triage.md turns it into the fixed-price bid risk. The SKILL.md instance is the only one that adds no action. The reference-side instances are defensible under the stand-alone rule; the entry-side full statements are the restatement.
- Recommendation: Truncate rather than delete, since SKILL.md is the fallback when no reference has loaded. Cut the brief paragraph to its non-inferable half: 'Read the briefs — `estimate-brief.json`, `accuracy-brief.json`. `estimate.json` and `analysis.json` are machine-written and do not belong in a conversation.' Cut the band gotcha to its one load-bearing clause: 'A wide band is computed from input completeness — narrowing it means answering questions, not being braver. When someone asks for a tighter number, give them the questions.' Absence cost of what is trimmed: nothing, since defend.md carries the field-level version and the accuracy-brief half is preserved. Roughly 70 tokens off the always-paid entry file.

#### architecture-6 — Reference routes to another reference

- Lens: architecture
- Location: `references/defend.md:33`
- Evidence: defend.md sends the coefficient-challenge branch to `references/curate.md`. References are meant to resolve one level deep — SKILL.md routes to a reference, never a reference to a reference. It reads as a capability handoff rather than nested content, so the cost is low, but SKILL.md:68 already routes that same case.
- Recommendation: Keep the sentence and drop the path: "that is a calibration conversation, not a negotiation" is enough for the agent to re-enter through SKILL.md's routing table.

#### determinism-7 — Definitions the engine owns are re-declared in the agent's scripts

- Lens: determinism
- Location: `scripts/scenario.py:29, :169-172; scripts/portfolio.py:125`
- Evidence: `AXES = ("size_band", "compressibility", "review_tier", "clarity", "novelty")` is scenario.py's own copy of a tuple estimate.py repeats inline four times (estimate.py:123-127, and again in `brief()` at render-estimate.py:151-155); a sixth axis added to the cost model would make `--retag` reject it with "is not a classification axis". Separately, band width has no single owner: the engine works in `band = 2 * half_band` (estimate.py:472) and reports `narrowing_questions[].band_reduction_pct` against it, while scenario.py:169-172 defines the band as `high - low` and portfolio.py:125 as `(high - low) / likely`. `low` is clamped at zero (estimate.py:492), so the two definitions are not identical, and the agent can end up quoting two percentages computed against different denominators in the same breath.
- Recommendation: Publish both from the engine — export the axis tuple as a module constant scenario.py imports, and emit `confidence.band_width` (and `band_width_pct`) in build_estimate for portfolio.py and scenario.py to read. Same rule as `inventory_from`: one definition, beside the pricing that owns it.

#### determinism-8 — Script standards: no --verbose, and refusals print to stdout rather than stderr

- Lens: determinism
- Location: `scripts/scenario.py:476-528, scripts/portfolio.py:230-292`
- Evidence: Both scripts conform on the load-bearing points: shebang on line 1, PEP 723 block with `requires-python = ">=3.10"`, stdlib only, `argparse` with `--help`, positional or required target, `-o/--output`, documented exit codes (0 done, 1 refused, 2 unreadable), and error messages that name the recovery rather than the fault — scenario.py:46-51 tells the reader where to find estimate.py and which flag passes it, and portfolio.py:242-247 states that a missing estimates folder "is a legitimate day-one state, not a failure". Two gaps against script-standards.md: neither script implements `--verbose`, and all diagnostics — including `Refused` messages and exit-2 read errors — are printed as JSON on stdout, where the standard puts diagnostics on stderr.
- Recommendation: Add `--verbose` (scenario.py has an obvious use: report each re-price the `--to-budget` walk performs, which is currently invisible and can be dozens of engine calls). Keep the JSON-on-stdout error envelope if it stays module-wide — every sibling does the same and the agent parses it — but mirror the message to stderr so a shell caller sees the refusal without parsing. Graceful degradation is deliberately and correctly absent for scenario.py: SKILL.md:40 forbids the hand-arithmetic fallback outright, which is the right call for this domain and should not be 'fixed'.

#### customization-3 — `name` and `title` carry no read-only comment while the persona hardcodes Nadia

- Lens: customization
- Location: `customize.toml:13-15`
- Evidence: `name = "Nadia"` and `title = "Delivery Estimator"` are install-time roster metadata, read-only at runtime. SKILL.md hardcodes the identity throughout — the H1, "You are Nadia", and the frontmatter description's trigger phrase "talk to Nadia". A user who sets `[agents.est-agent-estimator] name = "..."` in `_bmad/custom/config.toml` will change the roster label and watch the agent keep introducing itself as Nadia, with nothing in the file warning them. Populated `name` is correct here — First-Breath naming does not apply to a stateless agent.
- Recommendation: Add one comment line above the block, e.g. `# name/title are install-time roster metadata — read-only at runtime; overriding them in _bmad/custom/ renames the roster entry, not the agent.`

#### enhancement-9 — Add: defend prepares the material but never rehearses the conversation

- Lens: enhancement
- Location: `references/defend.md (Defend under challenge)`
- Evidence: The plan's stated outcome for this capability is 'Rehearse the client conversation before having it', and calls it the capability most likely to be used daily. What was built answers the user's questions about the number very well, but the pressure only ever comes from the user quoting the client secondhand. The weak spot in a real call is the challenge nobody anticipated — and the agent is holding the exact ammunition a procurement lead would use: `risk_quadrant` (the work you are charging most for is the work you say your tooling does not help with), `outside_agreed_scope_pct`, an `inferred` sensitive tag carrying 40% of the review hours, and `calibrated: false`.
- Recommendation: Offer a rehearsal turn in `defend.md`: when the user is preparing for a call rather than asking a question, offer to play the client's side and attack the number from those four fields, one challenge at a time, then drop back into Nadia to work the answers that came out thin. Offer it, never impose it — a user who wants a fast answer should not have to sit through a role-play.

#### agent-cohesion-7 — intake.md's `inventory-check.py` resolves to a path that does not exist

- Lens: agent-cohesion
- Location: `skills/est-agent-estimator/references/intake.md (opening paragraph and "Then hand off")`
- Evidence: SKILL.md conventions state that bare paths resolve from this skill's directory. intake.md refers to `inventory-check.py` bare, twice, but the script lives at `{project-root}/skills/est-scope-extract/scripts/inventory-check.py` — the agent ships no such script. The same paragraph gets the schema right (`{project-root}/skills/est-scope-extract/assets/feature-inventory.schema.json`), so the inconsistency is visible within one sentence. The invocation also omits the `--normalized` and `--manifest` arguments the checker needs to re-open sources and verify quotes, which is the entire point of running it. intake.md additionally never says how `{workspace}` comes to exist for a conversation that starts with no project slug and no folder.
- Recommendation: Largely dissolves if agent-cohesion-1 is taken, since est-scope-extract runs its own checker with its own arguments. If intake keeps any direct invocation, write the full path and the full command, and add the one line that opens the workspace and settles the project slug before the conversation is written down.

#### agent-cohesion-8 — The company profile is split across two references — created in triage.md, edited in curate.md

- Lens: agent-cohesion
- Location: `skills/est-agent-estimator/references/triage.md "The company profile interview"; references/curate.md "What you can change freely"`
- Evidence: triage.md carries two deal-facing topics (portfolio reading, bid/no-bid) plus a first-run setup ritual that has nothing to do with either and is reached from a different trigger — SKILL.md's activation check for a missing `company-profile.md`. curate.md already owns the file for edits and states what reads it. The four-way carve is otherwise sound: defend, intake, triage and curate are four things a user distinctly asks for, and none is a slice of another.
- Recommendation: Move the six-question profile interview into curate.md, which already owns everything about writing to `{memory}`, and point SKILL.md's activation check there. triage.md then reads cleanly as "which deal, and should we bid it", and the first-run journey lands in one file that owns both creating and correcting the profile.
