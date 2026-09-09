# Company profile

How this company delivers. Every estimate rests on it, so it is prose a person can read and
argue with rather than settings in a config file.

**Nothing parses this.** `est-estimate` reads it to settle four inputs it would otherwise
default silently, and `est-calibrate` reads it to judge whether a team's learning-curve
modifier has done its job. Write it for a colleague, not for a machine.

Lines marked **UNANSWERED** are the ones that change a number. While one is still marked,
`est-estimate` defaults that input and logs the assumption to the workspace memlog — the
estimate is still produced, but it rests on a guess nobody made. Delete the marker when you
answer it. `/est-agent-estimator` runs the interview if you would rather talk it through.

---

## Team shape and seniority

> **UNANSWERED** — selects `team_profiles`, which scales specification, review and rework.
> `senior-heavy` ×0.8/×0.8/×0.7 · `balanced` ×1.0 · `junior-heavy` ×1.3/×1.4/×1.6.
> Build hours are untouched by this: the agent writes the code either way, so the seniority
> gap lands entirely in the judgement-heavy work — and under BMad that gap widens.

Who is on the teams, how many, and what mix of seniority. Name the teams if they differ.

## BMad adoption depth, per team

> **UNANSWERED** — selects the `new-to-bmad` modifier, ×1.2 spec, ×1.2 review, ×1.5 rework.

Which teams have delivered with BMad before, and which are still learning. Per team, not
company-wide: **this modifier is meant to decay.** Once a team's delivered projects stop
showing the penalty, `est-calibrate` should retire it for that team rather than leave it
quietly inflating every estimate they touch.

## Dominant stacks

> **UNANSWERED** — selects the `stack` profile, which gates standing work.
> `mobile_plus_backend` adds ~30 h of mobile release process; `multi_service` adds ~32 h of
> integration environment. Wrong stack and work every project of that shape pays is missing.

What you build most, and what a typical project's architecture looks like.

## QA capability

> **UNANSWERED** — selects the `qa` profile: a share of the story-work total.
> web 9.5% · mobile manual 23.8% · **mobile through the MCP server 7.9%**.
> (These moved in cost-model 3.0. They are a share of delivered story hours now, not of a
> manual-equivalent baseline — the same 40 h of QA, measured against a real number instead
> of a constructed one.)

**Is the mobile MCP server doing the testing?** Nobody volunteers this and it is a threefold
difference on the same mobile scope. The industry default overstates your mobile QA badly, so
leaving it unanswered is wrong in your own disfavour — you lose work on a number that was
never true.

## Engagement model

> **UNANSWERED** — selects `overhead_rate`, priced in hours per person per week rather than as
> a share of scope: `low_touch` 2.0 · `standard` 3.5 · `high_touch` 5.0+.

How you work with clients: ceremony, demos, who reviews, how often. Overhead follows the
calendar, so on a long project this is not a rounding difference.

## Architect setup and support

> Not a question — a recorded fact, and the best-evidenced coefficient in the model. All three
> delivered projects fit `setup + a capped weekly rate` exactly: EPP 40 h setup + 7 weeks x 10;
> memorial-healthcare 30 + 3 x 10; easyterms 30 + 5 x 10. Setup does not scale with the backlog
> and support scales with the calendar, so a bigger backlog does not buy a bigger architect.
> Say here if your engagements run differently — a different setup figure or a different weekly
> ceiling is exactly the kind of thing this file is for.

## House rules

Anything else true of how this company works that an estimate should respect. Three worth
confirming explicitly, because all three read as omissions otherwise:

- **The Architect absorbs PM responsibilities during planning.** There is no PM in the role
  split, deliberately.
- Roles are `architect, dev, devops, qa, ba, ux` — the `est_roles` setting. Every estimate bills
  all six. **Only one of the three calibration projects staffed all six**: memorial-healthcare
  booked no QA and no DevOps, easyterms booked no BA, no UX, no QA and no DevOps. If your
  projects are staffed like those, say so — the estimate will report hours nobody will book.
- **Splitting a story is decomposition, not scope growth.** All three projects delivered roughly
  1.7x the story count they planned, at unchanged scope and unchanged hours. It is priced into
  planning, which pays per artefact written, and nowhere else.

## Rates and commercials

Not here. This file is about how work gets done, not what it is sold for. Delivered-hours
anchors from past projects go in `comparables.md` with their source.
