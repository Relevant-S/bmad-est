#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Render the estimate-versus-actual accuracy report.

Deliberately a static page. Skill #2's report recomputes in the browser so scope can be
cut live, and that duplicated logic drifted twice. Nothing here needs to be interactive,
so nothing here recomputes anything: every figure is read from the analysis JSON that
produced it.
"""

import argparse
import html
import json
import sys
from pathlib import Path


def verdict_line(acc):
    hit, target = acc["band_hit_rate"], acc["band_hit_target"]
    if hit is None:
        return "Not enough delivered projects to judge accuracy yet."
    if hit < target - 0.15:
        return (f"**Ranges are too narrow.** Actuals landed inside the quoted range {hit:.0%} of "
                f"the time against a {target:.0%} target, so the estimates promise more precision "
                f"than the model has.")
    if hit > target + 0.20:
        return (f"**Ranges are wider than they need to be.** Actuals landed inside {hit:.0%} of the "
                f"time against a {target:.0%} target — honest, but a range that always contains the "
                f"answer is not saying much.")
    return (f"**Ranges are about right.** Actuals landed inside the quoted range {hit:.0%} of the "
            f"time, against a {target:.0%} target.")


def markdown(analysis, backtests=None):
    out = ["# Estimate accuracy", ""]
    if analysis["analysis_mode"] == "readiness":
        r = analysis["readiness"]
        out += [analysis["message"], "", "## What is in the ledger", "",
                f"- {r['ledger_entries']} estimates recorded",
                f"- {r['with_actuals']} with actuals attached, {r['usable']} of them comparable", ""]
        if r.get("chase"):
            out += ["## Projects to chase", "",
                    "Estimates that went out and have not come back with hours. Oldest first — "
                    "these are the conversations that move the model forward.", "",
                    "| Project | Status | Estimated | Recorded |", "| --- | --- | ---: | --- |"]
            for c in r["chase"]:
                out.append(f"| {c['project'] or c['id']} | {c['status']} | "
                           f"{c['estimated'] or 0:,.0f} | {(c['generated'] or '')[:10]} |")
            out.append("")
        if r["blocked"]:
            out += ["### Recorded but not comparable", ""]
            out += [f"- **{b['id']}** — {b['reason']}" for b in r["blocked"]] + [""]
        out += ["## What capturing actuals would unlock", "",
                "| Capture | Unlocks | Have | Need |", "| --- | --- | ---: | ---: |"]
        for u in r["unlocks"]:
            out.append(f"| {u['capture']} | {u['unlocks']} | {u['have']} | {u['need']} |")
        out += ["", f"> {r['advice']}", ""]
        return "\n".join(out) + "\n"

    acc = analysis["accuracy"]
    out += [verdict_line(acc), "",
            f"Based on {acc['samples']} delivered projects. Median outcome "
            f"{acc['median_error_pct']:+.1f}% against the central estimate "
            f"(spread {acc['error_spread_pct']:.1f}%) — {acc['direction']}.", ""]

    out += ["## Delivered projects", "",
            "| Project | Quoted range | Actual | Inside? | Error |",
            "| --- | --- | ---: | :---: | ---: |"]
    for row in acc["entries"]:
        out.append(f"| {row['project'] or row['id']} | {row['low']:,.0f}–{row['high']:,.0f} | "
                   f"{row['actual']:,.0f} | {'yes' if row['inside_band'] else 'no'} | "
                   f"{row['error_pct']:+.1f}% |")
    out.append("")

    if analysis.get("skipped"):
        out += ["### Not comparable", "",
                "These were left out rather than averaged in, because comparing them would move "
                "the model on evidence that is not evidence.", ""]
        out += [f"- **{s['id']}** — {s['reason']}" for s in analysis["skipped"]] + [""]

    deltas = {k: v for k, v in (analysis.get("phase_deltas") or {}).items() if v.get("median_ratio")}
    if deltas:
        out += ["## Where the hours actually went", "",
                "| Phase | Actual ÷ estimated | Projects | Outliers excluded |",
                "| --- | ---: | ---: | ---: |"]
        for phase, stats in sorted(deltas.items(), key=lambda kv: -abs(kv[1]["median_ratio"] - 1)):
            out.append(f"| {phase} | {stats['median_ratio']:.2f}× | {stats['samples']} | "
                       f"{stats['outliers_excluded']} |")
        out.append("")

    results = {b["proposal"]: b for b in (backtests or {}).get("backtests", [])}
    if analysis["proposals"]:
        out += ["## Proposed changes", "",
                "Nothing below has been applied. Each row is a proposal for a human to accept or "
                "reject.", ""]
        for p in analysis["proposals"]:
            b = results.get(p["id"], {})
            out += [f"### {p['id']} — `{p['coefficient']}`", "",
                    f"**{p['current']} → {p['proposed']}**"
                    + (f" (the data alone points at {p['point_estimate']}; the proposal moves "
                       f"{p.get('shrinkage_weight', 0):.0%} of the way there)"
                       if p.get("point_estimate") is not None else ""),
                    "",
                    f"- **Evidence:** {p['evidence']}",
                    f"- **Samples:** {p['samples']}"
                    + (" — **weak signal, treat as indicative**" if p.get("weak_signal") else ""),
                    f"- **Needs:** {p['needs']}"]
            if b:
                out.append(f"- **Backtest:** {b['verdict']} — {b['detail']}")
            if p.get("caution"):
                out.append(f"- **Caution:** {p['caution']}")
            out.append("")
    else:
        out += ["## Proposed changes", "",
                "None. Either the model is behaving, or there is not yet enough evidence to move a "
                "coefficient without guessing.", ""]

    reg = analysis.get("regression") or {}
    if reg:
        reason = reg["reason"]
        out += ["## Per-tier calibration", "",
                ("Available. " if reg.get("ready") else "Not available yet. ")
                + reason[0].upper() + reason[1:], ""]

    return "\n".join(out) + "\n"


def brief(analysis):
    """The stable distillate a conversational agent loads to answer 'how accurate are we?'.

    accuracy-report.md is prose written for a person and overwritten each run; analysis.json
    is an internal schema carrying every entry and every intermediate. This is the small,
    stable middle: the headline figures, the direction, and whether anything is pending.
    """
    if analysis["analysis_mode"] == "readiness":
        r = analysis["readiness"]
        return {
            "calibrated": False,
            "state": "readiness",
            "message": analysis.get("message"),
            "ledger_entries": r["ledger_entries"],
            "usable_actuals": r["usable"],
            "awaiting_actuals": [{"id": c["id"], "project": c["project"], "status": c["status"]}
                                 for c in r.get("chase", [])],
            "advice": r["advice"],
        }
    acc = analysis["accuracy"]
    return {
        "calibrated": True,
        "state": "calibration",
        "samples": acc["samples"],
        "band_hit_rate": acc["band_hit_rate"],
        "band_hit_target": acc["band_hit_target"],
        "verdict": verdict_line(acc).replace("**", ""),
        "median_error_pct": acc["median_error_pct"],
        "error_spread_pct": acc["error_spread_pct"],
        "direction": acc["direction"],
        "pending_proposals": [
            {"id": p["id"], "coefficient": p["coefficient"], "current": p["current"],
             "proposed": p["proposed"], "samples": p["samples"],
             "weak_signal": p.get("weak_signal", False)}
            for p in analysis.get("proposals", [])
        ],
        "per_tier_calibration_available": (analysis.get("regression") or {}).get("ready", False),
    }


def to_html(markdown_text, title):
    """A deliberately plain rendering: no recomputation, no embedded model, nothing to drift."""
    body, in_table, in_list = [], False, False
    for line in markdown_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if set("".join(cells)) <= set("-: "):
                continue
            tag = "th" if not in_table else "td"
            if not in_table:
                body.append("<table>")
                in_table = True
            body.append("<tr>" + "".join(f"<{tag}>{html.escape(c)}</{tag}>" for c in cells) + "</tr>")
            continue
        if in_table:
            body.append("</table>")
            in_table = False
        if stripped.startswith("- "):
            if not in_list:
                body.append("<ul>")
                in_list = True
            body.append(f"<li>{inline(stripped[2:])}</li>")
            continue
        if in_list:
            body.append("</ul>")
            in_list = False
        if stripped.startswith("### "):
            body.append(f"<h3>{inline(stripped[4:])}</h3>")
        elif stripped.startswith("## "):
            body.append(f"<h2>{inline(stripped[3:])}</h2>")
        elif stripped.startswith("# "):
            body.append(f"<h1>{inline(stripped[2:])}</h1>")
        elif stripped.startswith("> "):
            body.append(f"<blockquote>{inline(stripped[2:])}</blockquote>")
        elif stripped:
            body.append(f"<p>{inline(stripped)}</p>")
    if in_table:
        body.append("</table>")
    if in_list:
        body.append("</ul>")

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
 :root {{ --bg:#fbfbf9; --panel:#fff; --ink:#1a1a1a; --muted:#6b6b6b; --line:#e3e3df; --accent:#1f5f4f; }}
 @media (prefers-color-scheme: dark) {{ :root {{ --bg:#16171a; --panel:#1e1f23; --ink:#ececed;
   --muted:#9a9a9e; --line:#31323a; --accent:#6fc0a6; }} }}
 body {{ margin:0; background:var(--bg); color:var(--ink);
   font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }}
 main {{ max-width:900px; margin:0 auto; padding:32px 20px 80px; }}
 h1 {{ font-size:26px; letter-spacing:-0.01em; }}
 h2 {{ font-size:14px; text-transform:uppercase; letter-spacing:.07em; color:var(--muted);
   margin-top:34px; }}
 h3 {{ font-size:16px; margin-top:26px; }}
 table {{ width:100%; border-collapse:collapse; font-size:14px; margin:12px 0; background:var(--panel);
   border:1px solid var(--line); border-radius:8px; overflow:hidden; }}
 th,td {{ text-align:left; padding:8px 12px; border-bottom:1px solid var(--line); }}
 th {{ color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.05em; }}
 blockquote {{ margin:12px 0; padding:12px 16px; background:var(--panel); border-left:3px solid var(--accent);
   border-radius:0 6px 6px 0; }}
 code {{ background:var(--panel); padding:1px 5px; border-radius:4px; border:1px solid var(--line); }}
 li {{ margin:3px 0; }}
</style></head><body><main>
{chr(10).join(body)}
</main></body></html>
"""


def inline(text):
    escaped = html.escape(text)
    for pattern, tag in (("**", "strong"), ("`", "code")):
        parts = escaped.split(pattern)
        escaped = "".join(p if i % 2 == 0 else f"<{tag}>{p}</{tag}>" for i, p in enumerate(parts))
    return escaped


def main():
    ap = argparse.ArgumentParser(description="Render the estimate-versus-actual accuracy report.")
    ap.add_argument("analysis", help="analysis JSON from analyze.py")
    ap.add_argument("--backtest", help="backtest JSON from backtest.py")
    ap.add_argument("--out-dir", help="directory for the report (default: alongside the analysis)")
    ap.add_argument("--formats", default="md,html,brief")
    args = ap.parse_args()

    path = Path(args.analysis)
    try:
        analysis = json.loads(path.read_text(encoding="utf-8"))
        backtests = json.loads(Path(args.backtest).read_text(encoding="utf-8")) if args.backtest else None
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 2

    out_dir = Path(args.out_dir) if args.out_dir else path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    text = markdown(analysis, backtests)
    written = []
    if "md" in args.formats:
        target = out_dir / "accuracy-report.md"
        target.write_text(text, encoding="utf-8")
        written.append(str(target))
    if "html" in args.formats:
        target = out_dir / "accuracy-report.html"
        target.write_text(to_html(text, "Estimate accuracy"), encoding="utf-8")
        written.append(str(target))
    if "brief" in args.formats:
        target = out_dir / "accuracy-brief.json"
        target.write_text(json.dumps(brief(analysis), indent=2, ensure_ascii=False) + "\n",
                          encoding="utf-8")
        written.append(str(target))

    print(json.dumps({"ok": True, "written": written, "mode": analysis["analysis_mode"]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
