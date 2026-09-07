# Estimating scope that only exists in someone's head

*Paths, so this file resolves on its own if SKILL.md is no longer in context: `{workspace}` → `{output_folder}/estimates/{project-slug}/`, where `{output_folder}` is `core.output_folder` from the resolved config, defaulting to `{project-root}/_bmad-output`.*

No document, no RFP — a person describing what they want built. **You do not extract the scope yourself.** Your job is the conversation and the transcript it produces; `est-scope-extract` turns that transcript into a verified inventory exactly as it would a client's PDF, and it already knows how to read a transcript for what was committed versus what was mused about.

That split matters. Building the inventory here would skip the coverage accounting, the mechanical quote verification and the per-source review pass — the things that catch invented scope — and an inventory that skips them is the confident wrong number this module exists to prevent. What only you can do is get the person to say the things the classification needs.

## Write the conversation down as a source

This is the artefact you are producing. Traceability requires every feature to quote the text it came from, and in a conversation that text is what the person said — so capture it as a real file rather than leaving it in the chat:

```
{workspace}/normalized/conversation.md
```

Append their own words as they say them, in blocks with headings you can cite. **Do not summarise into it.** A citation has to be verbatim or the checker will reject it, and rightly — and the client's own phrasing surviving into the estimate is what makes the number defensible back to them months later.

When the conversation is done, register it the way every other source is registered — by running the converter over it, not by writing the manifest by hand:

```
uv run {project-root}/skills/est-scope-extract/scripts/convert-input.py {workspace}/normalized/conversation.md \
  --out-dir {workspace}/normalized -o {workspace}/normalized/manifest.json
```

A hand-written manifest entry is missing the fields the tooling reads — `converted_path` above all, without which nothing can tell that the transcript changed after the inventory was built.

## Draw out what the classification needs

You are not running an interview script. The five axes the cost model prices on tell you what is still missing, and the gaps are usually the same ones:

- **Size** needs a sense of surface area — how many screens, how many entities, how many states.
- **Compressibility** needs to know what it touches: greenfield CRUD, or an undocumented legacy system, or a client-proprietary integration nobody outside their building understands.
- **Review tier** needs money, PII, auth, permissions, audit trails, regulated data. Ask directly. This axis moves the number more than any other, and people do not volunteer it because to them it is obviously just "the checkout".
- **Clarity** you do not ask about — you observe it, and you must not flatter it. Someone who explained a feature in one sentence has given you thin material, and it will be tagged accordingly.
- **Novelty** needs to know whether they have built this before.

Capture sequencing as it surfaces too. "Once login is in place, users can…" is a dependency, and the sentence that implies it is gone by the time the estimate runs — so get it into the transcript verbatim while it is still being said.

Push where the description is thin, the same way you would on a document: the user they forgot, the state nobody described, the integration named but never specified. That pushback is the entire reason to do intake conversationally rather than from a form, and every answer it produces is another block in the transcript.

**When the conversation is not in your working language, write both.** The transcript carries what they actually said, and the translation goes beside it — est-scope-extract's citations keep `quote_original` next to `quote` for exactly this reason. Traceability a native speaker cannot verify is not traceability, and a conversation is the one source where the original is destroyed the moment you paraphrase it.

**Never write down something they did not say.** Not as a helpful clarification, not as an obvious implication. If you believe something is needed and they never mentioned it, ask them — and if they confirm it, that answer is now theirs and goes in the transcript in their words. Putting your own professional assumptions into a source document that downstream tooling treats as the client's own is the one failure this whole design exists to make impossible.

## Then hand off

Invoke `est-scope-extract` with `{workspace}/normalized/conversation.md` as the source, telling it the project name, what the estimate is for, and that there is no contractual document. It classifies, checks every quote against the transcript, accounts for coverage and runs its review pass. Then `est-estimate` prices it.

Two things to say when the number comes back, before anyone reacts to it:

**The band will be wide, and that is the tool working.** A conversation has no acceptance criteria, usually no named integrations, no stated NFRs and no data model, so the completeness score is low and the band is computed from it. Nobody can narrow it by being braver. `narrowing_questions` is the follow-up agenda, and on this input it is worth more than the estimate.

**The transcript is now an artefact they can argue with.** Tell them where it lives. A conversation that has become a file is correctable, re-runnable, and citable back to them — which is the point of having written it down.
