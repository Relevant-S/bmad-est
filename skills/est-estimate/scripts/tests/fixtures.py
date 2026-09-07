"""Shared fixture builders for est-estimate script tests."""

import copy
import json
from pathlib import Path

MODEL_PATH = Path(__file__).resolve().parent.parent.parent / "assets" / "cost-model.seed.json"


def model():
    return json.loads(MODEL_PATH.read_text(encoding="utf-8"))


def tag(value, why="because", status="inferred"):
    return {"value": value, "why": why, "status": status}


def feature(fid="F1", name="A feature", size="M", compressibility="high",
            review_tier="routine", clarity="medium", novelty="standard", **overrides):
    base = {
        "id": fid,
        "name": name,
        "description": f"{name} description.",
        "citations": [{"source_id": "S1", "location": "§1", "quote": f"{name} is required."}],
        "commitment": "committed",
        "tags": {
            "size_band": tag(size),
            "compressibility": tag(compressibility),
            "review_tier": tag(review_tier),
            "clarity": tag(clarity),
            "novelty": tag(novelty),
        },
        "depends_on": [],
        "open_questions": [],
    }
    base.update(copy.deepcopy(overrides))
    return base


def inventory(features=None, granularity="project", **overrides):
    base = {
        "schema_version": "1.0",
        "generated": "2026-09-07T12:00:00Z",
        "project": "Test Project",
        "granularity": granularity,
        "working_language": "en",
        "sources": [{"id": "S1", "path": "docs/sow.docx", "doc_type": "sow", "language": "en"}],
        "features": features if features is not None else [feature()],
        "not_scope": [],
        "conflicts": [],
        "assumptions": [],
        "completeness_signals": {},
    }
    base.update(copy.deepcopy(overrides))
    return base


def options(mode="presale", completeness=0.6, team="balanced", **overrides):
    m = model()
    base = {
        "mode": mode,
        "team": m["team_profiles"][team],
        "team_name": team,
        "stack": "standard_saas",
        "qa_platform": "web",
        "engagement": "standard",
        "team_size": None,
        "granularity": "project",
        "input_completeness": completeness,
        "inventory_path": "feature-inventory.json",
        "generated": "2026-09-07T12:00:00Z",
    }
    base.update(overrides)
    return base
