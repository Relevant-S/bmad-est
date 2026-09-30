#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Resolve the official icon for any service, on demand.

Nothing is bundled. There are 2,693 official cloud-service SVGs alone and the vendors revise
them quarterly, so a copy vendored into this repository is stale the day it lands. Icons are
looked up when a diagram needs one and written into the renderer's icon cache — which accepts
any name, so the catalogue the renderer ships with is a floor rather than a ceiling.

Three sources, ranked deliberately:

  1. **The vendors' own architecture icons** (AWS, Azure, GCP via `tf2d2/icons`). The only
     source with an icon for an individual cloud SERVICE rather than the provider's corporate
     logo, and what the reference diagram is drawn from.
  2. **SVGL** — a curated, full-colour catalogue of modern product logos.
  3. **Iconify** — 300,000 icons across 200+ sets, for the long tail.

**The ranking is explicit because search cannot be trusted.** Iconify's own results put
`mdi:railway` — a train — above the Railway logo, an insect above Fly.io, and a pixel-art glyph
above Cloudflare. Taking the top hit would put a picture of a locomotive on a client's
infrastructure diagram.

Every resolution is recorded in `assets/icons.resolved.json` with its source, id, URL, licence
and the date it was fetched, so a diagram's iconography can be audited the way its numbers are.

    uv run scripts/icons.py "Amazon Cognito" --provider aws
    uv run scripts/icons.py --ensure architecture.json
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ASSETS = HERE.parent / "assets"
SOURCES = ASSETS / "icon-sources.json"
UA = "bmad-est-architect/1.0 (architecture diagram icon resolution)"

# Words that identify the vendor rather than the service. Stripped before matching so
# "Amazon Cognito" finds "Cognito" and "Azure Cosmos DB" finds "Cosmos DB".
VENDOR_WORDS = ("amazon", "aws", "azure", "microsoft", "google cloud", "google", "gcp")


def config(path=None):
    return json.loads(Path(path or SOURCES).read_text(encoding="utf-8"))


def source(cfg, sid):
    return next(s for s in cfg["sources"] if s["id"] == sid)


def _get(url, timeout=20):
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def slug(text):
    text = (text or "").lower()
    for word in VENDOR_WORDS:
        text = re.sub(rf"\b{re.escape(word)}\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text


def _tokens(text, cfg=None):
    """Words that identify a service, with the vendor, the noise and the plan tier removed.

    Abbreviations are expanded first: AWS publishes `Amazon-Simple-Storage-Service.svg` and
    never `S3`, so a lookup for the name everybody actually says finds nothing without the
    alias table.
    """
    cfg = cfg or config()
    aliases = {k: v for k, v in (cfg.get("aliases") or {}).items() if not k.startswith("_")}
    stop = set(cfg.get("stopwords") or [])
    raw = slug(text)
    if raw in aliases:
        raw = aliases[raw]
    words = []
    for word in re.split(r"[^a-z0-9]+", raw):
        if not word:
            continue
        word = aliases.get(word, word)
        words += [w for w in word.split() if w and w not in stop]
    return words


def _match(wanted, stem, require_head=True):
    """How well a candidate file name matches a wanted service name.

    Coverage rather than "every token must appear": `Amazon RDS for PostgreSQL` has to be able
    to find `Amazon-RDS.svg`, which carries only one of its words. Extra words in the candidate
    count against it, so `Amazon-S3-on-Outposts` loses to `Amazon-Simple-Storage-Service` — the
    first version of this picked Outposts.

    Coverage alone is not enough, because it does not care WHICH word matched. The head word —
    the first one left after the vendor and the noise are stripped — has to appear, or
    "Stripe Connect Express + Stripe Billing" wins AWS's `Amazon-Connect.svg` on the strength of
    the single shared word *connect*, at 118 against a floor of 110.
    """
    if not wanted or not stem:
        return None
    if require_head and wanted[0] not in stem:
        return None
    common = set(wanted) & set(stem)
    if not common:
        return None
    coverage = len(common) / len(wanted)
    extra = len(stem) - len(common)
    return coverage * 30 - extra * 3 + (20 if stem == wanted else 0)


# ---------------------------------------------------------------- the vendors' own icons

def cloud_index(cfg, cache_dir, refresh=False):
    """The official-icon file list, fetched once and cached beside the icons.

    Cached rather than vendored: it is 2,693 paths that change when a vendor ships a new set,
    and a stale index silently resolves to last quarter's artwork.
    """
    spec = source(cfg, "cloud")
    path = Path(cache_dir) / "_cloud-index.json"
    if path.exists() and not refresh:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            pass
    tree = json.loads(_get(spec["index"], cfg.get("timeout_seconds", 20)))
    paths = [t["path"] for t in tree.get("tree", []) if t["path"].endswith(".svg")]
    index = {"fetched": date.today().isoformat(), "paths": paths,
             "truncated": bool(tree.get("truncated"))}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(index), encoding="utf-8")
    return index


def search_cloud(cfg, service, provider, index):
    """Official vendor art for a named service, preferring the service set over the resource
    set and the largest size available."""
    spec = source(cfg, "cloud")
    if provider not in (spec.get("providers") or []):
        return []
    wanted = _tokens(service, cfg)
    if not wanted:
        return []
    head = cfg.get("require_head_token", True)
    refuse = spec.get("refuse_path") or []
    hits = []
    for path in index.get("paths") or []:
        if not path.startswith(provider + "/"):
            continue
        # A CATEGORY icon is a section header in the vendor's own deck — "End User Computing",
        # "Storage" — and never a service mark. Left eligible, it answered "AWS End User Messaging
        # SMS" with the virtual-desktop category on the shared words `end` and `user`, which is a
        # substitute drawn where no official art exists: the one thing the brief rules out.
        if any(marker in path for marker in refuse):
            continue
        stem = _tokens(Path(path).stem, cfg)
        fit = _match(wanted, stem, head)
        if fit is None:
            continue
        bonus = fit
        for i, marker in enumerate(spec.get("prefer_path") or []):
            if marker in path:
                bonus += (len(spec["prefer_path"]) - i) * 4
        for i, marker in enumerate(spec.get("prefer_size") or []):
            if marker in path:
                bonus += (len(spec["prefer_size"]) - i)
        hits.append({"source": "cloud", "id": path, "score": round(spec["rank"] + bonus, 2),
                     "url": spec["raw"] + urllib.parse.quote(path),
                     "licence": spec["licence"]})
    return sorted(hits, key=lambda h: (-h["score"], h["id"]))[:5]


# ---------------------------------------------------------------- curated brand catalogues

def queries(service, cfg):
    """The search strings to try, longest first.

    A catalogue indexes `Supabase`, not `Supabase Postgres`, and `fly`, not `fly.io`. Searching
    only the literal service label found nothing for either, so the query is narrowed until it
    matches something: the label, then its identifying words, then the first word alone.
    """
    words = _tokens(service, cfg)
    out = [service]
    if words:
        out.append(" ".join(words))
        out.append(words[0])
    seen, unique = set(), []
    for q in out:
        key = q.lower().strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(q)
    return unique


def _search_json(url, timeout):
    try:
        return json.loads(_get(url, timeout))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def search_svgl(cfg, service):
    spec = source(cfg, "svgl")
    found = None
    for query in queries(service, cfg):
        found = _search_json(spec["search"].format(query=urllib.parse.quote(query)),
                             cfg.get("timeout_seconds", 20))
        if found:
            break
    if not found:
        return []
    wanted = _tokens(service, cfg)
    hits = []
    for entry in found if isinstance(found, list) else []:
        fit = _match(wanted, _tokens(entry.get("title") or "", cfg),
                     cfg.get("require_head_token", True))
        if fit is None:
            continue
        route = entry.get("route")
        url = route.get("light") if isinstance(route, dict) else route
        if not url:
            continue
        score = round(spec["rank"] + fit, 2)
        hits.append({"source": "svgl", "id": entry.get("title"), "score": score, "url": url,
                     "licence": spec["licence"]})
    return sorted(hits, key=lambda h: -h["score"])[:5]


def search_iconify(cfg, service):
    spec = source(cfg, "iconify")
    found = None
    for query in queries(service, cfg):
        found = _search_json(spec["search"].format(query=urllib.parse.quote(query)),
                             cfg.get("timeout_seconds", 20))
        if found and found.get("icons"):
            break
    if not found:
        return []
    wanted = _tokens(service, cfg)
    prefer = spec.get("prefer_prefixes") or []
    # An ALLOW list. Iconify indexes 300,000 icons and only a handful of its sets are brand
    # catalogues; everything else is UI glyphs whose names collide with product words. Denying
    # the sets that had embarrassed us was whack-a-mole, and every new one was found by somebody
    # looking at a finished diagram — `mdi:railway` for Railway, `bytesize:end` for `AWS End User
    # Messaging SMS`. A product has a brand mark or it has none.
    allow = set(spec.get("allow_prefixes") or [])
    hits = []
    for full in found.get("icons") or []:
        prefix, _, name = full.partition(":")
        if allow and prefix not in allow:
            continue
        # A set that is not on the preferred list is not necessarily a UI glyph set, but it is
        # not known to be a brand set either, so it sits below every preferred one.
        lowered = name.lower()
        if any(bad in lowered for bad in spec.get("skip_contains") or []):
            continue
        if any(lowered.endswith(bad) for bad in spec.get("skip_suffix") or []):
            continue
        # Deliberately smaller than the 20-point gap between this source and the vendors' own
        # catalogue: a brand set is the fallback for what the vendors do not publish, and at 6
        # points a step it was outscoring official AWS art for AWS's own services.
        rank = (len(prefer) - prefer.index(prefix)) * 3 if prefix in prefer else 0
        # A square mark over a lockup: `logos:supabase` is 5.17:1 and unreadable in an icon
        # slot, `logos:supabase-icon` is square.
        if spec.get("prefer_suffix") and lowered.endswith(spec["prefer_suffix"]):
            rank += 25
        fit = _match(wanted, _tokens(name, cfg), cfg.get("require_head_token", True))
        if fit is None:
            continue
        hits.append({"source": "iconify", "id": full,
                     "score": round(spec["rank"] + rank + fit, 2),
                     "url": spec["svg"].format(prefix=prefix, name=name),
                     "licence": spec["licence"]})
    return sorted(hits, key=lambda h: (-h["score"], h["id"]))[:5]


# ---------------------------------------------------------------- resolution

ASPECT = re.compile(r'viewBox="\s*[-\d.]+\s+[-\d.]+\s+([\d.]+)\s+([\d.]+)', re.I)
PAINT = re.compile(r'(?:fill|stroke|stop-color)\s*[=:]\s*["\']?\s*(#[0-9a-fA-F]{3,8}'
                   r'|rgba?\([^)]*\)|[a-zA-Z]+)', re.I)
UNPAINTED = {"none", "transparent", "inherit", "initial", "unset", "currentcolor"}
NAMED_GREY = {"black", "white", "grey", "gray", "silver", "dimgray", "dimgrey", "darkgray",
              "darkgrey", "lightgray", "lightgrey", "gainsboro", "whitesmoke"}


def aspect(svg):
    """Width over height from the viewBox, or None when it does not declare one."""
    found = ASPECT.search(svg.decode("utf-8", "replace")[:4000])
    if not found:
        return None
    try:
        width, height = float(found.group(1)), float(found.group(2))
        return width / height if height else None
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _chromatic(paint):
    """Is this paint value an actual colour, rather than ink?

    Greyscale does not count. `simple-icons` paints with `currentColor` and some brand sets
    hardcode `#000`; both render as the flat line-art the reference beats most obviously, so
    neither may pass for colour.
    """
    value = (paint or "").strip().lower()
    if not value or value in UNPAINTED or value in NAMED_GREY or value.startswith("url("):
        return False
    channels = None
    if value.startswith("#"):
        digits = value[1:]
        if len(digits) in (3, 4):
            digits = "".join(c * 2 for c in digits)
        if len(digits) in (6, 8):
            try:
                channels = [int(digits[i:i + 2], 16) for i in range(0, 6, 2)]
            except ValueError:
                return False
    elif value.startswith("rgb"):
        numbers = re.findall(r"[\d.]+", value)
        if len(numbers) >= 3:
            try:
                channels = [float(n) for n in numbers[:3]]
            except ValueError:
                return False
    if channels is None:
        return True                      # a named colour that is not in the grey list
    return max(channels) - min(channels) > 12


def colourful(svg):
    """Does this SVG carry colour of its own?

    Measured rather than inferred from the set it came from: `simple-icons:celery` and
    `thesvg-color:celery` are the same drawing and only one of them is green.
    """
    text = svg.decode("utf-8", "replace")[:200000]
    return any(_chromatic(paint) for paint in PAINT.findall(text))


def _grade(candidate, cfg):
    """Where a measured candidate sits on the acceptance ladder. Lower is better.

    0  coloured and square       the official branded icon, as asked for
    1  coloured lockup           Stripe publishes nothing else; 2.39:1 still reads
    2  monochrome and square     authentic artwork, flat — better than an illegible sliver
    3  measured, nothing else    last resort
    """
    square = candidate.get("aspect") is None or candidate["aspect"] <= cfg.get("max_aspect", 2.2)
    lockup = candidate.get("aspect") is not None \
        and candidate["aspect"] <= cfg.get("wordmark_aspect", 3.3)
    if candidate.get("colour") and square:
        return 0
    if candidate.get("colour") and lockup:
        return 1
    if square:
        return 2
    return 3


def _candidates(service, provider, cfg, cache_dir, index):
    """Everything that matched, ranked, floor applied."""
    found = []
    if provider:
        try:
            found += search_cloud(cfg, service, provider,
                                  index if index is not None else cloud_index(cfg, cache_dir))
        except (urllib.error.URLError, OSError, ValueError):
            pass
    found += search_svgl(cfg, service)
    found += search_iconify(cfg, service)
    floor = cfg.get("min_score", 110)
    return [c for c in sorted(found, key=lambda c: (-c["score"], c["source"], str(c["id"])))
            # Below the floor the honest answer is "nothing", and the caller draws the
            # capability's own glyph. Without it the resolver reached for whatever was closest:
            # an arcade game for "machines static or ssr", and another company's logo for
            # "auth orgs".
            if c["score"] >= floor]


def narrowed(service, cfg):
    """The head product name, when a full label found nothing. None when it would be a guess.

    *Celery worker + beat* narrows to *Celery* and *Fly Machines (static or SSR)* to *Fly*,
    because a product name leads. *Object storage* narrows to nothing, because `object` is a
    common noun and searching it finds whatever is closest.
    """
    words = _tokens(service, cfg)
    if len(words) < 2:
        return None
    head = words[0]
    if head in set(cfg.get("generic_heads") or []) or len(head) < 3:
        return None
    return head


def resolve(service, provider=None, cfg=None, cache_dir=None, index=None, fetched=None):
    """The best official icon for a service, or None. Never guesses: no candidate is None.

    Candidates are FETCHED AND MEASURED before one is accepted, for two properties a name cannot
    reveal:

      * **colour.** `simple-icons:celery` and `thesvg-color:celery` are the same artwork and only
        one of them is green; a set's reputation does not settle it.
      * **shape.** A brand set carries both a lockup and a square mark — `logos:supabase` is
        5.17:1 and renders as a sliver — and Stripe publishes no square variant at all.

    `fetched` carries the bytes back so the caller does not download them twice.
    """
    cfg = cfg or config()
    cache_dir = cache_dir or (ASSETS / cfg["cache_dir"])
    ranked = _candidates(service, provider, cfg, cache_dir, index)
    if not ranked:
        head = narrowed(service, cfg)
        if head:
            ranked = _candidates(head, provider, cfg, cache_dir, index)
    if not ranked:
        return None

    best = None
    for candidate in ranked[:6]:
        try:
            svg = _get(candidate["url"], cfg.get("timeout_seconds", 20))
        except (urllib.error.URLError, OSError):
            continue
        if b"<svg" not in svg[:2000]:
            continue
        shape = aspect(svg)
        candidate["aspect"] = round(shape, 2) if shape else None
        candidate["colour"] = colourful(svg)
        if candidate["aspect"] and candidate["aspect"] > cfg.get("reject_aspect", 4.0):
            # Past this there is no icon, only a strip. `thesvg-color:ping-identity` is 5.73:1 and
            # was accepted for want of anything better, which is how a built identity capability
            # ended up wearing another company's wordmark.
            continue
        grade = _grade(candidate, cfg)
        if best is None or grade < best[0]:
            best = (grade, candidate, svg)
        if grade == 0:
            break
    if best is None:
        return None
    if fetched is not None:
        fetched[best[1]["url"]] = best[2]
    return best[1]


def cache_name(found, provider=None, fallback=None):
    """The name the diagram refers to a resolved icon by, and the file it lands in.

    Derived from the ICON's identity, not the component's label, so two components that resolve
    to the same artwork share one file and one manifest row — and `repeated_icons` can see that a
    vendor's mark is drawn twice, which it could not when Supabase Postgres and Supabase Storage
    wrote `supabase-postgres.svg` and `supabase-storage.svg` with identical bytes in them.

    Official cloud art keeps its provider in front: `slug()` strips the vendor word, so AWS's and
    Azure's "Cloud Storage" would otherwise be one name and the second vendor would get the
    first one's picture. A brand logo needs no prefix — `aws-django` would say something untrue.
    """
    if not found:
        return fallback
    identity = str(found.get("id") or "")
    if found.get("source") == "cloud":
        stem = slug(Path(identity).stem)
        name = f"{provider}-{stem}" if provider and not stem.startswith(f"{provider}-") else stem
    else:
        name = slug(identity.partition(":")[2] or identity)
    # The renderer's loader accepts `^[a-z0-9][a-z0-9-]*$` and nothing else.
    name = re.sub(r"[^a-z0-9-]+", "-", (name or "").lower()).strip("-")
    return name or fallback


def normalise(icons, renderer_dir=None, timeout=120):
    """Run fetched SVGs through the RENDERER'S OWN icon transform before they are cached.

    The renderer normalises what it fetches — inlining style classes, sanitising, ensuring a
    viewBox and prefixing every internal id — and returns a cache hit verbatim. So the icons we
    put in the cache ourselves are the only ones that skip it, and they are exactly the ones that
    need it: every official AWS SVG declares `<rect id="Rectangle">`, so several on one page
    collide and a `url(#id)` gradient resolves to whichever icon loaded first.

    Calling their function rather than reimplementing it means our normalisation cannot drift
    from theirs. Returns {name: bytes} for whatever came back; a name missing from the result is
    cached raw by the caller, which is what happens when Node is not installed.
    """
    if not icons:
        return {}
    directory = Path(renderer_dir or (ASSETS / "renderer"))
    entry = directory / "node_modules" / "@eraserlabs" / "diagrams" / "dist" / "index.js"
    script = HERE / "render.mjs"
    if not entry.exists() or not script.exists() or not shutil.which("node"):
        return {}
    request = {"mode": "normalize", "rendererDir": str(directory),
               "icons": [{"name": name, "svg": svg.decode("utf-8", "replace")}
                         for name, svg in icons.items()]}
    try:
        result = subprocess.run(["node", str(script)], input=json.dumps(request),
                                capture_output=True, text=True, timeout=timeout)
        report = json.loads(result.stdout or "{}")
    except (OSError, subprocess.SubprocessError, ValueError):
        return {}
    if not report.get("ok"):
        return {}
    return {name: text.encode("utf-8")
            for name, text in (report.get("icons") or {}).items() if text}


def _store(cache_dir, writes, renderer_dir=None):
    """Write resolved icons into the renderer's cache, normalised where that is possible.

    Returns the set of names that went in raw, so the caller can say so rather than imply that
    everything was sanitised.
    """
    if not writes:
        return set()
    cache_dir.mkdir(parents=True, exist_ok=True)
    clean = normalise(writes, renderer_dir)
    raw = set()
    for name, svg in writes.items():
        body = clean.get(name)
        if body is None:
            raw.add(name)
            body = svg
        (cache_dir / f"{name}.svg").write_bytes(body)
    return raw


def ensure(name, service, provider=None, cfg=None, cache_dir=None, manifest=None, index=None,
           renderer_dir=None):
    """Put `<name>.svg` in the renderer's cache, resolving it if it is not there already.

    Returns the manifest record, or None when nothing could be resolved — in which case the
    caller keeps whatever icon it already had rather than drawing a blank.
    """
    cfg = cfg or config()
    cache_dir = Path(cache_dir or (ASSETS / cfg["cache_dir"]))
    manifest = manifest if manifest is not None else load_manifest(cfg)
    target = cache_dir / f"{name}.svg"
    if target.exists() and name in manifest:
        return manifest[name]

    fetched = {}
    found = resolve(service, provider, cfg, cache_dir, index, fetched)
    if not found:
        return None
    svg = fetched.get(found["url"])
    if svg is None:
        try:
            svg = _get(found["url"], cfg.get("timeout_seconds", 20))
        except (urllib.error.URLError, OSError):
            return None
    if b"<svg" not in svg[:2000]:
        return None
    raw = _store(cache_dir, {name: svg}, renderer_dir)
    record = {"service": service, "provider": provider, "source": found["source"],
              "id": found["id"], "url": found["url"], "licence": found["licence"],
              "aspect": found.get("aspect"), "colour": found.get("colour"),
              "normalised": name not in raw,
              "bytes": len(svg), "fetched": date.today().isoformat()}
    manifest[name] = record
    return record


def resolve_components(components, capabilities, cfg=None, cache_dir=None, manifest=None,
                       index=None, renderer_dir=None, stats=None):
    """Decide, fetch and cache an icon for every drawn thing. Returns {key: icon name}.

    A component contributes up to two keys: its own id for the software or service, and
    `<id>:runtime` for the platform service it runs inside. They are separate things and they get
    separate icons — that is the whole point of drawing one inside the other.

    **A glyph is never substituted for official art.** An earlier version gave a shared logo to
    one component and sent the rest to their capability glyph, which cost `Sentry Uptime + Web
    Vitals` its Sentry mark and `Django templates + HTMX` its Django mark. A vendor that serves
    two capabilities draws its mark twice, because that is what is true of the system. The
    capability glyph remains the fallback for a component that resolved NOTHING — and it is the
    right fallback rather than a lesser one, since the catalogue's icon for a relational store is
    a Postgres elephant and for secrets a key, which is what those components are.
    """
    cfg = cfg or config()
    cache_dir = Path(cache_dir or (ASSETS / cfg["cache_dir"]))
    manifest = manifest if manifest is not None else load_manifest(cfg)
    # Counted rather than inferred. A run with no network resolves nothing new and falls back to
    # the capability glyphs, which is the right behaviour — but a report that shows six official
    # icons where a previous run showed thirteen, and says nothing about why, is a required
    # output degrading quietly.
    stats = stats if stats is not None else {}
    stats.setdefault("looked_up", 0)
    stats.setdefault("unresolved", 0)
    stats.setdefault("index", "cached")
    if index is None:
        try:
            index = cloud_index(cfg, cache_dir)
        except (urllib.error.URLError, OSError, ValueError):
            index = {"paths": []}
            stats["index"] = "unreachable"

    # (key, product, provider, fallback glyph)
    wanted, names_only = [], []
    for component in components:
        if component.get("mode") == "actor" or not component.get("name"):
            continue
        glyph = ((capabilities.get(component.get("capability")) or {}).get("icon")
                 or component.get("icon") or "box")
        product = component.get("product")
        if product:
            wanted.append((component["id"], product, component.get("platform"), glyph))
        else:
            # No product was chosen, so there is no official icon to find and searching the
            # label would find somebody else's. The capability's own glyph is the answer.
            names_only.append((component["id"], glyph))
        runtime = component.get("runs_on") or {}
        if runtime.get("service"):
            wanted.append((f"{component['id']}:runtime", runtime["service"],
                           runtime.get("platform") or component.get("platform"), glyph))

    names, writes, fetched = dict(names_only), {}, {}
    for key, label, provider, glyph in wanted:
        stats["looked_up"] += 1
        found = resolve(label, provider, cfg, cache_dir, index, fetched)
        if not found:
            stats["unresolved"] += 1
            names[key] = glyph
            continue
        name = cache_name(found, provider, glyph)
        names[key] = name
        # No shortcut for "the resolved name happens to equal the capability glyph". `Amazon S3`
        # resolves to a name the catalogue also uses as its default, and skipping the write left
        # the art un-normalised and the resolution unrecorded — an audit trail with a hole in it
        # exactly where a reader would not think to look.
        if (cache_dir / f"{name}.svg").exists() and name in manifest:
            continue
        svg = fetched.get(found["url"])
        if svg is None:
            try:
                svg = _get(found["url"], cfg.get("timeout_seconds", 20))
            except (urllib.error.URLError, OSError):
                names[key] = glyph
                continue
        if b"<svg" not in svg[:2000]:
            names[key] = glyph
            continue
        writes[name] = svg
        manifest[name] = {"service": label, "provider": provider, "source": found["source"],
                          "id": found["id"], "url": found["url"], "licence": found["licence"],
                          "aspect": found.get("aspect"), "colour": found.get("colour"),
                          "bytes": len(svg), "fetched": date.today().isoformat()}

    raw = _store(cache_dir, writes, renderer_dir)
    for name in writes:
        manifest[name]["normalised"] = name not in raw
    return names, manifest


def load_manifest(cfg=None):
    cfg = cfg or config()
    path = ASSETS / cfg["manifest"]
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("icons", {})
    except ValueError:
        return {}


def save_manifest(icons, cfg=None):
    cfg = cfg or config()
    (ASSETS / cfg["manifest"]).write_text(json.dumps({
        "_what": "Every icon this installation has resolved, with where it came from, the "
                 "licence it carries and the date it was fetched. Icons are not bundled; this "
                 "is the audit trail for the ones that were.",
        "updated": date.today().isoformat(),
        "icons": dict(sorted(icons.items())),
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def stale(manifest, cfg=None):
    cfg = cfg or config()
    limit = cfg.get("stale_after_days", 180)
    today = date.today()
    out = []
    for name, record in (manifest or {}).items():
        try:
            age = (today - date.fromisoformat(str(record.get("fetched"))[:10])).days
        except (TypeError, ValueError):
            out.append((name, None))
            continue
        if age > limit:
            out.append((name, age))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("service", nargs="?", help="a concrete service name, e.g. 'Amazon Cognito'")
    ap.add_argument("--provider", help="aws, azure or gcp, when the service is a cloud service")
    ap.add_argument("--ensure", help="an architecture.json; resolve every component's icon")
    ap.add_argument("--refresh-index", action="store_true")
    ap.add_argument("--cache-dir")
    args = ap.parse_args()

    cfg = config()
    cache_dir = Path(args.cache_dir or (ASSETS / cfg["cache_dir"]))
    if args.refresh_index:
        index = cloud_index(cfg, cache_dir, refresh=True)
        print(json.dumps({"official_icons": len(index["paths"]),
                          "fetched": index["fetched"]}, indent=2))
        return 0

    if args.ensure:
        architecture = json.loads(Path(args.ensure).read_text(encoding="utf-8"))
        manifest = load_manifest(cfg)
        try:
            index = cloud_index(cfg, cache_dir)
        except (urllib.error.URLError, OSError, ValueError):
            index = {"paths": []}
        done, missed = [], []
        for component in architecture.get("components") or []:
            service = component.get("name")
            if not service or component.get("mode") == "actor":
                continue
            name = component.get("icon") or slug(service)
            record = ensure(name, service, component.get("platform"), cfg, cache_dir,
                            manifest, index)
            (done if record else missed).append(name)
        save_manifest(manifest, cfg)
        print(json.dumps({"resolved": len(done), "unresolved": missed,
                          "cache": str(cache_dir)}, indent=2))
        return 0

    if not args.service:
        ap.error("give a service name, or --ensure an architecture.json")
    found = resolve(args.service, args.provider, cfg, cache_dir)
    print(json.dumps(found or {"error": f"nothing resolved for {args.service!r}"}, indent=2))
    return 0 if found else 1


if __name__ == "__main__":
    sys.exit(main())
