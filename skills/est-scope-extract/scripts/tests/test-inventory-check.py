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


class Sizing(unittest.TestCase):
    """The band distribution against the delivery anchor.

    None of this blocks. All of it exists because one extraction tagged 37% of its stories `L`
    against an anchor's 25%, priced three times over, and nothing in the pipeline objected.
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
        """25% L, 64% M, 11% S over one source line each — the shape that was delivered."""
        self.assertEqual(self.warn(self.stories({"L": 19, "M": 49, "S": 8})), [])

    def test_too_many_large_stories_is_reported_with_what_it_is_worth(self):
        warnings = self.warn(self.stories({"L": 131, "M": 154, "S": 56, "XS": 10, "XL": 1}, lines=3))
        self.assertTrue(any("37% of stories are L" in w and "25%" in w for w in warnings))
        self.assertTrue(any("of the whole manual baseline" in w for w in warnings))

    def test_xs_is_reported_because_the_anchor_had_none(self):
        warnings = self.warn(self.stories({"XS": 6, "M": 45, "L": 18, "S": 7}))
        self.assertTrue(any("are XS" in w for w in warnings))

    def test_xl_is_reported_as_a_split_signal(self):
        warnings = self.warn(self.stories({"XL": 1, "M": 49, "L": 19, "S": 8}))
        self.assertTrue(any("XL" in w and "signal to split" in w for w in warnings))

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

    def test_density_against_the_anchor_rate(self):
        """Every story L over three source rows: 11h per row against the anchor's 2h."""
        warnings = self.warn(self.stories({"L": 40, "M": 20, "S": 5}, lines=3))
        self.assertTrue(any("manual baseline per source line" in w for w in warnings))

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
