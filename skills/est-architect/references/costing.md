# The run-cost breakdown

Required reading before the first row is written.

## The rule

**Every figure traces to a quote from a vendor's pricing page** — the price, the tier's own
wording, the URL, and the date it was fetched. This is the module's founding rule moved one
domain over: every hour in an estimate traces to a quote in a client document, and a price
recalled from memory is the exact analogue of invented scope.

It is worse in one respect. Scope invented from a document can be argued with, because the
document is right there. **A wrong AWS figure looks identical to a right one.**

This is also the point in the whole workflow where fabrication is most likely, because a model
that has read a thousand pricing pages will produce a plausible number faster than it will admit
it could not reach the page.

## How the numbers are obtained

**One research subagent per vendor, not per row** — a vendor's pricing page usually covers
several capabilities, and one fetch answers them together. Each returns ONLY structured rows:

```json
{"item": "Managed Postgres — AWS RDS db.t4g.micro, Single-AZ, eu-west-1",
 "capability": "relational_store", "type": "monthly",
 "rate": 45.0, "quantity": 1, "unit": "instance-month", "currency": "USD",
 "assumption": "1 instance, 20 GB gp3", "assumption_basis": "operator",
 "free_until": null, "payer": "client",
 "low": null, "high": null,
 "quote": "<verbatim from the page>", "url": "https://...", "fetched_at": "2026-09-29"}
```

`price.py` **recomputes** `cost` from `rate x quantity` and every total. A row whose supplied
cost disagrees with its own rate is a finding: arithmetic is never done by hand here.

Where a vendor publishes a machine-readable price list — AWS does — use it. The row shape
accepts it and the `url` becomes the query.

## `unpriced` is a first-class answer

Pricing pages are increasingly JavaScript-rendered, region-gated, or behind *contact sales*. A
price that cannot be fetched is recorded as `unpriced` with its reason, **never guessed**. This
is the `needs_native_read` case from est-scope-extract: the row appears in the table, the totals
say how many rows are missing, and nobody reads a total as complete when it is not.

## Every assumption has a basis

*"25 MVP users"* is itself a number that can be invented. Each assumption is cited to the
inventory where a story states it, recorded as an operator answer where they gave one, or
defaulted and logged in `.memlog.md`. An assumption with no basis is this table's version of a
feature with no citation, and `price.py` says so.

## The format, and why it differs from the one asked for

The operator's three columns come first and in their order, so a reader who wants only
`Item | Cost | Type` reads three columns and stops. Four extensions sit to the right:

| Addition | Why |
| --- | --- |
| **Source** | The no-invention rule cannot be checked by anyone afterwards without it. A rule nobody can verify degrades on the first busy day. |
| **Assumption** | Its own column rather than smuggled into the item text, so `cost` can be recomputed and the whole table re-run against a different assumption: *"what does this cost at 500 users"* becomes one number changed. |
| **Free until** | The most valuable addition. Four rows can read `0` for four different reasons — free at this volume, free forever, free by assumption, not a cost at all — and the dangerous one is invisible. A zero row must name the threshold that ends it, and `price.py` raises a finding when it does not. |
| **Checked** | Prices move. A figure older than `costing.stale_after_days` is flagged. |

Plus **TOTAL — Year 1** (`one-time + 12 x monthly + annually`), which is the number anyone
actually asks for and which the three per-type totals cannot show.

**Credits are not rows.** *"Cloud credits, ~$1k–$5k available"* at `0` is three category errors
at once: an offset rather than a cost, a range rather than a figure, and *available* is not
*granted*. They go in `notes`, under the table, netted into nothing.

`low` and `high` may be `null` on a fixed-price row — that is this document's own shape, and the
totals treat an explicit null as absent rather than raising on it. They used to raise.

**Usage-driven rows carry a range.** A subscription is a contract and a point figure is honest;
Stripe fees, model-inference spend and log ingest are whatever the month does. Fixed rows stay
points, usage rows carry `low`/`high`, and the totals carry the band. A single number for model
usage is a forecast wearing a price tag.

## Verification

`cost-check.py` re-fetches each cited page and checks the quoted text is still on it. Three
verdicts, kept apart on purpose:

- **verified** — the quote is on the page as fetched.
- **not_found** — the page was fetched and the quote is not on it. The dangerous one: fabricated,
  or the price moved. Either way it must not be quoted until somebody looks.
- **unreachable** — could not be fetched, or the page renders its prices in JavaScript. **Not
  evidence of anything**; the row simply has not been re-checked.

**Vendors geo-redirect.** `--locale us` (or `gb`, `de`) sends the matching `Accept-Language` and
country cookie, because stripe.com serves a EUR/PT edition to a European visitor and every Stripe
row in a real run read `not_found` although all six quotes were on the US page. A verdict that
depends on where the machine is sitting is not a verdict.

Script tags are excluded from the search: a price that appears only inside one has not been
published on the page a reader would open. That includes a price behind a JavaScript toggle: Sentry
serves `$26/mo When billed annually` and shows the monthly figure only after a click, so the
checkable quote is the annual one and the row says so.

**A page is read whole or not at all.** The fetch used to stop at 3 MB. AWS's machine-readable
RDS price list for one region is 22 MB, its PostgreSQL rows sit past the cut, and three quotes
that were verbatim on the page came back `not_found` — the verdict that means fabricated or moved.
It now reads up to 64 MB, and a page larger than that is `unreachable` with the reason, never
`not_found`.

## The boundary

**Run-cost is not delivery cost.** The table is dollars per month and continues after the
project ends; the estimate is hours. They are never summed and never rendered adjacent without a
label, and every artefact says so in those words — because somebody will otherwise add twelve
months of run-cost to a project quote.
