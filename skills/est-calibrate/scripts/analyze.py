#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Compare estimates against actuals and propose evidence-backed coefficient changes.

Reads ledger entries written by est-estimate, each carrying the snapshot of the cost model
that produced it, so a delta can always be attributed to the estimate rather than to a
model that has since moved.

Two things shape everything here:

Band hit rate is the headline, not average error. The module quotes ranges, so the honest
question is how often the actual landed inside the range it quoted. That also happens to be
the one thing a bare project total can calibrate, which matters because bare project totals
are what this company mostly has.

Robust statistics throughout — median and MAD, never mean and standard deviation. One
unusual project must not move a coefficient, and with a handful of samples a single outlier
would dominate any mean.
"""

import argparse
import json
import math
import statistics
import subprocess
import sys
from pathlib import Path

PHASES = ["planning", "planning-review", "spec", "build", "review", "rework",
          "qa", "overhead", "architecture"]

CONFIDENCE_WEIGHT = {"measured": 1.0, "reconstructed": 0.6, "estimated": 0.3}

# How widely a tier's share of hours must span across delivered projects before the tiers
# can be separated from project totals. Deliberately well above the sampling noise a small
# project produces on its own, so that "more projects of the same shape" never unlocks a fit.
# Expected range of n samples from a standard normal (the control-chart d2 constant). The
# range of pure noise GROWS with sample count, which is why comparing an observed spread
# against one standard deviation of noise lets more projects of the same shape look varied.
_D2 = {2: 1.128, 3: 1.693, 4: 2.059, 5: 2.326, 6: 2.534, 7: 2.704, 8: 2.847, 9: 2.970,
       10: 3.078, 11: 3.173, 12: 3.258, 15: 3.472, 20: 3.735, 25: 3.931}


def expected_noise_range(n):
    """How wide a spread pure sampling noise alone would produce across n projects."""
    if n in _D2:
        return _D2[n]
    keys = sorted(_D2)
    if n < keys[0]:
        return _D2[keys[0]]
    if n > keys[-1]:
        return _D2[keys[-1]] + 0.55 * math.log(n / keys[-1])
    lo = max(k for k in keys if k <= n)
    hi = min(k for k in keys if k >= n)
    span = (n - lo) / (hi - lo) if hi != lo else 0
    return _D2[lo] + span * (_D2[hi] - _D2[lo])


# How far the observed spread in project composition must exceed what noise alone explains.
DEFAULT_MIX_MARGIN = 1.5

# Small samples get pulled toward the value already in the model. Seven delivered projects
# are real evidence but not enough to justify jumping to a point estimate, and a model that
# lurches on thin data is one nobody trusts twice. The weight n/(n+SHRINKAGE_K) reaches half
# at six projects and four fifths at twenty-four, so a persistent signal still arrives — it
# just takes more than one quarter of data to get there.
DEFAULT_SHRINKAGE_K = 6.0

# How far a phase's actual-to-estimated ratio must sit from 1.0 before it is worth proposing.
DEFAULT_PHASE_DEADBAND = 0.12


def shrink(current, target, samples, k=DEFAULT_SHRINKAGE_K):
    """Move from `current` toward `target` by a weight that grows with the evidence."""
    weight = samples / (samples + k)
    return current + (target - current) * weight, round(weight, 3)


# --- robust statistics -------------------------------------------------------

def band_target(model):
    """The coverage a calibrated estimator should achieve, derived from the model's own z.

    est-estimate reports mean ± z·sd, so the share of actuals that should land inside is
    erf(z/√2) — 68% at z=1.0, 80% at z=1.28, 90% at z=1.645. Assuming 68% regardless would
    tell a company that had deliberately widened to an 80% band that its correctly
    calibrated ranges were far too wide, and propose narrowing them.
    """
    z = (model.get("uncertainty") or {}).get("z", 1.0)
    return round(math.erf(z / math.sqrt(2)), 3)


def median(values):
    return statistics.median(values) if values else 0.0


def mad(values):
    """Median absolute deviation, scaled to be comparable with a standard deviation."""
    if len(values) < 2:
        return 0.0
    med = statistics.median(values)
    return 1.4826 * statistics.median([abs(v - med) for v in values])


def outliers(values, threshold=3.0):
    """Indices lying more than `threshold` scaled MADs from the median."""
    spread = mad(values)
    if spread == 0:
        return set()
    med = statistics.median(values)
    return {i for i, v in enumerate(values) if abs(v - med) / spread > threshold}


# --- loading -----------------------------------------------------------------

def configured_min_samples(project_root, fallback=3):
    """The threshold the operator actually set.

    est-setup collects `est_min_calibration_samples` and describes it as how many delivered
    projects it takes before a pattern counts as more than a weak signal. Nothing read it, so
    the number in the config file was decoration and the real threshold was a default in this
    argparse line — a setting that does nothing is worse than one that is absent, because it
    tells the operator they have made a choice.
    """
    resolver = Path(project_root) / "_bmad" / "scripts" / "resolve_config.py"
    if not resolver.exists():
        return fallback
    # `-k` is the resolver's own interface for asking one question, and it answers in a flat
    # dict keyed by the dotted path. Omitting it returns the whole nested config instead, where
    # a dotted key matches nothing and this silently fell back to 3 — the exact failure the
    # docstring above claims to have fixed.
    key = "modules.est.est_min_calibration_samples"
    try:
        proc = subprocess.run([sys.executable, str(resolver), "-p", str(project_root), "-k", key],
                              capture_output=True, text=True, timeout=30)
        if proc.returncode != 0:
            return fallback
        config = json.loads(proc.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return fallback
    value = config.get(key)
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return fallback


def load_ledger(ledger_dir):
    entries = []
    for path in sorted(Path(ledger_dir).glob("EST-*.json")):
        try:
            entries.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return entries


def usable(entry):
    """Whether an entry can be compared against its estimate, and if not, why not.

    A project that delivered different scope from what was priced is not evidence the
    model was wrong, and averaging it in would drive every coefficient the wrong way.
    """
    actuals = (entry.get("ledger") or {}).get("actuals")
    if not actuals:
        return False, "no actuals recorded"
    if not actuals.get("delivery_hours"):
        return False, "actuals carry no delivery_hours"
    scope = actuals.get("scope_delivered")
    if scope == "unknown":
        return False, "scope_delivered is unknown — cannot tell whether like is being compared with like"
    if scope in ("reduced", "expanded") and not actuals.get("features_delivered"):
        return False, (f"scope was {scope} but features_delivered is missing, so the estimate "
                       f"cannot be re-priced to match what actually shipped")
    if actuals.get("excluded_hours") and not (actuals.get("excluded_why") or "").strip():
        return False, "excluded_hours is set with no excluded_why — an exclusion nobody can interrogate"
    return True, None


# --- accuracy ----------------------------------------------------------------

def accuracy(entries, model):
    """Band hit rate first, then error size. Both robust to a single bad project."""
    target = band_target(model)
    rows = []
    for entry in entries:
        actuals = entry["ledger"]["actuals"]
        total = entry["total_hours"]
        actual = actuals["delivery_hours"]
        sd = (entry.get("confidence") or {}).get("aggregated_sd") or 0.0
        rows.append({
            "id": entry["ledger"]["id"],
            "project": entry.get("project"),
            "likely": total["likely"],
            "low": total["low"],
            "high": total["high"],
            "actual": actual,
            "inside_band": total["low"] <= actual <= total["high"],
            "error_pct": 100 * (actual - total["likely"]) / total["likely"] if total["likely"] else 0.0,
            # Standardised residual: if the model's own uncertainty were honest, the spread
            # of these would be about 1.0. Anything larger means it understates itself.
            "sd": sd,
            "residual_z": (actual - total["likely"]) / sd if sd else None,
            "confidence": actuals.get("confidence", "measured"),
            "granularity": actuals.get("granularity"),
        })

    errors = [r["error_pct"] for r in rows]
    residuals = [r["residual_z"] for r in rows if r["residual_z"] is not None]
    hits = sum(1 for r in rows if r["inside_band"])

    bias = median(errors) / 100.0

    return {
        "samples": len(rows),
        "band_hit_rate": round(hits / len(rows), 3) if rows else None,
        "band_hit_target": target,
        "band_hit_target_why": (f"The model reports mean ± {(model.get('uncertainty') or {}).get('z', 1.0)}"
                                f" standard deviations, so a well-calibrated estimator's actuals land "
                                f"inside the quoted range about {target:.0%} of the time. Materially "
                                f"below that means the ranges are too narrow to be honest; materially "
                                f"above means they are so wide they say nothing."),
        "median_error_pct": round(median(errors), 1),
        "error_spread_pct": round(mad(errors), 1),
        "direction": ("under-estimating" if median(errors) > 5 else
                      "over-estimating" if median(errors) < -5 else "no systematic bias"),
        "residual_spread": round(mad(residuals), 2) if len(residuals) > 1 else None,
        "measured_bias": round(bias, 4),
        "entries": rows,
    }


# --- proposals ---------------------------------------------------------------

def spread_after_correction(acc, correction):
    """Residual spread once the sizing correction that will ACTUALLY be applied is removed.

    Systematic error is the sizing scale's job and random spread is the band's, so the band
    must be judged on what the scale leaves behind. Two ways to get this wrong, both of which
    were here: removing the full measured bias when only a shrunk fraction of it will be
    applied sizes the band for a correction nobody makes; and removing it at all when no
    sizing proposal was raised narrows the band for a correction that will never happen.
    """
    residuals = [(r["actual"] - r["likely"] * correction) / r["sd"]
                 for r in acc["entries"] if r["sd"] and r["likely"]]
    return round(mad(residuals), 2) if len(residuals) > 1 else None


def propose_model_risk(acc, model, min_samples, spread, k=DEFAULT_SHRINKAGE_K):
    """Calibrate band width from the spread of standardised residuals.

    Needs nothing but project totals, which is why it is the first thing this company can
    honestly calibrate. If the residual spread is 1.8, the model understates its own
    uncertainty by that factor; model_risk is solved so the band would have been right.
    """
    # Judged on debiased residuals: whatever the sizing scale will correct is not the band's
    # job, and counting it twice is how a systematically biased model ends up with a
    # confidently narrow range.
    if spread is None or acc["samples"] < min_samples:
        return None
    # A MAD of zero means more than half the sample landed on the same value — routine below
    # ten projects — not that the estimates have no spread. Left unguarded it clears any
    # tolerance and drives model_risk to zero, proposing a band of no width at all.
    if spread <= 0.05:
        return None
    current = model["uncertainty"].get("model_risk", 0.0)

    # The dead-band has to shrink with sample size, because the spread statistic is itself
    # noisy: measured over eight projects, an observed 1.13 is indistinguishable from 1.0,
    # and a fixed threshold would have proposed a band change on that. Requiring the
    # deviation to clear roughly the sampling error of the estimate keeps the calibrator
    # from chasing its own noise — at the cost of needing either more projects or a
    # genuinely wrong band before it says anything.
    tolerance = max(0.15, 1.5 / math.sqrt(acc["samples"]))
    if abs(spread - 1.0) < tolerance:
        return None

    # sd_total = hypot(sd_features, model_risk * mean). Scaling sd_total by `spread` while
    # holding sd_features fixed gives the model_risk that would have made the band honest.
    # Entries with no recorded sd are dropped, not counted as zero: an unmeasurable entry is
    # absent evidence, and medianing a zero in would drag the band toward nothing.
    scaled = [max((row["sd"] * spread) / row["likely"], 0.0)
              for row in acc["entries"] if row["sd"] and row["likely"]]
    if not scaled:
        return None

    point = median(scaled)
    proposed, weight = shrink(current, point, acc["samples"], k)
    proposed = round(proposed, 3)
    return {
        "coefficient": "uncertainty.model_risk",
        "kind": "absolute",
        "current": current,
        "proposed": proposed,
        "direction": "widen" if proposed > current else "narrow",
        "samples": acc["samples"],
        "evidence": (f"Actuals landed inside the quoted range {acc['band_hit_rate']:.0%} of the time "
                     f"against a {acc['band_hit_target']:.0%} target. Once the sizing correction "
                     f"that will actually be applied is taken out — systematic error is the scale's "
                     f"job, not the band's — the spread of standardised residuals is {spread}, "
                     f"where a calibrated model gives 1.0. The model "
                     f"{'understates' if spread > 1 else 'overstates'} its own uncertainty by roughly "
                     f"{spread:.1f}x."),
        "why": (f"Band width calibrated from {acc['samples']} delivered projects: residual spread "
                f"{spread} against a target of 1.0, clearing the ±{tolerance:.2f} sampling "
                f"tolerance for that many samples."),
        "needs": "project totals only",
        "point_estimate": round(point, 3),
        "shrinkage_weight": weight,
        "shrinkage_why": (f"The data alone points at {point:.3f}. The proposal moves only "
                          f"{weight:.0%} of the way there, because {acc['samples']} projects are "
                          f"real evidence but not enough to justify jumping to a point estimate. "
                          f"The remaining distance is closed as more projects land."),
        "tolerance_applied": round(tolerance, 2),
        "companion": ("If a sizing-scale proposal is accepted alongside this one, both were "
                      "derived together: the bias was removed before the band was measured, so "
                      "they do not double-count. Accepting only one of the two is still valid."),
    }


def propose_global_scale(acc, model, min_samples, k=DEFAULT_SHRINKAGE_K):
    """A systematic direction in the totals means the sizing baseline is off.

    Deliberately proposed against size_bands rather than any single downstream coefficient:
    the band IS the story's hours, and build, spec, review and rework are shares of it, so a
    uniform sizing error is the simplest explanation consistent with a total that is
    consistently off.
    """
    if acc["samples"] < min_samples:
        return None
    bias = acc["median_error_pct"]
    if abs(bias) < 8:
        return None
    point = 1 + bias / 100
    factor, weight = shrink(1.0, point, acc["samples"], k)
    factor = round(factor, 3)
    return {
        "coefficient": "size_bands.*",
        "kind": "factor",
        "current": 1.0,
        "proposed": factor,
        "direction": "scale up" if factor > 1 else "scale down",
        "samples": acc["samples"],
        "evidence": (f"Across {acc['samples']} delivered projects the median outcome was "
                     f"{bias:+.1f}% against the central estimate, with a spread of "
                     f"{acc['error_spread_pct']:.1f}%. A consistent direction across varied projects "
                     f"points at the sizing baseline rather than any one downstream coefficient."),
        "why": (f"Uniform sizing scale from {acc['samples']} projects: median outcome {bias:+.1f}% "
                f"against estimate."),
        "needs": "project totals only",
        "point_estimate": round(point, 3),
        "shrinkage_weight": weight,
        "shrinkage_why": (f"The data alone points at {point:.3f}x. The proposal moves "
                          f"{weight:.0%} of the way, so a persistent bias converges over several "
                          f"calibrations rather than swinging the model on one quarter's projects."),
        "caution": ("This scales every size band together. If the actuals also show a per-phase "
                    "pattern, prefer the specific coefficient — a uniform scale is the honest "
                    "explanation only when nothing finer is visible."),
    }


def phase_deltas(entries, min_samples):
    """Per-phase ratios of actual to estimated, for entries that report phase-level hours."""
    ratios = {phase: [] for phase in PHASES}
    for entry in entries:
        actuals = entry["ledger"]["actuals"]
        by_phase = actuals.get("by_phase") or {}
        if not by_phase:
            continue
        weight = CONFIDENCE_WEIGHT.get(actuals.get("confidence", "measured"), 1.0)
        for phase, hours in by_phase.items():
            if phase not in ratios:
                # A ledger entry from a model with a phase this build does not know. Recorded
                # rather than crashed: history is the asset, and a KeyError here would make an
                # older entry unreadable rather than merely unmapped.
                ratios[phase] = []
            estimated = (entry.get("by_phase") or {}).get(phase, {}).get("hours")
            if estimated and estimated > 0 and weight >= 0.6:
                ratios[phase].append(hours / estimated)

    out = {}
    for phase, values in ratios.items():
        if not values:
            continue
        flagged = outliers(values)
        clean = [v for i, v in enumerate(values) if i not in flagged]
        out[phase] = {
            "samples": len(clean),
            "outliers_excluded": len(flagged),
            "median_ratio": round(median(clean), 3) if clean else None,
            "spread": round(mad(clean), 3) if len(clean) > 1 else None,
            "sufficient": len(clean) >= min_samples,
        }
    return out


PHASE_COEFFICIENTS = {
    "planning-review": "planning.review_hours",
    "planning": "planning.agent_hours",
    "qa": "qa",
    "overhead": "overhead_rate",
    # Architecture maps to a weekly rate, not to a per-project figure, so a ratio here is a
    # statement about the RATE only if the schedule was right too. It is deliberately absent:
    # architect hours are `setup + weekly x weeks`, and an over-run could be either term.
    # analyze() reports the phase; curate.py is where a human decides which half moved.
}


def propose_from_phases(deltas, model, min_samples, deadband=DEFAULT_PHASE_DEADBAND, k=DEFAULT_SHRINKAGE_K):
    """Where a phase maps to one coefficient family, a consistent ratio is a direct proposal."""
    proposals = []
    for phase, stats in deltas.items():
        target = PHASE_COEFFICIENTS.get(phase)
        if not target or not stats["sufficient"] or stats["median_ratio"] is None:
            continue
        ratio = stats["median_ratio"]
        if abs(ratio - 1.0) < deadband:
            continue
        shrunk, weight = shrink(1.0, ratio, stats["samples"], k)
        proposals.append({
            "coefficient": target,
            "kind": "factor",
            "current": 1.0,
            "proposed": round(shrunk, 3),
            "point_estimate": round(ratio, 3),
            "shrinkage_weight": weight,
            "direction": "scale up" if ratio > 1 else "scale down",
            "samples": stats["samples"],
            "evidence": (f"Actual {phase} hours ran at {ratio:.2f}x the estimate across "
                         f"{stats['samples']} projects (spread {stats['spread']}), "
                         f"{stats['outliers_excluded']} outlier(s) excluded."),
            "why": f"{phase} calibrated from {stats['samples']} projects: actuals ran {ratio:.2f}x estimate.",
            "needs": "phase-level actuals",
        })
    return proposals


def regression_readiness(entries, model, min_projects, margin=DEFAULT_MIX_MARGIN):
    """Can per-tier coefficients be separated from project totals alone?

    Only if the projects differ in shape. Ten projects with identical composition carry the
    same information as one, because no arrangement of coefficients is distinguishable from
    another. That is a conditioning question, not a sample-size question, and answering it
    with sample size alone is how a regression quietly fits noise.
    """
    tiers = ["routine", "sensitive", "critical"]
    rows, feature_counts = [], []
    for entry in entries:
        feature_counts.append(len(entry.get("features", [])) or 1)
        mix = {t: 0.0 for t in tiers}
        for feature in entry.get("features", []):
            tier = feature.get("tags", {}).get("review_tier")
            if tier in mix:
                mix[tier] += feature.get("hours", 0.0)
        total = sum(mix.values())
        if total > 0:
            rows.append([mix[t] / total for t in tiers])

    if len(rows) < min_projects:
        return {"ready": False, "projects": len(rows), "required": min_projects,
                "reason": (f"{len(rows)} delivered projects with tier mix; at least {min_projects} "
                           f"are needed before a fit can be told apart from noise.")}

    # Judge the RANGE of each tier's share, not its spread. Spread is the intuitive measure
    # and the wrong one: a handful of features per project produces sampling noise of roughly
    # sqrt(p(1-p)/n) — about 0.17 for an eight-feature project — so a set of projects built to
    # the same recipe still looks "varied" by spread alone, and the regression would then fit
    # that noise. A wide range means someone genuinely delivered a payments-heavy project and
    # a CRUD-heavy one, which is the only thing that separates the coefficients.
    ranges = [max(r[i] for r in rows) - min(r[i] for r in rows) for i in range(len(tiers))]

    # Compare each tier's observed span against the span sampling noise alone would produce
    # for projects of this size. A set of projects built to one recipe still varies, because
    # which features land in which tier is partly chance; the question is whether they vary
    # by MORE than that.
    features = statistics.median(feature_counts)
    shares = [statistics.mean(r[i] for r in rows) for i in range(len(tiers))]
    noise = [math.sqrt(max(p * (1 - p), 1e-9) / features) * expected_noise_range(len(rows))
             for p in shares]
    thresholds = [n * margin for n in noise]
    varied = sum(1 for r, t in zip(ranges, thresholds) if r >= t)

    detail = {"projects": len(rows),
              "mix_range": [round(r, 3) for r in ranges],
              "noise_only_range": [round(n, 3) for n in noise],
              "required_range": [round(t, 3) for t in thresholds]}
    if varied < 2:
        widest = max(zip(ranges, thresholds), key=lambda rt: rt[0] - rt[1])
        return {**detail, "ready": False, "required": min_projects,
                "reason": (f"The delivered projects are too similar in composition to separate the "
                           f"review tiers. The widest tier share spans {widest[0]:.0%}, but "
                           f"sampling noise alone would produce about "
                           f"{widest[1] / margin:.0%} across {len(rows)} projects of this size — so "
                           f"{widest[0]:.0%} is not evidence of real variation. Regression needs "
                           f"projects of genuinely different shape, and more of the same shape "
                           f"never supplies it.")}
    return {**detail, "ready": True,
            "reason": (f"Enough delivered projects, and their composition varies by more than "
                       f"sampling noise explains — the widest tier share spans {max(ranges):.0%} "
                       f"against a noise-only expectation of "
                       f"{max(noise):.0%} — so the tiers can be told apart.")}


# --- readiness ---------------------------------------------------------------

def chase_list(entries):
    """Delivered-looking projects with no actuals: the specific asks, oldest first.

    A have/need table reads the same every month and prompts nobody. These are the
    conversations that would actually move the module forward, with the command to run
    once someone comes back with a number.
    """
    rows = []
    for entry in entries:
        ledger = entry.get("ledger") or {}
        if ledger.get("actuals") or ledger.get("status") not in ("sent", "won", "delivered"):
            continue
        rows.append({
            "id": ledger.get("id"),
            "project": entry.get("project"),
            "status": ledger.get("status"),
            "estimated": (entry.get("total_hours") or {}).get("likely"),
            "generated": entry.get("generated"),
            "command": (f"uv run scripts/ingest-actuals.py --entry <ledger>/{ledger.get('id')}.json "
                        f"--total <hours> --scope as_estimated --source \"<where it came from>\""),
        })
    return sorted(rows, key=lambda r: r["generated"] or "")


def readiness(entries):
    """What capturing actuals would unlock. This is the mode that runs before any exist."""
    with_actuals = [e for e in entries if (e.get("ledger") or {}).get("actuals")]
    blocked = []
    for entry in entries:
        ok, reason = usable(entry)
        if not ok and (entry.get("ledger") or {}).get("actuals"):
            blocked.append({"id": entry["ledger"]["id"], "reason": reason})

    granularity = {}
    for entry in with_actuals:
        level = entry["ledger"]["actuals"].get("granularity", "project")
        granularity[level] = granularity.get(level, 0) + 1

    return {
        "ledger_entries": len(entries),
        "with_actuals": len(with_actuals),
        "usable": len(with_actuals) - len(blocked),
        "blocked": blocked,
        "granularity_mix": granularity,
        "chase": chase_list(entries),
        "unlocks": [
            {"capture": "A single delivery_hours total per closed project",
             "unlocks": "Band width (uncertainty.model_risk) and a uniform sizing scale",
             "why": "Comparing one number against the quoted range needs no attribution at all, "
                    "and band honesty is the claim clients test first.",
             "have": sum(1 for e in with_actuals),
             "need": 4},
            {"capture": "Hours split by BMad phase",
             "unlocks": "planning review, planning, standing work, QA and overhead coefficients directly",
             "why": "Each of those phases maps to one coefficient family, so a consistent ratio "
                    "is a proposal rather than an inference.",
             "have": sum(1 for e in with_actuals if e["ledger"]["actuals"].get("by_phase")),
             "need": 4},
            {"capture": "Hours per feature",
             "unlocks": "review tier and compressibility class coefficients — the module's core IP",
             "why": "These are what make a payments feature price differently from a CRUD screen. "
                    "Without per-feature hours they can only be inferred from projects of "
                    "genuinely different shape, and only once several exist.",
             "have": sum(1 for e in with_actuals if e["ledger"]["actuals"].get("by_feature")),
             "need": 5},
            {"capture": "Hours per role",
             "unlocks": "the role-weight split",
             "why": "Nothing else can calibrate it; the split is currently a reasoned guess.",
             "have": sum(1 for e in with_actuals if e["ledger"]["actuals"].get("by_role")),
             "need": 4},
        ],
        "advice": ("Capture delivery_hours, scope_delivered and excluded_hours on every closed "
                   "project from now on. Those three fields alone make band width calibratable, "
                   "and scope_delivered is the one that most often silently invalidates a "
                   "comparison later."),
    }


# --- main --------------------------------------------------------------------

def build_analysis(entries, model, min_samples, min_projects,
                   margin=DEFAULT_MIX_MARGIN, k=DEFAULT_SHRINKAGE_K,
                   deadband=DEFAULT_PHASE_DEADBAND):
    comparable, skipped = [], []
    for entry in entries:
        ok, reason = usable(entry)
        (comparable if ok else skipped).append(
            entry if ok else {"id": (entry.get("ledger") or {}).get("id"), "reason": reason})

    if not comparable:
        return {"analysis_mode": "readiness", "readiness": readiness(entries), "skipped": skipped,
                "proposals": [],
                "message": ("No ledger entry can be compared against its estimate yet. The readiness "
                            "section says what to capture and what each level of data would unlock.")}

    acc = accuracy(comparable, model)
    deltas = phase_deltas(comparable, min_samples)

    # Order matters: the sizing proposal decides how much of the systematic error will be
    # corrected, and the band is then judged on whatever that leaves behind. Computing them
    # independently sizes the band for a world that will not exist.
    scale = propose_global_scale(acc, model, min_samples, k)
    correction = scale["proposed"] if scale else 1.0
    residual_spread = spread_after_correction(acc, correction)
    acc["residual_spread_after_correction"] = residual_spread
    acc["correction_assumed"] = correction
    acc["correction_note"] = (
        f"The band is judged on the spread left after the sizing correction that will actually be "
        f"applied ({correction}x)"
        + (" — no sizing change is proposed, so nothing was removed." if not scale else
           f", not after the full measured bias of {1 + acc['measured_bias']:.3f}x. Sizing the band "
           f"for a correction only partly made would leave it too narrow.")
    )

    proposals = [p for p in [propose_model_risk(acc, model, min_samples, residual_spread, k),
                             scale] if p]
    proposals += propose_from_phases(deltas, model, min_samples, deadband, k)

    for i, p in enumerate(proposals, start=1):
        p["id"] = f"P{i}"
        p["weak_signal"] = p["samples"] < min_samples + 2

    return {
        "analysis_mode": "calibration",
        "samples": len(comparable),
        "skipped": skipped,
        "accuracy": acc,
        "phase_deltas": deltas,
        "regression": regression_readiness(comparable, model, min_projects, margin),
        "proposals": proposals,
        "readiness": readiness(entries),
    }


def main():
    ap = argparse.ArgumentParser(
        description="Compare estimates against actuals and propose coefficient changes.",
        epilog="Exit codes: 0 analysis produced, 1 nothing comparable yet (readiness reported), 2 unreadable input.",
    )
    ap.add_argument("--ledger", required=True, help="ledger directory written by est-estimate")
    ap.add_argument("--cost-model", required=True, help="current cost-model.json")
    ap.add_argument("-o", "--output", help="write the analysis JSON here instead of stdout")
    ap.add_argument("--min-samples", type=int, default=None,
                    help="delivered projects required before a coefficient change is proposed. "
                         "Defaults to est_min_calibration_samples from the project config, or 3.")
    ap.add_argument("--project-root", default=".",
                    help="project root, used to resolve est_min_calibration_samples (default: .)")
    ap.add_argument("--min-projects-for-regression", type=int, default=8,
                    help="projects required before per-tier coefficients can be fitted from totals (default 8)")
    ap.add_argument("--mix-margin", type=float, default=DEFAULT_MIX_MARGIN,
                    help="how far the observed variation in project composition must exceed what "
                         "sampling noise alone explains before the tiers can be separated "
                         "(default 1.5x); more projects of the same shape never unlock a fit")
    ap.add_argument("--shrinkage-k", type=float, default=DEFAULT_SHRINKAGE_K,
                    help="how hard proposals are pulled toward the current value; the weight is "
                         "n/(n+k), so k=6 moves half the way at six projects (default 6)")
    ap.add_argument("--phase-deadband", type=float, default=DEFAULT_PHASE_DEADBAND,
                    help="how far a phase's actual-to-estimated ratio must sit from 1.0 before it "
                         "is worth proposing (default 0.12)")
    args = ap.parse_args()
    if args.min_samples is None:
        args.min_samples = configured_min_samples(args.project_root)

    model_path = Path(args.cost_model)
    if not model_path.exists():
        print(json.dumps({
            "ok": False,
            "error": (f"no cost model at {model_path}. est-estimate seeds it from its own asset on "
                      f"first run, so its absence means nothing has been estimated yet and there is "
                      f"nothing to calibrate against. Run est-estimate first."),
        }, indent=2))
        return 2
    try:
        model = json.loads(model_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": f"cannot read cost model: {exc}"}, indent=2))
        return 2

    entries = load_ledger(args.ledger)
    if not entries:
        # Day one of a module that takes months to accumulate evidence. Reporting what to
        # capture is the useful answer; failing is not.
        empty = {"analysis_mode": "readiness", "readiness": readiness([]), "skipped": [], "proposals": [],
                 "message": (f"No estimates recorded in {args.ledger} yet. Once est-estimate has "
                             f"written ledger entries and projects close, this becomes a "
                             f"calibration run.")}
        text = json.dumps(empty, indent=2, ensure_ascii=False)
        if args.output:
            Path(args.output).write_text(text + "\n", encoding="utf-8")
            print(json.dumps({"ok": True, "analysis": args.output, "analysis_mode": "readiness",
                              "proposals": 0}, indent=2))
        else:
            print(text)
        return 1

    analysis = build_analysis(entries, model, args.min_samples, args.min_projects_for_regression,
                              args.mix_margin, args.shrinkage_k, args.phase_deadband)
    text = json.dumps(analysis, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
        print(json.dumps({"ok": True, "analysis": args.output, "mode": analysis["analysis_mode"],
                          "proposals": len(analysis["proposals"])}, indent=2))
    else:
        print(text)
    return 0 if analysis["analysis_mode"] == "calibration" else 1


if __name__ == "__main__":
    sys.exit(main())
