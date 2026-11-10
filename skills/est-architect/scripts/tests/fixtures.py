"""Shared fixture builders for est-architect.

The inventory fixtures carry REAL story prose rather than `Feature F1 does a thing.`, because
the capability map is built by matching signals against that prose. A fixture whose stories say
nothing would let every signal change pass here and fail on the first real backlog.
"""

import importlib.util
import json
import os
import tempfile
from pathlib import Path

# Module memory is found by walking UP from the working directory (`capabilities.memory_dir`).
# Run from inside an installed project, the suite therefore read that project's company memory:
# its own platform profiles and capabilities merged over the shipped ones, and five tests failed
# on a project that had done nothing wrong (passenger-seat, 2026-11-10). Every test starts from a
# directory with no `_bmad` above it; the tests that exercise memory resolution chdir into their
# own temporary root, as they always did.
os.chdir(tempfile.mkdtemp(prefix="est-architect-tests-"))

ROOT = Path(__file__).resolve().parents[3]
ARCH = ROOT / "est-architect"
EST = ROOT / "est-estimate"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


caps = load("capabilities", ARCH / "scripts" / "capabilities.py")


def model():
    return json.loads((ARCH / "assets" / "architecture-model.seed.json").read_text(encoding="utf-8"))


def cost_model():
    return json.loads((EST / "assets" / "cost-model.seed.json").read_text(encoding="utf-8"))


def tag(value, why="fixture"):
    return {"value": value, "why": why, "status": "inferred"}


def story(fid, name, description, epic="E1", surfaces=("backend", "frontend"),
          size="M", depends_on=(), tasks=()):
    return {
        "id": fid,
        "name": name,
        "description": description,
        "epic_id": epic,
        "surfaces": list(surfaces),
        "commitment": "committed",
        "citations": [{"source_id": "S1", "location": "§1", "quote": description}],
        "depends_on": [{"feature_id": d, "inferred": False, "evidence": "stated"}
                       for d in depends_on],
        "open_questions": [],
        "tasks": [{"id": f"{fid}-T{i}", "text": t} for i, t in enumerate(tasks, 1)],
        "tags": {"size_band": tag(size), "compressibility": tag("medium"),
                 "review_tier": tag("routine"), "clarity": tag("medium"),
                 "novelty": tag("standard")},
    }


def inventory(features, epics=None):
    epic_ids = sorted({f["epic_id"] for f in features})
    return {
        "schema_version": "1.1",
        "generated": "2026-09-29T00:00:00Z",
        "project": "Fixture",
        "granularity": "project",
        "working_language": "en",
        "sources": [{"id": "S1", "path": "docs/prd.md", "doc_type": "prd", "language": "en"}],
        "epics": epics or [{"id": e, "name": f"Epic {e}", "origin": "source",
                            "sequence": i + 1, "sequence_why": "stated", "citations": []}
                           for i, e in enumerate(epic_ids)],
        "features": features,
        "not_scope": [], "conflicts": [], "assumptions": [],
        "completeness_signals": {},
        "standing_scope": {"selected": []},
    }


def clinical():
    """A clinical monitoring platform, shaped like the reference diagram.

    Chosen because it exercises the capabilities whose sourcing is genuinely arguable —
    identity, payments, model inference, an analytics store — alongside ones that are settled,
    so the liveness test has both kinds to separate.
    """
    return inventory([
        story("F1", "Clinician sign-in with MFA",
              "Clinicians sign in with email and password plus a second factor. Sessions expire "
              "after inactivity.", epic="E1",
              tasks=("Password reset link by email", "Role-based access for clinician and admin")),
        story("F2", "Patient self-registration",
              "A patient creates an account, confirms their email address and consents to "
              "monitoring.", epic="E1"),
        story("F3", "Admin manages clinician permissions",
              "An operations admin grants and revokes clinician roles.", epic="E1"),
        story("F4", "Device vitals ingestion",
              "The platform ingests a continuous vitals feed from the wearable device API and "
              "stores it as a time series.", epic="E2", surfaces=("backend", "data"), size="L",
              tasks=("Retry failed webhook deliveries", "Queue readings for background processing")),
        story("F5", "Normalise device readings",
              "Readings from each device model are normalised into one canonical data model "
              "before storage.", epic="E2", surfaces=("backend", "data")),
        story("F6", "Clinician dashboard",
              "A single pane showing each patient's latest vitals and trend.", epic="E3",
              surfaces=("frontend", "design")),
        story("F7", "Trend detection and alerting",
              "An AI model detects anomalies in a patient's trend and raises an alert to the "
              "clinician.", epic="E3", size="L",
              tasks=("Summarise the anomaly in clinical language",)),
        story("F8", "Patient read-only view",
              "Patients see their own readings and nothing else.", epic="E3",
              surfaces=("frontend", "design")),
        story("F9", "Subscription checkout",
              "A subscriber pays monthly by card and can cancel.", epic="E4",
              tasks=("Handle failed payment retries", "Issue an invoice per billing period")),
        story("F10", "Billing admin",
              "Operations staff see subscription status and refund a payment.", epic="E4"),
        story("F11", "Clinical report export",
              "A clinician exports a patient report as a PDF document and downloads it.",
              epic="E5", surfaces=("backend", "frontend")),
        story("F12", "Compliance audit log",
              "Every access to patient data is recorded with who, what and when, and is "
              "retained.", epic="E5", surfaces=("backend", "data")),
        story("F13", "Operational monitoring and alerts",
              "System health is monitored and the on-call engineer is alerted on failure.",
              epic="E6", surfaces=("infra",)),
        story("F14", "Aggregate usage reporting",
              "Management sees aggregate statistics and trends across the cohort, exported to "
              "csv.", epic="E6", surfaces=("data", "backend")),
        story("F15", "SMS reminder to patients",
              "Patients receive an sms reminder to wear the device.", epic="E6"),
    ])


def thin():
    """Three stories, no dependencies, nothing material — the backlog where almost every
    sourcing decision should come back not live."""
    return inventory([
        story("F1", "Static marketing page", "A landing page describing the product.",
              epic="E1", surfaces=("frontend", "design")),
        story("F2", "Contact form", "A visitor submits a message.", epic="E1"),
        story("F3", "Admin views messages", "Staff read submitted messages.", epic="E1"),
    ])
