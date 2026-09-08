# Cost Model Guide

`{project-root}/_bmad/memory/est/cost-model.json` is the company's own model. It is data, not logic: nothing in `est-estimate` hardcodes a coefficient, so changing a number there changes every future estimate and nothing else has to be touched. Every entry is a three-point value (`lo` / `likely` / `hi`) plus a `why` explaining what it encodes, because a coefficient nobody can interrogate is exactly what this module refuses to ship.

## What the model actually says

Read it once and the shape of a BMad estimate becomes obvious.

**`size_bands`** give `manual_baseline` — what a **story** would have cost a human team writing it by hand. The unit matters: these described a feature until the module moved to pricing stories, and a band table one unit out prices every project about three times too high while every individual coefficient still reads as reasonable. Everything else derives from that, so it is the one place a wrong tag distorts the whole line item. It is deliberately *not* a BMad figure; conflating the two double-counts the compression.

Two sub-keys inside `size_bands` are documentation rather than arithmetic, and both are read by `est-scope-extract` at the moment a band is chosen: each band's **`exemplars`** (and, where the call is got wrong often, `not_exemplars`) are worked examples from delivered work, and **`_anchor`** records the band distribution and the manual baseline per story of the project the bands were fitted against. They live here rather than in the extractor's guide so they move when the hours move — a reference class that outlives its coefficients is worse than none. `inventory-check.py --bands` prints them; `apply.py` and `backtest.py` skip `_`-prefixed keys and touch only `lo`/`likely`/`hi`, so a `size_bands.*` scale leaves both alone. If you recalibrate the bands, rewrite the exemplars in the same edit.

**`compressibility`** divides `manual_baseline` to give build hours. It answers one question: how much of what this needs is already in the model's world? A Stripe integration is `high` because Stripe is thoroughly documented and thoroughly represented. The client's fifteen-year-old ERP over an undocumented SOAP endpoint is `low` — the same word "integration", an order of magnitude apart.

**`review_rate`** is the important one, and the easiest to get wrong when editing. It is a share of `manual_baseline`, **never of build hours**. Review effort tracks the volume of output produced, not the time taken to produce it, so compression shrinks the build and leaves the review where it was. That single choice is why a payments feature stays expensive while CRUD collapses, and it needs no special-casing anywhere — the behaviour falls out of the arithmetic. If someone "simplifies" this to a share of build hours, every sensitive feature is suddenly cheap and the model stops describing reality.

**`clarity`** drives specification and rework. Under BMad, ambiguity is no longer resolved by a developer stopping to ask — it gets confidently implemented, reviewed, and rebuilt. Vagueness costs *more* than it did in manual delivery, which inverts what most estimators assume.

**`planning.review_hours`** carries the tightest bands in the file, and that is deliberate. This company reads 100% of planning artefacts on every project, so it is reading at a known rate over a known volume: the uncertainty is in the volume, not the rate. It is the estimate's high-confidence anchor and the part of any number that can be defended hardest.

**`uncertainty.completeness_multiplier`** is the mechanism that makes false precision impossible. Band width is computed from the inventory's completeness score, so a two-paragraph brief *cannot* produce a narrow range — the arithmetic forbids it rather than a rule discouraging it.

## Changing a coefficient responsibly

Three questions before editing anything:

1. **Is this a coefficient problem or a classification problem?** A feature that looks mispriced is usually mistagged. Fix it in the Feature Inventory and re-run; changing the model to fix one feature silently distorts every other estimate that uses it.
2. **What evidence changed?** Write it into the `why`. "Raised sensitive review from 0.35 to 0.42 — three closed projects ran over on line-by-line review, see calibration-log" is a model that gets better. "Raised to 0.42" is a model nobody can audit or reverse.
3. **Would this change make a past estimate look different?** It will not — every estimate snapshots the whole model into its ledger entry, so history is never rewritten. But it does mean a coefficient change and an estimate delta are separately attributable, which is precisely what `est-calibrate` relies on.

The change that is never legitimate is editing a coefficient to make one number land where someone wants it. That is hand-adjusting the total with extra steps, and it corrupts the only asset the module is accumulating.

## The line between the model and calibration

While `calibration_status` still begins with `UNCALIBRATED`, every value is a reasoned starting point rather than a measurement. Say so in client-facing output. The *shape* of the estimate — which work compresses, where review dominates, which quadrant carries the risk — is defensible on its reasoning alone. The absolute hours are a hypothesis.

`est-calibrate` is what changes that: it reconciles ledger entries against real actuals, identifies systematic bias, proposes coefficient changes with their evidence and sample size, and applies only what a human approves. Until it has run, resist the temptation to hand-tune the model toward figures that "feel right" — an untested model with honest provenance is worth more than a tuned one whose adjustments nobody can reconstruct.

## Profiles worth keeping current

Four lookups describe this company rather than software in general, and they drift: `team_profiles`, `qa`, `env_infra`, `overhead_rate`. Each carries its own `why` — read those before editing, since they are on screen in the file you are already in.

The one worth adding here, because the data cannot say it: `overhead_rate` is a commercial choice as much as a delivery one. A high-touch client genuinely costs more to serve, and setting the rate low does not make the meetings shorter — it just means absorbing them.
