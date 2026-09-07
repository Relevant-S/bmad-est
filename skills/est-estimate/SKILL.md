---
name: est-estimate
description: Estimates delivery hours from a Feature Inventory. Use when user says "estimate this", "how long will this take", "price this scope", or "produce a presale estimate". Supports headless (-H) for batch runs.
---

# est-estimate

## Overview

This skill turns a Feature Inventory into a ranged, role-split estimate decomposed along the real BMad delivery phases. Act as a delivery lead pricing work you will have to defend to a client who did not write the document. The output is `estimate.json` plus rendered views, and a ledger entry that makes later calibration possible.

`module-code: est`

## Resolution rules

- Bare paths and `{skill-root}` (e.g. `references/cost-model-guide.md`) resolve from this skill's installed directory.
- `{project-root}` → the project working directory.
- `{output_folder}` → `core.output_folder` via `uv run {project-root}/_bmad/scripts/resolve_config.py -p {project-root}`, defaulting to `{project-root}/_bmad-output`. Config is TOML here, so reading `config.yaml` finds nothing and defaults silently.
- `{workspace}` → `{output_folder}/estimates/{project-slug}/`, the folder `est-scope-extract` already created for this project. The estimate is written **beside the inventory it prices**, so the scope, its sources and the number that came from them stay together.
- `{memory}` → `{project-root}/_bmad/memory/est/`, holding `cost-model.json` and `ledger/`.

## The bar

The number goes in front of a client who wants it to be smaller. Everything here exists so it survives that conversation: every hour traces to a feature, every feature to a quote in a source document, and every coefficient to a line in `cost-model.json` that a human can read and argue with.

**The range is a consequence of the input**, computed from the inventory's completeness score — so never present a tighter band than the arithmetic gives. And when review hours dwarf build hours on a sensitive feature, that is the model working, not a fault: `references/cost-model-guide.md` explains why, and is required reading before touching any coefficient.

## Input boundary

This skill consumes a **Feature Inventory only**. Given raw documents — a PDF, an RFP, a folder — do not extract scope yourself. Point at `est-scope-extract` and stop. That boundary exists because an unreviewed inventory produces a confident wrong number, and the extraction review is what catches invented scope.

## Modes

| Mode | For | Runs |
| --- | --- | --- |
| `quick` | A go/no-go in minutes: is this a 400-hour deal or a 4,000-hour one? | Totals, splits and risk quadrant. Skips dependencies, duration and sensitivity; renders `--formats md` only and records no ledger entry — a go/no-go is not an estimate anyone should later reconcile against |
| `presale` | The client-facing estimate. Use this unless told otherwise | Everything, all four projections, a `draft` ledger entry |
| `delivery` | Scope inside a running project | Everything, and the team you are fitting against is a required input rather than an option |

**Headless** — no TTY, a programmatic caller, `-H`, or every input supplied up front — follow `references/headless.md` for the whole run.

## Estimating

**First run only:** if `{memory}/cost-model.json` does not exist, copy `assets/cost-model.seed.json` there. That file is now the company's own model and the asset is only ever a seed — never edit the asset to change an estimate. `references/cost-model-guide.md` explains what each coefficient encodes and the rules for changing one.

**Validate before pricing.** Run est-scope-extract's checker over the inventory and keep its JSON:

```
uv run {project-root}/skills/est-scope-extract/scripts/inventory-check.py {workspace}/feature-inventory.json \
  --normalized {workspace}/normalized -o {workspace}/check.json
```

`estimate.py` refuses to price an inventory with unresolved findings, and takes the input completeness score from that report — pricing a broken inventory is how a confident wrong number gets made.

Reuse `{workspace}/check.json` if it is newer than the inventory; if the checker is not at that path, look for it under the project's skills directory; if it is genuinely absent, **stop and say so**. Never supply `--completeness` from your own judgement — the score is computed under fixed weights precisely so nobody can tune a thin input into looking certain. Without `uv`, all four scripts are stdlib-only and run under `python3`.

**Settle the four profile inputs**, because each moves the number and each is an assumption someone can challenge: the **team profile** (seniority, and whether they are new to BMad), the **stack**, the **QA platform** — use `mobile_mcp_automated` where the mobile MCP server does the testing, since the industry default would overstate it — and the **engagement model**. Defaults exist for all four; take them from `{memory}/company-profile.md` when it exists, and state whichever you assumed. In `delivery` mode also ask for the team's size and shape and pass `--team-size` — fitting scope to a team you have not named is guesswork wearing a number. Init `{workspace}/.memlog.md` if it is absent (`uv run {project-root}/_bmad/scripts/memlog.py init --path {workspace}/.memlog.md`) and append one `assumption` entry per input you had to default — six months on, nobody will remember whether a figure assumed a senior team or a junior one, and calibration will need to know.

**Compute.** `uv run scripts/estimate.py {workspace}/feature-inventory.json --cost-model {memory}/cost-model.json --check-report {workspace}/check.json --mode <mode> [--team-profile …] [--stack …] [--qa-platform …] [--engagement …] [--team-size N] -o {workspace}/estimate.json` (`--help` for the interface). It does all the arithmetic — never recompute or adjust any of it by hand.

**Read the output before rendering it.** Three things deserve your judgement rather than a pass-through:

- **`risk_quadrant`** — the features that are both low-compressibility and sensitive or critical. BMad's advantage is smallest there and that is where the number is most likely to be wrong.
- **`scope_split[…].share_of_total_pct`** — when `outside_agreed_scope` is a large share, say so plainly. Someone is about to quote a number for work the contract does not cover.
- **`narrowing_questions`** — ranked by how much band each removes. Each carries an `assumes` field naming the answer its figure is priced on; quote that alongside the hours, because a tier confirmed rather than downgraded narrows nothing. On a thin input this list is worth more than the number.

**Render and record.** `uv run scripts/render-estimate.py {workspace}/estimate.json` writes four things: the markdown, the CSV for sales, the interactive HTML where unticking a feature recomputes the whole estimate live — including the project overheads that shrink with it — and `estimate-brief.json`, the distillate `est-agent-estimator` loads to explain and defend a number, carrying each tag's reasoning and the client's own words behind it. Add `--show-manual-baseline` for internal output only. The report re-runs the aggregation in the browser so scope can be cut against a live number, which means two implementations of one model — verify them before anyone sees it: `uv run scripts/check-parity.py {workspace}/estimate.json`. A silent divergence there puts a different range on the client's screen from the one in the document. Then record it — **except in `quick` mode, which records nothing**. Show what will be written (id, project, range) and ask first; the ledger is the module's one durable record. `uv run scripts/ledger.py --ledger {memory}/ledger --record {workspace}/estimate.json --status draft`, always through the script, since the entry snapshots the cost model that produced the number. Re-estimating the same project the same day is normal after a client pushes back — pass `--revision` to keep both. A `draft` can be replaced deliberately; anything `sent`, `won` or `delivered` never is.

**Present the number with its band and its basis**, never bare. Lead with the range and name the completeness score that set its width.

## Gotchas

- **Never adjust the number directly.** If it looks wrong, either a feature is misclassified — fix it in the inventory and re-run `est-scope-extract` — or a coefficient is wrong, in which case read `references/cost-model-guide.md` first, then edit `{memory}/cost-model.json` and say what evidence changed. A hand-adjusted total destroys the traceability the whole estimate rests on, and calibration can never learn from it.
- **Build compression is not project compression.** The model reports how much faster BMad *builds*; planning, environments, QA and client overhead are costs a manual project pays too. Quoting an 8× build compression as though the project were 8× cheaper is the overclaim this module exists to prevent.
- **Agreed and additional scope are never merged into one figure.** And when a client asks what dropping the additions would save, quote `standalone_hours`, not `apportioned_hours` — they will not save the apportioned figure, because environments and most planning are paid once regardless.
- **The seed model is uncalibrated.** Until `est-calibrate` has reconciled it against real actuals, the shape of the estimate is defensible and the absolute figures are a hypothesis. Say that in client-facing output rather than letting it be assumed away.
- **Calendar duration is derived and secondary.** It depends on a team shape nobody knows at presale. Never lead with it and never state it without the assumptions that produced it.
