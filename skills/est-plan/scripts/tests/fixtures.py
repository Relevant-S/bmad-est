"""Shared fixture builders for est-plan.

Every fixture is priced through the real engine against the shipped cost model, because what
est-plan consumes is an estimate.json and a fixture that merely looks like one would let a
change to the estimate's shape pass here and fail in the field.
"""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EST = ROOT / "est-estimate"
PLAN = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


estimate_mod = load("estimate", EST / "scripts" / "estimate.py")
schedule = load("schedule", PLAN / "schedule.py")
staffing = load("staffing", PLAN / "staffing.py")
archetypes = load("archetypes", PLAN / "archetypes.py")
plan_mod = load("plan", PLAN / "plan.py")


def model():
    return json.loads((EST / "assets" / "cost-model.seed.json").read_text(encoding="utf-8"))


def tag(value, why="because", status="inferred"):
    return {"value": value, "why": why, "status": status}


def feature(fid, epic="E1", size="M", depends_on=(), name=None,
            surfaces=("backend", "frontend", "design", "infra", "data")):
    return {
        "id": fid,
        "name": name or f"Feature {fid}",
        "description": f"{fid} does a thing.",
        "epic_id": epic,
        "citations": [{"source_id": "S1", "location": "§1", "quote": f"{fid} is required."}],
        "commitment": "committed",
        "surfaces": list(surfaces),
        "depends_on": [{"feature_id": d, "inferred": False, "evidence": "stated"} for d in depends_on],
        "open_questions": [],
        "tags": {"size_band": tag(size), "compressibility": tag("high"),
                 "review_tier": tag("routine"), "clarity": tag("medium"),
                 "novelty": tag("standard")},
    }


def inventory(features, epics=None):
    epic_ids = sorted({f["epic_id"] for f in features})
    return {
        "schema_version": "1.1",
        "generated": "2026-09-16T00:00:00Z",
        "project": "Fixture",
        "granularity": "project",
        "working_language": "en",
        "sources": [{"id": "S1", "path": "docs/sow.md", "doc_type": "sow", "language": "en"}],
        "epics": epics or [{"id": e, "name": f"Epic {e}", "origin": "source",
                            "sequence": i + 1, "sequence_why": "stated order",
                            "citations": []}
                           for i, e in enumerate(epic_ids)],
        "features": features,
        "not_scope": [], "conflicts": [], "assumptions": [],
        "completeness_signals": {},
    }


def priced(features, epics=None, completeness=0.75, **over):
    m = model()
    options = {
        "mode": "presale", "team": m["team_profiles"]["balanced"], "team_name": "balanced",
        "stack": "standard_saas", "qa_platform": "web", "engagement": "standard",
        "team_size": None, "granularity": "project", "input_completeness": completeness,
        "inventory_path": "fixture.json", "generated": "2026-09-16T00:00:00Z",
    }
    options.update(over)
    return estimate_mod.build_estimate(inventory(features, epics), m, options)


def wide(n=24, epics=4, size="L"):
    """A backlog with no dependencies at all — every story independent.

    The case where parallelism is genuinely available, so a guardrail that refuses here is
    refusing for a reason that is not the dependency graph.
    """
    return [feature(f"F{i}", epic=f"E{i % epics + 1}", size=size) for i in range(1, n + 1)]


def chain(n=14, size="L"):
    """A single dependency chain. Nothing can run beside anything else.

    The case a second developer cannot help with, no matter how many hours are in the backlog.
    """
    return [feature(f"F{i}", epic=f"E{(i - 1) // 5 + 1}", size=size,
                    depends_on=() if i == 1 else (f"F{i - 1}",))
            for i in range(1, n + 1)]


def layered(per=4, layers=4, size="L"):
    """Epics in a chain, but only ONE story per epic carrying the cross-epic edge.

    The shape that broke the real plan. Every story-level dependency can be honoured and the
    epics still build in the wrong order, because the other `per - 1` stories in each epic are
    unconstrained and go to whoever is idle. Kitespire's Authentication epic had one gated
    story in eight.
    """
    out = []
    for layer in range(1, layers + 1):
        epic = f"E{layer}"
        for i in range(1, per + 1):
            fid = f"F{layer}{i:02d}"
            # Only the first story of each epic names its predecessor.
            deps = (f"F{layer - 1}01",) if layer > 1 and i == 1 else ()
            out.append(feature(fid, epic=epic, size=size, depends_on=deps))
    return out


def declared_only(per=3, size="M"):
    """Two epics ordered by `depends_on_epics` alone, with no story edge between them.

    The ordering `depends_on_epics` exists to record — Kitespire's three were violated in the
    shipped plan because nothing but `foundation_epics()` ever read them.
    """
    features = [feature(f"F{n}{i}", epic=f"E{n}", size=size)
                for n in (1, 2) for i in range(1, per + 1)]
    epics = [{"id": "E1", "name": "Ground", "origin": "source", "sequence": 1,
              "sequence_why": "stated", "citations": []},
             {"id": "E2", "name": "Upper", "origin": "source", "sequence": 2,
              "sequence_why": "stated", "citations": [],
              "depends_on_epics": [{"epic_id": "E1", "why": "the SOW says so"}]}]
    return features, epics


def two_streams(per=10, size="L"):
    """Two independent chains in two epics — the shape a second developer is FOR."""
    out = []
    for stream, epic in ((1, "E1"), (2, "E2")):
        for i in range(1, per + 1):
            fid = f"F{stream}{i:02d}"
            out.append(feature(fid, epic=epic, size=size,
                               depends_on=() if i == 1 else (f"F{stream}{i - 1:02d}",)))
    return out


def team_of(shape, m=None, roster=None):
    return plan_mod.build_team(shape, m or model(), roster or {})


def run(estimate, shape, archetype="pipelined", m=None, roster=None):
    m = m or model()
    policy = archetypes.POLICIES[archetype](estimate, m)
    return schedule.simulate(estimate, m, team_of(shape, m, roster), policy)


def judge_shape(estimate, role, count, shape=None, roster=None, model_=None):
    """Judge a headcount the way plan.py does — against a real simulation of the shape.

    The guardrail reads a schedule now, not a span somebody guessed. A test that hands it a
    number of weeks is testing the number it picked, which is how the old gate came to report
    the bottleneck role as exactly 100% occupied in every case.
    """
    m = model_ or model()
    shape = dict(shape or {"ba": 1, "ux": 1, "qa": 1, "devops": 1}, **{role: count})
    fewer = dict(shape, **{role: max(1, count - 1)})
    return staffing.judge(estimate, m, role, count,
                          run(estimate, shape, m=m, roster=roster), (roster or {}).get(role, 0),
                          before=run(estimate, fewer, m=m, roster=roster))


def span_for(estimate, role, count, model_=None):
    """The span a role's own backlog implies at this headcount.

    Tests that pass a span by hand are testing the number they guessed. The sweep derives it
    from the bottleneck role, so a fixture should too — otherwise a guardrail assertion fails
    because the fixture's imagined calendar disagreed with its own backlog.
    """
    rate = (model_ or model())["calendar"]["hours_per_person_week"]
    return staffing.role_demand(estimate).get(role, 0.0) / (max(1, count) * rate)
