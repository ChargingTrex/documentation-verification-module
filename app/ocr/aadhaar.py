"""
An Aadhaar card out of OCR lines.

Front: a Hindi name, the English name, "DOB: dd/mm/yyyy" (or "Year of Birth:
yyyy"), the gender, and the 12-digit number. Back: "Address:" and the
address ending in a PIN code, the number again. The name is the Latin line
nearest above the DOB line that is not a label; the number must pass its
Verhoeff check. Only the last four digits leave this module.
"""

from __future__ import annotations

import re

from app.extraction.address import describe_address
from app.extraction.facts import find_phones
from app.ocr import verhoeff
from app.ocr.cards import (
    DATE,
    LATIN_NAME,
    IdCardFacts,
    clean_name,
    confidence,
    detect_card_type,
    iso_date,
    looks_like,
    texts,
)
from app.ocr.engine import OcrLine

#: What the card prints besides the holder's details; a line resembling one
#: of these, even garbled, is never a name.
PRINTED = (
    "GOVERNMENT OF INDIA",
    "UNIQUE IDENTIFICATION AUTHORITY OF INDIA",
    "MERA AADHAAR MERI PEHCHAAN",
    "AADHAAR",
    "YEAR OF BIRTH",
    "DATE OF BIRTH",
)

# Twelve digits in 4-4-4 (or run together). Neither preceded nor followed by
# another digit group, so the last twelve digits of a 16-digit VID do not match.
NUMBER = re.compile(r"(?<!\d)(?<!\d[ \t])(\d{4})[ \t]?(\d{4})[ \t]?(\d{4})(?![ \t]?\d)")
_DOB = re.compile(r"(?:dob|d\.o\.b|date\s*of\s*birth|जन्म\s*तिथि)\s*[:\-]?\s*", re.IGNORECASE)
_YOB = re.compile(r"(?:year\s*of\s*birth|yob|जन्म\s*वर्ष)\s*[:\-]?\s*((?:19|20)\d{2})", re.IGNORECASE)
_GENDER = re.compile(r"\b(male|female|transgender)\b|(पुरुष|महिला)", re.IGNORECASE)
_ADDRESS = re.compile(r"^\W*(?:address|पता)\b\s*[:\-]?\s*", re.IGNORECASE)
_RELATION = re.compile(r"^\W*(?:s/o|d/o|w/o|c/o)\b\s*[:\-]?\s*", re.IGNORECASE)
_PIN = re.compile(r"(?<!\d)[1-9]\d{5}(?!\d)")
_LABEL = re.compile(
    r"government\s*of\s*india|unique\s*identification|authority\s*of\s*india|aadha?ar|"
    r"भारत\s*सरकार|आधार|mera\s*aadhaar|meri\s*pehcha?an|help@|uidai|www\.|\b1947\b|"
    r"issue\s*date|download\s*date|enrol|\bvid\b|address|^\W*to\b|s/o|d/o|w/o|c/o|"
    r"dob|date\s*of\s*birth|year\s*of\s*birth|\bmale\b|\bfemale\b|transgender|"
    r"identity|citizenship|proof|verify|qr|signature|^\W*$",
    re.IGNORECASE,
)


def _is_name_line(line: str) -> bool:
    return (
        bool(LATIN_NAME.match(line))
        and len(line) >= 3
        and not _LABEL.search(line)
        and not looks_like(line, PRINTED)
    )


def mask_numbers(line: str) -> str:
    return NUMBER.sub(lambda m: f"XXXX XXXX {m.group(3)}", line)


def parse_aadhaar(lines: list[OcrLine], engine_name: str = "unknown", engine_detail: str | None = None) -> IdCardFacts:
    rows_ = texts(lines)
    facts = IdCardFacts(
        type="aadhaar", ocr_engine=engine_name, ocr_detail=engine_detail, ocr_confidence=confidence(lines)
    )
    facts.lines = [mask_numbers(row) for row in texts(lines, min_score=None)]
    facts.detected_type = detect_card_type(lines)
    if facts.detected_type is not None:
        facts.checks["card_type_matches"] = facts.detected_type == "aadhaar"
    joined = "\n".join(rows_)

    # --- number ---
    numbers = [m for m in NUMBER.finditer(joined)]
    facts.checks["aadhaar_number_found"] = bool(numbers)
    if numbers:
        valid = [m for m in numbers if verhoeff.validate("".join(m.groups()))]
        chosen = (valid or numbers)[0]
        facts.id_last4 = chosen.group(3)
        facts.checks["aadhaar_checksum"] = bool(valid)

    # --- birth ---
    dob_index: int | None = None
    for index, row in enumerate(rows_):
        if _DOB.search(row):
            dob_index = index
            if (date := DATE.search(row)) and (iso := iso_date(date)):
                facts.dob = iso
            elif index + 1 < len(rows_) and (date := DATE.search(rows_[index + 1])) and (iso := iso_date(date)):
                facts.dob = iso
            break
        if yob := _YOB.search(row):
            dob_index = index
            facts.year_of_birth = int(yob.group(1))
            break
    if facts.dob:
        facts.year_of_birth = int(facts.dob[:4])

    # --- gender ---
    if gender := _GENDER.search(joined):
        word = (gender.group(1) or gender.group(2)).lower()
        facts.gender = {"male": "M", "female": "F", "transgender": "O", "पुरुष": "M", "महिला": "F"}[word]

    # --- name: nearest Latin line above the DOB line, else the first one ---
    candidates = [index for index, row in enumerate(rows_) if _is_name_line(row)]
    if dob_index is not None:
        above = [index for index in candidates if index < dob_index]
        if above:
            facts.full_name = clean_name(rows_[above[-1]])
    if facts.full_name is None and candidates:
        facts.full_name = clean_name(rows_[candidates[0]])

    # --- address (back side) ---
    start = next((i for i, row in enumerate(rows_) if _ADDRESS.match(row) or _RELATION.match(row)), None)
    if start is not None:
        chunk = []
        first = _ADDRESS.sub("", rows_[start], count=1).strip()
        if first:
            chunk.append(first)
        for row in rows_[start + 1 : start + 7]:
            if NUMBER.search(row) or _LABEL.search(row) and not _RELATION.match(row):
                break
            chunk.append(row)
            if _PIN.search(row):
                break
        if chunk:
            facts.address = describe_address(", ".join(chunk))

    # --- a printed mobile (back side, sometimes) -- never the Aadhaar digits ---
    facts.phones = find_phones(NUMBER.sub(" ", joined))
    facts.sides = ["back" if facts.address and not facts.full_name else "front"]
    return facts


def merge_aadhaar(front: IdCardFacts | None, back: IdCardFacts | None) -> IdCardFacts:
    """
    One card out of its two sides.

    Identity fields come from the front (the back only when the front lacks
    them), the address from the back. Both sides print the number: when both
    were read, their last four digits must agree -- a mismatch means the two
    images are not the same card, which is a check the reviewer must see.
    """
    if front is None and back is None:
        raise ValueError("At least one side is needed.")
    if front is None or back is None:
        single = front or back
        single.sides = ["front"] if front else ["back"]
        return single

    merged = IdCardFacts(type="aadhaar", ocr_engine=front.ocr_engine, ocr_detail=front.ocr_detail)
    merged.sides = ["front", "back"]
    for name in ("full_name", "dob", "year_of_birth", "gender", "father_name"):
        setattr(merged, name, getattr(front, name) or getattr(back, name))
    merged.address = back.address or front.address
    merged.phones = list(dict.fromkeys(front.phones + back.phones))
    merged.id_last4 = front.id_last4 or back.id_last4
    scores = [s for s in (front.ocr_confidence, back.ocr_confidence) if s is not None]
    merged.ocr_confidence = round(sum(scores) / len(scores), 3) if scores else None
    merged.lines = [f"front: {line}" for line in front.lines] + [f"back: {line}" for line in back.lines]

    merged.detected_type = front.detected_type or back.detected_type
    merged.checks = {**back.checks, **front.checks}
    if "card_type_matches" in front.checks or "card_type_matches" in back.checks:
        merged.checks["card_type_matches"] = front.checks.get("card_type_matches", True) and back.checks.get(
            "card_type_matches", True
        )
    merged.checks["aadhaar_number_found"] = bool(front.id_last4 or back.id_last4)
    if "aadhaar_checksum" in front.checks or "aadhaar_checksum" in back.checks:
        merged.checks["aadhaar_checksum"] = bool(
            front.checks.get("aadhaar_checksum", back.checks.get("aadhaar_checksum"))
            and back.checks.get("aadhaar_checksum", front.checks.get("aadhaar_checksum"))
        )
    if front.id_last4 and back.id_last4:
        merged.checks["aadhaar_sides_agree"] = front.id_last4 == back.id_last4
    return merged
