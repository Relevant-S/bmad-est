#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Assemble the run-cost breakdown from researched vendor rows.

**This script sets no price.** It takes rows that a research pass fetched from vendors' own
pricing pages — each carrying the rate, the tier's own wording as a verbatim quote, the URL and
the date it was fetched — and it does the arithmetic, the totals and the validation. A figure
that appears here and nowhere in a `quote` is a figure somebody typed from memory, and on this
layer that is the exact analogue of invented scope: scope invented from a document can be
argued with, while a wrong AWS figure looks identical to a right one.

Every `cost` is RECOMPUTED from `rate x quantity` rather than restated. The module's standing
rule is that arithmetic is never done by hand, and a row whose supplied cost disagrees with its
own rate is a finding rather than a number to trust.

A price that could not be fetched is `unpriced` with its reason, never guessed. Pricing pages
are increasingly JavaScript-rendered, region-gated or behind *contact sales*; this is the
`needs_native_read` case from est-scope-extract, and the totals say how many rows are missing
so nobody reads one as complete when it is not.

    uv run scripts/price.py <architecture.json> --rows researched-rows.json -o costs.json
"""

import argparse
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

TYPES = ("one-time", "monthly", "annually")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


caps = _load("capabilities", HERE / "capabilities.py")


def compute_cost(row):
    """`rate x quantity`, in the row's own currency, converted if it is not the report currency.

    Returns (value, detail) or (None, reason).
    """
    if row.get("unpriced"):
        return None, row.get("unpriced")
    rate, quantity = row.get("rate"), row.get("quantity", 1)
    if rate is None:
        return None, "no rate was researched"
    try:
        value = float(rate) * float(quantity)
    except (TypeError, ValueError):
        return None, f"rate {rate!r} or quantity {quantity!r} is not a number"
    fx = row.get("fx")
    if fx:
        value *= float(fx.get("rate", 1.0))
    return round(value, 2), None


def price(architecture, rows, model=None, notes=None):
    """Validate, recompute and total. The only thing here that invents anything is the sum."""
    model = model or caps.load_model()
    rule = model["costing"]
    currency = rule["report_currency"]
    known = {c["capability"] for c in architecture.get("components") or []}
    findings, priced = [], []

    for index, row in enumerate(rows or []):
        out = dict(row)
        where = row.get("item") or f"row {index}"

        if row.get("type") not in TYPES:
            findings.append({"kind": "bad_type", "row": where,
                             "detail": f"`type` must be one of {', '.join(TYPES)}; got "
                                       f"{row.get('type')!r}"})
        if not row.get("unpriced"):
            for field in ("quote", "url", "fetched_at"):
                if not row.get(field):
                    findings.append({
                        "kind": "figure_without_a_source", "row": where,
                        "detail": f"`{field}` is missing. Every figure traces to a quote from a "
                                  f"vendor's pricing page, the way every hour traces to a quote "
                                  f"from a client document."})
        if row.get("assumption") and not row.get("assumption_basis"):
            findings.append({
                "kind": "assumption_without_a_basis", "row": where,
                "detail": f"the row assumes `{row['assumption']}` and does not say where that "
                          f"came from. An assumption with no basis is this table's version of a "
                          f"feature with no citation."})
        if row.get("capability") and known and row["capability"] not in known:
            findings.append({"kind": "row_serves_nothing", "row": where,
                             "detail": f"priced for capability `{row['capability']}`, which no "
                                       f"component in the architecture provides"})
        if row.get("fx") and not (row["fx"].get("rate") and row["fx"].get("date")):
            findings.append({"kind": "unrated_conversion", "row": where,
                             "detail": "a row in another currency needs an fx rate and the date "
                                       "it was taken"})

        value, reason = compute_cost(row)
        supplied = row.get("cost")
        if value is not None and supplied is not None and abs(float(supplied) - value) > 0.01:
            findings.append({
                "kind": "cost_does_not_follow_from_its_rate", "row": where,
                "detail": f"the row states {supplied} but {row.get('rate')} x "
                          f"{row.get('quantity', 1)} is {value}. Arithmetic is never done by "
                          f"hand here."})
        out["cost"] = value
        out["unpriced"] = reason if value is None else None
        if value == 0 and not row.get("free_until"):
            findings.append({
                "kind": "zero_without_a_cliff", "row": where,
                "detail": "a zero row must say what ends it. Free-at-this-volume, free-forever "
                          "and free-by-assumption all read as `0`, and the dangerous one is "
                          "invisible."})
        out.setdefault("currency", currency)
        priced.append(out)

    def band(row, edge):
        """`low`/`high` fall back to the point cost when absent OR explicitly null.

        `r.get("low", r["cost"])` returns None for a row carrying `"low": null` — which is the
        exact shape references/costing.md documents for a fixed-price row — and summing None
        raised a TypeError in the totals. The documentation was right and the code could not
        read what it documented.
        """
        value = row.get(edge)
        return row["cost"] if value is None else float(value)

    totals = {}
    for kind in TYPES:
        mine = [r for r in priced if r.get("type") == kind and r["cost"] is not None]
        totals[kind] = {
            "cost": round(sum(r["cost"] for r in mine), 2),
            "low": round(sum(band(r, "low") for r in mine), 2),
            "high": round(sum(band(r, "high") for r in mine), 2),
            "rows": len(mine),
            "unpriced_rows": len([r for r in priced
                                  if r.get("type") == kind and r["cost"] is None]),
        }
    # The number anyone actually asks for, and the one the example format could not show.
    totals["year_one"] = {
        "cost": round(totals["one-time"]["cost"] + 12 * totals["monthly"]["cost"]
                      + totals["annually"]["cost"], 2),
        "low": round(totals["one-time"]["low"] + 12 * totals["monthly"]["low"]
                     + totals["annually"]["low"], 2),
        "high": round(totals["one-time"]["high"] + 12 * totals["monthly"]["high"]
                      + totals["annually"]["high"], 2),
        "formula": "one-time + (12 x monthly) + annually",
    }

    unpriced = [r["item"] for r in priced if r["cost"] is None]
    return {
        "schema_version": "1.0",
        "currency": currency,
        "rows": priced,
        "totals": totals,
        "unpriced": unpriced,
        # Offsets are not costs. "Available" is not "granted", a range is not a figure, and
        # netting either into a total makes the total wrong in the direction everyone likes.
        "notes": list(notes or []),
        "findings": findings,
        "ok": not findings,
        "stated": (f"{len(priced)} row(s), {len(priced) - len(unpriced)} priced from a fetched "
                   f"page and {len(unpriced)} unpriced; totals in {currency}. Run-cost is not "
                   f"delivery cost and the two are never summed."),
    }


def to_rows(costs):
    """The sheet, in the operator's own three columns with the extensions to their right."""
    header = ["Item", "Cost", "Type", "Assumption", "Free until", "Source", "Checked"]
    body = []
    for row in costs["rows"]:
        body.append([
            row.get("item", ""),
            "unpriced" if row["cost"] is None else row["cost"],
            row.get("type", ""),
            row.get("assumption", ""),
            row.get("free_until", ""),
            row.get("url", "") if not row.get("unpriced") else (row.get("unpriced") or ""),
            row.get("fetched_at", ""),
        ])
    body.append([""] * len(header))
    for kind in TYPES:
        total = costs["totals"][kind]
        body.append([f"TOTAL - {kind.replace('-', ' ').title()}", total["cost"], kind,
                     f"{total['rows']} row(s)"
                     + (f", {total['unpriced_rows']} unpriced" if total["unpriced_rows"] else ""),
                     "", "", ""])
    year = costs["totals"]["year_one"]
    body.append(["TOTAL - Year 1", year["cost"], "year 1", year["formula"], "", "", ""])
    return header, body


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("architecture")
    ap.add_argument("--rows", required=True, help="researched rows, one per service")
    ap.add_argument("--notes", help="offsets and caveats that are NOT costs, e.g. cloud credits")
    ap.add_argument("--model")
    ap.add_argument("-o", "--output")
    args = ap.parse_args()

    architecture = json.loads(Path(args.architecture).read_text(encoding="utf-8"))
    rows = json.loads(Path(args.rows).read_text(encoding="utf-8"))
    notes = json.loads(Path(args.notes).read_text(encoding="utf-8")) if args.notes else []
    costs = price(architecture, rows, caps.load_model(args.model), notes)
    text = json.dumps(costs, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if costs["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
