# Cost Model Guide

`{project-root}/_bmad/memory/est/cost-model.json` is the company's own model. It is data, not logic: nothing in `est-estimate` hardcodes a coefficient, so changing a number there changes every future estimate and nothing else has to be touched. Every entry is a three-point value (`lo` / `likely` / `hi`) plus a `why` explaining what it encodes, because a coefficient nobody can interrogate is exactly what this module refuses to ship.

## What the model actually says

Read it once and the shape of a BMad estimate becomes obvious. Schema 3.0 rebuilt it against
three delivered projects, and the rebuild changed the *frame*, not just the numbers.

**`size_bands`** give the **delivered hours** for one story, across every role billed to story
work. They used to give a manual-equivalent baseline that build hours were divided out of — and
**neither of those quantities was ever recorded on any delivered project**, so the division was
arithmetic over a construct. These are measured: EPP's own per-story record weights all 75 stories
on a 1–5 scale and reconciles to 240 dev hours at **1.165 h per point**, re-checked independently
on a later slice at 1.173. `measured_dev_h` on each band is that raw figure; `likely` is it
grossed up by 1.32 to cover the other roles a story bills, which is the one fitted number in the
block.

**The spread is 4.8x, and everything about how the module behaves follows from it.** The 2.x bands
ran 1 h to 90 h, so one band of error moved a story 3.0x and a 12-point shift in an inventory's L
share moved the estimate 17%. On the measured bands the same shift moves it 2%. That is why the
sizing checks were re-tuned and demoted to informational in the same release: thresholds calibrated
to a 90x spread manufacture findings against a 4.8x one, and every one of those findings pushed the
classifier back toward the middle of the table.

Three sub-keys inside `size_bands` are documentation rather than arithmetic, and all are read by
`est-scope-extract` at the moment a band is chosen: each band's **`exemplars`** are worked examples
quoted from the delivered record; **`_anchor.distribution`** is the mix that project actually
delivered (XS 3% · S 17% · M 45% · L 31% · XL 4% — the 2.x file claimed 64% M with no XS and no XL,
and that claim was being enforced); and **`_anchor.surfaces_per_story`** is the granularity signal
`check_granularity` compares an inventory against. They live here rather than in the extractor's
guide so they move when the hours move. `inventory-check.py --bands` prints them; `apply.py` and
`backtest.py` skip `_`-prefixed keys and touch only `lo`/`likely`/`hi`. If you recalibrate the
bands, rewrite the exemplars in the same edit.

**`manual_effort_premium`** is additive hours for work whose cost is not the code — a payment rail,
an external IdP, a device build. Additive rather than a band, because a provider account is the
same console work behind a small story as a large one. Measured as the residual over what a story's
surface count predicts: money rail +0.75 points, external IdP +0.73, native/device +0.41, and a
story touching nothing external −0.07. That last row is the control. `provisioning` is deliberately
unpriced: all three anchors deferred real infrastructure, so it raises an open question instead of
inventing a number.

The catalogue is not the whole mechanism any more. **`standing_work` holds the items and their
hours; the inventory holds the selection.** An extraction at schema 1.1 writes `standing_scope`
saying which items this project pays and why, and which the client is bringing — so a pipeline
still costs the same on every estimate, while a project that is not paying for one stops being
billed for it. The reason it moved is measurable: all three delivered anchors priced repo
scaffold, CI and environment setup as ordinary stories *and* paid standing work on top, and
nothing could see the overlap because the two lists were produced in different skills.
`inventory-check.py` now reports it, and `covered_by` is where the answer is recorded. An item
the selection never mentions is still priced — the failure mode has to be paying twice, never
silently discounting.

**`compressibility`** is **reported only**. `manual_equivalent = delivered x compressibility` is the
client-facing "this would have cost X by hand" sentence, and no priced hour depends on it. If it is
wrong, only that sentence moves.

**`review_tier`** is a small multiplier on the story total, and this is the coefficient the rebuild
changed most. Measured: the anchor's sensitive stories average 1.05x its routine ones, and 1.06x
once every provider-touching story is excluded. The 2.x model priced the tier at 0.04 / 0.17 / 0.30
of a manual baseline — a 3.5x swing on the review component. Criticality is expensive in
consequences, not in hours; what is expensive is the provider behind the sensitive work, and that
is `manual_effort_premium`. `critical` at 1.25 is the exception and it is a **judgement** — none of
the three anchors carried an external compliance sign-off.

**`component_shares`** decide only where a story's hours are *reported*. They sum to 1, so moving one
can never change what a story costs. All three anchors recorded hours by role and never by phase, so
this decomposition is an explicit hypothesis — stated as numbers precisely so a future project can
falsify it.

**`architect`** is `setup + a capped weekly rate`, and it is the best-evidenced coefficient in the
file: all three projects fit it exactly (40 + 7x10 = 110; 30 + 3x10 = 60; 30 + 5x10 = 80), and the
formula was stated independently of the totals rather than fitted to them. In 2.x the architect had
no component at all — its hours fell out of role weights on planning and overhead, both of which
scale with story count, so a bigger backlog bought a bigger architect.

**`planning.split_factor`** is the one place a split story genuinely costs more: planning is priced
per artefact written, and two stories get two story files and two reviews. All three projects
delivered roughly 1.7x the story count they planned, at unchanged scope and unchanged hours — it is
decomposition, not scope growth, so it is applied to planning and nowhere else.

**`clarity`** drives specification and rework. Under BMad, ambiguity is no longer resolved by a
developer stopping to ask — it gets confidently implemented, reviewed, and rebuilt. Vagueness costs
*more* than it did in manual delivery, which inverts what most estimators assume. Unmeasured: the
ordering is the claim, not the level.

**`planning.review_hours`** carries the tightest bands in the file, and that is deliberate. This
company reads 100% of planning artefacts on every project, so it is reading at a known rate over a
known volume: the uncertainty is in the volume, not the rate.

**`uncertainty.completeness_multiplier`** is the mechanism that makes false precision impossible.
Band width is computed from the inventory's completeness score, so a two-paragraph brief *cannot*
produce a narrow range — the arithmetic forbids it rather than a rule discouraging it.

## How much to trust each block

The rebuild scored every coefficient against the evidence behind it, and the scores are as much a
part of the model as the numbers. Read them before you quote anything.

| Block | Confidence | Resting on | What would raise it |
| --- | --- | --- | --- |
| `architect` | **9/10** | Three projects, exact fit, formula stated independently of the totals | A fourth project with a different engagement shape |
| `size_bands` shape | **7/10** | One project's per-story record, re-validated on a second slice at 0.7% | The same weighting applied to an unseen project before its hours are known |
| `review_tier` (sensitive) | **7/10** | Measured across 75 stories, and again with provider stories excluded | The same measurement on a second project |
| `manual_effort_premium` money | **6/10** | n=4, consistent, corroborated by the epic retrospective | Tagging the same classes on the other two anchors |
| `planning.split_factor` | **6/10** | Three projects, 1.52x / 1.98x / 1.56x | Nothing much — it is small and well-bounded |
| `size_bands` gross-up | **5/10** | Fitted to one project's five staffed role totals | A second project that staffs all six roles |
| `qa` | **4/10** | n=1, and the other two anchors staffed no QA at all | One more project that actually books QA |
| `manual_effort_premium` IdP | **3/10** | n=1 | Two more SSO integrations |
| `compressibility` | **3/10** | One sentence in the anchor's own assessment; nobody measured a manual baseline | Estimating one project manually before it is built |
| `component_shares`, `clarity`, `team_profiles` | **2/10** | Nothing — the anchors record hours by role, never by phase | One project that time-tracks to build / specify / review / rework |
| `overhead_rate` | **2/10** | Nothing — no anchor separated ceremony from delivery | One time-tracking export that splits meetings from build |
| `standing_work` hours | **2/10** | Nothing, and worse: all three anchors *deferred* the work it prices, while pricing some of it again as ordinary stories | Actuals from one project that reached production |
| `standing_work` selection | **6/10** | Not a coefficient — a per-project decision with a stated reason on every line | Nothing; it is auditable by construction |

**The limit of the whole thing, stated once.** No unit available at presale normalises the three
projects to better than about 1.7x. Hours per delivered story spread 3.2x across them, per
acceptance criterion 3.7x, per complexity point 1.9x. The model is fitted to the most expensive of
the three, so it runs high against a finely-sliced inventory — `check_granularity` is what says so
out loud, and it is the number to read before any individual band.

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

Four lookups describe this company rather than software in general, and they drift: `team_profiles`, `qa`, `standing_work`, `overhead_rate`. Each carries its own `why` — read those before editing, since they are on screen in the file you are already in. Three of the four sit at 2–4/10 in the table above, which is not a reason to ignore them: it is a reason to write down what your own projects actually did.

The one worth adding here, because the data cannot say it: `overhead_rate` is a commercial choice as much as a delivery one. A high-touch client genuinely costs more to serve, and setting the rate low does not make the meetings shorter — it just means absorbing them.
