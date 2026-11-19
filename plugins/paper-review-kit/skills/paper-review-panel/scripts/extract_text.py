#!/usr/bin/env python3
"""Extract the text layer of a manuscript PDF (and of its supplement) for quote checking.

usage: extract_text.py MANUSCRIPT.pdf [SUPPLEMENT.pdf ...] [-o OUT.txt] [--pdftotext PATH]

Runs `pdftotext` (from poppler or xpdf) in its default reading-order mode, which keeps
two-column pages in column order. The output is UTF-8 with one form feed after each page,
Unicode NFKC-normalised so that typographic ligatures become plain letters. Line breaks are
kept so the file stays readable; check_quotes.py applies the remaining normalisation
(whitespace, line-end hyphenation, quote marks, dashes) to both sides of every comparison.

Several PDFs: give the manuscript first, then the supplement and any other documents
submitted with it. Their texts follow each other in one file, page after page, and a page
map is written next to it (manuscript.txt -> manuscript.pages.json) saying which pages
belong to which file. check_quotes.py reads the map and reports a quote as found on
"supplement p. 3" instead of "p. 15". A document is named after its file name without the
extension. With one PDF the output is as before and no map is written (a stale map from an
earlier run with several PDFs is removed).

The text is for scripts, and for reviewers to copy quotes from. Reviewers read the PDF
pages themselves, because text extraction drops figures and often garbles tables and
formulas.

Default output: the first PDF's path with the suffix .txt. Exit status 2 when pdftotext is
missing or fails.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import die, page_map_path, safe_console, write_json, write_text  # noqa: E402

INSTALL_HINT = (
    "pdftotext was not found. It is part of poppler (or xpdf). Install it, then rerun:\n"
    "  Debian/Ubuntu: sudo apt install poppler-utils\n"
    "  Fedora:        sudo dnf install poppler-utils\n"
    "  macOS:         brew install poppler\n"
    "  conda:         conda install -c conda-forge poppler\n"
    "  Windows:       a poppler build for Windows, with its bin folder on PATH\n"
    "or pass its location with --pdftotext PATH (or the PDFTOTEXT environment variable).\n"
    "Without it, quotes cannot be checked by script; say so in the report."
)


def find_pdftotext(explicit: str | None) -> str:
    candidate = explicit or os.environ.get("PDFTOTEXT")
    if candidate:
        if Path(candidate).is_file():
            return candidate
        found = shutil.which(candidate)
        if found:
            return found
        die(f"pdftotext not found at {candidate!r}.\n{INSTALL_HINT}")
    found = shutil.which("pdftotext")
    if not found:
        die(INSTALL_HINT)
    return found


def extract(pdf: Path, exe: str) -> str:
    try:
        proc = subprocess.run([exe, "-enc", "UTF-8", str(pdf), "-"], capture_output=True, check=False)
    except OSError as exc:
        die(f"could not run {exe}: {exc}\n{INSTALL_HINT}")
    if proc.returncode != 0:
        message = proc.stderr.decode("utf-8", errors="replace").strip()
        die(f"pdftotext failed on {pdf} (exit {proc.returncode}): {message}")
    text = proc.stdout.decode("utf-8", errors="replace")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return unicodedata.normalize("NFKC", text)


def page_texts(text: str) -> list[str]:
    """One string per page; pdftotext ends every page, including the last, with a form feed."""
    if not text.strip():
        return []
    if not text.endswith("\f"):
        text += "\f"
    return text.split("\f")[:-1]


def relative_name(pdf: Path, folder: Path) -> str:
    """The PDF's path as stored in the page map: relative to the text file's folder when inside it."""
    try:
        return pdf.resolve().relative_to(folder.resolve()).as_posix()
    except ValueError:
        return str(pdf.resolve())


def report_pages(name: str, pages: list[str], show: bool = True) -> None:
    words = sum(len(p.split()) for p in pages)
    if show:
        print(f"  {name}: {len(pages)} pages, {words} words")
    empty = [i + 1 for i, page in enumerate(pages) if len(page.split()) < 20]
    if not pages or words / len(pages) < 50:
        print(
            f"warning: {name}: almost no text layer (scanned or image-only PDF?). Quote checks will fail; "
            "OCR the PDF first or report that quotes could not be checked.",
            file=sys.stderr,
        )
    elif empty:
        print(f"note: {name}: pages with little or no text: {', '.join(map(str, empty))}", file=sys.stderr)


def main() -> None:
    safe_console()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pdfs", type=Path, nargs="+", metavar="PDF",
                        help="the manuscript PDF, then any supplement or other submitted PDFs")
    parser.add_argument("-o", "--out", type=Path, help="output text file (default: first PDF's path with .txt)")
    parser.add_argument("--pdftotext", help="path to the pdftotext executable")
    args = parser.parse_args()

    for pdf in args.pdfs:
        if not pdf.is_file():
            die(f"{pdf}: no such file")
    names = [pdf.stem for pdf in args.pdfs]
    if len(set(names)) < len(names):
        die("two of the PDFs have the same file name; the page map names documents by file name")
    exe = find_pdftotext(args.pdftotext)
    out = args.out or args.pdfs[0].with_suffix(".txt")
    map_path = page_map_path(out)

    if len(args.pdfs) == 1:
        text = extract(args.pdfs[0], exe)
        write_text(out, text)
        pages = page_texts(text)
        print(f"{out}: {len(pages)} pages, {len(text.split())} words")
        report_pages(names[0], pages, show=False)
        if map_path.is_file():
            map_path.unlink()
            print(f"removed {map_path}: a page map from an earlier run with several PDFs")
        return

    parts, documents, first = [], [], 1
    for pdf, name in zip(args.pdfs, names):
        pages = page_texts(extract(pdf, exe))
        report_pages(name, pages)
        parts.extend(page + "\f" for page in pages)
        documents.append({"name": name, "file": relative_name(pdf, out.parent), "first_page": first, "pages": len(pages)})
        first += len(pages)
    write_text(out, "".join(parts))
    write_json(map_path, {"text": out.name, "pages": first - 1, "documents": documents})
    spans = ", ".join(f"{d['name']} {d['first_page']}-{d['first_page'] + d['pages'] - 1}" for d in documents)
    print(f"{out}: {first - 1} pages ({spans})")
    print(f"{map_path}: page map")


if __name__ == "__main__":
    main()
