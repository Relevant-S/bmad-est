#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["openpyxl>=3.1"]
# ///
"""Project plan.json into the documents a person reads: markdown, and Gantt tabs.

The workbook is EXTENDED, never replaced. `est-estimate` already wrote `estimate.xlsx` with
its Stories and Tasks tabs and the hyperlinks between them; this opens that file and appends
sheets to it, so a client has one workbook rather than two that have to be read side by side.
It deliberately does not touch `render-inventory.py:write_workbook`, which est-scope-extract
and est-estimate share — putting a Gantt concern inside a function two other skills call would
make a scheduling bug their problem too.

The Gantt is a CELL GRID, not a chart object. Readability is the requirement, and a grid
prints, survives a copy-paste into a deck, collapses by outline level, and can carry a
hyperlink on every row — none of which an embedded chart does. One column per week, labelled
W1..Wn, because this module's plans carry no dates.

    uv run scripts/render-plan.py <plan.json> --workbook estimate.xlsx [-o plan.md]
"""

import argparse
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BRAND = HERE.parent.parent / "est-estimate" / "scripts" / "brand.py"

ROLE_ORDER = ("ba", "ux", "architect", "dev", "qa", "devops")
ROLE_LABEL = {"ba": "BA", "ux": "UX", "dev": "Dev", "qa": "QA",
              "devops": "DevOps", "architect": "Architect"}


def brand_module():
    spec = importlib.util.spec_from_file_location("brand", BRAND)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def link_label(value):
    """The text a hyperlink shows, for the `display` attribute — see est-scope-extract's
    render-inventory.link_label for why it is needed and why the 255-character cap is there.

    Deliberately duplicated rather than imported: the two skills install independently, and a
    cross-skill import for three lines would make this one unable to run without the other.
    """
    text = "" if value is None else str(value)
    return text[:252] + "..." if len(text) > 255 else text


# --- markdown ----------------------------------------------------------------

def markdown(plan):
    """Every option, its hours, its score and its risks — the recommendation last, explained.

    Options are presented complete. A schedule without its cost is half an answer, and the
    module's rule is that the reader compares plan-and-cost pairs rather than calendars.
    """
    out = [f"# Delivery options — {plan.get('project') or 'untitled'}", "",
           "Each option below is a complete plan **and its own estimate**. The same scope "
           "sequenced and staffed differently costs differently: the architect is priced as "
           "setup plus a weekly presence, and ceremony is priced per person per week, so a "
           "longer plan genuinely costs more and a leaner one genuinely costs less. Story "
           "hours never move.", "",
           "**Weeks are relative.** Week 1 is whenever this starts. This plan carries no dates.",
           ""]

    roster = plan["inputs"].get("roster") or {}
    out += ["## Team", "",
            ("Headcount is an output here, not a constraint — the sweep explores team shapes "
             "and every addition below is justified or refused against the backlog's own "
             "dependency graph."), ""]
    if roster:
        out += [f"You supplied: {', '.join(f'{n}x {ROLE_LABEL.get(r, r)}' for r, n in sorted(roster.items()))}. "
                "Treated as a starting point, not a ceiling.", ""]
    for row in plan["staffing"].get("oversized_roster") or []:
        out += [f"> **The roster is larger than this backlog can occupy.** {row['note']} "
                f"On this scope {row['sustainable_count']} would be busy.", ""]

    allowed = [d for d in plan["staffing"]["decisions"] if d["allowed"]]
    refused = [d for d in plan["staffing"]["decisions"] if not d["allowed"]]
    if allowed:
        out += ["**Additions this backlog justifies**", ""]
        for d in allowed:
            for line in d["justification"]:
                out.append(f"- {line}" if not line.startswith("  ") else f"  - {line.strip()}")
        out.append("")
    if refused:
        out += ["**Additions it refuses**", ""]
        for d in refused:
            out.append(f"- **{ROLE_LABEL.get(d['role'], d['role'])} → {d['count']}.** "
                       + " ".join(d["refusals"]))
        out.append("")

    order = plan.get("build_order") or {}
    if order.get("epics"):
        out += ["## Build order", "",
                "What each epic stands on, and why. Every schedule below respects this — the "
                "same graph gates the calendar, so a bar cannot start before what it depends "
                "on, whatever the archetype.", "",
                order.get("how", ""), "",
                "| # | Epic | Waits for | Why |", "| ---: | --- | --- | --- |"]
        for row in order["epics"]:
            waits = row.get("waits_for") or []
            out.append(f"| {row.get('sequence')} | {row.get('name') or row['epic_id']} | "
                       + (", ".join(w["epic_id"] for w in waits) or "—") + " | "
                       + (waits[-1]["why"] if waits else "nothing precedes it") + " |")
        out.append("")
        for row in order.get("cycles_broken") or []:
            out += [f"> **{row['epic']} and {row['waits_on']} depend on each other.** "
                    f"{row['dropped']} The dropped edge was: {row['why']}.", ""]

    audit = plan.get("ordering_check") or {}
    if audit and not audit.get("ok"):
        out += ["> **This plan's calendar contradicts its own dependency graph.** "
                + f"{len(audit.get('findings') or [])} orderings are violated. "
                  "It is printed so it can be argued with, and it is not shippable.", ""]
        for finding in (audit.get("findings") or [])[:8]:
            out.append(f"> - {finding['detail']}")
        out.append("")

    multi = any(len(o.get("phases") or []) > 1 for o in plan["options"])
    out += ["## The options", ""]
    if multi:
        out += ["Phase 1 first, because a later phase is often a separate agreement and the "
                "number a client signs should not silently contain it. The whole-programme "
                "columns are what the option actually delivers, and the fit score is computed "
                "on them — every option holds the same scope, so scoring phase 1 alone would "
                "let an option win by pushing work across the boundary.", "",
                "| # | Option | P1 weeks | P1 h | Whole weeks | Whole h | Range | Fit |",
                "| --- | --- | ---: | ---: | ---: | ---: | --- | ---: |"]
    else:
        out += ["| # | Option | Weeks | Likely h | Range | Fit |",
                "| --- | --- | ---: | ---: | --- | ---: |"]
    for i, o in enumerate(plan["options"], start=1):
        t = o["estimate"]["total_hours"]
        mark = " ★" if o["id"] == plan.get("recommended") else ""
        flag = "" if o["feasibility"]["feasible"] else " ⚠ not deliverable"
        head = (f"| {i}{mark} | {o['archetype'].title()}, "
                f"{team_label(o['team_shape'])}{flag} | ")
        phases = o.get("phases") or []
        if multi:
            first = phases[0] if phases else None
            out.append(head
                       + (f"{first['finishes_week']:.1f} | {first['standalone_hours']:.0f} | "
                          if first else "— | — | ")
                       + f"{o['schedule']['weeks']:.1f} | {t['likely']:.0f} | "
                         f"{t['low']:.0f}–{t['high']:.0f} | {o['score']['fit']:.1f} |")
        else:
            out.append(head + f"{o['schedule']['weeks']:.1f} | {t['likely']:.0f} | "
                              f"{t['low']:.0f}–{t['high']:.0f} | {o['score']['fit']:.1f} |")
    out.append("")

    baseline = plan.get("baseline")
    if baseline is not None and not any(o["id"] == baseline["id"] for o in plan["options"]):
        # Only when the sweep never considered it, which means a supplied roster put its floor
        # above one person per role. It is printed as a reference, not offered as an option —
        # a roster is a floor, and proposing a smaller team than the one the user says they
        # have would be answering a question nobody asked.
        out += ["## The baseline", "",
                baseline["baseline_note"], ""]
        out += option_section(baseline, False)

    for o in plan["options"]:
        out += option_section(o, o["id"] == plan.get("recommended"))

    if plan.get("recommended"):
        best = next(o for o in plan["options"] if o["id"] == plan["recommended"])
        out += ["## Why this one", "",
                f"**{best['archetype'].title()}, {team_label(best['team_shape'])}** scores "
                f"{best['score']['fit']:.1f}. Every sub-score is printed above it; the weights "
                f"live in the cost model's `staffing.scoring` block, so anyone who weighs these "
                f"differently can re-run it and get their own answer rather than arguing with "
                f"this one.", ""]
    else:
        out += ["## No option is deliverable", "",
                "Every schedule considered failed its feasibility check. The failures are "
                "printed above; they are not presentational, and none of these plans should be "
                "shown to a client.", ""]
    return "\n".join(out) + "\n"


def team_label(shape):
    return ", ".join(f"{n}x {ROLE_LABEL.get(r, r)}" for r, n in sorted(shape.items()))


def phase_lead(o):
    """The headline, led by the FIRST phase rather than by the whole programme.

    A later phase is frequently a separate agreement, so a client being quoted an MVP should
    not be handed a span and a total that silently include work under a different contract.
    The whole-programme figure stays on the line beside it, labelled, because it is what the
    option actually contains.
    """
    phases = o.get("phases") or []
    t = o["estimate"]["total_hours"]
    whole = (f"{o['schedule']['weeks']:.1f} weeks, {t['likely']:.0f} h likely "
             f"({t['low']:.0f}–{t['high']:.0f})")
    fit = f"Fit {o['score']['fit']:.1f}/10."
    if len(phases) < 2:
        return f"**{whole}.** {fit}"
    first = phases[0]
    later = len(phases) - 1
    return (f"**Phase {first['phase']}: {first['finishes_week']:.1f} weeks, "
            f"{first['standalone_hours']:.0f} h on its own.** "
            f"Whole programme, including {later} later phase{'s' if later > 1 else ''}: "
            f"{whole}. {fit}")


def option_section(o, recommended):
    t = o["estimate"]["total_hours"]
    out = [f"### {o['archetype'].title()} — {team_label(o['team_shape'])}"
           + ("  ★ recommended" if recommended else ""), "",
           o["what_it_is"], "",
           phase_lead(o), "",
           "| Role | Low | Likely | High |", "| --- | ---: | ---: | ---: |"]
    for role in ROLE_ORDER:
        row = o["estimate"]["by_role"].get(role)
        if row:
            out.append(f"| {ROLE_LABEL.get(role, role)} | {row['low']:.0f} | "
                       f"{row['likely']:.0f} | {row['high']:.0f} |")
    phases = o.get("phases") or []
    if len(phases) > 1:
        out += ["", "**The phases.** A phase is a delivery commitment, not a dependency: "
                "nothing in a later phase is built until the earlier one closes, whether or not "
                "the graph requires it. Analysis may overlap — the next phase can be specified "
                "while this one builds — which is why a phase's window starts before the one "
                "before it ends.", "",
                "| Phase | Runs | On its own | Share of this programme | Why it is a phase |",
                "| ---: | --- | ---: | ---: | --- |"]
        for row in phases:
            out.append(f"| {row['phase']} | W{int(row['starts_week']) + 1}–"
                       f"W{max(1, -(-row['finishes_week'] // 1)):.0f} | "
                       f"{row['standalone_hours']:.0f} h | "
                       f"{row['apportioned_hours']:.0f} h | {row['basis']} |")
        out += ["", "*On its own* is what that phase costs if it is the only thing commissioned; "
                "*share of this programme* is its portion of the total above. The second is "
                "smaller because environments and most planning are paid once however many "
                "phases run — quote the first to anyone deciding whether to commission a phase.",
                ""]

    staggered = [p for p in o["schedule"]["team"] if p.get("join_week", 0.0) > 0.005]
    if staggered:
        out += ["", "**Who arrives when.** Nobody joins before their role has more ready work "
                "than the people already on it can clear — so the plan does not start four "
                "developers on the same Monday against a codebase that does not exist yet.", "",
                "| Person | Joins | First delivery | Hours | Occupied |",
                "| --- | ---: | ---: | ---: | ---: |"]
        for person in o["schedule"]["team"]:
            out.append(f"| {person['name']} | W{int(person.get('join_week', 0.0)) + 1} | "
                       f"W{int(person['starts_week']) + 1} | {person['delivered_hours']:.0f} | "
                       f"{person['utilisation']:.0%} |")
    out += ["", "| Sub-score | /10 | What it rests on |", "| --- | ---: | --- |"]
    for name, part in o["score"]["parts"].items():
        out.append(f"| {name.title()} | {part['score']:.1f} | {part['rests_on']} |")
    out += ["", "**Risks**", ""]
    for row in o["risks"]:
        out.append(f"- *{row['risk']}* — {row['mitigation']}")
    feas = o["feasibility"]
    out += ["", "**Deliverable?** " + ("Yes. " + "; ".join(feas["checks"]) + "."
                                       if feas["feasible"] else
                                       "**No.** " + " ".join(feas["failures"])), ""]
    return out


# --- the Gantt ---------------------------------------------------------------

def packets(person, weeks):
    """One row per person per EPIC, with the weeks that person is actually in that epic.

    The first version cut a row every time a run of work broke, which is what the schedule
    genuinely does — a developer dips in and out of four epics in a morning — and it produced
    a 381-row chart in which Epic 1 appeared four times under one name. Nobody reads that. One
    row per epic, with gaps shown as gaps, says the same thing in a tenth of the space and
    answers the question a reader actually has: when is this person on this epic.
    """
    rows = {}
    for item in person["items"]:
        # Planning and project setup belong to no epic. They are real work on the calendar and
        # naming them "unassigned" tells a reader nothing — worse, it reads as a mistake.
        key = item["epic_id"] or ("planning" if item["component"] == "planning"
                                  else "setup" if str(item["story_id"] or "").startswith("SW-")
                                  else "—")
        row = rows.setdefault(key, {"epic_id": key, "hours": 0.0,
                                    "stories": [], "occupied": set(),
                                    "by_component": {},
                                    "component": item["component"],
                                    "start_week": item["start_week"],
                                    "finish_week": item["finish_week"]})
        row["hours"] += item["hours"]
        row["by_component"][item["component"]] = (row["by_component"].get(item["component"], 0.0)
                                                  + item["hours"])
        # The component that OPENS the packet, which is the one the Starts column is showing.
        # Taking the biggest instead quoted a build gate beside an analyst's spec start — two
        # true statements about different moments, which reads as a contradiction.
        if item["start_week"] <= row["start_week"]:
            row["component"] = item["component"]
        if item["story_id"] and item["story_id"] not in row["stories"]:
            row["stories"].append(item["story_id"])
        row["start_week"] = min(row["start_week"], item["start_week"])
        row["finish_week"] = max(row["finish_week"], item["finish_week"])
        for w in span_weeks(item["start_week"], item["finish_week"], weeks):
            row.setdefault("load", {})
            row["load"][w] = row["load"].get(w, 0.0) + item["hours"]

    # ONE OWNING EPIC PER WEEK. A person can only do one thing at a time — `take()` guarantees
    # it — but the chart did not: each epic row painted every week it touched, so a developer
    # dipping between four epics inside week 3 appeared on all four rows for that week, and the
    # plan read as one person working four epics at once for the whole project. The week goes
    # to whichever epic holds most of that person's hours in it; the others leave it blank and
    # the reader can still see the run from the Starts/Ends columns.
    owner = {}
    for key, row in rows.items():
        for week, load in (row.get("load") or {}).items():
            if load > owner.get(week, (0.0, None))[0]:
                owner[week] = (load, key)
    for key, row in rows.items():
        row["occupied"] = {w for w, (_, holder) in owner.items() if holder == key}
    return sorted(rows.values(), key=lambda r: r["start_week"])


def span_weeks(start, finish, weeks):
    """The week columns a piece of work touches. Work shorter than a week still owns the week
    it happened in — an empty row reads as nothing scheduled, which would be a lie."""
    lo = max(0, int(start))
    hi = max(lo, min(weeks - 1, int(finish - 1e-9)))
    return set(range(lo, min(hi, weeks - 1) + 1))


def story_index(workbook):
    """id -> row on the Stories tab, so every Gantt row can link to the work it draws."""
    if "Stories" not in workbook.sheetnames:
        return {}
    sheet = workbook["Stories"]
    header = [c.value for c in sheet[1]]
    if "id" not in header:
        return {}
    column = header.index("id") + 1
    return {sheet.cell(row=r, column=column).value: r
            for r in range(2, sheet.max_row + 1)
            if sheet.cell(row=r, column=column).value}


def gates(plan, option):
    """Per epic: the epics it stands on and the week the last of them clears.

    So a reader can answer "why is this here" off the chart itself. The graph comes from
    `plan["build_order"]`, which plan.py wrote from the same `epic_predecessors` the scheduler
    was given — quoting a different graph on the chart from the one the calendar was built
    against is the failure this whole change exists to remove.
    """
    done = {"spec": {}, "build": {}}
    for person in option["schedule"]["team"]:
        for item in person["items"]:
            key, component = item.get("epic_id"), item.get("component")
            if key and component in done:
                done[component][key] = max(done[component].get(key, 0.0), item["finish_week"])
    out = {}
    for row in (plan.get("build_order") or {}).get("epics") or []:
        waits = [w["epic_id"] for w in row.get("waits_for") or []]
        if not waits:
            continue
        for component, table in done.items():
            clears = max((table[w] for w in waits if w in table), default=None)
            out[(row["epic_id"], component)] = (
                ", ".join(waits)
                + (f" (clears W{max(1, -(-clears // 1)):.0f})" if clears else ""))
    return out


def draw_gantt(workbook, option, epics, index, style, title=None, subtitle=None, waits=None):
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.hyperlink import Hyperlink

    title = (title or f"Gantt — {option['archetype'].title()}")[:31]
    if title in workbook.sheetnames:
        del workbook[title]
    sheet = workbook.create_sheet(title)
    sheet.sheet_view.showGridLines = False

    weeks = max(1, int(option["schedule"]["weeks"] + 0.999))
    labels = ["Who / what", "Hours", "Joins", "Starts", "Ends", "Waits for"]
    first_week = len(labels) + 1

    sheet.cell(row=1, column=1, value=f"{option['archetype'].title()} — "
                                     f"{team_label(option['team_shape'])}").font = style["band_font"]
    phases = option.get("phases") or []
    lead = ""
    if len(phases) > 1:
        lead = (f"Phase {phases[0]['phase']} closes W"
                f"{max(1, -(-phases[0]['finishes_week'] // 1)):.0f} at "
                f"{phases[0]['standalone_hours']:.0f} h on its own · whole programme ")
    sheet.cell(row=2, column=1,
               value=(lead + f"{option['schedule']['weeks']:.1f} weeks · "
                      f"{option['estimate']['total_hours']['likely']:.0f} h likely · "
                      f"fit {option['score']['fit']:.1f}/10 · weeks are relative, "
                      f"week 1 is whenever this starts")).font = style["muted_font"]
    if subtitle:
        sheet.cell(row=3, column=1, value=subtitle).font = style["muted_font"]

    head = 4
    for i, label in enumerate(labels, start=1):
        cell = sheet.cell(row=head, column=i, value=label)
        cell.fill, cell.font = style["header_fill"], style["header_font"]
    for w in range(weeks):
        cell = sheet.cell(row=head, column=first_week + w, value=f"W{w + 1}")
        cell.fill, cell.font, cell.alignment = (style["header_fill"], style["header_font"],
                                                style["centre"])

    # The phase boundary, named on the row above the grid. A phase is a delivery commitment —
    # often a separate contract — so a reader has to be able to see where one ends without
    # counting bars, and the plan drew Phase 2 inside Phase 1 for exactly as long as nothing
    # marked it.
    if len(phases) > 1:
        # Column 1 of this row belongs to the subtitle when there is one — the baseline chart
        # uses it — so the label only takes the cell if it is free. The markers themselves sit
        # in week columns and never collide with it.
        if not subtitle:
            sheet.cell(row=head - 1, column=1,
                       value="Phase boundaries").font = style["muted_font"]
        for row_ in phases[:-1]:
            at = first_week + min(weeks - 1, max(0, int(row_["finishes_week"])))
            cell = sheet.cell(row=head - 1, column=at,
                              value=f"end P{row_['phase']}")
            cell.font, cell.alignment = style["muted_font"], style["centre"]

    epic_name = {e.get("id"): e.get("name") for e in epics}
    row = head + 1
    for role in ROLE_ORDER:
        people = [p for p in option["schedule"]["team"] if p["role"] == role]
        if not people:
            continue
        cell = sheet.cell(row=row, column=1, value=ROLE_LABEL.get(role, role))
        cell.fill, cell.font = style["band_fill"], style["band_font"]
        hours = sum(p["delivered_hours"] for p in people)
        sheet.cell(row=row, column=2, value=round(hours, 1)).font = style["band_font"]
        for w in range(weeks):
            sheet.cell(row=row, column=first_week + w).fill = style["band_fill"]
        row += 1

        for person in people:
            sheet.row_dimensions[row].outlineLevel = 1
            note = "" if person["on_project"] else " (new)"
            join = person.get("join_week", 0.0)
            sheet.cell(row=row, column=1, value=f"  {person['name']}{note}").font = style["body_font"]
            sheet.cell(row=row, column=2, value=person["delivered_hours"]).font = style["body_font"]
            sheet.cell(row=row, column=3, value=f"W{int(join) + 1}").font = style["body_font"]
            sheet.cell(row=row, column=4, value=f"W{int(person['starts_week']) + 1}").font = style["body_font"]
            sheet.cell(row=row, column=5,
                       value=f"W{max(1, -(-person['finishes_week'] // 1)):.0f}").font = style["body_font"]
            # Three states, painted in the order they happen so each covers the one before:
            # not here yet, here but still arriving, delivering. People now join when the demand
            # in their role justifies them rather than all in week one, and a chart that showed
            # the weeks before someone arrived as blank would read as a plan paying them to wait.
            if join > 0:
                _paint(sheet, row, first_week, span_weeks(0.0, join, weeks), style["absent_fill"])
            ramp = person.get("ramp_until_week", 0.0)
            if ramp:
                _paint(sheet, row, first_week, span_weeks(join, ramp, weeks), style["idle_fill"])
            rows = packets(person, weeks)
            for pkt in rows:
                _paint(sheet, row, first_week, pkt["occupied"], style["role_fill"].get(role))
            row += 1

            for pkt in rows:
                sheet.row_dimensions[row].outlineLevel = 2
                sheet.row_dimensions[row].hidden = True
                key = pkt["epic_id"]
                name = epic_name.get(key) or {"planning": "Planning artefacts",
                                              "setup": "Project setup",
                                              "—": "Unassigned"}.get(key, key)
                n = len([s for s in pkt["stories"] if s])
                label = (f"{name} · {n} stor{'y' if n == 1 else 'ies'}" if n
                         else name)
                cell = sheet.cell(row=row, column=1, value=f"      {label}")
                at = index.get(pkt["stories"][0]) if pkt["stories"] else None
                if at:
                    # `display` is what Google Sheets shows. Without it the import turns this
                    # into a bare `=HYPERLINK("#gid=...&range=A77")` and the reader gets the
                    # address where the epic name should be. render-inventory.link_label carries
                    # the reasoning and the 255-character cap.
                    cell.hyperlink = Hyperlink(ref=cell.coordinate, location=f"Stories!A{at}",
                                               display=link_label(cell.value))
                    cell.font = style["link_font"]
                else:
                    cell.font = style["muted_font"]
                sheet.cell(row=row, column=2, value=round(pkt["hours"], 1)).font = style["muted_font"]
                sheet.cell(row=row, column=4, value=f"W{int(pkt['start_week']) + 1}").font = style["muted_font"]
                sheet.cell(row=row, column=5, value=f"W{max(1, -(-pkt['finish_week'] // 1)):.0f}").font = style["muted_font"]
                gate = (waits or {}).get((key, pkt.get("component")))
                if gate:
                    sheet.cell(row=row, column=6, value=gate).font = style["muted_font"]
                _paint(sheet, row, first_week, pkt["occupied"], style["role_fill"].get(role))
                row += 1

    # The two calendar-priced roles. Neither is on the team: the architect is `setup + a capped
    # weekly rate` so a second one cannot be priced, and overhead is ceremony charged per person
    # per week. Both are drawn from THIS option's own estimate and span the plan, because that
    # is exactly what they are — and leaving them off meant the chart accounted for about half
    # the hours the deal was being sold on, with the Architect band never drawn at all.
    for name, key in (("Architect", "architect"), ("Ceremony", "overhead")):
        component = (option["estimate"].get("project_components") or {}).get(key) or {}
        hours = component.get("hours") or 0.0
        if hours <= 0:
            continue
        cell = sheet.cell(row=row, column=1, value=name)
        cell.fill, cell.font = style["band_fill"], style["band_font"]
        sheet.cell(row=row, column=2, value=round(hours, 1)).font = style["band_font"]
        sheet.cell(row=row, column=4, value="W1").font = style["band_font"]
        sheet.cell(row=row, column=5, value=f"W{weeks}").font = style["band_font"]
        _paint(sheet, row, first_week, range(weeks), style["role_fill"].get(key)
               or style["band_fill"])
        row += 1
        sheet.row_dimensions[row].outlineLevel = 1
        sheet.cell(row=row, column=1, value=(
            f"  {'setup plus a capped weekly rate, across the plan' if key == 'architect' else 'ceremony, per person per week'}"
        )).font = style["muted_font"]
        row += 1

    # Reconciliation. The chart and the estimate are two views of one number and a reader is
    # entitled to check that they agree — three different dev figures once sat in one workbook
    # with nothing saying which was which.
    scheduled = sum(p["delivered_hours"] for p in option["schedule"]["team"])
    calendar_priced = sum((option["estimate"]["project_components"].get(k) or {}).get("hours", 0.0)
                          for k in ("architect", "overhead"))
    priced = sum(r["hours"] for r in option["estimate"]["by_role"].values())
    row += 1
    sheet.cell(row=row, column=1, value="Drawn above").font = style["band_font"]
    sheet.cell(row=row, column=2, value=round(scheduled + calendar_priced, 1)).font = style["band_font"]
    sheet.cell(row=row, column=first_week, value=(
        f"Scheduled {scheduled:.0f} h + architect and ceremony {calendar_priced:.0f} h "
        f"= {scheduled + calendar_priced:.0f} h, against {priced:.0f} h on the estimate "
        f"({(scheduled + calendar_priced) / priced:.0%}). Hours here are expected values (PERT "
        f"means); the Stories tab quotes the mode of each interval, which is a different and "
        f"slightly smaller figure.")).font = style["muted_font"]
    row += 1

    sheet.freeze_panes = sheet.cell(row=head + 1, column=first_week)
    sheet.column_dimensions["A"].width = 46
    for i in range(2, first_week):
        sheet.column_dimensions[get_column_letter(i)].width = 9
    for w in range(weeks):
        sheet.column_dimensions[get_column_letter(first_week + w)].width = 4.2
    sheet.sheet_properties.outlinePr.summaryBelow = False
    return sheet


def _paint(sheet, row, first_week, columns, fill):
    """Fill the given week columns on a row."""
    if fill is None:
        return
    for w in sorted(columns):
        sheet.cell(row=row, column=first_week + w).fill = fill


def draw_options(workbook, plan, style):
    """Every option side by side: the schedule, the score, and the role hours it costs."""
    title = "Options"
    if title in workbook.sheetnames:
        del workbook[title]
    sheet = workbook.create_sheet(title)
    sheet.sheet_view.showGridLines = False

    sheet.cell(row=1, column=1, value=f"Delivery options — {plan.get('project') or ''}"
               ).font = style["band_font"]
    sheet.cell(row=2, column=1, value=plan["estimate"]["why_it_differs"]).font = style["muted_font"]

    columns = (["Option", "Archetype", "Team", "Weeks", "Likely h", "Low", "High", "Fit",
                "Deliverable"] + [ROLE_LABEL.get(r, r) for r in ROLE_ORDER]
               + ["Drift h", "Utilisation"])
    head = 4
    for i, name in enumerate(columns, start=1):
        cell = sheet.cell(row=head, column=i, value=name)
        cell.fill, cell.font = style["header_fill"], style["header_font"]

    for n, o in enumerate(plan["options"], start=1):
        row = head + n
        t = o["estimate"]["total_hours"]
        util = [p["utilisation"] for p in o["schedule"]["team"]]
        values = ([("★ " if o["id"] == plan.get("recommended") else "") + o["id"],
                   o["archetype"], team_label(o["team_shape"]),
                   round(o["schedule"]["weeks"], 1), round(t["likely"]), round(t["low"]),
                   round(t["high"]), o["score"]["fit"],
                   "yes" if o["feasibility"]["feasible"] else "NO"]
                  + [round(o["estimate"]["by_role"].get(r, {}).get("hours", 0.0))
                     for r in ROLE_ORDER]
                  + [o["schedule"]["drift_hours"],
                     round(sum(util) / len(util), 2) if util else 0.0])
        for i, value in enumerate(values, start=1):
            cell = sheet.cell(row=row, column=i, value=value)
            cell.font = style["band_font"] if o["id"] == plan.get("recommended") else style["body_font"]
            cell.border = style["rule"]

    sheet.freeze_panes = f"A{head + 1}"
    sheet.column_dimensions["A"].width = 38
    sheet.column_dimensions["C"].width = 34
    from openpyxl.utils import get_column_letter
    for i in range(4, len(columns) + 1):
        sheet.column_dimensions[get_column_letter(i)].width = 11
    return sheet


def extend_workbook(plan, path, per="archetype"):
    """Append the Options tab and the Gantts to the estimate's own workbook."""
    try:
        from openpyxl import load_workbook
    except ImportError:
        return False, "openpyxl is not importable"
    path = Path(path)
    if not path.exists():
        return False, f"{path} does not exist — run est-estimate's render first"

    style = brand_module().xlsx()
    workbook = load_workbook(path)
    index = story_index(workbook)
    draw_options(workbook, plan, style)

    # One Gantt per SCHEDULE OFFERED, which is the best team shape for each archetype — not one
    # per row of the sweep. Nine near-identical charts is not a more readable document than
    # three, and readability is the requirement; the Options tab carries every row.
    #
    # The BASELINE comes first, always. Picking the best-fit shape of each archetype always
    # picks the largest team the sweep allowed — all three charts in one real workbook were
    # `2x BA, 4x Dev, 1x DevOps, 1x QA, 1x UX` — so the one-person-per-role reading, which is
    # what a reader calibrates every other option against, was the single schedule the workbook
    # did not contain.
    drawn = []
    if per == "option":
        chosen = list(plan["options"])
    else:
        chosen = []
        for name in ("sequential", "foundation", "pipelined"):
            same = [o for o in plan["options"] if o["archetype"] == name]
            if same:
                chosen.append(max(same, key=lambda o: o["score"]["fit"]))

    baseline = plan.get("baseline")
    if baseline is not None:
        best = next((o for o in plan["options"] if o["id"] == plan.get("recommended")), None)
        against = (f" Compare against {best['archetype'].title()}, {team_label(best['team_shape'])}: "
                   f"{best['schedule']['weeks']:.1f} weeks, "
                   f"{best['estimate']['total_hours']['likely']:.0f} h."
                   if best is not None and best["id"] != baseline["id"] else "")
        draw_gantt(workbook, baseline, plan.get("epics") or [], index, style,
                   title="Gantt — Baseline (1 each)",
                   subtitle=baseline.get("baseline_note", "") + against,
                   waits=gates(plan, baseline))
        drawn.append(baseline["id"] + " (baseline)")
        chosen = [o for o in chosen if o["id"] != baseline["id"]]

    for option in chosen:
        draw_gantt(workbook, option, plan.get("epics") or [], index, style,
                   waits=gates(plan, option))
        drawn.append(option["id"])
    workbook.save(path)
    return True, drawn


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("plan", help="path to plan.json")
    ap.add_argument("-o", "--output", help="write plan.md here (default: beside plan.json)")
    ap.add_argument("--workbook", help="estimate.xlsx to extend with the Gantt tabs")
    ap.add_argument("--gantt-per", choices=("archetype", "option"), default="archetype",
                    help="a Gantt for the best shape of each archetype (default) or for every option")
    ap.add_argument("--no-markdown", action="store_true")
    args = ap.parse_args()

    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    written, notes = [], []
    if not args.no_markdown:
        target = Path(args.output or Path(args.plan).with_name("plan.md"))
        target.write_text(markdown(plan), encoding="utf-8")
        written.append(str(target))
    if args.workbook:
        ok, result = extend_workbook(plan, args.workbook, args.gantt_per)
        if ok:
            written.append(str(args.workbook))
            notes.append(f"gantt tabs: {', '.join(result)}")
        else:
            notes.append(f"workbook skipped: {result}")
    print(json.dumps({"ok": True, "written": written, "notes": notes}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
