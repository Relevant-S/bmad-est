#!/usr/bin/env python3
"""Tests for fit-anchor.py.

The failure this guards against is the one that produced a review rate of 0.016: attributing
a whole project's error to whichever coefficient family happens to be reachable, and reporting
it with the confidence of a measurement. The script's job is as much to refuse an attribution
as to make one.
"""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("fit_anchor", SCRIPTS / "fit-anchor.py")
fit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fit)


def entry(total=1000.0, actual=500.0, by_role=None, actual_roles=None, **actuals):
    return {
        "project": "test",
        "total_hours": {"low": 800.0, "likely": total, "high": 1200.0},
        "by_role": by_role or {"dev": 600.0, "qa": 200.0, "ux": 200.0},
        "by_phase": {"build": {"hours": 400.0}, "qa": {"hours": 200.0}},
        "ledger": {"id": "EST-1", "status": "delivered", "actuals": dict(
            {"granularity": "project", "delivery_hours": actual, "scope_delivered": "as_estimated",
             "source": "test", "confidence": "reconstructed", "captured": "2026-01-01",
             "by_role": actual_roles or {"dev": 300.0, "qa": 50.0, "ux": 150.0}}, **actuals)},
    }


class Attribution(unittest.TestCase):
    def test_the_headline_ratio_is_the_project_ratio(self):
        a = fit.attribute(entry(), {})
        self.assertEqual(a["total"], {"estimated": 1000.0, "actual": 500.0, "ratio": 2.0})

    def test_qa_is_separable_because_it_maps_to_one_component(self):
        """`role_weights.qa` is qa 1.0, so the qa role IS the qa component. No other role has
        that property, and pretending otherwise is where blended evidence turns into a
        confident coefficient."""
        a = fit.attribute(entry(), {})
        qa = next(s for s in a["separable"] if s["role"] == "qa")
        self.assertEqual(qa["observed_ratio"], 4.0)      # 200 predicted / 50 actual
        self.assertEqual(qa["factor"], 0.25)
        self.assertEqual([s["role"] for s in a["separable"]], ["qa"])

    def test_every_other_role_is_reported_as_blended_not_as_a_coefficient(self):
        a = fit.attribute(entry(), {})
        self.assertEqual({b["role"] for b in a["blended"]}, {"dev", "ux"})
        for b in a["blended"]:
            self.assertNotIn("factor", b)

    def test_a_role_whose_share_is_right_is_not_called_mis_weighted(self):
        """Everything over by the same factor is a scale error, not a split error. Reading it
        as a split error moves weights that were correct."""
        a = fit.attribute(entry(by_role={"dev": 600.0, "ux": 400.0},
                                actual_roles={"dev": 300.0, "ux": 200.0}), {})
        for b in a["blended"]:
            self.assertIn("about right", b["reading"], b["role"])

    def test_an_under_weighted_role_is_named_as_such(self):
        a = fit.attribute(entry(by_role={"dev": 900.0, "ux": 100.0},
                                actual_roles={"dev": 300.0, "ux": 200.0}), {})
        ux = next(b for b in a["blended"] if b["role"] == "ux")
        self.assertIn("under-weighted", ux["reading"])


class Refusals(unittest.TestCase):
    """What it will not claim is the point."""

    def test_it_says_bands_and_rates_cannot_be_separated_without_phase_actuals(self):
        a = fit.attribute(entry(), {})
        self.assertTrue(any("cannot be separated" in n for n in a["not_identifiable"]))

    def test_phase_actuals_remove_that_caveat(self):
        a = fit.attribute(entry(by_phase={"build": 200.0, "qa": 50.0}), {})
        self.assertFalse(any("cannot be separated" in n for n in a["not_identifiable"]))
        self.assertIsNotNone(a["by_phase"])

    def test_the_uniform_scale_is_emitted_with_its_own_warning(self):
        """It is the one thing analyze.py can propose and the one most likely to be wrong."""
        a = fit.attribute(entry(), {})
        scale = next(s for s in a["suggested"] if s["path"] == "size_bands.*")
        self.assertEqual(scale["factor"], 0.5)
        self.assertIn("absorb every other coefficient", scale["why"])
        self.assertTrue(scale["caution"])

    def test_no_actuals_at_all_is_refused_rather_than_attributed(self):
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as tmp:
            bare = entry()
            bare["ledger"]["actuals"] = {}
            e = Path(tmp) / "e.json"; e.write_text(json.dumps(bare))
            m = Path(tmp) / "m.json"; m.write_text("{}")
            proc = subprocess.run([sys.executable, str(SCRIPTS / "fit-anchor.py"),
                                   "--entry", str(e), "--cost-model", str(m)],
                                  capture_output=True, text=True)
            self.assertEqual(proc.returncode, 1)
            self.assertIn("ingest-actuals.py", json.loads(proc.stdout)["error"])


class AgainstTheRealAnchor(unittest.TestCase):
    """The EPP entry this script was written for, if it is on this machine."""

    LEDGER = Path("/Users/Ostap/Projects/estimation/_bmad/memory/est/ledger/EST-20260908-epp.json")

    def test_it_reproduces_the_epp_attribution(self):
        if not self.LEDGER.exists():
            self.skipTest("EPP anchor not on this machine")
        a = fit.attribute(json.loads(self.LEDGER.read_text()), {})
        self.assertEqual(a["total"]["ratio"], 5.83)
        qa = next(s for s in a["separable"] if s["role"] == "qa")
        self.assertEqual(qa["observed_ratio"], 15.26)
        under = {b["role"] for b in a["blended"] if "under-weighted" in b["reading"]}
        self.assertEqual(under, {"ux", "devops"})


if __name__ == "__main__":
    unittest.main()
