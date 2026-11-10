#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Design an architecture for a priced-or-not-yet-priced Feature Inventory.

Three layers, scored in order because each constrains the next:

    Layer 1  stack         language, frameworks, libraries, tooling
    Layer 2  sourcing      per capability: build / adopt open-source / buy managed
    Layer 3  platform set  capability -> platform, possibly several platforms

Layer 2 lives in `sourcing.py` and stops for the operator before Layer 3 runs: the platform
layer's input is the set of capabilities that still need somewhere to run, and binding
platforms to sourcing that is about to change is wasted work.

Nothing here invents a candidate. Stack options and open-source candidates are researched and
passed in; managed services come from the platform profiles, which name real products. A mode
or a sub-score with no evidence behind it scores `null` and says so — an unevaluated option and
a bad option are not the same claim, and this module has no business making them look alike.

    uv run scripts/architect.py <feature-inventory.json> -o architecture.json \\
        [--estimate estimate.json] [--stacks stacks.json] [--candidates candidates.json] \\
        [--inputs inputs.json] [--preferences architecture-preferences.md]

Exit 0 when every gate is confirmed and a viable combination exists, 1 when none is viable,
2 when the audit fails, **3 when a gate is waiting on the operator** — which is the normal
outcome of the first three invocations, not an error.
"""

import argparse
import datetime as dt
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
sourcing = _load("sourcing", HERE / "sourcing.py")
preferences = _load("preferences", HERE / "preferences.py")
check = _load("architecture_check", HERE / "architecture-check.py")
gates = _load("gates", HERE / "gates.py")

NOVELTY_MULTIPLIER = 1.15      # cost-model.json novelty_rework_multiplier.novel.multiplier


# ---------------------------------------------------------------- gates

def evaluate_gates(constraints, subject, platforms=None):
    """Hard constraints against one option. Returns (failed, unevaluated).

    A gate whose evidence has never been verified is **unevaluated** — not passed and not
    failed. A platform profile shipping `certifications: {value: null, checked: null}` has not
    said the platform lacks the certification; it has said nobody looked. Treating that as a
    pass would put an unchecked compliance claim behind a recommendation, and treating it as a
    fail would silently drop every candidate on every project.
    """
    failed, unevaluated = [], []
    for c in constraints or []:
        kind, detail = c["kind"], c.get("detail", "")
        if kind == "mandated_platform":
            used = set(subject.get("platforms") or [])
            if used and detail not in used:
                failed.append({"constraint": c["id"], "kind": kind,
                               "detail": f"{detail} is mandated and this set uses "
                                         f"{', '.join(sorted(used))}"})
        elif kind == "excluded_platform":
            if detail in set(subject.get("platforms") or []):
                failed.append({"constraint": c["id"], "kind": kind,
                               "detail": f"{detail} is excluded and this set uses it"})
        elif kind in ("data_residency", "certification"):
            field = "residency" if kind == "data_residency" else "certifications"
            for pid in subject.get("platforms") or []:
                entry = ((platforms or {}).get(pid, {}).get("volatile") or {}).get(field) or {}
                if entry.get("checked") is None:
                    unevaluated.append({
                        "constraint": c["id"], "kind": kind, "platform": pid,
                        "detail": f"{pid}'s `{field}` has never been verified by this "
                                  f"installation, so `{detail}` could not be evaluated against "
                                  f"it. Research and date the profile field before quoting this "
                                  f"option against a {kind.replace('_', ' ')} requirement."})
                elif detail.lower() not in str(entry.get("value", "")).lower():
                    failed.append({"constraint": c["id"], "kind": kind,
                                   "detail": f"{pid} does not record {detail}"})
    return failed, unevaluated


def _compose(parts, weights):
    """Weighted mean over the parts that HAVE a number.

    Renormalising rather than treating an unscored part as zero: "we did not look" must not
    read as "we looked and it was bad".
    """
    scored = {k: v for k, v in parts.items() if v.get("score") is not None}
    for key, part in parts.items():
        part["weight"] = weights.get(key, 0.0)
    if not scored:
        return None
    mass = sum(weights.get(k, 0.0) for k in scored) or 1.0
    return round(sum(weights.get(k, 0.0) * v["score"] for k, v in scored.items()) / mass, 2)


# ---------------------------------------------------------------- Layer 1: the stack

def stack_profile(option, inventory):
    """Which `stack` value est-estimate should price against, and why.

    This is a real coupling and a narrow one: `estimate.py` reads `spec["stacks"]` on each
    standing-work item and switches items on. It is not a multiplier and must never be
    described as one.
    """
    if option.get("mobile"):
        return "mobile_plus_backend", ("the design has a mobile client alongside the backend, "
                                       "which switches on the mobile standing-work items")
    services = int(option.get("deployable_services") or 1)
    if services > 1:
        return "multi_service", (f"{services} independently deployable services, which switches "
                                 f"on the multi-service standing-work items (a pipeline and an "
                                 f"environment set per service)")
    return "standard_saas", "one deployable service, so the default standing-work set applies"


def score_stack(option, cap_map, inventory, model, constraints, prefs, cost_model=None):
    weights = model["weights"]["stack"]
    features = [f for f in inventory.get("features") or []
                if f.get("origin") != "standing" and f.get("epic_id")]
    total = len(features) or 1
    parts = {}

    gapped = sorted({s for gap in option.get("gaps") or [] for s in gap.get("stories") or []})
    parts["scope_fit"] = {
        "score": round(10.0 * (total - len(gapped)) / total, 2),
        "basis": (f"{total - len(gapped)} of {total} stories served natively"
                  + (f"; {', '.join(gapped)} need an escape hatch — "
                     + "; ".join(g["why"] for g in option.get("gaps") or [])
                     if gapped else "; no story needs an escape hatch")),
    }

    libraries = option.get("libraries")
    if libraries is None:
        parts["library_coverage"] = {"score": None,
                                     "basis": "the libraries this scope needs were not researched"}
    else:
        wanted = [c for c in cap_map if c not in ("application", "web_client")]
        have = [c for c in wanted if libraries.get(c)]
        missing = [c for c in wanted if not libraries.get(c)]
        parts["library_coverage"] = {
            "score": round(10.0 * len(have) / max(1, len(wanted)), 2),
            "basis": (f"{len(have)} of {len(wanted)} capabilities have a named library"
                      + (f"; none found for {', '.join(missing)}" if missing else "")),
        }

    currency = option.get("currency") or {}
    parts["ecosystem_currency"] = (
        {"score": float(currency["score"]),
         "basis": f"{currency.get('note') or 'researched'} (checked {currency.get('checked')})"}
        if currency.get("score") is not None and currency.get("checked")
        else {"score": None,
              "basis": "ecosystem currency was not researched, or was researched without a date "
                       "— an undated claim about a framework's state is not evidence"})

    technologies = option.get("technologies") or []
    known = [t for t in technologies if preferences.knows(prefs, t)]
    unknown = [t for t in technologies if preferences.knows(prefs, t) is False]
    if preferences.knows(prefs, technologies[0] if technologies else "") is None:
        parts["team_fit"] = {"score": None,
                             "basis": "architecture-preferences.md is UNANSWERED, so no "
                                      "technology here has a delivered project behind it that "
                                      "this installation can see"}
    else:
        parts["team_fit"] = {
            "score": round(10.0 * len(known) / max(1, len(technologies)), 2),
            "basis": (f"{len(known)} of {len(technologies)} technologies have a delivered "
                      f"project behind them"
                      + (f"; no delivered project for {', '.join(unknown)}" if unknown else "")),
        }

    profile, profile_why = stack_profile(option, inventory)
    novel = bool(unknown) if parts["team_fit"]["score"] is not None else None
    impact_score = 10.0 if profile == "standard_saas" else 8.5
    impact_basis = [f"implies stack profile `{profile}` — {profile_why}"]
    if novel is True:
        impact_score = round(impact_score / NOVELTY_MULTIPLIER, 2)
        impact_basis.append(f"unfamiliar to this company ({', '.join(unknown)}), which the cost "
                            f"model prices at {NOVELTY_MULTIPLIER}x on every story total and "
                            f"1.6x on the rework share")
    elif novel is None:
        impact_basis.append("novelty could not be assessed — architecture-preferences.md is "
                            "UNANSWERED, so this score covers the standing-work effect only")
    else:
        impact_basis.append("every technology has a delivered project behind it, so no story "
                            "becomes `novel` on account of the stack")
    parts["estimate_impact"] = {"score": impact_score, "basis": "; ".join(impact_basis)}

    failed, unevaluated = evaluate_gates(constraints, {"platforms": []})
    return {"id": option["id"], "name": option["name"],
            "axis": option.get("axis") or "unstated",
            "score": _compose(parts, weights), "parts": parts,
            "viable": not failed, "not_viable_because": failed,
            "unevaluated_gates": unevaluated,
            "detail": {"technologies": technologies, "stack_profile": profile,
                       "stack_profile_why": profile_why, "novel": novel,
                       "novel_technologies": unknown,
                       "unscored_parts": sorted(k for k, v in parts.items()
                                                if v["score"] is None)}}


# ---------------------------------------------------------------- Layer 3: the platform set

def needs_platform(decisions, model):
    """Which capabilities need somewhere to run, and why.

    `build` capabilities are part of the application and need no binding of their own; the
    application runtime is what they need, and that is a capability in its own right.
    """
    out = {}
    for d in decisions:
        cap = d["capability"]
        if cap in ("application", "web_client"):
            out[cap] = "the project's own code has to run somewhere"
        elif d["mode"] == "buy":
            out[cap] = "bought, so a vendor has to provide it"
        elif d["mode"] == "adopt" and (d.get("self_run") or False):
            out[cap] = "adopted and self-run, so it needs a host"
    return out


def runtime_needs(decisions):
    """What the application tier must actually be able to do, derived rather than assumed."""
    needs = {}
    for d in decisions:
        if d["capability"] == "async_work" and d["mode"] in ("build", "adopt"):
            needs["long_running"] = ("async work is built or self-run here, so the runtime has "
                                     "to hold a process open")
            needs["background_jobs"] = "queued work outside a request"
    return needs


def allowed_platforms(platforms, constraints):
    """The candidate pool after the hard platform gates.

    An excluded platform is removed BEFORE enumeration rather than after. Building sets out of
    it and letting the gate kill them afterwards left a project with an excluded provider no
    viable set at all — every candidate had quietly pulled the banned platform in to cover one
    capability, and the run reported "no viable platform set" on a backlog three vendors could
    serve comfortably.
    """
    excluded = {c["detail"] for c in constraints or [] if c["kind"] == "excluded_platform"}
    mandated = {c["detail"] for c in constraints or [] if c["kind"] == "mandated_platform"}
    pool = {p: v for p, v in platforms.items() if p not in excluded}
    missing = sorted(mandated - set(pool))
    return pool, sorted(excluded & set(platforms)), missing


def apply_sourcing_overrides(decisions, overrides, candidates):
    """The operator's corrections to the confirmation batch.

    `overrides` is `{capability: {"mode": ..., "why": ...}}`. The scored answer is kept beside
    the operator's (`scored_mode`, `scored_candidate`) so the record shows where a human
    overruled the model and why, rather than the scores being edited until they agreed.

    Why it keeps both: `--sourcing-confirmed` used to be a single flag with no way to carry a
    selective correction, so the only way to record a human overruling the model was to edit the
    scores until they agreed. The scored answer and the chosen one are different facts and the
    record has to hold both.
    """
    for d in decisions:
        rule = (overrides or {}).get(d["capability"])
        if not rule or not d["live"]:
            continue
        mode = rule["mode"]
        supplied = ((candidates or {}).get(d["capability"]) or {}).get(mode) or {}
        d["scored_mode"], d["scored_candidate"] = d["mode"], d.get("candidate")
        d["mode"] = mode
        d["candidate"] = supplied.get("name") if mode != "build" else None
        d["source"] = "operator"
        d["why"] = (f"operator chose {mode}"
                    + (f" — {d['candidate']}" if d["candidate"] else "")
                    + f" over the scored {d['scored_mode']}: {rule.get('why', 'no reason recorded')}."
                    + f" Scores: {d['why']}")
    return decisions


def apply_counter_proposals(decisions, proposals):
    """Where the workflow disagrees with its own scoring, in its own name.

    A counter-proposal does NOT change the decision — the scored answer stands until a human
    changes it. It is marked so the gate can present it as *the workflow's* proposal.

    A real run put two of its own proposals behind an option labelled `(Recommended)`, the
    operator ticked it, and the log recorded them as operator corrections. Both facts were true
    and the record told only one of them.
    """
    for d in decisions:
        rule = (proposals or {}).get(d["capability"])
        if not rule or not d.get("live"):
            continue
        d["model_counter_proposal"] = True
        d["scored_mode"] = d["mode"]
        d["proposed_mode"] = rule["mode"]
        d["counter_why"] = rule.get("why") or "no reason recorded"
    return decisions


def pinned_bindings(decisions, candidates, pool):
    """Capabilities whose Layer 2 decision already named the vendor.

    A `buy` decision for a candidate carrying `platform: <profile id>` binds that capability to
    that platform before the greedy fill runs. Without this, buying Clerk for identity drew
    Amazon Cognito on the diagram whenever AWS sorted ahead of Clerk in the fill.

    Layer 2 chooses the vendor; Layer 3 used to re-choose it. Buying Clerk for identity drew
    Amazon Cognito on the diagram whenever AWS sorted ahead of Clerk in the fill — the two
    layers disagreeing about a decision one of them had already made.
    """
    out = {}
    for d in decisions:
        if d["mode"] != "buy":
            continue
        pid = (((candidates or {}).get(d["capability"]) or {}).get("buy") or {}).get("platform")
        if pid and pid in pool and caps.serves_natively(pool[pid], d["capability"]):
            out[d["capability"]] = pid
    return out


def enumerate_sets(needed, platforms, model, house, mandated=(), pinned=None):
    """Candidate platform sets, one per plausible primary, filled greedily.

    Deterministic on purpose: the same inventory produces the same candidates every run, so two
    readings of one project can be compared. The greedy fill is what produces COMBINATIONS —
    a PaaS that serves six capabilities and a BaaS that serves seven will not cover a backlog
    between them without a third, and the set that results is the honest answer rather than a
    single vendor chosen because the enumeration could not express anything else.
    """
    order = sorted(platforms)
    # A capability NO profile in the catalogue serves is a gap in the catalogue, not a gap in
    # any one set. Reported separately and kept out of every set's coverage denominator:
    # otherwise a missing Stripe profile reads as a flaw in AWS, and penalises every candidate
    # identically while telling the reader nothing they can act on.
    unservable = sorted(c for c in needed
                        if not any(caps.serves_natively(platforms[p], c) for p in order))
    needed = {c: why for c, why in needed.items() if c not in unservable}
    primaries = [p for p in order
                 if caps.serves_natively(platforms[p], "application")
                 or caps.serves_natively(platforms[p], "web_client")]
    sets = []
    # Each primary is tried alone and with each other platform as a preferred second. Without
    # this, a platform serving nearly everything absorbed every leftover in every set and a
    # combination such as Vercel + Supabase could not be enumerated at all — which makes
    # "hosting is open" an unanswerable question rather than a scored one.
    seeds = [(p, q) for p in primaries for q in [None] + [x for x in order if x != p]]
    for primary, second in seeds:
        binding, used = {}, []
        remaining = dict(needed)
        # A capability whose sourcing decision already named its vendor is bound before the fill
        # runs. Layer 2 chose it; Layer 3 has no business choosing again.
        for cap, pid in (pinned or {}).items():
            if cap in remaining:
                binding[cap] = pid
                remaining.pop(cap)
                if pid not in used:
                    used.append(pid)

        def take(pid):
            profile = platforms[pid]
            covered = [c for c in remaining if caps.serves_natively(profile, c)]
            if not covered:
                return False
            if pid not in used:
                used.append(pid)
            for cap in covered:
                binding[cap] = pid
                remaining.pop(cap)
            return True

        # The head is deliberate and is taken in order; the rest is filled by the platform
        # covering the MOST remaining capabilities — which is what platform-binding.md has always
        # documented. The code took the alphabetically first platform covering anything, so the
        # broadest vendor swept up every leftover purely because of its name.
        for pid in [x for x in (primary, second) if x]:
            take(pid)
        while remaining:
            def reach(pid):
                return sum(1 for c in remaining if caps.serves_natively(platforms[pid], c))
            best = max(order, key=lambda pid: (reach(pid),
                                               pid in used,
                                               pid in (house or []),
                                               pid))
            if not reach(best):
                break
            take(best)

        if not binding:
            continue
        # A mandated platform has to be IN the set, not merely not-excluded. A set that cannot
        # reach it is dropped here rather than scored and then refused, so the options a reader
        # sees are the ones they could actually choose.
        if mandated and not set(mandated) <= set(binding.values()):
            continue
        key = tuple(sorted(binding.items()))
        if any(s["key"] == key for s in sets):
            continue
        sets.append({"key": key, "primary": primary, "binding": binding,
                     "platforms": sorted(set(binding.values())),
                     "uncovered": sorted(remaining), "unservable": unservable})
    # Stable ordering: house platforms first, then fewest vendors, then alphabetical.
    sets.sort(key=lambda s: (0 if s["primary"] in (house or []) else 1,
                             len(s["platforms"]), s["primary"]))
    return sets, unservable


def score_platform_set(pset, needed, platforms, model, constraints, decisions, prefs):
    needed = {c: w for c, w in needed.items() if c not in (pset.get("unservable") or [])}
    weights = model["weights"]["platform"]
    parts = {}
    binding = pset["binding"]

    covered, missing = len(binding), pset["uncovered"]
    parts["capability_coverage"] = {
        "score": round(10.0 * covered / max(1, len(needed)), 2),
        "basis": (f"{covered} of {len(needed)} capabilities that need a home are served"
                  + (f"; nothing in this set serves {', '.join(missing)}" if missing else "")),
    }

    wants = runtime_needs(decisions)
    # The long-running requirement comes from the async work, so it is checked where the async
    # work is bound. Checking only the application host scored "Next.js on Vercel + a BullMQ
    # worker on Heroku" at 0 for a process that never runs on Vercel.
    host_id = binding.get("async_work") or binding.get("application") or pset["primary"]
    host = platforms.get(host_id, {})
    runtime = host.get("runtime") or {}
    unmet = [(k, why) for k, why in wants.items() if not runtime.get(k)]
    parts["runtime_fit"] = {
        "score": round(10.0 * (len(wants) - len(unmet)) / max(1, len(wants)), 2) if wants else 10.0,
        "basis": (f"{host.get('name', pset['primary'])} runs the long-running tier; "
                  + ("; ".join(f"cannot do {k}: {why}" for k, why in unmet) if unmet
                     else f"meets all {len(wants)} runtime requirement(s) the sourcing "
                          f"decisions imply" if wants
                     else "no sourcing decision imposes a runtime requirement")),
    }

    vendors = pset["platforms"]
    unique = {pid: [c for c, p in binding.items() if p == pid] for pid in vendors}
    existing = {x.lower() for x in (prefs.get("existing_subscriptions") or [])}
    live_caps = {d["capability"] for d in decisions if d.get("live")}
    # A vendor the project CHOSE, against one a settled capability forced on it. Payments are
    # Stripe and email is a deliverability vendor whoever you are; charging a set for those
    # punishes it for decisions nobody made. `balance()` was corrected for exactly this and
    # this term was not.
    chosen = [p for p in vendors
              if any(c in live_caps for c in unique[p]) and p.lower() not in existing]
    forced = [p for p in vendors if p not in chosen]
    decay = float(model.get("vendor_sprawl", {}).get("decay", 0.75))
    parts["vendor_sprawl"] = {
        "score": round(10.0 * (decay ** max(0, len(chosen) - 1)), 2) if chosen else 10.0,
        "basis": (f"{len(chosen)} vendor(s) this set chose"
                  + (": " + "; ".join(f"{p} for {', '.join(unique[p])}" for p in chosen)
                     if chosen else "")
                  + (f". {len(forced)} more are forced by settled capabilities and are not "
                     f"counted against it ({', '.join(forced)})" if forced else "")
                  + ". Each chosen vendor is another account, another bill, another SLA and "
                    "another data-processing agreement"),
    }

    self_run = [c for c, p in binding.items()
                if not ((platforms[p].get("serves") or {}).get(c) or {}).get("managed", True)]
    parts["operational_burden"] = {
        "score": round(max(0.0, 10.0 - 2.0 * len(self_run)), 2),
        "basis": (f"{len(self_run)} component(s) this team operates itself"
                  + (f": {', '.join(self_run)}" if self_run else
                     " — every bound capability is run by its platform")
                  + ". A count of people-cost, not money; the money is the cost breakdown's job"),
    }

    standard = [c for c, p in binding.items()
                if ((platforms[p].get("serves") or {}).get(c) or {}).get("interface") == "standard"]
    locked = [c for c in binding if c not in standard]
    parts["reversibility"] = {
        "score": round(10.0 * len(standard) / max(1, len(binding)), 2),
        "basis": (f"{len(standard)} of {len(binding)} bindings sit behind a standard interface"
                  + (f"; {', '.join(locked)} would have to be re-bound" if locked else "")),
    }

    failed, unevaluated = evaluate_gates(constraints, {"platforms": vendors}, platforms)
    parts["constraint_compliance"] = {
        "score": 0.0 if failed else (None if unevaluated else 10.0),
        "basis": ("; ".join(f["detail"] for f in failed) if failed
                  else "; ".join(u["detail"] for u in unevaluated) if unevaluated
                  else f"{len(constraints or [])} hard constraint(s) evaluated, none violated"),
    }

    return {"id": "+".join(vendors), "name": " + ".join(platforms[p]["name"] for p in vendors),
            "axis": f"{platforms[pset['primary']].get('kind', '?')}-first",
            "score": _compose(parts, weights), "parts": parts,
            "viable": not failed, "not_viable_because": failed,
            "unevaluated_gates": unevaluated,
            "detail": {"binding": binding, "platforms": vendors,
                       "primary": pset["primary"], "uncovered": missing,
                       "unservable": pset.get("unservable") or [],
                       "unscored_parts": sorted(k for k, v in parts.items()
                                                if v["score"] is None)}}


def collapse_ties(options):
    """Fold sets that score the same into one option carrying its variants.

    With a broad catalogue the enumeration produces many sets that differ in a single slot and
    score identically — thirty-three options, eight of them tied, is noise rather than a
    landscape, and it hides the real choice instead of showing it. A real run had to explain
    this in prose after the fact: "three variants tied at 7.64, differing only in the CDN
    vendor". Saying it in the table is better than saying it in a footnote.

    The representative is the first in the existing deterministic order; the others are recorded
    as `variants` with the capabilities whose binding differs, so nothing is dropped.
    """
    # Grouped on the WHOLE sub-score vector, not the headline. Two sets can tie at 9.8 with
    # completely different shapes — one strong on runtime and weak on reversibility, the other
    # the reverse — and folding those together would hide the actual trade behind a single row.
    # Only sets that are indistinguishable on every sub-score are the same option.
    groups = {}
    for option in options:
        key = (round(option["score"], 2) if option["score"] is not None else None,
               tuple(sorted((name, part.get("score"))
                            for name, part in option.get("parts", {}).items())))
        groups.setdefault(key, []).append(option)
    out = []
    for _, group in groups.items():
        head, rest = group[0], group[1:]
        if rest:
            differing = sorted({cap for other in rest
                                for cap, pid in (other["detail"].get("binding") or {}).items()
                                if (head["detail"].get("binding") or {}).get(cap) != pid})
            head["variants"] = [{"id": o["id"], "name": o["name"],
                                 "platforms": o["detail"]["platforms"]} for o in rest]
            head["variants_differ_in"] = differing
            head["name"] += f" (+{len(rest)} tied variant{'s' if len(rest) > 1 else ''})"
        out.append(head)
    return sorted(out, key=lambda o: (-(o["score"] if o["score"] is not None else -1), o["id"]))


def apply_house_bonus(options, model, house):
    """The tiebreak from the brief, as a weight and never a gate.

    It cannot make a non-viable set viable and it cannot overturn a materially better fit; when
    it decides the answer, the report has to say that is why.
    """
    rule = model["house_preference"]
    for option in options:
        used = set(option["detail"].get("platforms") or [])
        if not used & set(house or []):
            continue
        for key in rule["bonus_applies_to"]:
            part = option["parts"].get(key)
            if part and part["score"] is not None:
                part["score"] = round(min(10.0, part["score"] + rule["bonus"]), 2)
                part["basis"] += (f". Includes the {rule['bonus']} house bonus: "
                                  f"{', '.join(sorted(used & set(house)))} is already run here")
        option["score"] = _compose(option["parts"], model["weights"]["platform"])
        option["house_bonus_applied"] = True
    return options


def recommend(options, model, house):
    """Highest-scoring viable option, and the sentence that says whether the tiebreak decided it."""
    viable = [o for o in options if o["viable"] and o["score"] is not None]
    if not viable:
        return None, "no option is both viable and scorable"
    ranked = sorted(viable, key=lambda o: -o["score"])
    best = ranked[0]
    margin = model["house_preference"]["material_margin"]
    if len(ranked) > 1 and (best["score"] - ranked[1]["score"]) < margin:
        runner_up = ranked[1]
        # The bonus only DECIDED it if the runner-up did not get one too. When every candidate
        # carries a house platform the bonus cancels out and the order is what separated them —
        # a real run reported "chosen on the house preference" for two sets tied at 7.64, both
        # of which had the bonus. Saying so is the difference between a reason and an alibi.
        if best.get("house_bonus_applied") and not runner_up.get("house_bonus_applied"):
            return best, (f"{best['name']} chosen on the house preference; {runner_up['name']} "
                          f"scored within {margin} ({runner_up['score']} against {best['score']})")
        return best, (f"{best['name']} and {runner_up['name']} scored within {margin} "
                      f"({best['score']} against {runner_up['score']})"
                      + (" and both use a house platform, so the bonus separated neither of "
                         "them — the order did. Pick on a reason the scores do not carry."
                         if best.get("house_bonus_applied") else
                         ". Nothing material separates them."))
    return best, f"{best['name']} scores {best['score']}" + (
        f", ahead of {ranked[1]['name']} at {ranked[1]['score']}" if len(ranked) > 1 else
        " and is the only viable option")


# ---------------------------------------------------------------- what gets drawn

# Languages rather than frameworks. A stack option that does not name its `framework` is read
# as the first technology that is not one of these: ["python", "django", "htmx"] means Django.
# Named here rather than inferred, because "the first entry" is Python and a Python logo on the
# application box says nothing a reader did not already know.
LANGUAGES = {"python", "typescript", "javascript", "js", "ts", "go", "golang", "ruby", "java",
             "php", "rust", "elixir", "kotlin", "swift", "csharp", "c#", "dotnet", ".net",
             "scala", "clojure", "dart", "node", "nodejs"}


def stack_software(stack):
    """The one product whose logo identifies the application, or None.

    None is a real answer: `architecture-check.py` reports a stack that never named its framework
    rather than this function guessing one. A diagram is allowed to say "Application"; it is not
    allowed to say "Django" because something looked like it might be.
    """
    if not stack:
        return None
    detail = stack.get("detail") or {}
    named = stack.get("framework") or detail.get("framework")
    if named:
        return named
    for technology in detail.get("technologies") or []:
        if str(technology).strip().lower() not in LANGUAGES:
            return str(technology).strip().title() if str(technology).islower() else technology
    return None


def runtime_of(served, pid, platforms):
    """The one named service that RUNS the code, or None.

    `serves[cap].service` is a description and sometimes a choice — AWS answers `application`
    with "AWS App Runner, ECS Fargate or Lambda", which is three services and not a runtime. A
    profile that collapsed a choice names the `runtime` it actually means, and the alternatives
    beside it; one that names a single product needs neither.
    """
    if not pid or not served:
        return None
    # `runtime` only. `service` is a description of what the platform offers for a capability and
    # is sometimes a choice or a pair — AWS answers `web_client` with "S3 and CloudFront" — and
    # neither is a container to draw code inside. A profile that hosts code says so explicitly.
    service = served.get("runtime")
    if not service:
        return None
    return {"service": service, "platform": pid,
            "alternatives": served.get("runtime_alternatives") or [],
            "why": served.get("runtime_why") or served.get("interface_why") or ""}


def build_components(decisions, binding, platforms, cap_map, model, inventory, inputs,
                     stack=None):
    """One component per capability, each carrying why it is on the canvas.

    `serves` is the whole point. A component that serves nothing is invented infrastructure —
    the same failure as invented scope — and `architecture-check.py` fails the run on it.
    """
    catalogue = caps.capabilities(model)
    standing = {s.get("item"): s for s in
                ((inventory.get("standing_scope") or {}).get("selected") or [])
                if s.get("applies")}
    all_stories = [f["id"] for f in inventory.get("features") or []
                   if f.get("origin") != "standing" and f.get("epic_id")]

    software = stack_software(stack)

    out = []
    # Not "Users": the actors' own boundary is labelled `Users` by the tier catalogue, and A4
    # wants every name on the canvas to be unique. A default that collides with a container of
    # ours is our defect, not the operator's.
    for actor in (inputs.get("actors") or [{"name": "End users", "why": "every story is delivered "
                                                                   "to somebody"}]):
        out.append({"id": f"actor-{len(out)}", "capability": "_actor",
                    "name": actor["name"], "tier": "actors", "mode": "actor", "role": "User",
                    "icon": actor.get("icon", "user"), "interface": "internal",
                    # What this person actually uses. Without it every actor was drawn into the
                    # WAF, so on passenger-seat learners and instructors — who use a mobile app —
                    # were shown entering through the same door as staff on a browser console.
                    **({"reaches": list(actor["reaches"])} if actor.get("reaches") else {}),
                    "serves": {"stories": all_stories, "standing_work": [],
                               "assumptions": [actor.get("why", "")] if actor.get("why") else []}})

    for d in decisions:
        cap = d["capability"]
        spec = catalogue[cap]
        stories = (cap_map.get(cap) or {}).get("stories") or []
        pid = binding.get(cap)
        served = ((platforms.get(pid, {}).get("serves") or {}).get(cap) or {}) if pid else {}
        # A thing the team writes or adopts and the thing that RUNS it are two different items,
        # and the diagram has to show one inside the other. Collapsing them into one label —
        # "Django on Fargate" — put one box on the canvas where there are two, and made the
        # icon a coin toss between a framework and a cloud service.
        runs_on, product = None, None
        if d["mode"] in ("build", "adopt"):
            runs_on = runtime_of(served, pid, platforms)
            if d["mode"] == "adopt" and d.get("candidate"):
                product = d["candidate"]
            elif cap == "application":
                # Only the application tier IS the stack. A built search or analytics capability
                # is written in the same framework, but labelling four boxes "Django" says
                # nothing about any of them.
                product = software
        elif d["mode"] == "buy":
            product = d.get("candidate") if not served.get("service") else served.get("service")
        else:
            product = served.get("service")
        # `product` is the concrete named thing, and its absence is the point. A capability that
        # chose nothing keeps its own label — "Identity and access", "Model inference" — and a
        # label like that is not a product, so it must never be looked up in a brand catalogue.
        # It was: "Identity and access" found PING IDENTITY's logo and "Model inference" found
        # Model Context Protocol's. Another company's mark on a box the team is going to write.
        name = product or spec["name"]
        items = [k for k in standing if cap in (standing[k].get("capabilities") or [])]
        if not (stories or items):
            # Nothing puts this box on the canvas. Recorded as a refusal rather than drawn.
            continue
        component = {
            "id": cap, "capability": cap, "name": name, "product": product,
            # The diagram's second label line: the product on top, what it IS underneath. The
            # catalogue's own `name` is the fallback, so a capability added by research still
            # gets one rather than a blank line.
            "role": spec.get("role") or spec["name"],
            "platform": pid, "tier": spec["tier"], "mode": d["mode"],
            "icon": served.get("icon") or spec.get("icon") or "box",
            "interface": served.get("interface") or ("internal" if d["mode"] == "build"
                                                     else "proprietary"),
            "serves": {"stories": stories, "standing_work": items, "assumptions": []},
        }
        if runs_on:
            component["runs_on"] = runs_on
        out.append(component)
    return out


def apply_component_overrides(components, overrides):
    """Let the operator name a box, and say what it runs inside.

    `inputs.component_overrides` was declared, echoed into `architecture.json` and read by
    nothing — a real run put six of them in `inputs.json` and the components kept the platform
    profile's own labels. An input nobody applies is worse than an input that does not exist,
    because the file says it was honoured.

    An override may set `name`, `icon` and `runs_on`, and must say `why`: it overrules a profile,
    so the reason belongs on the component beside the stories it serves. `runs_on: null` removes
    a runtime the profile implied — for code that genuinely runs nowhere else.
    """
    by_id = {c["id"]: c for c in components}
    unknown = []
    for cap, override in (overrides or {}).items():
        component = by_id.get(cap)
        if component is None:
            unknown.append(cap)
            continue
        if override.get("name"):
            component["name"] = override["name"]
            # An operator naming a box is naming a real thing, so it becomes the product to look
            # an icon up by unless the override says otherwise.
            component["product"] = override.get("product", override["name"])
        if override.get("icon"):
            component["icon"] = override["icon"]
        if "runs_on" in override:
            runtime = override["runs_on"]
            if runtime:
                component["runs_on"] = dict(runtime, platform=runtime.get("platform")
                                            or component.get("platform"))
            else:
                component.pop("runs_on", None)
        if override.get("why"):
            component["serves"]["assumptions"].append(f"operator override: {override['why']}")
    return components, unknown


def build_connections(components, catalogue=None):
    """The graph the architecture actually has, read off the capability catalogue.

    The previous version derived edges from TIERS: every component in the application tier was
    joined to every component in services, data and external. `web_client` lives in that tier, so
    a browser was given authored edges to a secrets manager, a relational store and a payment
    vendor — half the graph was false, and no layout engine can draw a false graph well. It was
    invisible because the diagram aggregated every edge to its tier group before drawing.

    So each capability names what it talks to. `reaches` draws an edge to every listed capability
    the architecture contains; `reaches_first` draws one edge, to the first that is present, which
    keeps the request path a path when an optional hop like a CDN is not in the set. The label
    comes from the TARGET's `edge_label` — what arrives here — so a label says what flows, and two
    edges cannot share one without sharing a target.

    A capability added by research carries none of those fields. It is reached from the application
    rather than left floating, and labelled from its own name: the honest default, and the report
    says a default was used.
    """
    catalogue = catalogue or {}
    by_cap = {}
    for c in components:
        if c["capability"] != "_actor":
            by_cap.setdefault(c["capability"], []).append(c)
    spec = lambda cap: catalogue.get(cap) or {}

    def label_for(cap, target):
        # A capability the catalogue knows says what arrives at it. One added by research does
        # not, so the edge is named after the thing itself — still a verb and an object, still
        # unique, and visibly a default rather than a phrase somebody chose.
        return spec(cap).get("edge_label") or f"Calls {target['name']}"

    edges, defaulted = [], []

    def join(source, cap):
        for target in by_cap.get(cap, []):
            if target["id"] != source["id"]:
                edges.append({"from": source["id"], "to": target["id"],
                              "label": label_for(cap, target)})

    for cap, items in by_cap.items():
        for source in items:
            for target_cap in spec(cap).get("reaches") or []:
                join(source, target_cap)
            for target_cap in spec(cap).get("reaches_first") or []:
                if target_cap in by_cap:
                    join(source, target_cap)
                    break

    # A capability the catalogue does not know reaches nothing and is reached by nothing, so it
    # would float off the canvas unconnected. The application is what would call it.
    reached = {e["to"] for e in edges}
    for cap, items in by_cap.items():
        if spec(cap).get("reaches") or spec(cap).get("reaches_first"):
            continue
        for target in items:
            if target["id"] in reached or target["capability"] == "application":
                continue
            for source in by_cap.get("application", []):
                edges.append({"from": source["id"], "to": target["id"],
                              "label": label_for(cap, target)})
                defaulted.append(target["id"])

    # An actor touches the front of the system, not its identity provider. Which component is the
    # front depends on what the set contains, so it is a preference list rather than a tier lookup.
    front = None
    for cap in ("edge_protection", "cdn", "web_client", "application"):
        if by_cap.get(cap):
            front = by_cap[cap][0]
            break
    for actor in components:
        if actor["capability"] != "_actor":
            continue
        # An actor that says what it uses is joined to exactly that; one that does not keeps the
        # default front door. A named capability absent from the set falls back rather than
        # leaving the person unconnected.
        targets = [t for cap in actor.get("reaches") or [] for t in by_cap.get(cap, [])]
        if not targets and front is not None:
            targets = [front]
        for target in targets:
            edges.append({"from": actor["id"], "to": target["id"],
                          "label": label_for(target["capability"], target)})

    seen, unique = set(), []
    for e in edges:
        key = (e["from"], e["to"])
        if key in seen or e["from"] == e["to"]:
            continue
        seen.add(key)
        unique.append(e)
    # Several arrows converging on one box describe one flow, so they carry one label between
    # them rather than the same words three times over. This is what keeps D7's "unique in the
    # diagram" honest: a label may not mean two different things, but one meaning does not need
    # to be written out once per arrowhead.
    labelled = set()
    for e in unique:
        key = (e["to"], e["label"])
        if key in labelled:
            e["label"] = ""
        else:
            labelled.add(key)
        if e["to"] in defaulted:
            e["defaulted"] = True
    return unique


def apply_connection_overrides(connections, components, overrides):
    """A design decision that removes an edge the catalogue would draw, with its reason.

    `reaches` is company-wide: it says what an application USUALLY talks to. A project's design can
    route something differently — on passenger-seat every email and push leaves through the
    workers, never from the request path, so `application -> email` and `application -> sms_push`
    described a design nobody chose. `inputs.connection_overrides.remove` is
    `[{"from": cap, "to": cap, "why": ...}]`; each removal is refused if it names an edge the
    architecture does not have, and every applied one is returned so the deliverable says what was
    taken off the picture and why — the same rule as every other override here.
    """
    by_cap = {}
    for c in components:
        by_cap.setdefault(c["capability"], []).append(c["id"])
    applied, unknown = [], []
    for rule in (overrides or {}).get("remove") or []:
        if not rule.get("why"):
            raise SystemExit(f"connection_overrides.remove {rule} has no `why`; an edge taken off "
                             f"a client-facing diagram has to say why")
        sources, targets = set(by_cap.get(rule["from"], [])), set(by_cap.get(rule["to"], []))
        hit = [e for e in connections if e["from"] in sources and e["to"] in targets]
        if not hit:
            unknown.append(rule)
            continue
        connections = [e for e in connections if e not in hit]
        applied.append({"from": rule["from"], "to": rule["to"], "why": rule["why"]})
    return connections, applied, unknown


def build_handoff(stack, decisions, cap_map):
    """What est-estimate reads. EVIDENCE, never a verdict: the classifier still decides bands.

    Scope does not move here. Buying identity does not delete the identity stories — the work
    is still delivered, differently, and what changes is how it classifies.
    """
    detail = stack["detail"] if stack else {}
    notes = []
    for d in decisions:
        if d["mode"] == "build":
            continue
        what = d.get("candidate") or d["name"]
        for story in (cap_map.get(d["capability"]) or {}).get("stories") or []:
            notes.append({
                "story": story, "capability": d["capability"], "mode": d["mode"],
                "note": (f"{'integrates' if d['mode'] == 'buy' else 'builds against'} "
                         f"{what} rather than implementing {d['name'].lower()} from scratch"),
            })
    return {
        "stack_profile": {"value": detail.get("stack_profile", "standard_saas"),
                          "why": detail.get("stack_profile_why", "no stack option was scored")},
        "novel_stack": {"is_novel": bool(detail.get("novel")),
                        "technologies": detail.get("novel_technologies") or [],
                        "why": ("no delivered project behind "
                                + ", ".join(detail.get("novel_technologies") or [])
                                + f"; the cost model prices that at {NOVELTY_MULTIPLIER}x"
                                if detail.get("novel") else
                                "every technology has a delivered project behind it"
                                if detail.get("novel") is False else
                                "novelty could not be assessed — preferences are UNANSWERED")},
        "sourcing_notes": notes,
    }


def build_architecture(inventory, model, platforms, inputs, stacks=None, candidates=None,
                       estimate=None, prefs=None, sourcing_confirmed=False,
                       stack_confirmed=False, platform_confirmed=False, stop_after=None):
    prefs = prefs or {f: None for f in preferences.FIELDS}
    house = inputs.get("house_platforms") or prefs.get("house_platforms") or []
    constraints = inputs.get("constraints") or []

    cap_map = caps.build_map(inventory, model, estimate)
    cap_map = caps.apply_overrides(cap_map, inputs.get("capability_overrides"), inventory,
                                   estimate)
    decisions = sourcing.build_decisions(cap_map, inventory, model, candidates)
    apply_counter_proposals(decisions, inputs.get("model_counter_proposals"))
    apply_sourcing_overrides(decisions, inputs.get("sourcing_overrides"), candidates)
    for d in decisions:
        supplied = ((candidates or {}).get(d["capability"]) or {}).get(d["mode"]) or {}
        d["self_run"] = bool(supplied.get("self_run"))

    stack_options = [score_stack(o, cap_map, inventory, model, constraints, prefs)
                     for o in (stacks or [])]
    picked = inputs.get("stack_choice")
    if picked:
        chosen_stack = next((o for o in stack_options if o["id"] == picked), None)
        stack, stack_why = chosen_stack, (
            f"{chosen_stack['name']} chosen by the operator" if chosen_stack else
            f"operator named stack `{picked}`, which was not among the options scored")
    else:
        stack, stack_why = recommend(stack_options, model, house)

    needed = needs_platform(decisions, model)
    pool, excluded, unmet_mandates = allowed_platforms(platforms, constraints)
    mandated = [c["detail"] for c in constraints
                if c["kind"] == "mandated_platform" and c["detail"] in pool]
    pinned = pinned_bindings(decisions, candidates, pool)
    sets, unservable = enumerate_sets(needed, pool, model, house, mandated, pinned)
    platform_options = [score_platform_set(s, needed, platforms, model, constraints,
                                           decisions, prefs) for s in sets]
    platform_options = apply_house_bonus(platform_options, model, house)
    platform_options = collapse_ties(platform_options)
    chosen_set, set_why = recommend(platform_options, model, house)

    binding = (chosen_set or {}).get("detail", {}).get("binding", {})
    components = build_components(decisions, binding, platforms, cap_map, model,
                                  inventory, inputs, stack)
    components, unknown_overrides = apply_component_overrides(
        components, inputs.get("component_overrides"))
    drawn = {c["capability"] for c in components}
    refusals = [{"what": caps.capabilities(model)[d["capability"]]["name"],
                 "kind": "component",
                 "why": "no story and no standing-work item puts it on the canvas, so it is "
                        "not drawn — a component that serves nothing is invented infrastructure"}
                for d in decisions if d["capability"] not in drawn]
    # Only platforms that actually reached a scored set are worth refusing. With a twenty-
    # profile catalogue, listing every vendor the design did not use put eleven rows of noise
    # in a client-facing report and buried the two that mattered.
    considered = {p for option in platform_options for p in option["detail"]["platforms"]}
    for pid, profile in sorted(platforms.items()):
        if pid not in considered:
            continue
        if chosen_set and pid not in (chosen_set["detail"]["platforms"]):
            mine = [c for c in needed if caps.serves_natively(profile, c)]
            if mine and all(c in binding for c in mine):
                refusals.append({
                    "what": profile["name"], "kind": "vendor",
                    "why": f"serves {', '.join(mine)}, all of which a platform already in the "
                           f"set provides. A vendor that adds nothing is another account, "
                           f"another bill and another data-processing agreement for nothing"})

    for pid in excluded:
        refusals.append({
            "what": platforms[pid]["name"], "kind": "platform",
            "why": "excluded by a hard constraint, so it was kept out of the candidate pool "
                   "rather than scored and then refused"})
    for detail in unmet_mandates:
        refusals.append({
            "what": detail, "kind": "platform",
            "why": f"`{detail}` is mandated and no profile in the catalogue provides it. Add one "
                   f"— a data file, never code — or the constraint cannot be honoured."})

    for cap in unknown_overrides:
        refusals.append({
            "what": cap, "kind": "component_override",
            "why": f"`component_overrides.{cap}` names a capability that is not drawn, so the "
                   f"override changed nothing. Either the capability serves no story or the key "
                   f"is misspelt."})

    connections, removed_edges, unknown_edges = apply_connection_overrides(
        build_connections(components, caps.capabilities(model)), components,
        inputs.get("connection_overrides"))
    for rule in removed_edges:
        refusals.append({"what": f"{rule['from']} -> {rule['to']}", "kind": "connection",
                         "why": rule["why"]})
    for rule in unknown_edges:
        refusals.append({"what": f"{rule['from']} -> {rule['to']}", "kind": "connection_override",
                         "why": "`connection_overrides.remove` names an edge this architecture "
                                "does not draw, so it changed nothing"})

    balance = sourcing.balance(decisions, model)
    balance["vendors_added"] = len((chosen_set or {}).get("detail", {}).get("platforms", []))

    out = {
        "schema_version": "1.0",
        "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        # Which copy of the skill wrote this. A project installs by copy, and a run that executes
        # a stale one produces a defensible-looking artefact from code nobody is reading.
        "produced_by": caps.revision(),
        "project": inventory.get("project") or "unnamed",
        "inventory_path": inputs.get("inventory_path") or "",
        "estimate_path": inputs.get("estimate_path"),
        # Echoed so the deliverable can reproduce the run. A real run's override payload lived
        # only in a scratch inputs.json that was not among the copied deliverables, so the
        # folder a reader was handed could not rebuild what it described.
        "inputs": {"house_platforms": house,
                   "procurement": inputs.get("procurement") or {},
                   "nfr": inputs.get("nfr") or [],
                   "constraints": constraints,
                   "capability_overrides": inputs.get("capability_overrides") or {},
                   "component_overrides": inputs.get("component_overrides") or {},
                   "connection_overrides": inputs.get("connection_overrides") or {},
                   "diagram": inputs.get("diagram") or {},
                   "sourcing_overrides": inputs.get("sourcing_overrides") or {},
                   "model_counter_proposals": inputs.get("model_counter_proposals") or {},
                   "stack_choice": inputs.get("stack_choice")},
        "capability_map": cap_map,
        "layers": {
            "stack": {"options": stack_options,
                      "chosen": (stack or {}).get("id"), "chosen_why": stack_why,
                      "confirmed": bool(stack_confirmed),
                      "confirmed_by": "operator" if stack_confirmed else None},
            "sourcing": {"decisions": decisions, "confirmed": bool(sourcing_confirmed),
                         "confirmed_by": "operator" if sourcing_confirmed else None,
                         "balance": balance,
                         "batch": sourcing.confirmation_batch(decisions)},
            "platform": {"options": platform_options,
                         "chosen": (chosen_set or {}).get("id"), "chosen_why": set_why,
                         "confirmed": bool(platform_confirmed),
                         "confirmed_by": "operator" if platform_confirmed else None},
        },
        "gate": {"pending": None, "order": list(gates.ORDER),
                 "stopped_after": stop_after},
        "components": components,
        "connections": connections,
        "refusals": refusals,
        "handoff": build_handoff(stack, decisions, cap_map),
        # What the options were chosen FROM. A recommendation drawn from a catalogue of one is
        # not a recommendation, and the reader cannot tell without this.
        "catalogue": {
            "profiles": len(platforms),
            "shipped": sum(1 for p in platforms.values()
                           if "assets/platforms" in str(p.get("_path", ""))),
            "researched": sum(1 for p in platforms.values()
                              if "assets/platforms" not in str(p.get("_path", ""))),
            # Over every capability the backlog mentions, not only the ones already needing a
            # home: "identity has one candidate" is the signal that sends somebody to research,
            # and it is invisible if the count is taken after the binding.
            "candidates_per_capability": {
                c: sorted(p for p, profile in platforms.items()
                          if caps.serves_natively(profile, c))
                for c in sorted(cap_map)},
            "thin": sorted(c for c in cap_map
                           if 0 < len([p for p, profile in platforms.items()
                                       if caps.serves_natively(profile, c)]) < 2),
            "thin_why": "a capability with one candidate is not a decision — research the "
                        "space and add a profile with scripts/profile-scaffold.py",
        },
        "catalogue_gaps": [
            {"capability": c,
             "detail": f"no platform profile in the catalogue serves `{c}`, so no set could bind "
                       f"it and it is excluded from every coverage score. Add a profile for the "
                       f"vendor that provides it — a data file, never code.",
             "needed_because": needs_platform(decisions, model).get(c, "")}
            for c in unservable],
        "research": {"available": bool(stacks or candidates),
                     "unsourced_subscores": sorted({
                         f"stack.{p}" for o in stack_options
                         for p in o["detail"].get("unscored_parts") or []} | {
                         f"sourcing.{d['capability']}.{m}" for d in decisions
                         for m in d.get("needs_research") or []})},
    }
    out["gate"]["pending"] = gates.pending(out)
    return out



def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inventory", help="path to feature-inventory.json")
    ap.add_argument("-o", "--output", help="write architecture.json here instead of stdout")
    ap.add_argument("--estimate", help="an estimate.json, if one already exists")
    ap.add_argument("--stacks", help="researched stack options")
    ap.add_argument("--candidates", help="researched adopt/buy candidates, by capability")
    ap.add_argument("--inputs", help="constraints, NFRs, procurement position, actors")
    ap.add_argument("--preferences", help="architecture-preferences.md from module memory")
    ap.add_argument("--platforms", help="platform profile directory")
    ap.add_argument("--model", help="architecture-model.json from module memory")
    ap.add_argument("--stack-confirmed", action="store_true",
                    help="the operator has accepted or corrected the stack (gate 1 of 3)")
    ap.add_argument("--sourcing-confirmed", action="store_true",
                    help="the operator has accepted or corrected the sourcing batch (gate 2)")
    ap.add_argument("--platform-confirmed", action="store_true",
                    help="the operator has accepted or corrected the platform set (gate 3)")
    ap.add_argument("--stop-after", choices=("stack", "sourcing", "platform"),
                    help="score up to this layer and stop, whatever is confirmed")
    ap.add_argument("--gate-dir", help="where the gate documents are written; defaults to "
                                       "beside the output")
    args = ap.parse_args()

    def read(path, default=None):
        return json.loads(Path(path).read_text(encoding="utf-8")) if path else default

    inventory = read(args.inventory)
    inputs = read(args.inputs, {}) or {}
    inputs.setdefault("inventory_path", args.inventory)
    inputs.setdefault("estimate_path", args.estimate)
    model = caps.load_model(args.model)
    out = build_architecture(
        inventory, model, caps.load_platforms(args.platforms), inputs,
        stacks=read(args.stacks, []), candidates=read(args.candidates, {}),
        estimate=read(args.estimate), prefs=preferences.load(args.preferences),
        sourcing_confirmed=args.sourcing_confirmed,
        stack_confirmed=args.stack_confirmed, platform_confirmed=args.platform_confirmed,
        stop_after=args.stop_after)

    text = json.dumps(out, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)

    # A gate that is not confirmed stops the run. The layers constrain each other, so scoring
    # past an unsettled decision is work that has to be thrown away — and reporting a choice
    # nobody made as though they had made it is the failure this whole mechanism exists for.
    waiting = out["gate"]["pending"] or args.stop_after
    if waiting:
        where = Path(args.gate_dir) if args.gate_dir else (
            Path(args.output).parent if args.output else Path.cwd())
        where.mkdir(parents=True, exist_ok=True)
        document = where / f"gate-{waiting}.md"
        document.write_text(gates.render(waiting, out, inventory), encoding="utf-8")
        nth = gates.ORDER.index(waiting) + 1
        print(f"gate {nth} of 3 ({waiting}) is waiting on the operator: {document}",
              file=sys.stderr)
        return 3
    # Audited on the way out, by the same code a reviewer runs later. A plan that fails its own
    # audit is still written so it can be argued with, and must not be sent.
    report = check.audit(out, inventory, model=caps.load_model(args.model),
                         platforms=caps.load_platforms(args.platforms))
    out["check"] = report
    if args.output:
        Path(args.output).write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n",
                                     encoding="utf-8")
    if not report["ok"]:
        print(f"architecture audit FAILED: {len(report['findings'])} finding(s); "
              f"checked {report['checked']}", file=sys.stderr)
        return 2
    viable = [o for o in out["layers"]["platform"]["options"] if o["viable"]]
    if not viable:
        print("no viable platform set — every candidate violates a hard constraint",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
