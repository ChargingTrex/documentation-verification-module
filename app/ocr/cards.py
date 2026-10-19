"""What the two card parsers share: the record they produce and line helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.ocr.engine import OcrLine

# A line of Latin letters (with the dots, apostrophes and hyphens names
# carry). Devanagari lines -- the Hindi rendering above an English name --
# fail this, which is what we want.
LATIN_NAME = re.compile(r"^[A-Za-z][A-Za-z .'\-]{1,80}$")
DATE = re.compile(r"(?<!\d)(\d{2})[/\-.](\d{2})[/\-.]((?:19|20)\d{2})(?!\d)")


@dataclass
class IdCardFacts:
    type: str
    #: What the printed headings say the card is, or None when unclear.
    detected_type: str | None = None
    full_name: str | None = None
    id_last4: str | None = None
    dob: str | None = None
    year_of_birth: int | None = None
    gender: str | None = None
    father_name: str | None = None
    address: dict | None = None
    phones: list[str] = field(default_factory=list)
    ocr_engine: str = "unknown"
    ocr_detail: str | None = None
    ocr_confidence: float | None = None
    checks: dict[str, bool] = field(default_factory=dict)
    #: The OCR lines with ID numbers masked -- safe to store.
    lines: list[str] = field(default_factory=list)
    #: Which sides of the card were read: ["front"], ["back"] or both.
    sides: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "type": self.type,
            "detected_type": self.detected_type,
            "sides": self.sides,
            "full_name": self.full_name,
            "id_last4": self.id_last4,
            "dob": self.dob,
            "year_of_birth": self.year_of_birth,
            "gender": self.gender,
            "father_name": self.father_name,
            "address": self.address,
            "phones": self.phones,
            "ocr_engine": self.ocr_engine,
            "ocr_detail": self.ocr_detail,
            "ocr_confidence": self.ocr_confidence,
            "checks": self.checks,
            "lines": self.lines,
        }


#: Below this, a recognised line is noise (a smudge, the edge of a Hindi
#: glyph) and must not become a name. The audit `lines` keep everything.
MIN_LINE_SCORE = 0.45


def texts(lines: list[OcrLine], min_score: float | None = MIN_LINE_SCORE) -> list[str]:
    return [
        line.text.strip()
        for line in lines
        if line.text and line.text.strip() and (min_score is None or line.score is None or line.score >= min_score)
    ]


def confidence(lines: list[OcrLine]) -> float | None:
    scores = [line.score for line in lines if line.score is not None]
    return round(sum(scores) / len(scores), 3) if scores else None


def iso_date(match: re.Match) -> str | None:
    """dd/mm/yyyy -> ISO, or None when it is not a real date."""
    import datetime

    try:
        return datetime.date(int(match.group(3)), int(match.group(2)), int(match.group(1))).isoformat()
    except ValueError:
        return None


def clean_name(value: str) -> str | None:
    value = re.sub(r"\s+", " ", value).strip(" :.-")
    return value if LATIN_NAME.match(value) else None


def looks_like(line: str, phrases: tuple[str, ...], threshold: int = 80) -> bool:
    """
    Does the line resemble one of the printed phrases, OCR slips included?

    A regex on "income tax" misses "lNCOME TAX" or "INCOMETAX DEPARTMENT
    GOVT.OFINDIA"; a fuzzy partial match does not. Used to keep a card's
    printed headings out of the name slot.
    """
    from rapidfuzz import fuzz

    text = re.sub(r"[^A-Za-z ]+", " ", line).upper().strip()
    if len(text) < 4:
        return False
    return any(fuzz.partial_ratio(text, phrase) >= threshold for phrase in phrases)


def uppercase_share(line: str) -> float:
    letters = [ch for ch in line if ch.isalpha()]
    return sum(ch.isupper() for ch in letters) / len(letters) if letters else 0.0


# --- which card is this? ------------------------------------------------------
# The printed headings say what the card is. They are read here for that one
# purpose, and never as a name.

PAN_SIGNS = (
    "INCOME TAX DEPARTMENT",
    "GOVT OF INDIA",
    "PERMANENT ACCOUNT NUMBER",
    "PERMANENT ACCOUNT NUMBER CARD",
    "FATHERS NAME",
    "SIGNATURE",
)
AADHAAR_SIGNS = (
    "GOVERNMENT OF INDIA",
    "UNIQUE IDENTIFICATION AUTHORITY OF INDIA",
    "MERA AADHAAR MERI PEHCHAAN",
    "AADHAAR",
    "AADHAR",
    "YEAR OF BIRTH",
    "UIDAI",
)
_PAN_NUMBER = re.compile(r"(?<![A-Z0-9])[A-Z]{5}\d{4}[A-Z](?![A-Z0-9])")
_AADHAAR_NUMBER = re.compile(r"(?<!\d)(?<!\d[ \t])\d{4}[ \t]?\d{4}[ \t]?\d{4}(?![ \t]?\d)")
_DEVANAGARI_PAN = re.compile(r"आयकर|विभाग|स्थायी|लेखा|संख्या")
_DEVANAGARI_AADHAAR = re.compile(r"आधार|भारत\s*सरकार|मेरा\s*आधार|मेरी\s*पहचान")


def detect_card_type(lines: list[OcrLine]) -> str | None:
    """
    "pan", "aadhaar", or None when the text says neither.

    Each printed sign counts one; the numbers' own shapes count two, since a
    PAN pattern or a 12-digit group is rarely on the other card. Ties and
    silence give None: the declared type stands and nothing is flagged.
    """
    rows_ = texts(lines, min_score=None)
    joined = "\n".join(rows_)
    pan = sum(looks_like(row, PAN_SIGNS) for row in rows_)
    aadhaar = sum(looks_like(row, AADHAAR_SIGNS) for row in rows_)
    # "GOVT OF INDIA" and "GOVERNMENT OF INDIA" resemble each other; the
    # Devanagari headings and the number shapes settle it.
    pan += 2 * bool(_PAN_NUMBER.search(joined)) + bool(_DEVANAGARI_PAN.search(joined))
    aadhaar += 2 * bool(_AADHAAR_NUMBER.search(joined)) + bool(_DEVANAGARI_AADHAAR.search(joined))
    if pan == aadhaar:
        return None
    return "pan" if pan > aadhaar else "aadhaar"
