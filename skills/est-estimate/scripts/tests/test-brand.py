#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Tests for brand.py — one palette, rendered into the forms documents need.

The palette used to be declared by hand in the estimate template and again in the calibration
report, and the two had already drifted on tokens they shared while the workbook had no colour
at all. These tests are about the single source holding: a token that exists in one output has
to exist in the others, and a colour must never be written into a document by hand again.
"""

import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("brand", ROOT / "scripts" / "brand.py")
brand = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(brand)

TEMPLATE = ROOT / "assets" / "report-template.html"

try:
    import openpyxl  # noqa: F401
    HAS_XLSX = True
except ImportError:
    HAS_XLSX = False


class TheSourceOfTruth(unittest.TestCase):
    def test_the_brand_is_the_companys_own_tokens_not_a_guess(self):
        """Read off relevant.software's published :root custom properties. A screenshot samples
        what a JPEG encoder decided; the site states its palette, under the names its own front
        end uses."""
        data = brand.load()
        self.assertEqual(data["palette"]["light"]["brand"], "#002c8d")
        self.assertEqual(data["palette"]["light"]["ink"], "#001035")
        self.assertIn("relevant.software", data["source"]["url"])

    def test_the_licensed_face_is_named_but_never_relied_on(self):
        """PP Mori is licensed and self-hosted behind hashed build URLs. It cannot be embedded
        in a document handed to a client, and linking the site's own woff2 breaks the moment
        the page is opened offline or the hash rotates."""
        font = brand.load()["font"]
        self.assertIn("PP Mori", font["css_family"])
        self.assertIn("Arial", font["css_family"])
        self.assertEqual(font["xlsx_family"], "Arial")
        self.assertIn("size_adjust", font["metric_overrides"])

    def test_every_light_token_has_a_dark_counterpart(self):
        """A token defined on one side only is a colour that disappears at night."""
        palette = brand.load()["palette"]
        light = {k for k in palette["light"] if not k.startswith("_")}
        dark = {k for k in palette["dark"] if not k.startswith("_")}
        self.assertEqual(light, dark)


class TheCss(unittest.TestCase):
    def setUp(self):
        self.css = brand.css()

    def test_it_defines_light_on_bare_root_and_overrides_only_for_dark(self):
        self.assertIn(":root {", self.css)
        self.assertIn("@media (prefers-color-scheme: dark)", self.css)
        self.assertLess(self.css.index(":root {"),
                        self.css.index("@media (prefers-color-scheme: dark)"))

    def test_the_fallback_face_carries_the_sites_own_metric_overrides(self):
        """So a reader without PP Mori gets Arial occupying PP Mori's space, rather than the
        same estimate reflowing differently for two people looking at it."""
        self.assertIn("@font-face", self.css)
        self.assertIn("size-adjust: 105.82%", self.css)
        self.assertIn('src: local("Arial")', self.css)

    def test_the_template_carries_a_placeholder_and_no_palette_of_its_own(self):
        """The whole point. A hex in the template is a hex that will drift."""
        html = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("__BRAND_CSS__", html)
        style = html[html.index("<style>"):html.index("</style>")]
        self.assertEqual(re.findall(r"#[0-9a-fA-F]{6}\b", style), [],
                         "a literal colour is back in the template")

    def test_every_token_the_template_uses_is_one_the_brand_defines(self):
        """The check that catches a rename. The template referred to --accent for a year after
        the palette stopped calling it that."""
        html = TEMPLATE.read_text(encoding="utf-8")
        used = set(re.findall(r"var\(--([a-z-]+)\)", html))
        defined = {k.replace("_", "-") for k in brand.load()["palette"]["light"]
                   if not k.startswith("_")} | {"font"}
        self.assertEqual(used - defined, set())


class TheWorkbookStyles(unittest.TestCase):
    @unittest.skipUnless(HAS_XLSX, "openpyxl is not installed")
    def test_it_hands_back_real_openpyxl_objects_for_every_role(self):
        style = brand.xlsx()
        for role in ("ba", "dev", "qa", "ux", "devops", "architect"):
            self.assertIn(role, style["role_fill"])
        self.assertEqual(style["header_font"].name, "Arial")

    @unittest.skipUnless(HAS_XLSX, "openpyxl is not installed")
    def test_translucent_tokens_are_flattened_rather_than_rejected(self):
        """A spreadsheet cell does not composite, and openpyxl will not take an rgba(). The
        wash has to become the colour it looks like on white, not raise."""
        self.assertEqual(len(brand.xlsx()["idle_fill"].fgColor.rgb), 8)

    def test_a_colour_that_is_neither_hex_nor_rgba_is_refused_not_guessed(self):
        with self.assertRaises(ValueError):
            brand._hex("cornflowerblue")

    def test_hex_conversion_matches_the_published_value(self):
        self.assertEqual(brand._hex("#002c8d"), "002C8D")
        self.assertEqual(brand._hex("rgba(0,0,0,0.0)"), "FFFFFF")


class NobodyElseDeclaresAPalette(unittest.TestCase):
    def test_the_calibration_report_reads_the_brand_instead_of_repeating_it(self):
        """It used to re-declare six of the same tokens by hand, and had already lost three."""
        source = (ROOT.parent / "est-calibrate" / "scripts" / "render-report.py"
                  ).read_text(encoding="utf-8")
        self.assertIn("brand", source)
        style = source[source.index("<style>"):source.index("</style>")] \
            if "<style>" in source else ""
        self.assertEqual(re.findall(r"#[0-9a-fA-F]{6}\b", style), [])


if __name__ == "__main__":
    unittest.main()
