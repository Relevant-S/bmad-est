#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""What this company has delivered in — read from `{memory}/architecture-preferences.md`.

Three sub-scores depend on it and all three report `null` without it. That is the point: a
team-fit score of 5 invented from nothing reads exactly like a team-fit score of 5 that was
measured, and nobody argues with a number.

The file is markdown for the human who fills it in, with one fenced `yaml` block the scripts
read. `UNANSWERED` in any field means absent — never a value, and never a quiet default.
"""

import re
from pathlib import Path

UNANSWERED = "UNANSWERED"
FIELDS = ("delivered_in", "house_platforms", "existing_subscriptions",
          "will_not_run", "will_not_buy")


def parse(text):
    """The fenced yaml block, with every UNANSWERED field resolved to None.

    Returns `{field: list | None}`. None means nobody has answered; an empty list means
    somebody answered "none", and those are different claims.
    """
    match = re.search(r"```ya?ml\n(.*?)```", text or "", re.S)
    if not match:
        return {f: None for f in FIELDS}
    try:
        import yaml
        block = yaml.safe_load(match.group(1)) or {}
    except ImportError:                                         # pragma: no cover - env-specific
        block = {}
        for line in match.group(1).splitlines():
            if ":" in line and not line.strip().startswith("#"):
                key, _, value = line.partition(":")
                block[key.strip()] = value.strip()
    out = {}
    for field in FIELDS:
        value = block.get(field)
        if value is None or (isinstance(value, str) and value.strip() == UNANSWERED):
            out[field] = None
        elif isinstance(value, str):
            out[field] = [v.strip() for v in value.split(",") if v.strip()]
        else:
            out[field] = list(value)
    return out


def load(path):
    path = Path(path) if path else None
    if not path or not path.exists():
        return {f: None for f in FIELDS}
    return parse(path.read_text(encoding="utf-8"))


def knows(prefs, technology):
    """Whether a named technology has a delivered project behind it.

    Returns None — not False — when nobody has answered, so a caller can tell "we have never
    shipped this" from "nobody has said".
    """
    delivered = prefs.get("delivered_in")
    if delivered is None:
        return None
    wanted = technology.strip().lower()
    return any(wanted == d.strip().lower() for d in delivered)
