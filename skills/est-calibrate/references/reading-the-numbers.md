# Reading the Numbers

The analysis reports several statistics that look similar and mean different things. Getting them the wrong way round is how a calibrator talks someone into a change that makes the model worse.

## Band hit rate is the headline

How often the actual landed inside the range that was quoted. The module sells ranges, so this is the claim a client would test, and it is the one figure a bare project total can settle.

The target is 68%, because estimates are reported as mean ± one standard deviation. Read it in three bands:

- **Materially below 68%** — the ranges are too narrow. The estimator is promising precision it does not have, which is the failure that loses money on a fixed price.
- **Around 68%** — the ranges are honest. Say so; it is the most useful sentence in the report.
- **Far above 68%** — the ranges are wider than they need to be. Not dangerous, but a range that always contains the answer is not telling anyone much, and it invites a client to negotiate against the bottom of it.

## Bias and spread are different faults

Two projects can be equally "wrong" in opposite ways. Keep them apart.

**Bias** is direction: the median outcome against the central estimate. A consistent +23% means the sizing baseline is low, and the fix is the sizing scale.

**Spread** is consistency: how much the outcomes vary once the bias is removed. A wide spread means the model cannot tell projects apart, and the fix is band width.

They interact in a way that is easy to get backwards. A run of estimates all wrong by the same 25% produces *very consistent* residuals — the errors agree with each other. Measure spread on those raw residuals and the model looks over-confident in the wrong direction: the calibrator would narrow the band on a systematically biased model, making it confidently wrong. The analysis therefore removes the bias before measuring the spread, and reports both `residual_spread` and `residual_spread_debiased` so the difference is visible. Judge the band on the debiased figure.

## Shrinkage: why the proposal is smaller than the signal

Every proposal reports two numbers: `point_estimate`, which is what the data alone says, and `proposed`, which is what the calibrator actually suggests. The proposal is deliberately pulled toward the value already in the model, by a weight that grows with the sample size — half the way at six projects, four fifths at twenty-four.

This is not timidity. A model that lurches to a point estimate on one quarter's projects will lurch back on the next, and nobody will trust a number that moves like that. A persistent signal still arrives in full; it just takes more than one batch of evidence to get there. When someone asks why the proposal is only 1.12 when the data says 1.30, that is the answer, and the `shrinkage_why` field says it in the output.

## Sample size gates two different things

**Whether to propose at all** — below the minimum, the analysis reports the accuracy figures and proposes nothing. "We do not know yet" is a finding.

**Whether the band moves** — the dead-band on the residual spread scales with sample size, because the spread statistic is itself noisy when measured over few projects. Over eight projects an observed spread of 1.13 is indistinguishable from 1.0, so it does not move anything. This is why band-width proposals appear later than sizing ones despite needing the same data.

## What each proposal needs, and what it cannot know

| Proposal | Needs | Cannot be derived from |
| --- | --- | --- |
| `uncertainty.model_risk` | Project totals | — the easiest to earn |
| `size_bands.*` | Project totals | Anything finer is better, but totals suffice |
| `planning.review_hours`, `planning.agent_hours`, `env_infra`, `qa`, `overhead_rate` | Phase-level hours | Project totals — the phases are not separable from a single number |
| `review_tier` per tier, `compressibility` per class | Per-feature hours, or projects of genuinely different shape | Totals from similar projects, at any sample size |

That last row is the one people expect and cannot have cheaply. Review tier and compressibility are the module's core IP, and separating them from project totals needs projects that differ — a payments-heavy one and a CRUD-heavy one — not simply more of the same. Ten identical projects carry the information of one. The analysis says whether the delivered projects vary enough, and refuses the fit when they do not.

## Backtest verdicts

`improves past estimates` means the change reduces error on delivered projects, or moves band coverage toward the target. `makes past estimates worse` means the opposite — and note it fires on band coverage falling below target even when central error does not move at all, because a change to band width leaves every central figure untouched while still being harmful.

An overshoot above the target is reported but not treated as harm: a good sizing correction often widens coverage past 68% as a side effect, and the band-width proposal is what tightens it afterwards.
