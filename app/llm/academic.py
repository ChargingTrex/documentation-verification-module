"""The model's reading of a marksheet or transcript, validated."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.llm.client import LLMClient, get_client
from app.llm.prompts import _UNTRUSTED_RULE
from app.llm.resume import _ask
from app.llm.schema import MAX_LIST_ITEMS, _as_number_or_none, _as_iso_date, _fit_entries, _fit_list, _fit_text

ACADEMIC_SYSTEM_PROMPT = f"""You extract facts from an Indian school marksheet or a college transcript (grade card) for a document verification desk.
{_UNTRUSTED_RULE}

Return exactly these keys:
{{
  "document_type": "marksheet_10"|"marksheet_12"|"transcript"|null,   // 10th standard, 12th standard, or a college/university grade card
  "full_name": string|null,            // the candidate's / student's name as printed
  "father_name": string|null,
  "mother_name": string|null,
  "roll_number": string|null,          // roll / register / seat / enrolment number as printed
  "date_of_birth": "YYYY-MM-DD"|null,
  "board_or_university": string|null,  // e.g. "CBSE", "Tamil Nadu State Board", "Anna University"
  "institution": string|null,          // school or college name, if printed
  "year": integer|null,                // year of passing / examination
  "subjects": [{{"name": string, "marks": number|null, "max_marks": number|null, "grade": string|null}}],
  "total_marks": number|null,
  "max_total": number|null,
  "percentage": number|null,           // only if printed on the document
  "cgpa": number|null,                 // on a 10-point scale, only if printed
  "sgpa": [number],                    // semester GPAs in order, transcripts only
  "result": string|null                // e.g. "PASS", "FAIL", "COMPARTMENT"
}}
Copy numbers exactly as printed. Do not compute a percentage or a total yourself.
"""


class _Reply(BaseModel):
    model_config = ConfigDict(extra="ignore")


class SubjectEntry(_Reply):
    name: str | None = Field(None, max_length=100)
    marks: float | None = Field(None, ge=0, le=1000)
    max_marks: float | None = Field(None, ge=1, le=1000)
    grade: str | None = Field(None, max_length=10)


class AcademicFactsModel(_Reply):
    document_type: Literal["marksheet_10", "marksheet_12", "transcript"] | None = None
    full_name: str | None = Field(None, max_length=150)
    father_name: str | None = Field(None, max_length=150)
    mother_name: str | None = Field(None, max_length=150)
    roll_number: str | None = Field(None, max_length=40)
    date_of_birth: str | None = Field(None, max_length=20)
    board_or_university: str | None = Field(None, max_length=200)
    institution: str | None = Field(None, max_length=200)
    year: int | None = Field(None, ge=1950, le=2100)
    subjects: list[SubjectEntry] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)
    total_marks: float | None = Field(None, ge=0, le=10000)
    max_total: float | None = Field(None, ge=1, le=10000)
    percentage: float | None = Field(None, ge=0, le=100)
    cgpa: float | None = Field(None, ge=0, le=10)
    sgpa: list[float] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)
    result: str | None = Field(None, max_length=30)


_TYPE_WORDS = [
    ("marksheet_12", re.compile(r"12|xii|hsc|higher|senior|intermediate|plus", re.I)),
    ("marksheet_10", re.compile(r"10|\bx\b|sslc|ssc|secondary|matric", re.I)),
    ("transcript", re.compile(r"transcript|grade|degree|semester|college|university|b\.?tech|b\.?e", re.I)),
]


def _clamp_type(value):
    if value in ("marksheet_10", "marksheet_12", "transcript"):
        return value
    if isinstance(value, str):
        for kind, pattern in _TYPE_WORDS:
            if pattern.search(value):
                return kind
    return None


def _fit_subject(entry: dict) -> dict:
    entry = dict(entry)
    entry["name"] = _fit_text(entry.get("name"), 100)
    entry["grade"] = _fit_text(entry.get("grade"), 10) if isinstance(entry.get("grade"), str) else None
    for key in ("marks", "max_marks"):
        entry[key] = _as_number_or_none(entry.get(key))
    return entry


def normalise_academic_reply(data: dict) -> dict:
    data = dict(data)
    data["document_type"] = _clamp_type(data.get("document_type"))
    for key, limit in (("full_name", 150), ("father_name", 150), ("mother_name", 150), ("roll_number", 40),
                       ("board_or_university", 200), ("institution", 200), ("result", 30)):
        value = data.get(key)
        data[key] = _fit_text(str(value) if isinstance(value, (int, float)) else value, limit)
    data["date_of_birth"] = _as_iso_date(data.get("date_of_birth"))
    for key in ("total_marks", "max_total", "percentage", "cgpa"):
        data[key] = _as_number_or_none(data.get(key))
    year = _as_number_or_none(data.get("year"))
    data["year"] = int(year) if year is not None and 1950 <= year <= 2100 else None
    if data.get("percentage") is not None and not 0 <= data["percentage"] <= 100:
        data["percentage"] = None
    if data.get("cgpa") is not None and not 0 <= data["cgpa"] <= 10:
        data["cgpa"] = None
    subjects = [s for s in (data.get("subjects") or []) if isinstance(s, dict)]
    data["subjects"] = _fit_entries(subjects, _fit_subject)
    sgpa = data.get("sgpa")
    if isinstance(sgpa, str):
        sgpa = [part for part in re.split(r"[,\s]+", sgpa) if part]
    data["sgpa"] = [v for v in (_as_number_or_none(x) for x in _fit_list(sgpa)) if v is not None and 0 <= v <= 10]
    return data


def parse_academic_facts(text: str, client: LLMClient | None = None) -> dict:
    """The model's reading, validated. Raises LLMUnavailable to send callers to regex."""
    client = client or get_client()
    data = _ask(client, ACADEMIC_SYSTEM_PROMPT, text, normalise_academic_reply, AcademicFactsModel)
    data["model"] = client.model
    return data
