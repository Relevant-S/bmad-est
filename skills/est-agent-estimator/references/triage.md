# Portfolio triage, bid/no-bid, and the company profile

*Paths, so this file resolves on its own if SKILL.md is no longer in context: `{memory}` → `{project-root}/_bmad/memory/est/`. `{estimates}` → `modules.est.est_output_folder` from the resolved config, defaulting to `{output_folder}/estimates`.*

## Reading the portfolio

`uv run scripts/portfolio.py --estimates {estimates} --ledger {memory}/ledger` returns every project's state in one pass. It orders by how much a wrong answer costs, not by importance — that judgement is yours.

`next_action` is derived strictly from what exists on disk, and two values deserve to be read out rather than summarised:

- **`re-estimate: scope changed`** — the inventory is newer than the estimate. Someone corrected the scope after the number went out, and the number that is being quoted is behind it. This is the scope-creep case the module exists to catch.
- **`capture actuals`** — a won or delivered project with no hours recorded. Every week that passes makes those hours harder to reconstruct, and they are the only thing that will ever calibrate the model. Chase the oldest first.

`skipped_folders` names any directory under `estimates/` that is not a project — a stray export, a half-made folder. It is reported rather than dropped, because a real project silently missing from a triage list is worse than a line of noise. Calibration runs live at `{output_folder}/calibration/`, deliberately outside this scan.

`attention` carries the signals that bear on priority — thin input, risk-quadrant share, outside-agreed-scope share, unverifiable traceability — each with its threshold stated. Lead with what needs a decision. The have/need table reads the same every month and prompts nobody.

## Closing the loop

Every activation you read out what the ledger is waiting for. Both of the things it waits for are yours to record, and neither takes more than one command — a chase list nobody can act on from inside the conversation is a list that gets read out forever.

**A deal moved.** `uv run {project-root}/skills/est-estimate/scripts/ledger.py --ledger {memory}/ledger --set-status <id> <draft|sent|won|lost|delivered>`. Status is a commercial fact, so take it from the person rather than inferring it from a date, and say which entry you are about to change before you change it. `won` and `lost` are the two that matter most: without them the module cannot tell a pipeline from a history.

**A project closed with real hours.** `uv run {project-root}/skills/est-calibrate/scripts/ingest-actuals.py --entry {memory}/ledger/<id>.json --from-export <time-export.csv> --scope as_estimated --source "<where it came from>"` — or `--total <hours>` when there is no export. Three answers decide whether the project can be compared at all, and all three are questions for a human, so ask them rather than defaulting:

- **`--scope`**, because an estimate for ten features against the actuals for seven delivered ones is not evidence, and averaging it in teaches the model something untrue.
- **`--exclude-hours` with its reason**, because time sheets are full of waiting on a client and paused months, and leaving that in makes the estimator look pessimistic and drives every coefficient the wrong way.
- **`--confidence`**, because a PM's recollection should not move a coefficient as hard as a time-tracking export does.

A single project total with those three fields is enough to calibrate band width and overall sizing. Say that when someone protests they do not have per-story tracking — the ask is small, and it is the only thing in this module that compounds.

## Bid / no-bid

The project's `portfolio.py` row already carries three of the four figures — `risk_quadrant_pct`, `band_width_pct` and `outside_agreed_scope_pct` — each computed against a stated threshold. Read them from there rather than summing hours out of `estimate.json`, which is arithmetic on an estimate and is exactly what this agent does not do. Four things make a deal dangerous, and they compound:

**Risk-quadrant share.** Low-compressibility work at sensitive or critical review tier is where BMad's advantage is smallest — the agent does not help much and a human reads every line. A deal dominated by that quadrant is a deal you would have priced similarly before BMad, so the competitive edge that justifies the bid is not there.

**Band width relative to the number.** A wide band is not a risk in itself; it is a statement about the input. It becomes a risk the moment someone proposes fixed price against it.

**Outside-agreed-scope share.** When a large slice of the estimate is work no contract covers, someone is about to quote a number for work that was never agreed. Say the two figures separately, always.

**Unresolved dependencies.** A long critical path means the sequencing carries the schedule; `estimate.json`'s `dependencies` gives its length and hours. Whether those links were *stated* by the client or *inferred* during extraction survives only in `feature-inventory.json` — the estimate flattens it away — so say which you checked, and do not claim confirmed sequencing you did not verify there.

State the read as a recommendation with its reasons, not a score. "I would bid this, and I would not fix the price" is a useful sentence; a risk rating out of ten is not.

## Batch triage

A folder of pending deals is the workflows' work, not yours. Run `est-scope-extract -H` then
`est-estimate -H` over each input folder — both carry a headless contract designed for exactly
this, and both return a `needs_confirmation` list naming what a human must look at. Then
`portfolio.py -o` for the ranked read across all of them.

What only you can do is the last step: read the pooled `needs_confirmation` entries and attention
signals back as a decision about where the next hour goes. Twenty unattended estimates are a pile
of JSON; the useful output is "these two need you today, and here is why".
