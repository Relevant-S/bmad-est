#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Recover the delivered shape of a BMad project, so one finished project can calibrate.

The calibrator's evidence path needs a ledger entry: an estimate, priced under a recorded
model, with actuals attached. A project delivered before the module existed has no estimate,
so it cannot enter that path at all — which leaves editing the cost model by hand, and a
hand-edit writes no `calibration_history`, so the model goes on calling itself uncalibrated
while its coefficients say otherwise. That happened, and the estimate it produced contradicted
its own snapshot two screens down.

This script closes that door by recovering what a project actually delivered — its epics, its
stories, their status — and emitting a skeleton inventory. It does not classify: size band,
compressibility, review tier and clarity are judgements about work, and a script that guessed
them would be manufacturing the evidence the calibration is supposed to weigh. Every tag comes
back `null` for the agent to fill in against the story files, which are still on disk.

    uv run scripts/anchor-project.py <project-dir> [--epics 1-9] [--status done] -o skeleton.json

Exit 0 when stories were found, 1 when the layout yielded none, 2 on unreadable input.
"""

import argparse
import json
import re
import sys
from pathlib import Path

EPIC_RE = re.compile(r"^#{1,3}\s+Epic\s+(?P<num>[0-9]+(?:\.[0-9]+)?)\s*[:.]\s*(?P<name>.+?)\s*$", re.M)
STORY_RE = re.compile(r"^#{1,4}\s+Story\s+(?P<num>[0-9]+(?:\.[0-9]+)+[a-z]?)\s*[:.]\s*(?P<name>.+?)\s*$", re.M)
# Only the leading word matters. Real story files carry things like
# "Status: done  <!-- code-reviewed 2026-08-08 -->" and "Status: done (AC1 deferred)", and an
# anchored match drops those stories silently — which understates the delivered scope the
# calibration is being anchored on, in the direction that makes the model look better.
STATUS_RE = re.compile(r"^Status:\s*(?P<status>[A-Za-z][A-Za-z-]*)", re.M)
STORY_FILE_RE = re.compile(r"^(?P<num>[0-9]+)-(?P<seq>[0-9]+[a-z]?)-(?P<slug>.+)\.md$")
TASK_RE = re.compile(r"^#{2,4}\s+Task\s+[0-9]+", re.M)


def epic_of(story_number):
    return story_number.split(".")[0]


def read_epics(root):
    """Epics and stories as the planning artefacts declared them.

    The planning documents are authoritative on what the project set out to do, in a way the
    implementation folder is not: a story that was folded into another leaves a file behind.
    """
    epics, stories, seen = {}, {}, []
    # Superseded and template copies describe work that was re-planned or never planned at
    # all; counting their stories would anchor the calibration on scope nobody delivered.
    ignore = {"node_modules", ".git", "superseded", "templates", "archive"}
    for path in sorted(root.rglob("epics*.md")):
        if ignore & set(path.parts) or "template" in path.name:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        seen.append(str(path.relative_to(root)))
        for m in EPIC_RE.finditer(text):
            epics.setdefault(m.group("num"), {"id": f"E{m.group('num')}",
                                              "name": m.group("name").strip(),
                                              "origin": "source",
                                              "why": f"declared in {path.name}"})
        for m in STORY_RE.finditer(text):
            num = m.group("num")
            stories.setdefault(num, {"number": num, "name": m.group("name").strip(),
                                     "epic": epic_of(num), "status": None, "tasks": 0,
                                     "file": None, "declared_in": path.name})
    return epics, stories, seen


def read_story_files(root, stories):
    """Delivered status and task count, from the implementation artefacts."""
    found = []
    ignore = {"node_modules", ".git", "superseded", "templates", "archive"}
    for path in sorted(root.rglob("*.md")):
        if ignore & set(path.parts):
            continue
        m = STORY_FILE_RE.match(path.name)
        if not m:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        title = STORY_RE.search(text)
        num = title.group("num") if title else f"{m.group('num')}.{m.group('seq')}"
        status = STATUS_RE.search(text)
        entry = stories.setdefault(num, {"number": num, "name": m.group("slug").replace("-", " "),
                                         "epic": epic_of(num), "status": None, "tasks": 0,
                                         "file": None, "declared_in": None})
        entry["status"] = status.group("status").strip().lower() if status else entry["status"]
        entry["tasks"] = len(TASK_RE.findall(text))
        entry["file"] = str(path.relative_to(root))
        found.append(num)
    return found


def parse_range(spec):
    """'1-9', '1,2,5', '1-3,7' → the set of epic numbers to keep."""
    if not spec:
        return None
    keep = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            keep.update(str(n) for n in range(int(lo), int(hi) + 1))
        elif part:
            keep.add(part)
    return keep


def skeleton(project, epics, stories):
    """A feature inventory with the shape filled in and every judgement left blank.

    The tags are null on purpose. A calibration anchored on one project is fragile enough
    without the classification being invented by the same run that consumes it.
    """
    axes = ("size_band", "compressibility", "review_tier", "clarity", "novelty")
    features = []
    for story in stories:
        features.append({
            "id": f"S{story['number'].replace('.', '-')}",
            "name": story["name"],
            "description": f"Delivered story {story['number']} of {project}.",
            "epic_id": f"E{story['epic']}",
            "surfaces": None,
            "citations": [{
                "source_id": "S1",
                "location": story["file"] or story["declared_in"] or "planning artefacts",
                "quote": f"Story {story['number']}: {story['name']}",
            }],
            "commitment": "committed",
            "tags": {axis: {"value": None, "why": None, "status": "unclassified"} for axis in axes},
            "tasks_recorded": story["tasks"],
            "depends_on": [],
            "open_questions": [],
        })
    return {
        "schema_version": "1.0",
        "generated": None,
        "project": project,
        "granularity": "project",
        "working_language": "en",
        "sources": [{"id": "S1", "path": str(project), "doc_type": "backlog", "language": "en",
                     "coverage_note": "Delivered BMad project, read from its own planning and "
                                      "implementation artefacts rather than from a client document."}],
        "features": features,
        "epics": [epics[n] for n in sorted(epics, key=lambda x: [int(p) for p in x.split(".")])
                  if any(f["epic_id"] == f"E{n}" for f in features)],
        "not_scope": [],
        "conflicts": [],
        "assumptions": [
            "Reconstructed from a delivered project, not extracted from a client document. "
            "Every classification is unset and must be tagged against the story files before pricing.",
        ],
        "completeness_signals": {},
    }


def main():
    ap = argparse.ArgumentParser(
        description="Recover a delivered BMad project's shape as a skeleton inventory.",
        epilog="Exit codes: 0 stories found, 1 none found, 2 unreadable input.",
    )
    ap.add_argument("project", help="root of the delivered BMad project")
    ap.add_argument("-o", "--output", help="write the skeleton here instead of stdout")
    ap.add_argument("--epics", help="restrict to these epic numbers, e.g. '1-9' or '1,2,5'")
    ap.add_argument("--status", default="done",
                    help="story status to count as delivered; 'any' keeps every story (default: done)")
    args = ap.parse_args()

    root = Path(args.project).expanduser()
    if not root.is_dir():
        print(json.dumps({"ok": False, "error": f"{root} is not a directory"}, indent=2))
        return 2

    epics, stories, epic_files = read_epics(root)
    read_story_files(root, stories)

    keep = parse_range(args.epics)
    selected, skipped = [], {"epic_filter": 0, "status": 0}
    for story in sorted(stories.values(), key=lambda s: [int(p) for p in re.findall(r"\d+", s["number"])]):
        if keep is not None and story["epic"] not in keep:
            skipped["epic_filter"] += 1
            continue
        if args.status != "any" and (story["status"] or "") != args.status:
            skipped["status"] += 1
            continue
        selected.append(story)

    if not selected:
        print(json.dumps({
            "ok": False,
            "error": ("no delivered stories found. Looked for 'Epic N:' and 'Story N.M:' headings in "
                      "epics*.md and for story files named '<epic>-<seq>-<slug>.md'. Check the path, "
                      "or pass --status any if this project does not record a Status line."),
            "epics_files_read": epic_files,
            "stories_seen": len(stories),
            "skipped": skipped,
        }, indent=2))
        return 1

    result = {
        "ok": True,
        "project": root.name,
        "shape": {
            "epics": len({s["epic"] for s in selected}),
            "stories": len(selected),
            "tasks_recorded": sum(s["tasks"] for s in selected),
            "stories_with_a_file": sum(1 for s in selected if s["file"]),
        },
        "skipped": skipped,
        "epics_files_read": epic_files,
        "skeleton": skeleton(root.name, epics, selected),
        "next": ("Tag every feature against its story file — the tags are null and pricing will "
                 "refuse them — then price with est-estimate, record the ledger entry, and attach "
                 "the project's real hours with ingest-actuals.py."),
    }
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
        print(json.dumps({k: v for k, v in result.items() if k != "skeleton"}, indent=2))
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
