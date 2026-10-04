"""Text extraction with page references and extraction-problem flags.

Supported: PDF (PyMuPDF), plain text and Markdown, `.docx` and `.pptx` (read straight from the
OOXML zip; no macros or embedded objects are touched). Extraction only reads bytes: nothing in a
document is ever executed or followed.

Page model: PDFs and slides use their real page or slide number. Plain text, Markdown and Word
have no stable pages, so they are split into synthetic "pages" of about `SYNTHETIC_PAGE_CHARS`
characters so passages still carry a reference the learner can find.

Flags (stored in `document_versions.extraction_flags`):
  `low_text_pages`   page numbers with almost no text (scanned images, diagrams)
  `needs_ocr`        most of the document has no text layer and no OCR provider ran
  `ocr_pages`        pages recovered through the OCR fallback
  `truncated`        text was cut at `MAX_TEXT_CHARS`
  `empty`            nothing extractable
  `suspected_injection`  pages containing instruction-like phrases. Informational only: the text
                     is still treated as data everywhere and is not altered.
"""

import io
import re
import zipfile
from dataclasses import dataclass, field
from typing import Any, Protocol
from xml.etree import ElementTree

import pymupdf

from sg_core.knowledge.errors import ExtractionError, UnsupportedDocumentError

MAX_TEXT_CHARS = 2_000_000
MAX_PAGES = 1_000
MIN_PAGE_CHARS = 25  # fewer characters than this and a page counts as "no text layer"
SYNTHETIC_PAGE_CHARS = 3_000
MAX_ZIP_MEMBER_BYTES = 50 * 1024 * 1024  # zip-bomb guard for docx/pptx members

PDF = "application/pdf"
TEXT = "text/plain"
MARKDOWN = "text/markdown"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"

_EXTENSIONS = {
    ".pdf": PDF,
    ".txt": TEXT,
    ".md": MARKDOWN,
    ".markdown": MARKDOWN,
    ".docx": DOCX,
    ".pptx": PPTX,
}
SUPPORTED_MIME_TYPES = frozenset(_EXTENSIONS.values())

_INJECTION = re.compile(
    r"ignore (?:all |any )?(?:the )?(?:previous|prior|above) (?:instructions|prompts?)"
    r"|disregard (?:all |any )?(?:the )?(?:previous|prior|above)"
    r"|you are now\b"
    r"|new instructions:"
    r"|system prompt"
    r"|<\s*/?\s*(?:system|assistant)\s*>"
    r"|reveal (?:your|the) (?:instructions|prompt)",
    re.IGNORECASE,
)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


@dataclass(frozen=True, slots=True)
class Page:
    number: int  # 1-based
    text: str


@dataclass(slots=True)
class ExtractedDocument:
    pages: list[Page]
    flags: dict[str, Any] = field(default_factory=dict)

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def text_chars(self) -> int:
        return sum(len(p.text) for p in self.pages)


class OcrProvider(Protocol):
    """Optional fallback for pages without a text layer. Receives a rendered page image (PNG)
    and returns recognised text. Nothing is configured by default: such pages are flagged."""

    async def recognize(self, image_png: bytes) -> str: ...


def detect_mime_type(filename: str | None, declared: str | None, data: bytes) -> str:
    """Resolve the document type from magic bytes first, then the extension.

    The declared `Content-Type` is only a tiebreaker: clients can send anything.
    """
    name = (filename or "").lower()
    extension = next((ext for ext in _EXTENSIONS if name.endswith(ext)), None)
    if data.startswith(b"%PDF-"):
        return PDF
    if data.startswith(b"PK\x03\x04"):
        if extension in (".docx", ".pptx"):
            return _EXTENSIONS[extension]
        raise UnsupportedDocumentError("unsupported archive; upload PDF, DOCX, PPTX, TXT or MD")
    if extension == ".pdf":
        raise UnsupportedDocumentError("file is not a valid PDF")
    if extension in (".docx", ".pptx"):
        raise UnsupportedDocumentError(f"file is not a valid {extension[1:].upper()}")
    if extension in (".txt", ".md", ".markdown") or (declared or "").startswith("text/"):
        if b"\x00" in data[:4096]:
            raise UnsupportedDocumentError("binary data in a text upload")
        return MARKDOWN if extension in (".md", ".markdown") else TEXT
    raise UnsupportedDocumentError("unsupported file type; upload PDF, DOCX, PPTX, TXT or MD")


def clean_text(text: str) -> str:
    """Drop control characters and normalise whitespace while keeping paragraph breaks."""
    text = _CONTROL.sub(" ", text.replace("\r\n", "\n").replace("\r", "\n"))
    lines = [" ".join(line.split()) for line in text.split("\n")]
    out: list[str] = []
    blank = False
    for line in lines:
        if line:
            out.append(line)
            blank = False
        elif not blank and out:
            out.append("")
            blank = True
    return "\n".join(out).strip()


async def extract_document(
    data: bytes, mime_type: str, *, ocr: OcrProvider | None = None
) -> ExtractedDocument:
    try:
        if mime_type == PDF:
            doc = await _extract_pdf(data, ocr)
        elif mime_type in (TEXT, MARKDOWN):
            doc = _extract_plain(data)
        elif mime_type == DOCX:
            doc = _extract_docx(data)
        elif mime_type == PPTX:
            doc = _extract_pptx(data)
        else:
            raise UnsupportedDocumentError(f"unsupported type {mime_type}")
    except (UnsupportedDocumentError, ExtractionError):
        raise
    except Exception as exc:  # corrupt or hostile file: fail the version, not the worker
        raise ExtractionError(f"could not read document: {type(exc).__name__}") from exc
    return _finish(doc)


def _finish(doc: ExtractedDocument) -> ExtractedDocument:
    total = 0
    kept: list[Page] = []
    for page in doc.pages:
        if total >= MAX_TEXT_CHARS:
            doc.flags["truncated"] = True
            break
        remaining = MAX_TEXT_CHARS - total
        text = page.text
        if len(text) > remaining:
            text = text[:remaining]
            doc.flags["truncated"] = True
        kept.append(Page(page.number, text))
        total += len(text)
    doc.pages = kept
    low = [p.number for p in kept if len(p.text.strip()) < MIN_PAGE_CHARS]
    if low and len(low) < len(kept):
        doc.flags["low_text_pages"] = low
    if not any(p.text.strip() for p in kept):
        doc.flags["empty"] = True
    suspicious = [p.number for p in kept if _INJECTION.search(p.text)]
    if suspicious:
        doc.flags["suspected_injection"] = suspicious
    return doc


async def _extract_pdf(data: bytes, ocr: OcrProvider | None) -> ExtractedDocument:
    with pymupdf.open(stream=data, filetype="pdf") as pdf:  # type: ignore[no-untyped-call]
        if pdf.needs_pass:
            raise ExtractionError("PDF is password protected")
        if pdf.page_count > MAX_PAGES:
            raise ExtractionError(f"PDF has more than {MAX_PAGES} pages")
        pages: list[Page] = []
        ocr_pages: list[int] = []
        textless: list[int] = []
        for index in range(pdf.page_count):
            page = pdf[index]
            text = clean_text(page.get_text("text"))
            if len(text) < MIN_PAGE_CHARS:
                textless.append(index + 1)
                if ocr is not None:
                    png = page.get_pixmap(dpi=150).tobytes("png")
                    recognised = clean_text(await ocr.recognize(png))
                    if recognised:
                        text = recognised
                        ocr_pages.append(index + 1)
            pages.append(Page(index + 1, text))
    doc = ExtractedDocument(pages)
    if ocr_pages:
        doc.flags["ocr_pages"] = ocr_pages
    unrecovered = [n for n in textless if n not in ocr_pages]
    if pages and len(unrecovered) * 2 > len(pages):
        doc.flags["needs_ocr"] = True  # mostly scanned and no OCR available
    return doc


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


def _paginate(text: str) -> list[Page]:
    """Split on paragraph boundaries into synthetic pages of about SYNTHETIC_PAGE_CHARS."""
    pages: list[Page] = []
    current: list[str] = []
    size = 0
    for block in re.split(r"\n\s*\n", text):
        block = block.strip()
        if not block:
            continue
        if current and size + len(block) > SYNTHETIC_PAGE_CHARS:
            pages.append(Page(len(pages) + 1, "\n\n".join(current)))
            current, size = [], 0
        current.append(block)
        size += len(block) + 2
    if current:
        pages.append(Page(len(pages) + 1, "\n\n".join(current)))
    return pages


def _extract_plain(data: bytes) -> ExtractedDocument:
    return ExtractedDocument(_paginate(clean_text(_decode(data))))


def _read_member(archive: zipfile.ZipFile, name: str) -> bytes:
    info = archive.getinfo(name)
    if info.file_size > MAX_ZIP_MEMBER_BYTES:
        raise ExtractionError("document part is too large")
    return archive.read(name)


def _xml_text(xml: bytes, paragraph_tag: str, text_tag: str) -> str:
    # ElementTree does not resolve external entities; Python's expat caps entity expansion.
    root = ElementTree.fromstring(xml)
    paragraphs: list[str] = []
    for paragraph in root.iter(paragraph_tag):
        runs = [node.text or "" for node in paragraph.iter(text_tag)]
        paragraphs.append("".join(runs))
    return "\n\n".join(paragraphs)


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


def _extract_docx(data: bytes) -> ExtractedDocument:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if "word/document.xml" not in archive.namelist():
            raise ExtractionError("not a Word document")
        text = _xml_text(_read_member(archive, "word/document.xml"), f"{_W}p", f"{_W}t")
    return ExtractedDocument(_paginate(clean_text(text)))


def _extract_pptx(data: bytes) -> ExtractedDocument:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        slides = [n for n in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)]
        if not slides:
            raise ExtractionError("not a PowerPoint document")
        slides.sort(key=lambda n: int(re.findall(r"\d+", n)[-1]))
        if len(slides) > MAX_PAGES:
            raise ExtractionError(f"deck has more than {MAX_PAGES} slides")
        pages = [
            Page(i, clean_text(_xml_text(_read_member(archive, name), f"{_A}p", f"{_A}t")))
            for i, name in enumerate(slides, start=1)
        ]
    return ExtractedDocument(pages)
