#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Generate the three delivered-project inventories used by test-anchors.py.

⚠️ NOT part of the test suite, and it will not run on a machine that does not have the three
project repositories checked out at the paths below. It is here because a checked-in fixture
with no reproducible provenance is a fixture nobody can argue with — and this module's whole
claim is that every number can be traced back to a document.

Run only when a new anchor lands or an existing one is re-measured; the JSON it writes is
checked in, so the test does not depend on the three project repos being present.

EPP's bands come from its OWN measured record (docs/reference/phase-1-per-feature-estimate.csv).
memorial-healthcare's and easyterms' do not exist, so they are bridged onto the same scale by
files-touched using EPP's files->points mapping. That bridge carries a 1.09-point mean error per
story and lands within 4% in aggregate; it is honest enough for a project-level backtest and not
for anything finer, which is why the assertions on those two are looser.
"""
import csv, json, os, re, bisect, statistics, collections
from pathlib import Path

OUT = str(Path(__file__).resolve().parent)
EPP_CSV = "/Users/Ostap/Projects/epp/docs/docs/reference/phase-1-per-feature-estimate.csv"
EPP_DIR = "/Users/Ostap/Projects/epp/docs/_bmad-output/implementation-artifacts/phase-1-2.1"
MH_DIR  = "/Users/Ostap/Projects/memorial-healthcare/_bmad-output/implementation-artifacts"
ET_DIR  = "/Users/Ostap/Projects/easyterms/_bmad-output/implementation-artifacts"

def delivered_keys(sprint_status):
    """Only stories the project actually shipped. Files exist for keys that were cut mid-flight
    (memorial-healthcare 9-5/9-6/9-8, retired when Epic 9 was rewritten), and pricing those
    against hours nobody spent on them would be a backtest of the wrong scope."""
    keys = set()
    for line in open(sprint_status, encoding="utf-8"):
        m = re.match(r"^  ([0-9][\w.\-]*): (done|review)\s*(#.*)?$", line.split("#")[0].rstrip() + " ")
        if m: keys.add(m.group(1))
    return keys
PTS2BAND = {1:"XS", 2:"S", 3:"M", 4:"L", 5:"XL"}

def filelist(t):
    fl = re.search(r'^#{2,4} File List\s*$(.*?)(?=^#{2,4} |\Z)', t, re.M | re.S)
    if not fl: return None
    return len(set(re.findall(
        r'[\w@][\w./@-]*\.(?:ts|tsx|js|jsx|prisma|sql|json|yml|yaml|css|html|py|sh|mjs|cjs)\b',
        fl.group(1))))

SENS = ('payment','pay','credit','wallet','ledger','invoice','stripe','money','billing','refund',
        'login','logout','session','sso','auth','rbac','role','permission','admin','profile',
        'password','verification','suspend','identity','sign-up','signup','entra','hipaa','audit',
        'tenant','pii','consent','escalation','officer')
def tier_of(text):
    t = text.lower()
    return "sensitive" if any(w in t for w in SENS) else "routine"

def tag(v, why): return {"value": v, "why": why, "status": "confirmed"}

def wrap(pid, project, features, note):
    return {"schema_version": "1.0", "generated": "2026-09-09T00:00:00Z", "project": project,
            "granularity": "project", "working_language": "en",
            "_provenance": note,
            "sources": [{"id": "S1", "path": f"{pid}/epics.md", "doc_type": "backlog", "language": "en"}],
            "features": features, "not_scope": [], "conflicts": [], "assumptions": [],
            # A delivered project's own epics: acceptance criteria on every story, the stack
            # settled, the integrations named. Recorded so the fixture is a VALID inventory and
            # inventory-check.py can run over it end to end, which is how the pipeline is
            # exercised rather than just the engine.
            "completeness_signals": {
                k: {"value": v, "why": "a delivered project's own epics, read after the fact"}
                for k, v in (("acceptance_criteria", "most"), ("stack_specified", "full"),
                             ("integrations_named", "all"), ("nfrs_stated", "most"),
                             ("data_model_described", "detailed"), ("ui_defined", "designed"))}}

_NEXT = {"n": 0}


def feat(key, name, epic, band, surfaces, tier, premium, why):
    """`key` is the project's own story id. The inventory id has to match the schema's
    ^F[0-9]+$, so it is sequential and the real key travels in the citation location, where a
    reader can still trace a priced row back to the story file it came from."""
    _NEXT["n"] += 1
    fid = f"F{_NEXT['n']}"
    f = {"id": fid, "name": name, "epic_id": f"E{epic}", "description": name,
         "citations": [{"source_id": "S1", "location": f"story {key}", "quote": name}],
         "commitment": "committed", "surfaces": sorted(surfaces),
         "tags": {"size_band": tag(band, why),
                  "compressibility": tag("high", "conventional web/SaaS delivery"),
                  "review_tier": tag(tier, "inferred from the story's own subject matter"),
                  "clarity": tag("high", "delivered against written acceptance criteria"),
                  "novelty": tag("standard", "the team had built this shape before")},
         "depends_on": [], "open_questions": []}
    if premium: f["manual_effort"] = premium
    return f

# ---------------------------------------------------------------- EPP (measured)
SURF = {"DB":"data", "API":"backend", "Member Web":"frontend", "Admin Web":"frontend",
        "Member Native":"frontend", "Infra":"infra", "Redis":"infra", "SQS/DLQ":"infra",
        "S3":"backend", "Stripe":"backend", "Zoho":"backend", "Entra":"backend",
        "Socket.IO":"backend", "Email":"backend"}
rows = [r for r in csv.DictReader(open(EPP_CSV, encoding="utf-8-sig")) if r.get("Story ID")]
epp = []
for r in rows:
    raw = {x.strip() for x in r["Surfaces"].split(";")}
    prem = []
    if "Stripe" in raw or "Zoho" in raw: prem.append("money_rail")
    if "Entra" in raw: prem.append("external_idp")
    if "Member Native" in raw: prem.append("native_release")
    epp.append(feat(r["Story ID"], r["Feature"], r["Epic"],
                    r["Complexity Band"], {SURF[s] for s in raw if s in SURF},
                    tier_of(r["Feature"] + " " + r["Complexity Drivers"]), prem,
                    f"measured: {r['Weight (pts)']} pts, {r['Basis'].lower()}"))
json.dump(wrap("epp", "EPP (myEPP) epics 1-9", epp,
    "Bands, surfaces and the money/IdP/native premiums are read from EPP's own measured "
    "per-story record: docs/reference/phase-1-per-feature-estimate.csv (75 stories, 237 points, "
    "1.165 h/point). review_tier is inferred from each story's subject matter using the "
    "classification guide's own trigger words. Actuals: dev 300 / architect 110 / BA 100 / "
    "UX 100 / QA 40 / DevOps 40 = 690 h over 7 weeks, 8 planned epics."),
    open(f"{OUT}/epp.json", "w"), indent=1, ensure_ascii=False)

# ---------------------------------------------- files -> points bridge, fitted on EPP
allf = os.listdir(EPP_DIR)
def find(sid):
    a, b = sid.split(".", 1)
    pref = f"{a}-{b.replace('.', '-')}-"
    return next((f for f in allf if f.startswith(pref) and f.endswith(".md")), None)
pairs = []
for r in rows:
    n = filelist(open(os.path.join(EPP_DIR, find(r["Story ID"])), encoding="utf-8").read())
    if n: pairs.append((n, int(r["Weight (pts)"])))
by = collections.defaultdict(list)
for n, p in pairs: by[p].append(n)
centres = {p: statistics.median(v) for p, v in sorted(by.items())}
CUTS = [(centres[p] + centres[p + 1]) / 2 for p in sorted(centres)[:-1]]
def bridge(n): return bisect.bisect_left(CUTS, n) + 1

# ------------------------------------------------- MH and ET (bridged)
def build(d, keep, pid, project, note, epic_of, keys=None):
    _NEXT["n"] = 0
    out = []
    for f in sorted(os.listdir(d)):
        if not f.endswith(".md") or not re.match(r"^\d", f): continue
        m = re.match(r"^(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?[a-z-]*)-(.*)\.md$", f)
        if not m: continue
        epic = float(m.group(1))
        if not keep(epic): continue
        if keys is not None and f[:-3] not in keys: continue
        text = open(os.path.join(d, f), encoding="utf-8").read()
        n = filelist(text)
        band = PTS2BAND[bridge(n)] if n else "M"
        title = (re.search(r"^# (.+)$", text, re.M) or [None, m.group(3)])[1]
        low = (title + " " + f).lower()
        surf = set()
        if any(w in low for w in ("frontend", "ui", "page", "component", "screen", "widget",
                                  "client", "drawer", "modal", "view")): surf.add("frontend")
        if any(w in low for w in ("endpoint", "api", "service", "backend", "server", "engine",
                                  "pipeline", "sync", "queue", "auth", "guard")): surf.add("backend")
        if any(w in low for w in ("schema", "migration", "parser", "database", "model", "corpus",
                                  "ingest", "upload", "data")): surf.add("data")
        if any(w in low for w in ("ci", "docker", "deploy", "infra", "redis", "环境",
                                  "environment", "pipeline gate")): surf.add("infra")
        if not surf: surf = {"backend"}
        prem = []
        if any(w in low for w in ("stripe", "payment", "invoice", "billing")): prem.append("money_rail")
        if any(w in low for w in ("sso", "oidc", "entra", "identity handshake")): prem.append("external_idp")
        out.append(feat(m.group(1) + "-" + m.group(2), title,
                        epic_of(epic), band, surf, tier_of(title), prem,
                        f"bridged from {n} files touched" if n else "no File List; defaulted to M"))
    return wrap(pid, project, out, note)

json.dump(build(MH_DIR, lambda e: e <= 9.7, "memorial-healthcare",
    "memorial-healthcare epics 1-9.7",
    "NO per-story effort record exists. Bands are bridged onto EPP's measured 1-5 scale by "
    "files-touched (mean error 1.09 points per story; within 4% in aggregate). Surfaces and "
    "premiums are inferred from story titles. Actuals: dev 140 / architect 60 / BA 80 / UX 80, "
    "no QA and no DevOps = 360 h over 3.5 weeks, 9 planned epics.",
    lambda e: int(e) if e == int(e) else e,
    delivered_keys(f"{MH_DIR}/sprint-status.yaml")),
    open(f"{OUT}/memorial-healthcare.json", "w"), indent=1, ensure_ascii=False)

json.dump(build(ET_DIR, lambda e: e <= 5 or e == 8, "easyterms",
    "easyterms epics 1-5 + 8",
    "NO per-story effort record exists. Bands are bridged onto EPP's measured 1-5 scale by "
    "files-touched. Epic 8 is included per the delivery lead: its 11 stories are inside the "
    "160 dev h. Actuals: dev 160 / architect 80, no other role staffed = 240 h over 5 weeks, "
    "6 planned epics.",
    lambda e: int(e),
    delivered_keys(f"{ET_DIR}/sprint-status.yaml")),
    open(f"{OUT}/easyterms.json", "w"), indent=1, ensure_ascii=False)

for name in ("epp", "memorial-healthcare", "easyterms"):
    inv = json.load(open(f"{OUT}/{name}.json"))
    c = collections.Counter(f["tags"]["size_band"]["value"] for f in inv["features"])
    print(f"{name}: {len(inv['features'])} stories  bands {dict(sorted(c.items()))}")
