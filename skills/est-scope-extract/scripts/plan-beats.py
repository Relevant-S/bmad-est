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

    uv run plan-beats.py <normalized-dir> --manifest <manifest.json> -o <workspace>/beats.json

Exit 0 with a plan, 2 on unreadable input.
"""

import argparse
import json
import re
import sys
from pathlib import Path

SHEET = re.compile(r"^## sheet:\s*(.+?)\s*$")
ROW = re.compile(r"^\|\s*(\d+)\s*\|")
HEADING = re.compile(r"^(#{1,3})\s+(.+?)\s*$")

# A sheet whose first column carries a value on more than this share of its rows is not
# grouped by that column — it is a catalogue, and the playbook prices it as one story.
DENSE_SHARE = 0.8
# Below this many rows a sheet is one beat whatever its shape; splitting it buys nothing and
# costs the reader the context of its neighbours.
MIN_ROWS_TO_SPLIT = 12
# A group larger than this is windowed anyway — the point of the exercise is a readable unit.
MAX_ROWS_PER_BEAT = 60


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


def prose_beats(lines):
    marks = [(i, m.group(2)) for i, line in enumerate(lines) if (m := HEADING.match(line))]
    if len(marks) < 2:
        return [("whole document", (0, len(lines) - 1), "no headings to cut on")]
    out = []
    for (start, title), (nxt, _) in zip(marks, marks[1:] + [(len(lines), None)]):
        out.append((title, (start, nxt - 1), "one heading section"))
    return out


def plan(normalized_dir, manifest):
    sources = {s.get("id"): s for s in (manifest or {}).get("sources", [])}
    beats, notes = [], []
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
    return beats, notes


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
        beats, notes = plan(args.normalized, manifest)
    except OSError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 2

    result = {
        "ok": True,
        "normalized": args.normalized,
        "beats": beats,
        "notes": notes,
        "summary": {
            "beats": len(beats),
            "units": sum(b["units"] for b in beats),
            "largest": max((b["units"] for b in beats), default=0),
            "why": ("Each beat is a contiguous line range, so a citation written inside one "
                    "anchors exactly as it would have in a single pass over the whole file."),
        },
    }
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
        print(json.dumps({"ok": True, "written": args.output} | result["summary"], indent=2))
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
