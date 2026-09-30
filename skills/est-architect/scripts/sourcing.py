#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Layer 2 — build, adopt, or buy, per capability.

The layer with the strongest numbers in the workflow. The other two score fit and risk; this
one converts into hours, which is this module's home ground: the stories at stake are named
ids with real size bands read from the inventory.

**The ratio applied to them is not measured.** `sourcing_effort` in the architecture model says
so outright, and every basis string this module writes repeats it, because a figure that reads
as an arithmetic result and is actually an assertion is the failure mode this whole module is
built against.

**This script never invents a candidate.** `buy` candidates come from the platform profiles,
which name real services. `adopt` candidates come from research and are passed in. When no
research was supplied the adopt mode is scored `null` and says it was never evaluated, rather
than scoring zero — an unevaluated option and a bad option are not the same claim.

    uv run scripts/sourcing.py <feature-inventory.json> [--estimate e.json] [--candidates c.json]
"""

import argparse
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


caps = _load("capabilities", HERE / "capabilities.py")

MODES = ("build", "adopt", "buy")


def at_stake(entry, inventory):
    """The work this capability represents: the story ids, their bands, and hours if priced."""
    bands = {}
    by_id = {f["id"]: f for f in inventory.get("features") or []}
    for sid in entry["stories"]:
        feature = by_id.get(sid) or {}
        band = ((feature.get("tags") or {}).get("size_band") or {}).get("value")
        bands[sid] = band
    return {"stories": list(entry["stories"]), "bands": bands,
            "hours": entry.get("story_hours"),
            "share_of_backlog": entry.get("share_of_backlog")}


def _effort_units(mode, model, gaps=0):
    """Relative delivery effort. Build is 1.0 by definition; a gap adds work back on top.

    A gap is build work the purchase does not absorb, so it is counted here rather than only
    described in the requirement-fit prose — which is how "it covers most of it" quietly
    becomes a saving nobody delivered.
    """
    effort = model["sourcing_effort"]
    share = float(effort[mode]["share"])
    return share + gaps * float(effort["gap_penalty"]["share"])


def _effort_basis(mode, stake, units, model):
    effort = model["sourcing_effort"]
    n = len(stake["stories"])
    named = ", ".join(stake["stories"][:6]) + ("…" if n > 6 else "")
    size = (f"{stake['hours']:.0f} h" if stake["hours"] else f"{n} stor{'y' if n == 1 else 'ies'}")
    if mode == "build":
        return f"{size} at stake ({named}); the baseline the other modes are relative to"
    return (f"{size} at stake ({named}); {mode} is modelled at {units:.2f} of that — "
            f"an ASSERTED coefficient with no delivered project behind it "
            f"({effort[mode]['why'].split('.')[0].lower()})")


def score_mode(mode, stake, candidate, model):
    """One row of a capability's option table. Every part carries the number it rests on."""
    weights = model["weights"]["sourcing"]
    defaults = model["sourcing_effort"]["mode_defaults"]["build"]
    gaps = len((candidate or {}).get("gaps") or [])
    units = _effort_units(mode, model, gaps)
    parts = {}

    max_units = _effort_units("build", model)
    parts["delivery_effort"] = {
        "score": round(max(0.0, 10.0 * (max_units - units) / max_units), 2),
        "basis": _effort_basis(mode, stake, units, model),
    }

    if mode == "build":
        for key in ("requirement_fit", "maintenance_health", "cost_licence", "escape_cost"):
            parts[key] = {"score": defaults[key], "basis": defaults[f"{key}_why"]}
    elif candidate is None:
        for key in ("requirement_fit", "maintenance_health", "cost_licence", "escape_cost"):
            parts[key] = {"score": None,
                          "basis": f"no {mode} candidate was researched, so this was never "
                                   f"evaluated — not the same claim as a low score"}
    else:
        covers = len(candidate.get("covers") or [])
        total = max(1, len(stake["stories"]))
        parts["requirement_fit"] = {
            "score": round(10.0 * covers / total, 2) if candidate.get("covers") is not None else None,
            "basis": (f"covers {covers} of {total} stories"
                      + (f"; does not do: {'; '.join(candidate['gaps'])}" if gaps else
                         "; no gap recorded")
                      if candidate.get("covers") is not None else
                      "the candidate's coverage was not researched"),
        }
        parts["maintenance_health"] = _health(candidate)
        parts["cost_licence"] = _cost_licence(candidate, mode)
        parts["escape_cost"] = _escape(candidate)

    scored = {k: v for k, v in parts.items() if v["score"] is not None}
    if not scored:
        total_score = None
    else:
        # Renormalise over the parts that HAVE a number, so an unresearched sub-score does not
        # silently drag an option down as though it had scored zero.
        mass = sum(weights[k] for k in scored)
        total_score = round(sum(weights[k] * v["score"] for k, v in scored.items()) / mass, 2)
    for key, part in parts.items():
        part["weight"] = weights[key]
    return {"id": mode, "name": mode, "axis": mode, "score": total_score, "viable": True,
            "parts": parts, "candidate": (candidate or {}).get("name"),
            "unscored_parts": sorted(k for k, v in parts.items() if v["score"] is None)}


def _health(candidate):
    health = candidate.get("health")
    if not health:
        return {"score": None, "basis": "maintenance health was not researched"}
    bits = [f"last release {health['last_release']}" if health.get("last_release") else None,
            f"{health['contributors']} contributors" if health.get("contributors") else None,
            health.get("note")]
    return {"score": health.get("score"),
            "basis": "; ".join(b for b in bits if b) or "researched, no detail recorded"}


def _cost_licence(candidate, mode):
    licence = candidate.get("licence")
    pricing = candidate.get("pricing_model")
    if mode == "adopt":
        if not licence:
            return {"score": None, "basis": "the licence was not researched"}
        blocked = candidate.get("licence_blocked")
        return {"score": 2.0 if blocked else 9.0,
                "basis": (f"{licence}" + (" — incompatible with how this will ship, which is a "
                                          "GATE rather than a low score" if blocked else
                                          ", compatible with a commercial release"))}
    if not pricing:
        return {"score": None, "basis": "the pricing model was not researched"}
    return {"score": 6.0, "basis": f"{pricing}; the figure itself is fetched in the cost "
                                   f"breakdown, never guessed here"}


def _escape(candidate):
    interface = candidate.get("interface")
    if not interface:
        return {"score": None, "basis": "the interface was not researched"}
    standard = interface == "standard"
    return {"score": 8.0 if standard else 3.0,
            "basis": (candidate.get("interface_why")
                      or ("behind a standard interface, so replacing it is a reconnect"
                          if standard else
                          "behind a proprietary interface, so replacing it is a rewrite"))}


def decide(cap_id, entry, inventory, model, candidates):
    """One capability's decision: settled with a reason, or scored across the modes it has."""
    spec = caps.capabilities(model)[cap_id]
    live, why = caps.is_live(cap_id, entry, model)
    if not live:
        settled = spec.get("settled") or {}
        return {"capability": cap_id, "name": spec["name"], "live": False,
                "mode": settled.get("mode", "build"), "source": "settled",
                "why": why, "candidate": None, "options": [],
                "at_stake": at_stake(entry, inventory)}

    stake = at_stake(entry, inventory)
    supplied = (candidates or {}).get(cap_id) or {}
    options = [score_mode("build", stake, None, model)]
    for mode in ("adopt", "buy"):
        options.append(score_mode(mode, stake, supplied.get(mode), model))

    # Only a FULLY EVALUATED option can be recommended. The delivery-effort sub-score
    # structurally favours not building, so an option with four unscored parts and one effort
    # score outranked build on every capability nobody had researched — which is to say the
    # workflow recommended buying things it had never looked at. Build is fully evaluated by
    # definition, so there is always at least one candidate for the recommendation.
    complete = [o for o in options if o["score"] is not None and not o["unscored_parts"]]
    best = max(complete, key=lambda o: o["score"])
    unresearched = [o["id"] for o in options if o["unscored_parts"]]
    why = (f"{best['id']} scores {best['score']} against "
           + ", ".join(f"{o['id']} {o['score'] if o['score'] is not None else 'unscored'}"
                       for o in options if o is not best))
    if unresearched:
        why += (f" — {' and '.join(unresearched)} could not be recommended because no candidate "
                f"was researched, which is a gap in the evidence rather than a verdict on them")
    return {"capability": cap_id, "name": spec["name"], "live": True,
            "mode": best["id"], "source": "scored",
            "candidate": best.get("candidate"),
            "needs_research": unresearched,
            "why": why,
            "options": options, "at_stake": stake}


def build_decisions(cap_map, inventory, model, candidates=None):
    order = list(caps.capabilities(model))
    return [decide(c, cap_map[c], inventory, model, candidates)
            for c in order if c in cap_map]


def balance(decisions, model):
    """The portfolio view. No target ratio is asserted; the distribution is made visible and
    the degenerate ends raise a finding the report has to answer."""
    rule = model["balance"]
    live = [d for d in decisions if d["live"]]
    # LIVE decisions only. Counting the settled defaults made the bought share 83% on every
    # backlog — nobody chose to buy a CDN, and a finding that fires every time is noise that
    # trains a reader to skip it.
    counts = {m: sum(1 for d in live if d["mode"] == m) for m in MODES}
    total = max(1, sum(counts.values()))
    avoided = sorted({s for d in live if d["mode"] in ("adopt", "buy")
                      for s in d["at_stake"]["stories"]})
    findings = []
    if counts["build"] / total > rule["flag_all_build_above"]:
        findings.append({"kind": "all_build",
                         "detail": f"{counts['build']} of {total} capabilities are built "
                                   f"({counts['build']/total:.0%}). A mature candidate has "
                                   f"almost certainly not been scored against.",
                         "why": rule["why"]})
    bought = (counts["adopt"] + counts["buy"]) / total
    if bought > rule["flag_all_buy_above"]:
        findings.append({"kind": "all_buy",
                         "detail": f"{counts['adopt'] + counts['buy']} of {total} capabilities "
                                   f"are adopted or bought ({bought:.0%}). The integration glue "
                                   f"is likely to cost more than building would have.",
                         "why": rule["why"]})
    return {"build": counts["build"], "adopt": counts["adopt"], "buy": counts["buy"],
            "live_decisions": len(live), "settled": len(decisions) - len(live),
            "counted": f"{total} live decision(s); {len(decisions) - len(live)} settled "
                       f"capabilities are excluded because nobody chose them",
            "stories_avoided": avoided,
            "vendors_added": 0,          # Layer 3 fills this: sourcing says buy, it says from whom
            "findings": findings}


def confirmation_batch(decisions):
    """One table, every live capability, accepted wholesale or corrected selectively.

    Not a queue: asking one at a time produces rubber-stamping exactly where accuracy matters
    most, and a dozen capabilities asked in sequence is a dozen chances to stop reading.
    """
    rows = ["| Capability | Work at stake | Recommended | Why | Change to |",
            "| --- | --- | --- | --- | --- |"]
    for d in decisions:
        if not d["live"]:
            continue
        stake = d["at_stake"]
        size = (f"{stake['hours']:.0f} h" if stake["hours"]
                else f"{len(stake['stories'])} stories")
        rows.append(f"| {d['name']} | {size} ({', '.join(stake['stories'][:4])}"
                    f"{'…' if len(stake['stories']) > 4 else ''}) | **{d['mode']}**"
                    f"{' — ' + d['candidate'] if d['candidate'] else ''} | {d['why']} | |")
    settled = [d for d in decisions if not d["live"]]
    body = "\n".join(rows)
    if settled:
        body += ("\n\nSettled without scoring, each with its reason:\n\n"
                 + "\n".join(f"- **{d['name']}** → {d['mode']} — {d['why']}" for d in settled))
    return body


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inventory")
    ap.add_argument("--estimate")
    ap.add_argument("--candidates", help="researched adopt/buy candidates, keyed by capability")
    ap.add_argument("--model")
    ap.add_argument("-o", "--output")
    args = ap.parse_args()

    inventory = json.loads(Path(args.inventory).read_text(encoding="utf-8"))
    estimate = (json.loads(Path(args.estimate).read_text(encoding="utf-8"))
                if args.estimate else None)
    candidates = (json.loads(Path(args.candidates).read_text(encoding="utf-8"))
                  if args.candidates else None)
    model = caps.load_model(args.model)
    cap_map = caps.build_map(inventory, model, estimate)
    decisions = build_decisions(cap_map, inventory, model, candidates)
    out = {"decisions": decisions, "confirmed": False,
           "balance": balance(decisions, model),
           "batch": confirmation_batch(decisions)}
    text = json.dumps(out, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
