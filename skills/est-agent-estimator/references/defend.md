# Explaining, defending and re-cutting a number

*Paths, so this file resolves on its own if SKILL.md is no longer in context: `{workspace}` → `{estimates}/{project-slug}/`, the project's folder. `{memory}` → `{project-root}/_bmad/memory/est/`. `{estimates}` → `modules.est.est_output_folder` from the resolved config, defaulting to `{output_folder}/estimates`.*

Load `{workspace}/estimate-brief.json`. It is the distillate built for this conversation, and it already holds what people ask about. Reach for `{workspace}/estimate.json` only for `scope_split[…].standalone_hours`, `dependencies`, `duration` and `project_components` — the fields the brief deliberately leaves out.

**If the brief is not there, stop and look at what the workspace actually holds** — this is common rather than exotic, and reading `estimate.json` for something to talk about is the wrong recovery.

| What is there | What to say |
| --- | --- |
| Nothing, or only sources | Nothing has been priced. Route to `est-scope-extract` then `est-estimate` |
| An inventory, no estimate | The scope exists and the number does not. Offer to run `est-estimate` |
| A `quick`-mode estimate | Only the markdown exists — no brief, no per-feature chain, no ledger entry, by design. It answered a go/no-go and cannot be decomposed or defended. Say so and offer a `presale` re-run, which is minutes |

**Then check the ledger before you re-price anything.** `uv run {project-root}/skills/est-agent-estimator/scripts/portfolio.py --estimates {estimates} --ledger {memory}/ledger` returns each project's entries with their `status`, and what that status says changes what a scenario even means:

- **`draft`** — proceed as written below.
- **`sent`** — the client is holding a number. A re-price is a re-quote: name both figures and what changed between them, rather than quietly presenting the new one.
- **`won` or `delivered`** — the total is contractually fixed. A scenario here is a change order, not a revised estimate. Quote the addition's `standalone_hours` and never put a new project total in front of anyone.
- **A workspace estimate that disagrees with the latest `sent` or `won` entry** — someone re-ran it locally after the number went out. Say which figure the client actually holds before answering anything else.

## Explain

The chain is in the brief and you walk it downward until the person stops asking:

```
total_hours → by_phase / features[].hours → features[].dominant_component
            → features[].why.<axis>.value  (the tag)
            → features[].why.<axis>.why    (why that tag)
            → features[].source.quote      (the client's own sentence)
```

The coefficient step lives in `estimate.json`, not the brief: `features[].component_hours` splits a feature into build, spec, review and rework, and `cost_model_snapshot` holds the rate each tag selected, with its own `why`. Reach for them when someone asks why a tag costs what it costs — that is the link the chain would otherwise skip.

**"Who actually does this work?" is answered per story, not per project.** `features[].by_role` in the brief carries the split for each line, and a role missing from it is not a rounding artefact — it is a role the story's `surfaces` say is not on this work. A backend job bills no designer, and saying so is more convincing than a project-level pie chart. The architect never appears against a story: story review is developer work, and the architect's hours sit in `project_components` where the planning and coordination are.

**Two kinds of line are not the client's scope, and both say so on their own row.** `origin: standing` is setup, pipeline, environment and release work that every project pays and no document describes — it is in `standing_work` with its own total, and `--no-standing-work` removes the whole block if the client is bringing a platform. `origin: implicit` is work this project's own source implies without stating; its `rationale` is what stands where a quote normally would. Neither is folded into the total silently, and neither should be offered as a scope cut.

`why.<axis>.status` tells you how much weight the tag deserves: `confirmed` and `overridden` were decided by a human, `inferred` was not. An inferred `sensitive` tag on a feature carrying 40% of the review hours is the first thing to check when a number looks wrong.

Two questions come up constantly and both have real answers rather than apologies:

- **"Why is this feature four times that one when they look the same size?"** Because review scales with the volume of output, not the time taken to produce it. Compression collapses `build` and leaves `review` untouched, so a payments screen and a settings screen diverge exactly where the review tier differs. `dominant_component` names which half is doing it.
- **"Why is the range so wide?"** Because `confidence.input_completeness` is what set it. Quote `confidence.why`, which states the multiplier. The band is computed from the input, so it cannot be tightened by anyone being braver about it.

## Defend under challenge

Four things carry a challenge, and only the pricing rule is a sequence rather than a standing habit.

**Find where the give actually is.** Compression is where BMad helps, so high-compressibility work is already cheap and cutting it saves little. The give is in scope, not in coefficients. Sort features by hours and look at what carries the total.

**Name where there is no give.** `risk_quadrant` in `estimate.json` lists the low-compressibility, sensitive-or-critical features — the work BMad barely accelerates and review dominates. Those hours do not move without moving the requirement, and saying so early is more persuasive than defending the total afterwards.

**Price every proposed cut before you agree to it.** Never estimate a saving in your head; run it (below). A cut that looks like 80 hours is routinely 120 or 45, and being wrong about it in a client call is expensive in a way being slow is not.

**When the challenge is about the coefficients rather than the scope**, that is a curation conversation, not a negotiation. Finish here, then go back to the routing table and load the curation capability — a coefficient never moves in the middle of a defence.

## Rehearse it, if they want that

When someone is preparing for a call rather than asking a question, offer to play the client's side — once, and drop it the moment they want a straight answer instead. A user in a hurry should never have to sit through a role-play.

The value is that you are holding the exact ammunition a sharp procurement lead would use, and it is better met here than in the room:

- **`risk_quadrant`** — *"you are charging most for the work you tell me your tooling doesn't help with."* Real, and answerable: that is where review dominates, which is the honest reason it costs what it does.
- **`outside_agreed_scope` share** — *"why am I being quoted for things that aren't in the contract?"*
- **An `inferred` `sensitive` or `critical` tag carrying a large share of the review hours** — *"who decided this was sensitive?"* If nobody confirmed it, that is worth knowing before the client asks rather than after.
- **`calibrated: false`** — *"what is this based on?"* The shape is defensible; the absolute hours are a reasoned hypothesis. Say so first rather than being caught with it.

Attack one at a time, then drop back and work whichever answer came out thin.

## What-if

Every recomputation is one command. All figures come back from a real re-price through est-estimate's engine, and the script refuses outright if it cannot first reproduce the estimate's own headline from its own snapshot.

```
uv run scripts/scenario.py {workspace}/estimate.json --drop F3 F7
uv run scripts/scenario.py {workspace}/estimate.json --drop F3 --with-dependents
uv run scripts/scenario.py {workspace}/estimate.json --retag F4:review_tier=routine
uv run scripts/scenario.py {workspace}/estimate.json --set team_profile=senior-heavy
uv run scripts/scenario.py {workspace}/estimate.json --add-file change-request.json
uv run scripts/scenario.py {workspace}/estimate.json --to-budget 600
```

`--help` for the full interface. It also runs against a ledger entry, which is how you price a change request against a project that is already sold — and on a sold project the ledger rule above applies: what comes back is the price of the addition, never a new total for the deal.

**A scenario number decomposes like any other.** `scenario_estimate.features` carries each feature's re-priced hours, what it was, the change, its component split and the tags that produced it — so a retagged or re-teamed headline breaks down through the same chain. That matters most here, because a scenario total is the figure said out loud in the room.

**Quote `comparison.saving`, never `dropped_features_own_hours`.** The script reports both and says why they differ: overhead, QA and planning review shrink with the scope that remains, so the feature's own hours are never the saving. `saving_vs_own_hours` is written to be read out loud.

**`dependency_warnings` is not advisory.** It names features still in scope that depend on something the scenario removed. Priced work that has lost what it was built on is not a smaller project, it is a broken plan — either re-run with `--with-dependents` or take the warning to the client.

**A retag is a commercial claim, not a discount.** `--retag F4:review_tier=routine` answers "what would this cost if payments did not need line-by-line review" — and if the feature touches money, the answer is that it does need it. Use retags to show what a requirement costs, never to reach a number someone wanted.

## "The proposal needs one number"

Refusing does not prevent it. The proposal template has one field, so someone picks a figure out of the band on the way to the document, alone, unrecorded — which is the spreadsheet behaviour this agent exists to replace. Give them the figure and the position that goes with it.

**Quote `total_hours.likely` unless there is a reason not to.** It is the PERT mean, it is what the ledger entry already records, and quoting it means the proposal and the estimate cannot drift apart. Any other point on the band is a deliberate commercial choice — say which point it is and why, in the proposal itself and to whoever is signing it, because the ledger stores the band and not the figure that went out.

**Name what the single number is.** "830 hours" alone is a promise. "830 is the mid-point; the range is 620 to 1,040 and the width comes from an input completeness of 0.24" is a position, and it survives the conversation where the project comes in at 950.

**Then mark it as gone out** — `uv run {project-root}/skills/est-estimate/scripts/ledger.py --ledger {memory}/ledger --set-status <id> sent` — so the portfolio knows a number is with a client.

The refusal is reserved for the thing that is actually unsafe: a **fixed price** against a band this wide. That is not a number problem, it is a contract problem, and the honest sentence is that a fixed price needs the input completeness raised first — which is what `narrowing_questions` is for.

## Handing over the artefact

A defend session that ends in scrollback has produced nothing anyone can take into a room. Three things already exist in `{workspace}` and are worth naming:

- **`estimate.html`** — the interactive report, where unticking a feature recomputes the whole range live, overheads included. This is the module's best answer to "your number is too high": open it in the client call and the conversation becomes *which of these do you want*. It is the reason to reach for this agent rather than a spreadsheet, so hand it over rather than describing it.
- **`estimate.csv`** — the line items, for sales.
- **`estimate.md`** — the written version, with assumptions and exclusions attached.

When a scenario is agreed, the rendered artefacts are now behind the decision. Re-run `uv run {project-root}/skills/est-estimate/scripts/render-estimate.py {workspace}/estimate.json` after the inventory or the estimate is updated, so what the client opens matches what was agreed — and verify the browser recompute still matches the engine with `check-parity.py` before anyone sees it.

## Pricing a change request

The one scenario that starts from a file you have to author, and the one whose result must not stay in the terminal.

The added feature is a normal inventory feature and is held to the same bar as one extracted from a document — **including its citation**, which here is the client's own request. A change-request email is a citable source; an addition with no quote behind it is invented scope that happens to have been invented late.

```json
[{ "id": "F9", "name": "Bulk CSV import",
   "description": "Admins upload a CSV to create users in bulk.",
   "commitment": "committed", "scope_status": "outside_agreed_scope",
   "citations": [{"source_id": "CR1", "location": "change request 2026-10-02",
                  "quote": "we also need to be able to upload users in bulk from a spreadsheet"}],
   "tags": {"size_band":       {"value": "M",        "why": "…", "status": "inferred"},
            "compressibility": {"value": "high",     "why": "…", "status": "inferred"},
            "review_tier":     {"value": "sensitive","why": "…", "status": "confirmed"},
            "clarity":         {"value": "medium",   "why": "…", "status": "inferred"},
            "novelty":         {"value": "standard", "why": "…", "status": "inferred"}},
   "depends_on": [], "open_questions": [] }]
```

Run it against the **ledger entry**, not the workspace estimate, so it prices against the scope that was actually sold:

```
uv run scripts/scenario.py {memory}/ledger/<id>.json --add-file change-request.json
```

`scope_status: outside_agreed_scope` is almost always right for a change request, and it is what keeps the addition out of the agreed number. Quote the addition's own cost, never a revised project total.

**Then record it, or the divergence you just measured becomes invisible.** A terminal re-price leaves the ledger showing the sold project exactly as before, and the agreed number and the quoted number drift apart silently — which is the scope-creep case this module exists to catch. Append the request to the project's sources and re-run `est-scope-extract` and `est-estimate`, then record the result as a revision: `uv run {project-root}/skills/est-estimate/scripts/ledger.py --ledger {memory}/ledger --record {workspace}/estimate.json --status draft --revision`. Both entries survive, and the history of how the number moved is the thing calibration wants most.

## Cut lines

`--to-budget` proposes cuts, each figure a genuine re-price, in an order that puts the easiest conversation first: outside the agreed scope, then speculative, then implied, then committed. Read three fields before you present anything.

`restored_as_unnecessary` lists cuts the greedy walk took and then put back because the budget did not need them. `candidates` is the full table with each feature's dependency closure and true saving — that is where you find the alternative the ordering did not pick, and the person you are talking to knows what is worth keeping far better than the priority rules do. `unreachable_reason` appears when no cut reaches the target, because planning, standing setup work, QA and overhead are paid on whatever ships; when it appears, say so directly. A budget below the floor is a different project, and pretending otherwise sells work nobody can deliver.

## Sanity-check a human's number

Compare their figure against `by_phase` and ask where they differ. Almost always it is one of three places: they priced build effort from pre-BMad intuition and forgot that review did not compress with it; they left out planning review, which the company does at 100% without exception; or they know something true about the client that the tags do not capture. The third is a calibration input, not an error, and it needs somewhere to land or it lasts only as long as the session. Write it down as you hear it: something about how the company works goes to `{memory}/company-profile.md`; a delivered-hours anchor they quote goes to `{memory}/comparables.md` with its source; a disagreement about a coefficient with no delivered evidence behind it yet is a curation conversation for after this one, so write down what they said and who said it.

`manual_equivalent.manual_hours` in `estimate.json` is the honest anchor here: it is what a human team would have spent writing this code, and it is the number their intuition is actually calibrated against. Say what it rests on in the same breath — the multiple behind it is one sentence in a delivered project's own effort assessment, and nobody estimated any of the three calibration projects manually.

**Then read `{memory}/comparables.md`.** It holds what projects of this shape were estimated at and what they actually cost, which settles a disagreement faster than any argument from coefficients — and it is the first thing a fifteen-year veteran reaches for. Quote a comparable with its scope shape and how far its actual landed from its estimate, and call it an anchor rather than evidence: three similar projects are a pattern worth naming, not a calibration.

## Range-narrowing questions

`narrowing_questions` is ranked by how much band each one removes. Each carries an `assumes` field naming the answer its figure is priced on — quote that alongside the hours, because a tier *confirmed* rather than downgraded narrows nothing. On a thin brief this list is worth more than the estimate, and it is the right thing to send a client instead of a tighter number.
