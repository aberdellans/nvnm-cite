"""Regenerate the committed .txt extractions from the fixture PDFs.

Usage: uv run python tests/fixtures/briefs/extract_text.py

Extraction tool and version are recorded in manifest.json; the .txt files
are committed so the normalizer integration tests do not depend on
pdfplumber at run time. Page texts are joined with newlines (the normalizer
collapses all whitespace anyway).
"""

from __future__ import annotations

import json
from pathlib import Path

import pdfplumber

HERE = Path(__file__).parent


def main() -> None:
    manifest = json.loads((HERE / "manifest.json").read_text())
    out_dir = HERE / "extracted"
    out_dir.mkdir(exist_ok=True)
    for entry in manifest["documents"]:
        pdf_path = HERE / entry["file"]
        with pdfplumber.open(pdf_path) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        out = out_dir / (pdf_path.stem + ".txt")
        out.write_text(text, encoding="utf-8")
        print(f"{out.name}: {len(text)} chars from {entry['file']}")


if __name__ == "__main__":
    main()
