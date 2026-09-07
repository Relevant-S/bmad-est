#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Tests for inventory-check.py — validation rules and the completeness score."""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fixtures import feature, inventory, signals, tag  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "inventory_check", Path(__file__).resolve().parent.parent / "inventory-check.py"
)
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)

SCHEMA = __import__("json").loads(check.SCHEMA_PATH.read_text(encoding="utf-8"))


def findings_for(inv):
    return check.validate_schema(inv, SCHEMA, SCHEMA) + check.check_integrity(inv)


class TestValidation(unittest.TestCase):
    def test_valid_inventory_has_no_findings(self):
        self.assertEqual(findings_for(inventory()), [])

    def test_missing_required_top_level_field(self):
        inv = inventory()
        del inv["not_scope"]
        self.assertTrue(any("not_scope" in f and "missing" in f for f in findings_for(inv)))

    def test_feature_without_citation_is_caught(self):
        inv = inventory(features=[feature(citations=[])])
        self.assertTrue(any("citations" in f and "at least 1" in f for f in findings_for(inv)))

    def test_citation_to_unknown_source_names_the_known_ids(self):
        f = feature()
        f["citations"][0]["source_id"] = "S9"
        found = findings_for(inventory(features=[f]))
        self.assertTrue(any("S9" in x and "S1" in x for x in found))

    def test_empty_tag_justification_is_caught(self):
        f = feature()
        f["tags"]["size_band"]["why"] = "   "
        self.assertTrue(any("why" in x and "black-box" in x for x in findings_for(inventory(features=[f]))))

    def test_tag_outside_vocabulary_is_caught(self):
        f = feature()
        f["tags"]["review_tier"]["value"] = "scary"
        self.assertTrue(any("scary" in x for x in findings_for(inventory(features=[f]))))

    def test_dangling_dependency_is_caught(self):
        f = feature(depends_on=[{"feature_id": "F99", "inferred": True}])
        self.assertTrue(any("F99" in x for x in findings_for(inventory(features=[f]))))

    def test_self_dependency_is_caught(self):
        f = feature(depends_on=[{"feature_id": "F1", "inferred": True}])
        self.assertTrue(any("depends on itself" in x for x in findings_for(inventory(features=[f]))))

    def test_stated_dependency_without_evidence_is_caught(self):
        a = feature("F1", "Login")
        b = feature("F2", "Profile", depends_on=[{"feature_id": "F1", "inferred": False}])
        self.assertTrue(any("evidence" in x for x in findings_for(inventory(features=[a, b]))))

    def test_dependency_cycle_is_detected(self):
        a = feature("F1", "A", depends_on=[{"feature_id": "F2", "inferred": True}])
        b = feature("F2", "B", depends_on=[{"feature_id": "F1", "inferred": True}])
        self.assertTrue(any("dependency cycle" in x for x in findings_for(inventory(features=[a, b]))))

    def test_acyclic_chain_is_not_reported_as_a_cycle(self):
        a = feature("F1", "A")
        b = feature("F2", "B", depends_on=[{"feature_id": "F1", "inferred": True}])
        c = feature("F3", "C", depends_on=[{"feature_id": "F2", "inferred": True}])
        self.assertEqual([x for x in findings_for(inventory(features=[a, b, c])) if "cycle" in x], [])

    def test_duplicate_feature_ids_are_caught(self):
        inv = inventory(features=[feature("F1", "A"), feature("F1", "B")])
        self.assertTrue(any("duplicate feature id" in x for x in findings_for(inv)))

    def test_foreign_language_source_requires_original_quote(self):
        inv = inventory()
        inv["sources"][0]["language"] = "uk"
        found = findings_for(inv)
        self.assertTrue(any("quote_original" in x for x in found))

    def test_foreign_language_source_passes_with_original_quote(self):
        inv = inventory()
        inv["sources"][0]["language"] = "uk"
        inv["features"][0]["citations"][0]["quote_original"] = "Користувачі повинні входити в систему."
        self.assertEqual([x for x in findings_for(inv) if "quote_original" in x], [])


class TestCitationVerification(unittest.TestCase):
    """Silent invention is a substring search, not a judgement call."""

    SOURCE_TEXT = (
        "<!-- source: docs/sow.docx | converter: python-docx -->\n\n"
        "## 2. Scope\n\n"
        "Users must be able to log in with an email and password.\n"
        "The supplier shall provide localisation into Polish.\n"
    )

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "S1-sow.md").write_text(self.SOURCE_TEXT, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def verify(self, inv):
        return check.verify_citations(inv, self.dir)

    def test_verbatim_quote_passes(self):
        self.assertEqual(self.verify(inventory()), [])

    def test_quote_differing_only_in_whitespace_and_case_passes(self):
        f = feature()
        f["citations"][0]["quote"] = "users must be able to log in   with an email and password."
        self.assertEqual(self.verify(inventory(features=[f])), [])

    def test_invented_quote_is_reported_as_possibly_invented(self):
        f = feature()
        f["citations"][0]["quote"] = "The system shall support biometric retina scanning at every depot."
        found = self.verify(inventory(features=[f]))
        self.assertEqual(len(found), 1)
        self.assertIn("may be invented scope", found[0])

    def test_paraphrase_is_distinguished_from_invention(self):
        f = feature()
        f["citations"][0]["quote"] = "Users must be able to log in with an email and a password."
        found = self.verify(inventory(features=[f]))
        self.assertEqual(len(found), 1)
        self.assertIn("paraphrased", found[0])

    def test_foreign_source_is_verified_against_the_original_not_the_translation(self):
        (self.dir / "S1-sow.md").write_text(
            "Користувачі повинні входити в систему.", encoding="utf-8")
        inv = inventory()
        inv["sources"][0]["language"] = "uk"
        inv["features"][0]["citations"][0]["quote"] = "Users must be able to log in."
        inv["features"][0]["citations"][0]["quote_original"] = "Користувачі повинні входити в систему."
        self.assertEqual(self.verify(inv), [])

    def test_missing_normalized_file_is_reported_as_unverifiable(self):
        inv = inventory()
        inv["sources"][0]["id"] = "S7"
        inv["features"][0]["citations"][0]["source_id"] = "S7"
        found = self.verify(inv)
        self.assertTrue(any("could not be verified" in x for x in found))

    def test_verification_is_off_unless_normalized_is_supplied(self):
        f = feature()
        f["citations"][0]["quote"] = "Something nobody ever wrote."
        self.assertEqual(findings_for(inventory(features=[f])), [])


class TestAgreedScope(unittest.TestCase):
    """Once a contract is among the sources, it defines the agreed scope."""

    def with_sow_and_transcript(self, extra_feature):
        inv = inventory(features=[feature(), extra_feature])
        inv["sources"].append({"id": "S2", "path": "call.md", "doc_type": "transcript", "language": "en"})
        return inv

    def only_transcript_feature(self, **overrides):
        f = feature("F2", "Dispatcher workflow replacement", **overrides)
        f["citations"] = [{"source_id": "S2", "location": "[00:02:11]",
                           "quote": "The core problem is our dispatchers copying job data every Monday."}]
        return f

    def test_feature_absent_from_the_contract_without_scope_status_is_flagged(self):
        inv = self.with_sow_and_transcript(self.only_transcript_feature())
        found = findings_for(inv)
        self.assertTrue(any("not traceable to the agreed scope" in x and "F2" in x for x in found))

    def test_flag_names_the_contractual_source_and_the_remedy(self):
        inv = self.with_sow_and_transcript(self.only_transcript_feature())
        finding = next(x for x in findings_for(inv) if "not traceable" in x)
        self.assertIn("S1", finding)
        self.assertIn("outside_agreed_scope", finding)

    def test_explicit_scope_status_clears_the_finding(self):
        inv = self.with_sow_and_transcript(
            self.only_transcript_feature(scope_status="outside_agreed_scope"))
        self.assertEqual([x for x in findings_for(inv) if "not traceable" in x], [])

    def test_no_contractual_source_means_no_such_finding(self):
        inv = inventory(features=[feature()])
        inv["sources"] = [{"id": "S1", "path": "call.md", "doc_type": "transcript", "language": "en"}]
        self.assertEqual([x for x in findings_for(inv) if "not traceable" in x], [])

    def test_invalid_scope_status_is_rejected(self):
        inv = self.with_sow_and_transcript(self.only_transcript_feature(scope_status="maybe"))
        self.assertTrue(any("maybe" in x for x in findings_for(inv)))

    def test_coverage_lists_features_outside_the_agreed_scope(self):
        inv = self.with_sow_and_transcript(
            self.only_transcript_feature(scope_status="outside_agreed_scope"))
        self.assertEqual(check.coverage(inv)["outside_agreed_scope"], ["F2"])


class TestScoring(unittest.TestCase):
    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(check.SIGNAL_WEIGHTS.values()), 1.0, places=9)

    def test_richest_possible_input_scores_one(self):
        inv = inventory(
            features=[feature(tags={**feature()["tags"], "clarity": tag("high")}, commitment="committed")],
            completeness_signals=signals(
                acceptance_criteria="most", stack_specified="full",
                integrations_named="all", nfrs_stated="most",
                data_model_described="detailed", ui_defined="designed"),
        )
        self.assertAlmostEqual(check.score(inv)["input_completeness"], 1.0, places=3)

    def test_thinnest_possible_input_scores_zero(self):
        inv = inventory(
            features=[feature(tags={**feature()["tags"], "clarity": tag("low")}, commitment="speculative")],
            completeness_signals=signals(
                acceptance_criteria="none", stack_specified="none",
                integrations_named="none", nfrs_stated="none",
                data_model_described="none", ui_defined="none"),
        )
        # commitment 'speculative' still contributes 0.1 of its 0.08 weight
        self.assertLess(check.score(inv)["input_completeness"], 0.02)

    def test_thin_transcript_scores_below_rich_spec(self):
        thin = inventory(
            features=[feature(tags={**feature()["tags"], "clarity": tag("low")}, commitment="speculative")],
            completeness_signals=signals(
                acceptance_criteria="none", stack_specified="none",
                integrations_named="none", nfrs_stated="none",
                data_model_described="none", ui_defined="none"),
        )
        rich = inventory(
            features=[feature(tags={**feature()["tags"], "clarity": tag("high")})],
            completeness_signals=signals(
                acceptance_criteria="most", stack_specified="full",
                integrations_named="all", nfrs_stated="most",
                data_model_described="detailed", ui_defined="designed"),
        )
        self.assertLess(check.score(thin)["input_completeness"], check.score(rich)["input_completeness"])

    def test_score_is_reproducible(self):
        inv = inventory()
        self.assertEqual(check.score(inv)["input_completeness"], check.score(inv)["input_completeness"])


class TestAnchorsAndCoverage(unittest.TestCase):
    """Anchors are only useful if something checks that a citation lands on one."""

    WORKBOOK = ("## sheet: Backlog\n\n| row | A | B |\n| --- | --- | --- |\n"
                "| 1 | Feature | Priority |\n| 4 | Login | Must |\n| 5 | Export | Should |\n")
    PDF = "<!-- page 1 -->\n\nFirst page.\n\n<!-- page 2 -->\n\nSecond page.\n"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def workbook_inventory(self, location):
        (self.dir / "S1-book.md").write_text(self.WORKBOOK, encoding="utf-8")
        f = feature()
        f["citations"] = [{"source_id": "S1", "location": location, "quote": "Login"}]
        inv = inventory(features=[f], not_scope=[])
        inv["sources"][0]["doc_type"] = "backlog"
        return inv

    def test_citation_to_a_real_row_resolves(self):
        self.assertEqual(check.check_anchors(self.workbook_inventory("sheet 'Backlog' row 4"), self.dir), [])

    def test_citation_to_a_row_the_sheet_does_not_have_is_caught(self):
        found = check.check_anchors(self.workbook_inventory("sheet 'Backlog' row 99"), self.dir)
        self.assertTrue(any("no row 99" in x for x in found))

    def test_citation_to_a_sheet_that_does_not_exist_is_caught(self):
        found = check.check_anchors(self.workbook_inventory("sheet 'Nowhere' row 4"), self.dir)
        self.assertTrue(any("Nowhere" in x for x in found))

    def test_page_beyond_the_end_of_the_document_is_caught(self):
        (self.dir / "S1-doc.md").write_text(self.PDF, encoding="utf-8")
        f = feature()
        f["citations"] = [{"source_id": "S1", "location": "page 7", "quote": "First page."}]
        found = check.check_anchors(inventory(features=[f], not_scope=[]), self.dir)
        self.assertTrue(any("page 7" in x and "2 pages" in x for x in found))

    def test_unstructured_location_is_not_second_guessed(self):
        (self.dir / "S1-sow.md").write_text("## 3. Scope\n\nSupplier shall deliver.", encoding="utf-8")
        f = feature()
        f["citations"] = [{"source_id": "S1", "location": "§3.1", "quote": "Supplier shall deliver."}]
        self.assertEqual(check.check_anchors(inventory(features=[f], not_scope=[]), self.dir), [])

    def test_unreferenced_workbook_rows_are_listed_for_the_coverage_pass(self):
        inv = self.workbook_inventory("sheet 'Backlog' row 4")
        regions = check.coverage_regions(inv, self.dir)
        rows = [r for region in regions for r in region.get("rows", [])]
        self.assertIn(5, rows)      # Export was never cited
        self.assertNotIn(4, rows)   # Login was

    def test_staleness_reports_sources_newer_than_the_inventory(self):
        import os
        import time

        inv_path = self.dir / "feature-inventory.json"
        inv_path.write_text("{}", encoding="utf-8")
        source = self.dir / "S1-book.md"
        source.write_text(self.WORKBOOK, encoding="utf-8")
        os.utime(source, (time.time() + 60, time.time() + 60))
        stale = check.check_staleness(inventory(), inv_path, self.dir)
        self.assertIn("S1-book.md", stale["newer_sources"])

    def test_staleness_reports_a_source_path_that_no_longer_exists(self):
        inv_path = self.dir / "feature-inventory.json"
        inv_path.write_text("{}", encoding="utf-8")
        inv = inventory()
        inv["sources"][0]["path"] = str(self.dir / "deleted.docx")
        stale = check.check_staleness(inv, inv_path, self.dir)
        self.assertEqual(len(stale["missing_source_paths"]), 1)


class TestManifestReconciliation(unittest.TestCase):
    """A converted source the inventory never lists is silent omission at document level."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "manifest.json"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, sources):
        self.path.write_text(json.dumps({"sources": sources}), encoding="utf-8")
        return self.path

    def test_converted_source_missing_from_the_inventory_is_caught(self):
        manifest = self.write([{"id": "S1", "path": "docs/sow.docx"},
                               {"id": "S2", "path": "call.md", "needs_native_read": False}])
        found = check.reconcile_manifest(inventory(), manifest)
        self.assertTrue(any("S2" in x and "was converted" in x for x in found))

    def test_unreadable_source_missing_from_the_inventory_is_still_caught(self):
        manifest = self.write([{"id": "S1", "path": "docs/sow.docx"},
                               {"id": "S9", "path": "scan.pdf", "needs_native_read": True}])
        found = check.reconcile_manifest(inventory(), manifest)
        self.assertTrue(any("S9" in x and "could not be converted" in x for x in found))

    def test_unreadable_source_without_a_coverage_note_is_caught(self):
        manifest = self.write([{"id": "S1", "path": "docs/sow.docx", "needs_native_read": True}])
        found = check.reconcile_manifest(inventory(), manifest)
        self.assertTrue(any("coverage_note" in x for x in found))

    def test_unreadable_source_with_a_coverage_note_passes(self):
        inv = inventory()
        inv["sources"][0]["coverage_note"] = "scanned; read directly with native PDF reading"
        manifest = self.write([{"id": "S1", "path": "docs/sow.docx", "needs_native_read": True}])
        self.assertEqual(check.reconcile_manifest(inv, manifest), [])

    def test_a_different_file_behind_the_same_source_id_is_caught(self):
        manifest = self.write([{"id": "S1", "path": "docs/other-sow.docx"}])
        found = check.reconcile_manifest(inventory(), manifest)
        self.assertTrue(any("different file" in x for x in found))

    def test_the_same_file_written_as_a_different_path_is_not_flagged(self):
        manifest = self.write([{"id": "S1", "path": "/abs/elsewhere/sow.docx"}])
        self.assertEqual(check.reconcile_manifest(inventory(), manifest), [])

    def test_matching_manifest_and_inventory_produce_nothing(self):
        self.assertEqual(check.reconcile_manifest(inventory(), self.write([{"id": "S1", "path": "docs/sow.docx"}])), [])

    def test_inventory_source_absent_from_the_manifest_is_caught(self):
        inv = inventory()
        inv["sources"].append({"id": "S4", "path": "ghost.md", "doc_type": "brief", "language": "en"})
        found = check.reconcile_manifest(inv, self.write([{"id": "S1", "path": "docs/sow.docx"}]))
        self.assertTrue(any("S4" in x for x in found))


class TestSignalIntegrity(unittest.TestCase):
    """The score's weights are fixed; its inputs are judgement, so they must be interrogable."""

    def test_signal_without_a_reason_is_caught(self):
        inv = inventory()
        inv["completeness_signals"]["nfrs_stated"]["why"] = "  "
        self.assertTrue(any("completeness_signals.nfrs_stated" in x and "why" in x
                            for x in findings_for(inv)))

    def test_bare_string_signal_is_rejected(self):
        inv = inventory()
        inv["completeness_signals"]["ui_defined"] = "described"
        self.assertTrue(any("expected an object" in x for x in findings_for(inv)))

    def test_value_from_another_signals_vocabulary_is_caught(self):
        inv = inventory()
        # 'detailed' is valid for data_model_described but not for acceptance_criteria
        inv["completeness_signals"]["acceptance_criteria"]["value"] = "detailed"
        self.assertTrue(any("acceptance_criteria" in x and "detailed" in x
                            for x in findings_for(inv)))

    def test_unmapped_value_is_a_finding_not_a_silent_zero(self):
        inv = inventory()
        inv["completeness_signals"]["stack_specified"]["value"] = "mostly"
        self.assertTrue(any("stack_specified" in x and "mostly" in x for x in findings_for(inv)))


class TestCoverage(unittest.TestCase):
    def test_counts_review_tiers(self):
        a = feature("F1", "Login")
        b = feature("F2", "Marketing page", tags={**feature()["tags"], "review_tier": tag("routine")})
        cov = check.coverage(inventory(features=[a, b]))
        self.assertEqual(cov["review_tiers"]["sensitive"], 1)
        self.assertEqual(cov["review_tiers"]["routine"], 1)

    def test_source_contributing_nothing_is_surfaced(self):
        inv = inventory()
        inv["sources"].append({"id": "S2", "path": "docs/nda.pdf", "doc_type": "other", "language": "en"})
        self.assertEqual(check.coverage(inv)["sources_contributing_nothing"], ["S2"])

    def test_source_appearing_only_in_not_scope_is_not_flagged(self):
        inv = inventory()
        inv["sources"].append({"id": "S2", "path": "docs/nda.pdf", "doc_type": "other", "language": "en"})
        inv["not_scope"].append({"source_id": "S2", "location": "whole document",
                                 "quote": "Mutual non-disclosure agreement.", "reason": "legal, not scope"})
        self.assertEqual(check.coverage(inv)["sources_contributing_nothing"], [])

    def test_lists_the_ids_the_confirmation_batch_needs(self):
        a = feature("F1", "Login")                                    # sensitive by fixture default
        b = feature("F2", "Marketing page", tags={**feature()["tags"], "review_tier": tag("routine")},
                    depends_on=[{"feature_id": "F1", "inferred": True}])
        cov = check.coverage(inventory(features=[a, b]))
        self.assertEqual(cov["sensitive_or_critical"], ["F1"])
        self.assertEqual(cov["inferred_dependency_pairs"], [{"feature": "F2", "depends_on": "F1"}])

    def test_counts_inferred_dependencies(self):
        a = feature("F1", "Login")
        b = feature("F2", "Profile", depends_on=[{"feature_id": "F1", "inferred": True}])
        self.assertEqual(check.coverage(inventory(features=[a, b]))["inferred_dependencies"], 1)


if __name__ == "__main__":
    unittest.main()
