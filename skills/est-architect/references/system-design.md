# System-design judgment

The scoring decides between options. This decides what the options *are* — and a workflow that
generates three mediocre candidates will pick the best mediocre one and report a 9.4.

Read this before proposing anything. It applies to the stack and the sourcing layer as much as
to infrastructure.

## Start from the shape of the problem, not from a stack

Before naming a technology, read the inventory for the five things that actually constrain a
design. All five are in the file; almost none of them are in the PRD's architecture section.

| Question | Where it is in the inventory | What it decides |
| --- | --- | --- |
| **What is the system of record, and how relational is it?** | Epics with a ledger, leases, bookings, double-entry, invoices | Whether a document store is viable at all. A project with a ledger needs transactions; that rules out a BaaS with no relational tier no matter how fast it ships. |
| **What is the read/write shape?** | Story counts per epic; dashboards and reports vs data entry | Read-heavy with a reporting surface implies a separate analytics path. Write-heavy implies the queue is real. |
| **Where does work leave the request?** | `async_work` stories: nightly jobs, webhooks, retries, ingestion | Whether the runtime must hold a process open — the single most common reason a PaaS choice is wrong. |
| **What is the tenancy model?** | Multi-tenant isolation, RLS, org membership | Tenancy leaks into identity, the data model and the compliance story at once. It is the decision hardest to reverse. |
| **What is the regulated surface?** | `not_scope` and `open_questions`, compliance NFRs, payment stories | Which vendors are even eligible, and which data may leave the region. |

If the answer to any of these is not in the inventory, it is an **assumption** and is recorded
as one. Designing on an unrecorded assumption is how a design becomes unarguable.

## Principles that earn their place

**Prefer boring technology.** Every unfamiliar component spends a novelty budget the estimate
prices at 1.15× on every story. Spend it where it buys something the project actually needs,
and nowhere else. Three novel choices in one design is a project that will miss its date for
reasons nobody will be able to attribute.

**A distributed system is a cost, not an achievement.** Splitting into services multiplies
pipelines, environments, failure modes and the standing-work bill — `stack_profile:
multi_service` switches those items on and they carry real hours. Split when a seam is forced by
a team boundary, a scaling boundary or a compliance boundary, not because the diagram looks
more serious.

**Put the queue where the work is, not where the pattern is.** A queue is justified by work that
must survive the request: nightly charges, webhook retries, ingestion, anything with a
dead-letter path. If no story needs one, it is invented infrastructure, and the `serves` rule
will refuse it.

**Buy the things that are somebody's whole company.** Deliverability, card processing, identity
at scale and certificate management are products with years of work behind them; the project
will not out-build them and should not try. Build the domain — the ledger, the leases, the rules
the client is paying for. `references/sourcing.md` has the scoring; this is the intuition it
encodes.

**Do not let a vendor hold your domain model.** A bought component should serve a capability,
not own a concept the product is about. Putting tenancy into an identity vendor's organisation
model because it is convenient couples the domain to a pricing tier and a member cap — and the
project is still building its own tenant records regardless.

**Design for the second year.** The question is not what the free tier costs; it is what happens
at ten times the volume, and what it costs to leave. Both are scored — `free_until` in the cost
table, `escape_cost` in sourcing — and both are usually decided before anybody looks.

**One irreversible decision at a time.** Rank the choices by how hard they are to undo — data
model and tenancy first, runtime second, vendors last — and spend the argument there. Most
architecture debate is spent on the reversible half.

## Failure modes this workflow is prone to

- **Resume-driven design.** The newest thing scores well on ecosystem currency and badly on
  team fit; the weights are there so the trade is visible rather than argued.
- **Cargo-culting the reference architecture.** A vendor's canonical diagram is designed to use
  that vendor's services. Read it for the shape, not the shopping list.
- **Solving for the demo.** The shape that ships a prototype fastest is often the one that
  cannot hold the second year's data. Say which one is being optimised for.
- **Confusing "we could" with "we should".** Every capability *could* be bought. The balance
  finding exists because a design that buys everything is as unconsidered as one that builds
  everything.
- **Designing past the evidence.** Where the inventory is silent, say so and record an
  assumption. An architecture whose basis is invisible cannot be corrected by the one person who
  knows the answer.

## What good looks like in the output

A reader who knows the domain but not this project should be able to say, from the report alone:
what the system of record is and why; where work leaves the request; which decisions are
reversible and which are not; what the team has done before and what it has not; and which parts
of the recommendation rest on nothing. If any of those is missing, the design has not been
explained — whatever it scored.
