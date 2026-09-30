# Headless

`-H`/`--headless`, no TTY, a programmatic caller, or every input supplied up front.

The rule is the same one the rest of the module follows: **an unattended run makes the honest
default choice and reports what it could not ask.** It never invents a constraint and never
presents an unconfirmed decision as a confirmed one.

## At each point that would otherwise ask

| Decision | Headless behaviour |
| --- | --- |
| **Platform requirements** | None assumed. Nothing is gated and the scoring decides; the house preference still breaks ties, and still says when it did. |
| **Procurement and licence position** | Unknown. Every `cost_licence` sub-score that depends on it scores `null` and is listed in `unsourced_subscores`. Never assume the client will pay for subscriptions. |
| **Non-functional drivers** | Only what the inventory states. Each recorded with `basis: "inventory"`; nothing is defaulted into existence. |
| **Hard constraints** | None. An unattended run must not invent a compliance regime, and must not quietly drop one either — if the inventory mentions one, it becomes an `open_question` in the return value. |
| **All three gates** | Take the recommendation at each, proceed, and return `stack_confirmed`, `sourcing_confirmed` and `platform_confirmed` all **false**. An unattended run may choose; it may not report a choice nobody made as though somebody had. |
| **A capability→story link** | Stays `how: "signal"`. The return value reports how many links are unconfirmed keyword matches. |

## Return value

```json
{"architecture": "<path>", "diagram": "<path>", "costs": "<path|null>",
 "stack": "<id|null>", "platforms": ["aws"],
 "confirmed": {"stack": false, "sourcing": false, "platform": false},
 "stack_reverses_a_recorded_decision": false,
 "balance": {"build": 6, "adopt": 0, "buy": 1},
 "unsourced_subscores": ["stack.team_fit", "sourcing.async_work.adopt"],
 "catalogue_gaps": ["payments"],
 "unpriced_rows": 2,
 "audit": {"ok": true, "checked": "..."},
 "open_questions": []}
```

## What still fails rather than degrades

- **No renderer.** The diagram is a required output. Exit non-zero naming `/est-setup`; do not
  write a partial workspace and report success.
- **A failed audit.** `architect.py` exits 2. The file is still written so it can be argued
  with, and it must not be sent.
- **A cost row whose quote is not on its page.** `cost-check.py` exits 1. An unattended run has
  no more licence to quote an unverifiable figure than an attended one.

## What headless must never do

Fabricate a price, invent a candidate, assume a certification, or confirm its own sourcing
table. Each of those turns an honest gap into a confident claim, which is the one failure this
module is built to prevent.
