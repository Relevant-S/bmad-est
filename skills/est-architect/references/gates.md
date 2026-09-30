# The three gates

The brief this workflow was built to was *"propose several options, score each 0–10 with
reasoning, and wait for me to verify."* The first build honoured it for one layer of three. The
stack choice — which reversed a PRD's stated stack and invalidated an estimate already priced on
it — and a seven-vendor platform set were decided and reported rather than verified.

Each layer is now scored, presented and **stopped**.

| Gate | Continue with | Corrections come back as |
| --- | --- | --- |
| 1. Stack | `--stack-confirmed` | `inputs.stack_choice` |
| 2. Sourcing | `--sourcing-confirmed` | `inputs.sourcing_overrides`, `inputs.capability_overrides` |
| 3. Platform set | `--platform-confirmed` | re-run with a changed constraint or a pinned vendor |

`architect.py` exits **3** at the first unconfirmed gate and writes `gate-<layer>.md` beside the
output. Exit 3 is the normal outcome of the first three invocations; it is not an error.

## Why three and not one

Each layer constrains the next. The stack decides which open-source candidates exist and which
platforms can run the result; sourcing decides which capabilities need a home at all. Scoring
Layer 3 against a sourcing table that is about to change is work that gets thrown away, and — the
worse failure — presenting it invites the operator to ratify a set built on a premise they were
about to overturn.

## What a gate document has to contain

Every option, its `axis` (the structural thing it varies), its headline score, and **every
sub-score with the number it rests on**. A sub-score with no evidence renders `—`, never a
default. A non-viable option is still shown, with the constraint it broke, so the operator can
see what a constraint cost them.

## The stack gate calls out a reversal

If the recommendation shares less than half of its own languages and frameworks with a stack the
inventory records as **decided**, the gate says so above the table, quotes the record, and states
the consequence: *any estimate already priced on the recorded stack is priced on a different
design and should be re-run.*

Three things that rule got wrong before it worked, all found on one real backlog:

- **Datastores do not identify a stack.** Django-on-Postgres and Next.js-on-Postgres share a
  database and nothing else; comparing on the broad vocabulary let a complete reversal pass
  because both sides said "postgres". Only languages, frameworks and job runners decide it.
- **A conflict is not a decision.** A conflict record names *both* candidate stacks, so
  everything overlaps with everything. Only `assumptions` — decisions taken — are compared.
- **A decision mentions what it rejected.** One passing "Next.js" inside a paragraph choosing
  Django was enough to suppress the flag. Hence a majority threshold rather than any-overlap.

## A counter-proposal belongs to whoever made it

When the workflow disagrees with its own scoring, it records that in
`inputs.model_counter_proposals`. This **does not change the decision** — the scored answer
stands until a human changes it — and the gate presents it under *"Where the workflow disagrees
with its own scoring"*, labelled as the workflow's.

A run put two of its own proposals behind an option labelled `(Recommended)`, the operator ticked
it, and the log recorded them as operator corrections. Both facts were true and the record told
only one of them. `sourcing_overrides` is the operator's own channel and is recorded as
`source: operator`; the scored answer is kept beside it as `scored_mode`.

## Headless

Take the recommendation at every gate, proceed, and return all three flags **false**. An
unattended run may choose; it may not report a choice nobody made as though somebody had.
