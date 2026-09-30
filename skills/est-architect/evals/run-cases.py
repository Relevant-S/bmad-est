#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Adversarial cases for est-architect — the conclusions, not the arithmetic.

These are not unit tests. Each case is a shape whose *emergent* answer is the claim being
checked: that a runtime which cannot hold a process open loses to one that can, that a
mediocre product loses to building, that nothing unexamined is ever recommended, that a
constraint removes an option instead of discounting it. Unit tests protect the scoring; these
protect the advice, which is where a plausible-looking architecture goes wrong.

Every case runs against the SHIPPED model and the SHIPPED platform profiles, because the
coefficients that decide a refusal are the ones a client will be told about.

    uv run evals/run-cases.py [--case NAME] [--quiet]

Exit 0 when every case holds, 1 when any fails.
"""

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARCH = ROOT / "est-architect"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


caps = load("capabilities", ARCH / "scripts" / "capabilities.py")
architect = load("architect", ARCH / "scripts" / "architect.py")
sourcing = load("sourcing", ARCH / "scripts" / "sourcing.py")
check = load("check", ARCH / "scripts" / "architecture-check.py")
price = load("price", ARCH / "scripts" / "price.py")

MODEL = json.loads((ARCH / "assets" / "architecture-model.seed.json").read_text(encoding="utf-8"))
PLATFORMS = caps.load_platforms()
CASES = {}


def case(name):
    def register(fn):
        CASES[name] = fn
        return fn
    return register


def story(fid, name, description, epic="E1", surfaces=("backend", "frontend"), size="M"):
    return {"id": fid, "name": name, "description": description, "epic_id": epic,
            "surfaces": list(surfaces), "commitment": "committed", "tasks": [],
            "citations": [{"source_id": "S1", "location": "§1", "quote": description}],
            "depends_on": [], "open_questions": [],
            "tags": {"size_band": {"value": size, "why": "eval", "status": "inferred"}}}


def inventory(features):
    return {"schema_version": "1.1", "generated": "2026-09-29T00:00:00Z", "project": "Eval",
            "granularity": "project", "working_language": "en",
            "sources": [{"id": "S1", "path": "p.md", "doc_type": "prd", "language": "en"}],
            "epics": [{"id": e, "name": e, "origin": "source", "sequence": i + 1,
                       "sequence_why": "eval", "citations": []}
                      for i, e in enumerate(sorted({f["epic_id"] for f in features}))],
            "features": features, "not_scope": [], "conflicts": [], "assumptions": [],
            "completeness_signals": {}, "standing_scope": {"selected": []}}


def build(inv, inputs=None, **kw):
    return architect.build_architecture(inv, MODEL, PLATFORMS, inputs or {}, **kw)


WORKER_BACKLOG = inventory([
    story("F1", "Clinician sign-in", "Clinicians sign in with a password and a second factor."),
    story("F2", "Ingest device feed",
          "A background worker consumes a continuous device feed and queues each reading for "
          "processing, retrying failures.", surfaces=("backend", "data"), size="L"),
    story("F3", "Dashboard", "A dashboard shows the latest readings.",
          surfaces=("frontend", "design")),
    story("F4", "Store readings", "Readings persist to the database as a record.",
          surfaces=("backend", "data")),
])


@case("a-runtime-that-cannot-hold-a-process-open-loses")
def runtime(report):
    """The backlog needs a worker. A PaaS that only runs request-scoped functions cannot host
    it, and no amount of convenience elsewhere should hide that."""
    out = build(WORKER_BACKLOG, {"house_platforms": []})
    options = {o["detail"]["primary"]: o for o in out["layers"]["platform"]["options"]}
    report(f"scores: " + ", ".join(f"{k}={v['score']}" for k, v in options.items()))
    assert options["aws"]["parts"]["runtime_fit"]["score"] == 10.0
    for weak in ("vercel", "supabase"):
        if weak in options:
            assert options[weak]["parts"]["runtime_fit"]["score"] < 10.0, weak
            assert "cannot do long_running" in options[weak]["parts"]["runtime_fit"]["basis"]
    assert out["layers"]["platform"]["chosen"] == "aws", out["layers"]["platform"]["chosen"]


@case("a-mediocre-product-loses-to-building-it")
def mediocre(report):
    """The counterweight that stops the effort sub-score recommending every purchase. Effort
    always favours buying; requirement fit, escape cost and maintenance health are what make a
    bad candidate lose anyway."""
    poor = {"identity": {"buy": {
        "name": "A narrow identity service", "covers": ["F1"],
        "gaps": ["no role model", "no admin delegation"],
        "health": {"score": 3.0, "note": "single maintainer"},
        "pricing_model": "per seat", "interface": "proprietary"}}}
    good = {"identity": {"buy": {
        "name": "A mature identity service", "covers": ["F1"], "gaps": [],
        "health": {"score": 9.0, "last_release": "2026-09"},
        "pricing_model": "per monthly active user", "interface": "standard",
        "interface_why": "OIDC"}}}
    bad = build(WORKER_BACKLOG, candidates=poor)
    ok = build(WORKER_BACKLOG, candidates=good)
    decision = lambda o: next(d for d in o["layers"]["sourcing"]["decisions"]
                              if d["capability"] == "identity")
    report(f"poor candidate -> {decision(bad)['mode']}; good candidate -> {decision(ok)['mode']}")
    assert decision(bad)["mode"] == "build", decision(bad)["why"]
    assert decision(ok)["mode"] == "buy", decision(ok)["why"]


@case("nothing-unexamined-is-ever-recommended")
def unexamined(report):
    """Delivery effort structurally favours not building, so an option with one score and four
    blanks beat `build` on every capability nobody had researched — the workflow recommended
    buying things it had never looked at."""
    out = build(WORKER_BACKLOG)
    live = [d for d in out["layers"]["sourcing"]["decisions"] if d["live"]]
    assert live, "no live decision — the case proves nothing"
    for decision in live:
        assert decision["mode"] == "build", f"{decision['capability']} -> {decision['mode']}"
        assert decision["needs_research"], decision["capability"]
        assert "no candidate was researched" in decision["why"]
    report(f"{len(live)} live decisions, all defaulted to build with the gap named")


@case("a-constraint-removes-an-option-rather-than-discounting-it")
def constraint(report):
    """And removes it from the POOL, not just from the recommendation.

    The weaker version enumerated sets out of an excluded platform and refused them afterwards.
    On a backlog where only that platform served some capability, the greedy fill pulled it into
    every candidate, every candidate came back non-viable, and the run reported "no viable
    platform set" for a project three vendors could serve between them. What the constraint cost
    is reported as a refusal instead, so nothing is lost by filtering early.
    """
    out = build(WORKER_BACKLOG, {"constraints": [
        {"id": "C1", "kind": "excluded_platform", "detail": "aws", "basis": "stated"}]})
    options = out["layers"]["platform"]["options"]
    assert options, "the exclusion removed every option — the gate ate the answer"
    for option in options:
        assert "aws" not in option["detail"]["platforms"], option["id"]
    chosen = out["layers"]["platform"]["chosen"]
    assert chosen and "aws" not in chosen, chosen
    refusal = next(r for r in out["refusals"]
                   if r["kind"] == "platform" and "Amazon" in r["what"])
    assert "excluded by a hard constraint" in refusal["why"]
    report(f"{len(options)} option(s) survive without the excluded platform; chosen {chosen}, "
           f"and the exclusion is recorded as a refusal rather than vanishing")


@case("an-unverified-certification-is-neither-a-pass-nor-a-fail")
def unverified(report):
    """A profile shipping `certifications: {checked: null}` has not said the platform lacks the
    certification. It has said nobody looked, and a recommendation must not quietly convert
    that into either answer."""
    inputs = {"constraints": [{"id": "C1", "kind": "certification", "detail": "HIPAA",
                              "basis": "stated"}]}
    out = build(WORKER_BACKLOG, inputs)
    chosen = next(o for o in out["layers"]["platform"]["options"]
                  if o["id"] == out["layers"]["platform"]["chosen"])
    assert chosen["viable"], "an unverified fact must not fail an option"
    assert chosen["unevaluated_gates"], "nor silently pass it"
    assert chosen["parts"]["constraint_compliance"]["score"] is None
    audit = check.audit(out, WORKER_BACKLOG, platforms=PLATFORMS)
    assert any(f["kind"] == "gate_on_unverified_fact" for f in audit["findings"])
    report("unevaluated, and the audit raises it rather than the option swallowing it")


@case("the-house-preference-cannot-overturn-a-material-win")
def house(report):
    options = [{"id": "house", "name": "House", "viable": True, "score": 6.0,
                "house_bonus_applied": True, "parts": {}, "detail": {"platforms": ["aws"]}},
               {"id": "other", "name": "Other", "viable": True, "score": 9.0,
                "parts": {}, "detail": {"platforms": ["vercel"]}}]
    best, why = architect.recommend(options, MODEL, ["aws"])
    assert best["id"] == "other", why
    assert "house preference" not in why
    close = [dict(options[0], score=7.0), dict(options[1], score=6.8)]
    _, why_close = architect.recommend(close, MODEL, ["aws"])
    assert "chosen on the house preference" in why_close
    report("loses a 3-point gap; wins a 0.2 gap and says that is why")


@case("buying-a-capability-does-not-shrink-the-backlog")
def scope(report):
    """The most dangerous failure available here: an architecture that 'buys auth' and quietly
    drops the auth stories has re-priced the deal without telling anyone."""
    before = build(WORKER_BACKLOG)
    after = build(WORKER_BACKLOG, candidates={"identity": {"buy": {
        "name": "A mature identity service", "covers": ["F1"], "gaps": [],
        "health": {"score": 9.0}, "pricing_model": "per MAU", "interface": "standard"}}})
    audit = check.audit(after, WORKER_BACKLOG, previous=before, platforms=PLATFORMS)
    assert not [f for f in audit["findings"] if f["kind"] == "story_dropped"]
    assert not [f for f in audit["findings"] if f["kind"] == "story_unserved"]
    notes = [n for n in after["handoff"]["sourcing_notes"] if n["capability"] == "identity"]
    assert notes and all("integrates" in n["note"] for n in notes)
    report(f"scope held; {len(notes)} sourcing note(s) handed to est-estimate as evidence")


@case("every-box-on-the-diagram-says-what-it-is-for")
def traceability(report):
    out = build(WORKER_BACKLOG)
    audit = check.audit(out, WORKER_BACKLOG, platforms=PLATFORMS)
    assert audit["ok"], audit["findings"][:3]
    assert audit["components"] > 0 and audit["mapped_story_links"] > 0
    for component in out["components"]:
        serves = component["serves"]
        assert serves["stories"] or serves["standing_work"] or serves["assumptions"], component["id"]
    report(audit["checked"])


@case("a-vendor-that-buys-nothing-is-refused")
def sprawl(report):
    out = build(WORKER_BACKLOG, {"house_platforms": ["aws"]})
    refused = [r for r in out["refusals"] if r["kind"] == "vendor"]
    assert refused, "no vendor was ever considered and refused"
    assert all("adds nothing" in r["why"] for r in refused)
    report(f"refused {', '.join(r['what'] for r in refused)}")


@case("a-price-with-no-page-behind-it-is-refused")
def fabricated(report):
    """The worst failure available on the cost layer, and the cheapest to catch."""
    out = build(WORKER_BACKLOG)
    costs = price.price(out, [{"item": "Managed Postgres", "capability": "relational_store",
                               "type": "monthly", "rate": 45.0, "quantity": 1}])
    kinds = [f["kind"] for f in costs["findings"]]
    assert kinds.count("figure_without_a_source") == 3, kinds
    assert not costs["ok"]
    zero = price.price(out, [{"item": "Auth free tier", "capability": "identity",
                              "type": "monthly", "rate": 0.0, "quantity": 1,
                              "quote": "free", "url": "https://x.invalid",
                              "fetched_at": "2026-09-29"}])
    assert any(f["kind"] == "zero_without_a_cliff" for f in zero["findings"])
    report("a figure with no quote, url or date is refused; so is a zero with no cliff")


@case("a-gate-cannot-be-skipped")
def gates_block(report):
    """The brief was to propose, score and WAIT. The first build waited at one layer of three:
    a stack choice that reversed a PRD and a seven-vendor set were decided and reported."""
    gate = load("gates", ARCH / "scripts" / "gates.py")
    steps = [({}, "stack"),
             ({"stack_confirmed": True}, "sourcing"),
             ({"stack_confirmed": True, "sourcing_confirmed": True}, "platform"),
             ({"stack_confirmed": True, "sourcing_confirmed": True,
               "platform_confirmed": True}, None)]
    for flags, expected in steps:
        out = build(WORKER_BACKLOG, {"house_platforms": []}, **flags)
        assert out["gate"]["pending"] == expected, (flags, out["gate"]["pending"])
    # confirming out of order must not skip anything
    out = build(WORKER_BACKLOG, {"house_platforms": []}, platform_confirmed=True)
    assert out["gate"]["pending"] == "stack", out["gate"]["pending"]
    assert gate.ORDER == ("stack", "sourcing", "platform")
    report("three gates, in order, and a late confirmation skips none of them")


@case("a-reversal-of-a-recorded-stack-is-called-out")
def reversal(report):
    gate = load("gates", ARCH / "scripts" / "gates.py")
    inv = dict(WORKER_BACKLOG)
    inv["assumptions"] = [{"text": "Operator decision: the stack is Python 3.12 / Django 5 + "
                                   "DRF, Django templates + HTMX, Celery + Redis."}]
    stacks = [{"id": "next", "name": "Next.js + TypeScript", "axis": "one language",
               "technologies": ["typescript", "nextjs", "react", "bullmq"],
               "deployable_services": 1, "libraries": {},
               "currency": {"score": 9.0, "checked": "2026-09-29"}, "gaps": []},
              {"id": "drf", "name": "Django + DRF + React", "axis": "split runtime",
               "technologies": ["python", "django", "celery", "react"],
               "deployable_services": 2, "libraries": {},
               "currency": {"score": 8.0, "checked": "2026-09-29"}, "gaps": []}]
    out = build(inv, {"house_platforms": [], "stack_choice": "next"}, stacks=stacks)
    chosen = next(o for o in out["layers"]["stack"]["options"] if o["id"] == "next")
    clash = gate.contradicts(chosen, inv)
    assert clash, "a complete reversal was not flagged"
    assert clash["agreement"] < 0.5, clash
    doc = gate.render("stack", out, inv)
    assert "This reverses what the sources say" in doc
    assert "should be re-run" in doc
    still = next(o for o in out["layers"]["stack"]["options"] if o["id"] == "drf")
    assert gate.contradicts(still, inv) is None, "a Django stack was called a reversal"
    report(f"flagged at {clash['agreement']:.0%} agreement; the Django option stays quiet")


@case("a-vendor-nobody-chose-is-not-counted-as-sprawl")
def sprawl_counts_choices(report):
    """Payments are Stripe and email is a deliverability vendor whoever you are. Charging a set
    for decisions nobody made punishes the wrong thing — the identical mistake `balance()` was
    already corrected for."""
    out = build(WORKER_BACKLOG, {"house_platforms": []})
    for option in out["layers"]["platform"]["options"]:
        basis = option["parts"]["vendor_sprawl"]["basis"]
        assert "vendor(s) this set chose" in basis, basis
        assert option["parts"]["vendor_sprawl"]["score"] is not None
    decay = MODEL["vendor_sprawl"]["decay"]
    scores = [round(10.0 * (decay ** max(0, n - 1)), 2) for n in (1, 5, 7, 20)]
    assert scores[1] > scores[2] > scores[3] > 0, scores
    report(f"counts chosen vendors only; penalty at 1/5/7/20 vendors = {scores}")


@case("every-arguable-capability-has-something-to-choose-between")
def catalogue_breadth(report):
    """A run scored eleven platform sets that all contained the same five vendors, because
    identity, email and error-tracking had exactly one candidate each. An architecture chosen
    from a catalogue of one is not chosen."""
    thin = []
    for capability in ("identity", "relational_store", "object_store", "async_work",
                       "observability", "error_tracking", "email", "application", "cdn"):
        serving = [p for p, profile in PLATFORMS.items()
                   if caps.serves_natively(profile, capability)]
        if len(serving) < 2:
            thin.append(f"{capability} ({serving})")
    assert not thin, f"nothing to choose between for: {'; '.join(thin)}"
    report(f"{len(PLATFORMS)} profiles; every arguable capability has at least two candidates")


@case("the-diagram-is-not-one-long-strip")
def diagram_shape(report):
    layout = load("layout", ARCH / "scripts" / "layout.py")
    out = build(WORKER_BACKLOG, {"house_platforms": []})
    doc = layout.document(out, MODEL, PLATFORMS)
    width = max(e["x"] + e.get("width", 0) for e in doc["entities"])
    height = max(e["y"] + e.get("height", 0) for e in doc["entities"])
    assert width / height < 4.0, f"{width}x{height} is a strip"
    assert not layout.overlaps(doc)
    icons = [e for e in doc["entities"] if e.get("tag") == "Icon"]
    assert not layout.repeated_icons(icons), layout.repeated_icons(icons)
    report(f"{width}x{height} ({width/height:.2f}:1), no overlaps, no repeated logo")


@case("an-official-icon-is-found-for-a-real-service")
def official_icons(report):
    """The reference diagram's quality is mostly its iconography. Nothing is bundled — 2,693
    official cloud SVGs, revised quarterly — so it is resolved on demand and the ranking is
    what stops a train being drawn for Railway."""
    icons = load("icons", ARCH / "scripts" / "icons.py")
    cfg = icons.config()
    # Stubbed: an eval must not fail because a third-party API is slow.
    square = b'<svg viewBox="0 0 256 256"></svg>'
    wide = b'<svg viewBox="0 0 512 99"></svg>'
    import json as _json
    def stub(url, timeout=20):
        if "iconify.design/search" in url:
            return _json.dumps({"icons": ["mdi:railway", "logos:railway",
                                          "logos:supabase", "logos:supabase-icon"]}).encode()
        if "svgl.app" in url:
            return b"[]"
        return wide if url.endswith("/supabase.svg") else square
    original = icons._get
    icons._get = stub
    try:
        railway = icons.resolve("Railway", None, cfg, "/tmp", {"paths": []})
        supabase = icons.resolve("Supabase", None, cfg, "/tmp", {"paths": []})
        junk = icons.resolve("machines static or ssr", None, cfg, "/tmp", {"paths": []})
    finally:
        icons._get = original
    assert railway and railway["id"] == "logos:railway", railway
    assert supabase and supabase["id"] == "logos:supabase-icon", supabase
    assert junk is None, junk
    report("a brand set beats a UI glyph set, a square mark beats a wordmark, "
           "and a weak match resolves to nothing at all")


@case("the-catalogue-can-be-extended-by-research")
def catalogue_extensible(report):
    """A workflow that can only choose from what somebody hardcoded keeps recommending the same
    seven vendors. A run scored eleven platform sets that all held the same five names."""
    scaffold = load("profile_scaffold", ARCH / "scripts" / "profile-scaffold.py")
    spec = {"id": "evalcloud", "name": "Eval Cloud", "kind": "paas",
            "what": "A researched platform that was never in the shipped catalogue.",
            "serves": {"cache": {"service": "Eval Cache", "managed": True,
                                 "interface": "standard"}},
            "pricing": {"model": "usage"}, "researched_on": "2026-09-29",
            "sources": ["https://example.invalid"]}
    profile, problems = scaffold.scaffold(spec, MODEL)
    assert not problems, problems
    assert caps.serves_natively(profile, "cache")
    # and it is held to the same standard as the shipped ones
    assert scaffold.check(ARCH / "assets" / "platforms", MODEL) == []
    bad = dict(spec, volatile={"certifications": {"value": "SOC 2"}})
    _, refused = scaffold.scaffold(bad, MODEL)
    assert refused, "an uncited certification was accepted"
    report(f"{len(PLATFORMS)} shipped profiles, and a researched one validates identically; "
           f"an uncited compliance claim is refused")


@case("a-capability-with-one-candidate-is-reported-as-thin")
def thin_reported(report):
    out = build(WORKER_BACKLOG, {"house_platforms": []})
    cat = out["catalogue"]
    assert cat["profiles"] == len(PLATFORMS)
    assert "candidates_per_capability" in cat
    counts = {c: len(v) for c, v in cat["candidates_per_capability"].items()}
    assert counts, "nothing was counted"
    for capability in cat["thin"]:
        assert counts[capability] == 1, (capability, counts[capability])
    assert "not a decision" in cat["thin_why"]
    report(f"{cat['profiles']} profiles; thin = {cat['thin'] or 'none'}; "
           f"identity has {counts.get('identity', 0)} candidates")


@case("a-runtime-contains-the-software-it-runs")
def runtime_containment(report):
    """"Django on Fargate" was one box carrying two products, and its icon was a coin toss
    between a framework and a cloud service. The split is a field, not a parse: the framework
    comes from the stack layer and the runtime from the platform profile."""
    layout = load("layout", ARCH / "scripts" / "layout.py")
    out = build(WORKER_BACKLOG, {"house_platforms": ["aws"]})
    application = next(c for c in out["components"] if c["capability"] == "application")
    runtime = (application.get("runs_on") or {}).get("service")
    assert runtime, "the application names no runtime, so the diagram cannot draw it inside one"
    assert runtime.lower() not in application["name"].lower(), \
        f"the label '{application['name']}' still carries its own runtime"

    doc = layout.document(out, MODEL, PLATFORMS, {"application:runtime": "aws-fargate"})
    group = next(e for e in doc["entities"] if e["id"] == "runtime-application")
    icon = next(e for e in doc["entities"] if e["id"] == "application")
    assert group["title"]["text"] == runtime
    assert group["title"].get("icon") == "aws-fargate", "the runtime has no icon of its own"
    assert icon["containerId"] == group["id"], "the software is not drawn inside its runtime"
    assert not layout.overlaps(doc)
    report(f"'{application['name']}' drawn inside '{runtime}', each with its own icon")


@case("a-capability-label-is-never-searched-for-a-logo")
def no_logo_for_a_label(report):
    """"Identity and access" resolves to PING IDENTITY's logo and "Model inference" to Model
    Context Protocol's. A capability that chose nothing has no product, and a component with no
    product is never looked up at all."""
    icons = load("icons", ARCH / "scripts" / "icons.py")
    out = build(WORKER_BACKLOG, {"house_platforms": ["aws"]})
    catalogue = caps.capabilities(MODEL)
    asked = []

    def stub(url, timeout=20):
        asked.append(url)
        return b"[]" if "svgl" in url else b'{"icons": []}'

    original = icons._get
    icons._get = stub
    try:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            names, _ = icons.resolve_components(out["components"], catalogue, cache_dir=tmp,
                                                manifest={}, index={"paths": []})
    finally:
        icons._get = original

    unnamed = [c for c in out["components"]
               if c.get("mode") != "actor" and not c.get("product")]
    for component in unnamed:
        assert names[component["id"]] == catalogue[component["capability"]]["icon"], \
            f"{component['id']} resolved something for a label that names no product"
        label = component["name"].split()[0].lower()
        assert not [u for u in asked if label in u.lower()], \
            f"'{component['name']}' was searched in a brand catalogue"
    report(f"{len(unnamed)} capability label(s) drew their own glyph and were never searched; "
           f"{len(out['components']) - len(unnamed)} named products were")


@case("no-connector-runs-over-a-component")
def connectors_stay_clear(report):
    """The router avoids obstacles but falls back to a STRAIGHT LINE when no corridor exists.
    The first real diagram had nineteen segments crossing components and nobody could have
    counted them from the PNG. This renders and measures rather than looking."""
    layout = load("layout", ARCH / "scripts" / "layout.py")
    routing = load("routing_check", ARCH / "scripts" / "routing-check.py")
    renderer = load("check_renderer", ARCH / "scripts" / "check-renderer.py")
    rd = load("render_diagram", ARCH / "scripts" / "render-diagram.py")

    chromium, _ = renderer.find_chromium()
    entry = ARCH / "assets" / "renderer" / "node_modules" / "@eraserlabs" / "diagrams"
    if not chromium or not entry.exists():
        report("SKIPPED — no local renderer; run /est-setup. Nothing was measured, so nothing "
               "is claimed about the routing.")
        return

    out = build(WORKER_BACKLOG, {"house_platforms": ["aws"]})
    doc = layout.document(out, MODEL, PLATFORMS)
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        png, measured = Path(tmp) / "a.png", Path(tmp) / "a.json"
        api, geometry = rd.api_render(doc, png, chromium, ARCH / "assets" / "renderer",
                                      ARCH / "assets" / "icon-cache", 1, "png", measured)
        assert api and api.get("ok"), f"the render failed: {api}"
        assert geometry, "the renderer returned no measured geometry"
        verdict = routing.check(geometry)
    assert verdict["ok"], "; ".join(
        f"{f['connection']} over {f['what'] or f['over']}" for f in verdict["findings"])
    report(verdict["checked"])


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--case")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    names = [args.case] if args.case else list(CASES)
    failures = 0
    for name in names:
        notes = []
        try:
            CASES[name](notes.append)
            status = "ok  "
        except AssertionError as exc:
            status, failures = "FAIL", failures + 1
            notes.append(str(exc))
        except KeyError:
            print(f"no such case: {name}", file=sys.stderr)
            return 2
        if not args.quiet:
            print(f"{status} {name}")
            for note in notes:
                print(f"       {note}")
    print(f"\n{len(names) - failures}/{len(names)} cases hold")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
