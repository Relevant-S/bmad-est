#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Tests for price.py and cost-check.py — the run-cost breakdown.

This is the point in the whole workflow where fabrication is most likely, because a model that
has read a thousand AWS pricing pages will produce a plausible number faster than it will admit
it could not reach the page. So the tests are mostly about what the table REFUSES: a figure with
no source, a zero with no cliff, a cost that does not follow from its own rate, a quote that is
not on the page it cites.
"""

import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fixtures as F  # noqa: E402

arch = F.load("architect", F.ARCH / "scripts" / "architect.py")
price = F.load("price", F.ARCH / "scripts" / "price.py")
cost_check = F.load("cost_check", F.ARCH / "scripts" / "cost-check.py")

TODAY = dt.date.today().isoformat()


def architecture():
    return arch.build_architecture(F.clinical(), F.model(), F.caps.load_platforms(),
                                   {"house_platforms": ["aws"]})


def row(**kw):
    base = {"item": "Managed Postgres — AWS RDS db.t4g.micro", "capability": "relational_store",
            "type": "monthly", "rate": 45.0, "quantity": 1, "unit": "instance-month",
            "assumption": "1 instance, 20 GB gp3", "assumption_basis": "operator",
            "quote": "db.t4g.micro $0.062 per hour", "url": "https://example.invalid/rds",
            "fetched_at": TODAY}
    base.update(kw)
    return base


class EveryFigureTracesToAPage(unittest.TestCase):
    def test_a_row_with_no_source_is_a_finding(self):
        out = price.price(architecture(), [row(quote=None, url=None, fetched_at=None)])
        kinds = [f["kind"] for f in out["findings"]]
        self.assertEqual(3, kinds.count("figure_without_a_source"))
        self.assertIn("every hour traces to a quote", out["findings"][0]["detail"].lower())

    def test_a_properly_sourced_row_raises_nothing(self):
        self.assertTrue(price.price(architecture(), [row()])["ok"])

    def test_an_assumption_without_a_basis_is_a_finding(self):
        out = price.price(architecture(), [row(assumption_basis=None)])
        finding = next(f for f in out["findings"]
                       if f["kind"] == "assumption_without_a_basis")
        self.assertIn("feature with no citation", finding["detail"])

    def test_a_row_for_a_capability_nothing_provides_is_caught(self):
        out = price.price(architecture(), [row(capability="quantum_annealer")])
        self.assertIn("row_serves_nothing", [f["kind"] for f in out["findings"]])


class ArithmeticIsNeverDoneByHand(unittest.TestCase):
    def test_cost_is_recomputed_from_rate_times_quantity(self):
        out = price.price(architecture(), [row(rate=12.5, quantity=4)])
        self.assertEqual(50.0, out["rows"][0]["cost"])

    def test_a_supplied_cost_that_disagrees_with_its_rate_is_caught(self):
        out = price.price(architecture(), [row(rate=45.0, quantity=1, cost=450.0)])
        finding = next(f for f in out["findings"]
                       if f["kind"] == "cost_does_not_follow_from_its_rate")
        self.assertIn("45.0 x 1 is 45.0", finding["detail"])

    def test_a_foreign_currency_needs_a_rate_and_a_date(self):
        out = price.price(architecture(), [row(currency="GBP", fx={"rate": 1.27})])
        self.assertIn("unrated_conversion", [f["kind"] for f in out["findings"]])

    def test_a_converted_row_is_converted(self):
        out = price.price(architecture(), [row(rate=10.0, currency="GBP",
                                               fx={"rate": 1.3, "date": TODAY})])
        self.assertEqual(13.0, out["rows"][0]["cost"])


class AZeroMustSayWhatEndsIt(unittest.TestCase):
    def test_a_zero_row_with_no_cliff_is_a_finding(self):
        out = price.price(architecture(), [row(rate=0.0, item="Auth — Cognito free tier")])
        finding = next(f for f in out["findings"] if f["kind"] == "zero_without_a_cliff")
        self.assertIn("the dangerous one is invisible", finding["detail"])

    def test_a_zero_row_that_names_its_threshold_is_fine(self):
        out = price.price(architecture(),
                          [row(rate=0.0, capability="identity", free_until="50,000 MAU")])
        self.assertEqual([], [f for f in out["findings"]
                              if f["kind"] == "zero_without_a_cliff"])


class TheTotals(unittest.TestCase):
    def setUp(self):
        self.costs = price.price(architecture(), [
            row(type="monthly", rate=45.0, capability="relational_store"),
            row(type="monthly", rate=10.0, capability="object_store", item="S3"),
            row(type="annually", rate=15.0, capability="web_client", item="Domain"),
            row(type="one-time", rate=500.0, capability="application", item="Migration"),
        ])

    def test_each_type_totals_separately(self):
        self.assertEqual(55.0, self.costs["totals"]["monthly"]["cost"])
        self.assertEqual(15.0, self.costs["totals"]["annually"]["cost"])
        self.assertEqual(500.0, self.costs["totals"]["one-time"]["cost"])

    def test_year_one_is_the_number_anyone_actually_asks_for(self):
        """The example format's three totals are each correct and none of them is this."""
        year = self.costs["totals"]["year_one"]
        self.assertEqual(500.0 + 12 * 55.0 + 15.0, year["cost"])
        self.assertEqual("one-time + (12 x monthly) + annually", year["formula"])

    def test_a_usage_row_widens_the_band_rather_than_asserting_a_point(self):
        costs = price.price(architecture(), [
            row(type="monthly", rate=200.0, low=80.0, high=600.0, capability="ai_inference",
                item="Model inference")])
        monthly = costs["totals"]["monthly"]
        self.assertEqual((80.0, 200.0, 600.0), (monthly["low"], monthly["cost"], monthly["high"]))

    def test_the_sheet_keeps_the_operators_three_columns_first(self):
        header, body = price.to_rows(self.costs)
        self.assertEqual(["Item", "Cost", "Type"], header[:3])
        self.assertIn("TOTAL - Year 1", [r[0] for r in body])

    def test_an_unpriced_row_is_visible_in_the_total_rather_than_silently_dropped(self):
        costs = price.price(architecture(), [
            row(type="monthly", rate=45.0, capability="relational_store"),
            row(type="monthly", rate=None, capability="object_store", item="Something gated",
                unpriced="behind contact sales")])
        self.assertEqual(["Something gated"], costs["unpriced"])
        self.assertEqual(1, costs["totals"]["monthly"]["unpriced_rows"])
        header, body = price.to_rows(costs)
        self.assertIn("unpriced", [str(r[1]) for r in body])


class CreditsAreNotCosts(unittest.TestCase):
    def test_a_credit_lives_in_the_notes_and_not_in_a_total(self):
        """'Cloud credits, ~$1k-$5k available' at 0 is three category errors in one row: an
        offset rather than a cost, a range rather than a figure, and available is not granted."""
        costs = price.price(architecture(), [row(type="monthly", rate=45.0)],
                            notes=["Cloud credits: startup programmes may offset year one. "
                                   "Not secured, not netted into any total."])
        self.assertEqual(45.0, costs["totals"]["monthly"]["cost"])
        self.assertEqual(1, len(costs["notes"]))
        self.assertIn("not netted into any total", costs["notes"][0])


class TheRefetchIsWhatMakesTheRuleMechanical(unittest.TestCase):
    def costs(self, **kw):
        return price.price(architecture(), [row(**kw)])

    def test_a_quote_present_on_the_page_verifies(self):
        def fetcher(url):
            return cost_check.normalise("<p>db.t4g.micro  $0.062 per   hour</p>"), None
        report = cost_check.audit(self.costs(), fetcher=fetcher)
        self.assertTrue(report["ok"])
        self.assertEqual(1, report["verdicts"]["verified"])

    def test_a_quote_absent_from_the_page_fails_the_run(self):
        def fetcher(url):
            return cost_check.normalise("<p>pricing has changed</p>"), None
        report = cost_check.audit(self.costs(), fetcher=fetcher)
        self.assertFalse(report["ok"])
        finding = next(f for f in report["findings"]
                       if f["kind"] == "quote_not_on_the_page")
        self.assertIn("must not be quoted until somebody looks", finding["detail"])

    def test_an_unreachable_page_is_not_evidence_of_anything(self):
        """Distinct from not_found on purpose: a JavaScript-rendered page means the row has not
        been re-checked, not that the figure is wrong."""
        def fetcher(url):
            return None, "URLError: blocked"
        report = cost_check.audit(self.costs(), fetcher=fetcher)
        self.assertEqual(1, report["verdicts"]["unreachable"])
        self.assertEqual([], [f for f in report["findings"]
                              if f["kind"] == "quote_not_on_the_page"])

    def test_a_stale_price_is_a_finding_with_its_age(self):
        old = (dt.date.today() - dt.timedelta(days=200)).isoformat()
        def fetcher(url):
            return cost_check.normalise("db.t4g.micro $0.062 per hour"), None
        report = cost_check.audit(self.costs(fetched_at=old), fetcher=fetcher)
        finding = next(f for f in report["findings"] if f["kind"] == "stale_price")
        self.assertIn("200 days ago", finding["detail"])

    def test_offline_says_it_verified_nothing(self):
        report = cost_check.audit(self.costs(), offline=True)
        self.assertIn("OFFLINE", report["checked"])
        self.assertEqual(1, report["verdicts"]["unreachable"])

    def test_it_says_how_many_of_each_verdict(self):
        def fetcher(url):
            return cost_check.normalise("db.t4g.micro $0.062 per hour"), None
        report = cost_check.audit(self.costs(), fetcher=fetcher)
        self.assertIn("1 row(s)", report["checked"])
        self.assertIn("verified against the cited page", report["checked"])


class TheLocaleReachesTheRequest(unittest.TestCase):
    """stripe.com serves a EUR/PT edition to a European visitor, so all six Stripe rows in a
    real run read `not_found` although every quote was on the US page. A verdict that depends
    on where the machine is sitting is not a verdict.

    Asserted on the request that would be sent, because this machine has no network: the value
    of the fix is that the right headers go out, and that is checkable here.
    """

    def _request(self, locale):
        import urllib.request
        captured = {}

        def urlopen(request, timeout=None):
            captured["headers"] = dict(request.header_items())
            raise OSError("no network in this test")

        original = urllib.request.urlopen
        urllib.request.urlopen = urlopen
        try:
            cost_check.fetch("https://example.invalid/pricing", locale=locale)
        finally:
            urllib.request.urlopen = original
        return {k.lower(): v for k, v in captured.get("headers", {}).items()}

    def test_a_locale_sends_its_language_and_country_cookie(self):
        headers = self._request("us")
        self.assertIn("en-US", headers.get("Accept-language".lower(), ""))
        self.assertIn("country=US", headers.get("cookie", ""))

    def test_another_locale_sends_a_different_one(self):
        headers = self._request("de")
        self.assertIn("de-DE", headers.get("Accept-language".lower(), ""))

    def test_no_locale_sends_no_cookie(self):
        headers = self._request(None)
        self.assertNotIn("cookie", headers)
        self.assertIn("bmad-est-architect", headers.get("user-agent", ""))

    def test_the_report_says_which_edition_it_read(self):
        report = cost_check.audit(
            price.price({"components": [{"capability": "relational_store"}]}, [row()]),
            fetcher=lambda url, locale=None: (
                cost_check.normalise("db.t4g.micro $0.062 per hour"), None),
            locale="us")
        self.assertEqual("us", report["locale"])
        self.assertIn("fetched as the US edition", report["checked"])


class TheHtmlStrippingSurvivesRealPages(unittest.TestCase):
    def test_a_quote_split_across_tags_and_lines_still_matches(self):
        page = "<div>db.t4g.micro</div>\n<span>$0.062</span>  <b>per hour</b>"
        self.assertIn(cost_check.normalise("db.t4g.micro $0.062 per hour"),
                      cost_check.normalise(page))

    def test_script_contents_are_not_searched(self):
        """A price that appears only inside a script tag has not been published on the page a
        reader would open."""
        page = "<script>var price='db.t4g.micro $0.062 per hour'</script><p>see pricing</p>"
        self.assertNotIn(cost_check.normalise("db.t4g.micro $0.062 per hour"),
                         cost_check.normalise(page))


class APageTooLongToReadIsNotEvidence(unittest.TestCase):
    """passenger-seat, 2026-11-10: the fetch read 3 MB and stopped. AWS's RDS price list for one
    region is 22 MB, and three verbatim quotes past the cut came back `not_found` — the verdict
    that means fabricated or moved."""

    class Response:
        def __init__(self, body):
            self.body = body

        def read(self, n=-1):
            return self.body if n < 0 else self.body[:n]

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fetch_with(self, body):
        original = cost_check.urllib.request.urlopen
        cost_check.urllib.request.urlopen = lambda request, timeout=None: self.Response(body)
        try:
            return cost_check.fetch("https://example.test/prices.json")
        finally:
            cost_check.urllib.request.urlopen = original

    def test_a_quote_past_the_old_three_megabyte_cut_is_read(self):
        body = b" " * 4_000_000 + b"$ 0.036 per RDS db.t4g.small Single-AZ instance hour"
        text, error = self.fetch_with(body)
        self.assertIsNone(error)
        self.assertIn("0.036 per rds db.t4g.small", text)

    def test_a_page_over_the_cap_is_unread_rather_than_missing_a_quote(self):
        body = b"x" * (cost_check.MAX_PAGE_BYTES + 1)
        text, error = self.fetch_with(body)
        self.assertIsNone(text)
        self.assertIn("not read in full", error)


if __name__ == "__main__":
    unittest.main()
