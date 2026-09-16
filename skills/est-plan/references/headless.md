# Headless

Triggered by `-H`/`--headless`, by the absence of a TTY, or by a caller that supplied every input up front.

## What replaces each human gate

| Gate | Interactive | Headless |
| --- | --- | --- |
| Is a team already on this? | Ask | **No roster.** Never invent one — an unconstrained sweep is what a caller who supplied nothing asked for |
| Is there a target span? | Ask | None, unless `--deadline` was passed. In **weeks**; this module takes no dates |
| Which archetypes? | All three | All three, unless `--archetype` narrows it |
| Oversized roster | Raise immediately | Returned in `oversized_roster`, and the caller is responsible for surfacing it |
| No option feasible | Stop and explain | Exit **1** with `recommended: null`; do not present a plan |

## Return contract

```json
{
  "plan": "{workspace}/plan.json",
  "markdown": "{workspace}/plan.md",
  "workbook": "{workspace}/estimate.xlsx",
  "options": 9,
  "recommended": "pipelined-ba1-dev3-devops1-qa1-ux1",
  "refused": [{"role": "dev", "count": 4, "why": "..."}],
  "oversized_roster": []
}
```

## What headless must not do

- **Do not fall back to a default team.** A roster changes which options exist and which one wins; inventing one reports a choice nobody made.
- **Do not recommend an infeasible option** because it scored well. Feasibility is a gate, not a term in the score.
- **Do not render a workbook that is not there.** If `estimate.xlsx` is absent, report it — creating one would hand a client a second file with a Gantt and no scope in it.
