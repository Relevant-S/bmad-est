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

    findings.extend(f"dependency cycle: {' -> '.join(c)}" for c in find_cycles(features))
    return findings


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
    ap.add_argument("--weights", action="store_true", help="print the scoring weights and exit")
    ap.add_argument("--verbose", action="store_true", help="list findings on stderr as well")
    args = ap.parse_args()

    if args.weights:
        print(json.dumps({"weights": SIGNAL_WEIGHTS, "signal_points": SIGNAL_POINTS,
                          "clarity_points": CLARITY_POINTS,
                          "commitment_points": COMMITMENT_POINTS}, indent=2))
        return 0

    if not args.inventory:
        ap.error("inventory path is required unless --weights is given")

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
    }
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
