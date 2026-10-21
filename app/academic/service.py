"""
From an uploaded marksheet or transcript to one stored record.

Text first: the PDF's own text when it has any, otherwise OCR of the image
(or the rendered first page). Then two readings of that text -- the regex
parser always, the model when it is on -- merged into one record with a
source per field, the way the CV is handled. Percentages are recomputed
from the subject rows in Python; the model's arithmetic is never used.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

from app import llm
from app.academic.parser import AcademicFacts, mask_rolls, parse_academic
from app.config import settings
from app.extraction.text import ResumeParseError, extract_text_from_pdf
from app.ocr.cards import texts
from app.ocr.engine import OCRError, get_ocr_engine
from app.llm.academic import parse_academic_facts

logger = logging.getLogger(__name__)

LLM, REGEX, NONE = "llm", "regex", "none"
#: Stated and computed percentages this close are the same figure.
PERCENT_TOLERANCE = 0.6


def read_lines(data: bytes, filename: str) -> tuple[list[str], dict]:
    """The document's text as lines, and how it was obtained."""
    if Path(filename or "").suffix.lower() == ".pdf":
        try:
            text = extract_text_from_pdf(io.BytesIO(data))
        except ResumeParseError:
            text = ""
        if len(text.strip()) >= 40:
            return [line for line in text.split("\n") if line.strip()], {"text_source": "pdf"}
    engine = get_ocr_engine()
    lines = engine.read(data, filename)
    scores = [line.score for line in lines if line.score is not None]
    return texts(lines, min_score=None), {
        "text_source": "ocr",
        "ocr_engine": engine.name,
        "ocr_detail": getattr(engine, "detail", None),
        "ocr_confidence": round(sum(scores) / len(scores), 3) if scores else None,
    }


def _pick(name, regex_value, llm_value, sources: dict, prefer: str = LLM):
    """The model's value unless it has none, else regex's; the source noted."""
    first, second = ((LLM, llm_value), (REGEX, regex_value)) if prefer == LLM else ((REGEX, regex_value), (LLM, llm_value))
    for source, value in (first, second):
        if value not in (None, "", [], {}):
            sources[name] = source
            return value
    sources[name] = NONE
    return None


def academic_record(
    declared_type: str,
    regex: AcademicFacts,
    facts: dict | None,
    meta: dict,
) -> dict:
    """One record from both readings, each field saying which one supplied it."""
    sources: dict[str, str] = {}
    facts = facts or {}
    record: dict = {
        "type": declared_type,
        "detected_type": _pick("detected_type", regex.detected_type, facts.get("document_type"), sources, prefer=REGEX),
        "full_name": _pick("full_name", regex.full_name, facts.get("full_name"), sources),
        "father_name": _pick("father_name", regex.father_name, facts.get("father_name"), sources),
        "mother_name": _pick("mother_name", regex.mother_name, facts.get("mother_name"), sources),
        "roll_last4": _pick("roll_last4", regex.roll_last4,
                            (facts.get("roll_number") or "")[-4:] or None, sources, prefer=REGEX),
        "dob": _pick("dob", regex.dob, facts.get("date_of_birth"), sources, prefer=REGEX),
        "board": _pick("board", regex.board, facts.get("board_or_university"), sources),
        "institution": _pick("institution", regex.institution, facts.get("institution"), sources),
        "year": _pick("year", regex.year, facts.get("year"), sources),
        "subjects": _pick("subjects", regex.subjects, facts.get("subjects"), sources) or [],
        "total_marks": _pick("total_marks", regex.total_marks, facts.get("total_marks"), sources),
        "max_total": _pick("max_total", regex.max_total, facts.get("max_total"), sources),
        "cgpa": _pick("cgpa", regex.cgpa, facts.get("cgpa"), sources, prefer=REGEX),
        "sgpa": _pick("sgpa", regex.sgpa, facts.get("sgpa"), sources) or [],
        "result": _pick("result", regex.result, facts.get("result"), sources, prefer=REGEX),
    }

    # The percentage: what is printed, checked against what the rows add up to.
    stated = regex.percentage if regex.percentage_source == "stated" else None
    if stated is None and facts.get("percentage") is not None:
        stated, stated_source = facts["percentage"], LLM
    else:
        stated_source = REGEX if stated is not None else NONE
    rows = [s for s in record["subjects"] if s.get("marks") is not None]
    computed = None
    if len(rows) >= 3:
        out_of = sum(s.get("max_marks") or 100.0 for s in rows)
        computed = round(sum(s["marks"] for s in rows) / out_of * 100, 2) if out_of else None
    elif record["total_marks"] and record["max_total"]:
        computed = round(record["total_marks"] / record["max_total"] * 100, 2)
    record["percentage_computed"] = computed
    if stated is not None:
        record["percentage"], record["percentage_source"], sources["percentage"] = stated, "stated", stated_source
    elif computed is not None:
        record["percentage"], record["percentage_source"], sources["percentage"] = computed, "computed", sources.get("subjects", REGEX)
    else:
        record["percentage"], record["percentage_source"], sources["percentage"] = None, None, NONE

    checks = dict(regex.checks)
    if record["detected_type"] is not None:
        checks["document_type_matches"] = record["detected_type"] == declared_type
    if stated is not None and computed is not None:
        checks["percentage_matches_rows"] = abs(stated - computed) <= PERCENT_TOLERANCE
    if record["cgpa"] is not None and record["sgpa"]:
        checks["cgpa_matches_sgpa"] = abs(record["cgpa"] - sum(record["sgpa"]) / len(record["sgpa"])) <= 0.3

    record.update({
        "checks": checks,
        "extraction_source": LLM if facts else REGEX,
        "llm_model": facts.get("model") if facts else None,
        "field_sources": sources,
        "lines": [mask_rolls(line) for line in regex.lines],
        **meta,
    })
    return record


def analyse_academic(data: bytes, filename: str, declared_type: str, *, client=None) -> dict:
    """Text out of the file, both readings, one record. Raises OCRError when unreadable."""
    lines, meta = read_lines(data, filename)
    if not lines:
        raise OCRError("No text could be read off the document.")
    regex = parse_academic(lines, declared_type)

    facts = None
    if client is not None or llm.llm_enabled():
        try:
            facts = parse_academic_facts("\n".join(lines), client=client)
        except llm.LLMUnavailable as exc:
            logger.warning("Academic reading fell back to regex: %s", exc)
    return academic_record(declared_type, regex, facts, meta)


def ocr_settings_note() -> str:
    return f"ocr={settings.ocr_engine}"
