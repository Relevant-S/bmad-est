"""Shared fixture builders for est-scope-extract script tests."""

import copy


def tag(value, why="because", status="inferred", **extra):
    return {"value": value, "why": why, "status": status, **extra}


def signals(**values):
    """completeness_signals in schema shape: every signal carries its reason."""
    return {name: {"value": value, "why": f"stated in the sources: {value}", "status": "inferred"}
            for name, value in values.items()}


def feature(fid="F1", name="User login", **overrides):
    base = {
        "id": fid,
        "name": name,
        "description": "Email and password authentication with session handling.",
        "citations": [
            {"source_id": "S1", "location": "§2.1", "quote": "Users must be able to log in with an email and password."}
        ],
        "commitment": "committed",
        "tags": {
            "size_band": tag("M"),
            "compressibility": tag("high"),
            "review_tier": tag("sensitive", triggers=["log in", "password"]),
            "clarity": tag("medium"),
            "novelty": tag("standard"),
        },
        "depends_on": [],
        "open_questions": [],
    }
    base.update(overrides)
    return base


def inventory(**overrides):
    base = {
        "schema_version": "1.0",
        "generated": "2026-09-07T12:00:00Z",
        "project": "Acme Portal",
        "granularity": "project",
        "working_language": "en",
        "sources": [
            {"id": "S1", "path": "docs/sow.docx", "doc_type": "sow",
             "language": "en", "converter": "python-docx"}
        ],
        "features": [feature()],
        "not_scope": [
            {"source_id": "S1", "location": "§7", "quote": "Payment terms are net 30.",
             "reason": "commercial terms, not scope"}
        ],
        "conflicts": [],
        "assumptions": [],
        "completeness_signals": signals(
            acceptance_criteria="some", stack_specified="partial",
            integrations_named="partial", nfrs_stated="none",
            data_model_described="none", ui_defined="described",
        ),
    }
    base.update(copy.deepcopy(overrides))
    return base
