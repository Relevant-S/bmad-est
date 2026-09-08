# Update and Validate

Two read-mostly intents over an existing Feature Inventory. Both work on `feature-inventory.json` in the extraction workspace at `{estimates}/{project-slug}/`, which is the source of truth; the `.md` and `.csv` beside it are regenerated projections and are never edited directly.

Both intents re-extract or re-read against the same three references a create run uses, and neither works without them:

- `references/source-type-playbook.md` — identifying what a document is and how scope hides in it
- `assets/feature-inventory.schema.json` — the shape every inventory must satisfy

The conversion rule holds here too: read the **normalized** files under `<workspace>/normalized/`, never the originals, because the citation anchors live only in the converted text. A source the manifest marks `needs_native_read` is read directly and recorded in that source's `coverage_note`.

## Update — re-extract against an existing inventory

The scope-creep case: the client sent a revised document, or a new one arrived alongside the old. The output is a merged inventory plus a diff saying exactly what changed, so added scope becomes visible and priceable instead of quietly absorbed.

**Read `.memlog.md` first.** It carries the decisions a human made on the previous pass, and this intent exists partly to avoid undoing them.

Convert the new sources into the same `normalized/` folder — `uv run scripts/convert-input.py <paths> --out-dir <workspace>/normalized -o <workspace>/normalized/manifest-v2.json` (always `-v2`, never `-v3`: it exists only for the length of this run, and a growing series of manifests is a workspace nobody can read) — then extract them into a fresh inventory at `<workspace>/feature-inventory.next.json`, exactly as a create run does: citations against the anchors, coverage accounting, `surfaces` on every story, and `completeness_signals` each carrying their reason.

**Then diff and merge in one step:**

```
uv run scripts/inventory-diff.py <workspace>/feature-inventory.json \
    <workspace>/feature-inventory.next.json \
    --merge <workspace>/feature-inventory.merged.json
```

The merge is deterministic and the script does it, rather than you retyping an inventory — every verbatim quote survives byte-for-byte because nothing regenerates it. It matches features by id and then by name similarity (a re-extraction renumbers freely), keeps the **old** feature ids on matched features so anything referencing them elsewhere still resolves — `classification.json` above all, which keys on those ids — and allocates non-colliding ids to genuinely new features.

**What it will not decide, it returns in `needs_decision`:**

- A feature whose description changed materially in the new sources. Its classification still keys onto it, but the text behind that judgement moved — `classification-merge.py` reports it.
- A feature absent from the re-extraction. Dropped scope, or simply absent because a *different* document was supplied? Nothing is removed automatically; decide, then edit the merged file.

Work through that list before going further. Where the answer is a commercial one — whether removed work is really out of scope — it belongs to the operator, not to you.

**Validate the merge before it replaces anything.** The merge is what keeps feature ids stable, and `classification.json` keys on them — so a merge that renumbered a story silently would orphan the judgement attached to it.

1. `uv run scripts/inventory-check.py <workspace>/feature-inventory.merged.json --normalized <workspace>/normalized --manifest <workspace>/normalized/manifest-v2.json` — clean, or fix and repeat.
2. `uv run scripts/inventory-diff.py <workspace>/feature-inventory.json <workspace>/feature-inventory.merged.json` — the `changed` array must contain only scope changes you can point at in the new sources.
3. `uv run {project-root}/skills/est-estimate/scripts/classification-merge.py <workspace>/classification.json --old <workspace>/feature-inventory.json --new <workspace>/feature-inventory.merged.json` — `orphans` must come back **empty**. Anything listed is a judgement the re-extraction stranded; re-key or re-classify it before pricing.

Only once both pass, move the original to `feature-inventory.prev.json`, promote the merged file to `feature-inventory.json`, delete `.next.json`, and re-render. Then **delete `.prev.json` and `manifest-v2.json` before you finish**: the promotion is the point at which the update either worked or did not, and a workspace that keeps every previous generation stops being readable as a set of current artefacts. The inventory that was replaced is in git and in the memlog; a stale `.prev.json` is only ever mistaken for the live one. `check-outputs.py` names them if they survive.

**Then update `extraction-report.md`** with a scope-change section: features added and removed, stories whose description moved under a classification that was already made, and anything `classification-merge.py` could not re-key. Append a memlog `decision` entry for each `needs_decision` the operator resolved. A story whose text changed under an existing judgement deserves its own line — re-reading it can move the number more than several new small features.

## Validate — read-only recheck

A confidence check before an inventory feeds an estimate, or after someone has hand-edited it. It changes nothing and writes nothing the user has to keep.

```
uv run scripts/inventory-check.py <workspace>/feature-inventory.json \
    --normalized <workspace>/normalized --manifest <workspace>/normalized/manifest.json
```

That one call covers most of what validation means here: every quote checked against the document it cites (with a similarity figure separating a paraphrase from an invention), structured locations resolved against anchors the file actually has, converted sources reconciled against the inventory's `sources`, schema and reference and dependency-graph integrity, `unreferenced_regions` listing the pages and rows nothing points at, `stale` reporting sources newer than the inventory or paths that no longer exist, and the completeness score with its full working.

**If `normalized/` is missing** — moved, cleaned, or never kept — the citation checks cannot run. Re-run `convert-input.py` over the paths in `sources[]` to rebuild it. If those originals are gone too, report the citation check as **not performed** and say plainly that the inventory cannot be certified fit to estimate from; a validate run that silently degrades to a schema check while still blessing the inventory is worse than no validation.

Then do the parts no script can:

- **Does each feature follow from its quote?** The script proves the quote is present; a real quote attached to the wrong conclusion passes every mechanical check. Sample the features whose quotes carry the most weight — anything a contract turns on, anything a compliance regime is named in, anything a single line stands in for.
- **Are the unreferenced regions genuinely insubstantial?** The script says what nothing cites; only you can say whether that matters.
- **Are the `completeness_signals` reasons still true** of the documents as they now stand?

Report findings by severity, and be specific about the two that matter: **features whose citation does not support them** (invented scope) and **substantive passages in neither the features nor `not_scope`** (lost scope). Recommend whether the inventory is fit to estimate from, and where it is not, say what would fix it.

If `stale` comes back non-empty, say so and point at update mode rather than validating a stale artifact into looking healthy.
