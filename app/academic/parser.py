"""
A marksheet or transcript out of its text lines, without a model.

Marksheets are tables: a header naming the board and the examination, the
candidate's details under labels, subject rows with marks, a total, a
result. Transcripts (grade cards) add semester SGPAs and a CGPA. The text
comes from the PDF when it has any, otherwise from OCR; both arrive here as
lines. Roll numbers are kept as their last four characters only.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field

from app.extraction.facts import find_cgpa
from app.ocr.cards import DATE, iso_date, looks_like

TYPES = ("marksheet_10", "marksheet_12", "transcript")

BOARDS = (
    "Central Board of Secondary Education", "CBSE",
    "Council for the Indian School Certificate Examinations", "CISCE", "ICSE", "ISC",
    "National Institute of Open Schooling", "NIOS",
    "State Board of School Examinations", "Tamil Nadu State Board", "Directorate of Government Examinations",
    "Board of Secondary Education", "Board of Intermediate Education", "Board of Higher Secondary Education",
    "Maharashtra State Board", "Karnataka Secondary Education Examination Board", "Kerala Board",
    "Board of Intermediate Education Andhra Pradesh", "Telangana State Board", "West Bengal Board",
    "Bihar School Examination Board", "Uttar Pradesh Board", "Madhya Pradesh Board", "Rajasthan Board",
    "Gujarat Secondary and Higher Secondary Education Board", "Punjab School Education Board",
    "Haryana Board", "Goa Board", "Odisha Board", "Assam Board",
)
UNIVERSITY = re.compile(
    r"\b(?:university|institute\s+of\s+technology|college\s+of\s+engineering|deemed\s+to\s+be|"
    r"anna\s+university|vtu|jntu|srm|vit|amrita|nit\b|iit\b|iiit\b|bits\b)",
    re.IGNORECASE,
)
_BOARD = re.compile("|".join(re.escape(b) for b in sorted(BOARDS, key=len, reverse=True)), re.IGNORECASE)

# What says which document this is.
_TWELFTH_SIGNS = ("HIGHER SECONDARY", "SENIOR SECONDARY", "SENIOR SCHOOL CERTIFICATE", "INTERMEDIATE",
                  "CLASS XII", "12TH", "PLUS TWO", "HSC", "PRE UNIVERSITY", "SECOND YEAR PUC")
_TENTH_SIGNS = ("SECONDARY SCHOOL EXAMINATION", "SECONDARY SCHOOL CERTIFICATE", "SSLC", "CLASS X",
                "10TH", "MATRICULATION", "HIGH SCHOOL CERTIFICATE", "SSC")
_TRANSCRIPT_SIGNS = ("TRANSCRIPT", "GRADE CARD", "GRADE SHEET", "CONSOLIDATED", "SEMESTER", "CGPA", "SGPA",
                     "CREDITS", "BACHELOR OF", "MASTER OF", "B.E.", "B.TECH", "M.TECH", "DEGREE")
_TWELFTH_RE = re.compile(r"\b(?:xii|12th|hsc|hse|plus\s*two|\+2|intermediate|senior\s*secondary|higher\s*secondary|puc)\b", re.I)
_TENTH_RE = re.compile(r"\b(?:x|10th|sslc|ssc|matric(?:ulation)?|secondary\s*school)\b", re.I)
_TRANSCRIPT_RE = re.compile(r"\b(?:transcript|grade\s*card|semester|sgpa|cgpa|credits?|b\.?\s?tech|b\.?e\.?|degree|bachelor|master)\b", re.I)

# Labels.
_NAME = re.compile(
    r"^\W*(?:candidate'?s?\s*name|student'?s?\s*name|name\s*of\s*(?:the\s*)?(?:candidate|student)|name)\s*[:\-]?\s*(.*)$",
    re.IGNORECASE,
)
_FATHER = re.compile(r"^\W*(?:father'?s?|parent'?s?|guardian'?s?)\s*name\s*[:\-]?\s*(.*)$", re.IGNORECASE)
_MOTHER = re.compile(r"^\W*mother'?s?\s*name\s*[:\-]?\s*(.*)$", re.IGNORECASE)
_ROLL = re.compile(
    r"(?:roll|register(?:ed)?|registration|regn?\.?|seat|enrol(?:l)?ment|hall\s*ticket|index|admission|usn|prn)"
    r"\s*(?:no|number|num|#)?\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9/\-]{3,19})",
    re.IGNORECASE,
)
_DOB = re.compile(r"(?:date\s*of\s*birth|d\.?o\.?b\.?|born)\s*[:\-]?\s*", re.IGNORECASE)
_YEAR_LABEL = re.compile(
    r"(?:year\s*of\s*passing|passing\s*year|month\s*(?:&|and)\s*year|examination\s*(?:held\s*in|of)|held\s*in|"
    r"session|academic\s*year|year)\D{0,25}((?:19|20)\d{2})",
    re.IGNORECASE,
)
_YEAR = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
_RESULT = re.compile(r"\b(passed|pass|qualified|promoted|failed|fail|compartment|reappear|withheld)\b", re.IGNORECASE)
_PERCENT_LABEL = re.compile(r"(?:percentage|percent|aggregate|overall)\s*(?:of\s*marks)?\s*[:\-=]?\s*(\d{2,3}(?:\.\d{1,2})?)\s*%?", re.IGNORECASE)
_PERCENT = re.compile(r"(?<![\d.])(\d{2,3}(?:\.\d{1,2})?)\s*%")
_TOTAL = re.compile(
    r"\b(?:grand\s*total|total\s*(?:marks)?(?:\s*obtained)?)\s*[:\-=]?\s*(\d{2,4})(?:\s*(?:/|out\s*of|of)\s*(\d{3,4}))?",
    re.IGNORECASE,
)
_SGPA = re.compile(r"\bsgpa\s*[:\-=]?\s*(\d{1,2}(?:\.\d{1,2})?)", re.IGNORECASE)
# A subject row: a name of letters, then marks (and maybe a maximum, and a grade).
_SUBJECT_ROW = re.compile(
    r"^(?P<name>[A-Za-z][A-Za-z&.,'()/ \-]{2,40}?)\s+(?P<marks>\d{1,3}(?:\.\d{1,2})?)(?!\d)"
    r"(?:\s*(?:/|out\s*of)?\s*(?P<max>\d{2,3})(?!\d))?(?:\s+(?P<grade>[A-F][1-2+]?|[A-F]\b|O\b|S\b))?\s*$"
)
_NOT_A_SUBJECT = re.compile(
    r"\b(?:total|percentage|percent|aggregate|roll|name|date|birth|result|school|college|board|year|"
    r"marks\s*obtained|maximum|max|minimum|min|grade|subject|code|credits?|sgpa|cgpa|semester|sem\b|"
    r"page|no\.|number|dob|signature|controller|seal|"
    r"january|february|march|april|may|june|july|august|september|october|november|december|"
    r"jan|feb|mar|apr|jun|jul|aug|sept?|oct|nov|dec|session|held|examination|exam)\b",
    re.IGNORECASE,
)


@dataclass
class AcademicFacts:
    type: str
    detected_type: str | None = None
    full_name: str | None = None
    father_name: str | None = None
    mother_name: str | None = None
    roll_last4: str | None = None
    dob: str | None = None
    board: str | None = None
    institution: str | None = None
    year: int | None = None
    subjects: list[dict] = field(default_factory=list)
    total_marks: float | None = None
    max_total: float | None = None
    percentage: float | None = None
    #: "stated" (printed on the sheet), "computed" (from the rows), or None.
    percentage_source: str | None = None
    #: Percentage the subject rows add up to, when they do -- for the stated figure to be checked against.
    percentage_computed: float | None = None
    cgpa: float | None = None
    sgpa: list[float] = field(default_factory=list)
    result: str | None = None
    checks: dict[str, bool] = field(default_factory=dict)
    lines: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "type": self.type, "detected_type": self.detected_type, "full_name": self.full_name,
            "father_name": self.father_name, "mother_name": self.mother_name, "roll_last4": self.roll_last4,
            "dob": self.dob, "board": self.board, "institution": self.institution, "year": self.year,
            "subjects": self.subjects, "total_marks": self.total_marks, "max_total": self.max_total,
            "percentage": self.percentage, "percentage_source": self.percentage_source,
            "percentage_computed": self.percentage_computed, "cgpa": self.cgpa, "sgpa": self.sgpa,
            "result": self.result, "checks": self.checks, "lines": self.lines,
        }


def detect_academic_type(lines: list[str]) -> str | None:
    """
    marksheet_10, marksheet_12, transcript, or None when the text says none clearly.

    Each printed sign counts one; the regex over the whole text counts two.
    A 12th sheet's "HIGHER SECONDARY" shares words with a 10th sheet's
    "SECONDARY SCHOOL", so a tie between the two goes to the 12th, whose
    signs are the more specific; any other tie is None.
    """
    joined = "\n".join(lines)
    scores = {
        "marksheet_12": sum(looks_like(l, _TWELFTH_SIGNS, 88) for l in lines) + 2 * bool(_TWELFTH_RE.search(joined)),
        "marksheet_10": sum(looks_like(l, _TENTH_SIGNS, 88) for l in lines) + 2 * bool(_TENTH_RE.search(joined)),
        "transcript": sum(looks_like(l, _TRANSCRIPT_SIGNS, 88) for l in lines) + 2 * bool(_SGPA.search(joined))
                      + bool(UNIVERSITY.search(joined)) + bool(re.search(r"\bcgpa\b", joined, re.I)),
    }
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    (best, top), (runner_up, second) = ranked[0], ranked[1]
    if top == 0:
        return None
    if top == second:
        return "marksheet_12" if {best, runner_up} == {"marksheet_10", "marksheet_12"} else None
    return best


def mask_rolls(line: str) -> str:
    return _ROLL.sub(lambda m: m.group(0)[: m.start(1) - m.start(0)] + "XXXX" + m.group(1)[-4:], line)


def _clean(value: str | None) -> str | None:
    if not value:
        return None
    value = re.sub(r"\s+", " ", value).strip(" :.-|")
    value = re.sub(r"\s*(?:father|mother|dob|date of birth|roll).*$", "", value, flags=re.IGNORECASE).strip(" :.-")
    return value if 2 <= len(value) <= 80 and re.search(r"[A-Za-z]", value) else None


def _value_after(rows: list[str], index: int, match: re.Match) -> str | None:
    inline = _clean(match.group(1))
    if inline and not re.fullmatch(r"[\W_]*", inline):
        return inline
    for row in rows[index + 1 : index + 3]:
        if row and not _NOT_A_SUBJECT.search(row) and re.search(r"[A-Za-z]{2,}", row) and not _YEAR.search(row):
            return _clean(row)
    return None


def _subjects(rows: list[str]) -> list[dict]:
    subjects = []
    for row in rows:
        match = _SUBJECT_ROW.match(row.strip())
        if not match:
            continue
        name = match.group("name").strip()
        if _NOT_A_SUBJECT.search(name) or len(name) < 3:
            continue
        marks = float(match.group("marks"))
        maximum = float(match.group("max")) if match.group("max") else None
        if maximum is not None and marks > maximum:
            continue
        if maximum is None and marks > 100:
            continue
        subjects.append({"name": name, "marks": marks, "max_marks": maximum or 100.0, "grade": match.group("grade")})
    return subjects


def parse_academic(lines: list[str], declared_type: str, today: datetime.date | None = None) -> AcademicFacts:
    rows = [line.strip() for line in lines if line and line.strip()]
    facts = AcademicFacts(type=declared_type, lines=[mask_rolls(row) for row in rows])
    joined = "\n".join(rows)
    today = today or datetime.date.today()

    facts.detected_type = detect_academic_type(rows)
    if facts.detected_type is not None:
        facts.checks["document_type_matches"] = facts.detected_type == declared_type

    for index, row in enumerate(rows):
        if facts.father_name is None and (m := _FATHER.match(row)):
            facts.father_name = _value_after(rows, index, m)
        elif facts.mother_name is None and (m := _MOTHER.match(row)):
            facts.mother_name = _value_after(rows, index, m)
        elif facts.full_name is None and (m := _NAME.match(row)):
            facts.full_name = _value_after(rows, index, m)

    if m := _ROLL.search(joined):
        facts.roll_last4 = m.group(1)[-4:]

    for row in rows:
        if _DOB.search(row) and (d := DATE.search(row)) and (iso := iso_date(d)):
            facts.dob = iso
            break

    if m := _BOARD.search(joined):
        facts.board = m.group(0)
    for row in rows:
        if UNIVERSITY.search(row) and len(row) < 90 and not _NOT_A_SUBJECT.search(row):
            facts.institution = row
            break
    if facts.board is None and facts.institution:
        facts.board = facts.institution

    if m := _YEAR_LABEL.search(joined):
        facts.year = int(m.group(1))
    else:
        years = [int(y) for y in _YEAR.findall(joined) if 1950 <= int(y) <= today.year]
        facts.year = max(years) if years else None

    if m := _RESULT.search(joined):
        word = m.group(1).lower()
        facts.result = {"passed": "PASS", "pass": "PASS", "qualified": "PASS", "promoted": "PASS",
                        "failed": "FAIL", "fail": "FAIL", "compartment": "COMPARTMENT", "reappear": "REAPPEAR",
                        "withheld": "WITHHELD"}[word]

    facts.subjects = _subjects(rows)
    if m := _TOTAL.search(joined):
        facts.total_marks = float(m.group(1))
        if m.group(2):
            facts.max_total = float(m.group(2))

    if m := _PERCENT_LABEL.search(joined) or _PERCENT.search(joined):
        value = float(m.group(1))
        if 0 < value <= 100:
            facts.percentage, facts.percentage_source = round(value, 2), "stated"
    if len(facts.subjects) >= 3:
        got = sum(s["marks"] for s in facts.subjects)
        out_of = sum(s["max_marks"] for s in facts.subjects)
        if out_of:
            facts.percentage_computed = round(got / out_of * 100, 2)
            if facts.total_marks is None:
                facts.total_marks, facts.max_total = got, out_of
    elif facts.total_marks is not None and facts.max_total:
        facts.percentage_computed = round(facts.total_marks / facts.max_total * 100, 2)
    if facts.percentage is None and facts.percentage_computed is not None:
        facts.percentage, facts.percentage_source = facts.percentage_computed, "computed"
    if facts.percentage is not None and facts.percentage_computed is not None and facts.percentage_source == "stated":
        facts.checks["percentage_matches_rows"] = abs(facts.percentage - facts.percentage_computed) <= 0.6

    facts.cgpa = find_cgpa(joined)
    facts.sgpa = [round(float(v), 2) for v in _SGPA.findall(joined) if 0 < float(v) <= 10]
    if facts.cgpa is None and facts.sgpa and declared_type == "transcript":
        facts.cgpa = round(sum(facts.sgpa) / len(facts.sgpa), 2)
    return facts
