#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["python-docx>=1.1", "openpyxl>=3.1", "pypdf>=4.0", "python-pptx>=0.6"]
# ///
"""Convert project source documents into normalized markdown with stable location anchors.

Every converted file carries anchors a citation can point at: page markers for PDFs,
sheet and row markers for workbooks, heading paths for documents. Without anchors the
extraction step cannot produce a verifiable `location`, and traceability collapses.

Emits a JSON manifest describing what was converted, by what, and what could not be read.
Formats it cannot handle are reported with needs_native_read so the caller falls back to
reading the original file directly rather than silently losing it.
"""

import argparse
import csv
import json
import re
import shutil
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

TEXT_SUFFIXES = {".md", ".markdown", ".txt", ".text", ".rst"}
SUPPORTED = TEXT_SUFFIXES | {
    ".csv", ".tsv", ".xlsx", ".xlsm", ".docx", ".pdf", ".pptx",
    ".html", ".htm", ".eml", ".json",
}


def _optional(module_name, attr=None):
    """Import an optional dependency, returning None when it is unavailable."""
    try:
        mod = __import__(module_name, fromlist=["*"] if attr else [])
    except ImportError:
        return None
    return getattr(mod, attr) if attr else mod


class _HTMLText(HTMLParser):
    SKIP = {"script", "style", "head"}

    def __init__(self):
        super().__init__()
        self.parts = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip_depth += 1
        elif tag in ("p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if not self._skip_depth and data.strip():
            self.parts.append(data.strip())

    def text(self):
        return re.sub(r"\n{3,}", "\n\n", " ".join(self.parts).replace(" \n ", "\n"))


def _column_labels(count):
    """Spreadsheet-style column labels: A, B, ... Z, AA, AB."""
    labels = []
    for i in range(count):
        name, n = "", i
        while True:
            name = chr(ord("A") + n % 26) + name
            n = n // 26 - 1
            if n < 0:
                break
        labels.append(name)
    return labels


def _rows_to_markdown(numbered_rows):
    """Render (source_row_number, cells) pairs, preserving the source's own coordinates.

    The row number emitted is the row's real position in the source file, never a
    re-derived count, because a citation of "sheet 'Backlog' row 14" is only verifiable
    if 14 means what it says. No row is designated the header: which row carries column
    names is a question about meaning, and meaning is the model's job, not this script's.
    """
    if not numbered_rows:
        return ""
    width = max(len(cells) for _, cells in numbered_rows)
    out = ["| row | " + " | ".join(_column_labels(width)) + " |",
           "| --- " * (width + 1) + "|"]
    for number, cells in numbered_rows:
        rendered = [("" if c is None else str(c)).replace("|", "\\|").replace("\n", "<br>")
                    for c in cells]
        rendered += [""] * (width - len(rendered))
        out.append(f"| {number} | " + " | ".join(rendered) + " |")
    return "\n".join(out)


def convert_text(path):
    return path.read_text(encoding="utf-8", errors="replace"), "passthrough", None


def convert_json(path):
    raw = path.read_text(encoding="utf-8", errors="replace")
    try:
        return "```json\n" + json.dumps(json.loads(raw), indent=2, ensure_ascii=False) + "\n```", "json", None
    except json.JSONDecodeError:
        return "```\n" + raw + "\n```", "json (unparsed)", "file is not valid JSON; included verbatim"


def convert_csv(path):
    delim = "\t" if path.suffix.lower() == ".tsv" else None
    if delim is None:
        try:
            with path.open(encoding="utf-8-sig", errors="replace", newline="") as fh:
                delim = csv.Sniffer().sniff(fh.read(4096), delimiters=",;\t|").delimiter
        except (csv.Error, OSError):
            delim = ","
    # Read the file object, not splitlines(): a quoted field may legitimately contain a
    # newline, and splitting on newlines first tears it in half and shifts every row after it.
    numbered, previous = [], 0
    with path.open(encoding="utf-8-sig", errors="replace", newline="") as fh:
        reader = csv.reader(fh, delimiter=delim)
        for cells in reader:
            numbered.append((previous + 1, cells))
            previous = reader.line_num
    return _rows_to_markdown(numbered), "csv", None


def convert_xlsx(path):
    load_workbook = _optional("openpyxl", "load_workbook")
    if load_workbook is None:
        return None, None, "openpyxl not installed"
    wb = load_workbook(path, data_only=True, read_only=True)
    chunks = []
    for name in wb.sheetnames:
        ws = wb[name]
        # Number by the sheet's own row index, then drop blanks. Numbering after filtering
        # would renumber the survivors and every citation below a blank row would be wrong.
        numbered = [(n, list(cells)) for n, cells in enumerate(ws.iter_rows(values_only=True), start=1)
                    if any(c is not None and str(c).strip() for c in cells)]
        if not numbered:
            continue
        # Sheet marker is the citation anchor: location becomes "sheet 'Backlog' row 14".
        chunks.append(f"## sheet: {name}\n\n{_rows_to_markdown(numbered)}")
    wb.close()
    if not chunks:
        return "", "openpyxl", "workbook contains no non-empty sheets"
    return "\n\n".join(chunks), "openpyxl", None


def convert_docx(path):
    Document = _optional("docx", "Document")
    if Document is None:
        return None, None, "python-docx not installed"
    doc = Document(str(path))
    out = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        style = (para.style.name or "").lower()
        if style.startswith("heading"):
            level = "".join(ch for ch in style if ch.isdigit()) or "1"
            out.append(f"{'#' * min(int(level), 6)} {text}")
        elif style.startswith("list"):
            out.append(f"- {text}")
        else:
            out.append(text)
    for n, table in enumerate(doc.tables, start=1):
        rows = [(i, [cell.text.strip() for cell in row.cells])
                for i, row in enumerate(table.rows, start=1)]
        if rows:
            out.append(f"### table {n}\n\n{_rows_to_markdown(rows)}")
    return "\n\n".join(out), "python-docx", None


def convert_pdf(path):
    """pdftotext first (fast, layout-aware), pypdf as fallback. Page markers are the anchors."""
    if shutil.which("pdftotext"):
        try:
            res = subprocess.run(
                ["pdftotext", "-layout", "-enc", "UTF-8", str(path), "-"],
                capture_output=True, text=True, timeout=180,
            )
            if res.returncode == 0 and res.stdout.strip():
                pages = res.stdout.split("\f")
                body = "\n\n".join(
                    f"<!-- page {n} -->\n\n{p.strip()}" for n, p in enumerate(pages, 1) if p.strip()
                )
                return body, "pdftotext", None
        except (subprocess.SubprocessError, OSError):
            pass

    PdfReader = _optional("pypdf", "PdfReader")
    if PdfReader is None:
        return None, None, "pdftotext produced nothing and pypdf not installed"
    reader = PdfReader(str(path))
    parts = []
    for n, page in enumerate(reader.pages, 1):
        text = (page.extract_text() or "").strip()
        if text:
            parts.append(f"<!-- page {n} -->\n\n{text}")
    if not parts:
        return None, None, "no extractable text; likely a scanned PDF, read the original directly"
    return "\n\n".join(parts), "pypdf", None


def convert_pptx(path):
    Presentation = _optional("pptx", "Presentation")
    if Presentation is None:
        return None, None, "python-pptx not installed"
    prs = Presentation(str(path))
    out = []
    for n, slide in enumerate(prs.slides, 1):
        lines = [f"<!-- slide {n} -->"]
        for shape in slide.shapes:
            if shape.has_text_frame and shape.text_frame.text.strip():
                lines.append(shape.text_frame.text.strip())
        if len(lines) > 1:
            out.append("\n\n".join(lines))
    return "\n\n".join(out), "python-pptx", None


def convert_html(path):
    parser = _HTMLText()
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    return parser.text(), "html.parser", None


def convert_eml(path):
    import email
    from email import policy

    msg = email.message_from_bytes(path.read_bytes(), policy=policy.default)
    head = "\n".join(
        f"**{f}:** {msg[f]}" for f in ("From", "To", "Cc", "Date", "Subject") if msg[f]
    )
    body_part = msg.get_body(preferencelist=("plain", "html"))
    body = body_part.get_content() if body_part else ""
    if body_part is not None and body_part.get_content_type() == "text/html":
        parser = _HTMLText()
        parser.feed(body)
        body = parser.text()
    return f"{head}\n\n---\n\n{body}", "email", None


CONVERTERS = {
    ".csv": convert_csv, ".tsv": convert_csv,
    ".xlsx": convert_xlsx, ".xlsm": convert_xlsx,
    ".docx": convert_docx,
    ".pdf": convert_pdf,
    ".pptx": convert_pptx,
    ".html": convert_html, ".htm": convert_html,
    ".eml": convert_eml,
    ".json": convert_json,
}


def collect(paths):
    files = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            files.extend(sorted(f for f in p.rglob("*") if f.is_file() and not f.name.startswith(".")))
        elif p.is_file():
            files.append(p)
        else:
            files.append(p)  # recorded as missing downstream
    return files


def convert_one(path, out_dir, index):
    entry = {
        "id": f"S{index}",
        "path": str(path),
        "suffix": path.suffix.lower(),
        "converted_path": None,
        "converter": None,
        "chars": 0,
        "needs_native_read": False,
        "warning": None,
    }
    if not path.exists():
        entry["warning"] = "file not found"
        entry["needs_native_read"] = True
        return entry

    suffix = path.suffix.lower()
    try:
        if suffix in TEXT_SUFFIXES:
            body, converter, warning = convert_text(path)
        elif suffix in CONVERTERS:
            body, converter, warning = CONVERTERS[suffix](path)
        else:
            entry["warning"] = f"unsupported extension {suffix or '(none)'}"
            entry["needs_native_read"] = True
            return entry
    except Exception as exc:  # a malformed file must not abort the whole batch
        entry["warning"] = f"{type(exc).__name__}: {exc}"
        entry["needs_native_read"] = True
        return entry

    if body is None:
        entry["warning"] = warning
        entry["needs_native_read"] = True
        return entry

    header = f"<!-- source: {path} | converter: {converter} -->\n\n"
    target = out_dir / f"{entry['id']}-{re.sub(r'[^A-Za-z0-9._-]+', '-', path.stem)[:60]}.md"
    target.write_text(header + body, encoding="utf-8")

    entry.update(
        converted_path=str(target),
        converter=converter,
        chars=len(body),
        warning=warning,
        needs_native_read=len(body.strip()) == 0,
    )
    return entry


def main():
    ap = argparse.ArgumentParser(
        description="Convert source documents to normalized markdown with citable location anchors.",
        epilog="Exit codes: 0 all converted, 1 some need native reading, 2 nothing usable.",
    )
    ap.add_argument("paths", nargs="+", help="files or directories to convert")
    ap.add_argument("--out-dir", required=True, help="directory to write normalized markdown into")
    ap.add_argument("-o", "--output", help="write the JSON manifest here instead of stdout")
    ap.add_argument("--verbose", action="store_true", help="report each conversion to stderr")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    sources = []
    for i, path in enumerate(collect(args.paths), start=1):
        entry = convert_one(path, out_dir, i)
        sources.append(entry)
        if args.verbose:
            state = entry["converter"] or f"UNREAD ({entry['warning']})"
            print(f"{entry['id']} {path} -> {state}", file=sys.stderr)

    converted = [s for s in sources if not s["needs_native_read"]]
    manifest = {
        "out_dir": str(out_dir),
        "total": len(sources),
        "converted": len(converted),
        "needs_native_read": [s["id"] for s in sources if s["needs_native_read"]],
        "missing_converters": sorted(
            {s["warning"] for s in sources if s["warning"] and "not installed" in s["warning"]}
        ),
        "sources": sources,
    }

    text = json.dumps(manifest, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)

    if not converted:
        return 2
    return 1 if manifest["needs_native_read"] else 0


if __name__ == "__main__":
    sys.exit(main())
