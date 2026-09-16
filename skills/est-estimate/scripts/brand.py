#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""The company's visual identity, rendered into the two forms documents need.

`assets/brand.json` is the source. This module turns it into a CSS `:root` block for the
HTML reports and into openpyxl fills and fonts for the workbooks, so neither one carries a
hex of its own. Before this existed the palette was declared by hand in three places — the
estimate template, the calibration report and nowhere at all for the xlsx, which had no
colour — and the three had already drifted apart on the tokens they shared.

Read as a script it prints the CSS, which is how you check what a change will look like
without rendering a whole estimate:

    uv run skills/est-estimate/scripts/brand.py --css
    uv run skills/est-estimate/scripts/brand.py --roles
"""

import argparse
import json
import sys
from pathlib import Path

BRAND_PATH = Path(__file__).resolve().parent.parent / "assets" / "brand.json"


def load(path=None):
    return json.loads(Path(path or BRAND_PATH).read_text(encoding="utf-8"))


def _tokens(scope):
    """The palette as CSS custom properties. Keys become `--kebab-case`."""
    return "".join(f"    --{name.replace('_', '-')}: {value};\n"
                   for name, value in scope.items() if not name.startswith("_"))


def css(brand=None):
    """The `:root` block the report templates drop in place of a hardcoded palette.

    Light is defined on bare `:root` and dark overrides it under `prefers-color-scheme`, so
    a reader who has expressed no preference gets the brand as the company publishes it.
    The font face is declared with the site's own metric overrides against Arial: the
    document then occupies the same space whether or not PP Mori is installed, instead of
    reflowing between two readers looking at the same estimate.
    """
    brand = brand or load()
    font, pal = brand["font"], brand["palette"]
    m = font["metric_overrides"]
    out = [
        "  /* Generated from assets/brand.json by scripts/brand.py. Do not edit by hand:",
        "     this block is replaced on every render, and the palette lives in one file so",
        "     the estimate, the plan and the calibration report cannot drift apart. */",
        "  @font-face {",
        f"    font-family: \"{font['local_first']} Fallback\";",
        f"    src: local(\"{font['fallback']}\");",
        f"    size-adjust: {m['size_adjust']}; ascent-override: {m['ascent_override']};",
        f"    descent-override: {m['descent_override']}; line-gap-override: {m['line_gap_override']};",
        "  }",
        "  :root {",
        f"    --font: {font['css_family']};",
    ]
    out.append(_tokens(pal["light"]).rstrip("\n"))
    out.append("  }")
    out.append("  @media (prefers-color-scheme: dark) {")
    out.append("    :root {")
    out.append(_tokens(pal["dark"]).replace("    --", "      --").rstrip("\n"))
    out.append("    }")
    out.append("  }")
    return "\n".join(out) + "\n"


def role_colour(role, brand=None):
    """The Gantt's colour for a delivery role, or the neutral line for anything unnamed."""
    brand = brand or load()
    roles = brand["roles"]
    return roles.get(role) or brand["palette"]["light"]["line_strong"]


def _hex(value):
    """openpyxl wants `RRGGBB`. Anything with alpha is flattened onto the panel white,
    because a spreadsheet cell has no compositing and a literal `rgba(...)` is rejected."""
    value = value.strip()
    if value.startswith("#"):
        return value[1:].upper().rjust(6, "0")[:6]
    if value.startswith("rgba"):
        r, g, b, a = (float(p) for p in value[value.index("(") + 1:value.index(")")].split(","))
        return "".join(f"{round(c * a + 255 * (1 - a)):02X}" for c in (r, g, b))
    raise ValueError(f"brand.json colour {value!r} is neither a hex nor an rgba()")


def xlsx(brand=None):
    """Fills, fonts and a border for the workbooks, built once and reused per sheet.

    Returns plain dicts of openpyxl objects rather than applying anything, so the caller
    decides what a header or a bar means — this module knows the brand, not the layout.
    Raises ImportError only if openpyxl is missing, which every caller already handles by
    degrading to CSV.
    """
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    brand = brand or load()
    pal, family = brand["palette"]["light"], brand["font"]["xlsx_family"]
    fill = lambda c: PatternFill("solid", fgColor=_hex(c))  # noqa: E731
    return {
        "family": family,
        "header_fill": fill(pal["brand"]),
        "header_font": Font(name=family, bold=True, color="FFFFFF", size=11),
        "band_fill": fill(pal["brand_tint"]),
        "band_font": Font(name=family, bold=True, color=_hex(pal["ink"]), size=11),
        "body_font": Font(name=family, color=_hex(pal["ink"]), size=11),
        "muted_font": Font(name=family, color=_hex(pal["muted"]), size=10),
        "link_font": Font(name=family, color=_hex(pal["brand"]), underline="single", size=11),
        "idle_fill": fill(pal["brand_wash"]),
        "role_fill": {r: fill(c) for r, c in brand["roles"].items() if not r.startswith("_")},
        "role_font": {r: Font(name=family, color="FFFFFF", bold=True, size=10)
                      for r in brand["roles"] if not r.startswith("_")},
        "rule": Border(bottom=Side(style="thin", color=_hex(pal["line"]))),
        "wrap": Alignment(wrap_text=True, vertical="top"),
        "centre": Alignment(horizontal="center", vertical="center"),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--css", action="store_true", help="print the :root block")
    ap.add_argument("--roles", action="store_true", help="print the per-role Gantt colours")
    ap.add_argument("--brand", help="a brand.json other than the shipped one")
    args = ap.parse_args()
    brand = load(args.brand)
    if args.roles:
        for role, colour in brand["roles"].items():
            if not role.startswith("_"):
                print(f"{role:10} {colour}")
        return 0
    sys.stdout.write(css(brand))
    return 0


if __name__ == "__main__":
    sys.exit(main())
