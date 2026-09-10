#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Validate a Feature Inventory and compute its input completeness score.

Two jobs, one pass over the file:

1. Validation — schema conformance plus the integrity rules a schema cannot express
   (dangling references, dependency cycles, missing original-language quotes, tag
   vocabulary). Every finding names the fix, so the model can self-correct before the
   inventory reaches est-estimate.

2. Scoring — the input completeness score, from the signals the model set plus two
   derived measures. The model sets signals; the score is computed here, because it
   determines estimate band width downstream and must not be something anyone chooses.

Weights are printed by --weights so the formula stays inspectable.
"""

import argparse
import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "assets" / "feature-inventory.schema.json"
# The classification's schema lives with the skill that writes it. Validated here because this is
# where the two halves are read together, and because the judgement half should not be the
# unchecked one — the inventory has a schema and the file that decides what everything costs
# should be held to the same bar.
CLASSIFICATION_SCHEMA_PATH = (Path(__file__).resolve().parent.parent.parent
                              / "est-estimate" / "assets" / "classification.schema.json")

# The bands are defined by the cost model, not by this script. Falling back to the shipped seed
# matters: extraction legitimately runs before a project has a model of its own, and a band table
# quoted from memory instead of read from the file is how the two drift apart.
SEED_MODEL_PATH = (Path(__file__).resolve().parent.parent.parent
                   / "est-estimate" / "assets" / "cost-model.seed.json")

TAG_VOCABULARY = {
    "size_band": ["XS", "S", "M", "L", "XL"],
    "compressibility": ["high", "medium", "low", "none"],
    "review_tier": ["routine", "sensitive", "critical"],
    "clarity": ["high", "medium", "low"],
    "novelty": ["standard", "novel"],
}

# Weights sum to 1.0. Raising one means lowering another; keep the sum exact.
SIGNAL_WEIGHTS = {
    "acceptance_criteria": 0.20,
    "clarity_quality": 0.18,      # derived from feature clarity tags
    "integrations_named": 0.13,
    "data_model_described": 0.12,
    "nfrs_stated": 0.12,
    "stack_specified": 0.10,
    "commitment_quality": 0.08,   # derived from feature commitment levels
    "ui_defined": 0.07,
}

# Keyed per signal rather than pooled: "partial" means something different for a stack than
# for an integration list, and a pooled namespace scores an unmapped value the same as an
# explicit "none", silently turning a mistake into a confident zero.
SIGNAL_POINTS = {
    "acceptance_criteria":  {"none": 0.0, "some": 0.5, "most": 1.0},
    "stack_specified":      {"none": 0.0, "partial": 0.5, "full": 1.0},
    "integrations_named":   {"none": 0.0, "partial": 0.5, "all": 1.0},
    "nfrs_stated":          {"none": 0.0, "some": 0.5, "most": 1.0},
    "data_model_described": {"none": 0.0, "partial": 0.5, "detailed": 1.0},
    "ui_defined":           {"none": 0.0, "described": 0.5, "designed": 1.0},
}

CLARITY_POINTS = {"high": 1.0, "medium": 0.5, "low": 0.0}
COMMITMENT_POINTS = {"committed": 1.0, "implied": 0.6, "speculative": 0.1}


# --- minimal JSON Schema subset validator (keeps the schema file the single source of truth) ---

def _resolve(node, root):
    ref = node.get("$ref")
    if not ref:
        return node
    target = root
    for part in ref.lstrip("#/").split("/"):
        target = target[part]
    return target


def validate_schema(data, schema, root, path="$"):
    schema = _resolve(schema, root)
    errors = []
    expected = schema.get("type")

    if expected == "object":
        if not isinstance(data, dict):
            return [f"{path}: expected an object, got {type(data).__name__}"]
        for field in schema.get("required", []):
            if field not in data:
                errors.append(f"{path}.{field}: required field is missing")
        for key, sub in schema.get("properties", {}).items():
            if key in data:
                errors.extend(validate_schema(data[key], sub, root, f"{path}.{key}"))
    elif expected == "array":
        if not isinstance(data, list):
            return [f"{path}: expected an array, got {type(data).__name__}"]
        if len(data) < schema.get("minItems", 0):
            errors.append(f"{path}: needs at least {schema['minItems']} item(s), found {len(data)}")
        for i, item in enumerate(data):
            errors.extend(validate_schema(item, schema.get("items", {}), root, f"{path}[{i}]"))
    elif expected == "string":
        if not isinstance(data, str):
            return [f"{path}: expected a string, got {type(data).__name__}"]
        if "enum" in schema and data not in schema["enum"]:
            errors.append(f"{path}: '{data}' is not one of {schema['enum']}")
        if "pattern" in schema and not re.match(schema["pattern"], data):
            errors.append(f"{path}: '{data}' does not match {schema['pattern']}")
    elif expected == "boolean" and not isinstance(data, bool):
        errors.append(f"{path}: expected a boolean, got {type(data).__name__}")

    return errors


# --- citation verification against the normalized sources ---

def _comparable(text):
    """Strip the artefacts conversion introduces, then flatten whitespace and case."""
    text = text.replace("<br>", " ").replace("\\|", "|")
    return re.sub(r"\s+", " ", text).strip().lower()


def iter_citations(inv, tasks=True, implicit=True):
    """Every citation in the inventory, with the label that locates it and what owns it.

    The walk used to stop at `feature.citations`. That is why an extraction could give all 912
    of its tasks a citation quoting the task's own title and pass every gate in this file: no
    check ever descended into a task. A task's citation is the only place a source row's text
    survives, so it is held to exactly what a feature's citation is held to.

    Yields (label, citation, feature, task) — task is None for a feature's own citation.
    """
    for feature in list(inv.get("features") or []) + (list(inv.get("implicit_scope") or []) if implicit else []):
        fid = feature.get("id", "?")
        for i, cit in enumerate(feature.get("citations") or []):
            yield f"{fid}.citations[{i}]", cit, feature, None
        if not tasks:
            continue
        for j, task in enumerate(feature.get("tasks") or []):
            for i, cit in enumerate(task.get("citations") or []):
                yield f"{fid}.tasks[{j}].citations[{i}]", cit, feature, task


def verify_citations(inv, normalized_dir):
    """Confirm every quote actually appears in the source it cites.

    Silent invention — a quote that is not in the document — is one of the two failures
    this module exists to prevent, and it is a substring search, not a judgement call.
    A similarity ratio separates a paraphrase (high) from a fabrication (low), so the
    finding can say which it is.
    """
    findings = []
    texts = {}
    for source in inv.get("sources", []):
        sid = source.get("id")
        matches = sorted(Path(normalized_dir).glob(f"{sid}-*.md"))
        if matches:
            texts[sid] = _comparable(matches[0].read_text(encoding="utf-8", errors="replace"))

    working = (inv.get("working_language") or "en").lower()
    langs = {s.get("id"): (s.get("language") or "").lower() for s in inv.get("sources", [])}

    for label, cit, _feature, _task in iter_citations(inv):
        sid = cit.get("source_id")
        if sid not in texts:
            findings.append(
                f"{label}: no normalized text found for {sid} in {normalized_dir} — "
                f"the quote could not be verified"
            )
            continue
        # A translated quote will never appear verbatim; check the original instead.
        foreign = langs.get(sid) and langs[sid] != working
        quote = cit.get("quote_original") if foreign and cit.get("quote_original") else cit.get("quote")
        needle = _comparable(quote or "")
        if not needle or needle in texts[sid]:
            continue
        ratio = max(
            (SequenceMatcher(None, needle, texts[sid][pos:pos + len(needle)]).ratio()
             for pos in range(0, max(len(texts[sid]) - len(needle), 0) + 1,
                              max(len(needle) // 4, 1))),
            default=0.0,
        )
        verdict = ("close to source text; likely paraphrased or lightly edited — quote it verbatim"
                   if ratio >= 0.75 else
                   "no similar passage in the source — this may be invented scope")
        findings.append(
            f"{label}: quote not found in {sid} (closest match {ratio:.0%}) — {verdict}"
        )
    return findings


# --- anchors, coverage, staleness, manifest reconciliation ---

PAGE_RE = re.compile(r"<!--\s*(page|slide)\s+(\d+)\s*-->")
SHEET_RE = re.compile(r"^##\s*sheet:\s*(.+?)\s*$", re.M)
ROW_RE = re.compile(r"^\|\s*(\d+)\s*\|", re.M)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.M)

LOC_PAGE = re.compile(r"\b(?:page|p\.?)\s*(\d+)", re.I)
LOC_SLIDE = re.compile(r"\bslide\s*(\d+)", re.I)
LOC_SHEET_ROW = re.compile(r"sheet\s*['\"]?(.+?)['\"]?\s*[, ]\s*row\s*(\d+)", re.I)


def _normalized_files(inv, normalized_dir):
    """Map each source id to the converted text produced for it."""
    files = {}
    for source in inv.get("sources", []):
        sid = source.get("id")
        matches = sorted(Path(normalized_dir).glob(f"{sid}-*.md"))
        if matches:
            files[sid] = matches[0]
    return files


def _line_of(text, pos):
    return text.count("\n", 0, pos) + 1


def index_anchors(text):
    """Every citable position the converter emitted for one source, and the line it sits on.

    Anchors map position -> line number rather than being a bare set of positions. The line
    is what lets a rendered citation link *into* the converted source at the row it cites,
    instead of printing a location the reader then has to go and find. Every existing caller
    reads these as membership tests and min/max, which a dict answers over its keys exactly
    as a set did.
    """
    sheets = {}
    for match in SHEET_RE.finditer(text):
        end = text.find("\n## sheet:", match.end())
        rows = {}
        for row in ROW_RE.finditer(text, match.end(), end if end != -1 else len(text)):
            rows[int(row.group(1))] = _line_of(text, row.start())
        sheets[match.group(1)] = rows
    pages, slides = {}, {}
    for match in PAGE_RE.finditer(text):
        target = pages if match.group(1) == "page" else slides
        target[int(match.group(2))] = _line_of(text, match.start())
    return {
        "pages": pages,
        "slides": slides,
        "sheets": sheets,
        "headings": [h.strip() for _, h in HEADING_RE.findall(text)],
    }


def resolve_location(location, anchors):
    """Check a structured location against the anchors the file actually has.

    Only structured forms are judged. A section reference like "§3.1" in a plain
    document has no anchor to check against, and inventing a check for it would
    produce noise rather than findings.
    """
    location = location or ""
    match = LOC_SHEET_ROW.search(location)
    if match:
        sheet, row = match.group(1), int(match.group(2))
        if sheet not in anchors["sheets"]:
            return f"sheet '{sheet}' is not in this source — sheets present: {sorted(anchors['sheets']) or 'none'}"
        if row not in anchors["sheets"][sheet]:
            rows = anchors["sheets"][sheet]
            return (f"sheet '{sheet}' has no row {row} — rows present run "
                    f"{min(rows)}-{max(rows)}" if rows else f"sheet '{sheet}' has no rows")
        return None
    for pattern, key, label in ((LOC_SLIDE, "slides", "slide"), (LOC_PAGE, "pages", "page")):
        match = pattern.search(location)
        if match and anchors[key]:
            number = int(match.group(1))
            if number not in anchors[key]:
                return f"{label} {number} is not in this source — it has {max(anchors[key])} {label}s"
            return None
    return None


def check_anchors(inv, normalized_dir):
    findings = []
    for sid, path in _normalized_files(inv, normalized_dir).items():
        anchors = index_anchors(path.read_text(encoding="utf-8", errors="replace"))
        entries = [(label, c) for label, c, _f, _t in iter_citations(inv)
                   if c.get("source_id") == sid]
        entries += [(f"not_scope[{i}]", n) for i, n in enumerate(inv.get("not_scope", []))
                    if n.get("source_id") == sid]
        for label, entry in entries:
            problem = resolve_location(entry.get("location"), anchors)
            if problem:
                findings.append(f"{label}: location '{entry.get('location')}' — {problem}")
    return findings


def coverage_regions(inv, normalized_dir, limit=40):
    """Which anchor regions of each source nothing points at.

    Turns "walk the document end to end and confirm nothing was missed" from a memory
    exercise into a short list the model only has to judge for substance.
    """
    referenced = {}
    # Task citations count. A row cited only under its story used to report as an unreferenced
    # region, so the coverage pass was wrong in the one direction that matters: it manufactured
    # gaps where the source had in fact been read.
    for _label, cit, _f, _t in iter_citations(inv):
        referenced.setdefault(cit.get("source_id"), []).append(cit.get("location") or "")
    for entry in inv.get("not_scope", []):
        referenced.setdefault(entry.get("source_id"), []).append(entry.get("location") or "")

    unreferenced = []
    for sid, path in _normalized_files(inv, normalized_dir).items():
        text = path.read_text(encoding="utf-8", errors="replace")
        anchors = index_anchors(text)
        locations = referenced.get(sid, [])
        for page in sorted(anchors["pages"]):
            if not any(LOC_PAGE.search(loc) and int(LOC_PAGE.search(loc).group(1)) == page
                       for loc in locations):
                unreferenced.append({"source_id": sid, "region": f"page {page}"})
        for sheet, rows in anchors["sheets"].items():
            hit = {int(m.group(2)) for loc in locations
                   for m in [LOC_SHEET_ROW.search(loc)] if m and m.group(1) == sheet}
            missing = sorted(set(rows) - hit)
            if missing:
                unreferenced.append({"source_id": sid, "region": f"sheet '{sheet}'",
                                     "rows": missing[:limit], "row_count": len(missing)})
    return unreferenced[:limit]


# --- quote completeness ---

CELL_SPLIT = re.compile(r"(?<!\\)\|")
ENDS_CLEANLY = re.compile(r"""[.!?\u2026:;)\]}"'\u00bb\u201d]\s*$""")

TRUNCATION_TAIL = 25      # characters left over before a clipped quote is worth reporting
PARTIAL_CHARS = 80        # a cleanly-ended quote that still leaves this much of the cell unread
PARTIAL_SHARE = 0.4       # ...and this share of it


def _row_cells(text_lines, line_no):
    """The cells of one converted table row, in order, unescaped."""
    if not 1 <= line_no <= len(text_lines):
        return []
    parts = [c.strip() for c in CELL_SPLIT.split(text_lines[line_no - 1])]
    return [c.replace("\\|", "|") for c in parts if c]


def check_quote_completeness(inv, normalized_dir):
    """Whether each quote carries the passage or merely gestures at it.

    Two failures, both found in a real 365-story run and neither visible to any other check
    because both quotes are genuinely present in the source:

    - **The clipped quote.** 565 of 917 citations stopped at the same ~240-character ceiling,
      mid-sentence, because nothing said how much to quote. The cited cell is right there, so
      how much was dropped is arithmetic rather than judgement.
    - **The self-citation.** All 912 task citations quoted the task's own title. That proves
      the title exists. The paragraph beside it in the same row — the thing an estimator would
      size against and a reviewer would read — went nowhere.

    Returns (findings, warnings): clipped and self-citing quotes block, a quote that ends
    cleanly but still leaves most of its cell unread is advisory.
    """
    findings, warnings = [], []
    lines, anchors = {}, {}
    for sid, path in _normalized_files(inv, normalized_dir).items():
        text = path.read_text(encoding="utf-8", errors="replace")
        lines[sid] = text.splitlines()
        anchors[sid] = index_anchors(text)

    for label, cit, _feature, task in iter_citations(inv):
        sid = cit.get("source_id")
        quote = (cit.get("quote") or "").strip()
        if not quote or sid not in lines:
            continue
        needle = _comparable(quote)

        match = LOC_SHEET_ROW.search(cit.get("location") or "")
        cells = []
        if match:
            sheet, row = match.group(1), int(match.group(2))
            line_no = anchors[sid]["sheets"].get(sheet, {}).get(row)
            if line_no:
                cells = _row_cells(lines[sid], line_no)

        # The cell the quote came from, and the longest cell the row has to offer.
        holding = max((c for c in cells if needle and needle in _comparable(c)),
                      key=len, default=None)
        longest = max(cells, key=len, default=None)

        if task is not None and needle == _comparable(task.get("name") or ""):
            if longest and len(longest) > len(quote) + TRUNCATION_TAIL:
                findings.append(
                    f"{label}: the quote is the task's own name — it records that the label "
                    f"exists and nothing else. The cited row carries a {len(longest)}-character "
                    f"column the quote skips; that is the text this task is, and what the "
                    f"estimator would otherwise have to size against six words"
                )
            elif cells:
                warnings.append(
                    f"{label}: the quote is the task's own name, reproducing one of the "
                    f"{len(cells)} columns on the cited row. Nothing on that row is long enough "
                    f"to be its substance, so there may be no paragraph to quote — but what a "
                    f"reader gets back is the label and none of the rest of the row"
                )
            else:
                warnings.append(
                    f"{label}: the quote is the task's own name, and the location does not "
                    f"resolve to a row this can check it against. If the source says more than "
                    f"the title, quote that instead"
                )
            continue

        if holding is None:
            continue    # not located in a cell — verify_citations owns that finding
        left = len(holding) - len(needle)
        if left > TRUNCATION_TAIL and not ENDS_CLEANLY.search(quote):
            tail = " ".join(quote.split()[-6:])
            findings.append(
                f"{label}: truncated quote — the cited cell continues for {left} more "
                f'characters and the quote stops mid-sentence ("...{tail}"). Quote the '
                f"passage in full; a reader is meant to use it instead of opening the source"
            )
        elif left >= PARTIAL_CHARS and left / len(holding) >= PARTIAL_SHARE:
            warnings.append(
                f"{label}: the quote ends cleanly but leaves {left} of the cell's "
                f"{len(holding)} characters unquoted — check nothing that changes the scope "
                f"is in the part that was dropped"
            )
        elif longest and holding is not longest and len(longest) >= 2 * len(holding) and len(longest) >= 120:
            warnings.append(
                f"{label}: the quote is from a {len(holding)}-character column while the same "
                f"row carries a {len(longest)}-character one. Confirm the substance of the row "
                f"is the part quoted"
            )
    return findings, warnings


def check_staleness(inv, inventory_path, normalized_dir):
    inventory_mtime = Path(inventory_path).stat().st_mtime
    newer = [str(p.name) for p in sorted(Path(normalized_dir).glob("*.md"))
             if p.stat().st_mtime > inventory_mtime]
    missing = [s.get("path") for s in inv.get("sources", [])
               if s.get("path") and not Path(s["path"]).exists()]
    return {"newer_sources": newer, "missing_source_paths": missing}


def reconcile_manifest(inv, manifest_path):
    """A converted source the inventory never lists is silent omission at document level."""
    try:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"manifest: cannot read {manifest_path}: {exc}"]

    listed = {s.get("id"): s.get("path") for s in inv.get("sources", [])}
    findings = []
    for entry in manifest.get("sources", []):
        sid = entry.get("id")
        if sid not in listed:
            state = "could not be converted" if entry.get("needs_native_read") else "was converted"
            findings.append(
                f"manifest: {sid} ({entry.get('path')}) {state} but is not in the inventory's "
                f"sources — add it, with a not_scope entry if it contributed nothing"
            )
    by_id = {e.get("id"): e for e in manifest.get("sources", [])}
    for source in inv.get("sources", []):
        entry = by_id.get(source.get("id"))
        if entry and entry.get("needs_native_read") and not (source.get("coverage_note") or "").strip():
            findings.append(
                f"manifest: {source.get('id')} could not be converted and carries no coverage_note — "
                f"say how it was read, or that it was not"
            )
        # Compare filenames, not full paths: the same file is legitimately written as an
        # absolute path in one place and a relative one in the other. A differing basename
        # means a genuinely different document behind the same source id.
        if entry and entry.get("path") and source.get("path") and \
                Path(entry["path"]).name != Path(source["path"]).name:
            findings.append(
                f"manifest: {source.get('id')} points at a different file — manifest has "
                f"'{Path(entry['path']).name}', inventory has '{Path(source['path']).name}'"
            )

    converted = {e.get("id") for e in manifest.get("sources", [])}
    for sid in listed:
        if sid not in converted:
            findings.append(f"manifest: inventory lists {sid} but the manifest does not — stale source id?")
    return findings


# --- integrity rules a schema cannot express ---

def check_integrity(inv, classified=False):
    findings = []
    features = inv.get("features", [])
    sources = inv.get("sources", [])
    source_ids = {s.get("id") for s in sources}
    source_lang = {s.get("id"): (s.get("language") or "").lower() for s in sources}
    working = (inv.get("working_language") or "en").lower()

    seen = set()
    for f in features:
        fid = f.get("id", "?")
        if fid in seen:
            findings.append(f"{fid}: duplicate feature id — renumber so every id is unique")
        seen.add(fid)

    for label, cit, _feature, _task in iter_citations(inv):
        sid = cit.get("source_id")
        if sid not in source_ids:
            findings.append(
                f"{label}: source_id '{sid}' is not in sources — "
                f"known ids: {sorted(source_ids) or 'none'}"
            )
        lang = source_lang.get(sid, "")
        if lang and lang != working and not cit.get("quote_original"):
            findings.append(
                f"{label}: source {sid} is in '{lang}' but quote_original is missing — "
                f"keep the untranslated text so a native reader can verify the extraction"
            )
        if not (cit.get("quote") or "").strip():
            findings.append(f"{label}: quote is empty — a citation without source text proves nothing")

    for f in features:
        fid = f.get("id", "?")

        tags = f.get("tags", {})
        for axis, allowed in TAG_VOCABULARY.items():
            tag = tags.get(axis)
            if not isinstance(tag, dict):
                # The inventory schema no longer requires tags — they live in classification.json
                # now — so an absent axis on a feature being checked WITH a classification is a
                # gap in that file, not a shape the schema would have caught.
                if classified:
                    findings.append(
                        f"{fid}.tags.{axis}: no classification — every priced story needs all "
                        f"five axes, and est-estimate refuses to price without them"
                    )
                continue
            if tag.get("value") not in allowed:
                findings.append(f"{fid}.tags.{axis}: '{tag.get('value')}' is not one of {allowed}")
            if not (tag.get("why") or "").strip():
                findings.append(
                    f"{fid}.tags.{axis}: 'why' is empty — an untagged reason is a black-box coefficient"
                )

        for i, dep in enumerate(f.get("depends_on", [])):
            target = dep.get("feature_id")
            if target == fid:
                findings.append(f"{fid}.depends_on[{i}]: feature depends on itself — remove it")
            elif target not in seen and target not in {x.get("id") for x in features}:
                findings.append(
                    f"{fid}.depends_on[{i}]: '{target}' is not a known feature id — "
                    f"fix the reference or add the feature"
                )
            if not dep.get("inferred") and not (dep.get("evidence") or "").strip():
                findings.append(
                    f"{fid}.depends_on[{i}]: a stated dependency needs 'evidence'; "
                    f"set inferred=true if it was deduced instead"
                )
            if dep.get("inferred") and not (dep.get("why") or "").strip():
                findings.append(
                    f"{fid}.depends_on[{i}]: an inferred dependency needs 'why' — a human is "
                    f"being asked to confirm it, and '{target}' on its own is one bare id "
                    f"pointing at another"
                )

    signals = inv.get("completeness_signals", {})
    for name, allowed in SIGNAL_POINTS.items():
        signal = signals.get(name)
        if not isinstance(signal, dict):
            findings.append(
                f"completeness_signals.{name}: expected an object with 'value' and 'why' — "
                f"the score it feeds sets the estimate's band width, so it has to be interrogable"
            )
            continue
        if signal.get("value") not in allowed:
            findings.append(
                f"completeness_signals.{name}: '{signal.get('value')}' is not one of {sorted(allowed)}"
            )
        if not (signal.get("why") or "").strip():
            findings.append(
                f"completeness_signals.{name}: 'why' is empty — cite what in the sources decided it"
            )

    contractual = {s.get("id") for s in sources if s.get("doc_type") in ("sow", "rfp")}
    if contractual:
        for f in features:
            cited = {c.get("source_id") for c in f.get("citations", [])}
            if not (cited & contractual) and not f.get("scope_status"):
                findings.append(
                    f"{f.get('id', '?')}: not traceable to the agreed scope ({', '.join(sorted(contractual))}) "
                    f"but carries no scope_status — confirm with the operator, then set "
                    f"'outside_agreed_scope', or add a citation to the contractual source"
                )

    for i, ns in enumerate(inv.get("not_scope", [])):
        if ns.get("source_id") not in source_ids:
            findings.append(f"not_scope[{i}]: source_id '{ns.get('source_id')}' is not in sources")

    findings.extend(check_grouping(inv))
    findings.extend(f"dependency cycle: {' -> '.join(c)}" for c in find_cycles(features))
    return findings


SURFACES = {"backend", "frontend", "design", "infra", "data"}


def check_grouping(inv):
    """Epics, tasks and surfaces: the three things that decide how much the estimate invents.

    Epics are billed per epic, tasks are what a reviewer checks the workbook against, and
    surfaces are what keeps a role off work it does not do.

    From schema 1.1 grouping is REQUIRED: an ungrouped inventory has no delivery structure to
    order, and every render sorts on the epic sequence. Below 1.1 it stays optional but never
    half-done, because an estimate that mixes a declared epic count with a derived one is
    billing planning against a number matching neither the source nor the stories.
    """
    findings = []
    features = inv.get("features", [])
    epics = inv.get("epics", [])
    epic_ids = {e.get("id") for e in epics}
    ordered = str(inv.get("schema_version") or "1.0") >= "1.1"

    if ordered and not epics:
        findings.append(
            "no epics are declared — from schema 1.1 every inventory carries a delivery "
            "structure. Where the source groups nothing, synthesise the grouping and mark it "
            "origin 'synthesised' with a 'why'"
        )

    for i, epic in enumerate(epics):
        if epic.get("origin") == "synthesised" and not (epic.get("why") or "").strip():
            findings.append(f"epics[{i}] ({epic.get('id')}): synthesised but carries no 'why' — "
                            f"a grouping the source did not make has to say on what basis it was made")

    grouped = [f for f in features if f.get("epic_id")]
    if (epics or ordered) and len(grouped) != len(features):
        missing = [f.get("id") for f in features if not f.get("epic_id")][:5]
        findings.append(
            f"{len(features) - len(grouped)} stories carry no epic_id while {len(epics)} epics are "
            f"declared (e.g. {', '.join(missing)}) — planning is priced per epic, so a partial "
            f"grouping bills a count that matches neither the source nor the stories"
        )
    for f in grouped:
        if epic_ids and f["epic_id"] not in epic_ids:
            findings.append(f"{f.get('id')}: epic_id '{f['epic_id']}' is not a declared epic")

    task_ids = {}
    for f in features:
        for i, task in enumerate(f.get("tasks", [])):
            tid = task.get("id")
            if tid in task_ids:
                findings.append(f"{f.get('id')}.tasks[{i}]: task id '{tid}' is already used by "
                                f"{task_ids[tid]} — a source row belongs to exactly one story, or "
                                f"the work behind it is being counted twice")
            task_ids[tid] = f.get("id")
            if not task.get("citations"):
                findings.append(f"{f.get('id')}.tasks[{i}] ({tid}): no citation — the whole point "
                                f"of keeping the source rows is that they stay verifiable")

    for f in features:
        surfaces = f.get("surfaces")
        if surfaces is None:
            continue
        unknown = [x for x in surfaces if x not in SURFACES]
        if unknown:
            findings.append(f"{f.get('id')}.surfaces: {unknown} not in {sorted(SURFACES)}")
        if not surfaces:
            findings.append(f"{f.get('id')}.surfaces: empty — omit the field to mean 'not "
                            f"classified'. An empty list reads as 'no roles', which prices at zero")
    return findings


def check_boilerplate_tags(features, threshold=0.2, floor=20):
    """A justification repeated across many features is a default wearing a reason.

    The Kampies extraction tagged 385 of 795 features 'M' with the byte-identical sentence
    "Treated as one resource or flow; the row's verb does not mark it as a read-only view".
    Every downstream number rested on that, and nothing objected, because a `why` was
    present on every single tag. Presence was the only thing being checked.
    """
    if len(features) < floor:
        return []
    findings = []
    for axis in TAG_VOCABULARY:
        counts = {}
        for f in features:
            tag = (f.get("tags") or {}).get(axis)
            if isinstance(tag, dict) and (tag.get("why") or "").strip():
                key = " ".join(tag["why"].split()).lower()
                counts.setdefault(key, []).append(f.get("id"))
        for why, ids in counts.items():
            if len(ids) > max(floor, threshold * len(features)):
                findings.append(
                    f"tags.{axis}: {len(ids)} of {len(features)} features share one justification "
                    f"— \"{why[:80]}...\" (e.g. {', '.join(ids[:3])}). That is a default, not a "
                    f"judgement; classify them or say in the report that they were defaulted"
                )
    return findings


def join_classification(inv, classification):
    """Hang each feature's classification back on it, in memory only.

    Joining once here means every check below keeps reading `f["tags"]` exactly as it did when
    the inventory carried them inline — the tags moved skills, not shape. Mirrors
    est-estimate's `load_scope`, and the two must agree or the checker and the engine would be
    validating different things.
    """
    rows = (classification or {}).get("features") or {}
    for key in ("features", "implicit_scope"):
        for feature in inv.get(key) or []:
            row = rows.get(feature.get("id"))
            if row:
                feature["tags"] = row
    return sorted(set(rows) - {f.get("id") for key in ("features", "implicit_scope")
                               for f in inv.get(key) or []})


def load_bands(cost_model=None):
    """The band table and the delivery anchor it was fitted against.

    Returns (size_bands, used_path, source_label), or (None, None, reason). Never raises: a
    missing or older model costs the sizing report, not the validation run.
    """
    for path, label in ((cost_model, "cost model"), (SEED_MODEL_PATH, "shipped seed")):
        if not path:
            continue
        try:
            bands = json.loads(Path(path).read_text(encoding="utf-8")).get("size_bands")
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(bands, dict) and bands.get("_anchor"):
            return bands, Path(path), f"{label}: {path}"
    return None, None, ("no cost model with a size_bands._anchor block was readable — "
                        "sizing is unchecked for this run")


def load_standing_catalogue(cost_model=None):
    """The standing_work items an inventory selects from. Same fallback order as load_bands."""
    for path in (cost_model, SEED_MODEL_PATH):
        if not path:
            continue
        try:
            block = json.loads(Path(path).read_text(encoding="utf-8")).get("standing_work")
        except (OSError, json.JSONDecodeError):
            continue
        items = (block or {}).get("items")
        if isinstance(items, dict) and items:
            return items, f"{path}"
    return None, "no cost model with a standing_work catalogue was readable"


def band_of(feature):
    tag = (feature.get("tags") or {}).get("size_band")
    return tag.get("value") if isinstance(tag, dict) else None


def source_lines(feature):
    """How many lines of the client's own document this story absorbed.

    `tasks` is where story synthesis parks the source rows; a story built straight from one
    passage has none and is measured by its citations instead.
    """
    return max(len(feature.get("tasks") or []), len(feature.get("citations") or []), 1)

def check_sizing(features, bands, floor=20, impact=0.25, ratio=1.5):
    """Is the band distribution the shape a delivered project actually had?

    INFORMATIONAL, ALWAYS. Nothing here is an error, none of it blocks pricing, and none of it
    is grounds on its own to re-judge a story. That last clause is the 3.0 change, and it is
    the fix for a real bias: the classification guide told the classifier what distribution to
    expect BEFORE it judged anything, and this function then flagged deviation from that same
    distribution AFTERWARDS. The prior was injected and then enforced, so the distribution
    stopped carrying information about the project and all the real variance was squeezed into
    the story count — which nothing checked. `check_granularity` is the check that was missing.

    The thresholds also moved, because the arithmetic under them did. On the 2.x bands, which
    ran 1 h to 90 h of manual baseline, shifting an inventory's L share from 25% to 37% moved
    the baseline 17%; on the measured delivered-hours bands, which run 1.6 h to 7.7 h, the same
    shift moves it 2%. A threshold tuned to the first is noise against the second, so `impact`
    rose from 0.10 to 0.25 — a deviation now has to be worth a quarter of the estimate before
    it is worth a reader's attention.

    Half of these need a volume proxy — how much of the client's own document each story
    absorbed — and that only exists once story synthesis has parked the source rows as `tasks`.
    Against a prose source one citation can cover three pages, so the count means nothing and
    those checks are skipped rather than guessed at. `skipped` says which and why.
    """
    order = TAG_VOCABULARY["size_band"]
    if len(features) < floor or not bands:
        return [], {"skipped": "fewer than %d stories" % floor if bands else "no anchor"}
    anchor = bands["_anchor"]
    expected = anchor.get("distribution") or {}
    counts = {b: [f.get("id") for f in features if band_of(f) == b] for b in order}
    n = len(features)
    baseline = sum(float(bands[b]["likely"]) * len(ids) for b, ids in counts.items() if b in bands)
    lines_total = sum(source_lines(f) for f in features)
    # Row-shaped: the source rows survived into the inventory, so a count of them is a real
    # measure of how much was stated. Prose-shaped: it is not, and nothing below pretends it is.
    row_shaped = lines_total >= 1.5 * n
    warnings, skipped = [], []

    # XS and XL are NOT reported merely for existing. Both warnings used to fire on the first
    # tag and both pointed the same way — "check the unit", "a signal to split" — so between
    # them and a stated 64%-M expectation the classifier had three separate nudges toward the
    # middle of the table and none away from it. The anchor's own measured record has 2.7% XS
    # and 4.0% XL; the claim that it had neither was simply false, and it was pushing real work
    # up and down a band. They now fire only on a share the anchor cannot account for.
    for extreme, floor_share, note in (
        ("XS", 0.10, "Something this small is usually a task inside a story — the anchor's own "
                     "share is 2.7%, so a few are expected and a tenth of the inventory is not. "
                     "Check the unit before pricing it as one"),
        ("XL", 0.10, "An XL is a signal to look for a split — the anchor's own share is 4.0%. "
                     "est-estimate prices a narrowing question for each one"),
    ):
        share = len(counts[extreme]) / n
        if share >= floor_share:
            warnings.append(
                f"size_band: {share:.0%} of stories are {extreme} ({len(counts[extreme])} of {n}, "
                f"e.g. {', '.join(counts[extreme][:3])}), against "
                f"{expected.get(extreme, 0):.1%} in the delivery anchor. {note}"
            )

    # Judged by what the deviation is worth, not by how far the percentage moved. Two points off
    # the anchor matters at L and does not at XS, because the hours behind them differ thirty-fold
    # — and what a reader needs is how much of the estimate rests on the difference.
    for band in ("S", "M", "L"):
        want = expected.get(band)
        if want is None or not baseline:
            continue
        share = len(counts[band]) / n
        worth = (share - want) * n * float(bands[band]["likely"]) / baseline
        if abs(worth) >= impact:
            direction = "more" if share > want else "fewer"
            warnings.append(
                f"size_band: {share:.0%} of stories are {band}, against {want:.0%} in the delivery "
                f"anchor — {direction} than the reference class, and worth {abs(worth):.0%} of the "
                f"story hours. A reference class is not a target: this is here so a shape you did "
                f"not intend gets noticed, and it is NOT on its own a reason to re-band anything. "
                f"If the project really is shaped that way, say so in the extraction report. "
                f"{band} is \"{(bands[band].get('why') or '').split(',')[0].strip().lower()}\""
            )

    if row_shaped:
        # The double count. Holding the source volume at one line so the content cannot vary,
        # does the band still track how dangerous the story is? Then criticality is paid for
        # twice — here, and again through review_tier.
        thin = [f for f in features if source_lines(f) == 1]
        risky = {}
        for band in ("S", "M", "L"):
            group = [f for f in thin if band_of(f) == band]
            if len(group) >= 8:
                risky[band] = sum(
                    1 for f in group
                    if ((f.get("tags") or {}).get("review_tier") or {}).get("value")
                    in ("sensitive", "critical")
                ) / len(group)
        if len(risky) >= 2:
            low = min(risky, key=lambda b: order.index(b))
            high = max(risky, key=lambda b: order.index(b))
            if risky[high] - risky[low] >= 0.20:
                warnings.append(
                    f"size_band: among stories citing a single source line, where the content "
                    f"cannot vary, {risky[low]:.0%} of {low} stories are sensitive or critical "
                    f"against {risky[high]:.0%} of {high} ones. The band is tracking risk, not "
                    f"volume — and review_tier already prices risk, so it is being billed twice. "
                    f"Size is how much work there is; reach and consequence belong in review_tier"
                )

        # The clearest single case: one line of the client's document, priced as a new capability.
        big = [f.get("id") for f in features
               if source_lines(f) == 1 and band_of(f) in ("L", "XL")]
        if len(big) >= max(10, 0.05 * n):
            warnings.append(
                f"size_band: {len(big)} stories are L or XL on a single source line (e.g. "
                f"{', '.join(big[:3])}). One line can genuinely describe a protocol or a new "
                f"transport — \"sign in with Microsoft\" does — but at this count the band is "
                f"more likely reading importance than size"
            )
    else:
        skipped.append(
            "the per-source-line checks: this inventory carries %.2f source lines per story, so "
            "the citation count is not a measure of how much the source stated" % (lines_total / n)
        )

    rate, want, unit, over = (
        (baseline / lines_total, anchor.get("baseline_per_source_line_h"), "source line", lines_total)
        if row_shaped else
        (baseline / n, anchor.get("baseline_per_story_h"), "story", n)
    )
    if want and rate and (rate / want >= ratio or want / rate >= ratio):
        warnings.append(
            f"size_band: the bands assign {rate:.1f}h per {unit}, against {want:.1f}h in the "
            f"delivery anchor ({baseline:.0f}h over {over} {unit}s). The whole estimate scales "
            f"with this, so it is worth being deliberate about — but note that BOTH sides of this "
            f"ratio are under the extraction's own control: the citation count is set by its "
            f"quoting policy and the story count by its synthesis policy, so it can always be "
            f"satisfied by re-slicing. check_granularity is the check that cannot be"
        )

    return warnings, {"row_shaped": row_shaped,
                      "baseline_h": round(baseline, 1),
                      f"baseline_h_per_{'source_line' if row_shaped else 'story'}": round(rate, 2),
                      "anchor_expects": round(want, 2) if want else None,
                      "advisory_only": "no finding here is grounds on its own to re-band a story",
                      "skipped": skipped}


def check_granularity(features, bands, floor=20, tol=1.6):
    """Is this inventory sliced the way the anchor was? The check that was missing.

    Everything downstream is linear in the story count, and the story count is a property of
    whoever wrote the document rather than of the work. Across the three delivered projects the
    SAME scope was written at wildly different grain: hours per delivered story ran 9.2 / 2.9 /
    3.1, a 3.2-fold spread, and per acceptance criterion it was worse. Nothing in 2.x checked
    it, and both of the sanity ratios that existed divided by numbers the extraction itself
    chose — so they could always be satisfied by re-slicing.

    Surfaces per story is the one signal that cannot: it is an observation about what each story
    touches, and it separated the three anchors cleanly at 2.29 (EPP), 1.25 (memorial-healthcare)
    and 1.12 (easyterms) while hours per surface-touch stayed inside 1.74x. The cost model is
    fitted to EPP, so an inventory materially below the anchor's figure is sliced finer than the
    bands assume and the estimate will run HIGH. Reported with its direction, never gated: a
    genuinely fine-grained backlog is a real thing, and this is how it gets said out loud
    instead of quietly multiplying.
    """
    anchor = (bands or {}).get("_anchor") or {}
    want = anchor.get("surfaces_per_story")
    tagged = [f for f in features if f.get("surfaces")]
    if len(features) < floor or not want:
        return [], {"skipped": "fewer than %d stories" % floor if want
                    else "the cost model's anchor records no surfaces_per_story"}
    if len(tagged) < 0.5 * len(features):
        return [], {"skipped": f"only {len(tagged)} of {len(features)} stories carry surfaces, so "
                               f"the ratio would measure the tagging rather than the slicing"}

    got = sum(len(f["surfaces"]) for f in tagged) / len(tagged)
    stories_per_epic = None
    epics = {f.get("epic_id") for f in features if f.get("epic_id")}
    if epics:
        stories_per_epic = round(len(features) / len(epics), 1)

    warnings = []
    if got and (want / got >= tol or got / want >= tol):
        finer = got < want
        warnings.append(
            f"granularity: this inventory averages {got:.2f} surfaces per story against "
            f"{want:.2f} in the delivery anchor — sliced {want / got:.1f}x "
            f"{'FINER' if finer else 'COARSER'}. The bands are fitted to the anchor's grain, so "
            f"the estimate will run {'HIGH' if finer else 'LOW'} by roughly that factor. Either "
            f"re-synthesise toward the anchor's unit or say in the extraction report that the "
            f"grain is deliberate and the number is read with it. This is the ONE sizing signal "
            f"the extraction cannot satisfy by re-slicing, which is why it is here"
        )
    return warnings, {"surfaces_per_story": round(got, 2),
                      "anchor_expects": round(float(want), 2),
                      "ratio_to_anchor": round(got / float(want), 2),
                      "stories_per_epic": stories_per_epic,
                      "stories": len(features),
                      "advisory_only": "reported with its direction; never gates pricing"}


STANDING_TRIGGERS = {
    # Advisory name matches, not a classifier. Each is a prompt to look at a story that may
    # already cover a catalogue item the project is also paying standing work for.
    "repo_scaffold": ("scaffold", "monorepo", "boilerplate", "shared config", "lint", "bootstrap"),
    "bmad_setup": ("bmad",),
    "ci_pipeline": ("ci/cd", "ci ", "pipeline", "github actions", "regression gate"),
    "environments": ("environment", "provisioning", "secret", "dns", "tls"),
    "observability": ("observability", "logging", "metrics", "alerting", "monitoring"),
    "release_process": ("release", "rollback"),
    "mobile_release": ("app store", "testflight", "play console", "store provisioning"),
    "service_integration_env": ("integration environment",),
}


def check_sequence(inv):
    """Build order, and whether the order stated can actually be built.

    The extraction states `sequence`; this checks it rather than trusting it. Story-level
    `depends_on` is rolled up to epic level — a story in A depending on one in B means A cannot
    be built before B — and `depends_on_epics` adds the ordering no story records. A stated
    order contradicting a stated dependency is a fact rather than a preference, so it is a
    finding and not an advisory.

    Returns (findings, report). Quiet below schema 1.1, where `sequence` did not exist.
    """
    findings = []
    epics = inv.get("epics") or []
    report = {"epics": len(epics), "order": [], "violations": [],
              "derived_edges": 0, "stated_edges": 0}
    if not epics:
        return findings, report
    required = str(inv.get("schema_version") or "1.0") >= "1.1"

    seq, held = {}, {}
    for i, epic in enumerate(epics):
        eid, value = epic.get("id"), epic.get("sequence")
        if value is None:
            if required:
                findings.append(f"epics[{i}] ({eid}): no 'sequence' — from schema 1.1 every epic "
                                f"states where it falls in the build order")
            continue
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            findings.append(f"epics[{i}] ({eid}): sequence {value!r} is not a positive integer")
            continue
        if value in held:
            findings.append(f"epics[{i}] ({eid}): sequence {value} is already held by "
                            f"'{held[value]}' — two epics cannot both be built {value}th")
        held[value] = eid
        seq[eid] = value
        if required and not (epic.get("sequence_why") or "").strip():
            findings.append(f"epics[{i}] ({eid}): carries a sequence but no 'sequence_why' — an "
                            f"order nobody can interrogate is the guess this field exists to prevent")

    if seq and sorted(held) != list(range(1, len(epics) + 1)):
        findings.append(
            f"epic sequence reads {sorted(held)} — it must run 1..{len(epics)} with no gaps and "
            f"no repeats, because a gap reads as an epic somebody dropped rather than a space "
            f"left deliberately"
        )

    epic_of = {f.get("id"): f.get("epic_id")
               for key in ("features", "implicit_scope") for f in inv.get(key) or []}
    edges = {}
    for key in ("features", "implicit_scope"):
        for f in inv.get(key) or []:
            after = f.get("epic_id")
            for dep in f.get("depends_on") or []:
                before = epic_of.get(dep.get("feature_id"))
                if after and before and after != before:
                    edges.setdefault((after, before),
                                     f"{f.get('id')} depends on {dep.get('feature_id')}")
    report["derived_edges"] = len(edges)

    for i, epic in enumerate(epics):
        after = epic.get("id")
        for dep in epic.get("depends_on_epics") or []:
            before = dep.get("epic_id")
            if before not in epic_ids_of(epics):
                findings.append(f"epics[{i}] ({after}): depends_on_epics '{before}' is not a "
                                f"declared epic")
                continue
            if before == after:
                findings.append(f"epics[{i}] ({after}): depends on itself — remove it")
                continue
            report["stated_edges"] += 1
            edges[(after, before)] = dep.get("why") or "stated on the epic"

    pseudo = [{"id": e.get("id"),
               "depends_on": [{"feature_id": b} for (a, b) in edges if a == e.get("id")]}
              for e in epics]
    for cycle in find_cycles(pseudo):
        findings.append(f"epic dependency cycle: {' -> '.join(str(c) for c in cycle)} — no build "
                        f"order exists that satisfies it")

    for (after, before), why in sorted(edges.items()):
        if after in seq and before in seq and seq[after] <= seq[before]:
            findings.append(
                f"{after} is sequenced {seq[after]} but depends on {before} at {seq[before]} "
                f"({why}) — it cannot be built before what it stands on"
            )
            report["violations"].append({"epic": after, "needs": before, "sequence": seq[after],
                                         "needs_sequence": seq[before], "why": why})

    report["order"] = [{"id": e.get("id"), "name": e.get("name"),
                        "sequence": seq.get(e.get("id"))}
                       for e in sorted(epics, key=lambda e: (seq.get(e.get("id")) is None,
                                                             seq.get(e.get("id")) or 0,
                                                             str(e.get("id") or "")))]
    return findings, report


def epic_ids_of(epics):
    return {e.get("id") for e in epics}


def check_standing_overlap(inv, catalogue):
    """Foundation work: what was selected, what was left out, and what may be paid twice.

    Advisory throughout, and deliberately so. Nothing here can under-price: an item the
    inventory never mentions is still priced by est-estimate, so silence costs a warning
    rather than hours. The overlap it looks for is real and measured — all three delivered
    anchor projects priced repo scaffold, CI and environment setup as ordinary stories while
    the cost model billed standing work for the same thing on top — but the detection is a
    name match, and a name match is a reason to look rather than a verdict.
    """
    findings, warnings = [], []
    report = {"catalogue_items": len(catalogue or {}), "selected": [], "excluded": [],
              "unmentioned": [], "overlaps": [], "advisory_only": True}
    stories = [f for key in ("features", "implicit_scope") for f in inv.get(key) or []]
    ids = {f.get("id") for f in stories}
    block = inv.get("standing_scope")

    if not catalogue:
        report["note"] = "no cost model with a standing_work catalogue was readable"
        return findings, warnings, report
    if not block:
        report["note"] = ("no standing_scope block — est-estimate will select foundation work by "
                          "stack profile alone, which is what every inventory before schema 1.1 "
                          "did. Nothing is dropped; nothing is tailored either")
        report["unmentioned"] = sorted(catalogue)
        return findings, warnings, report

    seen = {}
    for i, row in enumerate(block.get("selected") or []):
        key = row.get("key")
        if key not in catalogue:
            findings.append(f"standing_scope.selected[{i}]: '{key}' is not a standing_work item — "
                            f"run inventory-check.py --standing for the catalogue")
            continue
        seen[key] = row
        entry = {"key": key, "name": catalogue[key].get("name"), "why": row.get("why")}
        if row.get("applies"):
            report["selected"].append(entry)
        else:
            entry["covered_by"] = row.get("covered_by") or []
            report["excluded"].append(entry)
        for fid in row.get("covered_by") or []:
            if fid not in ids:
                findings.append(f"standing_scope.selected[{i}] ({key}): covered_by '{fid}' is not "
                                f"a declared story")

    report["unmentioned"] = sorted(set(catalogue) - set(seen))
    # Split by how an unmentioned item actually behaves. One that every project pays is priced
    # regardless, so silence costs nothing but clarity. One gated to a stack profile is priced
    # only if the estimate happens to run under that stack — so silence there really can drop
    # it, and saying "priced anyway" about both would be false about half of them.
    universal = [k for k in report["unmentioned"] if catalogue[k].get("stacks") == "all"]
    gated = [k for k in report["unmentioned"] if k not in universal]
    if universal:
        warnings.append(
            f"standing_scope: {len(universal)} item(s) every project pays are neither claimed nor "
            f"declined ({', '.join(universal)}) — they are priced regardless, so nothing is lost, "
            f"but an item nobody wrote down is indistinguishable from one nobody considered"
        )
    if gated:
        warnings.append(
            f"standing_scope: {len(gated)} stack-gated item(s) are unmentioned "
            f"({', '.join(gated)}) — these are priced ONLY when the estimate runs under a "
            f"matching --stack, so leaving them out is the one case where silence can drop real "
            f"work. Claim or decline them explicitly"
        )

    for key, row in seen.items():
        if not row.get("applies"):
            continue
        words = STANDING_TRIGGERS.get(key, ())
        hits = [f"{f.get('id')} {f.get('name')}" for f in stories
                if any(w in (f.get("name") or "").lower() for w in words)]
        if hits:
            report["overlaps"].append({"key": key, "stories": hits[:5], "count": len(hits)})
            warnings.append(
                f"standing_scope: '{key}' is claimed while {len(hits)} extracted story name(s) "
                f"read like the same work (e.g. {hits[0]}) — if the story already covers it, set "
                f"applies false and name the story in covered_by, or the project pays for it twice"
            )
    return findings, warnings, report


def find_cycles(features):
    """Depth-first cycle detection. est-estimate cannot compute a critical path over a cyclic graph."""
    graph = {f.get("id"): [d.get("feature_id") for d in f.get("depends_on", [])] for f in features}
    cycles, state = [], {}

    def walk(node, stack):
        if state.get(node) == "done":
            return
        if state.get(node) == "open":
            cycles.append(stack[stack.index(node):] + [node])
            return
        state[node] = "open"
        for nxt in graph.get(node, []):
            if nxt in graph:
                walk(nxt, stack + [nxt])
        state[node] = "done"

    for node in graph:
        walk(node, [node])
    return cycles


# --- scoring ---

def score(inv, classified=False):
    """The input completeness score, or an explicit refusal to compute one.

    `clarity_quality` is 18% of this and comes from a tag that now lives in classification.json.
    Computed without one, every feature scores 0.0 for clarity — no exception, no finding — the
    ceiling silently becomes 0.82, and since band width is 1 + k(1-completeness)^p, every
    estimate quietly widens with nothing to point at. So an unclassified inventory returns
    `input_completeness: null` and says what is missing. est-estimate already refuses to price
    without a score, which makes "classification never ran" a refusal rather than a wide band.
    """
    signals = inv.get("completeness_signals", {})
    features = inv.get("features", [])

    points = {}
    for name, allowed in SIGNAL_POINTS.items():
        signal = signals.get(name)
        value = signal.get("value") if isinstance(signal, dict) else None
        points[name] = allowed.get(value, 0.0)

    points["commitment_quality"] = (sum(
        COMMITMENT_POINTS.get(f.get("commitment"), 0.0) for f in features
    ) / len(features)) if features else 0.0

    if not classified:
        return {
            "input_completeness": None,
            "pending": ["clarity_quality"],
            "why": ("clarity is 18% of the score and lives in classification.json. Run this again "
                    "with --classification once est-estimate has classified the scope; a score "
                    "computed without it would read as a thin brief rather than an unclassified one."),
            "points": {k: round(v, 3) for k, v in points.items()},
            "weights": SIGNAL_WEIGHTS,
        }

    points["clarity_quality"] = (sum(
        CLARITY_POINTS.get((f.get("tags", {}).get("clarity") or {}).get("value"), 0.0) for f in features
    ) / len(features)) if features else 0.0

    contributions = {k: round(points[k] * w, 4) for k, w in SIGNAL_WEIGHTS.items()}
    return {
        "input_completeness": round(sum(contributions.values()), 3),
        "points": {k: round(v, 3) for k, v in points.items()},
        "weights": SIGNAL_WEIGHTS,
        "contributions": contributions,
    }


def coverage(inv, classified=False):
    features = inv.get("features", [])
    tag_status, cited_sources = {}, set()
    for f in features:
        for tag in f.get("tags", {}).values():
            if isinstance(tag, dict):
                tag_status[tag.get("status")] = tag_status.get(tag.get("status"), 0) + 1
        for cit in f.get("citations", []):
            cited_sources.add(cit.get("source_id"))

    silent = [s["id"] for s in inv.get("sources", [])
              if s.get("id") not in cited_sources
              and not any(n.get("source_id") == s.get("id") for n in inv.get("not_scope", []))]

    return {
        "features": len(features),
        "not_scope_entries": len(inv.get("not_scope", [])),
        "conflicts": len(inv.get("conflicts", [])),
        "open_questions": sum(len(f.get("open_questions", [])) for f in features),
        "tag_status": tag_status,
        "inferred_dependencies": sum(
            1 for f in features for d in f.get("depends_on", []) if d.get("inferred")
        ),
        # Tag histograms are omitted rather than reported as zeros when no classification was
        # supplied — a coverage report full of empty bands reads as a badly classified project
        # instead of an unclassified one.
        **({} if not classified else {
        "review_tiers": {
            tier: sum(1 for f in features
                      if (f.get("tags", {}).get("review_tier") or {}).get("value") == tier)
            for tier in TAG_VOCABULARY["review_tier"]
        },
        # The band distribution, for the same reason the tiers are here: it is the shape a
        # reviewer judges, and re-deriving it means re-walking the inventory this just walked.
        "size_bands": {
            band: sum(1 for f in features if band_of(f) == band)
            for band in TAG_VOCABULARY["size_band"]
        },
        # Ids, not just counts: the confirmation batch needs the items themselves, and
        # re-deriving them means re-reading the inventory the script just walked.
        "sensitive_or_critical": [
            f.get("id") for f in features
            if (f.get("tags", {}).get("review_tier") or {}).get("value") in ("sensitive", "critical")
        ],
        }),
        "source_lines_per_story": round(
            sum(source_lines(f) for f in features) / len(features), 2) if features else 0,
        "inferred_dependency_pairs": [
            {"feature": f.get("id"), "depends_on": d.get("feature_id")}
            for f in features for d in f.get("depends_on", []) if d.get("inferred")
        ],
        "sources_contributing_nothing": silent,
        "outside_agreed_scope": [
            f.get("id") for f in features if f.get("scope_status") == "outside_agreed_scope"
        ],
    }


def main():
    ap = argparse.ArgumentParser(
        description="Validate a Feature Inventory and compute its input completeness score.",
        epilog="Exit codes: 0 clean, 1 findings to fix, 2 unreadable input.",
    )
    ap.add_argument("inventory", nargs="?", help="path to feature-inventory.json")
    ap.add_argument("-o", "--output", help="write the JSON result here instead of stdout")
    ap.add_argument("--normalized", metavar="DIR",
                    help="directory of normalized sources; verifies every quote actually appears "
                         "in the document it cites, resolves structured locations against the "
                         "anchors the file really has, lists unreferenced regions, and reports staleness")
    ap.add_argument("--manifest", metavar="PATH",
                    help="convert-input manifest; reconciles converted sources against the "
                         "inventory's sources array")
    ap.add_argument("--classification", metavar="PATH",
                    help="classification.json from est-estimate. Without it the tag checks and "
                         "the completeness score do not run — clarity is 18%% of that score, and "
                         "a score computed without it reads as a thin brief rather than an "
                         "unclassified one")
    ap.add_argument("--cost-model", metavar="PATH",
                    help="cost-model.json, for the band table and the delivery anchor the sizing "
                         "report compares against; falls back to the shipped seed")
    ap.add_argument("--bands", action="store_true",
                    help="print the size bands, their worked exemplars and the delivery anchor, "
                         "then exit — read this before classifying, not from memory")
    ap.add_argument("--standing", action="store_true",
                    help="print the standing_work catalogue an inventory's standing_scope selects "
                         "from, then exit — select against this, not from memory")
    ap.add_argument("--weights", action="store_true", help="print the scoring weights and exit")
    ap.add_argument("--verbose", action="store_true", help="list findings on stderr as well")
    ap.add_argument("--boilerplate-threshold", type=float, default=0.2,
                    help="share of features that may share one tag justification before it is "
                         "reported as a default rather than a judgement (default 0.2)")
    args = ap.parse_args()

    if args.bands:
        bands, _, source = load_bands(args.cost_model)
        if not bands:
            print(json.dumps({"ok": False, "error": source}, indent=2))
            return 2
        print(json.dumps({"source": source, "size_bands": bands}, indent=2, ensure_ascii=False))
        return 0

    if args.standing:
        catalogue, source = load_standing_catalogue(args.cost_model)
        if not catalogue:
            print(json.dumps({"ok": False, "error": source}, indent=2))
            return 2
        print(json.dumps({"source": source, "standing_work": catalogue},
                         indent=2, ensure_ascii=False))
        return 0

    if args.weights:
        print(json.dumps({"weights": SIGNAL_WEIGHTS, "signal_points": SIGNAL_POINTS,
                          "clarity_points": CLARITY_POINTS,
                          "commitment_points": COMMITMENT_POINTS}, indent=2))
        return 0

    if not args.inventory:
        ap.error("inventory path is required unless --weights, --bands or --standing is given")

    path = Path(args.inventory)
    try:
        inv = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": f"cannot read {path}: {exc}"}, indent=2))
        return 2

    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": f"cannot read schema: {exc}"}, indent=2))
        return 2

    classification, orphans, classification_findings = None, [], []
    if args.classification:
        try:
            classification = json.loads(Path(args.classification).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(json.dumps({"ok": False, "error": f"cannot read classification: {exc}"}, indent=2))
            return 2
        try:
            cls_schema = json.loads(CLASSIFICATION_SCHEMA_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cls_schema = None
        classification_findings = (validate_schema(classification, cls_schema, cls_schema)
                                   if cls_schema else [])
        orphans = join_classification(inv, classification)
    classified = classification is not None

    findings = validate_schema(inv, schema, schema) + check_integrity(inv, classified)
    findings += [f"classification{f[1:]}" if f.startswith("$") else f
                 for f in (classification_findings if classified else [])]
    if orphans:
        findings.append(
            f"classification: {len(orphans)} classified ids are not in this inventory "
            f"(e.g. {', '.join(orphans[:3])}). The classification was made against a different "
            f"extraction — re-key it with est-estimate's classification-merge.py"
        )
    result = {
        "ok": True,
        "inventory": str(path),
        "classification": args.classification or None,
        "citations_verified": bool(args.normalized),
        "coverage": coverage(inv, classified),
        "scoring": score(inv, classified),
        # Warnings do not block pricing. A backlog of fifty near-identical CRUD screens
        # legitimately shares a justification, and refusing to estimate it would be wrong;
        # what would also be wrong is pricing it as though every band had been judged. So the
        # estimate carries these into its own assumptions instead, where a client reads them.
        "warnings": (check_boilerplate_tags(inv.get("features", []), args.boilerplate_threshold)
                     if classified else []),
    }
    if not classified:
        # Said out loud: silence here is indistinguishable from a clean sizing report.
        result["sizing"] = {"skipped": "no --classification; the tags this judges live in "
                                       "classification.json, written by est-estimate"}
        bands = band_path = None
        sizing_warnings, sizing = [], {}
    else:
        bands, band_path, band_source = load_bands(args.cost_model)
        sizing_warnings, sizing = check_sizing(inv.get("features", []), bands)
    if classified and args.cost_model and band_path != Path(args.cost_model):
        # The project has its own model and the bands were read from somewhere else. If that
        # model has ever been recalibrated, the reference class being applied here is the wrong
        # one — and a wrong reference class that nobody mentions is how this went wrong before.
        sizing_warnings.append(
            f"size_band: {args.cost_model} carries no size_bands._anchor, so the bands and "
            f"exemplars came from the shipped seed instead. If that model has been recalibrated, "
            f"re-run est-estimate's migrate-cost-model.py so the reference class matches the "
            f"hours it will actually be priced at"
        )
    if classified:
        result["sizing"] = {"anchor": band_source,
                            "distribution": result["coverage"]["size_bands"],
                            "source_lines_per_story": result["coverage"]["source_lines_per_story"]} | sizing
        result["warnings"] += sizing_warnings
    # Granularity does NOT need the classification: surfaces are set at extraction, so the one
    # sizing signal the extraction cannot re-slice its way out of is also the one that can be
    # reported before anybody has banded a single story.
    if bands is None:
        bands = load_bands(args.cost_model)[0]
    grain_warnings, grain = check_granularity(inv.get("features", []), bands)
    result["granularity"] = grain
    result["warnings"] += grain_warnings

    # Build order and foundation work. Both read before the citation pass, because both are
    # facts about the inventory alone and neither needs the normalized sources.
    seq_findings, sequence = check_sequence(inv)
    findings += seq_findings
    result["sequence"] = sequence
    catalogue, _ = load_standing_catalogue(args.cost_model)
    sw_findings, sw_warnings, standing = check_standing_overlap(inv, catalogue)
    findings += sw_findings
    result["warnings"] += sw_warnings
    result["standing_scope"] = standing
    if args.normalized:
        findings += verify_citations(inv, args.normalized) + check_anchors(inv, args.normalized)
        clipped, partial = check_quote_completeness(inv, args.normalized)
        findings += clipped
        result["warnings"] += partial
        result["unreferenced_regions"] = coverage_regions(inv, args.normalized)
        result["stale"] = check_staleness(inv, path, args.normalized)
    if args.manifest:
        findings += reconcile_manifest(inv, args.manifest)
    result["findings"] = findings
    result["ok"] = not findings

    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    if args.verbose:
        for f in findings:
            print(f, file=sys.stderr)

    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
