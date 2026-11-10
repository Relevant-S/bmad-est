#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Re-fetch every cited pricing page and check the quoted figure is still on it.

This is what makes "nothing in this table may be invented" mechanical rather than aspirational.
`inventory-check.py` re-opens each source document and verifies every feature's quote against
it; this does the same thing one domain over, and for the same reason: a rule nobody can verify
is a rule that degrades on the first busy day.

It is also the one guard worth the most. A model that has read a thousand AWS pricing pages will
produce a confident, plausible, wrong number faster than it will admit it could not reach the
page, and a wrong price is indistinguishable from a right one on the page.

Three verdicts, kept apart on purpose:

  * **verified** — the quoted text is on the page as fetched.
  * **not_found** — the page was fetched and the quote is not in it. The dangerous one: the
    figure was fabricated, or the price moved. Either way it must not be quoted.
  * **unreachable** — the page could not be fetched at all, or renders its prices in
    JavaScript. NOT evidence of anything; the row simply has not been re-checked.

    uv run scripts/cost-check.py <costs.json> [--offline] [-o cost-check.json]

Exit 0 when nothing is `not_found`, 1 when anything is, 2 when it could not run.
"""

import argparse
import datetime as dt
import html
import importlib.util
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
UA = "bmad-est-architect/1.0 (cost verification; contact the operator of this workspace)"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


caps = _load("capabilities", HERE / "capabilities.py")


def normalise(text):
    """Strip tags, unescape entities and collapse whitespace, so a quote that wrapped across
    two lines on the page still matches the one that was recorded."""
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", text or "",
                  flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip().lower()


# Vendors geo-redirect. stripe.com serves a EUR/PT edition to a European visitor, so every
# Stripe row in a real run read `not_found` although all six quotes were on the US page. A
# verdict that depends on where the machine is sitting is not a verdict.
LOCALES = {
    "us": {"headers": {"Accept-Language": "en-US,en;q=0.9"},
           "cookie": "country=US; preferred_locale=en-US"},
    "gb": {"headers": {"Accept-Language": "en-GB,en;q=0.9"},
           "cookie": "country=GB; preferred_locale=en-GB"},
    "de": {"headers": {"Accept-Language": "de-DE,de;q=0.9"},
           "cookie": "country=DE; preferred_locale=de-DE"},
}


# AWS publishes its price list as per-service, per-region JSON, and price.py prefers it over a
# marketing page. Those files run to tens of megabytes (RDS eu-west-2: 22 MB).
MAX_PAGE_BYTES = 64_000_000

def fetch(url, timeout=60, locale=None):
    spec = LOCALES.get((locale or "").lower()) or {}
    try:
        headers = {"User-Agent": UA}
        headers.update(spec.get("headers") or {})
        if spec.get("cookie"):
            headers["Cookie"] = spec["cookie"]
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_PAGE_BYTES + 1)
        # A page longer than the cap was NOT read, so nothing can be said about a quote on it.
        # This used to read 3 MB and stop: AWS's machine-readable RDS price list for one region
        # is 22 MB, its PostgreSQL rows sit past the cut, and three quotes that were verbatim on
        # the page came back `not_found` — the verdict that means "fabricated or moved", on text
        # the checker never looked at (passenger-seat, 2026-11-10).
        if len(raw) > MAX_PAGE_BYTES:
            return None, (f"page larger than {MAX_PAGE_BYTES // 1_000_000} MB; not read in full, "
                          f"so the quote was not checked")
        return normalise(raw.decode("utf-8", "replace")), None
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def audit(costs, offline=False, model=None, today=None, fetcher=fetch, locale=None):
    model = model or caps.load_model()
    stale_after = model["costing"]["stale_after_days"]
    today = today or dt.date.today()
    findings, results = [], []
    pages = {}

    for row in costs.get("rows") or []:
        item = row.get("item") or "?"
        if row.get("unpriced"):
            results.append({"item": item, "verdict": "unpriced",
                            "detail": row.get("unpriced")})
            continue

        checked = row.get("fetched_at")
        if checked:
            try:
                age = (today - dt.date.fromisoformat(str(checked)[:10])).days
            except ValueError:
                age = None
                findings.append({"kind": "unreadable_date", "row": item,
                                 "detail": f"`fetched_at` is {checked!r}, which is not a date"})
            if age is not None and age > stale_after:
                findings.append({
                    "kind": "stale_price", "row": item,
                    "detail": f"fetched {age} days ago, past the {stale_after}-day threshold. "
                              f"Published cloud prices move on roughly a quarterly cadence and a "
                              f"figure older than half of one should be re-checked before it "
                              f"goes in front of a client."})

        url, quote = row.get("url"), row.get("quote")
        if not (url and quote):
            results.append({"item": item, "verdict": "unreachable",
                            "detail": "the row carries no url or no quote"})
            continue
        if offline:
            results.append({"item": item, "verdict": "unreachable",
                            "detail": "offline: the page was not re-fetched"})
            continue

        if url not in pages:
            try:
                pages[url] = fetcher(url, locale=locale) if locale else fetcher(url)
            except TypeError:                       # a fetcher that takes the url alone
                pages[url] = fetcher(url)
        body, error = pages[url]
        if body is None:
            results.append({"item": item, "verdict": "unreachable", "detail": error})
            continue
        needle = normalise(quote)
        if needle and needle in body:
            results.append({"item": item, "verdict": "verified", "detail": url})
        else:
            results.append({"item": item, "verdict": "not_found", "detail": url})
            findings.append({
                "kind": "quote_not_on_the_page", "row": item,
                "detail": f"the quoted text is not on {url} as fetched. Either the figure was "
                          f"never on that page, or the price moved, or the page renders its "
                          f"prices in JavaScript. It must not be quoted until somebody looks."})

    verdicts = {}
    for result in results:
        verdicts[result["verdict"]] = verdicts.get(result["verdict"], 0) + 1

    return {
        "ok": not any(f["kind"] == "quote_not_on_the_page" for f in findings) and not findings,
        "offline": bool(offline),
        "locale": locale,
        "results": results,
        "verdicts": verdicts,
        "findings": findings,
        "checked": (f"{len(results)} row(s): {verdicts.get('verified', 0)} verified against the "
                    f"cited page, {verdicts.get('not_found', 0)} not found on it, "
                    f"{verdicts.get('unreachable', 0)} unreachable, "
                    f"{verdicts.get('unpriced', 0)} unpriced"
                    + (f", fetched as the {locale.upper()} edition" if locale else "")
                    + (" — OFFLINE, so nothing was actually re-fetched" if offline else "")),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("costs")
    ap.add_argument("--locale", choices=sorted(LOCALES),
                    help="fetch each page as this locale's edition. A vendor that geo-redirects "
                         "serves a different page to a different machine, and a quote absent "
                         "from the wrong edition is not a missing quote.")
    ap.add_argument("--offline", action="store_true",
                    help="skip the network; check dates and structure only, and say so")
    ap.add_argument("-o", "--output")
    args = ap.parse_args()

    path = Path(args.costs)
    if not path.exists():
        print(json.dumps({"ok": False, "error": f"no costs at {path}"}, indent=2))
        return 2
    report = audit(json.loads(path.read_text(encoding="utf-8")), args.offline,
                   locale=args.locale)
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
