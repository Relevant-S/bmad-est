# Sourcing — build, adopt or buy

For each capability: written in the project, an existing open-source component, or a managed
third-party service.

**This is the layer with the strongest numbers in the workflow.** The other two score fit and
risk; this one converts into hours. Building identity is a set of stories with size bands.
Buying it is a smaller set of integration stories plus configuration. Both are nameable from the
inventory, so "adopting this saves roughly these stories" is a claim with story ids behind it.

## What the numbers actually rest on

Read this before quoting a saving to anyone:

- **The stories at stake are real.** Named ids, real size bands, real hours when an estimate
  exists.
- **The ratio applied to them is asserted.** `sourcing_effort` in the architecture model puts
  adopt at 0.5 and buy at 0.3 of building, with a `gap_penalty` of 0.25 added back per unmet
  requirement. No delivered project of this company's recorded what an adopted component cost
  against what building it would have. **Confidence 2/10 on the levels, 6/10 on the ordering.**
  Every basis string this module writes says `ASSERTED`, and so should you.

`est-calibrate` is how these become real: an adopted component that cost three times its
estimated integration is the first evidence this layer could ever have. Record the outcome in
`{memory}/architecture-preferences.md` when a project ships.

## Only live decisions are scored

A capability is **settled** — with a one-line reason — or **live**. Nobody builds a CDN; nobody
buys the domain rules that are the reason the project exists. Live requires credible candidates
in more than one mode *and* material work at stake (`sourcing_liveness`: at least two stories or
2% of the backlog). Forty-five scores nobody reads is the failure this prevents.

## Nothing unresearched is ever recommended

The delivery-effort sub-score structurally favours not building. An option with one score and
four blanks therefore outranked `build` on every capability nobody had looked at — the workflow
recommended buying things it had never examined. **Only a fully evaluated option can win**, and
`build` is fully evaluated by definition, so there is always a candidate. An unresearched mode
is still reported, with `needs_research` naming it: a gap in the evidence, not a verdict.

## Finding the balance

Both extremes are real, and each has a mechanism rather than a sentiment against it:

- **Build-everything** inflates the estimate and the calendar. Countered by the effort sub-score
  making avoided stories explicit, and by the rule that a mature candidate must be *scored
  against* rather than skipped.
- **Buy-everything** assembles eleven vendors, none quite fitting, with integration glue costing
  more than building would have. Countered by requirement-fit gaps feeding back into effort, by
  escape cost, and by Layer 3's sprawl term.

**No target ratio is hardcoded** — there is no evidence for one. The distribution is made
visible instead: *N built, M adopted, K bought; these stories avoided; this many vendors added*,
with a finding at the degenerate ends. A finding is not an error; it is a question the report has
to answer, which is the difference between a balance that was reasoned and one that just
happened. The balance counts **live decisions only** — nobody chose to buy a CDN, and counting
the settled defaults made every project read as 83% bought.

## The confirmation batch

**One table, every live capability, accepted wholesale or corrected selectively.** Not a queue:
asking one at a time produces rubber-stamping exactly where accuracy matters most, and a dozen
capabilities in sequence is a dozen chances to stop reading.

Layer 3 does not run until it is confirmed, because its input is the set of capabilities that
still need somewhere to run. Every operator change is a `.memlog.md` `decision` entry naming
what changed, from what, to what, and their reason.

## What a researched candidate must carry

```json
{"identity": {"buy": {
  "name": "the concrete product",
  "covers": ["F1", "F2"],          // story ids it serves natively
  "gaps": ["no per-tenant key rotation, which F42 requires"],
  "health": {"score": 9.0, "last_release": "2026-09", "contributors": 40},
  "licence": "MIT", "licence_blocked": false,   // adopt only
  "pricing_model": "per monthly active user",   // buy only; the FIGURE is fetched in costing
  "interface": "standard", "interface_why": "OIDC, so a migration re-issues tokens",
  "self_run": false}}}
```

A missing field scores `null` and says it was not researched. An **AGPL component in a
commercial SaaS** is `licence_blocked: true` — a gate, not a low score.
