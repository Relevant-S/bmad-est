# Architecture preferences

What this company has actually delivered in, and what it will and will not run. Seeded with
every section `UNANSWERED` and **never overwritten after** — the same convention as
`company-profile.md`.

**`UNANSWERED` is not an answer.** Until a section is filled in, the sub-scores that read it
report `null` and say why, rather than defaulting to the middle. A default that looks like a
measurement is worse than an admitted gap, because nobody argues with a number.

The fenced block below is what the scripts read. The prose around it is for the human filling
it in.

```yaml
# Technologies with at least one DELIVERED project behind them. Not "we have used it" —
# delivered, because the novelty coefficient prices the difference at 1.15x on every story.
delivered_in: UNANSWERED

# Platforms this company already holds accounts, pipelines and on-call knowledge for. These
# get the house tiebreak bonus, which is a weight and never a gate.
house_platforms: UNANSWERED

# Third-party services already under contract. A capability served by one of these adds no
# new vendor, no new bill and no new DPA, which is what the sprawl sub-score measures.
existing_subscriptions: UNANSWERED

# Things this company will not run or will not buy, with the reason. A refusal recorded here
# is a constraint; a preference belongs in the weights instead.
will_not_run: UNANSWERED
will_not_buy: UNANSWERED
```

## How a sourcing decision gets recorded here

After a project ships, add what was adopted or bought and how it went. This is the closest
thing the module will ever have to evidence on the sourcing layer — `est-calibrate` reconciles
hours against actuals, and an adopted component that cost three times its estimated integration
is the first real signal the asserted `sourcing_effort` ratios have ever had.

| Project | Capability | Mode | Candidate | How it went |
| --- | --- | --- | --- | --- |
