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


def sizing_workbook(out):
    """Band assignment: four rows whose correct band is not arguable.

    Every one of these was got wrong on a real workbook, and each wrong answer reads as
    reasonable on the page. The depot rows are six faces of one resource and must collapse to a
    single `M`; the SSO row is one line and is nonetheless `L`, because it is the first
    authentication protocol in the codebase; the capacity row is the trap — it is read by
    everything in the product, which raises its review tier and not its size; and the alert
    catalogue is one story configured forty ways, not forty features.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = "Backlog"
    ws.append(["Epic", "Feature", "Detail"])
    rows = [
        ("Depots", "Create a depot", "An operator creates a depot with its name, address and opening hours."),
        ("Depots", "View a depot", "An operator opens a depot and sees its details and its bays."),
        ("Depots", "Edit a depot", "An operator changes a depot's details."),
        ("Depots", "Archive a depot", "An operator archives a depot; archived depots take no new jobs."),
        ("Depots", "List depots", "A paginated list of depots with the columns the operator chose."),
        ("Depots", "Search depots", "Free-text search over depot name and address."),
        ("Access", "Sign in with Microsoft Entra",
         "Staff sign in with their work account instead of a password."),
        ("Depots", "Derive depot capacity from its bays",
         "A depot's capacity is the count of its in-service bays. Every job assignment, the "
         "planning board, the capacity report and the public availability API read this."),
        ("Billing", "Export the monthly invoice run",
         "An operator downloads the month's invoices as a single PDF."),
        ("Access", "Reset a forgotten password",
         "A member requests a reset link by email and sets a new password."),
    ]
    for row in rows:
        ws.append(list(row))

    alerts = wb.create_sheet("Alert rules")
    alerts.append(["Rule", "Fires when"])
    for i in range(1, 41):
        alerts.append([f"ALERT-{i:02d}", f"Condition {i} is met on a depot or a vehicle"])

    wb.save(out / "sizing-backlog.xlsx")


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


# Kept in step with cases.json BY HAND is how this drifted: it carried the pre-3.0
# `band-assignment` case long after the file had replaced it, so re-running the
# builder reverted the suite to expectations the module no longer meets. If you edit
# cases.json, edit this too — the builder rewrites that file.
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
            "refund processing and data retention are tagged sensitive or critical"
        ]
    },
    {
        "id": "synthesis-and-surfaces",
        "fixture": "sizing-backlog.xlsx",
        "asks": "Extract scope from this workbook.",
        "must_hold": [
            "the six Depots CRUD rows collapse into a single story, not six features",
            "the 40 alert-rule rows are one story whose size why names the count, not 40 features",
            "that depot story carries surfaces — it is the strongest single predictor of size in the delivery anchor (median surfaces per band 1/2/3/3/4, against acceptance-criterion counts of 5/7/8.5/8/12 that cannot tell M from L), so an untagged inventory costs the classifier its best signal",
            "'Sign in with Microsoft Entra' carries a backend surface and reads as a protocol the codebase does not have — the extraction records that, the classification prices it",
            "the extraction report states the story count and the surfaces per story, because inventory-check.py compares the latter against the anchor's 2.29 and that comparison moves the estimate more than any single band does",
            "no size_band is set anywhere in the inventory — bands are a judgement about cost and live in classification.json, written by est-estimate"
        ],
        "note": "Renamed from `band-assignment` in the 3.0 rebuild. Four of its assertions were about size_band, which est-scope-extract has not set since extraction and classification were separated — and one of them ('no story is tagged XS') was measured false: the delivery anchor's own record has 2.7% XS and 4.0% XL. The band assertions now live in est-estimate's own tests and its anchor backtest."
    },
    {
        "id": "row-text-not-row-label",
        "fixture": "sizing-backlog.xlsx",
        "asks": "Extract scope from this workbook.",
        "must_hold": [
            "every task's citation quote is the row's Detail text, never a copy of the row's Feature title — a run that quoted 912 titles back passed every check because the title is genuinely in the document, one column over",
            "the quote for 'Derive depot capacity from its bays' carries the whole Detail cell including 'the public availability API read this', not the first clause of it",
            "no quote stops mid-sentence while the cell it cites continues",
            "the six Depots rows survive as six tasks under one story, each with its own text, so a reviewer can check the story against the workbook without opening it",
            "inventory-check.py --normalized reports no truncated or self-quoting citations"
        ]
    },
    {
        "id": "multiline-quoted-field",
        "fixture": "requirements.csv",
        "asks": "Extract scope from this requirements file.",
        "must_hold": [
            "the R1 quote reads as one sentence, not 'signature\\nand a photograph' welded together",
            "R2 is cited at its real line number, not shifted by R1's embedded newline"
        ]
    },
    {
        "id": "non-english-source",
        "fixture": "vymohy-uk.md",
        "asks": "Extract scope from this document.",
        "must_hold": [
            "every citation carries quote_original in Ukrainian alongside the translation",
            "the payments feature is tagged sensitive",
            "section 5 (комерційні умови) is in not_scope, not a feature"
        ]
    },
    {
        "id": "contradicting-sources",
        "fixture": [
            "sow-excerpt.txt",
            "discovery-call.md"
        ],
        "asks": "Extract scope. The SOW is the contractual document.",
        "must_hold": [
            "the PCI disagreement appears in conflicts and is NOT silently resolved",
            "the dispatcher Monday cycle is surfaced — it is the stated core problem and the SOW does not cover it",
            "anything not traceable to the SOW carries scope_status outside_agreed_scope",
            "the predictive routing remark is commitment: speculative, not committed",
            "section 9 commercial terms are in not_scope"
        ]
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
            "offline operation is tagged low compressibility and novel"
        ]
    },
    {
        "id": "unreadable-sources",
        "fixture": [
            "wireframes.sketch",
            "scanned-contract.pdf"
        ],
        "asks": "Extract scope from these files.",
        "must_hold": [
            "both are listed in sources with a coverage_note saying they could not be read",
            "neither is silently omitted from the inventory",
            "inventory-check --manifest reports nothing missing, because both were listed"
        ]
    },
    {
        "id": "delivery-structure",
        "fixture": "sizing-backlog.xlsx",
        "asks": "Extract scope from this workbook.",
        "must_hold": [
            "every story carries an epic_id and the inventory declares the matching epics — grouping is not optional, because planning is priced per epic and every projection is laid out by epic",
            "every epic carries a sequence running 1..N with no gaps and a sequence_why naming what it must follow or what waits on it",
            "the foundation epic — repository, shared configuration, data model, auth skeleton — is sequenced before the epics whose stories depend on it, and no epic is sequenced before something it depends on",
            "an epic grouping the workbook did not itself make is marked origin 'synthesised' with a why naming what it was grouped on",
            "standing_scope carries one entry per catalogue item printed by `inventory-check.py --standing`, each with applies and a why — including the items this project does NOT pay, because a decline recorded with its reason is what tells a reader the item was considered",
            "where an extracted story already covers a catalogue item, that item is declined with the story named in covered_by, rather than claimed alongside it",
            "inventory-check.py returns no sequence findings and no standing_scope findings"
        ],
        "note": "Added with the delivery-structure change. The first four assertions are about ordering, which inventory-check.py validates against the dependency graph rather than accepting on trust; the last three are about foundation work, which the extraction now selects and the cost model still prices."
    }
]


def main():
    ap = argparse.ArgumentParser(description="Generate the adversarial fixture corpus.")
    ap.add_argument("--out", default="evals/fixtures", help="directory to write fixtures into")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for build in (banner_workbook, sizing_workbook, multiline_csv, non_english_source,
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
