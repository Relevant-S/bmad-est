---
name: est-setup
description: Installs and configures the BMad Delivery Estimator. Use when the user says "install the estimator", "set up est", "configure the delivery estimator", or before the first estimate in a new project.
---

# est-setup

## Overview

Registers the Delivery Estimator into a project: writes its settings, scaffolds the module memory the four skills share, seeds the cost model, and checks the document converters. Run it again any time to reconfigure — it is idempotent.

`module-code: est`

## Resolution rules

- Bare paths (e.g. `assets/module.yaml`) resolve from this skill's installed directory — but a **shell command** resolves against the working directory, not this one, so every invocation below spells it `{skill-root}/…` and you replace it with the real path. An agent sitting at the project root that runs `uv run scripts/merge-config.py` gets `No such file or directory`.
- `{skill-root}` → this skill's installed directory. Its siblings are `{skill-root}/../est-estimate`, `../est-scope-extract` and so on, which is how they find each other in an install as well as in this repo.
- `{project-root}` → the project working directory. **In config *values* it stays a literal token**, because the consuming skill resolves it. In the *path arguments* below it must be replaced with the real project root, or the scripts write into a directory literally named `{project-root}` — they refuse the unresolved token rather than doing that quietly.
- `{memory}` → `{project-root}/_bmad/memory/est/`.

## What this writes, and where

This installation stores config as **TOML in four layers**, merged by `{project-root}/_bmad/scripts/resolve_config.py`: `config.toml` → `config.user.toml` → `custom/config.toml` → `custom/config.user.toml`.

Settings go to **`custom/config.toml`**, not the base layer. The base file's own header says it is regenerated on every install and must be treated as read-only; the custom layer is the one the installer never touches, so what is written here survives a reinstall. It is committed, so a team estimates on shared defaults — which is what makes two people's numbers comparable.

**Do not run the stock BMad `cleanup-legacy.py` against this project.** Its documented invocation removes `_bmad/core/` and `_bmad/_config/` — the second of which holds `bmad-help.csv`, the catalog this setup registers into. There is nothing legacy here to migrate, and that script is deliberately not shipped in this skill.

## Setting up

**Read `assets/module.yaml`** for the module metadata and the ten settings, each with its prompt and default.

**Check whether this is an update.** Resolve the current config (`uv run {project-root}/_bmad/scripts/resolve_config.py -p {project-root}`) and look for a `modules.est` section. If it is there, say so and offer the existing values as the defaults — a reconfiguration should not silently reset someone's choices.

**Ask for the settings as one batch**, showing defaults in brackets, so the user can reply with only what they want to change. Never tell them to press enter or leave blank; in a chat they have to type something. Two are worth a sentence rather than a bare prompt:

- **`est_default_team_profile`** sets what an estimate assumes when nobody knows who will do the work — the normal case at presale. It moves specification, review and rework, not build.
- **`est_min_calibration_samples`** is how many delivered projects it takes before `est-calibrate` treats a pattern as more than a weak signal. Lower is not braver, it is noisier.

**Write them.** Put the answers in a temp JSON as `{"module": {...}}`, keeping the literal `{project-root}` token inside values, then:

```
uv run {skill-root}/scripts/merge-config.py --module-yaml {skill-root}/assets/module.yaml --answers <temp.json> \
  --custom-config {project-root}/_bmad/custom/config.toml \
  --custom-user-config {project-root}/_bmad/custom/config.user.toml
```

It replaces any previous `[modules.est]` table rather than merging over it, so a setting removed from `module.yaml` cannot survive as a zombie, and it re-parses the file afterwards — a config that was written but no longer parses is worse than one never written. Read `verified` in its output before telling anyone it worked.

**Register the capabilities.**

```
uv run {skill-root}/scripts/merge-help-csv.py --target {project-root}/_bmad/_config/bmad-help.csv \
  --source {skill-root}/assets/module-help.csv
```

That catalog is what `bmad-help` reads. **Never pass `--legacy-dir` here** — it would delete `_bmad/core/module-help.csv`, which belongs to another module.

Read `unresolved_skills` in its output. A catalogue row is a promise that the thing it names can be run, and the script checks each one against this module's own directory and `.claude/skills/`. Anything listed there is registered but unreachable — pass `--skills-dir` if the install put them somewhere else, and report it either way rather than leaving a menu entry that goes nowhere. The BMad installer keeps its own `_bmad/_config/skill-manifest.csv` assuming skills live at `_bmad/<module>/<skill>/`, which is not where a plugin install puts them; that file is the installer's and nothing in this module reads it, so say where the skills actually are and leave it alone.

## Headless

`-H`, no TTY, or every value supplied in the invocation: take the defaults for anything not given, skip the prompts, and still do everything else — write the config, register the capabilities, scaffold the memory, seed the model, check the converters.

Two things change. **Never overwrite an existing `{memory}/cost-model.json`**, which is the same rule as interactive but matters more when nobody is watching. And return this and nothing else:

```json
{
  "status": "complete",
  "module": "est",
  "config": "{project-root}/_bmad/custom/config.toml",
  "settings_written": 10,
  "help_entries": 11,
  "cost_model": "seeded | already present",
  "converters_missing": ["pdftotext"],
  "needs_attention": [
    "company-profile.md seeded but every section still UNANSWERED — estimates will default the team profile, stack, QA platform and engagement model",
    "cost model calibrated against 1 delivered project (n=1) — read calibration_history, never assume"
  ]
}
```

`needs_attention` is the load-bearing field: an unattended install that quietly leaves a project estimating against industry averages is worse than one that failed.

## Scaffold the module memory

The four skills share one memory at `{memory}`, and three of them expect it to exist. Create `{memory}/ledger/` and the configured `est_output_folder`.

Scaffold `{est_output_folder}` while you are here — it is `modules.est.est_output_folder`, which every est skill now resolves as the root of its per-project workspace. It defaults to `{output_folder}/estimates`, so with the defaults it is the same directory either way; the point is that when someone changes it, the skills follow rather than writing to a path setup never created.

**Seed the cost model** by copying `{skill-root}/../est-estimate/assets/cost-model.seed.json` to `{memory}/cost-model.json` — **only if it is not already there.** That file becomes the company's own model the moment it exists: `est-calibrate` writes to it under an audit trail, and overwriting it with the seed would discard every calibration and every logged judgement change. If it exists, leave it and say so.

**Seed the company profile** the same way: copy `{skill-root}/../est-agent-estimator/assets/company-profile.seed.md` to `{memory}/company-profile.md`, **only if it is not already there.** The four inputs it settles — team profile, BMad adoption depth, stack, QA capability, engagement model — are the ones `est-estimate` otherwise defaults silently, and a blank file nobody knew to write is why they stayed defaulted. Seeded, the questions are on the page with what each one costs beside it.

It arrives with every section marked **UNANSWERED**, and that marker is the state, not the file's absence: a seeded profile is not a written one. Report it as still needing the interview, and say which sections are unanswered rather than that the file is missing.

Then create the files the module appends to, if absent: an empty `{memory}/comparables.md` (with a one-line heading saying what it is) and `{memory}/calibration-log.md`. `est-estimate` also seeds the cost model on its own first run, so a missed seed here is recoverable — an overwritten one is not.

## Check the document converters

**There is almost nothing to install.** `convert-input.py` declares its libraries in a PEP 723 block, so `uv run` fetches them on demand — the operator does not provision them and `uv pip install` would need an active virtualenv anyway. What it reads with:

| Format | Reader | Provisioned by |
| --- | --- | --- |
| xlsx, xlsm | `openpyxl` — per-tab, with the sheet's real row numbers | `uv run` |
| docx | `python-docx` | `uv run` |
| pptx | `python-pptx` | `uv run` |
| pdf | `pdftotext -layout` first, `pypdf` `extract_text()` after | **system package** (poppler) / `uv run` |
| csv, tsv, json, html, eml, md, txt | stdlib | nothing |

So the one thing worth checking is **`pdftotext`** — `shutil.which("pdftotext")`, a system package. Without it PDFs fall to `pypdf`, which loses the layout that makes a page citation locatable; without both, the source is marked `needs_native_read` and the agent reads the original directly.

`markitdown` is **not** used and must not be installed for this: it was dropped deliberately because it flattens away the sheet rows and page markers that citations anchor to, and a citation that cannot name a verifiable location is not traceability.

Report what is available rather than failing — a missing converter degrades the extraction, it does not break it. Every converter returns `needs_native_read` instead of raising, and the manifest lists what was missing.

## Then hand over

Show what was written: the settings and where, the help entries registered, whether the cost model was seeded or left alone, and which converters are missing. Display `module_greeting` from `assets/module.yaml`.

Two things this setup cannot do, and both matter more than any setting here:

- **The company profile is seeded but unanswered.** `{memory}/company-profile.md` now exists with each question on the page and the coefficient it selects beside it, but every section is still marked `UNANSWERED` — which means `est-estimate` will default the team profile, the stack, the QA platform and the engagement model. The sharpest of those: if mobile QA runs through the MCP server, the industry default overstates it threefold, so leaving it unanswered is wrong in the company's own disfavour. Nadia (`est-agent-estimator`) runs the interview; it takes five minutes, or the file can be edited directly.
- **Say what the cost model's calibration actually is — read it, do not assert it.** `{memory}/cost-model.json` carries `calibration_history`; a model with no entries, or only `kind: judgement` ones, is uncalibrated, and any other is calibrated against the largest `samples` count in it. The shipped seed is fitted to one delivered project, so the honest line is **n=1**: much stronger than industry averages, and still one project, which cannot separate what is true of BMad delivery from what was true of that project. Hard-coding either answer here is how a client gets told something the file contradicts — `est-estimate/scripts/estimate.py` decides it with `is_calibrated()` and `calibration_samples()`, and this must agree with them rather than reach its own verdict.
