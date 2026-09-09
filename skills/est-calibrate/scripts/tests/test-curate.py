#!/usr/bin/env python3
"""Tests for curate.py.

The second door into the cost model has to be as hard to misuse as the first. The cases that
matter are the ones where a bad change looks fine: an inverted three-point range that collapses
the band rather than raising, a negative rate, a judgement quietly overwriting a calibrated
value, and a write that leaves no log behind.
"""

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fixtures as fx  # noqa: E402

import importlib.util  # noqa: E402


def _load(name):
    path = Path(__file__).resolve().parent.parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_load("backtest")
cu = _load("curate")


class Args:
    def __init__(self, **kw):
        self.cost_model = kw["cost_model"]
        self.calibration_log = kw["calibration_log"]
        self.set = kw.get("set", ["uncertainty.model_risk=0.10"])
        self.why = kw.get("why", "three delivered projects landed inside a tighter band")
        self.approved_by = kw.get("approved_by", "Ostap, delivery lead")
        self.ledger = kw.get("ledger")
        self.engine = kw.get("engine")
        self.preview = kw.get("preview", False)


def workspace(tmp, model=None):
    path = Path(tmp) / "cost-model.json"
    path.write_text(json.dumps(model or fx.model(), indent=2), encoding="utf-8")
    return Args(cost_model=str(path), calibration_log=str(Path(tmp) / "calibration-log.md"))


def run(args, tty=True):
    with mock.patch.object(sys, "stdin", io.StringIO()) as fake:
        fake.isatty = lambda: tty
        return cu.run(args)


class Parsing(unittest.TestCase):
    def test_a_three_point_value(self):
        self.assertEqual(cu.parse_change("qa.web=0.3/0.42/0.6"),
                         ("qa.web", {"lo": 0.3, "likely": 0.42, "hi": 0.6}))

    def test_a_scalar(self):
        self.assertEqual(cu.parse_change("uncertainty.z=1.28"), ("uncertainty.z", 1.28))

    def test_prose_is_refused(self):
        with self.assertRaises(cu.Refused) as ctx:
            cu.parse_change("uncertainty.z=higher")
        self.assertIn("belongs in --why", str(ctx.exception))

    def test_a_two_point_value_is_refused(self):
        with self.assertRaises(cu.Refused):
            cu.parse_change("qa.web=0.3/0.6")

    def test_a_path_that_does_not_exist_is_refused(self):
        with self.assertRaises(cu.Refused) as ctx:
            cu.resolve(fx.model(), "qa.paranoid")
        self.assertIn("not in the cost model", str(ctx.exception))

    def test_it_never_creates_a_coefficient(self):
        model = fx.model()
        with self.assertRaises(cu.Refused):
            cu.set_one(model, "qa.brand_new", 0.4, "why", "me", "2026-09-07")
        self.assertNotIn("brand_new", model["qa"])


class Sanity(unittest.TestCase):
    def test_an_inverted_range_is_refused(self):
        with self.assertRaises(cu.Refused) as ctx:
            cu.set_one(fx.model(), "qa.web", {"lo": 0.9, "likely": 0.3, "hi": 0.4},
                       "w", "me", "2026-09-07")
        self.assertIn("band collapses silently", str(ctx.exception))

    def test_one_bound_that_inverts_the_row_is_refused(self):
        with self.assertRaises(cu.Refused):
            cu.set_one(fx.model(), "qa.mobile_manual.lo", 0.9, "w", "me", "2026-09-07")

    def test_a_negative_coefficient_is_refused(self):
        with self.assertRaises(cu.Refused) as ctx:
            cu.set_one(fx.model(), "uncertainty.model_risk", -0.1, "w", "me", "2026-09-07")
        self.assertIn("negative hours", str(ctx.exception))

    def test_zero_compression_is_refused(self):
        with self.assertRaises(cu.Refused) as ctx:
            cu.set_one(fx.model(), "compressibility.high", {"lo": 0.0, "likely": 0.0, "hi": 0.0},
                       "w", "me", "2026-09-07")
        self.assertIn("infinite or negative", str(ctx.exception))

    def test_an_ordered_change_is_allowed(self):
        model = fx.model()
        cu.set_one(model, "qa.web", {"lo": 0.3, "likely": 0.45, "hi": 0.7},
                   "w", "me", "2026-09-07")
        self.assertEqual(model["qa"]["web"]["likely"], 0.45)

    def test_a_three_point_range_set_as_a_scalar_is_refused(self):
        with self.assertRaises(cu.Refused) as ctx:
            cu.set_one(fx.model(), "qa.web", 0.4, "w", "me", "2026-09-07")
        self.assertIn("name one bound", str(ctx.exception))


class Provenance(unittest.TestCase):
    def test_the_reason_lands_in_the_coefficients_own_why(self):
        model = fx.model()
        cu.set_one(model, "qa.web", {"lo": 0.3, "likely": 0.45, "hi": 0.7},
                   "money features get read line by line", "Ostap", "2026-09-07")
        why = model["qa"]["web"]["why"]
        self.assertIn("money features get read line by line", why)
        self.assertIn("NOT calibrated", why)

    def test_the_previous_value_is_recoverable_from_the_why_alone(self):
        model = fx.model()
        before = dict(model["uncertainty"])["model_risk"]
        cu.set_one(model, "uncertainty.model_risk", 0.08, "w", "me", "2026-09-07")
        self.assertIn(str(before), model["uncertainty"]["model_risk_why"])

    def test_overriding_a_calibrated_coefficient_warns(self):
        model = fx.model()
        model["qa"]["web"]["why"] = "Calibrated 2026-08-01 from 6 delivered projects."
        self.assertIn("replaces evidence with an opinion",
                      cu.overrides_evidence(model, "qa.web"))

    def test_an_uncalibrated_coefficient_does_not_warn(self):
        self.assertIsNone(cu.overrides_evidence(fx.model(), "qa.web"))


class Gates(unittest.TestCase):
    def test_an_unattended_run_refuses_to_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = workspace(tmp)
            with self.assertRaises(cu.Refused) as ctx:
                run(args, tty=False)
            self.assertIn("needs that person present", str(ctx.exception))
            self.assertFalse(Path(args.calibration_log).exists())

    def test_preview_works_unattended_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = workspace(tmp)
            args.preview = True
            before = Path(args.cost_model).read_text()
            result = run(args, tty=False)
            self.assertTrue(result["preview"])
            self.assertEqual(Path(args.cost_model).read_text(), before)
            self.assertFalse(Path(args.calibration_log).exists())

    def test_an_empty_why_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = workspace(tmp)
            args.why = "   "
            with self.assertRaises(cu.Refused) as ctx:
                run(args)
            self.assertIn("needs --why", str(ctx.exception))

    def test_applying_without_a_named_human_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = workspace(tmp)
            args.approved_by = ""
            with self.assertRaises(cu.Refused) as ctx:
                run(args)
            self.assertIn("--approved-by", str(ctx.exception))


class Writing(unittest.TestCase):
    def test_the_model_is_backed_up_before_it_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = workspace(tmp)
            original = json.loads(Path(args.cost_model).read_text())
            result = run(args)
            backup = json.loads(Path(result["backup"]).read_text())
            self.assertEqual(backup["uncertainty"]["model_risk"],
                             original["uncertainty"]["model_risk"])
            self.assertEqual(json.loads(Path(args.cost_model).read_text())
                             ["uncertainty"]["model_risk"], 0.10)

    def test_a_second_change_on_the_same_day_gets_its_own_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = workspace(tmp)
            first = run(args)["backup"]
            args.set = ["uncertainty.model_risk=0.12"]
            second = run(args)["backup"]
            self.assertNotEqual(first, second)
            self.assertEqual(json.loads(Path(first).read_text())["uncertainty"]["model_risk"], 0.15)

    def test_the_log_records_the_reversal_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = workspace(tmp)
            run(args)
            log = Path(args.calibration_log).read_text()
            self.assertIn("(judgement)", log)
            self.assertIn("To reverse this", log)
            self.assertIn("0.15", log)

    def test_history_records_the_change_as_judgement_not_calibration(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = workspace(tmp)
            run(args)
            history = json.loads(Path(args.cost_model).read_text())["calibration_history"]
            self.assertEqual(history[-1]["kind"], "judgement")

    def test_an_unwritable_log_rolls_the_model_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = workspace(tmp)
            args.calibration_log = str(Path(tmp) / "nope" / "calibration-log.md")
            before = Path(args.cost_model).read_text()
            with self.assertRaises(cu.Refused) as ctx:
                run(args)
            self.assertIn("rolled back", str(ctx.exception))
            self.assertEqual(Path(args.cost_model).read_text(), before)


class Impact(unittest.TestCase):
    def entry(self, tmp, status="sent", actuals=None):
        d = Path(tmp) / "ledger"
        d.mkdir(exist_ok=True)
        est = fx.entry(features=[fx.feature("F1", tier="sensitive"), fx.feature("F2")])
        est["ledger"] = {"id": "EST-20260101-x", "status": status, "actuals": actuals}
        (d / "EST-20260101-x.json").write_text(json.dumps(est), encoding="utf-8")
        return str(d)

    def test_no_ledger_says_the_effect_is_unknown(self):
        report = cu.impact(fx.model(), fx.model(), None)
        self.assertEqual(report["entries"], 0)
        self.assertIn("unknown", report["note"])

    def test_a_review_rate_change_moves_past_estimates(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = self.entry(tmp)
            after = fx.model()
            for bound in ("lo", "likely", "hi"):
                after["qa"]["web"][bound] *= 2
            report = cu.impact(fx.model(), after, ledger)
            self.assertEqual(report["entries"], 1)
            self.assertGreater(report["largest_move_pct"], 0)
            self.assertEqual(report["sent_or_won_affected"], ["EST-20260101-x"])

    def test_an_unchanged_model_moves_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = cu.impact(fx.model(), fx.model(), self.entry(tmp))
            self.assertEqual(report["largest_move_pct"], 0.0)
            self.assertEqual(report["sent_or_won_affected"], [])

    def test_actuals_say_whether_the_opinion_helps(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = self.entry(tmp, status="delivered", actuals={"delivery_hours": 1_000_000})
            after = fx.model()
            for bound in ("lo", "likely", "hi"):
                after["qa"]["web"][bound] *= 2
            report = cu.impact(fx.model(), after, ledger)
            self.assertEqual(report["against_actuals"]["compared"], 1)
            self.assertEqual(report["against_actuals"]["closer"], 1)

    def test_a_corrupt_ledger_entry_does_not_stop_the_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = self.entry(tmp)
            (Path(ledger) / "EST-20260202-bad.json").write_text("{", encoding="utf-8")
            self.assertEqual(cu.impact(fx.model(), fx.model(), ledger)["entries"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=1)
