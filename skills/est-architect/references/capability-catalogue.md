# The capability catalogue

A **capability** is what a system needs, stated without naming who provides it: identity, an
object store, async work, model inference. It is the unit every layer of this workflow turns on,
and it is never a vendor.

That separation is what makes the workflow cloud-agnostic by construction rather than by
prompting. The architecture is designed once in capabilities; a platform profile binds each one
to that platform's service and its icon. Re-binding an existing design to a different provider
is a re-render, not a redesign, and adding Azure, Hetzner or an on-prem estate is a data file.

## Where the catalogue lives

`{memory}/architecture-model.json`, seeded once from `assets/architecture-model.seed.json` and
never overwritten after. Each entry carries:

| Field | What it is for |
| --- | --- |
| `name`, `what` | How it reads on the diagram and in the report. |
| `tier` | The diagram column: `actors`, `edge`, `application`, `services`, `data`, `external`. This is what makes the layout deterministic instead of a judgement made afresh each run. |
| `surfaces` | Which story surfaces imply it. |
| `signals` | Lowercase phrases matched against a story's name, description and task text. |
| `icon` | A name from `assets/icons.verified.json` — see *Icons* below. |
| `settled` | A mode nobody sensibly argues about, with the reason. A settled capability never reaches a scoring table. |

## The map is built by keyword, and says so

`capabilities.py` matches `signals` against each story's prose and records every link as
`how: "signal"` with the phrase that matched. **This is weak evidence and is labelled as such.**
The operator's corrections promote a link to `how: "operator"`, and `architecture-check.py`
reports the split — so a reader can see how much of a confident-looking map is substring search.

Two failure modes are worth knowing about because both happened:

- **Over-matching.** A plain `in` test put model inference on eleven stories by matching `ai`
  inside `maintain`, `available` and `email`. Matching is now bounded at the front of a word.
- **Under-matching.** Identity missed *"Patient self-registration"* because the signal list had
  `signup` and `sign up` but not `registration`. Read the map against the backlog; a missing
  capability is as wrong as a spurious one.

`application` and `web_client` are special: they take every story on their surface, because
that is literally where those stories run. They are marked `capability_is_the_project`.

## Adding a capability

Add it to `{memory}/architecture-model.json`, give it a tier, signals and a verified icon, and
add a `serves` entry to every platform profile that offers it. A capability no profile serves is
reported as a **catalogue gap** — a gap in the catalogue, not a flaw in any option — so the
workflow degrades honestly while you fill it in.

## Icons

`assets/icons.verified.json` lists the names **proved** to resolve, by rendering each one and
reading the renderer's `W_UNKNOWN_ICON` warnings. Seven of the first batch did not exist —
`aws-s3` is `aws-simple-storage-service`, `nodejs` is `node`, `gcp` is `google-cloud`. An
unverified name fails the render rather than shipping a placeholder glyph, because a required
output degrading where nobody looks is worse than one that fails loudly.
