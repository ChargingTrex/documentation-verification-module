"""
A PAN card out of OCR lines.

Two layouts are in circulation. The 2018+ card labels every field ("Name",
"Father's Name", "Date of Birth") with the value on the next line or after
the label; the older card prints name, father's name and DOB unlabelled
under the department header. The PAN itself is five letters, four digits,
one letter; the fourth letter is P for an individual.
"""

from __future__ import annotations

import re

from app.ocr.cards import DATE, LATIN_NAME, IdCardFacts, clean_name, confidence, iso_date, texts
from app.ocr.engine import OcrLine

PAN = re.compile(r"(?<![A-Z0-9])([A-Z]{5}\d{4}[A-Z])(?![A-Z0-9])")
_NAME_LABEL = re.compile(r"^\W*(?:नाम\s*/?\s*)?name\b\s*[:\-]?\s*(.*)$", re.IGNORECASE)
_FATHER_LABEL = re.compile(r"^\W*(?:पिता\s*का\s*नाम\s*/?\s*)?father'?s?\s*name\b\s*[:\-]?\s*(.*)$", re.IGNORECASE)
_DOB_LABEL = re.compile(r"(?:date\s*of\s*birth|जन्म\s*की\s*तारीख|dob)", re.IGNORECASE)
_LABEL = re.compile(
    r"income\s*tax|govt|government|\bindia\b|permanent\s*account|\bcard\b|signature|hastakshar|"
    r"\bname\b|father|date\s*of\s*birth|\bdob\b|आयकर|विभाग|भारत|सरकार|नाम|पिता|जन्म|स्थायी|लेखा|"
    r"^\W*$",
    re.IGNORECASE,
)


def _is_name_line(line: str) -> bool:
    return bool(LATIN_NAME.match(line)) and not _LABEL.search(line) and not PAN.search(line) and len(line) >= 3


def mask_pan(line: str) -> str:
    return PAN.sub(lambda m: f"XXXXXX{m.group(1)[-4:]}", line)


def _value_after(rows_: list[str], index: int, label_match: re.Match) -> str | None:
    """The field's value: on the label's own line if present, else the next Latin line."""
    inline = clean_name(label_match.group(1)) if label_match.group(1) else None
    if inline:
        return inline
    for row in rows_[index + 1 : index + 3]:
        if _is_name_line(row):
            return clean_name(row)
    return None


def parse_pan(lines: list[OcrLine], engine_name: str = "unknown", engine_detail: str | None = None) -> IdCardFacts:
    rows_ = texts(lines)
    facts = IdCardFacts(type="pan", ocr_engine=engine_name, ocr_detail=engine_detail, ocr_confidence=confidence(lines))
    facts.lines = [mask_pan(row) for row in texts(lines, min_score=None)]
    facts.sides = ["front"]
    joined = "\n".join(rows_)

    if pan := PAN.search(joined):
        facts.id_last4 = pan.group(1)[-4:]
        facts.checks["pan_format"] = True
        facts.checks["pan_individual"] = pan.group(1)[3] == "P"
    else:
        facts.checks["pan_format"] = False

    for row in rows_:
        if (date := DATE.search(row)) and (iso := iso_date(date)):
            facts.dob = iso
            break

    # Labelled layout first.
    for index, row in enumerate(rows_):
        if facts.father_name is None and (match := _FATHER_LABEL.match(row)):
            facts.father_name = _value_after(rows_, index, match)
        elif facts.full_name is None and (match := _NAME_LABEL.match(row)):
            facts.full_name = _value_after(rows_, index, match)

    # Unlabelled (older) layout: the first two Latin lines are name, then father.
    if facts.full_name is None:
        candidates = [clean_name(row) for row in rows_ if _is_name_line(row)]
        candidates = [c for c in candidates if c]
        if candidates:
            facts.full_name = candidates[0]
            if facts.father_name is None and len(candidates) > 1:
                facts.father_name = candidates[1]
    return facts
