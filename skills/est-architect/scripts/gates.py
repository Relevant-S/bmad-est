#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""The three verification gates: stack, sourcing, platform set.

Each layer is scored, presented, and **waits**. This is what the workflow is for — the brief was
"propose several options, score each 0–10 with reasoning, and wait for me to verify" — and the
first real run honoured it for exactly one of the three. The stack choice, which reversed a
PRD's stated stack and invalidated a priced estimate, and a seven-vendor platform set were
decided and reported rather than verified.

A gate renders the options with every sub-score and the number it rests on, names what the
operator is actually choosing between, and refuses to let the next layer run until it is
confirmed — because each layer constrains the next and scoring against a decision that is about
to change is wasted work.

Two rules the gates enforce that the first run got wrong:

  * **A counter-proposal is the model's, not the operator's.** When the workflow disagrees with
    its own scoring it must say so in its own name. A run logged its two counter-proposals as
    "operator corrections" because the operator had ticked a box labelled `(Recommended)`.
  * **A contradicted source is called out.** If the winning stack differs from one the inventory
    records as the working assumption, that invalidates any estimate priced on it, and the
    operator has to be told at the moment of choosing rather than in a footnote afterwards.
"""

import re

ORDER = ("stack", "sourcing", "platform")
# Broad, for RECOGNISING that a passage is describing a stack at all.
STACK_WORDS = re.compile(
    r"\b(stack|django|rails|laravel|spring|next\.?js|nuxt|react|vue|svelte|angular|htmx|"
    r"alpine\.?js|node|python|typescript|golang|\.net|php|java|ruby|celery|bullmq|sidekiq|"
    r"postgres|postgresql|mysql|mongo|redis)\b", re.I)

# Narrow, for deciding whether two stacks are DIFFERENT. Languages, frameworks and job
# runners only — never datastores. Django-on-Postgres and Next.js-on-Postgres share a
# database and nothing else, and comparing on the broad list let a complete reversal of the
# application stack pass unflagged because both sides said "postgres".
DECIDING_WORDS = re.compile(
    r"\b(django|rails|laravel|spring|next\.?js|nuxt|react|vue|svelte|angular|htmx|"
    r"alpine\.?js|node|python|typescript|golang|\.net|php|java|ruby|celery|bullmq|sidekiq)\b",
    re.I)


def stated_stack(inventory):
    """What the sources say the stack is, quoted, from the inventory's own records.

    Reads `assumptions` and `conflicts` rather than guessing: those are where an extraction puts
    a stack the client prescribed, and they carry the operator's own wording.
    """
    out = []
    for assumption in inventory.get("assumptions") or []:
        text = assumption if isinstance(assumption, str) else (
            assumption.get("text") or assumption.get("assumption") or "")
        if text and STACK_WORDS.search(text):
            out.append({"kind": "assumption", "text": text.strip()})
    for conflict in inventory.get("conflicts") or []:
        topic = (conflict.get("topic") or "") if isinstance(conflict, dict) else ""
        text = (conflict.get("detail") or conflict.get("description") or ""
                ) if isinstance(conflict, dict) else str(conflict)
        if STACK_WORDS.search(topic) or "stack" in topic.lower():
            out.append({"kind": "conflict", "topic": topic, "text": text.strip()})
    return out


# A recommendation is a reversal when it shares less than this much of its identity with the
# stack the sources record. Not "shares nothing": a recorded assumption routinely mentions the
# alternative it rejected, and one passing mention of Next.js inside a paragraph choosing
# Django was enough to suppress the flag entirely on the first real backlog.
AGREEMENT_THRESHOLD = 0.5


def contradicts(option, inventory):
    """Whether the winning stack is not the one the inventory records as assumed.

    Measured as the share of the RECOMMENDED stack's own languages and frameworks that the
    recorded decision actually names. Django + DRF + Celery against a recorded Django stack
    agrees on most of itself; Next.js + React + TypeScript + BullMQ agrees on at most the one
    word the paragraph used to name what it was rejecting.
    """
    records = stated_stack(inventory)
    if not records or not option:
        return None
    # Only ASSUMPTIONS decide this. An assumption is a decision taken and reversing it has a
    # cost; a conflict is a decision outstanding, and a conflict record names BOTH candidate
    # stacks — so comparing against it, everything overlaps with everything and a complete
    # reversal passes unflagged. That is exactly what happened on the first real backlog.
    decided = [r for r in records if r["kind"] == "assumption"]
    if not decided:
        return None
    blob = " ".join(r["text"] + " " + r.get("topic", "") for r in decided).lower()
    named = {w.lower().replace(".", "") for w in DECIDING_WORDS.findall(blob)}
    mine = {t.lower().replace(".", "")
            for t in option.get("detail", {}).get("technologies") or []}
    mine = {t for t in mine if DECIDING_WORDS.fullmatch(t) or DECIDING_WORDS.search(t)}
    if not named or not mine:
        return None
    overlap = {m for m in mine if any(m in n or n in m for n in named)}
    agreement = len(overlap) / len(mine)
    if agreement >= AGREEMENT_THRESHOLD:
        return None
    return {"records": decided, "chosen": sorted(mine), "recorded": sorted(named),
            "agreement": round(agreement, 2), "shared": sorted(overlap)}


def _parts_table(option):
    rows = ["| Sub-score | Score | Weight | Rests on |", "| --- | --- | --- | --- |"]
    for name, part in (option.get("parts") or {}).items():
        score = "—" if part.get("score") is None else f"{part['score']:g}"
        rows.append(f"| {name.replace('_', ' ')} | {score} | {part.get('weight', 0):g} | "
                    f"{part.get('basis', '')} |")
    return "\n".join(rows)


def _options_table(layer, extra=()):
    head = ["| Option | Varies | Score | Viable |" + "".join(f" {e} |" for e in extra),
            "| --- | --- | --- | --- |" + "".join(" --- |" for _ in extra)]
    for option in layer.get("options") or []:
        mark = "yes" if option.get("viable") else "**no**"
        score = "—" if option.get("score") is None else f"{option['score']:g}"
        row = (f"| {option['name']} | {option.get('axis', '')} | {score} | {mark} |")
        for key in extra:
            part = (option.get("parts") or {}).get(key.lower().replace(" ", "_")) or {}
            row += f" {'—' if part.get('score') is None else format(part['score'], 'g')} |"
        head.append(row)
    return "\n".join(head)


def stack_gate(architecture, inventory):
    layer = architecture["layers"]["stack"]
    chosen = next((o for o in layer.get("options") or []
                   if o["id"] == layer.get("chosen")), None)
    out = ["# Gate 1 of 3 — the technology stack", "",
           "Nothing proceeds until you confirm or correct this. The stack constrains which "
           "open-source candidates exist for the next layer, and which platforms can run the "
           "result.", "", _options_table(layer, extra=("Scope fit", "Team fit")), "",
           f"**Recommended: {chosen['name'] if chosen else 'none'}** — "
           f"{layer.get('chosen_why', '')}", ""]

    clash = contradicts(chosen, inventory)
    if clash:
        out += ["> ### This reverses what the sources say", "",
                "> The inventory records a different stack as the working assumption:", ""]
        out += [f"> - *{r['kind']}*: {r['text'][:400]}" for r in clash["records"]]
        out += ["",
                f"> The recommendation is **{', '.join(clash['chosen'])}**, against the recorded "
                f"**{', '.join(clash['recorded'])}** — they share "
                f"{'nothing' if not clash['shared'] else ', '.join(clash['shared'])}"
                f" ({clash['agreement']:.0%} of the recommendation). Any estimate already priced "
                f"on the recorded stack is priced on a different design and should be re-run. "
                f"That is a commercial consequence, not a technical one, which is why it is here "
                f"rather than in a footnote.", ""]

    for option in layer.get("options") or []:
        out += [f"## {option['name']}", "", _parts_table(option), ""]
        for dead in option.get("not_viable_because") or []:
            out.append(f"> **Not viable** — {dead['detail']}")
        for unknown in option.get("unevaluated_gates") or []:
            out.append(f"> **Could not be evaluated** — {unknown['detail']}")
        out.append("")
    out += ["---", "",
            "Re-run with `--stack-confirmed` to continue, optionally with "
            "`--inputs` carrying a different `stack_choice`.", ""]
    return "\n".join(out)


def sourcing_gate(architecture):
    layer = architecture["layers"]["sourcing"]
    balance = layer.get("balance") or {}
    out = ["# Gate 2 of 3 — build, adopt or buy", "",
           "One table, every live capability, accepted wholesale or corrected selectively. Not "
           "a queue: asking one at a time produces rubber-stamping exactly where accuracy "
           "matters most.", "",
           f"**Balance** — {balance.get('build', 0)} built, {balance.get('adopt', 0)} adopted, "
           f"{balance.get('buy', 0)} bought across {balance.get('live_decisions', 0)} live "
           f"decisions. {balance.get('counted', '')}", ""]
    for finding in balance.get("findings") or []:
        out += [f"> **{finding['kind']}** — {finding['detail']}", "",
                "> This is a question the report has to answer, not an error. Say why the "
                "distribution is right, or change it here.", ""]
    out += [layer.get("batch") or "", ""]

    counters = [d for d in layer.get("decisions") or [] if d.get("model_counter_proposal")]
    if counters:
        out += ["## Where the workflow disagrees with its own scoring", "",
                "These are **the workflow's proposals, not yours.** Ticking them makes them "
                "yours; the record will say you were the one who changed it.", ""]
        out += [f"- **{d['name']}** — scored `{d.get('scored_mode')}`, proposed "
                f"`{d['mode']}`: {d.get('counter_why', '')}" for d in counters]
        out.append("")
    out += ["---", "",
            "Re-run with `--sourcing-confirmed`, and `--inputs` carrying `sourcing_overrides` "
            "for any capability you want changed.", ""]
    return "\n".join(out)


def platform_gate(architecture):
    layer = architecture["layers"]["platform"]
    out = ["# Gate 3 of 3 — where it runs", "",
           "A set may combine platforms; that is often the right answer. What it may not do is "
           "grow a vendor per capability, which is what the sprawl sub-score measures.", "",
           _options_table(layer, extra=("Vendor sprawl", "Runtime fit", "Reversibility")), "",
           f"**Recommended:** {layer.get('chosen_why', '')}", ""]
    for gap in architecture.get("catalogue_gaps") or []:
        out.append(f"> **Catalogue gap** — {gap['detail']}")
    if architecture.get("catalogue_gaps"):
        out.append("")
    for option in layer.get("options") or []:
        out += [f"## {option['name']}", "", _parts_table(option), ""]
        if option.get("variants"):
            out += [f"Tied variants, differing in "
                    f"{', '.join(option.get('variants_differ_in') or [])}: "
                    + "; ".join(v["name"] for v in option["variants"]), ""]
        for dead in option.get("not_viable_because") or []:
            out.append(f"> **Not viable** — {dead['detail']}")
        for unknown in option.get("unevaluated_gates") or []:
            out.append(f"> **Could not be evaluated** — {unknown['detail']}")
        out.append("")
    refusals = [r for r in architecture.get("refusals") or [] if r["kind"] == "vendor"]
    if refusals:
        out += ["## Vendors refused", ""]
        out += [f"- **{r['what']}** — {r['why']}" for r in refusals] + [""]
    out += ["---", "", "Re-run with `--platform-confirmed` to continue to the diagram and the "
            "cost breakdown.", ""]
    return "\n".join(out)


def render(layer, architecture, inventory=None):
    if layer == "stack":
        return stack_gate(architecture, inventory or {})
    if layer == "sourcing":
        return sourcing_gate(architecture)
    return platform_gate(architecture)


def pending(architecture):
    """The first gate not yet confirmed, or None when all three are."""
    for layer in ORDER:
        if not (architecture["layers"].get(layer) or {}).get("confirmed"):
            return layer
    return None
