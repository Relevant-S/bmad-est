#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Tests for apply.py — the only place in the module that writes to the cost model.

The properties that matter are that a change carries its provenance into the model itself,
that the previous values survive, and that both kinds of proposal apply correctly.
"""

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fixtures import model  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "apply", Path(__file__).resolve().parent.parent / "apply.py")
ap = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ap)

BACKTEST = {"verdict": "improves past estimates", "improved": 7, "worsened": 0, "samples": 7,
            "before": {"band_hit_rate": 0.4, "median_abs_error_pct": 20.0},
            "after": {"band_hit_rate": 0.7, "median_abs_error_pct": 11.0}}


class TestAbsoluteChanges(unittest.TestCase):
    def proposal(self, value=0.28):
        return {"id": "P1", "coefficient": "uncertainty.model_risk", "kind": "absolute",
                "current": 0.15, "proposed": value, "samples": 7, "why": "band too narrow"}

    def test_the_value_is_set(self):
        m = model()
        ap.apply_one(m, self.proposal(), BACKTEST, "Ostap", "2026-09-07")
        self.assertEqual(m["uncertainty"]["model_risk"], 0.28)

    def test_the_previous_value_is_recorded_beside_it(self):
        m = model()
        ap.apply_one(m, self.proposal(), BACKTEST, "Ostap", "2026-09-07")
        self.assertIn("Previous value 0.15", m["uncertainty"]["model_risk_why"])

    def test_the_approver_and_the_backtest_are_stamped_into_the_model(self):
        m = model()
        ap.apply_one(m, self.proposal(), BACKTEST, "Ostap", "2026-09-07")
        why = m["uncertainty"]["model_risk_why"]
        self.assertIn("Ostap", why)
        self.assertIn("improves past estimates", why)
        self.assertIn("improved 7 of 7", why)


class TestFactorChanges(unittest.TestCase):
    def proposal(self, factor=1.2):
        return {"id": "P2", "coefficient": "size_bands.*", "kind": "factor",
                "current": 1.0, "proposed": factor, "samples": 7, "why": "under-estimating"}

    def test_every_band_is_scaled(self):
        m = model()
        before = dict(m["size_bands"]["M"])
        ap.apply_one(m, self.proposal(), BACKTEST, "Ostap", "2026-09-07")
        for bound in ("lo", "likely", "hi"):
            self.assertAlmostEqual(m["size_bands"]["M"][bound], before[bound] * 1.2, places=3)

    def test_metadata_keys_are_left_alone(self):
        m = model()
        before = m["size_bands"]["_what"]
        ap.apply_one(m, self.proposal(), BACKTEST, "Ostap", "2026-09-07")
        self.assertEqual(m["size_bands"]["_what"], before)

    def test_the_original_reasoning_survives_alongside_the_new(self):
        m = model()
        original = m["size_bands"]["M"]["why"]
        ap.apply_one(m, self.proposal(), BACKTEST, "Ostap", "2026-09-07")
        why = m["size_bands"]["M"]["why"]
        self.assertIn(original.split("—")[0].strip()[:20], why)
        self.assertIn("Scaled by 1.2x", why)

    def test_the_change_record_names_what_moved(self):
        m = model()
        record = ap.apply_one(m, self.proposal(), BACKTEST, "Ostap", "2026-09-07")
        self.assertEqual(record["factor"], 1.2)
        self.assertIn("M", record["entries"])
        self.assertIn("from", record["entries"]["M"])


class TestLogEntry(unittest.TestCase):
    def test_the_log_carries_evidence_backtest_and_reversal(self):
        proposal = {"id": "P2", "coefficient": "size_bands.*", "kind": "factor",
                    "current": 1.0, "proposed": 1.2, "samples": 7,
                    "why": "under-estimating", "evidence": "median +20% across 7 projects"}
        text = ap.log_entry({"coefficient": "size_bands.*", "factor": 1.2}, proposal,
                            BACKTEST, "Ostap", "2026-09-07", ["EST-1", "EST-2"])
        for expected in ("median +20%", "improves past estimates", "EST-1, EST-2",
                         "Ostap", "To reverse this"):
            self.assertIn(expected, text)

    def test_a_weak_signal_is_marked_in_the_log(self):
        proposal = {"id": "P3", "coefficient": "qa", "kind": "factor", "current": 1.0,
                    "proposed": 1.3, "samples": 3, "why": "qa hot", "weak_signal": True}
        self.assertIn("weak signal", ap.log_entry({}, proposal, BACKTEST, "O", "2026-09-07", []))


class TestTheGuaranteeIsEnforcedNotAsserted(unittest.TestCase):
    """The module's one rule is that nothing changes the model without a human deciding it.

    A rule that lives only in prose holds only while the agent is still carrying that prose,
    which compaction or a programmatic caller can end.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.model_path = self.dir / "cost-model.json"
        self.model_path.write_text(json.dumps(model()), encoding="utf-8")
        self.log = self.dir / "calibration-log.md"
        self.analysis = self.dir / "analysis.json"
        self.backtest = self.dir / "backtest.json"
        proposal = {"id": "P1", "coefficient": "size_bands.*", "kind": "factor", "current": 1.0,
                    "proposed": 1.2, "samples": 7, "why": "under-estimating", "evidence": "e"}
        self.analysis.write_text(json.dumps({"proposals": [proposal],
                                             "accuracy": {"entries": [{"id": "E1"}]},
                                             "samples": 7}), encoding="utf-8")
        self.backtest.write_text(json.dumps({"backtests": [dict(BACKTEST, proposal="P1")]}),
                                 encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def run_apply(self, interactive=True, accept="P1", backtest_file=None):
        class FakeStdin:
            def isatty(self):
                return interactive
        argv, stdin = sys.argv, sys.stdin
        sys.argv = ["apply.py", "--analysis", str(self.analysis), "--backtest",
                    str(backtest_file or self.backtest), "--cost-model", str(self.model_path),
                    "--calibration-log", str(self.log), "--accept", accept,
                    "--approved-by", "Ostap"]
        sys.stdin = FakeStdin()
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                code = ap.main()
        finally:
            sys.argv, sys.stdin = argv, stdin
        return code, json.loads(buf.getvalue())

    def test_an_unattended_run_cannot_write_the_model(self):
        code, out = self.run_apply(interactive=False)
        self.assertEqual(code, 1)
        self.assertIn("unattended run", out["error"])
        self.assertEqual(json.loads(self.model_path.read_text())["size_bands"]["M"]["likely"],
                         model()["size_bands"]["M"]["likely"])

    def test_there_is_no_flag_to_override_the_unattended_refusal(self):
        self.assertNotIn("allow-unbacktested", Path(ap.__file__).read_text()
                         if hasattr(ap, "__file__") else "")
        source = (Path(__file__).resolve().parent.parent / "apply.py").read_text()
        self.assertNotIn("allow_unbacktested", source)
        self.assertNotIn("--force", source)

    def test_an_unbacktested_proposal_is_refused_with_no_way_round_it(self):
        empty = self.dir / "empty-backtest.json"
        empty.write_text(json.dumps({"backtests": []}), encoding="utf-8")
        code, out = self.run_apply(backtest_file=empty)
        self.assertEqual(code, 1)
        self.assertIn("no override", out["error"])

    def test_an_interactive_run_with_evidence_does_apply(self):
        code, out = self.run_apply()
        self.assertEqual(code, 0)
        self.assertTrue(out["ok"])
        after = json.loads(self.model_path.read_text())
        self.assertAlmostEqual(after["size_bands"]["M"]["likely"],
                               model()["size_bands"]["M"]["likely"] * 1.2, places=2)
        self.assertIn("Ostap", self.log.read_text())

    def test_the_backup_is_taken_before_anything_changes(self):
        self.run_apply()
        backups = list(self.dir.glob("cost-model.*.bak.json"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(json.loads(backups[0].read_text())["size_bands"]["M"]["likely"],
                         model()["size_bands"]["M"]["likely"])

    def test_a_second_same_day_run_does_not_overwrite_the_first_backup(self):
        """Otherwise the second backup is an already-calibrated model and the rollback path
        stops pointing at the pre-change state."""
        self.run_apply()
        first = list(self.dir.glob("cost-model.*.bak.json"))[0]
        original = json.loads(first.read_text())["size_bands"]["M"]["likely"]
        self.run_apply()
        backups = sorted(self.dir.glob("cost-model.*.bak.json"))
        self.assertEqual(len(backups), 2)
        self.assertEqual(json.loads(first.read_text())["size_bands"]["M"]["likely"], original)

    def test_a_model_change_is_rolled_back_when_the_log_cannot_be_written(self):
        """A changed model with no record of why is the drift this skill exists to prevent."""
        self.log.mkdir()          # a directory where a file must go: the append will fail
        code, out = self.run_apply()
        self.assertEqual(code, 1)
        self.assertIn("rolled back", out["error"])
        self.assertEqual(json.loads(self.model_path.read_text())["size_bands"]["M"]["likely"],
                         model()["size_bands"]["M"]["likely"])


class TestResolve(unittest.TestCase):
    def test_a_dotted_path_reaches_the_container_and_key(self):
        m = model()
        node, key = ap.resolve(m, "uncertainty.model_risk")
        self.assertIs(node, m["uncertainty"])
        self.assertEqual(key, "model_risk")


if __name__ == "__main__":
    unittest.main()
