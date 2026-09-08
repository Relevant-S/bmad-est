# Headless

An unattended run of `est-estimate` — batch presale triage, a scheduled re-estimate, or a call from a sibling skill. Everything in the interactive flow still applies: validate the inventory, classify it, settle the profile inputs, compute, render, record. What changes is every point that would otherwise ask a human, and what comes back at the end.

Headless holds for the whole run once recognised — do not fall back to asking partway through.

## Defaults at the human gates

Each of these replaces a question. **Take the default, then log it.** An unattended estimate that quietly assumes things is worse than none at all, because its output is indistinguishable from a reviewed one.

| Gate | Interactive | Headless |
| --- | --- | --- |
| Inventory has unresolved check findings | Fix them, or ask | **Stop.** Return `blocked` with the findings. Pricing a broken inventory is the one failure that produces a confident wrong number |
| No Feature Inventory, only raw documents | Point at `est-scope-extract` | **Stop.** Return `blocked` naming the skill to run first — never extract scope here |
| No classification yet | Classify it | Classify it here too — it is this skill's judgement, not a question for the operator. Fan out if subagents are available, work the epics in order if not, and say which way it ran |
| Sizing warnings after the reconcile pass | Re-judge, or answer them | Run the reconcile pass once, then proceed and put anything still flagged at the top of `needs_attention`. A band shape away from the anchor can be right; an unexamined one cannot be called right |
| An inventory carrying inline tags | Split it | Run `scripts/split-inventory.py --in-place`, log it as an assumption, and carry on. It is a move, not a judgement |
| Team profile unknown | Ask, or take `company-profile.md` | `balanced`, or the profile in `{memory}/company-profile.md` |
| Stack / QA platform / engagement unknown | Ask | `standard_saas` / `web` / `standard`, unless the inventory's own features indicate mobile, in which case `mobile_mcp_automated` where the company profile says the MCP server is in use |
| Large `outside_agreed_scope` share | Raise it with the operator | Proceed, and put it at the top of `needs_attention` |
| Risk-quadrant features present | Talk through them | Proceed, and list them in `needs_attention` |
| Ledger status | Ask | `draft` — never `sent` or `won`, which are commercial facts no unattended run can know |

The conservative choice is always the one that keeps the decision visible.

## Logging every assumption

For each default taken, append one entry through `{project-root}/_bmad/scripts/memlog.py`:

```
uv run {project-root}/_bmad/scripts/memlog.py append --path {workspace}/.memlog.md \
  --type assumption --text "<what was assumed, and what would have been asked>"
```

Log the four profile inputs without exception — team seniority, stack, QA platform and engagement model each move the number.

## Returning

Emit this and nothing else:

```json
{
  "status": "complete",
  "mode": "presale",
  "workspace": "{workspace}",
  "estimate": "{workspace}/estimate.json",
  "report": "{workspace}/estimate.md",
  "html": "{workspace}/estimate.html",
  "brief": "{workspace}/estimate-brief.json",
  "ledger_entry": "<path to the recorded entry>",
  "memlog": "{workspace}/.memlog.md",
  "total_hours": { "low": 298, "likely": 414, "high": 530 },
  "input_completeness": 0.21,
  "scope_split": { "in_agreed_scope": 190, "outside_agreed_scope": 224 },
  "needs_attention": [
    {"kind": "scope", "detail": "54% of the estimate is work the SOW does not cover"},
    {"kind": "risk_quadrant", "detail": "F4 is low-compressibility and novel — widest real uncertainty"},
    {"kind": "assumption", "detail": "team profile defaulted to balanced; no company profile found"}
  ]
}
```

On failure return `"status": "blocked"` with a one-line `"reason"` and the `memlog` path, so the caller can read what happened rather than inferring it from an absence.

`needs_attention` is the load-bearing field. It is what lets a batch of twenty presale estimates be triaged by a human in minutes: the number is in the file, and this list says which ones a person actually needs to look at.
