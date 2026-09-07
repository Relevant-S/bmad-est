# Analysis Report: skills/est-scope-extract

Generated: 2026-09-07 · Schema: 2

**Grade: Excellent**

> All twenty-three findings are resolved. The critical defect — citations pointing at the wrong workbook row — is fixed and regression-tested, and the traceability guarantee the module rests on is now enforced by script rather than asserted in prose.

est-scope-extract went into analysis with a clean architecture and a defect that a real-input eval had read straight past: workbook citations pointed at the wrong row, and a quoted multi-line field was silently corrupted. Both are fixed, and the wider gap they exposed is closed — inventory-check now re-opens the sources to verify quotes, resolve location anchors, list unreferenced regions and reconcile the manifest, while inventory-diff performs the update merge deterministically instead of having the model retype verbatim quotes. The headless contract, absent entirely, is now defined with a conservative default at every human gate. 101 unit tests pass and an eight-document adversarial fixture corpus now guards the class of failure that reads plausibly while being wrong.

| Severity | Count |
| --- | --- |
| Critical | 1 |
| High | 8 |
| Medium | 11 |
| Low | 3 |

## Themes

### 1. The traceability guarantee was asserted, not enforced

- Root cause: The skill names silent invention and silent omission as the failures that would destroy trust in the module, then leaves both to a self-review by the context that did the extracting. Every mechanical check validated the inventory against itself; nothing re-opened the sources. The critical row-anchor bug is what that gap produces — a citation that is confidently wrong and reads perfectly.
- Fix: Make every claim the skill makes about its own output mechanically checkable against the normalized sources: quote presence (done), location-anchor resolution, region coverage, and manifest-to-sources reconciliation. Reserve the model for the one judgement no script can make — whether the feature actually follows from the quote.
- Findings:
  - `determinism-1` Emitted row numbers were not source row numbers, so workbook citations pointed at the wrong row — `scripts/convert-input.py (_rows_to_markdown, convert_xlsx, convert_csv)`
  - `determinism-2` Citation verification — the module's stated non-negotiable — was left to model spot-checking — `references/update-and-validate.md; scripts/inventory-check.py`
  - `determinism-3` The coverage pass has no script support; the model holds whole-document accounting in its head — `SKILL.md (Create — coverage); scripts/inventory-check.py (coverage)`
  - `determinism-7` Nothing cross-references the convert-input manifest against the inventory's sources array — `SKILL.md (Create); scripts/inventory-check.py`
  - `enhancement-1` No independent review of the inventory before create finalizes it — `SKILL.md (Create — coverage, check, render)`

### 2. Headless is claimed everywhere and defined nowhere

- Root cause: The module plan requires headless for batch presale triage and the skill branches on it, but no line says how headless is detected, what it returns, or what it does at the two human gates. The sharpest consequence was a contradiction: a check that would not clear until a commercial decision was made, beside a rule forbidding the agent from making it.
- Fix: Define the headless contract once — detection, JSON return, memlog assumption logging, and a stated conservative default at every human gate — and give the interactive path a batched confirmation step as the middle mode.
- Findings:
  - `architecture-1` Headless mode is claimed but routes to no activation path or return contract — `SKILL.md (Create, Workspace, Gotchas)`
  - `architecture-2` The check-until-clean loop forced a headless run to make the commercial call the skill forbids — `SKILL.md (Create vs Gotchas); scripts/inventory-check.py`
  - `enhancement-3` Headless has no mode detection, no return, and no stated defaults for the human-gated calls — `SKILL.md (the interactive-only gates)`
  - `enhancement-5` The interactive confirmation tail is unbounded and invites rubber-stamping — `SKILL.md (Create — interactive confirmations)`

### 3. The update path leaves deterministic work to the prompt

- Root cause: inventory-diff.py computes everything a merge needs and stops at reporting, so the model retypes the whole inventory by hand — including the verbatim quotes whose byte-fidelity the guarantee rests on. Staleness detection and the merge itself are both script work sitting in prose.
- Fix: Add --merge to inventory-diff.py emitting the merged inventory with protected values restored and a needs_decision list, fold staleness into inventory-check, and make update-and-validate.md standalone by naming the three files it silently depends on.
- Findings:
  - `determinism-4` Update mode has the model hand-rewrite the merged inventory JSON — `references/update-and-validate.md (Update)`
  - `determinism-6` Staleness detection is asked of the prompt — `references/update-and-validate.md (Validate)`
  - `enhancement-2` Update executed before it validated, destroying its only copy of the human tags — `references/update-and-validate.md`
  - `architecture-3` references/update-and-validate.md is not standalone — it delegates back to SKILL.md — `references/update-and-validate.md (Update)`

### 4. Judgement presented as computation

- Root cause: The completeness score was described as a published formula immune to judgement while 74% of its weight came from three-valued strings the model picked with no reason required — held to a lower standard than the feature tags the same script rejects for an empty 'why'.
- Fix: Hold every judgement input to the same interrogability standard as a tag, and state plainly which part of a number is fixed and which is judgement.
- Findings:
  - `determinism-5` The completeness score was a judgement call laundered through arithmetic — `SKILL.md (Gotchas); scripts/inventory-check.py; assets/feature-inventory.schema.json`
  - `leanness-2` Trigger vocabulary restates the table row directly above it — `references/classification-guide.md (review_tier)`

### 5. The run's setup is never established before ingestion

- Root cause: Three things the whole run depends on — the workspace slug, the granularity, and whether a contractual source is present — are discovered incidentally or not at all, which is why one schema field is rendered on every view without any instruction ever setting it.
- Fix: Open create with two sentences that name the project, set granularity, and confirm which source is contractual; define {project-slug} in Resolution rules and add workspace discovery so an interrupted run can resume.
- Findings:
  - `architecture-4` {project-slug} is never defined and nothing discovers an existing workspace — `SKILL.md (Workspace, Intents); references/update-and-validate.md`
  - `architecture-5` Schema field `granularity` is set by no instruction yet rendered in every view — `assets/feature-inventory.schema.json; scripts/render-inventory.py`
  - `enhancement-4` No intent-before-ingestion opening; create begins by converting files — `SKILL.md (Create)`

## Strengths

- The schema is a real contract, not documentation: inventory-check.py validates against the schema file itself, so there is one source of truth, and it catches what a schema cannot — dangling references, dependency cycles, missing original-language quotes, empty justifications.
- The human-override protection is genuinely load-bearing and was verified on real data: with every feature renumbered, inventory-diff matched by name similarity and flagged both human decisions a re-extraction would have discarded.
- Every classification carries a required one-line reason, so no coefficient reaching est-estimate is unexplained — the constraint the user named as a condition for trusting the tool at all.
- Original-language quotes are preserved beside translations and enforced by the checker, so traceability survives a non-English source rather than quietly depending on the extractor being right.
- 77 unit tests across four scripts, including hostile inputs — pipes and newlines inside quotes, banner rows, blank rows, renumbered features — and a real-input eval on a three-source messy document set.
- Customization and path conventions pass with no findings; the declined-customization decision is executed coherently end to end.
- An adversarial fixture corpus (evals/) now encodes each way a real client document breaks an extractor — banner rows, embedded newlines, a non-English source, contradictory sources, a thin brief, unreadable formats — generated by script so it stays diffable, and reusable by the module's remaining skills.

## Recommendations

1. No outstanding work on this skill. Carry the adversarial fixture corpus and the Analyze pass forward as build gates for est-estimate, est-calibrate and est-agent-estimator.

## Experience

- **Presale, thin input** — A two-paragraph brief or a call transcript arrives → convert → extract with almost everything tagged clarity: low → completeness score lands low by construction → the deliverable is the ranked question list, and the report says whether to estimate now or go back to the client.
- **Presale, full document set** — SOW plus backlog workbook plus discovery call → convert with citable anchors → extract, dedupe across sources, surface conflicts rather than resolving them → classify on five axes → verify quotes against sources → render for the human and for sales.
- **Scope creep mid-delivery** — Client sends v2 → re-extract → diff → protected array names every human decision at risk → merge validated in a scratch file before it replaces the only copy → report says what was added, removed and retiered.
- **Pre-estimate confidence check** — Validate mode re-checks an inventory against its sources without writing anything, and says whether it is fit to estimate from.
- Headless: Fully specified in references/headless.md: detection, a conservative default at each of the five human gates, one memlog assumption entry per default taken, and a JSON return whose needs_confirmation field lets a batch of twenty presale extractions be triaged in minutes.

## Findings

### Critical (1)

#### determinism-1 — Emitted row numbers were not source row numbers, so workbook citations pointed at the wrong row

- Lens: determinism
- Location: `scripts/convert-input.py (_rows_to_markdown, convert_xlsx, convert_csv)`
- Evidence: convert_xlsx dropped blank rows and then renumbered the survivors from scratch while unconditionally treating row 1 as the header. Reproduced: a sheet with a title banner in row 1 and a blank row 2 emitted 'Login' — really at row 4 — as row 3, and the drift grew with every blank row above. The CSV path had the same defect from splitlines(), which additionally welded a quoted multi-line field into 'line oneline two', corrupting the quote itself. source-type-playbook.md told the model the conversion preserves row numbers. It did not.
- Recommendation: APPLIED IN THIS RUN. Both paths now carry the source's own coordinates — openpyxl row indices captured before filtering, csv.reader over the file object tracking line_num. No row is designated a header and columns are labelled A, B, C, because which row holds column names is a meaning question. Three regression tests fix the anchor contract: banner row, interior blank, quoted multi-line cell.

### High (8)

#### determinism-2 — Citation verification — the module's stated non-negotiable — was left to model spot-checking

- Lens: determinism
- Location: `references/update-and-validate.md; scripts/inventory-check.py`
- Evidence: No script re-opened the normalized sources at any point. inventory-check.py only checked that a quote was non-empty. So silent invention — a quote that is not actually in the document — was caught by sampling, in validate mode only; a create run never checked a single quote, though SKILL.md names this one of the two failures that 'make people stop trusting the whole module'.
- Recommendation: APPLIED IN FULL. --normalized now also resolves structured locations against the anchors the file actually has: a citation to 'sheet Backlog row 99' or 'page 7' of a two-page PDF is reported with the real range. Original recommendation: APPLIED IN THIS RUN, in part. inventory-check.py now takes --normalized DIR and confirms every quote appears in the document it cites, reporting a similarity ratio that separates a paraphrase from a fabrication; foreign-language sources verify against quote_original. Wired into create and both secondary intents. STILL OPEN: the lens also asked that `location` be checked to resolve to an anchor the file actually contains (page marker, sheet+row, heading). That half is not implemented.

#### determinism-5 — The completeness score was a judgement call laundered through arithmetic

- Lens: determinism
- Location: `SKILL.md (Gotchas); scripts/inventory-check.py; assets/feature-inventory.schema.json`
- Evidence: SKILL.md claimed the score 'has to come from a published formula rather than a judgement call'. Every input was model judgement: the six ordinal signals carried 0.74 of the weight as three-valued strings with no evidence requirement — no why, no status, no citation — while check_integrity rejected an empty `why` on a feature tag as 'a black-box coefficient'. Moving acceptance_criteria none→most added 0.20 to the number that sets estimate band width. ORDINALS was also one flat namespace across six vocabularies, scoring an unmapped value identically to an explicit 'none'.
- Recommendation: APPLIED IN THIS RUN. completeness_signals now take the same {value, why, status} shape as tags, and inventory-check enforces a non-empty `why` and a per-signal vocabulary. SIGNAL_POINTS is keyed per signal, so an unmapped value is a finding rather than a silent zero. The SKILL.md claim is corrected to what is true: the weights are fixed and published so band width cannot be tuned per run; the signals are judgement, recorded with reasons.

#### determinism-3 — The coverage pass has no script support; the model holds whole-document accounting in its head

- Lens: determinism
- Location: `SKILL.md (Create — coverage); scripts/inventory-check.py (coverage)`
- Evidence: SKILL.md asks the model to 'walk each normalized source end to end and confirm every substantive passage produced either a feature or a not_scope entry'. The only mechanical support is sources_contributing_nothing, which fires only when a whole source has zero citations and zero not_scope entries. Between 'this source was opened' and 'every passage in it is accounted for' there is nothing — yet the skill calls this pass non-optional and names silent omission a trust-killer. convert-input.py emits page, sheet/row and heading anchors that no consumer uses for coverage.
- Recommendation: APPLIED. inventory-check now returns unreferenced_regions — every page and workbook row nothing cites, with the source it belongs to. The coverage pass is a short list to judge for substance rather than a whole-document memory exercise. Original recommendation: Apply the pre-pass JSON pattern: have inventory-check enumerate every anchor region in each normalized file — page markers, `## sheet:` blocks and their rows, heading sections — and emit, per region, whether any citation or not_scope entry points into it, plus char count and first line. The model then reads a short list of unreferenced regions and judges only 'is this substantive?' rather than rebuilding the mapping by reading whole documents.

#### determinism-4 — Update mode has the model hand-rewrite the merged inventory JSON

- Lens: determinism
- Location: `references/update-and-validate.md (Update)`
- Evidence: inventory-diff.py already computes pairs, added, removed, changed and protected — everything a merge needs — but stops at reporting. The model then regenerates the whole inventory by hand on every update run, including every verbatim quote and quote_original: generation cost proportional to inventory size, paid each time, over exactly the strings whose byte-fidelity the traceability guarantee rests on.
- Recommendation: APPLIED. inventory-diff --merge <out> emits the merged inventory: new pass as base, stable old ids preserved so external references still resolve, every human confirmed/overridden tag restored with its why, non-colliding ids for new features, and a needs_decision list for the two cases the prompt must not settle alone. Verbatim quotes are never regenerated. Original recommendation: Add --merge <out> to inventory-diff.py (or a sibling inventory-merge.py) emitting the merged inventory: the new pass as base, every protected entry restored to the human's value, why and status, plus a needs_decision array for the cases the prompt is told not to decide alone — a protected tag whose source text changed, a feature absent because a different document was supplied. The model then answers a short question list instead of retyping the file.

#### enhancement-1 — No independent review of the inventory before create finalizes it

- Lens: enhancement
- Location: `SKILL.md (Create — coverage, check, render)`
- Evidence: Pattern: parallel review lenses. The coverage pass is a self-review by the same context that did the extracting — the context least able to see what it skipped, and the one most likely to have been compacted mid-document on a long RFP. Nothing independent tests either half of the stated non-negotiable.
- Recommendation: APPLIED. Create now fans out one subagent per normalized source before finalizing, each given only that source and the entries citing it, returning invented/omitted. The sequential fallback is named inline and the report records which way it ran. Original recommendation: After inventory-check comes back clean and before extraction-report.md is written, fan out one subagent per normalized source. Each gets the source path and only the features and not_scope entries citing that source, and returns ONLY {invented[], omitted[], misquoted[]}. Fix and re-run. Name the fallback inline: when subagents are unavailable, do the same two checks sequentially and say in the report which mode ran. NOTE: the --normalized quote verification added in this run covers the misquoted case mechanically, which narrows but does not close this.

#### enhancement-2 — Update executed before it validated, destroying its only copy of the human tags

- Lens: enhancement
- Location: `references/update-and-validate.md`
- Evidence: Pattern: plan-validate-execute. Update built the plan artifact correctly (feature-inventory.next.json plus the diff with its protected array) and then wrote the merge over feature-inventory.json, deleted the .next.json, and only then re-ran the check. The overwritten file is the only copy of every human confirmed/overridden tag, so a merge that dropped one destroyed the record the intent exists to protect — with nothing left to re-merge from.
- Recommendation: APPLIED IN THIS RUN. The merge now goes to feature-inventory.merged.json, is checked there, and is re-diffed against the original with the requirement that the protected array come back empty — the self-correcting check the pattern asks for, using machinery that already existed. Only then is the original moved to .prev.json and the merged file promoted.

#### architecture-1 — Headless mode is claimed but routes to no activation path or return contract

- Lens: architecture
- Location: `SKILL.md (Create, Workspace, Gotchas)`
- Evidence: The skill asserts a headless branch but nothing defines how a headless run is recognised (no flag, no {headless_mode}, no invocation contract) or what it returns. skill-quality-principles requires a JSON return carrying status plus the paths the caller needs, and requires the memlog to absorb every assumption made without the user. Neither exists: the Workspace section scopes memlog writes to human tag overrides, so a run with no human present writes nothing and the audit trail for the assumption-heavy case is empty. est-estimate is named as the consumer and would get prose back rather than a path contract.
- Recommendation: APPLIED. references/headless.md defines detection, the default at every human gate, memlog assumption logging, and the JSON return with status/paths/needs_confirmation and a reason on blocked. The Workspace memlog clause now covers unattended assumptions. Original recommendation: Add one activation line naming the headless trigger, a short JSON return block (status, workspace, feature-inventory.json, extraction-report.md, .memlog.md, completeness score, needs_confirmation[]; reason on blocked), and widen the memlog clause from 'when a human overrides a tag' to 'a human override, or, headless, each assumption made in place of a confirmation'. One clause, not a new section.

#### enhancement-3 — Headless has no mode detection, no return, and no stated defaults for the human-gated calls

- Lens: enhancement
- Location: `SKILL.md (the interactive-only gates)`
- Evidence: Pattern: three-mode architecture. The module plan specifies headless for batch presale triage. SKILL.md branches on it once but never says how headless is detected, returns no JSON, and logs no assumptions. A programmatic caller must guess the workspace path.
- Recommendation: APPLIED. See references/headless.md — detection, the three gate defaults, assumption logging and the JSON return. The frontmatter description now mentions -H. Original recommendation: Add a short ## Headless section. Detect as bmad-spec does: no TTY, programmatic caller, or pre-supplied inputs. State the defaults — sensitive/critical tags stay inferred, inferred dependencies stay inferred — appending each as a typed assumption via memlog.py, and return the JSON contract from architecture-1. PARTLY APPLIED IN THIS RUN: the scope_status gate now has an explicit headless arm (set the conservative value, record it as an assumption, surface it in the report), which was the case that actively forced a wrong decision.

### Medium (11)

#### architecture-2 — The check-until-clean loop forced a headless run to make the commercial call the skill forbids

- Lens: architecture
- Location: `SKILL.md (Create vs Gotchas); scripts/inventory-check.py`
- Evidence: Gotchas said scope_status is 'a commercial call, not an extraction call' and to stop and ask the operator. inventory-check.py enforced the same rule deterministically. Create then said 'fix every finding and re-run until clean.' With no operator present, those two instructions could only be satisfied by silently deciding the commercial question the skill had just said was not its to decide — both lines reading as correct in isolation.
- Recommendation: APPLIED IN THIS RUN. The gotcha now has a headless arm: set outside_agreed_scope (the conservative value), record it in assumptions and as a memlog assumption entry, and list it in extraction-report.md under what needs operator confirmation. The check clears without the decision being buried.

#### architecture-3 — references/update-and-validate.md is not standalone — it delegates back to SKILL.md

- Lens: architecture
- Location: `references/update-and-validate.md (Update)`
- Evidence: The update path says to extract new sources 'exactly as a create run would: citations, coverage accounting, five-axis classification, completeness_signals' and never says where any of that lives. It carries the convert-input.py invocation but not the rule governing it, and points at none of source-type-playbook.md, classification-guide.md or the schema. This is the stage-references-SKILL.md failure: it works while SKILL.md is in context and degrades silently after compaction — in the scope-creep case, where a wrong classification is most expensive.
- Recommendation: APPLIED. The file now names the three references it depends on, carries the normalized-read and needs_native_read rules inline, and stands alone under compaction. Original recommendation: Replace 'exactly as a create run would' with the three bare paths it means — references/source-type-playbook.md, references/classification-guide.md, assets/feature-inventory.schema.json — and carry the one-line normalized-read rule inline. About three lines, after which the file stands alone under compaction.

#### architecture-4 — {project-slug} is never defined and nothing discovers an existing workspace

- Lens: architecture
- Location: `SKILL.md (Workspace, Intents); references/update-and-validate.md`
- Evidence: Every path hangs off {output_folder}/estimates/{project-slug}/, but {project-slug} appears in neither the Resolution rules nor any prose, so each run improvises a slug. Nothing tells the agent to look for an existing workspace either: the Intents table separates create from update without saying how the agent learns which it faces. The uncovered state is an interrupted create run — workspace created, memlog initialised, inventory partial — matching neither row.
- Recommendation: APPLIED. {project-slug} is defined in Resolution rules, and Workspace carries the discovery rule: inventory present routes to update, a memlog with a partial inventory offers resume, nothing there means create. Original recommendation: Add {project-slug} to Resolution rules with its derivation (kebab-case of the project name the user gives), and one sentence in Workspace: once the project is named, look for the folder — inventory present, route to update; only a memlog and a partial inventory, read the memlog once and offer to resume; nothing there, create.

#### determinism-6 — Staleness detection is asked of the prompt

- Lens: determinism
- Location: `references/update-and-validate.md (Validate)`
- Evidence: 'If the inventory is stale — sources in normalized/ are newer than the inventory, or sources names a file that no longer exists — say so.' Comparing mtimes and testing file existence are canonical script operations, and inventory-check.py already has the inventory path open. No script implements this, so validate mode either skips the check or spends model turns shelling out for it.
- Recommendation: APPLIED. inventory-check reports stale: {newer_sources, missing_source_paths} in the same pass, using the --normalized directory it already receives. Original recommendation: The --normalized DIR flag added in this run already hands inventory-check.py the directory it needs, so this is nearly free: report stale: {newer_sources: [...], missing_paths: [...]} in the same JSON. Both facts are unit-testable with a fixture whose mtimes are set explicitly. The prompt decides what to do about staleness; it should not be detecting it.

#### determinism-7 — Nothing cross-references the convert-input manifest against the inventory's sources array

- Lens: determinism
- Location: `SKILL.md (Create); scripts/inventory-check.py`
- Evidence: convert-input.py emits a manifest with id, path, converter and needs_native_read per source; the model transcribes those into the inventory's sources entries by hand. inventory-check.py validates the inventory only against itself — source_ids is built from inv['sources'] — so a source the manifest converted but the model never listed is invisible to every check, including sources_contributing_nothing.
- Recommendation: APPLIED IN FULL. --manifest also now checks that a source the manifest marked needs_native_read carries a coverage_note, and compares filenames rather than full paths so the same file written as an absolute path in one place and a relative one in the other is not falsely flagged. APPLIED. inventory-check --manifest reconciles the convert-input manifest against the inventory's sources, catching both a converted source the inventory never listed and a listed source the manifest does not know about. Original recommendation: Add an optional --manifest flag to inventory-check.py that diffs the manifest's source ids and paths against the inventory's sources array, reporting converted-but-unlisted sources and listed-but-unconverted ones. A converted source missing from the inventory is silent omission at the document level — the coarsest possible version of the failure the skill exists to prevent — and it is a set difference.

#### enhancement-4 — No intent-before-ingestion opening; create begins by converting files

- Lens: enhancement
- Location: `SKILL.md (Create)`
- Evidence: Three things the run depends on are never established before ingestion. {project-slug} names the workspace but nothing says where it comes from. granularity drives est-estimate's fidelity mode and no step sets it. Most consequentially, whether a SOW or RFP is among the sources switches on the whole agreed-scope machinery — and the skill discovers that incidentally, mid-extraction, after the operator has stopped watching. A full open-floor opening would be ceremony here; the input is a set of file paths.
- Recommendation: APPLIED. Create opens by settling the project name, granularity, and which source is contractual — the last being what makes the later scope_status calls coherent rather than a mid-run surprise. Original recommendation: Two sentences before the convert step: name the project (the workspace slug), state what the estimate is for (which sets granularity), and confirm whether any source is contractual — one question against the manifest's own doc_type guesses. Settling the last up front is what makes the later scope_status calls coherent rather than a surprise. Headless takes all three from the caller's parameters and logs them as assumptions.

#### enhancement-5 — The interactive confirmation tail is unbounded and invites rubber-stamping

- Lens: enhancement
- Location: `SKILL.md (Create — interactive confirmations)`
- Evidence: 'Interactively, confirm two things before finishing: every feature tagged sensitive or critical, and every inferred dependency' is unbounded. On a 60-feature RFP whose compliance section raised a dozen tiers, plus inferred dependencies, plus each outside_agreed_scope call, that is thirty-odd separate approvals at the end of an already long run. The predictable outcome is rubber-stamping — and review_tier is the tag the classification guide calls the single highest-leverage one, so the fatigue lands exactly where accuracy matters most.
- Recommendation: APPLIED. Confirmations are presented as one table the operator accepts wholesale or corrects selectively, rather than as a queue of thirty approvals. Original recommendation: Present the confirmations as one batch rather than a sequence: a single table of items needing a decision, grouped by kind, that the operator can accept wholesale or correct selectively. This is the guided middle mode between full interactive and headless, and it is what makes the review survive a large document.

#### leanness-1 — Two Gotchas carry the full reference-file rule in the always-paid entry file

- Lens: leanness
- Location: `SKILL.md (Gotchas), against references/update-and-validate.md and references/source-type-playbook.md`
- Evidence: The scope_status gotcha and the source-type playbook state the same rule at the same length, with the same three options and the same justification; the protected-tag gotcha and update-and-validate.md likewise both state that confirmed/overridden outranks a fresh inference and both name inventory-diff.py's protected array. Both entry copies are branch-specific — the protected-tag rule can only fire on an update run, which loads that reference anyway — so the entry pays roughly nine lines on every invocation, including validate runs where neither rule is reachable.
- Recommendation: APPLIED, with the tension resolved rather than ignored. Both gotchas are cut to the rule plus a pointer. The headless behaviour they used to carry now lives in references/headless.md, which a headless run always loads — so nothing depends on a model loading a file for a situation it cannot recognise. Original recommendation: Truncate both entry gotchas to the rule plus a pointer, leaving the full versions in the reference files where they fire. NOTE, and this cuts against a straight application: the skill-quality principles hold that a gotcha whose trigger the model cannot recognise must stay in SKILL.md, because it cannot load a file for a situation it does not know it is in — and a headless create run may never load the playbook. Trim the justification prose; keep the operative rule and the headless arm inline.

#### enhancement-6 — Three external dependencies named no fallback; validate degraded silently

- Lens: enhancement
- Location: `references/update-and-validate.md; SKILL.md`
- Evidence: Validate's citation checks read normalized/; if that folder was cleaned, validate collapsed to a schema check yet could still report the inventory fit to estimate from. memlog.py was named with no fallback and no exact command. And the scripts were invoked only through uv, with no path for a machine without it.
- Recommendation: APPLIED. Validate now rebuilds normalized/ via convert-input.py, and where the originals are gone too it reports the citation check as NOT PERFORMED and refuses to certify the inventory. The memlog command is given in full with a hand-append fallback. SKILL.md states that the three stdlib-only scripts run under python3 without uv, and that missing conversion libraries route every source down the needs_native_read path.

#### enhancement-7 — The meta ## Workspace section was ceremony the working-state guidance forbids

- Lens: enhancement
- Location: `SKILL.md`
- Evidence: working-state-patterns.md says outright not to write a separate ## Workspace meta-section. Two of its three sentences instructed nothing — one declared a design choice, and the memlog clause sat three sections away from the only place an override actually happens.
- Recommendation: APPLIED. The section is gone. The layout and memlog init moved into Create where the workspace is opened; the memlog append moved to the confirmation beat, with the full command inline at the point an override occurs.

#### enhancement-8 — No entry point for an interrupted create run

- Lens: enhancement
- Location: `SKILL.md (Intents)`
- Evidence: create meant 'no existing inventory' and update meant 'an existing inventory'. A create run interrupted or compacted partway leaves a workspace with a memlog and a partial inventory, which matched neither row — the exact case a working-state strategy exists to catch.
- Recommendation: APPLIED. resume is now a fourth intent, and the routing rule is decided by looking rather than asking: a complete inventory means update, a partial one means resume, nothing there means create.

### Low (3)

#### architecture-5 — Schema field `granularity` is set by no instruction yet rendered in every view

- Lens: architecture
- Location: `assets/feature-inventory.schema.json; scripts/render-inventory.py`
- Evidence: The schema declares granularity with the enum project/epic/sprint/feature and the renderer prints it on every view with an 'unspecified' fallback, but the string appears nowhere in SKILL.md or any reference, so no run has a basis to set it. Every rendered inventory carries 'unspecified' into the artifact a human reviews beside the client's document.
- Recommendation: APPLIED. granularity is now set in the opening beat of Create, alongside the project name and the contractual-source question. Original recommendation: Set it in the Create beat that already sets completeness_signals, with one clause naming what decides it — which is also what enhancement-4 proposes establishing up front. Declared-but-never-set is the only option that costs without buying anything.

#### leanness-2 — Trigger vocabulary restates the table row directly above it

- Lens: leanness
- Location: `references/classification-guide.md (review_tier)`
- Evidence: The review_tier table's 'Raised by' column already gives sensitive as 'Money, personal data, authentication and authorization'. The four bullets that follow expand those same three categories into roughly sixty keywords, and the heading instruction — 'scan for these and their synonyms in any language' — concedes the list is not the operative thing, since the model must generalise past it anyway. The critical bullet is different and earns its place: GDPR, HIPAA, PCI-DSS, SOC 2, KYC and AML are named frameworks, a firmer boundary than the table's prose.
- Recommendation: APPLIED as a compression rather than a deletion. The three keyword bullets collapse to two lines naming the boundary; the named-framework list for critical is kept in full. An explicit vocabulary is retained because review_tier drives a 3-5x review multiplier and reproducibility across runs matters more here than brevity. Original recommendation: Consider dropping the Money, Personal data and Auth bullets and keeping the critical one, retitled as the named-framework list that promotes a feature to critical. Weigh against consistency: an explicit vocabulary makes tier detection reproducible across runs, which matters when the tag drives a 3-5x review multiplier. The two distinctions below it — displaying personal data vs anonymized aggregates, and tagging for what the feature itself touches — are doing the real disambiguating work and should stay either way.

#### determinism-8 — The confirmation list was reported as counts, forcing a re-scan for the ids

- Lens: determinism
- Location: `scripts/inventory-check.py (coverage)`
- Evidence: coverage() returned review_tiers as per-tier counts and inferred_dependencies as a single integer, while already returning real ids for outside_agreed_scope. The model therefore re-read the inventory to enumerate the very items the script had just counted — and 'list all' is a signal verb.
- Recommendation: APPLIED. coverage() now returns sensitive_or_critical as a list of ids and inferred_dependency_pairs as {feature, depends_on} objects, matching the shape outside_agreed_scope already used. The batched confirmation table is built from those directly.
