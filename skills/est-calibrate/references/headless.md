# Headless

An unattended run of `est-calibrate` — a scheduled accuracy check, or a call from a retrospective workflow.

Headless holds for the whole run once recognised: no TTY, a programmatic caller, `-H`, or every input supplied up front.

`{workspace}` below is `{output_folder}/estimates/calibration/{date}/` — one folder per run, holding the analysis, the backtests, the reports and the memlog.

## The one rule

**Headless never writes to the cost model.** Every other human gate in this module has a conservative unattended default, and this one deliberately does not: the whole value of the model is that nobody can change it without a named person accepting a specific, backtested proposal. A default of "apply the safe-looking ones" would be silent drift with extra steps.

So an unattended run does the analysis, runs the backtests, renders the report, and returns the proposals as *pending*. Nothing is applied — and this is enforced in the tool, not merely instructed here: `apply.py` refuses to run when there is no terminal, with no flag to override it. If the caller wants changes made, a human runs the interactive mode and accepts them by id.

## Defaults at the remaining gates

| Gate | Interactive | Headless |
| --- | --- | --- |
| Approving a coefficient change | Accept or reject each | **Never.** Return the proposals as pending |
| Nothing comparable in the ledger | Present readiness and stop | Return the readiness payload with `status: complete` and `mode: readiness` |
| An entry has actuals but is not comparable | Ask whether to fix the record | Leave it, list it in `not_comparable` with the reason |
| Appending comparables | Confirm the entries | Append them — comparables are observations, not decisions, and are individually reversible |
| A weak signal below the sample threshold | Mention it as one to watch | Include it in `watch`, never in `proposals` |

Log every inference as a memlog `assumption`, especially any actuals attribution that was inferred rather than measured.

## Returning

```json
{
  "status": "complete",
  "mode": "report-only",
  "samples": 7,
  "band_hit_rate": 0.71,
  "median_error_pct": 22.9,
  "direction": "under-estimating",
  "report": "{output_folder}/estimates/calibration/accuracy-report.md",
  "analysis": "{workspace}/analysis.json",
  "backtest": "{workspace}/backtest.json",
  "memlog": "{workspace}/.memlog.md",
  "pending_proposals": [
    {"id": "P2", "coefficient": "size_bands.*", "current": 1.0, "proposed": 1.123,
     "samples": 7, "backtest": "improves past estimates", "weak_signal": false}
  ],
  "watch": [],
  "not_comparable": [{"id": "EST-20260714-acme", "reason": "scope_delivered is unknown"}]
}
```

`status` is only ever `complete` or `blocked`, as in both sibling skills — a caller branching on those two values must not fall through on a readiness run, which is the most likely run today. Readiness travels in `mode` instead: `"status": "complete", "mode": "readiness"`, with the readiness payload in place of the accuracy figures. On failure return `"status": "blocked"` with a one-line `reason` and the memlog path.

`mode` is the skill's mode — `readiness`, `calibrate` or `report-only`. It is not `analyze.py`'s `analysis_mode`, which describes what the analysis found rather than how the skill was run; the two were one field and diverged.

`pending_proposals` is the load-bearing field: it is what lets a scheduled monthly run tell a delivery lead there is a decision waiting, without having made it for them.
