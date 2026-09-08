#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Adversarial cases for est-estimate: whole-inventory shapes that break estimators.

These are not unit tests. Each case is a realistic inventory shape whose *emergent*
behaviour is the claim being checked — that a thin brief cannot look certain, that
compression does not rescue a sensitive feature, that adding people cannot beat a
dependency chain. Unit tests protect the arithmetic; these protect the conclusions,
which is where a plausible-looking estimate goes wrong.

    uv run evals/run-cases.py                 # run every case
    uv run evals/run-cases.py --write-fixtures evals/fixtures   # also save the inventories

Exit 0 when every case holds, 1 when any fails.
"""

import argparse
import importlib.util
import json
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("estimate", SKILL / "scripts" / "estimate.py")
est = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(est)
MODEL = json.loads((SKILL / "assets" / "cost-model.seed.json").read_text(encoding="utf-8"))


def tag(value, why="fixture", status="inferred"):
    return {"value": value, "why": why, "status": status}


def feature(fid, name, size="M", comp="high", tier="routine", clarity="medium",
            novelty="standard", **extra):
    base = {
        "id": fid, "name": name, "description": f"{name}.",
        "citations": [{"source_id": "S1", "location": "§1", "quote": f"{name} is required."}],
        "commitment": "committed",
        "tags": {"size_band": tag(size), "compressibility": tag(comp), "review_tier": tag(tier),
                 "clarity": tag(clarity), "novelty": tag(novelty)},
        "depends_on": [], "open_questions": [],
    }
    base.update(extra)
    return base


def inventory(name, features, granularity="project"):
    return {
        "schema_version": "1.0", "generated": "2026-09-07T00:00:00Z", "project": name,
        "granularity": granularity, "working_language": "en",
        "sources": [{"id": "S1", "path": "fixture.md", "doc_type": "sow", "language": "en"}],
        "features": features, "not_scope": [], "conflicts": [], "assumptions": [],
        "completeness_signals": {},
    }


def run(inv, completeness=0.6, **over):
    opts = {
        "mode": "presale", "team": MODEL["team_profiles"]["balanced"], "team_name": "balanced",
        "stack": "standard_saas", "qa_platform": "web", "engagement": "standard",
        "team_size": None, "granularity": inv["granularity"], "input_completeness": completeness,
        "inventory_path": "fixture.json", "generated": "2026-09-07T00:00:00Z",
    }
    opts.update(over)
    return est.build_estimate(inv, MODEL, opts)


def extracted(estimate):
    """The features that came from the source, without the standing setup work.

    Cases about how the cost model treats extracted scope have to exclude it: standing work
    is a constant added to both sides of every comparison, so leaving it in turns a claim
    about review tiers into a statement about the size of the setup catalogue."""
    return [f for f in estimate["features"] if f.get("origin") != "standing"]


def rel_band(e):
    t = e["total_hours"]
    return (t["high"] - t["low"]) / 2 / t["likely"]


# --- the cases ---------------------------------------------------------------

def case_thin_brief():
    """Two paragraphs of scope. The band must be wide enough that nobody mistakes it for a quote."""
    inv = inventory("Thin brief", [
        feature("F1", "Depot portal", size="L", clarity="low"),
        feature("F2", "Driver app", size="L", clarity="low"),
        feature("F3", "Offline mode", size="L", comp="low", clarity="low", novelty="novel"),
    ])
    e = run(inv, completeness=0.08)
    return e, [
        ("band is at least ±40% of the central figure", rel_band(e) >= 0.40),
        ("every feature raises a narrowing question",
         len({q["question"].split("(")[-1].rstrip(")") for q in e["narrowing_questions"]}) >= 3),
        ("questions are ranked by band removed",
         [q["band_reduction_hours"] for q in e["narrowing_questions"]] ==
         sorted((q["band_reduction_hours"] for q in e["narrowing_questions"]), reverse=True)),
    ]


def case_compression_does_not_rescue_sensitive_work():
    """The module's central claim, at inventory scale rather than per feature."""
    routine = run(inventory("Routine", [feature(f"F{i}", f"CRUD {i}", tier="routine") for i in range(1, 9)]))
    sensitive = run(inventory("Sensitive", [feature(f"F{i}", f"Payments {i}", tier="sensitive") for i in range(1, 9)]))
    # Phase totals include standing work's own review, which is the same on both sides and
    # would flatten the ratio the claim is about. Compare the extracted scope's review.
    r_review = sum(f["component_hours"]["review"] for f in extracted(routine))
    s_review = sum(f["component_hours"]["review"] for f in extracted(sensitive))
    r_features = sum(f["hours"] for f in extracted(routine))
    s_features = sum(f["hours"] for f in extracted(sensitive))
    ratio_features = s_features / r_features
    ratio_total = sensitive["total_hours"]["likely"] / routine["total_hours"]["likely"]
    return sensitive, [
        ("identical build hours despite very different totals",
         abs(sum(f["component_hours"]["build"] for f in extracted(routine))
             - sum(f["component_hours"]["build"] for f in extracted(sensitive))) < 0.5),
        ("review is over four times higher for the sensitive scope", s_review > 4 * r_review),
        ("review outweighs build once the work is sensitive",
         s_review > sum(f["component_hours"]["build"] for f in extracted(sensitive))),
        ("feature work costs far more when the scope is sensitive", ratio_features > 1.7),
        # Project-level costs do not care about review tier, so a per-feature effect always
        # arrives diluted at the total. Anyone quoting the feature-level multiple as a project
        # multiple is making the same mistake as quoting build compression as project compression.
        ("the effect still moves the total, but arrives diluted",
         1.25 < ratio_total < ratio_features),
    ]


def case_deep_dependency_chain():
    """Twelve features in a line. Throwing people at it cannot beat the critical path."""
    features = [feature("F1", "Foundation", size="L")]
    for i in range(2, 13):
        features.append(feature(f"F{i}", f"Step {i}", size="M",
                                depends_on=[{"feature_id": f"F{i-1}", "inferred": True}]))
    inv = inventory("Chain", features)
    small = run(inv, team_size=2)
    large = run(inv, team_size=6)
    return large, [
        ("the critical path runs the full chain", len(large["dependencies"]["chain"]) == 12),
        ("tripling the team does not triple the speed",
         large["duration"]["weeks"] > small["duration"]["weeks"] / 3),
        ("duration is never reported without its basis", "not a commitment" in large["duration"]["basis"]),
    ]


def case_mostly_additional_scope():
    """Most of the work is outside the contract. Both the share and the standalone cost must be visible."""
    inv = inventory("Creep", [
        feature("F1", "In the SOW", size="M"),
        *[feature(f"F{i}", f"Raised on the call {i}", size="M",
                  scope_status="outside_agreed_scope") for i in range(2, 6)],
    ])
    e = run(inv)
    agreed = e["scope_split"]["in_agreed_scope"]
    extra = e["scope_split"]["outside_agreed_scope"]
    return e, [
        ("both scopes are reported, never merged", agreed and extra),
        ("additional scope dominates", extra["apportioned_hours"] > agreed["apportioned_hours"]),
        # Every scope group, not just the two commercial ones: standing work is its own
        # group now, and an assertion that quietly ignored it would stop noticing the day
        # apportionment lost a group.
        ("apportioned shares sum to the total",
         abs(sum(g["apportioned_hours"] for k, g in e["scope_split"].items()
                 if not k.startswith("_")) - e["total_hours"]["likely"]) < 1.0),
        ("dropping the additions saves less than their apportioned share",
         agreed["standalone_hours"] > agreed["apportioned_hours"]),
    ]


def case_undecomposed_scope():
    """Everything tagged XL. The estimate must push back rather than price a guess quietly."""
    inv = inventory("XL", [feature(f"F{i}", f"Product area {i}", size="XL", clarity="low")
                           for i in range(1, 4)])
    e = run(inv, completeness=0.2)
    return e, [
        ("breaking up the XL features is offered as a question",
         any("into its parts" in q["question"] for q in e["narrowing_questions"])),
        ("the band is wide, not falsely precise", rel_band(e) >= 0.30),
    ]


def case_mobile_qa_capability():
    """The company's automated mobile QA is a real coefficient, not a footnote."""
    inv = inventory("Mobile", [feature(f"F{i}", f"Screen {i}", comp="medium") for i in range(1, 9)])
    default = run(inv, qa_platform="mobile_manual")
    theirs = run(inv, qa_platform="mobile_mcp_automated")
    return theirs, [
        ("automated mobile QA materially lowers the number",
         theirs["total_hours"]["likely"] < 0.85 * default["total_hours"]["likely"]),
        ("QA is still a real line item, not zeroed", theirs["by_phase"]["qa"]["hours"] > 0),
    ]


def case_missing_citations():
    """An hour with no source behind it must be reported, not quietly priced."""
    inv = inventory("Untraceable", [
        feature("F1", "Properly cited"),
        feature("F2", "Invented", citations=[]),
    ])
    e = run(inv)
    return e, [
        ("the uncited feature is named in the findings",
         any("F2" in f and "no citation" in f for f in e["traceability"]["findings"])),
        ("it is still priced, so the problem is visible rather than hidden",
         len(extracted(e)) == 2),
    ]


def case_single_small_feature():
    """A change request. Project overheads must not swamp a one-feature estimate silently."""
    e = run(inventory("Change request", [feature("F1", "Add a column", size="XS")],
                      granularity="feature"))
    return e, [
        ("no planning documents are charged at feature granularity",
         e["planning_volume"]["documents"] == []),
        ("the estimate is still positive and bounded", 0 < e["total_hours"]["likely"] < 200),
    ]


CASES = {
    "thin-brief": case_thin_brief,
    "compression-does-not-rescue-sensitive-work": case_compression_does_not_rescue_sensitive_work,
    "deep-dependency-chain": case_deep_dependency_chain,
    "mostly-additional-scope": case_mostly_additional_scope,
    "undecomposed-scope": case_undecomposed_scope,
    "mobile-qa-capability": case_mobile_qa_capability,
    "missing-citations": case_missing_citations,
    "single-small-feature": case_single_small_feature,
}


def main():
    ap = argparse.ArgumentParser(description="Run est-estimate's adversarial cases.")
    ap.add_argument("--case", help="run one case by name")
    ap.add_argument("--write-fixtures", metavar="DIR",
                    help="also write each case's estimate JSON there, for inspection")
    ap.add_argument("--quiet", action="store_true", help="only report failures")
    args = ap.parse_args()

    names = [args.case] if args.case else list(CASES)
    failures = []
    for name in names:
        if name not in CASES:
            print(f"unknown case '{name}' — known: {', '.join(CASES)}", file=sys.stderr)
            return 2
        estimate, checks = CASES[name]()
        bad = [label for label, ok in checks if not ok]
        failures.extend(f"{name}: {label}" for label in bad)
        if not args.quiet or bad:
            mark = "FAIL" if bad else "ok  "
            print(f"{mark} {name} — {len(checks) - len(bad)}/{len(checks)} held "
                  f"({estimate['total_hours']['likely']:,.0f}h)")
            for label in bad:
                print(f"       ✗ {label}")
        if args.write_fixtures:
            out = Path(args.write_fixtures)
            out.mkdir(parents=True, exist_ok=True)
            (out / f"{name}.json").write_text(
                json.dumps(estimate, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"\n{len(names) - len({f.split(':')[0] for f in failures})}/{len(names)} cases fully held")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
