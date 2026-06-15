"""Document text extraction for the verifier: bytes in, text out, in memory.

Formats: plain text / markdown, DOCX (stdlib zipfile + XML, including
footnotes and endnotes, where briefs put half their citations), and PDF
via pdfplumber. pdfplumber is a runtime dependency (DECISIONS 2026-06-14):
a legal brief is almost always a PDF, so ``nvnm-cite check brief.pdf`` must
work out of the box. The import stays guarded so the package still loads if
pdfplumber is somehow absent (the caller then gets an honest "upload .docx
or .txt" error rather than an ImportError). Nothing here touches the
filesystem: the caller hands bytes, gets text, and both go out of scope
together.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from xml.etree import ElementTree

try:  # runtime dependency; the verifier degrades honestly if it is missing
    import pdfplumber
except ImportError:  # pragma: no cover - exercised only in broken installs
    pdfplumber = None

PDF_PAGE_CAP = 400
# Below this many extracted characters per page a PDF is almost certainly
# an image-only scan (the Mata ECF 21 affirmation measures ~62 chars/page
# of ECF header stamps; see DECISIONS 2026-06-11).
SCAN_SUSPECT_CHARS_PER_PAGE = 120


class ExtractError(ValueError):
    """The document cannot be turned into text; message is user-facing."""


@dataclass(frozen=True)
class Extraction:
    text: str
    method: str
    warning: str | None = None


def _decode_text(data: bytes) -> tuple[str, str]:
    for encoding in ("utf-8", "cp1252"):
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1"), "latin-1"


_DOCX_PARTS = (
    "word/document.xml",
    "word/footnotes.xml",
    "word/endnotes.xml",
)


def _docx_part_text(xml_bytes: bytes) -> str:
    """Visible text of one WordprocessingML part, paragraphs as lines."""
    root = ElementTree.fromstring(xml_bytes)
    pieces: list[str] = []
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag == "t" and element.text:
            pieces.append(element.text)
        elif tag == "tab":
            pieces.append("\t")
        elif tag in ("br", "cr"):
            pieces.append("\n")
        elif tag == "p":
            pieces.append("\n")
    return "".join(pieces)


def _extract_docx(data: bytes) -> Extraction:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ExtractError("not a valid .docx file (corrupt zip container)") from exc
    names = set(archive.namelist())
    if "word/document.xml" not in names:
        raise ExtractError("not a valid .docx file (no word/document.xml)")
    parts: list[str] = []
    for part in _DOCX_PARTS:
        if part in names:
            try:
                parts.append(_docx_part_text(archive.read(part)))
            except ElementTree.ParseError as exc:
                raise ExtractError(f"malformed XML in {part}") from exc
    return Extraction(text="\n".join(parts), method="docx")


def _extract_pdf(data: bytes) -> Extraction:
    if pdfplumber is None:
        raise ExtractError(
            "PDF support is not installed on this machine; upload the brief "
            "as .docx or .txt, or paste its text"
        )
    warning = None
    pages: list[str] = []
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            page_count = len(pdf.pages)
            for page in pdf.pages[:PDF_PAGE_CAP]:
                pages.append(page.extract_text() or "")
    except Exception as exc:  # pdfplumber raises a zoo of types on bad files
        raise ExtractError(f"could not parse PDF: {exc}") from exc
    if page_count > PDF_PAGE_CAP:
        warning = f"only the first {PDF_PAGE_CAP} of {page_count} pages were read"
    text = "\n\n".join(pages)
    if page_count and len(text) / page_count < SCAN_SUSPECT_CHARS_PER_PAGE:
        warning = (
            "this PDF has almost no text layer (likely an image-only scan); "
            "citations inside scanned pages cannot be read"
        )
    return Extraction(text=text, method=f"pdf ({page_count} pages)", warning=warning)


_EXT_RE = re.compile(r"\.([A-Za-z0-9]+)$")


def extract_text(data: bytes, filename: str) -> Extraction:
    """Extract checkable text from a document, format by extension with
    content-based fallbacks (PDF magic, zip magic)."""
    if not data:
        raise ExtractError("the uploaded file is empty")
    match = _EXT_RE.search(filename or "")
    ext = match.group(1).lower() if match else ""

    if data[:5] == b"%PDF-" or ext == "pdf":
        return _extract_pdf(data)
    if data[:2] == b"PK" or ext == "docx":
        if _looks_docx(data):
            return _extract_docx(data)
        raise ExtractError(
            f"unsupported zip-based format .{ext or '?'}; supported: .pdf, .docx, .txt, .md"
        )
    if ext in ("txt", "md", "text", ""):
        text, encoding = _decode_text(data)
        return Extraction(text=text, method=f"plain text ({encoding})")
    raise ExtractError(
        f"unsupported file type .{ext}; supported: .pdf, .docx, .txt, .md"
    )


def _looks_docx(data: bytes) -> bool:
    try:
        return "word/document.xml" in zipfile.ZipFile(io.BytesIO(data)).namelist()
    except zipfile.BadZipFile:
        return False
