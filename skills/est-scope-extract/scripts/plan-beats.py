#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Cut normalized sources into beats — the units of parallel extraction.

One real input was a single 426 KB workbook: 940 rows over six sheets, ~79k words, read in one
pass against ten thousand words of instruction. That pass produced 795 features sharing 53
justifications between them, one of which was repeated 336 times. Splitting the reading is what
fixes that, and the split has to be a script: a partition an agent chooses each run is a
partition nobody can reproduce, resume, or check the citations of.

The cut follows the source's own structure rather than a word count, because the grouping a
domain expert already did is better than any this could invent:

- **A grouping column** — the sparse-filled column A that `source-type-playbook.md` calls the
  epic: a value on the first row of a group, blank beneath. One beat per group.
- **A dense first column** — a value on every row is not a grouping column, it is data. That is
  the catalogue-tab shape (sixty workspace-health checks, fifty notification events), which the
  playbook says is *one* story sized for the count. One beat for the sheet, kept whole.
- **No usable column** — fixed row windows, so a wide sheet still splits.
- **Prose** — heading sections, then windows.

Every beat is a contiguous line range, so a citation written inside one anchors exactly as it
would have in a single pass. Nothing here reads meaning: it reads structure and hands the
meaning to whoever works the beat.

AND EVERY LINE IS IN EXACTLY ONE BEAT. That is the property that makes the partition
reproducible rather than merely repeatable, and it is checked rather than assumed. A 6,233-line
PRD once produced two beats covering 159 lines — 2.6% — because two table header rows starting
with a `#` were read as headings and everything before the first of them was silently dropped.
Extraction reads beats, so the other 97.4% was never read; every story came back citing one
line, and the estimate built on it came out at roughly twice what the same documents produced
on a run that had partitioned them by hand.

    uv run plan-beats.py <normalized-dir> --manifest <manifest.json> -o <workspace>/beats.json

Exit 0 with a plan, 1 when a source is not covered, 2 on unreadable input.
"""

import argparse
import json
import re
import sys
from pathlib import Path

SHEET = re.compile(r"^## sheet:\s*(.+?)\s*$")
ROW = re.compile(r"^\|\s*(\d+)\s*\|")
HEADING = re.compile(r"^(#{1,3}) (\S.*?)\s*$")
# Three or more consecutive spaces inside a title mean columns, not prose. This is what tells a
# converted table header apart from a heading; see `is_heading`.
COLUMNAR = re.compile(r"\S {3,}\S")

# A sheet whose first column carries a value on more than this share of its rows is not
# grouped by that column — it is a catalogue, and the playbook prices it as one story.
DENSE_SHARE = 0.8
# Below this many rows a sheet is one beat whatever its shape; splitting it buys nothing and
# costs the reader the context of its neighbours.
MIN_ROWS_TO_SPLIT = 12
# A group larger than this is windowed anyway — the point of the exercise is a readable unit.
MAX_ROWS_PER_BEAT = 60
# The same idea for prose. A heading section longer than this is windowed; a whole document with
# no headings at all is windowed from the start rather than handed over as one unreadable beat.
MAX_PROSE_LINES_PER_BEAT = 400
# Below this share of a source's lines placed in beats, the partition is not a partition and the
# plan is refused. Set high deliberately: the failure it exists to catch covered 2.6%, and a
# partition that leaves a tenth of a source unread is already one nobody should extract from.
MIN_COVERAGE = 0.995


def cells(line):
    parts = [p.strip() for p in line.split("|")]
    return parts[1:-1] if len(parts) >= 3 else []


def sheet_blocks(lines):
    """(sheet_name, [(line_no, row_no, first_cell)]) for each `## sheet:` block."""
    blocks, name, rows = [], None, []
    for i, line in enumerate(lines):
        match = SHEET.match(line)
        if match:
            if name is not None:
                blocks.append((name, rows))
            name, rows = match.group(1), []
            continue
        row = ROW.match(line)
        if row and name is not None:
            cell = cells(line)
            rows.append((i, int(row.group(1)), (cell[1] if len(cell) > 1 else "").strip()))
    if name is not None:
        blocks.append((name, rows))
    return blocks


def window(rows, size=MAX_ROWS_PER_BEAT):
    for start in range(0, len(rows), size):
        yield rows[start:start + size]


def beats_for_sheet(name, rows):
    """One beat per group where the first column groups; one for the sheet where it does not."""
    if len(rows) < MIN_ROWS_TO_SPLIT:
        return [(name, rows, "sheet is small enough to read whole")]

    labelled = [r for r in rows if r[2]]
    share = len(labelled) / len(rows)
    if share >= DENSE_SHARE:
        return [(name, rows, f"first column carries a value on {share:.0%} of rows — a catalogue, "
                             f"not a grouping column; the playbook prices it as one story")]
    if not labelled:
        return [(name, chunk, "no grouping column; fixed row window")
                for chunk in window(rows)]

    groups, current, label = [], [], None
    for row in rows:
        if row[2]:
            if current:
                groups.append((label, current))
            label, current = row[2], [row]
        else:
            current.append(row)
    if current:
        groups.append((label, current))

    out = []
    for label, group in groups:
        clean = " ".join((label or "unlabelled").replace("<br>", " ").split())
        if len(group) <= MAX_ROWS_PER_BEAT:
            out.append((f"{name} · {clean}", group, "one group of the sheet's own grouping column"))
        else:
            for chunk in window(group):
                out.append((f"{name} · {clean}", chunk,
                            f"a {len(group)}-row group, windowed to stay readable"))
    return out


def is_heading(line):
    """A markdown heading, and not a table row that happens to start with a hash.

    A 6,233-line PRD converted from PDF contained exactly two lines matching `^#{1,3}\\s+`:

        #    RISK                 IMPACT           LIKELIHOOD   MITIGATION
        #     ASSUMPTION                           IMPLICATION IF WRONG

    Both are table header rows whose first cell is a `#` column marker. Two marks cleared the
    `len(marks) < 2` fallback, the document was cut into those two sections, and 97.4% of it
    was never placed in a beat at all. The extraction that followed cited one line per story,
    the classifier sized a whole product against those single lines, and the estimate came out
    at roughly twice what the same documents produced on a run that partitioned them by hand.

    So a heading has to look like one: a single space after the hashes, and a title that is not
    a row of columns. Columns announce themselves by runs of whitespace — real heading text does
    not contain three spaces in a row.
    """
    match = HEADING.match(line)
    if not match:
        return None
    title = match.group(2)
    if COLUMNAR.search(title):
        return None
    return title


def prose_beats(lines, size=MAX_PROSE_LINES_PER_BEAT):
    """Heading sections, then windows — and every line lands in exactly one beat.

    Two things here are load-bearing and neither was true before. The region BEFORE the first
    heading is a beat: `zip(marks, marks[1:])` starts at the first mark, so a document's whole
    front matter used to be unreachable even when its headings were real. And a section longer
    than a readable unit is windowed, which the module's own docstring has always promised and
    which was never implemented — one 4,000-line section was one beat.
    """
    marks = [(i, title) for i, line in enumerate(lines) if (title := is_heading(line))]
    if not marks:
        sections = [(None, 0, len(lines) - 1, "no headings to cut on")]
    else:
        sections = []
        if marks[0][0] > 0:
            sections.append(("front matter", 0, marks[0][0] - 1,
                             "the region before the first heading, which no heading covers"))
        for (start, title), (nxt, _) in zip(marks, marks[1:] + [(len(lines), None)]):
            sections.append((title, start, nxt - 1, "one heading section"))

    def name(title, lo, hi, windowed):
        """A title a subagent can orient by.

        A heading keeps its own name; it is the name the document gave it and a reader can find
        it. Only a window needs the line range appended, because sixteen beats all called
        "whole document" tell nobody which part of it is theirs — and an untitled window takes
        the first line of real text inside it as a hint.
        """
        if title:
            return f"{title} · lines {lo + 1}-{hi + 1}" if windowed else title
        head = next((l.strip() for l in lines[lo:hi + 1] if l.strip()), "")
        head = " ".join(head.lstrip("#|* ").split())[:60]
        return f"lines {lo + 1}-{hi + 1}" + (f" · {head}" if head else "")

    out = []
    for title, lo, hi, why in sections:
        if hi < lo:
            continue
        span = hi - lo + 1
        if span <= size:
            out.append((name(title, lo, hi, False), (lo, hi), why))
            continue
        for chunk in window(list(range(lo, hi + 1)), size):
            out.append((name(title, chunk[0], chunk[-1], True), (chunk[0], chunk[-1]),
                        f"{why}, windowed at {size} lines to stay readable ({span} in total)"))
    return out


def coverage_of(cuts, total):
    """Which lines of a source no beat covers.

    Reported rather than assumed, because the whole failure this function exists to catch was
    invisible: `beats.json` said 2 beats and 159 units over a 6,233-line file, and nothing
    compared those numbers to each other.
    """
    seen = set()
    for _, (lo, hi), *_ in cuts:
        seen |= set(range(lo, hi + 1))
    missing = sorted(set(range(total)) - seen)
    gaps, run = [], []
    for i in missing:
        if run and i == run[-1] + 1:
            run.append(i)
        else:
            if run:
                gaps.append([run[0] + 1, run[-1] + 1])
            run = [i]
    if run:
        gaps.append([run[0] + 1, run[-1] + 1])
    return len(seen), gaps


def plan(normalized_dir, manifest):
    sources = {s.get("id"): s for s in (manifest or {}).get("sources", [])}
    beats, notes, coverage = [], [], []
    for path in sorted(Path(normalized_dir).glob("*.md")):
        source_id = path.name.split("-", 1)[0]
        if source_id not in sources:
            notes.append(f"{path.name}: not in the manifest — reading it anyway, as source {source_id}")
        lines = path.read_text(encoding="utf-8").splitlines()
        blocks = sheet_blocks(lines)

        cuts = []
        if blocks:
            for name, rows in blocks:
                if not rows:
                    notes.append(f"{source_id} sheet '{name}': no data rows")
                    continue
                # The sheet's first row is held out of the grouping and handed to every beat
                # instead. It is usually the column names, and a beat that cannot see them is
                # reading unlabelled cells — but it is also not a unit of work of its own.
                header, body = rows[0], rows[1:]
                if not body:
                    header, body = None, rows
                for title, group, why in beats_for_sheet(name, body):
                    cuts.append((title, (group[0][0], group[-1][0]),
                                 (group[0][1], group[-1][1]), len(group), why,
                                 header[1] if header else None))
        else:
            for title, (lo, hi), why in prose_beats(lines):
                cuts.append((title, (lo, hi), None, hi - lo + 1, why, None))

        # A spreadsheet's beats cover its data rows, not its blank lines and sheet markers, so
        # coverage is measured against the lines a partition could reach: every line for prose,
        # every data row for a workbook. Measuring a sheet against its raw line count would
        # report a false gap on every file and teach a reader to ignore the number.
        # A sheet's first row is held out of the grouping and handed to EVERY beat instead
        # (see below), so it is read by all of them rather than by none. Counting it unplaced
        # reported a false 97.2% on a workbook whose every data row was covered, which is
        # exactly the kind of number that teaches a reader to ignore this check.
        headers = sum(1 for _, rows in blocks if len(rows) > 1)
        reachable = len(lines) if not blocks else sum(len(rows) for _, rows in blocks)
        placed, gaps = coverage_of(cuts, len(lines))
        if blocks:
            placed = min(placed + headers, reachable)
        share = (placed / reachable) if reachable else 1.0
        coverage.append({"source_id": source_id, "path": str(path),
                         "lines": len(lines), "reachable": reachable, "placed": placed,
                         "share": round(share, 4),
                         "unplaced_line_ranges": gaps[:20] if not blocks else []})
        if share < MIN_COVERAGE:
            notes.append(
                f"{source_id}: the beats cover {share:.1%} of {reachable} reachable lines. "
                f"Extraction reads beats, so whatever is outside them is not read at all — "
                f"this is not a partition and the plan is refused.")

        for n, (title, (lo, hi), rows, count, why, header) in enumerate(cuts, 1):
            beats.append({
                "beat_id": f"{source_id}-b{n:02d}",
                "source_id": source_id,
                "path": str(path),
                "title": title,
                "lines": [lo + 1, hi + 1],
                "rows": list(rows) if rows else None,
                "header_row": header,
                "units": count,
                "why": why,
            })
    return beats, notes, coverage


def main():
    ap = argparse.ArgumentParser(
        description="Cut normalized sources into beats — the units of parallel extraction.",
        epilog="Exit codes: 0 plan written, 2 unreadable input.",
    )
    ap.add_argument("normalized", help="the workspace's normalized/ directory")
    ap.add_argument("--manifest", help="normalized/manifest.json, to name the sources")
    ap.add_argument("-o", "--output", help="write beats.json here instead of stdout")
    args = ap.parse_args()

    manifest = None
    if args.manifest:
        try:
            manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(json.dumps({"ok": False, "error": f"cannot read manifest: {exc}"}, indent=2))
            return 2
    try:
        beats, notes, coverage = plan(args.normalized, manifest)
    except OSError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 2

    short = [c for c in coverage if c["share"] < MIN_COVERAGE]
    result = {
        "ok": not short,
        "normalized": args.normalized,
        "beats": beats,
        "notes": notes,
        "coverage": coverage,
        "summary": {
            "beats": len(beats),
            "units": sum(b["units"] for b in beats),
            "largest": max((b["units"] for b in beats), default=0),
            "coverage": (min((c["share"] for c in coverage), default=1.0)),
            "sources_short_of_coverage": [c["source_id"] for c in short],
            "why": ("Each beat is a contiguous line range, so a citation written inside one "
                    "anchors exactly as it would have in a single pass over the whole file — "
                    "and every line of every source is inside one, which is the property that "
                    "makes the partition reproducible rather than merely repeatable."),
        },
    }
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
        print(json.dumps({"ok": result["ok"], "written": args.output} | result["summary"],
                         indent=2))
    else:
        print(text)
    # Exit 1 rather than 0 on a partition that does not cover its sources. The caller is an
    # agent about to fan subagents out over these beats; anything outside them is never read,
    # and a run that proceeds on a 2.6% partition produces an inventory whose evidence cannot
    # support any band it carries.
    if short:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
