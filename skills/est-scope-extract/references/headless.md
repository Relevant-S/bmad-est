# Headless

An unattended run of `est-scope-extract` — batch presale triage, a scheduled job, or a call from a sibling skill such as `est-estimate`. Everything in the interactive flow still applies: convert, extract, classify, account for coverage, check, review, render, report. What changes is every point that would otherwise ask a human, and what comes back at the end.

## Recognising it

No TTY, a programmatic caller, an explicit `-H` / `--headless`, or all inputs supplied up front with no operator expected. Once recognised, it holds for the whole run — do not fall back to asking partway through.

The three things a create run settles first — project name, `granularity`, and which source is contractual — come from the caller's parameters. When one is missing, infer it and record the inference as an `assumption`: the workspace slug from the file or folder name, `granularity` from the breadth of what was supplied, and the contractual source from the manifest's own `doc_type` classification.

## Defaults at the human gates

Each of these replaces a question. **Take the default, then log it** — an unattended run that quietly decides things is worse than no run at all, because its output is indistinguishable from a reviewed one.

| Gate | Interactive | Headless |
| --- | --- | --- |
| Feature tagged `sensitive` or `critical` | Confirm with the operator | Leave `status: inferred`; list in `needs_confirmation` |
| Inferred dependency | Confirm with the operator | Leave `inferred: true`; list in `needs_confirmation` |
| Feature not traceable to a contractual source | Ask: inside, outside, or not scope | Set `scope_status: outside_agreed_scope` — the conservative reading, since it is reported as an addition rather than folded into the agreed number — and list it |
| Sources that contradict each other | Surface for resolution | Record in `conflicts` and leave unresolved; never pick one |
| Per-source review pass | Subagents, or sequential fallback | Same; when neither is available, say so in the report rather than skipping it |

The conservative choice is always the one that keeps the decision visible: a tag stays `inferred` rather than being asserted, and uncovered work is priced separately rather than absorbed into an agreed number someone will later be held to.

## Logging every assumption

For each default taken, append one entry through `{project-root}/_bmad/scripts/memlog.py`:

```
uv run {project-root}/_bmad/scripts/memlog.py append --path <workspace>/.memlog.md \
  --type assumption --text "<what was assumed, and what would have been asked>"
```

This is the whole audit trail for an unattended run. Without it the next person cannot tell which classifications a human stood behind and which the machine guessed, and the `status` field alone does not say what the alternative was.

## Returning

Emit this and nothing else — a caller needs paths, not prose:

```json
{
  "status": "complete",
  "intent": "create",
  "workspace": "<path>",
  "inventory": "<path>/feature-inventory.json",
  "report": "<path>/extraction-report.md",
  "memlog": "<path>/.memlog.md",
  "features": 12,
  "input_completeness": 0.41,
  "needs_confirmation": [
    {"feature": "F4", "kind": "review_tier", "detail": "tagged sensitive from 'signature capture'"},
    {"feature": "F7", "kind": "scope_status", "detail": "not covered by the SOW; defaulted to outside_agreed_scope"}
  ]
}
```

Use `"intent": "update"` or `"validate"` as appropriate. When the run cannot finish — no source could be read, or `inventory-check.py` will not come back clean — return `"status": "blocked"` with a one-line `"reason"` and still return the `memlog` path, so the caller can read what happened rather than guessing from an absence.

`needs_confirmation` is the load-bearing field. It is what lets a batch of twenty presale extractions be triaged by a human in minutes: everything the machine was unsure about, in one list, per project.
