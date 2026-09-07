#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["openpyxl>=3.1"]
# ///
"""Build the adversarial fixture corpus for the est module.

Every fixture here encodes a way a real client document breaks an extractor, and each one
was chosen because it produces output that *reads correctly while being wrong* — the class
of defect a plausible-looking eval run sails straight past. The row-anchor case is not
hypothetical: it shipped, passed a real-input eval, and was caught only by an adversarial read.

Binary fixtures are generated rather than committed so they stay diffable and editable.

    uv run evals/build-fixtures.py --out evals/fixtures
"""

import argparse
import json
from pathlib import Path

from openpyxl import Workbook


def banner_workbook(out):
    """Row anchors: a title banner and a blank row above the real header.

    Naive conversion promotes the banner to the header and renumbers the survivors, so
    every citation below the blank row points one or more rows off. Rows are numbered here
    so the expectation is checkable: 'Refund processing' must be cited as row 7, not row 5.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Scope"
    ws.append(["NORTHWIND LOGISTICS — COMMERCIAL IN CONFIDENCE"])   # row 1
    ws.append([])                                                    # row 2
    ws.append(["Ref", "Feature", "Priority"])                        # row 3
    ws.append(["1.1", "Depot job list", "Must"])                     # row 4
    ws.append([])                                                    # row 5
    ws.append(["1.2", "Driver mobile app", "Must"])                  # row 6
    ws.append(["1.3", "Refund processing", "Must"])                  # row 7

    hidden = wb.create_sheet("Sheet3")   # real scope on an unpromising tab name
    hidden.append(["Additional requirement"])
    hidden.append(["Data retention policy enforcement (GDPR art. 17)"])

    terms = wb.create_sheet("Commercials")
    terms.append(["Item", "Value"])
    terms.append(["Day rate", "GBP 620"])
    terms.append(["Payment terms", "30 days net"])
    wb.save(out / "backlog-with-banner.xlsx")


def multiline_csv(out):
    """A quoted field containing a newline. Splitting on newlines first tears it in half
    and shifts every row after it, corrupting both the quote and the anchor."""
    (out / "requirements.csv").write_text(
        'Ref,Requirement\n'
        'R1,"The system shall allow a driver to capture a signature\n'
        'and a photograph as proof of delivery."\n'
        'R2,Localisation into Polish and Romanian.\n',
        encoding="utf-8",
    )


def non_english_source(out):
    """A Ukrainian source. The extractor must translate for `quote` and keep the original
    in `quote_original`, or a reviewer who speaks the language cannot verify anything."""
    (out / "vymohy-uk.md").write_text(
        "# Вимоги до системи\n\n"
        "## 2. Обсяг робіт\n\n"
        "2.1 Користувачі повинні мати можливість входити в систему за допомогою "
        "електронної пошти та паролю.\n\n"
        "2.2 Система повинна обробляти платежі через Stripe та зберігати історію транзакцій.\n\n"
        "## 5. Комерційні умови\n\n"
        "5.1 Оплата здійснюється щомісяця.\n",
        encoding="utf-8",
    )


def contradicting_sources(out):
    """A SOW and a call that disagree on something that changes the price.

    The SOW excludes PCI; the client's own IT lead says it applies. Resolving this silently
    picks a commercial position. The transcript also raises work the SOW never covers.
    """
    (out / "sow-excerpt.txt").write_text(
        "STATEMENT OF WORK — EXCERPT\n\n"
        "3. SCOPE\n"
        "3.1 Supplier shall implement a depot portal with authenticated access.\n"
        "3.2 Supplier shall implement payment capture via the Client's Stripe account.\n\n"
        "4. EXCLUSIONS\n"
        "4.1 PCI-DSS compliance work is excluded; the Client's existing portal remains "
        "the sole cardholder data environment.\n"
        "4.2 Migration of historical data is excluded.\n\n"
        "9. COMMERCIAL TERMS\n"
        "9.1 Invoiced monthly in arrears, 30 days net.\n",
        encoding="utf-8",
    )
    (out / "discovery-call.md").write_text(
        "Discovery call — 3 Sep 2026\n\n"
        "[00:04:10] Client IT lead: anything that touches the payment flow goes through our "
        "PCI review, no exceptions. That includes anything you build that reads the "
        "transaction table.\n\n"
        "[00:11:52] Client COO: honestly the real problem is the dispatchers. Every Monday "
        "they hand-copy the whole job list into a spreadsheet and email it round the depots. "
        "That's what I want to go away.\n\n"
        "[00:19:30] Client COO: and it'd be nice to have some kind of predictive thing for "
        "late routes eventually. Not now.\n",
        encoding="utf-8",
    )


def thin_brief(out):
    """Two paragraphs. Must produce a wide band and a strong question list, not twenty
    inferred features — the failure here is confident elaboration."""
    (out / "brief.md").write_text(
        "We need a portal where our depots can see their jobs, and an app the drivers use "
        "to confirm deliveries. It should work when they have no signal.\n\n"
        "Budget is tight and we'd like it live before the new year.\n",
        encoding="utf-8",
    )


def unreadable_sources(out):
    """An unsupported format and an empty PDF-named file. Both must be reported as unread,
    never silently dropped — a source absent from the inventory is indistinguishable from
    one nobody opened."""
    (out / "wireframes.sketch").write_bytes(b"\x00\x01binary-not-a-document")
    (out / "scanned-contract.pdf").write_bytes(b"%PDF-1.4\n% no extractable text\n")


CASES = [
    {
        "id": "row-anchor-drift",
        "fixture": "backlog-with-banner.xlsx",
        "asks": "Extract scope from this workbook.",
        "must_hold": [
            "'Refund processing' is cited as sheet 'Scope' row 7, not row 5 or 6",
            "the banner in row 1 is not treated as a column header",
            "the 'Sheet3' tab is read; data retention enforcement appears as a feature",
            "the 'Commercials' tab appears in not_scope, not as features",
            "refund processing and data retention are tagged sensitive or critical",
        ],
    },
    {
        "id": "multiline-quoted-field",
        "fixture": "requirements.csv",
        "asks": "Extract scope from this requirements file.",
        "must_hold": [
            "the R1 quote reads as one sentence, not 'signature\\nand a photograph' welded together",
            "R2 is cited at its real line number, not shifted by R1's embedded newline",
        ],
    },
    {
        "id": "non-english-source",
        "fixture": "vymohy-uk.md",
        "asks": "Extract scope from this document.",
        "must_hold": [
            "every citation carries quote_original in Ukrainian alongside the translation",
            "the payments feature is tagged sensitive",
            "section 5 (комерційні умови) is in not_scope, not a feature",
        ],
    },
    {
        "id": "contradicting-sources",
        "fixture": ["sow-excerpt.txt", "discovery-call.md"],
        "asks": "Extract scope. The SOW is the contractual document.",
        "must_hold": [
            "the PCI disagreement appears in conflicts and is NOT silently resolved",
            "the dispatcher Monday cycle is surfaced — it is the stated core problem and the SOW does not cover it",
            "anything not traceable to the SOW carries scope_status outside_agreed_scope",
            "the predictive routing remark is commitment: speculative, not committed",
            "section 9 commercial terms are in not_scope",
        ],
    },
    {
        "id": "thin-brief",
        "fixture": "brief.md",
        "asks": "Estimate scope from this brief.",
        "must_hold": [
            "input_completeness scores low (roughly under 0.25)",
            "almost every feature is clarity: low",
            "open_questions is substantial — the questions are the deliverable here",
            "no admin dashboard, audit log or export feature is invented",
            "offline operation is tagged low compressibility and novel",
        ],
    },
    {
        "id": "unreadable-sources",
        "fixture": ["wireframes.sketch", "scanned-contract.pdf"],
        "asks": "Extract scope from these files.",
        "must_hold": [
            "both are listed in sources with a coverage_note saying they could not be read",
            "neither is silently omitted from the inventory",
            "inventory-check --manifest reports nothing missing, because both were listed",
        ],
    },
]


def main():
    ap = argparse.ArgumentParser(description="Generate the adversarial fixture corpus.")
    ap.add_argument("--out", default="evals/fixtures", help="directory to write fixtures into")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for build in (banner_workbook, multiline_csv, non_english_source,
                  contradicting_sources, thin_brief, unreadable_sources):
        build(out)

    (out.parent / "cases.json").write_text(
        json.dumps({"skill": "est-scope-extract", "cases": CASES}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "ok": True,
        "fixtures": sorted(p.name for p in out.iterdir()),
        "cases": str(out.parent / "cases.json"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
