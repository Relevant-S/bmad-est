---
name: est-setup
description: Installs and configures the BMad Delivery Estimator. Use when the user says "install the estimator", "set up est", "configure the delivery estimator", or before the first estimate in a new project.
---

# est-setup

## Overview

Registers the Delivery Estimator into a project: writes its settings, scaffolds the module memory the four skills share, seeds the cost model, and checks the document converters. Run it again any time to reconfigure — it is idempotent.

`module-code: est`

## Resolution rules

- Bare paths (e.g. `assets/module.yaml`) resolve from this skill's installed directory.
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
uv run scripts/merge-config.py --module-yaml assets/module.yaml --answers <temp.json> \
  --custom-config {project-root}/_bmad/custom/config.toml \
  --custom-user-config {project-root}/_bmad/custom/config.user.toml
```

It replaces any previous `[modules.est]` table rather than merging over it, so a setting removed from `module.yaml` cannot survive as a zombie, and it re-parses the file afterwards — a config that was written but no longer parses is worse than one never written. Read `verified` in its output before telling anyone it worked.

**Register the capabilities.**

```
uv run scripts/merge-help-csv.py --target {project-root}/_bmad/_config/bmad-help.csv \
  --source assets/module-help.csv
```

That catalog is what `bmad-help` reads. **Never pass `--legacy-dir` here** — it would delete `_bmad/core/module-help.csv`, which belongs to another module.

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
  "converters_missing": ["markitdown"],
  "needs_attention": [
    "company-profile.md not written — estimates will use default team assumptions",
    "cost model is UNCALIBRATED"
  ]
}
```

`needs_attention` is the load-bearing field: an unattended install that quietly leaves a project estimating against industry averages is worse than one that failed.

## Scaffold the module memory

The four skills share one memory at `{memory}`, and three of them expect it to exist. Create `{memory}/ledger/` and the configured `est_output_folder`.

**Seed the cost model** by copying `{project-root}/skills/est-estimate/assets/cost-model.seed.json` to `{memory}/cost-model.json` — **only if it is not already there.** That file becomes the company's own model the moment it exists: `est-calibrate` writes to it under an audit trail, and overwriting it with the seed would discard every calibration and every logged judgement change. If it exists, leave it and say so.

Then create the files the module appends to, if absent: an empty `{memory}/comparables.md` (with a one-line heading saying what it is) and `{memory}/calibration-log.md`. `est-estimate` also seeds the cost model on its own first run, so a missed seed here is recoverable — an overwritten one is not.

## Check the document converters

`est-scope-extract` reads whatever the client sent. Without these it still works, falling back to reading each source natively, which is slower and loses spreadsheet row anchors. Check what is present and install what is missing:

| Tool | Covers | Install |
| --- | --- | --- |
| `markitdown` | docx, pptx, html, pdf — the primary converter | `uv pip install markitdown` |
| `openpyxl` | per-tab xlsx with real row numbers | `uv pip install openpyxl` |
| `python-docx` | docx fallback with better structure | `uv pip install python-docx` |
| `pypdf` | PDF text and tables | `uv pip install pypdf` |
| `pdftotext` (poppler) | PDF fallback | system package |

Report what is available rather than failing — a missing converter degrades the extraction, it does not break it. `uv run {project-root}/skills/est-scope-extract/scripts/convert-input.py --help` names what each path needs.

## Then hand over

Show what was written: the settings and where, the help entries registered, whether the cost model was seeded or left alone, and which converters are missing. Display `module_greeting` from `assets/module.yaml`.

Two things this setup cannot do, and both matter more than any setting here:

- **The company profile is not written yet.** `{memory}/company-profile.md` is what stops estimates being priced against industry averages instead of this company's teams. Nadia (`est-agent-estimator`) runs the interview; it takes five minutes and every estimate afterwards rests on it.
- **The cost model is UNCALIBRATED.** The shape of an estimate is defensible today; the absolute hours are a reasoned hypothesis until `est-calibrate` has reconciled them against delivered actuals. Say that plainly, because it is the one thing a client-facing number should never quietly assume away.
