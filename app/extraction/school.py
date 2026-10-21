"""
School marks a resume states: the 10th and 12th standard results.

Indian resumes list them under Education as one line each -- "Class X,
CBSE, 2019 - 92.4%" or "HSC (Tamil Nadu State Board), 2021, 88%". This
reads those lines so `/verify` can hold them against the marksheets.
"""

from __future__ import annotations

import re

_TWELFTH = re.compile(
    r"\b(?:12th|xii|hsc|hsce|hse|higher\s*secondary|senior\s*secondary|intermediate|"
    r"plus\s*two|\+\s*2|class\s*12|grade\s*12|puc|pre[\s-]*university|a[\s-]?levels?)\b",
    re.IGNORECASE,
)
_TENTH = re.compile(
    r"\b(?:10th|x|sslc|ssc|matric(?:ulation)?|secondary\s*school|class\s*10|grade\s*10|"
    r"high\s*school|o[\s-]?levels?)\b",
    re.IGNORECASE,
)
_PERCENT = re.compile(r"(?<![\d.])(\d{2,3}(?:\.\d{1,2})?)\s*%")
_PERCENT_WORD = re.compile(r"(?:percentage|percent|aggregate|marks)\s*[:\-=]?\s*(\d{2,3}(?:\.\d{1,2})?)", re.IGNORECASE)
_CGPA = re.compile(r"(?:cgpa|gpa)\s*[:\-=]?\s*(\d{1,2}(?:\.\d{1,2})?)", re.IGNORECASE)
_YEAR = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
BOARDS = (
    "CBSE", "Central Board of Secondary Education", "ICSE", "ISC", "CISCE", "NIOS", "IB", "IGCSE",
    "Tamil Nadu State Board", "State Board", "Maharashtra Board", "Karnataka Board", "Kerala Board",
    "Andhra Pradesh Board", "Telangana Board", "West Bengal Board", "Bihar Board", "UP Board",
    "MP Board", "Rajasthan Board", "Gujarat Board", "Punjab Board", "Haryana Board", "Matriculation Board",
)
_BOARD = re.compile("|".join(re.escape(b) for b in sorted(BOARDS, key=len, reverse=True)), re.IGNORECASE)


def _stage_facts(line: str, following: str) -> dict | None:
    window = line if (_PERCENT.search(line) or _CGPA.search(line) or _PERCENT_WORD.search(line)) else f"{line} {following}"
    percentage = cgpa = None
    if match := _PERCENT.search(window) or _PERCENT_WORD.search(window):
        value = float(match.group(1))
        if 30 <= value <= 100:
            percentage = round(value, 2)
    if match := _CGPA.search(window):
        value = float(match.group(1))
        if 0 < value <= 10:
            cgpa = round(value, 2)
    if percentage is None and cgpa is None:
        return None
    board = _BOARD.search(window)
    years = [int(y) for y in _YEAR.findall(window)]
    return {
        "percentage": percentage,
        "cgpa": cgpa,
        "board": board.group(0) if board else None,
        "year": max(years) if years else None,
    }


def find_school_marks(text: str) -> dict:
    """{"tenth": {...} | None, "twelfth": {...} | None} -- percentage, cgpa, board, year."""
    lines = [line.strip() for line in (text or "").split("\n")]
    result: dict = {"tenth": None, "twelfth": None}
    for index, line in enumerate(lines):
        if not line:
            continue
        following = lines[index + 1] if index + 1 < len(lines) else ""
        if result["twelfth"] is None and _TWELFTH.search(line):
            result["twelfth"] = _stage_facts(line, following)
        elif result["tenth"] is None and _TENTH.search(line) and not _TWELFTH.search(line):
            result["tenth"] = _stage_facts(line, following)
    return result
