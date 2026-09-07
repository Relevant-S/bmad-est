"""Shared fixture builders for est-agent-estimator script tests.

Estimates are built by running est-estimate's real engine over est-estimate's own fixture
inventories, so a scenario is always tested against a number the engine actually produced.
A hand-written estimate would let a scenario reproduce a baseline this module invented.
"""

import importlib.util
import json
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent.parent.parent
ENGINE = SKILLS / "est-estimate" / "scripts" / "estimate.py"
EST_FIXTURES = SKILLS / "est-estimate" / "scripts" / "tests"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


engine = _load("estimate", ENGINE)
# Loaded by path under its own module name: a plain import would resolve to this file.
est_fx = _load("est_estimate_fixtures", EST_FIXTURES / "fixtures.py")


def scenario_module():
    return _load("scenario", Path(__file__).resolve().parent.parent / "scenario.py")


def feature(fid="F1", **kw):
    return est_fx.feature(fid, **kw)


def depends(fid, *on, **kw):
    f = est_fx.feature(fid, **kw)
    f["depends_on"] = [{"feature_id": o, "inferred": False, "evidence": "stated"} for o in on]
    return f


def estimate(features=None, team="balanced", completeness=0.6, mode="presale",
             granularity="project", **option_overrides):
    """A real priced estimate, snapshot and all, as est-estimate would have written it."""
    inv = est_fx.inventory(features=features, granularity=granularity)
    opts = est_fx.options(mode=mode, completeness=completeness, team=team,
                          granularity=granularity, **option_overrides)
    est = engine.build_estimate(inv, est_fx.model(), opts)
    return est


def write(tmp, name, payload):
    target = Path(tmp) / name
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return str(target)
