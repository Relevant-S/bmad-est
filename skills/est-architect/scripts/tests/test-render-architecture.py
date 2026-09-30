#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Tests for render-architecture.py — the document a human actually reads.

A render test is not about formatting. It is about whether the things this module refuses to
let a reader misunderstand actually reach the page: that run-cost is not delivery cost, that an
unpriced row is visible rather than dropped, that a score resting on nothing says so, and that
the picture and the text underneath it describe the same architecture.
"""

import csv
import datetime as dt
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fixtures as F  # noqa: E402

arch = F.load("architect", F.ARCH / "scripts" / "architect.py")
ra = F.load("render_architecture", F.ARCH / "scripts" / "render-architecture.py")
pr = F.load("price", F.ARCH / "scripts" / "price.py")
chk = F.load("check", F.ARCH / "scripts" / "architecture-check.py")

TODAY = dt.date.today().isoformat()
STACKS = [{"id": "ts", "name": "TypeScript end to end", "axis": "one language throughout",
           "technologies": ["typescript", "node"], "deployable_services": 1,
           "libraries": {"identity": "a library"},
           "currency": {"score": 9.0, "checked": TODAY, "note": "current major"}, "gaps": []}]


def rows():
    return [
        {"item": "Managed Postgres — AWS RDS db.t4g.micro", "capability": "relational_store",
         "type": "monthly", "rate": 45.0, "quantity": 1, "assumption": "1 instance, 20 GB gp3",
         "assumption_basis": "operator", "quote": "db.t4g.micro",
         "url": "https://aws.amazon.com/rds/postgresql/pricing/", "fetched_at": TODAY},
        {"item": "Auth — Amazon Cognito free tier", "capability": "identity", "type": "monthly",
         "rate": 0.0, "quantity": 1, "assumption": "25 monthly active users",
         "assumption_basis": "operator", "free_until": "50,000 MAU", "quote": "free tier",
         "url": "https://aws.amazon.com/cognito/pricing/", "fetched_at": TODAY},
        {"item": "Enterprise support", "capability": "application", "type": "annually",
         "rate": None, "unpriced": "behind contact sales"},
    ]


def rendered(costs=True):
    inventory = F.clinical()
    platforms = F.caps.load_platforms()
    architecture = arch.build_architecture(inventory, F.model(), platforms,
                                           {"house_platforms": ["aws"]}, stacks=STACKS)
    architecture["check"] = chk.audit(architecture, inventory)
    priced = pr.price(architecture, rows(), F.model(),
                      notes=["Cloud credits: startup programmes may offset year one. "
                             "Not secured, not netted into any total."]) if costs else None
    return architecture, priced, ra.markdown(architecture, priced, "architecture.png",
                                             architecture["check"], F.model(), platforms)


class TheCostBoundaryIsStatedWhereverCostAppears(unittest.TestCase):
    def test_the_run_cost_section_says_it_is_not_delivery_cost(self):
        """Somebody will otherwise add twelve months of run-cost to a project quote."""
        _, _, md = rendered()
        self.assertIn("Run-cost is not delivery cost", md)
        self.assertIn("The two are never summed", md)

    def test_it_says_so_even_when_there_is_no_cost_breakdown(self):
        _, _, md = rendered(costs=False)
        self.assertIn("Run-cost is not delivery cost", md)


class TheCostTableKeepsWhatTheReaderNeeds(unittest.TestCase):
    def setUp(self):
        _, self.costs, self.md = rendered()

    def test_the_operators_three_columns_come_first(self):
        self.assertIn("| Item | Cost | Type | Assumption | Free until | Source | Checked |",
                      self.md)

    def test_the_year_one_total_is_there(self):
        self.assertIn("TOTAL - Year 1", self.md)

    def test_a_free_row_shows_the_threshold_that_ends_it(self):
        self.assertIn("50,000 MAU", self.md)

    def test_an_unpriced_row_is_visible_rather_than_dropped(self):
        self.assertIn("could not be priced", self.md)
        self.assertIn("Enterprise support", self.md)
        self.assertIn("never guessed", self.md)

    def test_credits_are_a_note_and_not_a_row(self):
        self.assertIn("Not costs, and not netted into any total", self.md)
        self.assertEqual(45.0, self.costs["totals"]["monthly"]["cost"])

    def test_the_csv_carries_the_same_rows(self):
        header, body = pr.to_rows(self.costs)
        handle = io.StringIO()
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(body)
        text = handle.getvalue()
        self.assertIn("Managed Postgres", text)
        self.assertIn("TOTAL - Year 1", text)


class ThePictureAndTheTextDescribeOneArchitecture(unittest.TestCase):
    def test_the_mermaid_bands_match_the_diagram_bands(self):
        architecture, _, md = rendered()
        layout = F.load("layout", F.ARCH / "scripts" / "layout.py")
        bands, _ = layout.plan(architecture, F.model())
        for band in bands:
            label = band["label"] or F.caps.load_platforms().get(band["id"], {}).get("name")
            self.assertIn(f'["{label}"]', md, f"band {label} is missing from the text form")

    def test_a_built_component_is_not_shown_as_third_party(self):
        """Deriving the bands a second time here put every built component in a third-party
        group while the diagram correctly drew it inside the platform hosting it."""
        _, _, md = rendered()
        block = md.split("```mermaid")[1].split("```")[0]
        third_party = block.split('subgraph _external')[1] if 'subgraph _external' in block else ""
        self.assertNotIn("Relational data store", third_party)

    def test_the_mode_is_on_every_node(self):
        _, _, md = rendered()
        block = md.split("```mermaid")[1].split("```")[0]
        self.assertIn("<i>build</i>", block)
        self.assertIn("<i>buy</i>", block)


class WhatRestsOnNothingIsNamed(unittest.TestCase):
    def test_unsourced_subscores_are_listed(self):
        _, _, md = rendered()
        self.assertIn("## What rests on nothing", md)
        self.assertIn("`stack.team_fit`", md)

    def test_a_null_subscore_renders_as_a_dash_rather_than_a_number(self):
        _, _, md = rendered()
        self.assertIn("| team fit | — |", md)


class TheDocumentCarriesTheArgument(unittest.TestCase):
    def setUp(self):
        _, _, self.md = rendered()

    def test_every_layer_has_a_section(self):
        for heading in ("## Technology stack", "## Sourcing — build, adopt or buy",
                        "## Platform set"):
            self.assertIn(heading, self.md)

    def test_refusals_are_shown_with_their_reasons(self):
        self.assertIn("## Refused, and why", self.md)
        self.assertIn("nobody can argue with", self.md)

    def test_catalogue_gaps_are_separated_from_option_gaps(self):
        self.assertIn("## Catalogue gaps", self.md)
        self.assertIn("not in any option", self.md)

    def test_the_audit_verdict_and_its_denominator_are_on_the_page(self):
        self.assertIn("## Audit", self.md)
        self.assertIn("PASSED", self.md)
        self.assertIn("capability-to-story links", self.md)

    def test_the_asserted_sourcing_coefficient_is_flagged_in_the_prose(self):
        self.assertIn("**asserted** coefficient with no", self.md)

    def test_an_unconfirmed_sourcing_table_says_so(self):
        self.assertIn("Not confirmed by the operator", self.md)


if __name__ == "__main__":
    unittest.main()
