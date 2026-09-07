#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Tests for check-parity.py — executed cross-language parity.

The interactive report reimplements the aggregation in JavaScript so a presale lead can cut
scope against a live number. Duplicated model logic drifts: the JS once omitted the
systematic model-risk term and rendered a band half the real width, beneath a headline that
included it. Nothing caught it because no test ran the JS. These do.
"""

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fixtures import feature, inventory, model, options  # noqa: E402

SCRIPTS = Path(__file__).resolve().parent.parent


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


est = load("estimate", "estimate.py")
parity = load("check_parity", "check-parity.py")


def estimate_for(features=None, **opt):
    inv = inventory(features)
    opt.setdefault("granularity", inv.get("granularity", "project"))
    return est.build_estimate(inv, model(), options(**opt))


class TestParity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def wide_estimate(self):
        return estimate_for([feature(f"F{i}", f"Thing {i}", size="L", clarity="low")
                             for i in range(1, 7)], completeness=0.4)

    def test_the_parity_block_is_still_delimited_in_the_template(self):
        block = parity.parity_block()
        self.assertIn("function compute", block)
        self.assertIn("model_risk", block)

    @unittest.skipIf(shutil.which("node") is None, "node not available")
    def test_the_javascript_reproduces_the_engine_across_the_whole_interval(self):
        e = self.wide_estimate()
        js = parity.run_js(e, {"stack": "standard_saas", "qa_platform": "web",
                               "engagement": "standard"})
        self.assertEqual(parity.compare(e, js), [])

    @unittest.skipIf(shutil.which("node") is None, "node not available")
    def test_parity_covers_phases_and_roles_not_only_the_total(self):
        e = self.wide_estimate()
        js = parity.run_js(e, {"stack": "standard_saas", "qa_platform": "web",
                               "engagement": "standard"})
        self.assertEqual(set(js["phases"]), set(e["by_phase"]))
        self.assertEqual(set(js["roles"]), set(e["by_role"]))

    @unittest.skipIf(shutil.which("node") is None, "node not available")
    def test_a_divergent_browser_result_is_reported_not_tolerated(self):
        """Proves the harness can fail: the omission it was written for was 99 hours wide."""
        e = self.wide_estimate()
        js = parity.run_js(e, {"stack": "standard_saas", "qa_platform": "web",
                               "engagement": "standard"})
        js["likely"] += 50.0
        drift = parity.compare(e, js)
        self.assertTrue(any(d["field"] == "total_hours.likely" for d in drift))

    @unittest.skipIf(shutil.which("node") is None, "node not available")
    def test_rounding_alone_does_not_trip_the_check(self):
        e = self.wide_estimate()
        js = parity.run_js(e, {"stack": "standard_saas", "qa_platform": "web",
                               "engagement": "standard"})
        js["low"] += 0.04
        self.assertEqual(parity.compare(e, js), [])


if __name__ == "__main__":
    unittest.main()
