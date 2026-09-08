---
name: est-scope-extract
description: Extracts traceable feature scope from project documents. Use when user says "extract scope", "build a feature inventory", "what's in this RFP", or "scope this SOW". Supports headless (-H) for batch runs.
---

# est-scope-extract

## Overview

This skill turns any project input — call transcript, PRD, SOW, RFP, backlog workbook, in any format or language — into a **Feature Inventory** in which every line traces back to the source text that produced it. Read as a delivery lead reading a client document for what is actually in it, not as a summarizer. The output is `feature-inventory.json` plus rendered views, consumed by `est-estimate`.

**It records what the source says. It decides nothing about cost.** Size band, compressibility, review tier, clarity and novelty are the coefficients a cost model prices on, and they belong to `est-estimate`, which writes them to `classification.json` beside this inventory. An extraction skill that also assigned them was deciding what work costs while claiming only to be reading a document — and a re-extraction could then silently revert a judgement a human had corrected. What stays here is what the source committed to (`commitment`, `scope_status`) and which kinds of work a story touches (`surfaces`): observations, not judgements.

`module-code: est`

## Resolution rules

- Bare paths and `{skill-root}` (e.g. `references/story-synthesis.md`) resolve from this skill's installed directory.
- `{project-root}` → the project working directory.
- `{output_folder}` → `core.output_folder` via `uv run {project-root}/_bmad/scripts/resolve_config.py -p {project-root}`, defaulting to `{project-root}/_bmad-output`. Config is TOML here, so reading `config.yaml` finds nothing and defaults silently.
- `{project-slug}` → kebab-case of the project or deal name the user gives.

## The bar

Two consumers set it. `est-estimate` needs every field its cost model reads, correctly typed. The human who must defend the resulting number needs to open this inventory beside the client's own document and verify it line by line — including a reviewer who reads the source's language and not yours.

**The non-negotiable is two-way traceability.** Every feature carries at least one citation with a verbatim quote. Every substantive passage that did *not* become a feature appears in `not_scope` with a reason. Silent invention and silent omission are the two failures that make people stop trusting the whole module, and they are invisible in a well-formatted output — which is why nothing here rests on your own reading being right. `inventory-check.py` re-opens the sources and verifies the claims mechanically.

## Intents

Read the user's intent and route. Ask the single disambiguating question only when it is genuinely unclear.

| Intent | When | Where |
| --- | --- | --- |
| **create** | Fresh sources, no existing inventory | Below |
| **update** | New or revised sources against an existing inventory — the scope-creep case | `references/update-and-validate.md` |
| **validate** | Read-only recheck of an inventory against its sources before it feeds an estimate | `references/update-and-validate.md` |
| **resume** | A workspace holding a memlog and a partial inventory — a create run that was interrupted | Read `.memlog.md` once, then continue in Create from the last beat it records |

Decide between them by looking, not by asking: once the project is named, check `{output_folder}/estimates/{project-slug}/`. A complete inventory means update, a partial one means resume, nothing there means create.

**Headless** — no TTY, a programmatic caller, `-H`/`--headless`, or every input supplied up front — changes what happens at each point that would otherwise ask a human. Load `references/headless.md` and follow it for the whole run.

## Create

**Settle three things first**, in two sentences, before converting anything: the project name, what the estimate is *for* (`granularity`: a whole project, an epic, a sprint, or a single feature), and **which source is contractual, if any**. That last one switches on the agreed-scope machinery, and discovering it accidentally mid-extraction is how it ends up applied inconsistently.

**Then open the workspace** at `{output_folder}/estimates/{project-slug}/`, which holds `feature-inventory.json` (source of truth), the rendered `.md` and `.csv`, `extraction-report.md`, `normalized/` (converted sources plus `manifest.json`), and `.memlog.md` — init that with `uv run {project-root}/_bmad/scripts/memlog.py init --path <workspace>/.memlog.md`. State lives on disk from here on, so the user has the path and nothing depends on the conversation surviving.

**Then plan the beats.** `uv run scripts/plan-beats.py <workspace>/normalized --manifest <workspace>/normalized/manifest.json -o <workspace>/beats.json` cuts each source into the units the reading fans out over. It cuts on the source's own structure — the sparse-filled grouping column, a catalogue tab kept whole, heading sections in prose — so every beat is a contiguous row range and a citation written inside one anchors exactly as it would have in a single pass. A partition chosen fresh each run is a partition nobody can reproduce, resume or check.

**Convert, then read.** `uv run scripts/convert-input.py <paths> --out-dir <workspace>/normalized -o <workspace>/normalized/manifest.json` (`--help` for the interface). It emits the anchors your citations point at — page markers, `## sheet:` blocks with real row numbers, headings — so read the normalized files, not the originals. Any source marked `needs_native_read` (a scanned PDF, an unsupported format) you read directly, recording how in its `coverage_note`; one you cannot read at all is recorded as unread, never quietly dropped. Without `uv`, the other three scripts are stdlib-only and run under `python3`; without the conversion libraries, every source falls to the `needs_native_read` path and you read them all directly — slower, and correct.

**Extract, one subagent per beat.** Fan them out, each given its beat's row range, its `header_row` and the type of document it belongs to — and nothing else — returning ONLY `{"beat_id", "features": [...], "not_scope": [...], "open_questions": [...]}`. **If a beat writes to disk rather than returning, the path is `<workspace>/extract/<beat_id>.json` and nothing else** — invented names accumulate as undeclared workspace nobody can tell apart from a partial run. Without subagents, work the beats in order and say in the report which way it ran. Beats must not touch `.memlog.md`: `memlog.py append` is a read-modify-write over one shared temp file, so two concurrent appends lose an entry or corrupt the render. Write the beats yourself after fan-in.

The reading itself is the same reading whoever does it. Identify what each document is (`references/source-type-playbook.md` — a transcript, an RFP and a backlog workbook each hide scope differently, and reading a transcript like a spec is the most common way to over-commit a client). Pull out the discrete claims the source makes, and cite each against the anchors the conversion gave you. Record what a passage was, if it was not scope.

**Then group them into stories.** `references/story-synthesis.md` — this is the step that decides whether the estimate is worth reading, and skipping it is how a 754-row workbook became 754 priced features averaging 1.6 hours each. A spreadsheet row is an acceptance criterion; the estimable unit is the story it belongs to. Rows survive as that story's `tasks`, with their citations, so the inventory can still be read line by line against the client's own document.

**Tag `surfaces` and capture dependencies.** `surfaces` — which of `backend`, `frontend`, `design`, `infra`, `data` a story actually touches — is an observation about the scope, and it decides which roles are billed to a story rather than how many hours it takes. `references/story-synthesis.md` has the rule; omitting it is not a way to say "none", because an untagged story keeps every role. Capture dependencies while the source is still in front of you, because the sentence that implies one ("once login is in place, users can…") is gone by the time the estimate runs.

The five cost axes are not yours to set. If a beat comes back carrying a `size_band`, drop it and say so in the report — a band judged against one slice of a workbook, with no reference class and no sight of the rest of the project, is exactly the guess this split exists to prevent.

**Add what the source will never say.** Work every project pays — repo scaffold, pipeline, environments, release process — is not yours to invent: it comes from the cost model's `standing_work` catalogue and `est-estimate` adds it. What *is* yours is project-specific work the source implies but never states: the migration behind "we have ten years of bookings", the backfill behind a reporting requirement. Those go in `implicit_scope`, each with a `rationale` naming what implies it. They have no citation by design, which is why the rationale is mandatory — work with neither a quote nor a reason is invented scope.

**Account for coverage.** Confirm every substantive passage produced either a feature or a `not_scope` entry. Set the `completeness_signals`, each with the one-line reason that decided it — they set the width of the whole estimate, so they are held to the same standard as a tag. Write the JSON against `assets/feature-inventory.schema.json`.

**Check.** `uv run scripts/inventory-check.py <workspace>/feature-inventory.json --normalized <workspace>/normalized --manifest <workspace>/normalized/manifest.json` verifies every quote against the document it cites, resolves structured locations against anchors the file really has, reconciles converted sources against `sources`, and checks the schema, references and dependency graph. Its `unreferenced_regions` is the coverage pass done by search rather than memory. Fix every finding, judge each unreferenced region for substance, re-run until clean. It returns `input_completeness: null` here by design — clarity is 18% of that score and is classified in `est-estimate`, which runs this same script again with `--classification` to complete it.

**Review before finalizing.** Fan out one subagent per normalized source, each given that source's path and only the features and `not_scope` entries citing it, returning ONLY `{"invented": [{feature_id, why}], "omitted": [{location, quote, why}]}`. They answer what no script can: does the feature actually *follow* from its quote. Without subagents, do the same checks yourself one source at a time and say in the report which way it ran. **If a reviewer writes its findings to a file rather than returning them, the path is `<workspace>/review/<source_id>.json` and nothing else** — invented names accumulate as megabytes of undeclared workspace that nobody can tell apart from a partial run.

**Then check the workspace holds what it should.** `uv run {skill-root}/../est-setup/scripts/check-outputs.py --skill est-scope-extract --workspace <workspace>`. It names any file the module does not declare, which is how a leftover from an interrupted run gets caught before someone reads it as current.

**Then render and report.** `uv run scripts/render-inventory.py <workspace>/feature-inventory.json` for the `.md` and `.csv`. Write `extraction-report.md` from the check output: the completeness score and what drove it, what the sources failed to say, open questions ranked by how much they matter, conflicts between sources, and anything unread. This report tells a presale lead whether to estimate now or go back to the client first.

**Confirm as one batch, not a queue.** Everything needing a human — inferred dependencies, every `outside_agreed_scope` call, every conflict between sources — goes into one table the operator can accept wholesale or correct selectively. A long RFP generates dozens; asking one at a time produces rubber-stamping exactly where accuracy matters most. When a human corrects a call, record it:

```
uv run {project-root}/_bmad/scripts/memlog.py append --path <workspace>/.memlog.md \
  --type decision --text "<what changed, from what, to what, the operator's reason>"
```

If that script is unavailable, append the same typed line to `.memlog.md` directly and note that it was written by hand.

## Gotchas

- **Never write the completeness score yourself.** You set `completeness_signals`; `inventory-check.py` computes the score under fixed, published weights (`--weights`). The weights are not negotiable per run, so nobody can tune a thin input into looking certain — but the signals are still your judgement, which is why each carries a `why`.
- **A re-extraction must not orphan a judgement.** It can no longer revert one — classification lives in its own file — but renumbering a story leaves its judgement keyed to an id that is gone. `inventory-diff.py --merge` keeps the old ids on matched features, and `est-estimate/scripts/classification-merge.py` re-keys whatever still moved. Losing a human's classification correction is still the failure that makes people stop trusting the tool.
- **Where a contract is present, it defines the agreed scope.** A feature the other sources raise but the contract does not cover is `scope_status: outside_agreed_scope` — priced, but as an addition, never folded into the agreed number. Ask the operator before tagging one; it is a commercial call, not an extraction call. `references/source-type-playbook.md` has the full rule, `references/headless.md` the unattended default.
- **A feature with no citation is invented scope.** If you believe something is needed but the source never says so, it is an `assumption`, not a feature — or a feature with `commitment: implied` and a citation for what implies it.
- **Preserve the original-language quote.** When a source is not in the working language, `quote` carries your translation and `quote_original` the untranslated text. Traceability a native reader cannot verify is not traceability.
- **Do not resolve disagreements between sources.** When the SOW and the call contradict each other, both go in `conflicts`. Picking one silently decides a commercial question that is not yours.
- **Speculation is not scope.** "They mentioned wanting notifications eventually" is `commitment: speculative`. Including it as committed inflates the estimate; dropping it loses a real signal.
- **The source's own scope columns are decisions already taken.** A backlog with `Status: REMOVE`, a `Priority`, a `Client Phase` or a "deprioritisation candidate" column has had a human make calls in it. Honour them — a removed row is `not_scope`, a phase is carried onto the story — rather than extracting every row and raising an open question that changes no number.
- **A change-log tab is not scope.** A sheet whose rows say `REPLACE row 300` or `INSERT` is a set of edits to another sheet. Apply it and say you did. Extracting it alongside the sheet it edits counts the same work twice.
