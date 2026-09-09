#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Validate the calibrator by recovery against a known truth.

There are no real actuals yet, and waiting for them would mean shipping a statistical
engine nobody has tested. So: perturb a copy of the cost model, generate actuals from the
perturbed model, run the calibrator over ledger entries priced with the *unperturbed* one,
and check it detects the bias in the right coefficient and the right direction.

This is stronger evidence than a handful of real projects would give, because the answer is
known in advance. It also tests the failure directions that matter more than the successes:
that a well-calibrated model produces no proposals, and that one weird project does not
move a coefficient.

    uv run evals/ground-truth.py

Exit 0 when every case holds, 1 when any fails.
"""

import argparse
import importlib.util
import json
import random
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
MODULE = SKILL.parent


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


analyze = load(SKILL / "scripts" / "analyze.py", "analyze")
backtest = load(SKILL / "scripts" / "backtest.py", "backtest")
est = load(MODULE / "est-estimate" / "scripts" / "estimate.py", "estimate")
SEED_MODEL = json.loads(
    (MODULE / "est-estimate" / "assets" / "cost-model.seed.json").read_text(encoding="utf-8"))


# --- synthetic projects -------------------------------------------------------

def tag(value):
    return {"value": value, "why": "synthetic fixture", "status": "inferred"}


def feature(fid, size, comp, tier, clarity="medium", novelty="standard"):
    return {
        "id": fid, "name": f"Feature {fid}", "description": "synthetic",
        "citations": [{"source_id": "S1", "location": "§1", "quote": "synthetic"}],
        "commitment": "committed",
        "tags": {"size_band": tag(size), "compressibility": tag(comp), "review_tier": tag(tier),
                 "clarity": tag(clarity), "novelty": tag(novelty)},
        "depends_on": [], "open_questions": [],
    }


def inventory(name, features):
    return {
        "schema_version": "1.0", "generated": "2026-01-01T00:00:00Z", "project": name,
        "granularity": "project", "working_language": "en",
        "sources": [{"id": "S1", "path": "x.md", "doc_type": "sow", "language": "en"}],
        "features": features, "not_scope": [], "conflicts": [], "assumptions": [],
        "completeness_signals": {},
    }


def price(inv, model, completeness=0.7):
    return est.build_estimate(inv, model, {
        "mode": "presale", "team": model["team_profiles"]["balanced"], "team_name": "balanced",
        "stack": "standard_saas", "qa_platform": "web", "engagement": "standard",
        "team_size": None, "granularity": "project", "input_completeness": completeness,
        "inventory_path": "synthetic.json", "generated": "2026-01-01T00:00:00Z",
    })


def project_mix(rng, n, sensitive_share, uniform=False):
    """A project of a given shape.

    `uniform` fixes the feature sizes as well as the tier counts. Both are needed: the
    regression guard measures each tier's share of *hours*, so fixing only the tier count
    while sampling sizes still produced a 0.50 span across projects built to one recipe —
    which is real, separable variation, and the guard was right to accept it. A fixture
    claiming uniformity has to actually be uniform or it tests the opposite of its name.
    """
    sensitive = round(n * sensitive_share)
    sizes = ["M"] * n if uniform else [rng.choice(["S", "M", "M", "L"]) for _ in range(n)]
    comps = ["high"] * n if uniform else [rng.choice(["high", "high", "medium"]) for _ in range(n)]
    return [feature(f"F{i}", sizes[i - 1], comps[i - 1],
                    "sensitive" if i <= sensitive else "routine")
            for i in range(1, n + 1)]


def make_ledger(rng, count, perturbed_model, noise=0.10, shares=None, completeness=0.7,
                uniform=False):
    """Ledger entries priced with the SEED model, carrying actuals from the perturbed one.

    The gap between the two is the bias the calibrator has to find. Noise is multiplicative
    so that projects of different size contribute comparably, as real variation does.
    """
    entries = []
    for i in range(count):
        share = shares[i % len(shares)] if shares else 0.4
        # 60 stories per project. This has been raised twice for the same reason and it is
        # worth stating once: a band bias is only detectable in a project total to the extent
        # story work IS the total. At 8 stories the fixed planning cost dominated; at 24, under
        # the 3.0 bands, story work is 57% of the total and a 20% band perturbation moves the
        # project 7.8% — just under the 8% deadband, so the calibrator correctly proposed
        # nothing and the case failed for a reason that had nothing to do with the calibrator.
        # At 60 it is 61% and the same perturbation moves the total 11.7%. That is a fact about
        # the fixture, not about detection: on a real project this small the honest answer is
        # that a band bias cannot be separated from the setup cost, which is why analyze.py
        # has a deadband at all.
        inv = inventory(f"Project {i+1}", project_mix(rng, 60, share, uniform))
        estimate = price(inv, SEED_MODEL, completeness)
        truth = price(inv, perturbed_model, completeness)
        actual = truth["total_hours"]["likely"] * (1 + rng.gauss(0, noise))
        estimate["ledger"] = {
            "id": f"EST-2026010{i+1}-project-{i+1}", "status": "delivered",
            "actuals": {
                "granularity": "project", "delivery_hours": round(actual, 1),
                "scope_delivered": "as_estimated", "source": "synthetic", "confidence": "measured",
                "captured": "2026-06-01",
                "by_phase": {p: round(truth["by_phase"][p]["hours"] * (1 + rng.gauss(0, noise)), 1)
                             for p in truth["by_phase"]},
            },
        }
        entries.append(estimate)
    return entries


def perturb(**changes):
    """A copy of the seed model with specific coefficients moved."""
    model = json.loads(json.dumps(SEED_MODEL))
    for path, factor in changes.items():
        node = model
        parts = path.split(".")
        for part in parts[:-1]:
            node = node[part]
        leaf = node[parts[-1]]
        if isinstance(leaf, dict):
            for key in ("lo", "likely", "hi"):
                if key in leaf:
                    leaf[key] = round(leaf[key] * factor, 4)
        else:
            node[parts[-1]] = round(leaf * factor, 4)
    return model


# --- cases --------------------------------------------------------------------

def run(entries, min_samples=3):
    return analyze.build_analysis(entries, SEED_MODEL, min_samples, 8)


def find(proposals, coefficient):
    return next((p for p in proposals if p["coefficient"] == coefficient), None)


def case_detects_under_estimation():
    """Everything costs 25% more than the model says. The calibrator must see the direction."""
    rng = random.Random(11)
    model = perturb(**{"size_bands.S": 1.25, "size_bands.M": 1.25, "size_bands.L": 1.25})
    a = run(make_ledger(rng, 6, model, noise=0.06))
    scale = find(a["proposals"], "size_bands.*")
    return a, [
        ("a sizing proposal is raised", scale is not None),
        ("it points upward", scale is not None and scale["proposed"] > 1.0),
        ("the underlying signal lands near the true 1.25x",
         scale is not None and 1.12 <= scale["point_estimate"] <= 1.38),
        ("the proposal is shrunk toward the current value, not jumped to",
         scale is not None and 1.0 < scale["proposed"] < scale["point_estimate"]),
        ("the direction is reported as under-estimating",
         a["accuracy"]["direction"] == "under-estimating"),
        ("the evidence names the sample size", scale is not None and scale["samples"] == 6),
    ]


def case_detects_over_estimation():
    rng = random.Random(23)
    model = perturb(**{"size_bands.S": 0.8, "size_bands.M": 0.8, "size_bands.L": 0.8})
    a = run(make_ledger(rng, 6, model, noise=0.06))
    scale = find(a["proposals"], "size_bands.*")
    return a, [
        ("a sizing proposal is raised", scale is not None),
        ("it points downward", scale is not None and scale["proposed"] < 1.0),
        ("the proposal is shrunk toward the current value",
         scale is not None and scale["point_estimate"] < scale["proposed"] < 1.0),
        ("the direction is reported as over-estimating",
         a["accuracy"]["direction"] == "over-estimating"),
    ]


def case_a_calibrated_model_proposes_nothing():
    """The most important failure direction: no change when the model is already right."""
    rng = random.Random(37)
    a = run(make_ledger(rng, 6, SEED_MODEL, noise=0.05))
    scale = find(a["proposals"], "size_bands.*")
    return a, [
        ("no sizing change is proposed", scale is None),
        ("no systematic bias is claimed", a["accuracy"]["direction"] == "no systematic bias"),
        ("the band hit rate is reported", a["accuracy"]["band_hit_rate"] is not None),
    ]


def case_band_width_is_calibrated_from_totals_alone():
    """Wide real variation with no bias: the central figure is right, the range is too narrow."""
    rng = random.Random(41)
    entries = make_ledger(rng, 12, SEED_MODEL, noise=0.55)
    for e in entries:                      # strip everything but the total
        e["ledger"]["actuals"].pop("by_phase", None)
    a = run(entries)
    risk = find(a["proposals"], "uncertainty.model_risk")
    return a, [
        ("band width is proposed from totals alone", risk is not None),
        ("it widens rather than narrows", risk is not None and risk["proposed"] > risk["current"]),
        ("it says it needs only project totals",
         risk is not None and risk["needs"] == "project totals only"),
        ("the hit rate came in under target",
         a["accuracy"]["band_hit_rate"] < a["accuracy"]["band_hit_target"]),
    ]


def case_a_noisy_spread_estimate_does_not_move_the_band():
    """The complement of the case above, and the one that matters more.

    Measured over few projects the residual spread is itself noisy: an observed 1.14 on
    eight samples is indistinguishable from 1.0. The calibrator must not propose a band
    change on that, or it spends the company's trust chasing its own sampling error.

    The noise level is expressed as a share of the project total, so it has to track the
    model's own band to keep testing the same thing, and it has now moved twice for that
    reason. It was 0.35 while overhead was priced as a three-point share of an already
    three-point subtotal — a compounding that inflated feature variance to roughly 0.28 of
    the mean. Overhead moved to the schedule and 0.18 was the level that again landed a mild
    spread just above 1.0. Under the 3.0 bands, which span 4.8x rather than 90x, feature
    variance is smaller again and 0.18 produces a spread of 0.70 — comfortably INSIDE the
    band, which tests nothing. 0.30 is the level that lands at 1.17.

    That the number keeps falling is itself the finding: each change made the model's own
    range a better description of real variation, so more real noise is needed before the
    calibrator sees anything worth reacting to. Raising it past ~0.40 tests that it reacts to
    a genuine signal, which is the case above, not this one.
    """
    rng = random.Random(41)
    entries = make_ledger(rng, 8, SEED_MODEL, noise=0.30)
    for e in entries:
        e["ledger"]["actuals"].pop("by_phase", None)
    a = run(entries)
    risk = find(a["proposals"], "uncertainty.model_risk")
    spread = a["accuracy"]["residual_spread"]
    return a, [
        ("the mild spread is within sampling tolerance for eight projects", 1.0 < spread < 1.4),
        ("no band change is proposed on it", risk is None),
        ("the accuracy figures are still reported", a["accuracy"]["band_hit_rate"] is not None),
    ]


def case_one_outlier_does_not_move_a_coefficient():
    """A single disastrous project is a story, not a pattern."""
    rng = random.Random(53)
    entries = make_ledger(rng, 6, SEED_MODEL, noise=0.05)
    entries[0]["ledger"]["actuals"]["delivery_hours"] *= 3.0     # one catastrophe
    a = run(entries)
    scale = find(a["proposals"], "size_bands.*")
    return a, [
        ("no sizing change is proposed on the strength of one project", scale is None),
        ("the median stays near zero", abs(a["accuracy"]["median_error_pct"]) < 8),
    ]


def case_too_few_projects_proposes_nothing():
    rng = random.Random(67)
    model = perturb(**{"size_bands.M": 1.4})
    a = run(make_ledger(rng, 2, model, noise=0.05), min_samples=3)
    return a, [
        ("nothing is proposed below the sample threshold", a["proposals"] == []),
        ("the accuracy figures are still reported", a["accuracy"]["samples"] == 2),
    ]


def case_phase_level_actuals_target_the_right_coefficient():
    """QA ran hot. With phase-level hours that is a QA proposal, not a global scale."""
    rng = random.Random(71)
    model = perturb(**{"qa.web": 1.6})
    a = run(make_ledger(rng, 6, model, noise=0.05))
    qa = find(a["proposals"], "qa")
    return a, [
        ("a QA coefficient change is proposed", qa is not None),
        ("it points upward", qa is not None and qa["proposed"] > 1.0),
        ("it declares that it needed phase-level actuals",
         qa is not None and qa["needs"] == "phase-level actuals"),
        ("the phase delta shows QA specifically",
         a["phase_deltas"].get("qa", {}).get("median_ratio", 0) > 1.2),
    ]


def case_scope_changes_are_excluded_not_averaged_in():
    """Comparing an estimate for ten features against actuals for seven is not evidence."""
    rng = random.Random(83)
    entries = make_ledger(rng, 5, SEED_MODEL, noise=0.05)
    entries[0]["ledger"]["actuals"]["scope_delivered"] = "reduced"
    entries[0]["ledger"]["actuals"].pop("features_delivered", None)
    entries[1]["ledger"]["actuals"]["scope_delivered"] = "unknown"
    a = run(entries)
    reasons = " ".join(s["reason"] for s in a["skipped"])
    return a, [
        ("both unusable entries are skipped", len(a["skipped"]) == 2),
        ("each skip states why", "scope" in reasons),
        ("the remaining three are still analysed", a["samples"] == 3),
    ]


def case_regression_refuses_on_uniform_project_shapes():
    """Ten identical projects carry the information of one. Sample size alone is not the gate."""
    rng = random.Random(97)
    same = make_ledger(rng, 10, SEED_MODEL, noise=0.05, shares=[0.4], uniform=True)
    varied = make_ledger(rng, 10, SEED_MODEL, noise=0.05, shares=[0.0, 0.25, 0.5, 0.75, 1.0],
                         uniform=True)
    a_same, a_varied = run(same), run(varied)
    return a_same, [
        ("uniform shapes are refused despite enough projects",
         a_same["regression"]["ready"] is False),
        ("the reason names composition, not count",
         "similar in composition" in a_same["regression"]["reason"]),
        ("it reports how wide the span actually was",
         "mix_range" in a_same["regression"]),
        ("varied shapes are accepted", a_varied["regression"]["ready"] is True),
    ]


def case_backtest_shows_the_proposal_improves_history():
    """The trust mechanism, end to end.

    A recovered proposal has to demonstrably improve the estimates it was derived from, or
    accepting it is an act of faith. This also exercises the rule that backtesting re-prices
    through est-estimate's own engine rather than a second implementation.
    """
    rng = random.Random(131)
    truth = perturb(**{"size_bands.S": 1.3, "size_bands.M": 1.3, "size_bands.L": 1.3})
    entries = make_ledger(rng, 8, truth, noise=0.06)
    a = run(entries)
    scale = find(a["proposals"], "size_bands.*")
    if scale is None:
        return a, [("a sizing proposal is raised to backtest", False)]
    result = backtest.compare(entries, SEED_MODEL, scale, backtest.engine())
    return a, [
        ("the proposal improves more past estimates than it worsens",
         result["improved"] > result["worsened"]),
        ("it improves most of them", result["improved"] >= result["samples"] - 1),
        ("median error falls",
         result["after"]["median_abs_error_pct"] < result["before"]["median_abs_error_pct"]),
        ("the verdict says so plainly", result["verdict"] == "improves past estimates"),
    ]


def case_backtest_rejects_a_change_that_makes_history_worse():
    """The direction that protects the model: a wrong proposal must be visibly wrong."""
    rng = random.Random(137)
    entries = make_ledger(rng, 8, SEED_MODEL, noise=0.05)      # model is already right
    bad = {"id": "P9", "coefficient": "size_bands.*", "kind": "factor",
           "current": 1.0, "proposed": 1.5, "samples": 8}
    result = backtest.compare(entries, SEED_MODEL, bad, backtest.engine())
    return {"proposals": [], "accuracy": {"samples": len(entries)}}, [
        ("a bad change worsens more than it improves", result["worsened"] > result["improved"]),
        ("median error rises",
         result["after"]["median_abs_error_pct"] > result["before"]["median_abs_error_pct"]),
        ("the verdict names it", result["verdict"] == "makes past estimates worse"),
    ]


def case_shrinkage_converges_as_projects_accumulate():
    """A persistent bias must arrive eventually, just not all at once from one quarter."""
    truth = perturb(**{"size_bands.S": 1.3, "size_bands.M": 1.3, "size_bands.L": 1.3})
    proposals = []
    for n in (4, 10, 30):
        rng = random.Random(151)
        a = run(make_ledger(rng, n, truth, noise=0.06))
        proposals.append(find(a["proposals"], "size_bands.*"))
    # The assertions are about the shrinkage mechanism, not about recovering 1.3 at the
    # project level. A 1.3x band perturbation does not move a project total by 30%: planning
    # is priced per epic and per story and does not scale with the bands at all, so the
    # measured signal arrives diluted to about 1.14–1.21. Pinning the test to 1.3 made it a
    # statement about how much of a project the bands happen to drive.
    closed = [(p["proposed"] - 1.0) / (p["point_estimate"] - 1.0) for p in proposals]
    return {"proposals": [], "accuracy": {"samples": 0}}, [
        ("a proposal is raised at every sample size", all(p is not None for p in proposals)),
        ("each larger sample moves further toward the truth",
         proposals[0]["proposed"] < proposals[1]["proposed"] < proposals[2]["proposed"]),
        ("thirty projects closes most of the gap to the measured signal", closed[2] > 0.8),
        ("four projects deliberately does not", closed[0] < 0.45),
        ("the signal is reported unshrunk alongside every proposal",
         all(p["proposed"] < p["point_estimate"] for p in proposals)),
    ]


def case_a_band_change_that_hurts_is_called_harmful_not_neutral():
    """Narrowing a band leaves every central figure untouched, so an error-only verdict
    calls a harmful change 'no measurable effect' — and someone skimming accepts it."""
    rng = random.Random(163)
    entries = make_ledger(rng, 8, SEED_MODEL, noise=0.30)
    bad = {"id": "P9", "coefficient": "uncertainty.model_risk", "kind": "absolute",
           "current": 0.15, "proposed": 0.01, "samples": 8}
    result = backtest.compare(entries, SEED_MODEL, bad, backtest.engine())
    return {"proposals": [], "accuracy": {"samples": 8}}, [
        ("central error is indeed unmoved", result["improved"] == 0 and result["worsened"] == 0),
        ("the band collapses", result["band_hit_change"] < -0.1),
        ("it is still called harmful", result["verdict"] == "makes past estimates worse"),
        ("the detail names the band", "band hit rate" in result["detail"]),
    ]


def case_readiness_when_nothing_has_actuals():
    rng = random.Random(101)
    entries = make_ledger(rng, 3, SEED_MODEL)
    for e in entries:
        e["ledger"]["actuals"] = None
    a = run(entries)
    unlocks = a["readiness"]["unlocks"]
    return a, [
        ("it falls back to readiness rather than failing", a["analysis_mode"] == "readiness"),
        ("no proposals are invented", a["proposals"] == []),
        ("it says what a bare total would unlock",
         any("model_risk" in u["unlocks"] for u in unlocks)),
        ("it says what per-feature hours would unlock",
         any("review tier" in u["unlocks"] for u in unlocks)),
    ]


CASES = {
    "detects-under-estimation": case_detects_under_estimation,
    "detects-over-estimation": case_detects_over_estimation,
    "calibrated-model-proposes-nothing": case_a_calibrated_model_proposes_nothing,
    "band-width-from-totals-alone": case_band_width_is_calibrated_from_totals_alone,
    "noisy-spread-does-not-move-the-band": case_a_noisy_spread_estimate_does_not_move_the_band,
    "one-outlier-does-not-move-a-coefficient": case_one_outlier_does_not_move_a_coefficient,
    "too-few-projects-proposes-nothing": case_too_few_projects_proposes_nothing,
    "phase-actuals-target-the-right-coefficient": case_phase_level_actuals_target_the_right_coefficient,
    "scope-changes-excluded": case_scope_changes_are_excluded_not_averaged_in,
    "regression-refuses-uniform-shapes": case_regression_refuses_on_uniform_project_shapes,
    "shrinkage-converges": case_shrinkage_converges_as_projects_accumulate,
    "backtest-shows-improvement": case_backtest_shows_the_proposal_improves_history,
    "backtest-rejects-a-bad-change": case_backtest_rejects_a_change_that_makes_history_worse,
    "band-harm-is-not-called-neutral": case_a_band_change_that_hurts_is_called_harmful_not_neutral,
    "readiness-without-actuals": case_readiness_when_nothing_has_actuals,
}


def main():
    ap = argparse.ArgumentParser(description="Validate est-calibrate against known ground truth.")
    ap.add_argument("--case", help="run one case by name")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    names = [args.case] if args.case else list(CASES)
    failures = []
    for name in names:
        if name not in CASES:
            print(f"unknown case '{name}' — known: {', '.join(CASES)}", file=sys.stderr)
            return 2
        analysis, checks = CASES[name]()
        bad = [label for label, ok in checks if not ok]
        failures.extend(f"{name}: {label}" for label in bad)
        if not args.quiet or bad:
            print(f"{'FAIL' if bad else 'ok  '} {name} — {len(checks) - len(bad)}/{len(checks)} held")
            for label in bad:
                print(f"       ✗ {label}")

    print(f"\n{len(names) - len({f.split(':')[0] for f in failures})}/{len(names)} cases fully held")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
