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

    for feature in inv.get("features", []):
        fid = feature.get("id", "?")
        for i, cit in enumerate(feature.get("citations", [])):
            sid = cit.get("source_id")
            if sid not in texts:
                findings.append(
                    f"{fid}.citations[{i}]: no normalized text found for {sid} in {normalized_dir} — "
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
                f"{fid}.citations[{i}]: quote not found in {sid} "
                f"(closest match {ratio:.0%}) — {verdict}"
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


def index_anchors(text):
    """Every citable position the converter emitted for one source."""
    sheets = {}
    for match in SHEET_RE.finditer(text):
        end = text.find("\n## sheet:", match.end())
        block = text[match.end():end if end != -1 else len(text)]
        sheets[match.group(1)] = {int(r) for r in ROW_RE.findall(block)}
    return {
        "pages": {int(n) for kind, n in PAGE_RE.findall(text) if kind == "page"},
        "slides": {int(n) for kind, n in PAGE_RE.findall(text) if kind == "slide"},
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
        entries = [(f.get("id"), i, c) for f in inv.get("features", [])
                   for i, c in enumerate(f.get("citations", [])) if c.get("source_id") == sid]
        entries += [("not_scope", i, n) for i, n in enumerate(inv.get("not_scope", []))
                    if n.get("source_id") == sid]
        for owner, i, entry in entries:
            problem = resolve_location(entry.get("location"), anchors)
            if problem:
                findings.append(f"{owner}[{i}]: location '{entry.get('location')}' — {problem}")
    return findings


def coverage_regions(inv, normalized_dir, limit=40):
    """Which anchor regions of each source nothing points at.

    Turns "walk the document end to end and confirm nothing was missed" from a memory
    exercise into a short list the model only has to judge for substance.
    """
    referenced = {}
    for feature in inv.get("features", []):
        for cit in feature.get("citations", []):
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
            missing = sorted(rows - hit)
            if missing:
                unreferenced.append({"source_id": sid, "region": f"sheet '{sheet}'",
                                     "rows": missing[:limit], "row_count": len(missing)})
    return unreferenced[:limit]


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

def check_integrity(inv):
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

    for f in features:
        fid = f.get("id", "?")

        for i, cit in enumerate(f.get("citations", [])):
            sid = cit.get("source_id")
            if sid not in source_ids:
                findings.append(
                    f"{fid}.citations[{i}]: source_id '{sid}' is not in sources — "
                    f"known ids: {sorted(source_ids) or 'none'}"
                )
            lang = source_lang.get(sid, "")
            if lang and lang != working and not cit.get("quote_original"):
                findings.append(
                    f"{fid}.citations[{i}]: source {sid} is in '{lang}' but quote_original is missing — "
                    f"keep the untranslated text so a native reader can verify the extraction"
                )
            if not (cit.get("quote") or "").strip():
                findings.append(f"{fid}.citations[{i}]: quote is empty — a citation without source text proves nothing")

        tags = f.get("tags", {})
        for axis, allowed in TAG_VOCABULARY.items():
            tag = tags.get(axis)
            if not isinstance(tag, dict):
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
    surfaces are what keeps a role off work it does not do. Each is optional — an inventory
    from a two-page brief has no epics to declare — but a half-declared one is worse than
    neither, because the estimate silently mixes a declared count with a derived one.
    """
    findings = []
    features = inv.get("features", [])
    epics = inv.get("epics", [])
    epic_ids = {e.get("id") for e in epics}

    for i, epic in enumerate(epics):
        if epic.get("origin") == "synthesised" and not (epic.get("why") or "").strip():
            findings.append(f"epics[{i}] ({epic.get('id')}): synthesised but carries no 'why' — "
                            f"a grouping the source did not make has to say on what basis it was made")

    grouped = [f for f in features if f.get("epic_id")]
    if epics and len(grouped) != len(features):
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


def band_of(feature):
    tag = (feature.get("tags") or {}).get("size_band")
    return tag.get("value") if isinstance(tag, dict) else None


def source_lines(feature):
    """How many lines of the client's own document this story absorbed.

    `tasks` is where story synthesis parks the source rows; a story built straight from one
    passage has none and is measured by its citations instead.
    """
    return max(len(feature.get("tasks") or []), len(feature.get("citations") or []), 1)

def check_sizing(features, bands, floor=20, impact=0.10, ratio=1.5):
    """Is the band distribution the shape a delivered project actually had?

    Nothing here is an error and none of it blocks pricing. A migration engagement or a
    design-led build legitimately sits away from the anchor. What is not legitimate is landing
    there by accident: one extraction tagged 37% of its stories `L` against an anchor's 25% and
    priced three times over, because nothing said so out loud.

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

    if counts["XS"]:
        warnings.append(
            f"size_band: {len(counts['XS'])} of {n} stories are XS (e.g. "
            f"{', '.join(counts['XS'][:3])}), and none of the anchor's delivered stories was. "
            f"Something under two hours is usually a task inside a story — check the unit before "
            f"pricing it as one"
        )
    if counts["XL"]:
        plural = "story is" if len(counts["XL"]) == 1 else "stories are"
        warnings.append(
            f"size_band: {len(counts['XL'])} {plural} XL (e.g. {', '.join(counts['XL'][:3])}). "
            f"An XL is a signal to split, not a size — est-estimate will price a narrowing "
            f"question for each one"
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
                f"whole manual baseline. Sound if the project really is shaped that way; say so in "
                f"the extraction report. {band} is "
                f"\"{(bands[band].get('why') or '').split(',')[0].strip().lower()}\""
            )

    if row_shaped:
        # The double count. Holding the source volume at one line so the content cannot vary,
        # does the band still track how dangerous the story is? Then criticality is paid for
        # twice — here, and again through review_rate.
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
        (baseline / lines_total, anchor.get("baseline_per_requirement_h"), "source line", lines_total)
        if row_shaped else
        (baseline / n, anchor.get("baseline_per_story_h"), "story", n)
    )
    if want and rate and (rate / want >= ratio or want / rate >= ratio):
        warnings.append(
            f"size_band: the bands assign {rate:.1f}h of manual baseline per {unit}, against "
            f"{want:.1f}h in the delivery anchor ({baseline:.0f}h over {over} {unit}s). The whole "
            f"estimate scales with this, so it is worth being deliberate about"
        )

    return warnings, {"row_shaped": row_shaped,
                      "baseline_h": round(baseline, 1),
                      f"baseline_h_per_{'source_line' if row_shaped else 'story'}": round(rate, 2),
                      "anchor_expects": round(want, 2) if want else None,
                      "skipped": skipped}


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

def score(inv):
    signals = inv.get("completeness_signals", {})
    features = inv.get("features", [])

    points = {}
    for name, allowed in SIGNAL_POINTS.items():
        signal = signals.get(name)
        value = signal.get("value") if isinstance(signal, dict) else None
        points[name] = allowed.get(value, 0.0)

    if features:
        points["clarity_quality"] = sum(
            CLARITY_POINTS.get((f.get("tags", {}).get("clarity") or {}).get("value"), 0.0) for f in features
        ) / len(features)
        points["commitment_quality"] = sum(
            COMMITMENT_POINTS.get(f.get("commitment"), 0.0) for f in features
        ) / len(features)
    else:
        points["clarity_quality"] = points["commitment_quality"] = 0.0

    contributions = {k: round(points[k] * w, 4) for k, w in SIGNAL_WEIGHTS.items()}
    return {
        "input_completeness": round(sum(contributions.values()), 3),
        "points": {k: round(v, 3) for k, v in points.items()},
        "weights": SIGNAL_WEIGHTS,
        "contributions": contributions,
    }


def coverage(inv):
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
        "source_lines_per_story": round(
            sum(source_lines(f) for f in features) / len(features), 2) if features else 0,
        # Ids, not just counts: the confirmation batch needs the items themselves, and
        # re-deriving them means re-reading the inventory the script just walked.
        "sensitive_or_critical": [
            f.get("id") for f in features
            if (f.get("tags", {}).get("review_tier") or {}).get("value") in ("sensitive", "critical")
        ],
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
    ap.add_argument("--cost-model", metavar="PATH",
                    help="cost-model.json, for the band table and the delivery anchor the sizing "
                         "report compares against; falls back to the shipped seed")
    ap.add_argument("--bands", action="store_true",
                    help="print the size bands, their worked exemplars and the delivery anchor, "
                         "then exit — read this before classifying, not from memory")
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

    if args.weights:
        print(json.dumps({"weights": SIGNAL_WEIGHTS, "signal_points": SIGNAL_POINTS,
                          "clarity_points": CLARITY_POINTS,
                          "commitment_points": COMMITMENT_POINTS}, indent=2))
        return 0

    if not args.inventory:
        ap.error("inventory path is required unless --weights or --bands is given")

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

    findings = validate_schema(inv, schema, schema) + check_integrity(inv)
    result = {
        "ok": True,
        "inventory": str(path),
        "citations_verified": bool(args.normalized),
        "coverage": coverage(inv),
        "scoring": score(inv),
        # Warnings do not block pricing. A backlog of fifty near-identical CRUD screens
        # legitimately shares a justification, and refusing to estimate it would be wrong;
        # what would also be wrong is pricing it as though every band had been judged. So the
        # estimate carries these into its own assumptions instead, where a client reads them.
        "warnings": check_boilerplate_tags(inv.get("features", []), args.boilerplate_threshold),
    }
    bands, band_path, band_source = load_bands(args.cost_model)
    sizing_warnings, sizing = check_sizing(inv.get("features", []), bands)
    if args.cost_model and band_path != Path(args.cost_model):
        # The project has its own model and the bands were read from somewhere else. If that
        # model has ever been recalibrated, the reference class being applied here is the wrong
        # one — and a wrong reference class that nobody mentions is how this went wrong before.
        sizing_warnings.append(
            f"size_band: {args.cost_model} carries no size_bands._anchor, so the bands and "
            f"exemplars came from the shipped seed instead. If that model has been recalibrated, "
            f"re-run est-estimate's migrate-cost-model.py so the reference class matches the "
            f"hours it will actually be priced at"
        )
    result["sizing"] = {"anchor": band_source,
                        "distribution": result["coverage"]["size_bands"],
                        "source_lines_per_story": result["coverage"]["source_lines_per_story"]} | sizing
    result["warnings"] += sizing_warnings
    if args.normalized:
        findings += verify_citations(inv, args.normalized) + check_anchors(inv, args.normalized)
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
