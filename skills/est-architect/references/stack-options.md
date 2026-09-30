# Stack options

Layer 1: language, frameworks, the libraries the scope actually needs, test and build tooling.

## Where options come from

**This module invents no candidate.** Stack options are researched and passed in via `--stacks`;
`architect.py` scores what it is given. A stack nobody researched cannot be scored, and a
sub-score with no evidence reports `null` rather than a default.

## Three options that differ structurally

Two options differing only in a library name are one option written twice. Each names the
`axis` it varies — *one language across client and server* against *split runtime per surface*
against *serverless-first* — and the report shows that axis beside the score, so a reader can
see what they are actually choosing between.

Fewer than three is honest when the scope genuinely admits fewer. Padding the list to look
thorough is the theatre this rule prevents.

## The shape of an option

```json
{"id": "ts", "name": "TypeScript end to end",
 "axis": "one language across client and server",
 "technologies": ["typescript", "node", "postgres"],
 "deployable_services": 1, "mobile": false,
 "libraries": {"identity": "the named library", "analytics_store": null},
 "currency": {"score": 9.0, "checked": "2026-09-29", "note": "current major, monthly releases"},
 "gaps": [{"stories": ["F7"], "why": "no mature native ML runtime"}]}
```

- `gaps` cost **scope fit** and name the stories that need an escape hatch.
- `libraries` with a `null` value cost **library coverage** and are named in the basis.
- `currency` **must carry `checked`**. An undated claim about a framework's state is not
  evidence, and scores `null`.
- `technologies` drives **team fit** against `{memory}/architecture-preferences.md`, and
  **estimate impact** through novelty.

## The two real couplings to est-estimate

Both were traced in the code rather than assumed, and neither is bigger than it is:

1. **`deployable_services` and `mobile` derive the `stack` profile.** `estimate.py` reads
   `spec["stacks"]` on each standing-work item and switches items on: `standard_saas`,
   `multi_service` or `mobile_plus_backend`. It is **not** a multiplier and must never be
   described as one. Three services means a pipeline and an environment set per service, and
   those items carry hours.
2. **An unfamiliar stack makes stories novel.** `novelty_rework_multiplier` is 1.15x on the
   story total and 1.6x on the rework share. A technology with no delivered project behind it in
   `architecture-preferences.md` is flagged, the estimate-impact sub-score is divided by that
   same coefficient, and the handoff carries it — so est-estimate prices the recommendation
   rather than assuming it was familiar.

## The gate calls out a reversal

If the winner shares less than half of its own languages and frameworks with a stack the
inventory records as decided, gate 1 says so and states the consequence: an estimate already
priced on the recorded stack is priced on a different design. `references/gates.md` has the rule
and the three ways it was wrong before it worked.

## Team fit reports `null` until somebody answers

`{memory}/architecture-preferences.md` ships with every section `UNANSWERED`. Until it is filled
in, team fit scores `null` and says why. A team-fit score of 5 invented from nothing reads
exactly like a team-fit score of 5 that was measured, and nobody argues with a number.

Filling it in is the highest-value thing an operator can do for this workflow: it is what turns
team fit, the house preference and the sourcing history from prose into scores.
