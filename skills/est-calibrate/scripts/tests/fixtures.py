"""Shared fixtures for est-calibrate script tests."""

import json
from pathlib import Path

MODULE = Path(__file__).resolve().parents[3]
MODEL_PATH = MODULE / "est-estimate" / "assets" / "cost-model.seed.json"


def model():
    return json.loads(MODEL_PATH.read_text(encoding="utf-8"))


def actuals(hours=500.0, **over):
    base = {"granularity": "project", "delivery_hours": hours, "scope_delivered": "as_estimated",
            "source": "test", "confidence": "measured", "captured": "2026-06-01"}
    base.update(over)
    return base


def entry(eid="EST-20260101-alpha", likely=400.0, low=320.0, high=480.0, sd=80.0,
          actual=500.0, features=None, **over):
    base = {
        "schema_version": "1.0", "project": "Alpha", "granularity": "project", "mode": "presale",
        "generated": "2026-01-01T00:00:00Z",
        "total_hours": {"low": low, "likely": likely, "high": high},
        "confidence": {"input_completeness": 0.6, "aggregated_sd": sd, "band_multiplier": 1.5},
        "inputs": {"team_profile": "balanced", "stack": "standard_saas",
                   "qa_platform": "web", "engagement": "standard", "team_size": None},
        "features": features if features is not None else [feature("F1")],
        "by_phase": {"build": {"hours": 100.0, "sd": 10.0}, "qa": {"hours": 60.0, "sd": 8.0},
                     "planning-review": {"hours": 20.0, "sd": 1.0}},
        "by_role": {"dev": 200.0, "architect": 120.0, "qa": 60.0, "ba": 20.0},
        "ledger": {"id": eid, "status": "delivered",
                   "actuals": actuals(actual) if actual is not None else None},
    }
    base.update(over)
    return base


def feature(fid="F1", tier="routine", size="M", comp="high", hours=50.0):
    return {
        "id": fid, "name": f"Feature {fid}", "hours": hours, "sd": 8.0,
        "scope_status": "in_agreed_scope", "commitment": "committed",
        "tags": {"size_band": size, "compressibility": comp, "review_tier": tier,
                 "clarity": "medium", "novelty": "standard"},
        "tag_why": {axis: "because" for axis in
                    ("size_band", "compressibility", "review_tier", "clarity", "novelty")},
        "tag_status": {axis: "inferred" for axis in
                       ("size_band", "compressibility", "review_tier", "clarity", "novelty")},
        "citations": [{"source_id": "S1", "location": "§1", "quote": "required"}],
        "component_hours": {"build": 15.0, "spec": 10.0, "review": 20.0, "rework": 5.0},
        "depends_on": [], "open_questions": [],
    }
