# Source Type Playbook

Scope hides differently in different documents, and reading one kind as though it were another is the most reliable way to produce a wrong Feature Inventory. Identify what each source actually is, then read it for what it hides. A document can be more than one thing — an RFP with a backlog sheet appended is both — so classify the parts, not just the file.

Everything below serves one output: features with verbatim citations, a `not_scope` entry for every substantive passage that did not become one, and honest `commitment` and `clarity` tags.

## Transcript (discovery call, workshop, sales meeting)

The hardest input and the most common thin one. Speech mixes commitment levels freely and nobody in the room marks the boundary.

Read for who is speaking and with what authority — a client's CTO saying "we'll need SSO" is different from a salesperson saying "we could do SSO". Attribute in the citation, and cite by timestamp or speaker turn.

The reliable tells: "we need", "it has to" → `committed`. "It'd be good if", "down the line", "phase two", "maybe" → `speculative`. And most importantly, features that arrive as *problems* rather than solutions — "our ops team spends every Monday copying this into a spreadsheet" is a feature request that never names a feature. Extract it as one, with the problem quoted, and put the solution shape in `open_questions`.

Almost everything from a transcript is `clarity: low`. Resist the pull to write a tidy specification from a messy conversation; the untidiness is real information about risk, and flattening it produces a confident estimate of something nobody agreed to.

## SOW / contract

Written to be binding, so it is precise about obligations and often silent about the work. The scope section is the smallest part of the document and the only part that is scope — rates, payment terms, IP, liability, notice periods and governing law all belong in `not_scope`, each with a reason, because a reviewer needs to see they were read and dismissed rather than missed.

**A SOW defines the agreed scope, which makes everything outside it a commercial question.** Once a SOW or RFP is among the sources, any feature the other sources raise but the contract does not cover — the dispatcher workflow described at length on a call and absent from the scope section, the "oh and" at minute 21 — is marked `scope_status: outside_agreed_scope`. It is still extracted and still estimated, because the work is real and someone will be asked to do it; it is simply reported as an addition rather than folded into the agreed number. Stop and ask the operator before tagging one, presenting the feature, its evidence, and the three options: inside the agreed scope, outside it, or not scope at all. Deciding this silently either inflates the agreed price or quietly gives the work away.

Two things carry disproportionate weight. **Exclusions** are as load-bearing as inclusions: an explicit "does not include data migration" belongs in `assumptions` so the estimate does not quietly price it. And **acceptance criteria**, where present, are the strongest `clarity: high` evidence any document type offers. Deliverables and milestones often name features that the scope prose never does — read them as scope.

## RFP / tender

Written to be answered, so it is exhaustive about requirements and vague about implementation, and it is usually padded. Requirements are typically numbered — cite the number, it is the most verifiable location anchor you will get.

Watch for the requirement that reads as one line and is a subsystem ("the system shall support role-based access control across all modules"). Watch equally for the compliance and non-functional sections, which are where the `sensitive` and `critical` review tiers hide, often stated once in a paragraph nobody reads. Mandatory-versus-desirable tables map directly onto `committed` versus `speculative`; use them.

An RFP's evaluation criteria and boilerplate go in `not_scope`, but its stated integrations, volumes and NFRs are gold for `completeness_signals` — this document type usually scores higher on completeness than anything else you will receive.

## PRD / product spec

The friendliest input: written to be built from, usually already decomposed into features with acceptance criteria. The risk is the opposite one — inheriting its structure uncritically.

A PRD's sections are not necessarily estimable units. Merge what the document splits for narrative reasons and split what it bundles for convenience. Its stated non-goals go in `assumptions`. Its user stories carry acceptance criteria that justify `clarity: high` — cite them.

## Backlog workbook (xlsx / csv, often multi-tab)

Nearly a finished inventory, which makes it the most dangerous to skim. Read every tab: scope frequently lives on one and assumptions, out-of-scope items, questions or a phasing plan live on others, and a tab named "Sheet3" is as likely to hold real content as one named "Scope".

Cite by sheet name and row number — `sheet 'Backlog' row 14` — which the normalized conversion preserves exactly: the number shown is the row's real position in the sheet, blank rows included in the count. That also means **no row is marked as the header** and columns are labelled A, B, C. Which row carries the column names is for you to read, not for the converter to assume — a title banner above the real header is common, and a converter that guessed would silently shift every citation below it. Where the workbook already carries estimates from the client or a previous vendor, those are **not** your estimates: record them in the feature's `description` or in `assumptions` as a stated figure, and tag the feature on its own merits. A prior estimate is evidence about expectations, not about effort.

Watch for a phase, priority or MoSCoW column; it maps onto `commitment`. Watch for rows that are epics with child rows beneath them, and do not double-count the parent.

## Brief / email / two paragraphs

The thin end, and the case the whole module exists to handle honestly. Extract what is there, tag nearly all of it `clarity: low`, and put real effort into `open_questions` — with an input this thin, the questions are the deliverable and the number is a placeholder.

Do not inflate a two-paragraph brief into a twenty-feature inventory by inferring everything a product like this "would normally have". Inferring the login screen behind "users can save their work" is legitimate — it is `commitment: implied`, with the implying sentence cited. Inferring an admin dashboard, an audit log and an export feature nobody mentioned is invention, and it will be estimated, quoted, and then argued about.

## Mixed and unknown

When a source resists classification, extract conservatively and set the source's `doc_type` to `mixed` or `other`. When a source contributes nothing at all — a company profile deck, a signed NDA — it still gets a `sources` entry and at least one `not_scope` line saying what it was. A source that appears nowhere in the inventory is indistinguishable from a source nobody opened.
