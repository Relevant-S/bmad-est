#!/usr/bin/env python3
"""Tests for portfolio.py.

Triage is only as good as its staleness detection, and staleness is where a plausible answer
is most likely to be wrong: a fresh clone rewrites every mtime, a recorded timestamp beats a
file's, and an estimate that is genuinely behind its scope must not read as current.
"""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

import importlib.util

import fixtures as fx


def _portfolio():
    path = Path(__file__).resolve().parent.parent / "portfolio.py"
    spec = importlib.util.spec_from_file_location("portfolio", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pf = _portfolio()


class Workspace:
    """A real estimate folder on disk, built the way the workflows build one."""

    def __init__(self, root, slug="acme", project="Acme Portal"):
        self.dir = Path(root) / slug
        self.dir.mkdir(parents=True)
        self.project = project

    def write(self, name, payload, when=None):
        target = self.dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        if when:
            os.utime(target, (when, when))
        return target

    def inventory(self, features=None, generated=None, when=None):
        inv = {"schema_version": "1.0", "project": self.project, "granularity": "project",
               "generated": generated, "features": features or [fx.feature("F1")],
               "sources": [], "not_scope": []}
        return self.write("feature-inventory.json", inv, when)

    def estimate(self, generated=None, when=None, **kw):
        est = fx.estimate(**kw)
        est["project"] = self.project
        est["generated"] = generated
        return self.write("estimate.json", est, when)

    def check(self, completeness=0.62, findings=()):
        return self.write("check.json", {"scoring": {"input_completeness": completeness},
                                         "findings": list(findings)})

    def manifest(self, converted, when=None):
        paths = []
        for name in converted:
            source = self.dir / "normalized" / name
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("# converted", encoding="utf-8")
            if when:
                os.utime(source, (when, when))
            paths.append({"id": "S1", "converted_path": str(source)})
        return self.write("normalized/manifest.json", {"sources": paths})


def ledger_entry(tmp, project="Acme Portal", status="draft", actuals=None, eid="EST-20260101-acme"):
    d = Path(tmp) / "ledger"
    d.mkdir(exist_ok=True)
    payload = {"project": project, "total_hours": {"likely": 400.0}, "generated": "2026-01-01",
               "ledger": {"id": eid, "status": status, "recorded": "2026-01-01", "actuals": actuals}}
    (d / f"{eid}.json").write_text(json.dumps(payload), encoding="utf-8")
    return str(d)


def scan(estimates, ledger=None):
    entries = pf.read_ledger(ledger)
    out = []
    for folder in sorted(p for p in Path(estimates).iterdir() if p.is_dir()):
        if not pf.is_workspace(folder):
            continue
        row, _, _ = pf.read_workspace(folder)
        mine = [e for e in entries if e["project"] == row["project"]]
        row["next_action"] = pf.next_action(row, mine)
        row["attention"] = pf.attention(row, mine)
        out.append(row)
    return out


class Staleness(unittest.TestCase):
    def test_an_inventory_newer_than_its_estimate_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(tmp)
            ws.estimate(generated="2026-03-01T09:00:00Z")
            ws.inventory(generated="2026-04-01T09:00:00Z")
            row = scan(tmp)[0]
            self.assertEqual(row["next_action"], "re-estimate: scope changed")
            self.assertIn("behind the scope", row["signals"][0]["detail"])

    def test_recorded_timestamps_beat_file_mtimes(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(tmp)
            # The inventory's file is newer, but its recorded stamp is older: a checkout, not a change.
            ws.estimate(generated="2026-04-01T09:00:00Z", when=time.time() - 500)
            ws.inventory(generated="2026-03-01T09:00:00Z", when=time.time())
            row = scan(tmp)[0]
            self.assertEqual(row["signals"], [])
            self.assertEqual(row["next_action"], "record in ledger")

    def test_mtimes_are_the_fallback_when_stamps_are_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(tmp)
            ws.estimate(generated=None, when=time.time() - 500)
            ws.inventory(generated=None, when=time.time())
            self.assertEqual(scan(tmp)[0]["next_action"], "re-estimate: scope changed")

    def test_a_converted_source_newer_than_the_inventory_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(tmp)
            ws.inventory(when=time.time() - 500)
            ws.estimate(when=time.time() - 400)
            ws.manifest(["S1-sow.md"], when=time.time())
            row = scan(tmp)[0]
            self.assertEqual(row["next_action"], "re-extract: sources changed")

    def test_equal_timestamps_are_not_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(tmp)
            stamp = "2026-04-01T09:00:00Z"
            ws.estimate(generated=stamp)
            ws.inventory(generated=stamp)
            self.assertEqual(scan(tmp)[0]["signals"], [])


class NextAction(unittest.TestCase):
    def test_a_folder_of_raw_documents_needs_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(tmp)
            (ws.dir / "client-sow.docx").write_bytes(b"raw")
            self.assertEqual(scan(tmp)[0]["next_action"], "extract")

    def test_an_inventory_without_an_estimate_needs_estimating(self):
        with tempfile.TemporaryDirectory() as tmp:
            Workspace(tmp).inventory()
            self.assertEqual(scan(tmp)[0]["next_action"], "estimate")

    def test_check_findings_outrank_everything_else(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(tmp)
            ws.inventory(generated="2026-04-01T09:00:00Z")
            ws.estimate(generated="2026-03-01T09:00:00Z")
            ws.check(findings=["F1 quote not found in source"])
            self.assertEqual(scan(tmp)[0]["next_action"], "fix inventory findings")

    def test_a_won_project_without_actuals_needs_them_captured(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(tmp)
            ws.inventory(); ws.estimate(); ws.check()
            row = scan(tmp, ledger_entry(tmp, status="won"))[0]
            self.assertEqual(row["next_action"], "capture actuals")
            self.assertTrue(any(a["kind"] == "awaiting_actuals" for a in row["attention"]))

    def test_a_won_project_with_actuals_is_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(tmp)
            ws.inventory(); ws.estimate(); ws.check()
            ledger = ledger_entry(tmp, status="won", actuals={"delivery_hours": 380})
            row = scan(tmp, ledger)[0]
            self.assertEqual(row["next_action"], "current")
            self.assertEqual(row["attention"], [])

    def test_an_estimate_with_no_ledger_entry_should_be_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(tmp)
            ws.inventory(); ws.estimate(); ws.check()
            self.assertEqual(scan(tmp)[0]["next_action"], "record in ledger")

    def test_a_quick_estimate_is_not_asked_to_be_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(tmp)
            ws.inventory(); ws.estimate(mode="quick"); ws.check()
            self.assertEqual(scan(tmp)[0]["next_action"], "current")


class Attention(unittest.TestCase):
    def test_a_thin_input_is_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(tmp)
            ws.inventory(); ws.estimate(completeness=0.18); ws.check(completeness=0.18)
            kinds = [a["kind"] for a in scan(tmp)[0]["attention"]]
            self.assertIn("thin_input", kinds)

    def test_a_healthy_input_is_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(tmp)
            ws.inventory(); ws.estimate(completeness=0.8); ws.check(completeness=0.8)
            kinds = [a["kind"] for a in scan(tmp)[0]["attention"]]
            self.assertNotIn("thin_input", kinds)

    def test_a_risk_heavy_project_is_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(tmp)
            ws.inventory()
            ws.estimate(features=[fx.feature("F1", size="XL", compressibility="low",
                                             review_tier="critical"),
                                  fx.feature("F2", size="XS")])
            ws.check()
            kinds = [a["kind"] for a in scan(tmp)[0]["attention"]]
            self.assertIn("risk_quadrant", kinds)

    def test_band_width_is_reported_as_a_share_of_the_number(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(tmp)
            ws.inventory(); ws.estimate(completeness=0.2); ws.check(completeness=0.2)
            row = scan(tmp)[0]
            self.assertGreater(row["band_width_pct"], 0)


class Ledger(unittest.TestCase):
    def test_entries_are_read_from_the_files_not_the_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = ledger_entry(tmp, status="sent")
            (Path(path) / "index.json").write_text(json.dumps({"entries": []}), encoding="utf-8")
            entries = pf.read_ledger(path)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["status"], "sent")

    def test_a_missing_ledger_is_not_an_error(self):
        self.assertEqual(pf.read_ledger(None), [])
        self.assertEqual(pf.read_ledger("/nowhere/at/all"), [])

    def test_a_corrupt_entry_is_skipped_rather_than_failing_the_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = ledger_entry(tmp)
            (Path(path) / "EST-20260202-broken.json").write_text("{not json", encoding="utf-8")
            self.assertEqual(len(pf.read_ledger(path)), 1)


class WorkspaceDetection(unittest.TestCase):
    """A folder that is not an estimate workspace must not become a phantom project.

    est-calibrate used to write its runs into the estimates folder, and every activation after
    the first calibration reported a project called `calibration` that needed scope extraction.
    """

    def test_a_calibration_run_folder_is_not_a_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            cal = Path(tmp) / "calibration" / "2026-09-07"
            cal.mkdir(parents=True)
            (cal / "analysis.json").write_text("{}", encoding="utf-8")
            self.assertFalse(pf.is_workspace(Path(tmp) / "calibration"))

    def test_an_empty_folder_is_not_a_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "empty").mkdir()
            self.assertFalse(pf.is_workspace(Path(tmp) / "empty"))

    def test_a_folder_of_dated_subdirectories_is_not_a_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "junk" / "2026-09-07").mkdir(parents=True)
            Workspace(tmp).inventory()
            rows = [p for p in sorted(Path(tmp).iterdir()) if p.is_dir()]
            kept = [p for p in rows if pf.is_workspace(p)]
            dropped = [p for p in rows if not pf.is_workspace(p)]
            self.assertEqual([p.name for p in kept], ["acme"])
            self.assertEqual([p.name for p in dropped], ["junk"])

    def test_a_workspace_mid_extraction_still_counts(self):
        """Converted sources but no inventory yet — `extract` is the right answer, not a skip."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(tmp)
            ws.manifest(["S1-sow.md"])
            self.assertTrue(pf.is_workspace(ws.dir))
            self.assertEqual(scan(tmp)[0]["next_action"], "extract")

    def test_an_estimate_without_an_inventory_still_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            ws = Workspace(tmp)
            ws.estimate()
            self.assertTrue(pf.is_workspace(ws.dir))


class Ordering(unittest.TestCase):
    def test_urgency_list_covers_every_action_the_code_can_return(self):
        with tempfile.TemporaryDirectory() as tmp:
            produced = set()
            for slug, build in [
                ("a", lambda w: None),
                ("b", lambda w: w.inventory()),
                ("c", lambda w: (w.inventory(), w.estimate(), w.check())),
            ]:
                ws = Workspace(Path(tmp), slug, project=slug)
                build(ws)
            for row in scan(tmp):
                produced.add(row["next_action"])
            self.assertTrue(produced <= set(pf.ACTION_URGENCY), produced)


if __name__ == "__main__":
    unittest.main(verbosity=1)
