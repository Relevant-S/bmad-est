# Platform binding

Layer 2 decided *what* is bought, adopted or built. Layer 3 decides *from whom*, and is free to
satisfy several bought capabilities with one platform — which is exactly what the sprawl
sub-score rewards.

## The candidate space is open

Not three vendors. AWS, GCP and Azure sit beside Vercel, Netlify, Cloudflare, Supabase,
Firebase, Heroku, Render, Fly.io, Railway, PlanetScale, Neon, Clerk, Auth0 and a self-hosted
profile. **Adding one is a data file, never code** — if a platform ever needs code, the
capability boundary is in the wrong place, and that is the test this design has to keep passing.

## A set is often a combination

Frontend on Vercel, auth and Postgres on Supabase, object store on S3 is an ordinary and often
correct answer. It is also four accounts, four bills, four SLAs, four failure domains and, under
a compliance regime, four data-processing agreements.

Without a term for that, a scorer picks the theoretically-best service for each capability
independently and arrives at nine vendors nobody can operate. `vendor_sprawl` is that term, and
a vendor serving only capabilities another platform in the set already provides is **refused**,
with that stated — est-plan's refusal to hire someone who does not fill their time, in a
different currency.

## How sets are enumerated

Deterministically. Each plausible primary — a platform that can host the application or the web
client — is tried alone **and with each other platform as a preferred second**; the remainder is
then filled with whichever platform covers the **most** remaining capabilities. Same inventory,
same candidates, every run, so two readings of one project can be compared.

Two corrections from the first real run, both of which made the enumeration unable to answer the
question it was asked:

- **The fill took the alphabetically first platform covering anything**, not the one covering the
  most — which this page had always claimed. A broad vendor swept up every leftover purely
  because of its name.
- **Without a preferred second, a combination was unreachable.** A platform serving nearly
  everything absorbed all the leftovers in every set, so "Vercel + Supabase" could not be
  enumerated at all and "is hosting open?" had no answer the scoring could give.

Sets that are indistinguishable on **every** sub-score collapse into one option carrying its
variants, so a table shows six real choices rather than thirty-three permutations of two. Sets
that merely tie on the headline are kept apart: the same 9.8 can be strong on runtime and weak on
reversibility or the reverse, and folding those together hides the trade.

The catalogue ships twenty profiles and is deliberately shaped to stress the design: IaaS (AWS,
GCP, Azure), PaaS that can run a worker (Heroku, Render, Fly.io, Railway), PaaS that cannot
(Vercel, Netlify), BaaS (Supabase, Firebase), single-capability specialists (Clerk, Auth0, Neon,
PlanetScale, Stripe, Resend, Sentry, Cloudflare) and self-hosted. A backlog needing a worker
cannot be served by a request-scoped PaaS alone, and the combination that results is the honest
answer rather than a single vendor chosen because the enumeration could not express anything
else.

## Where profiles live

Shipped ones in `assets/platforms/`; the company's own in `{memory}/platforms/`. Both are read
and **memory wins on a clash**, so a company can correct a shipped profile and add its own
without forking the catalogue. A run wrote six profiles into memory and nothing read them,
because the loader defaulted to the asset directory — the scoring ran against a three-platform
catalogue while nine sat on disk.

## Profile fields

| Field | Notes |
| --- | --- |
| `serves.<capability>` | `service` is the concrete product name that reaches the diagram and the cost table. `managed` drives operational burden. `interface` (`standard` or `proprietary`) drives reversibility — a candidate behind OIDC, the S3 API or SQL scores far above one behind a proprietary interface, even when both are third-party. `icon` must be in `assets/icons.verified.json`. |
| A `serves` entry with no `service` | A **recorded absence** — Supabase's `cache` says out loud that there is no managed cache. Not the same as the capability being missing from the file, which would mean nobody considered it. |
| `runtime` | What it can actually run: `long_running`, `background_jobs`, `websockets`, `containers`, `native_dependencies`, `cold_start`. The runtime-fit sub-score reads these and nothing else. The requirement is **derived** from the sourcing decisions — building the async work is what makes `long_running` necessary — rather than assumed from a fixed list. |
| `pricing` | Where the cost breakdown goes to look. A vendor with a machine-readable price list (AWS has one) should name it: it beats scraping a marketing page that may not carry the figure at all. |
| `volatile` | Certifications, regions, residency. **Every one carries `checked`.** |

## `checked: null` is not "no"

A volatile field nobody has verified is **not** evidence of absence. A certification or
residency gate against one is reported **unevaluated** — neither a pass nor a fail — and
`architecture-check.py` raises a finding when a gate rests on one. Treating it as a pass would
put an unchecked compliance claim behind a recommendation; treating it as a fail would silently
drop every candidate on every project.

Research it, write the value, the date and the URL, and the gate starts working for that
platform. A fact older than `costing.stale_after_days` is flagged again.

## The house preference

`est_house_platform` adds a stated bonus (0.4) to the team-fit and operational sub-scores of
platforms the company already runs — a real advantage, because an existing account, pipeline and
on-call knowledge genuinely cost less. It is a **weight and never a gate**: it cannot make a
non-viable set viable, and when the margin is under `material_margin` the report says the
tiebreak decided it rather than presenting it as a win.
