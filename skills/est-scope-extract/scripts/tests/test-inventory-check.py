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
        self.assertAlmostEqual(check.score(inv, classified=True)["input_completeness"], 1.0, places=3)

    def test_thinnest_possible_input_scores_zero(self):
        inv = inventory(
            features=[feature(tags={**feature()["tags"], "clarity": tag("low")}, commitment="speculative")],
            completeness_signals=signals(
                acceptance_criteria="none", stack_specified="none",
                integrations_named="none", nfrs_stated="none",
                data_model_described="none", ui_defined="none"),
        )
        # commitment 'speculative' still contributes 0.1 of its 0.08 weight
        self.assertLess(check.score(inv, classified=True)["input_completeness"], 0.02)

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
        self.assertLess(check.score(thin, classified=True)["input_completeness"], check.score(rich, classified=True)["input_completeness"])

    def test_score_is_reproducible(self):
        inv = inventory()
        self.assertEqual(check.score(inv, classified=True)["input_completeness"], check.score(inv, classified=True)["input_completeness"])


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
        cov = check.coverage(inventory(features=[a, b]), classified=True)
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
        cov = check.coverage(inventory(features=[a, b]), classified=True)
        self.assertEqual(cov["sensitive_or_critical"], ["F1"])
        self.assertEqual(cov["inferred_dependency_pairs"], [{"feature": "F2", "depends_on": "F1"}])

    def test_counts_inferred_dependencies(self):
        a = feature("F1", "Login")
        b = feature("F2", "Profile", depends_on=[{"feature_id": "F1", "inferred": True}])
        self.assertEqual(check.coverage(inventory(features=[a, b]))["inferred_dependencies"], 1)


class QuoteCompleteness(unittest.TestCase):
    """The two failures a 365-story run shipped, both of which passed every other check
    because both quotes were genuinely present in the document."""

    ROW9 = ("Every data-access path applies the acting user's view state for the record's "
            "domain — Full, Context only or None — at the data layer, not by hiding UI. "
            "Full serves navigation, lists, search, filters, KPI cards and exports, and "
            "Context only permits a record solely through the linked-record path.")
    SHORT = "Company or trading name"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "S1-book.md").write_text(
            "## sheet: Backlog\n\n| row | epic | name | description |\n"
            "| --- | --- | --- | --- |\n"
            f"| 9 | System | Enforce domain access | {self.ROW9} |\n"
            f"| 12 | Config | {self.SHORT} | Yes |\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def inv(self, task_name, task_quote, row=9, story_quote=None):
        f = feature()
        f["citations"] = [{"source_id": "S1", "location": f"sheet 'Backlog' row {row}",
                           "quote": story_quote or self.ROW9}]
        f["tasks"] = [{"id": "F1-T1", "name": task_name,
                       "citations": [{"source_id": "S1",
                                      "location": f"sheet 'Backlog' row {row}",
                                      "quote": task_quote}]}]
        inv = inventory(features=[f], not_scope=[])
        inv["sources"][0]["doc_type"] = "backlog"
        return inv

    def run_check(self, inv):
        return check.check_quote_completeness(inv, self.dir)

    def test_a_row_quoted_in_full_is_clean(self):
        findings, warnings = self.run_check(
            self.inv("Enforce domain access", self.ROW9))
        self.assertEqual((findings, warnings), ([], []))

    def test_a_task_quoting_its_own_name_is_an_error(self):
        """All 912 task citations in the real run did this. The quote is in the source — it is
        the title column — so the substring check could never have caught it."""
        findings, _ = self.run_check(
            self.inv("Enforce domain access", "Enforce domain access"))
        self.assertEqual(len(findings), 1)
        self.assertIn("the quote is the task's own name", findings[0])
        self.assertIn(str(len(self.ROW9)), findings[0], "it should name what was skipped")

    def test_a_self_quote_on_a_row_with_nothing_longer_is_only_a_warning(self):
        """A catalogue row of short attributes has no paragraph being skipped. Reporting it as
        an error would train people to ignore the check."""
        findings, warnings = self.run_check(
            self.inv(self.SHORT, self.SHORT, row=12, story_quote=self.SHORT))
        self.assertEqual(findings, [])
        self.assertTrue(any("columns on the cited row" in w for w in warnings))

    def test_a_quote_clipped_mid_sentence_is_an_error(self):
        """No quote in 917 exceeded 239 characters and 565 sat at that ceiling, because
        nothing said how much to quote."""
        clipped = self.ROW9[:120]
        findings, _ = self.run_check(
            self.inv("Enforce domain access", self.ROW9, story_quote=clipped))
        self.assertTrue(any("truncated quote" in f for f in findings))
        self.assertTrue(any(f"continues for {len(self.ROW9) - len(clipped)} more" in f
                            for f in findings))

    def test_the_finding_names_the_words_it_stopped_on(self):
        findings, _ = self.run_check(
            self.inv("Enforce domain access", self.ROW9,
                     story_quote=self.ROW9[:self.ROW9.index("at the data layer")]))
        self.assertTrue(any("Context only or None" in f for f in findings), findings)

    def test_a_quote_ending_on_a_full_stop_is_not_called_truncated(self):
        """A complete sentence is a legitimate partial quote; it is reported as leaving text
        unread, not as a defect."""
        upto = self.ROW9.index("Full serves")
        findings, warnings = self.run_check(
            self.inv("Enforce domain access", self.ROW9, story_quote=self.ROW9[:upto].strip()))
        self.assertEqual(findings, [])
        self.assertTrue(any("ends cleanly but leaves" in w for w in warnings))

    def test_an_unresolvable_location_is_not_second_guessed(self):
        """Same rule resolve_location already follows: a reference with no anchor produces
        noise rather than a finding."""
        inv = self.inv("Enforce domain access", "Enforce domain access")
        for cit in (inv["features"][0]["citations"][0],
                    inv["features"][0]["tasks"][0]["citations"][0]):
            cit["location"] = "§3.1"
        findings, warnings = self.run_check(inv)
        self.assertEqual(findings, [])
        self.assertTrue(any("does not resolve to a row" in w for w in warnings))


class TaskCitationsAreChecked(unittest.TestCase):
    """Every walk in this file stopped at feature.citations. That is why a task could cite a
    source that does not exist, quote nothing, or invent a passage, and pass."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "S1-sow.md").write_text(
            "## 2. Scope\n\nUsers must be able to log in with an email and password.\n"
            "Sessions expire after thirty minutes of inactivity.\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def with_task(self, **cit):
        f = feature()
        base = {"source_id": "S1", "location": "§2.1",
                "quote": "Sessions expire after thirty minutes of inactivity."}
        f["tasks"] = [{"id": "F1-T1", "name": "Expire sessions", "citations": [base | cit]}]
        return inventory(features=[f])

    def test_an_invented_task_quote_is_caught(self):
        found = check.verify_citations(
            self.with_task(quote="Sessions are secured with a hardware token."), self.dir)
        self.assertEqual(len(found), 1)
        self.assertIn("F1.tasks[0].citations[0]", found[0])

    def test_a_verbatim_task_quote_passes(self):
        self.assertEqual(check.verify_citations(self.with_task(), self.dir), [])

    def test_a_task_citing_a_source_that_does_not_exist_is_caught(self):
        found = check.check_integrity(self.with_task(source_id="S9"))
        self.assertTrue(any("F1.tasks[0].citations[0]" in f and "S9" in f for f in found))

    def test_an_empty_task_quote_is_caught(self):
        found = check.check_integrity(self.with_task(quote="   "))
        self.assertTrue(any("F1.tasks[0].citations[0]" in f and "quote is empty" in f
                            for f in found))

    def test_a_row_cited_only_under_its_story_is_not_reported_as_unread(self):
        """coverage_regions built its `referenced` set from feature citations alone, so a row
        the extraction did read came back as a gap — wrong in the direction that hides
        omissions behind noise."""
        (self.dir / "S1-book.md").write_text(
            "## sheet: Backlog\n\n| row | A |\n| --- | --- |\n| 4 | Login |\n| 5 | Export |\n",
            encoding="utf-8")
        (self.dir / "S1-sow.md").unlink()
        f = feature()
        f["citations"] = [{"source_id": "S1", "location": "sheet 'Backlog' row 4",
                           "quote": "Login"}]
        f["tasks"] = [{"id": "F1-T1", "name": "Export",
                       "citations": [{"source_id": "S1", "location": "sheet 'Backlog' row 5",
                                      "quote": "Export"}]}]
        inv = inventory(features=[f], not_scope=[])
        regions = check.coverage_regions(inv, self.dir)
        self.assertEqual([r for r in regions if 5 in r.get("rows", [])], [])


class InferredDependencies(unittest.TestCase):
    def dep(self, **extra):
        return inventory(features=[feature("F1"), feature("F2", depends_on=[
            {"feature_id": "F1", "inferred": True} | extra])])

    def test_an_inferred_dependency_without_a_why_is_caught(self):
        """A stated dependency needs evidence. An inferred one had no obligation at all, which
        left a bare id pointing at another bare id for a human to confirm on faith."""
        found = check.check_integrity(self.dep())
        self.assertTrue(any("inferred dependency needs 'why'" in f for f in found))

    def test_an_inferred_dependency_with_a_why_passes(self):
        found = check.check_integrity(self.dep(why="Password reset implies an account exists."))
        self.assertEqual([f for f in found if "depends_on" in f], [])


class Grouping(unittest.TestCase):
    """Epics, tasks and surfaces decide how much the estimate invents on its own."""

    def grouped(self, **over):
        f = feature("F1", "Login", epic_id="E1", surfaces=["backend", "frontend"],
                    tasks=[{"id": "T1", "name": "Sign in",
                            "citations": [{"source_id": "S1", "location": "§2.1", "quote": "q"}]}])
        inv = inventory(features=[f], epics=[{"id": "E1", "name": "Access", "origin": "source"}])
        inv.update(over)
        return inv

    def test_a_clean_grouping_passes(self):
        self.assertEqual(check.check_grouping(self.grouped()), [])

    def test_a_half_grouped_inventory_is_refused(self):
        inv = self.grouped()
        inv["features"].append(feature("F2", "Profile"))
        findings = check.check_grouping(inv)
        self.assertTrue(any("carry no epic_id" in f for f in findings), findings)

    def test_a_synthesised_epic_must_say_on_what_basis(self):
        inv = self.grouped(epics=[{"id": "E1", "name": "Access", "origin": "synthesised"}])
        self.assertTrue(any("no 'why'" in f for f in check.check_grouping(inv)))

    def test_a_source_row_cannot_belong_to_two_stories(self):
        """A row in two stories is the same work counted twice, which is the failure the
        whole grouping step exists to prevent."""
        inv = self.grouped()
        second = feature("F2", "Profile", epic_id="E1",
                         tasks=[{"id": "T1", "name": "Sign in",
                                 "citations": [{"source_id": "S1", "location": "§2.1", "quote": "q"}]}])
        inv["features"].append(second)
        self.assertTrue(any("already used by" in f for f in check.check_grouping(inv)))

    def test_a_task_without_a_citation_defeats_the_point_of_keeping_it(self):
        inv = self.grouped()
        inv["features"][0]["tasks"][0]["citations"] = []
        self.assertTrue(any("no citation" in f for f in check.check_grouping(inv)))

    def test_an_empty_surfaces_list_is_refused_but_an_absent_one_is_not(self):
        inv = self.grouped()
        inv["features"][0]["surfaces"] = []
        self.assertTrue(any("surfaces" in f for f in check.check_grouping(inv)))
        del inv["features"][0]["surfaces"]
        self.assertEqual(check.check_grouping(inv), [])

    def test_an_unknown_surface_is_refused(self):
        inv = self.grouped()
        inv["features"][0]["surfaces"] = ["backend", "telepathy"]
        self.assertTrue(any("telepathy" in f for f in check.check_grouping(inv)))


class MandatoryGroupingAtOnePointOne(unittest.TestCase):
    """From schema 1.1 an inventory carries a delivery structure or it is not finished."""

    def test_an_ungrouped_inventory_is_refused_at_one_point_one(self):
        inv = inventory(schema_version="1.1", features=[feature("F1", "Login")])
        self.assertTrue(any("no epics are declared" in f for f in check.check_grouping(inv)))

    def test_the_same_inventory_is_accepted_at_one_point_zero(self):
        """The obligation is new. An inventory written before it must stay readable, or every
        ledger entry in history becomes a finding."""
        inv = inventory(schema_version="1.0", features=[feature("F1", "Login")])
        self.assertEqual([f for f in check.check_grouping(inv) if "epic" in f], [])

    def test_at_one_point_one_a_story_with_no_epic_is_refused_even_with_no_epics_declared(self):
        inv = inventory(schema_version="1.1", features=[feature("F1", "Login")])
        self.assertTrue(any("carry no epic_id" in f for f in check.check_grouping(inv)))


class Sequence(unittest.TestCase):
    """Build order. The model states it; this is what checks it can actually be built."""

    def inv(self, epics=None, features=None, version="1.1"):
        epics = epics if epics is not None else [
            {"id": "E1", "name": "Foundation", "origin": "source", "sequence": 1,
             "sequence_why": "everything reads the data model it lands"},
            {"id": "E2", "name": "Booking", "origin": "source", "sequence": 2,
             "sequence_why": "needs the data model"},
        ]
        features = features if features is not None else [
            feature("F1", "Data model", epic_id="E1"),
            feature("F2", "Book a slot", epic_id="E2"),
        ]
        return inventory(schema_version=version, epics=epics, features=features)

    def findings(self, inv):
        return check.check_sequence(inv)[0]

    def test_a_clean_sequence_passes(self):
        self.assertEqual(self.findings(self.inv()), [])

    def test_a_missing_sequence_is_refused(self):
        epics = [{"id": "E1", "name": "Foundation", "origin": "source"},
                 {"id": "E2", "name": "Booking", "origin": "source", "sequence": 2,
                  "sequence_why": "second"}]
        self.assertTrue(any("no 'sequence'" in f for f in self.findings(self.inv(epics=epics))))

    def test_a_sequence_without_a_reason_is_refused(self):
        epics = [{"id": "E1", "name": "Foundation", "origin": "source", "sequence": 1},
                 {"id": "E2", "name": "Booking", "origin": "source", "sequence": 2,
                  "sequence_why": "second"}]
        self.assertTrue(any("sequence_why" in f for f in self.findings(self.inv(epics=epics))))

    def test_two_epics_cannot_hold_the_same_position(self):
        epics = [{"id": "E1", "name": "A", "origin": "source", "sequence": 1, "sequence_why": "w"},
                 {"id": "E2", "name": "B", "origin": "source", "sequence": 1, "sequence_why": "w"}]
        self.assertTrue(any("already held by" in f for f in self.findings(self.inv(epics=epics))))

    def test_a_gap_reads_as_a_dropped_epic_rather_than_a_deliberate_space(self):
        epics = [{"id": "E1", "name": "A", "origin": "source", "sequence": 1, "sequence_why": "w"},
                 {"id": "E2", "name": "B", "origin": "source", "sequence": 3, "sequence_why": "w"}]
        self.assertTrue(any("no gaps" in f for f in self.findings(self.inv(epics=epics))))

    def test_a_story_dependency_that_contradicts_the_order_is_a_finding(self):
        """The whole point of validating rather than trusting: E1 is sequenced first while a
        story in it waits on one in E2."""
        features = [feature("F1", "Data model", epic_id="E1",
                            depends_on=[{"feature_id": "F2", "inferred": True, "why": "needs it"}]),
                    feature("F2", "Book a slot", epic_id="E2")]
        findings = self.findings(self.inv(features=features))
        self.assertTrue(any("cannot be built before what it stands on" in f for f in findings),
                        findings)
        self.assertTrue(any("F1 depends on F2" in f for f in findings), findings)

    def test_a_stated_epic_dependency_that_contradicts_the_order_is_a_finding(self):
        """Ordering no story records — a design system before the screens consuming it."""
        epics = [{"id": "E1", "name": "A", "origin": "source", "sequence": 1, "sequence_why": "w",
                  "depends_on_epics": [{"epic_id": "E2", "why": "consumes its components"}]},
                 {"id": "E2", "name": "B", "origin": "source", "sequence": 2, "sequence_why": "w"}]
        self.assertTrue(any("E1 is sequenced 1 but depends on E2" in f
                            for f in self.findings(self.inv(epics=epics))))

    def test_a_dependency_pointing_at_no_declared_epic_is_a_finding(self):
        epics = [{"id": "E1", "name": "A", "origin": "source", "sequence": 1, "sequence_why": "w",
                  "depends_on_epics": [{"epic_id": "E9", "why": "typo"}]},
                 {"id": "E2", "name": "B", "origin": "source", "sequence": 2, "sequence_why": "w"}]
        self.assertTrue(any("'E9' is not a declared epic"
                            in f for f in self.findings(self.inv(epics=epics))))

    def test_a_cycle_between_epics_has_no_build_order_at_all(self):
        epics = [{"id": "E1", "name": "A", "origin": "source", "sequence": 1, "sequence_why": "w",
                  "depends_on_epics": [{"epic_id": "E2", "why": "a"}]},
                 {"id": "E2", "name": "B", "origin": "source", "sequence": 2, "sequence_why": "w",
                  "depends_on_epics": [{"epic_id": "E1", "why": "b"}]}]
        self.assertTrue(any("cycle" in f for f in self.findings(self.inv(epics=epics))))

    def test_the_report_orders_epics_by_sequence_not_by_array_position(self):
        """The array is allowed to disagree with the sequence, and the sequence wins — that is
        the whole reason the field exists rather than relying on write order."""
        epics = [{"id": "E2", "name": "Booking", "origin": "source", "sequence": 2,
                  "sequence_why": "w"},
                 {"id": "E1", "name": "Foundation", "origin": "source", "sequence": 1,
                  "sequence_why": "w"}]
        report = check.check_sequence(self.inv(epics=epics))[1]
        self.assertEqual([e["id"] for e in report["order"]], ["E1", "E2"])

    def test_it_is_quiet_below_one_point_one(self):
        epics = [{"id": "E1", "name": "A", "origin": "source"},
                 {"id": "E2", "name": "B", "origin": "source"}]
        self.assertEqual(self.findings(self.inv(epics=epics, version="1.0")), [])

    def test_a_dependency_inside_one_epic_creates_no_ordering_edge(self):
        features = [feature("F1", "A", epic_id="E1"),
                    feature("F2", "B", epic_id="E1",
                            depends_on=[{"feature_id": "F1", "inferred": True, "why": "w"}])]
        report = check.check_sequence(self.inv(features=features))[1]
        self.assertEqual(report["derived_edges"], 0)


class StandingScopeSelection(unittest.TestCase):
    """Foundation work: what was selected, what was declined, what may be paid twice."""

    CATALOGUE = {
        "repo_scaffold": {"name": "Repository scaffold and shared configuration", "stacks": "all"},
        "ci_pipeline": {"name": "Build, test and deploy pipeline", "stacks": "all"},
        "environments": {"name": "Environment provisioning and secrets", "stacks": "all"},
        "mobile_release": {"name": "Store provisioning and release channels",
                           "stacks": ["mobile_plus_backend"]},
    }

    def run_check(self, inv):
        return check.check_standing_overlap(inv, self.CATALOGUE)

    def inv(self, selected, features=None):
        return inventory(
            schema_version="1.1",
            features=features or [feature("F1", "Book a slot", epic_id="E1")],
            epics=[{"id": "E1", "name": "A", "origin": "source", "sequence": 1,
                    "sequence_why": "w"}],
            standing_scope={"catalogue": "cost-model standing_work", "selected": selected})

    ALL = [{"key": "repo_scaffold", "applies": True, "why": "greenfield"},
           {"key": "ci_pipeline", "applies": True, "why": "no story covers it"},
           {"key": "environments", "applies": False, "why": "client brings the AWS org"},
           {"key": "mobile_release", "applies": False, "why": "web only"}]

    def test_a_complete_selection_is_clean(self):
        findings, warnings, report = self.run_check(self.inv(list(self.ALL)))
        self.assertEqual(findings, [])
        self.assertEqual(warnings, [])
        self.assertEqual(len(report["selected"]), 2)
        self.assertEqual(len(report["excluded"]), 2)

    def test_an_unknown_key_is_a_finding(self):
        findings = self.run_check(self.inv([
            {"key": "teleportation", "applies": True, "why": "why not"}]))[0]
        self.assertTrue(any("teleportation" in f for f in findings))

    def test_covered_by_must_name_a_real_story(self):
        findings = self.run_check(self.inv([
            {"key": "ci_pipeline", "applies": False, "why": "covered", "covered_by": ["F99"]}]))[0]
        self.assertTrue(any("'F99' is not a declared story" in f for f in findings))

    def test_an_item_nobody_wrote_down_warns_but_never_discounts(self):
        """It is still priced, so the failure mode is paying twice, never silently dropping."""
        findings, warnings, report = self.run_check(self.inv([
            {"key": "repo_scaffold", "applies": True, "why": "greenfield"}]))
        self.assertEqual(findings, [])
        self.assertEqual(sorted(report["unmentioned"]),
                         ["ci_pipeline", "environments", "mobile_release"])
        self.assertTrue(any("priced regardless" in w for w in warnings), warnings)

    def test_an_unmentioned_stack_gated_item_is_warned_about_differently(self):
        """The one case where silence really can drop work: a stack-gated item is priced only
        when the estimate runs under a matching --stack, so 'priced anyway' would be false."""
        warnings = self.run_check(self.inv(
            [r for r in self.ALL if r["key"] != "mobile_release"]))[1]
        self.assertTrue(any("stack-gated" in w and "can drop real work" in w for w in warnings),
                        warnings)
        self.assertFalse(any("priced regardless" in w for w in warnings))

    def test_the_measured_double_count_is_surfaced(self):
        """All three delivered anchors priced repo scaffold as a story AND paid standing work
        for it. That overlap was invisible because the two lists lived in different skills."""
        inv = self.inv([{"key": "repo_scaffold", "applies": True, "why": "greenfield"},
                        {"key": "ci_pipeline", "applies": False, "why": "n/a"},
                        {"key": "environments", "applies": False, "why": "n/a"},
                        {"key": "mobile_release", "applies": False, "why": "n/a"}],
                       features=[feature("F1", "Monorepo scaffold and shared contracts",
                                         epic_id="E1")])
        findings, warnings, report = self.run_check(inv)
        self.assertEqual(findings, [])
        self.assertTrue(report["advisory_only"])
        self.assertEqual(report["overlaps"][0]["key"], "repo_scaffold")
        self.assertTrue(any("pays for it twice" in w for w in warnings))

    def test_a_declined_item_raises_no_overlap_warning(self):
        """Declining it with the story named in covered_by is the fix, so it must go quiet."""
        inv = self.inv([{"key": "repo_scaffold", "applies": False,
                         "why": "delivered as F1", "covered_by": ["F1"]},
                        {"key": "ci_pipeline", "applies": False, "why": "n/a"},
                        {"key": "environments", "applies": False, "why": "n/a"},
                        {"key": "mobile_release", "applies": False, "why": "n/a"}],
                       features=[feature("F1", "Monorepo scaffold", epic_id="E1")])
        self.assertEqual(self.run_check(inv)[1], [])

    def test_an_inventory_with_no_selection_says_so_rather_than_failing(self):
        inv = inventory(schema_version="1.0", features=[feature("F1", "Login")])
        findings, warnings, report = self.run_check(inv)
        self.assertEqual(findings, [])
        self.assertIn("stack profile alone", report["note"])


class BoilerplateTags(unittest.TestCase):
    """A justification repeated across the inventory is a default wearing a reason."""

    def features(self, count, why):
        return [feature(f"F{i}", f"Thing {i}",
                        tags={**feature()["tags"], "size_band": tag("M", why=why)})
                for i in range(count)]

    def test_one_sentence_over_most_of_the_inventory_is_reported(self):
        warnings = check.check_boilerplate_tags(self.features(50, "the row's verb is not a read"))
        self.assertTrue(any("size_band" in w and "50 of 50" in w for w in warnings))

    def test_genuinely_distinct_reasons_are_not_reported(self):
        features = [feature(f"F{i}", f"Thing {i}", tags={
            "size_band": tag("M", why=f"size reason {i}"),
            "compressibility": tag("high", why=f"compression reason {i}"),
            "review_tier": tag("routine", why=f"tier reason {i}"),
            "clarity": tag("medium", why=f"clarity reason {i}"),
            "novelty": tag("standard", why=f"novelty reason {i}"),
        }) for i in range(50)]
        self.assertEqual(check.check_boilerplate_tags(features), [])

    def test_a_small_inventory_is_left_alone(self):
        """Ten features sharing a reason is a small consistent scope, not a defaulted one."""
        self.assertEqual(check.check_boilerplate_tags(self.features(10, "same reason")), [])

    def test_it_does_not_block_the_estimate(self):
        """A backlog of near-identical CRUD screens legitimately shares a justification, and
        refusing to price it would be wrong; pricing it as though every band had been judged
        would also be wrong. So it warns, and the estimate carries the warning."""
        inv = inventory(features=self.features(50, "one rule for all of them"))
        self.assertEqual([f for f in check.check_integrity(inv) if "justification" in f], [])


class Granularity(unittest.TestCase):
    """The check that was missing, and the one the whole rebuild turns on.

    Every downstream figure is linear in the story count, and the story count is a property of
    whoever wrote the document rather than of the work. Across the three delivered projects the
    same kind of scope was written at wildly different grain — 9.2, 2.9 and 3.1 hours per
    delivered story, a 3.2-fold spread — and 2.x had no check for it at all. The two sanity
    ratios it did have both divided by numbers the extraction itself chooses, so both could be
    satisfied by re-slicing.

    Surfaces per story cannot be: it is an observation about what each story touches. It
    separated the three anchors at 2.29 / 1.25 / 1.12 while hours per surface-touch stayed
    inside 1.74x.
    """

    BANDS = check.load_bands()[0]

    def stories(self, count, surfaces, epic=None):
        return [feature(f"F{i}", f"Thing {i}",
                        **({"epic_id": epic} if epic else {}),
                        surfaces=list(surfaces))
                for i in range(count)]

    def warn(self, features):
        return check.check_granularity(features, self.BANDS)[0]

    def test_an_inventory_at_the_anchors_grain_raises_nothing(self):
        self.assertEqual(self.warn(self.stories(40, ("backend", "frontend"))
                                   + self.stories(20, ("backend", "frontend", "data"))), [])

    def test_a_finely_sliced_inventory_is_reported_with_its_direction(self):
        """The bands are fitted to the anchor's grain, so half the surfaces per story means
        roughly twice as many stories for the same scope — and the estimate runs HIGH."""
        warnings = self.warn(self.stories(60, ("backend",)))
        self.assertTrue(any("sliced" in w and "FINER" in w for w in warnings))
        self.assertTrue(any("run HIGH" in w for w in warnings))

    def test_a_coarsely_sliced_inventory_is_reported_the_other_way(self):
        warnings = self.warn(self.stories(60, ("backend", "frontend", "design", "infra", "data")))
        self.assertTrue(any("COARSER" in w and "run LOW" in w for w in warnings))

    def test_it_never_gates_and_says_so(self):
        """A genuinely fine-grained backlog is a real thing. This exists so it gets said out
        loud rather than quietly multiplying — not so it can be refused."""
        _, report = check.check_granularity(self.stories(60, ("backend",)), self.BANDS)
        self.assertIn("advisory_only", report)
        self.assertAlmostEqual(report["ratio_to_anchor"], 1 / 2.29, places=2)

    def test_it_reports_the_ratio_even_when_it_is_quiet(self):
        """Silence has to be distinguishable from not having looked."""
        _, report = check.check_granularity(self.stories(60, ("backend", "frontend")), self.BANDS)
        self.assertEqual(report["surfaces_per_story"], 2.0)
        self.assertEqual(report["anchor_expects"], 2.29)

    def test_stories_per_epic_travels_with_it_when_the_source_grouped_the_work(self):
        report = check.check_granularity(self.stories(60, ("backend", "frontend"), epic="E1"),
                                         self.BANDS)[1]
        self.assertEqual(report["stories_per_epic"], 60.0)

    def test_a_mostly_untagged_inventory_is_skipped_rather_than_guessed_at(self):
        """Without surfaces the ratio would measure the tagging rate, not the slicing — and a
        number that means something else is worse than no number."""
        features = self.stories(10, ("backend",)) + [feature(f"U{i}", surfaces=None)
                                                     for i in range(50)]
        warnings, report = check.check_granularity(features, self.BANDS)
        self.assertEqual(warnings, [])
        self.assertIn("would measure the tagging", report["skipped"])

    def test_a_small_inventory_is_left_alone(self):
        self.assertEqual(self.warn(self.stories(8, ("backend",))), [])

    def test_a_missing_anchor_costs_the_report_not_the_run(self):
        warnings, report = check.check_granularity(self.stories(60, ("backend",)), None)
        self.assertEqual(warnings, [])
        self.assertIn("skipped", report)


class Sizing(unittest.TestCase):
    """The band distribution against the delivery anchor.

    None of this blocks, and in 3.0 none of it is grounds on its own to re-band a story.
    Both changes came out of measuring the thing these checks were tuned against. The anchor
    was recorded as 25% L with no XS and no XL; its own per-story table says 31% L, 2.7% XS
    and 4.0% XL. And the 2.x bands ran 1 h to 90 h, so a 12-point shift in the L share moved
    the baseline 17% — against 2% on the measured bands. A threshold tuned to the first is
    noise against the second.
    """

    BANDS = check.load_bands()[0]

    def stories(self, bands, lines=1, tier="routine"):
        """`bands` as {band: count}. `lines` source rows per story — the volume proxy."""
        out, i = [], 0
        for band, count in bands.items():
            for _ in range(count):
                i += 1
                out.append(feature(
                    f"F{i}", f"Thing {i}",
                    tasks=[{"id": f"T{i}-{k}", "name": "row",
                            "citations": [{"source_id": "S1", "location": f"row {k}", "quote": "q"}]}
                           for k in range(lines)],
                    tags={**feature()["tags"], "size_band": tag(band, why=f"reason {i}"),
                          "review_tier": tag(tier, why=f"tier {i}")}))
        return out

    def warn(self, features):
        return check.check_sizing(features, self.BANDS)[0]

    def test_the_anchor_shape_raises_nothing(self):
        """The measured mix — 31% L, 45% M, 17% S, 3% XS, 4% XL — over one source line each."""
        self.assertEqual(self.warn(self.stories({"L": 23, "M": 34, "S": 13, "XS": 2, "XL": 3})), [])

    def test_a_share_the_anchor_cannot_account_for_is_reported_with_what_it_is_worth(self):
        warnings = self.warn(self.stories({"L": 240, "M": 100, "S": 10}, lines=3))
        self.assertTrue(any("% of stories are L" in w and "31%" in w for w in warnings))
        self.assertTrue(any("of the story hours" in w for w in warnings))

    def test_the_distribution_report_says_it_is_not_a_reason_to_reband(self):
        """The bias this closes: the classifier was told to expect 64% M before it judged
        anything, and then flagged for deviating from it. The prior was injected and then
        enforced, so the distribution stopped carrying information about the project."""
        warnings = self.warn(self.stories({"L": 240, "M": 100, "S": 10}, lines=3))
        self.assertTrue(any("NOT on its own a reason to re-band" in w for w in warnings))

    def test_a_handful_of_xs_is_not_reported_because_the_anchor_had_some(self):
        """2.x warned on the first XS tag, saying none of the anchor's stories was XS. Two of
        them were — 4.0 pre-Epic-4 hardening and 9.8, the one-line projection fix — and the
        warning was pushing real work up a band."""
        self.assertEqual(self.warn(self.stories({"XS": 2, "M": 34, "L": 23, "S": 13, "XL": 3})), [])

    def test_an_inventory_that_is_a_tenth_xs_still_is(self):
        warnings = self.warn(self.stories({"XS": 20, "M": 45, "L": 18, "S": 7}))
        self.assertTrue(any("are XS" in w and "2.7%" in w for w in warnings))

    def test_a_few_xl_are_not_reported_but_a_pile_of_them_are(self):
        self.assertEqual(self.warn(self.stories({"XL": 3, "M": 34, "L": 23, "S": 13, "XS": 2})), [])
        warnings = self.warn(self.stories({"XL": 20, "M": 45, "L": 18, "S": 7}))
        self.assertTrue(any("XL" in w and "signal to look for a split" in w for w in warnings))

    def test_a_band_that_tracks_risk_is_the_double_count(self):
        """Content held at one source line, so only the review tier varies with the band."""
        features = (self.stories({"S": 12}, lines=1, tier="routine")
                    + self.stories({"L": 12}, lines=1, tier="sensitive")
                    # The bulk carries several rows each, which is what makes the inventory
                    # row-shaped — without a volume proxy the correlation is uninterpretable.
                    + self.stories({"M": 60}, lines=4, tier="routine"))
        for i, f in enumerate(features):      # unique ids across the three groups
            f["id"] = f"G{i}"
        warnings = check.check_sizing(features, self.BANDS)[0]
        self.assertTrue(any("tracking risk, not volume" in w for w in warnings))

    def test_one_source_line_priced_as_a_new_capability_is_reported(self):
        features = self.stories({"L": 30}, lines=1) + self.stories({"M": 120}, lines=4)
        for i, f in enumerate(features):
            f["id"] = f"H{i}"
        warnings = check.check_sizing(features, self.BANDS)[0]
        self.assertTrue(any("on a single source line" in w for w in warnings))

    def test_density_against_the_anchor_rate_says_it_can_be_re_sliced_away(self):
        """It still fires, and it now admits its own weakness: both sides of the ratio are
        under the extraction's control, so it can always be satisfied by re-slicing."""
        warnings = self.warn(self.stories({"L": 40, "M": 20, "S": 5}, lines=3))
        self.assertTrue(any("per source line" in w for w in warnings))
        self.assertTrue(any("satisfied by re-slicing" in w for w in warnings))

    def test_the_same_inventory_re_sliced_finer_satisfies_the_density_check(self):
        """Demonstrating the weakness the message admits to. Same L-heavy shape, same rows —
        band them XS instead and the ratio lands on the anchor with nothing said."""
        self.assertEqual([w for w in self.warn(self.stories({"XS": 60, "S": 5}, lines=3))
                          if "per source line" in w], [])

    def test_prose_sourced_inventories_skip_the_volume_checks_and_say_so(self):
        """One citation over a PRD section is not one line of stated requirement, so the count
        proves nothing. Silence here has to be explained rather than implied."""
        _, report = check.check_sizing(self.stories({"L": 19, "M": 49, "S": 8}), self.BANDS)
        self.assertFalse(report["row_shaped"])
        self.assertTrue(any("per-source-line" in s for s in report["skipped"]))

    def test_a_small_inventory_is_left_alone(self):
        self.assertEqual(self.warn(self.stories({"L": 8, "M": 5})), [])

    def test_a_missing_anchor_costs_the_report_not_the_run(self):
        warnings, report = check.check_sizing(self.stories({"L": 40, "M": 40}), None)
        self.assertEqual(warnings, [])
        self.assertIn("skipped", report)

    def test_it_does_not_block_the_estimate(self):
        """est-estimate refuses to price an inventory with findings. A band distribution is a
        judgement about a project's shape, never a certainty, so it must never land there."""
        inv = inventory(features=self.stories({"L": 131, "M": 154, "S": 56}, lines=3))
        self.assertEqual([f for f in check.check_integrity(inv) if "size_band:" in f], [])


class Bands(unittest.TestCase):
    def test_the_shipped_seed_carries_an_anchor(self):
        bands, _, source = check.load_bands()
        self.assertIn("shipped seed", source)
        self.assertIn("distribution", bands["_anchor"])

    def test_every_band_carries_worked_exemplars(self):
        """Adjectives are what the classifier had when it over-tagged. Exemplars are the fix,
        so a band shipped without them is a band with no reference class."""
        bands = check.load_bands()[0]
        for band in check.TAG_VOCABULARY["size_band"]:
            self.assertTrue(bands[band].get("exemplars"), f"{band} has no exemplars")

    def test_a_project_model_without_an_anchor_is_reported_not_silently_replaced(self):
        """The dangerous case: the project has a model, it has been recalibrated, and the bands
        being compared against came from somewhere else. Silence there is the original bug."""
        import subprocess, sys as _s
        with tempfile.TemporaryDirectory() as tmp:
            old_model = Path(tmp) / "cost-model.json"
            old_model.write_text(json.dumps({"size_bands": {"M": {"lo": 6, "likely": 11, "hi": 20}}}))
            inv_path = Path(tmp) / "inv.json"
            inv_path.write_text(json.dumps(inventory(features=[
                feature(f"F{i}", f"Thing {i}") for i in range(25)])))
            features = [feature(f"F{i}", f"Thing {i}") for i in range(25)]
            inv_path.write_text(json.dumps(inventory(features=features)))
            cls_path = Path(tmp) / "classification.json"
            cls_path.write_text(json.dumps({
                "schema_version": "1.0", "generated": "2026-09-08T00:00:00Z",
                "inventory": str(inv_path),
                "features": {f["id"]: f["tags"] for f in features}}))
            out = subprocess.run(
                [_s.executable, str(Path(__file__).resolve().parent.parent / "inventory-check.py"),
                 str(inv_path), "--cost-model", str(old_model),
                 "--classification", str(cls_path)],
                capture_output=True, text=True)
            result = json.loads(out.stdout)
            self.assertTrue(any("carries no size_bands._anchor" in w for w in result["warnings"]))
            self.assertEqual(result["findings"], [])

    def test_an_unreadable_model_falls_back_to_the_seed(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "nope.json"
            bands, _, source = check.load_bands(missing)
            self.assertIn("shipped seed", source)
            self.assertTrue(bands)


class ClassificationSplit(unittest.TestCase):
    """The tags live in classification.json now. What must never happen is a quiet degrade."""

    def features(self, n=25):
        return [feature(f"F{i}", f"Thing {i}") for i in range(n)]

    def test_the_score_refuses_rather_than_losing_18_percent_of_itself(self):
        """clarity is 0.18 of input_completeness. Scored without a classification every feature
        reads clarity 0.0 — no exception, no finding — the ceiling silently becomes 0.82, and
        since band width is 1 + k(1-completeness)^p every estimate quietly widens with nothing
        to point at. So it returns null and says what is missing."""
        inv = inventory(features=self.features())
        scoring = check.score(inv, classified=False)
        self.assertIsNone(scoring["input_completeness"])
        self.assertIn("clarity_quality", scoring["pending"])
        self.assertNotIn("clarity_quality", scoring["points"])

    def test_commitment_still_scores_without_a_classification(self):
        """commitment is a field on the story, not a tag — it never moved."""
        inv = inventory(features=self.features())
        self.assertEqual(check.score(inv, classified=False)["points"]["commitment_quality"], 1.0)

    def test_a_missing_axis_is_a_finding_once_a_classification_exists(self):
        """The inventory schema no longer requires tags, so an absent axis is a gap in the
        classification rather than a shape validate_schema would have caught."""
        f = feature("F1")
        del f["tags"]["size_band"]
        findings = check.check_integrity(inventory(features=[f]), classified=True)
        self.assertTrue(any("F1.tags.size_band" in x and "no classification" in x for x in findings))
        self.assertEqual(check.check_integrity(inventory(features=[f]), classified=False), [])

    def test_the_join_puts_the_tags_back_where_every_check_reads_them(self):
        features = [dict(f) for f in self.features(3)]
        rows = {f["id"]: f.pop("tags") for f in features}
        inv = inventory(features=features)
        orphans = check.join_classification(inv, {"features": rows})
        self.assertEqual(orphans, [])
        self.assertEqual(inv["features"][0]["tags"]["size_band"]["value"], "M")

    def test_the_classification_is_held_to_its_own_schema(self):
        """The inventory has a schema; the file that decides what everything costs should not be
        the unchecked half. It shipped with one and nothing validated against it."""
        import subprocess, sys as _s
        with tempfile.TemporaryDirectory() as tmp:
            inv_path, cls_path = Path(tmp) / "inv.json", Path(tmp) / "classification.json"
            features = self.features(25)
            inv_path.write_text(json.dumps(inventory(features=features)))
            rows = {f["id"]: f["tags"] for f in features}
            rows[features[0]["id"]]["size_band"] = {"value": "M"}      # no why, no status
            cls_path.write_text(json.dumps({"features": rows}))        # and no schema_version
            out = subprocess.run(
                [_s.executable, str(Path(__file__).resolve().parent.parent / "inventory-check.py"),
                 str(inv_path), "--classification", str(cls_path)],
                capture_output=True, text=True)
            findings = json.loads(out.stdout)["findings"]
            self.assertTrue(any("classification.schema_version" in f for f in findings))
            self.assertTrue(any("'why' is empty" in f for f in findings))

    def test_a_classification_for_a_feature_that_is_gone_is_named(self):
        """It means the classification was made against a different extraction, and pricing on
        it would quietly mis-key every judgement after the one that moved."""
        features = [dict(f) for f in self.features(2)]
        rows = {f["id"]: f.pop("tags") for f in features}
        rows["F99"] = rows[features[0]["id"]]
        orphans = check.join_classification(inventory(features=features), {"features": rows})
        self.assertEqual(orphans, ["F99"])


if __name__ == "__main__":
    unittest.main()
