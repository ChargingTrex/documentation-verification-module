"""
Plain text out of an uploaded resume.

Ported from the placement portal's matching app. Two behavioural changes
from the original prototype: a file we cannot read raises (so the upload
flow can say so instead of silently extracting nothing), and PDFs go
through pdfium before PyPDF2, because a designer-template resume comes out
of PyPDF2 as one character per line.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

import PyPDF2
import docx

SUPPORTED_EXTENSIONS = {".pdf", ".docx"}


class ResumeParseError(Exception):
    """The file could not be read as a resume."""


def _normalise_whitespace(text: str) -> str:
    """
    Collapse the ragged whitespace PDF extraction produces.

    Layout-driven extraction emits runs of spaces and stray line breaks mid
    sentence; left alone they break the regex extractors ("2  years") and add
    noise to the similarity vectors.
    """
    text = text.replace(" ", " ").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return "\n".join(line.strip() for line in text.split("\n")).strip()


def _degenerate(text: str) -> bool:
    """
    One glyph per line: what PyPDF2 makes of a designer-template PDF whose
    characters are positioned individually. Nothing downstream can read it.
    """
    lines = [line for line in text.split("\n") if line.strip()]
    return bool(lines) and sum(len(line.strip()) == 1 for line in lines) / len(lines) > 0.3


def _pdf_text_pdfium(data: bytes) -> str:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(data)
    pages = []
    for page in document:
        textpage = page.get_textpage()
        get_text = getattr(textpage, "get_text_bounded", None) or textpage.get_text_range
        pages.append(get_text() or "")
    return "\n".join(pages)


def _pdf_text_pypdf2(data: bytes) -> str:
    reader = PyPDF2.PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def extract_text_from_pdf(file_obj) -> str:
    """
    pdfium first -- it reassembles words from positioned glyphs -- then PyPDF2.
    The first reader whose output is not glyph-per-line wins; failing that,
    the longest output; failing that, the last error.
    """
    data = file_obj.read() if hasattr(file_obj, "read") else bytes(file_obj)
    fallbacks: list[str] = []
    error: Exception | None = None
    for reader in (_pdf_text_pdfium, _pdf_text_pypdf2):
        try:
            text = reader(data)
        except Exception as exc:  # a corrupt file, or a reader that is not installed
            error = exc
            continue
        if text.strip() and not _degenerate(text):
            # Page breaks become blank lines rather than joining two sentences.
            return _normalise_whitespace(text)
        fallbacks.append(text)
    if fallbacks:
        return _normalise_whitespace(max(fallbacks, key=len))
    raise ResumeParseError(f"Could not read the PDF: {error}") from error


def extract_text_from_docx(file_obj) -> str:
    try:
        document = docx.Document(file_obj)
        blocks = [paragraph.text for paragraph in document.paragraphs]
        # Tables are common in resumes (skills grids, education tables) and
        # python-docx does not include them in `paragraphs`.
        for table in document.tables:
            for row in table.rows:
                blocks.extend(cell.text for cell in row.cells)
    except Exception as exc:
        raise ResumeParseError(f"Could not read the DOCX file: {exc}") from exc
    return _normalise_whitespace("\n".join(blocks))


def extract_text(file_obj, filename: str) -> str:
    """Dispatch on the file extension. Raises for anything unsupported."""
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        text = extract_text_from_pdf(file_obj)
    elif suffix == ".docx":
        text = extract_text_from_docx(file_obj)
    else:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ResumeParseError(
            f"Unsupported resume file type '{suffix or filename}'. Supported: {supported}."
        )

    if not text.strip():
        raise ResumeParseError(
            "No text could be extracted. If this is a scanned resume, upload a "
            "text-based PDF or a DOCX instead."
        )
    return text
