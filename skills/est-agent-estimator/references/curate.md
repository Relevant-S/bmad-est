# Changing the cost model

*Paths, so this file resolves on its own if SKILL.md is no longer in context: `{memory}` → `{project-root}/_bmad/memory/est/`, holding `cost-model.json`, `ledger/`, `calibration-log.md`, `comparables.md` and `company-profile.md`.*

The cost model is the company's accumulating asset and the one thing in this module that must never move without someone being able to reconstruct why. There are exactly two doors into it, both of which back up, log, and stay reversible from the log alone. **You never edit `cost-model.json` directly, and you never let anyone else do it either** — a hand edit has no backup, no provenance and no way back, and it silently breaks the snapshot chain that makes calibration possible.

## Which door

**Evidence — `est-calibrate`.** Projects have closed with real hours and the question is what those hours say. Invoke the skill; it analyses, backtests every proposal against delivered history, and applies only what a human accepts. This is the door that should be used most, and a change that comes through it carries proof that it improves past estimates.

**Judgement — est-calibrate's `scripts/curate.py`.** Somebody who has run twenty of these projects tells you the model is wrong about something, and there is no delivered history to test it against. That is a legitimate input, especially before the first project closes, and refusing it does not prevent the change — it sends someone to a text editor, which is strictly worse.

Route to the first door whenever it is available. Reach for the second when the evidence does not exist yet, and say plainly which one you used.

## Judgement changes

Preview first, always. It writes nothing and works unattended:

```
uv run {project-root}/skills/est-calibrate/scripts/curate.py \
  --cost-model {memory}/cost-model.json \
  --calibration-log {memory}/calibration-log.md \
  --ledger {memory}/ledger \
  --set qa.web=0.07/0.095/0.14 \
  --why "<the reasoning, in their words>" \
  --preview
```

The preview re-prices every recorded estimate through est-estimate's engine and reports what the change would do to numbers already sent to clients. **Read `impact` out loud before asking for approval.** Three fields decide whether this is a good idea:

- `sent_or_won_affected` — estimates already quoted that this re-prices. Someone needs to know.
- `against_actuals` — where real hours exist, whether the change moves estimates closer to what happened or further from it. A judgement change that moves the model away from measured reality is one where est-calibrate has better evidence than the opinion does, and the honest response is to say so.
- `warnings` — raised when the coefficient was last set by calibration. Replacing evidence with an opinion is allowed and should be a deliberate act, not a surprise.

Then apply with `--approved-by "<name and role>"` and without `--preview`. It refuses to run without a terminal, refuses without a reason, and refuses a value that would invert a three-point range or go negative — the two ways a hand-set coefficient collapses the band instead of failing loudly.

Every change lands in `calibration-log.md` marked `(judgement)` rather than calibrated, and in the coefficient's own `why`, so a year from now nobody mistakes an informed opinion for measured evidence.

## What you can change freely

`{memory}/company-profile.md` is prose and carries no audit requirement — team shape, stacks, BMad adoption depth, QA capability, engagement model. Edit it when the user tells you something new about how the company works. `est-estimate` reads it for its default profile inputs, so a correction here improves every future estimate without touching a coefficient.

`{memory}/comparables.md` grows as projects close and is the anchoring corpus. `est-calibrate` writes to it; you can add an anchor a user gives you, with its source.

## The company profile interview

Run this the first time `{memory}/company-profile.md` is missing. Generic coefficients priced against the wrong team shape are the fastest way to lose credibility on the first number.

`est-setup` seeds it from `{skill-root}/assets/company-profile.seed.md` with every section marked **UNANSWERED** and the coefficient each one selects printed beside it. **Fill that file in; do not invent a structure.** The sections are the four inputs `est-estimate` would otherwise default, and a profile shaped differently each time is one nobody can scan to see what is still missing. Delete each `UNANSWERED` marker as it is answered — that marker, not the file's absence, is what says the work is outstanding.

Interview conversationally and write prose a person can edit. Two things read the file: `est-estimate` takes its default profile inputs from it, and `est-calibrate` reads it to judge whether a team's learning-curve modifier has served its purpose.

Then ask by name about the three nobody volunteers:

- **Is the mobile MCP server doing the QA testing?** It materially changes mobile estimates and the industry default overstates them badly.
- **Which teams are still new to BMad?** The modifier is real and it is meant to decay, so record which teams are inside it rather than applying it everywhere forever.
- **Confirm the Architect absorbs PM responsibilities during planning.** The absence of a PM from the role split is deliberate, not an omission.

## Two maintenance jobs worth raising unprompted

**`uncertainty.model_risk` is seeded at 0.15 while the model is uncalibrated.** It is a deliberate admission that the coefficients are untested, and it widens every band. Once backtesting shows how far estimates actually land from actuals, it should come down — but through `est-calibrate`, on evidence, not through judgement.

**The `new-to-bmad` team modifier is meant to decay.** It inflates spec, review and rework by design while a team is learning. When a team's delivered projects stop showing the penalty, propose retiring it for that team rather than leaving it quietly inflating every estimate they touch.
