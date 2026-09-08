---
name: est-calibrate
description: Turns delivered actuals into cost-model improvements. Use when user says "calibrate the estimator", "compare estimates to actuals", "how accurate are our estimates", or after a project closes. Supports headless report-only.
---

# est-calibrate

## Overview

This skill compares what projects were estimated at against what they actually cost, and proposes evidence-backed changes to the cost model. Act as an analyst who has to convince a sceptical delivery lead that a coefficient should move — the burden of proof is on the change. The outputs are an accuracy report, a batch of proposals with their backtests, and, only after a human accepts them, an updated model with an audit trail.

`module-code: est`

## Resolution rules

- Bare paths and `{skill-root}` (e.g. `references/reading-the-numbers.md`) resolve from this skill's installed directory.
- `{project-root}` → the project working directory.
- `{memory}` → `{project-root}/_bmad/memory/est/`, holding `cost-model.json`, `ledger/`, `calibration-log.md` and `comparables.md`.
- `{output_folder}` → `core.output_folder` via `uv run {project-root}/_bmad/scripts/resolve_config.py -p {project-root}`, defaulting to `{project-root}/_bmad-output`. Config is TOML here, so reading `config.yaml` finds nothing and defaults silently.
- `{workspace}` → `{output_folder}/calibration/{date}/`, holding `analysis.json`, `backtest.json`, the reports and `.memlog.md`. One folder per calibration run, because a run is a decision record and the previous one should still be readable. Deliberately outside `{output_folder}/estimates/`, which holds one folder per project: a calibration is portfolio-wide, and parking it there makes it read as a project that was never scoped.

## The bar

The cost model is the company's accumulating asset and this is the only skill that writes to it. **No silent drift:** every change is approved by a named human, carries its evidence and sample size, is backtested against delivered history, and is reversible from the log alone. A coefficient that moved for reasons nobody can reconstruct is worse than one that never moved.

The second bar is restraint. **Most runs should propose nothing** — report the accuracy figures, say the model is holding, and stop. A calibrator that finds something every time is fitting noise, and spends the trust the one genuinely important change will need.

## Modes

| Mode | When | Writes |
| --- | --- | --- |
| **readiness** | No ledger entry has usable actuals yet — the normal state until projects close | Nothing |
| **anchor** | No ledger at all, but one BMad project has been delivered | A ledger entry, then the model through the same gate |
| **calibrate** | Delivered projects with actuals exist. The default | The model, but only after a human accepts named proposals |
| **report-only** | An accuracy check without touching anything; the only headless mode | A report |

**Headless never writes to the cost model.** There is no conservative default for an approval gate, and `apply.py` enforces this itself rather than trusting the caller: it refuses to run without a terminal. See `references/headless.md`.

## Calibrating

**Check the module memory exists.** `{memory}/cost-model.json` is seeded by `est-estimate` on its first run; if it is absent, nothing has been estimated yet and there is nothing to calibrate — say so and point at `est-estimate` rather than reporting a file error. An absent or empty `{memory}/ledger/` is different and legitimate: that is readiness.

**Open the workspace and check for an unfinished run.** Create `{workspace}` and init its memlog (`uv run {project-root}/_bmad/scripts/memlog.py init --path {workspace}/.memlog.md`). If a recent calibration folder already holds an `analysis.json` with proposals nobody finished deciding, read its memlog once and offer to resume rather than re-deriving the batch.

**Attach actuals as projects close.** `uv run scripts/ingest-actuals.py --entry {memory}/ledger/<id>.json --from-export <time-export.csv> --scope as_estimated --source "<where it came from>"` — or `--total <hours>` when no export exists (`--help` for the interface). Three fields decide whether a project can be compared at all: `--scope`, because an estimate for ten features versus actuals for seven delivered ones is not evidence; `--exclude-hours` with its reason, because time sheets are full of waiting that is not delivery effort; and `--confidence`, because a PM's recollection should not move a coefficient as hard as a time-tracking export. `assets/actuals.schema.json` is the contract — what each field means, and what each granularity level unlocks — and the script validates against it before writing.

**Analyse.** `uv run scripts/analyze.py --ledger {memory}/ledger --cost-model {memory}/cost-model.json --project-root {project-root} -o {workspace}/analysis.json`. `--project-root` is what makes the operator's configured `est_min_calibration_samples` the threshold actually enforced; without it the script falls back to 3. With nothing comparable it returns readiness instead of failing — present that and stop. Otherwise read the accuracy figures before the proposals. **`references/reading-the-numbers.md` is required reading before you put any proposal to a human** — it works through what band hit rate, the debiased residual spread and the shrinkage weight mean, and which of them is telling you something.

**Backtest before showing anyone a proposal.** `uv run scripts/backtest.py --analysis {workspace}/analysis.json --ledger {memory}/ledger --cost-model {memory}/cost-model.json -o {workspace}/backtest.json` re-prices delivered history through est-estimate's own engine rather than reimplementing pricing.

**That engine is a hard dependency of the write path.** A proposal without a backtest is a different guess, not a calibration, and `apply.py` refuses it outright — there is no override. If `backtest.py` reports the engine missing, look for `estimate.py` under the project's skills directory and pass it with `--engine`. If `est-estimate` genuinely is not installed, report the accuracy figures, propose nothing, and say why — an unbacktested coefficient change is exactly what this skill exists to prevent.

**In `report-only`, stop here** — after the backtest, before the approval. Render the report and return the proposals as pending with their evidence attached. A scheduled run exists to tell someone a decision is waiting and show them the case for it; it just must not make the decision.

**Put the batch to a human.** One table: proposal id, coefficient, current → proposed, the evidence, sample size, and what the backtest did to past estimates. Say plainly which are weak signals. Where a proposal overshoots — the data points one way and the proposal moves only part of it — explain that the rest arrives as more projects land. Accept and reject individually; deferring everything is a legitimate answer and often the right one on a first run. **Log each decision as the human gives it** — `memlog.py append --path {workspace}/.memlog.md --type decision --text "<id, accepted/rejected/deferred, and why>"` — so a batch interrupted halfway is recoverable rather than re-derived.

**A coefficient set from expertise rather than evidence** — the normal case before the first project closes — uses `scripts/curate.py --preview` to show what it would do to recorded estimates, then the same command with `--approved-by` to apply it. `est-agent-estimator` routes here; it carries no model-writing code of its own, so this directory remains the only thing in the module that writes the cost model.

**Apply only what was accepted.** `uv run scripts/apply.py --analysis {workspace}/analysis.json --backtest {workspace}/backtest.json --cost-model {memory}/cost-model.json --calibration-log {memory}/calibration-log.md --accept P2 P4 --approved-by "<name and role>"`. It backs up the model, writes the provenance into each changed coefficient's own `why`, and appends a log entry naming every ledger entry the change came from.

**Then report and record.** `uv run scripts/render-report.py {workspace}/analysis.json --backtest {workspace}/backtest.json --out-dir {workspace}`. It also writes `accuracy-brief.json`, the small stable distillate `est-agent-estimator` loads to answer "how accurate are our estimates?" without parsing a report written for a person. Append the delivered projects to `{memory}/comparables.md` as anchors for future estimates — project, scope shape, estimate, actual — and log an `assumption` entry in the memlog for anything you had to infer. Finish with `uv run {skill-root}/../est-setup/scripts/check-outputs.py --skill est-calibrate --workspace {workspace}`.

## Anchoring on a single delivered project

The evidence path needs a ledger entry — an estimate priced under a recorded model, with
actuals attached — and a project delivered before this module existed has none. That used to
leave editing `cost-model.json` by hand, which writes no `calibration_history`, so the model
goes on announcing itself uncalibrated in every rendered estimate while its coefficients say
otherwise. The two disagreeing inside one document is worse than either being wrong.

One project is statistically weak and this mode says so at every step. It is still far better
than a seeded hypothesis, and it is what most companies have.

**Recover the shape.** `uv run scripts/anchor-project.py <project-dir> --epics 1-9 -o {workspace}/skeleton.json`
reads the project's own planning and implementation artefacts for its epics, its stories and
their status. `--status any` includes work still in review; the default counts only `done`.
Check the reported shape against what the team remembers shipping before going on — if the
story count is wrong, everything downstream divides real hours by a wrong denominator.

**Classify it yourself.** Every tag comes back `null`, and pricing refuses them. That is
deliberate: a script that guessed size bands would be manufacturing the evidence this run
exists to weigh. Read the story files — they are named in each feature's citation — and tag
against `est-scope-extract`'s classification guide, with a `why` per tag that points at the
story. Set `surfaces` from what each story actually touched.

**Price and record.** Run `est-estimate` over the classified skeleton, then record the ledger
entry. The entry snapshots the model that priced it, which is what makes the comparison
attributable later.

**Attach the real hours.** `uv run scripts/ingest-actuals.py --entry {memory}/ledger/<id>.json --total <hours> --scope as_estimated --source "<where the number came from>" --confidence <recalled|reconstructed|measured>`.
A per-role split belongs here too when it exists; it is the only thing that can calibrate the
role weights. Be honest in `--confidence`: a recollection must not move a coefficient as hard
as a time-tracking export, and the analysis weights it accordingly.

**Then run the normal path.** With one entry, `analyze.py` reports accuracy and proposes
nothing — the sample-size floor is doing its job, and `est_min_calibration_samples` is now the
number it enforces. Use `curate.py --preview` to see what a change would do to recorded
estimates, and `curate.py --approved-by` to apply it. That stamps `kind: judgement` and writes
the history entry, so the model's own account of itself stays true.

**Say n=1 in the log and in the model.** Put the sample size in the `--why` of every change.
The next person to read `calibration-log.md` needs to know the model is fitted to one project
before they trust a coefficient to three significant figures.

## Readiness — the mode that runs until projects close

With no comparable actuals, `analyze.py` returns readiness rather than failing, and an empty ledger is treated the same way: day one is a legitimate state, not an error.

Render it (`uv run scripts/render-report.py {workspace}/analysis.json --out-dir {workspace}`) and lead with the **chase list** — estimates that went out and never came back with hours, oldest first. That list is the actionable part; the have/need table below it reads the same every month and prompts nobody.

Say plainly what the next level of data would buy. A single `delivery_hours` total per closed project, with `scope_delivered` and `excluded_hours`, is enough to calibrate band width and overall sizing — that is the whole ask, and it is worth making it small. Per-feature hours are what unlock review tier and compressibility, the module's core IP, and nothing else gets there cheaply on a handful of projects.

## Gotchas

- **A weak signal is not a small change.** Below the sample threshold the honest output is "watch this", not a smaller adjustment in the same direction.
- **Never hand-edit the model to match a proposal.** Run `apply.py`, or the change loses its backup, its provenance and its reversibility. The one change `apply.py` cannot carry — a coefficient a delivery lead knows is wrong before any project has closed, so no backtest exists — goes through `scripts/curate.py` instead: same backup, same log, same TTY-only approval, but stamped `judgement` rather than calibrated, and it re-prices the whole ledger first so the effect on estimates already sent is visible before anyone accepts it. `apply.py`'s bar does not move; this is a second door, not a lower one.
- **Bias and band width are separate faults with separate fixes.** Consistent residuals on a systematically biased model look like an over-wide band, and narrowing it makes the model confidently biased. The analysis debiases before judging the band — do not re-derive spread from raw residuals yourself (`references/reading-the-numbers.md` works it through).
- **Retire the learning-curve modifier when it has served.** `new-to-bmad` is meant to decay: once a team's delivered projects stop showing the penalty, propose removing it for that team rather than leaving it inflating every estimate.
- **Scope-changed and unknown-scope projects are excluded, not averaged in.** They appear in the report's "not comparable" list with the reason. Chasing them into the sample is how the model learns something untrue.
