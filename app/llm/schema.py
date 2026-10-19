"""
The shape a model reply must fit, and the cleaning that happens before it is
checked.

Strict about shape (a list is a list), lenient about content: a reply with
one odd value is cleaned, not thrown away. Ported from the portal's DRF
serializers to Pydantic; the field names are unchanged so downstream
consumers need no remapping.
"""

from __future__ import annotations

import datetime
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.extraction.facts import (
    EDUCATION_ORDER,
    MAX_PLAUSIBLE_YEARS,
    find_education_levels,
    highest_education_level,
)

Level = Literal["UG", "Masters", "PG"]
Kind = Literal["internship", "part_time", "full_time", "volunteer", "freelance"]

#: Lists in a reply are cut to this many items rather than rejected.
MAX_LIST_ITEMS = 100


class _Reply(BaseModel):
    model_config = ConfigDict(extra="ignore")


class EducationEntry(_Reply):
    degree: str | None = Field(None, max_length=200)
    level: Level | None = None
    field: str | None = Field(None, max_length=200)
    institution: str | None = Field(None, max_length=200)
    start: str | None = Field(None, max_length=20)
    end: str | None = Field(None, max_length=20)
    cgpa: float | None = Field(None, ge=0, le=10)


class ExperienceEntry(_Reply):
    role: str | None = Field(None, max_length=200)
    organization: str | None = Field(None, max_length=200)
    kind: Kind | None = None
    start: str | None = Field(None, max_length=20)
    end: str | None = Field(None, max_length=20)
    is_current: bool = False
    summary: str | None = Field(None, max_length=1000)


class ProjectEntry(_Reply):
    title: str | None = Field(None, max_length=200)
    tech_stack: list[str] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)


class ResumeFactsModel(_Reply):
    full_name: str | None = Field(None, max_length=150)
    emails: list[str] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)
    phones: list[str] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)
    address: str | None = Field(None, max_length=500)
    age: int | None = Field(None, ge=0, le=120)
    date_of_birth: str | None = Field(None, max_length=20)
    cgpa: float | None = Field(None, ge=0, le=10)
    education: list[EducationEntry] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)
    experience: list[ExperienceEntry] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)
    skills: list[str] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)
    projects: list[ProjectEntry] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)
    certifications: list[str] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)
    links: list[str] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)


class JobFactsModel(_Reply):
    title: str | None = Field(None, max_length=200)
    canonical_role: str | None = Field(None, max_length=100)
    required_skills: list[str] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)
    nice_to_have: list[str] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)
    min_experience_years: float | None = Field(None, ge=0, le=MAX_PLAUSIBLE_YEARS)
    education_levels: list[Level] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)


# --- coercions ----------------------------------------------------------------

# Generic words a model uses for the three levels, for what the degree
# patterns in `extraction/facts.py` do not already read. Whole words only.
_LEVEL_WORDS = [
    ("PG", re.compile(r"\b(?:ph\.?\s?d|doctor\w*)\b", re.IGNORECASE)),
    ("Masters", re.compile(r"\b(?:master'?s?|post[\s-]?grad\w*|pg(?:\s+diploma)?)\b", re.IGNORECASE)),
    ("UG", re.compile(r"\b(?:bachelor'?s?|under[\s-]?grad\w*|ug)\b", re.IGNORECASE)),
]
_KIND_WORDS = {
    "intern": "internship",
    "part": "part_time",
    "full": "full_time",
    "volunt": "volunteer",
    "freelanc": "freelance",
    "contract": "freelance",
}


def _clamp_level(value) -> str | None:
    """
    Map whatever the model wrote ('Bachelors', 'B.Tech') to UG/Masters/PG.

    An exact level first; then the same degree patterns the regex path uses,
    so both paths read a degree name alike; then a few generic words.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    if value in EDUCATION_ORDER:
        return value
    from_degree = highest_education_level(find_education_levels(value))
    if from_degree:
        return from_degree
    for level, pattern in _LEVEL_WORDS:
        if pattern.search(value):
            return level
    return None


def _clamp_kind(value) -> str | None:
    if not isinstance(value, str):
        return None
    lowered = value.lower()
    for prefix, kind in _KIND_WORDS.items():
        if lowered.startswith(prefix):
            return kind
    return None


def _as_number_or_none(value):
    """'8.4', '8.4/10', 8.4 -> 8.4; anything unreadable -> None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    match = re.match(r"\s*(\d+(?:\.\d+)?)", str(value))
    return float(match.group(1)) if match else None


def _as_cgpa(value):
    """A ten-point CGPA, or None. '3.6/4' is a four-point figure: None."""
    if isinstance(value, str):
        scale = re.search(r"/\s*(\d+(?:\.\d+)?)", value)
        if scale and float(scale.group(1)) != 10.0:
            return None
    number = _as_number_or_none(value)
    return number if number is not None and 0 <= number <= 10 else None


def _as_iso_date(value):
    """'2003-03-12' if it is a real date in ISO form; anything else -> None."""
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()):
        return None
    try:
        return datetime.date.fromisoformat(value.strip()).isoformat()
    except ValueError:
        return None


def _split_if_text(value):
    """'Python, Django' -> ['Python', 'Django']; anything else unchanged."""
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return value


# --- fitting ------------------------------------------------------------------
# The prompt invites null for anything unstated, and a model will write a
# long summary or a hundred and one skills. Each of those used to fail
# validation twice and throw a good reading away, so: null lists become [],
# a null boolean False, over-long text and lists are cut.


def _fit_text(value, max_length: int):
    return value[:max_length] if isinstance(value, str) else value


def _fit_list(value, item_max_length: int | None = None):
    if value is None:
        return []
    if not isinstance(value, list):
        return value  # a dict here must fail validation, not be hidden
    items = [item for item in value if item is not None][:MAX_LIST_ITEMS]
    if item_max_length is not None:
        items = [_fit_text(item, item_max_length) for item in items]
    return items


def _fit_entries(value, fit_one):
    if value is None:
        return []
    if not isinstance(value, list):
        return value
    return [fit_one(item) if isinstance(item, dict) else item for item in value[:MAX_LIST_ITEMS]]


def _fit_education(entry: dict) -> dict:
    entry = dict(entry)
    for key, limit in (("degree", 200), ("field", 200), ("institution", 200), ("start", 20), ("end", 20)):
        entry[key] = _fit_text(entry.get(key), limit)
    return entry


def _fit_experience(entry: dict) -> dict:
    entry = dict(entry)
    for key, limit in (("role", 200), ("organization", 200), ("start", 20), ("end", 20), ("summary", 1000)):
        entry[key] = _fit_text(entry.get(key), limit)
    if entry.get("is_current") is None:
        entry["is_current"] = False
    return entry


def _fit_project(entry: dict) -> dict:
    entry = dict(entry)
    entry["title"] = _fit_text(entry.get("title"), 200)
    entry["tech_stack"] = _fit_list(_split_if_text(entry.get("tech_stack")), 60)
    return entry


def normalise_resume_reply(data: dict) -> dict:
    """Coerce near-misses before validation, so one odd value does not cost a retry."""
    data = dict(data)
    for key, limit in (("emails", 254), ("phones", 30), ("skills", 60), ("certifications", 200), ("links", 300)):
        data[key] = _fit_list(_split_if_text(data.get(key)), limit)
    for key, limit in (("full_name", 150), ("address", 500), ("date_of_birth", 20)):
        data[key] = _fit_text(data.get(key), limit)

    data["age"] = _as_number_or_none(data.get("age"))
    data["cgpa"] = _as_cgpa(data.get("cgpa"))
    data["date_of_birth"] = _as_iso_date(data.get("date_of_birth"))
    if isinstance(data.get("age"), float):
        data["age"] = int(data["age"])
    if data.get("age") is not None and not 0 <= data["age"] <= 120:
        data["age"] = None

    education = []
    for entry in data.get("education") or []:
        if isinstance(entry, dict):
            entry = dict(entry)
            entry["level"] = _clamp_level(entry.get("level")) or _clamp_level(entry.get("degree"))
            entry["cgpa"] = _as_cgpa(entry.get("cgpa"))
            education.append(entry)
    data["education"] = _fit_entries(education, _fit_education)

    experience = []
    for entry in data.get("experience") or []:
        if isinstance(entry, dict):
            entry = dict(entry)
            entry["kind"] = _clamp_kind(entry.get("kind"))
            experience.append(entry)
    data["experience"] = _fit_entries(experience, _fit_experience)

    projects = [entry for entry in data.get("projects") or [] if isinstance(entry, dict)]
    data["projects"] = _fit_entries(projects, _fit_project)
    return data


def normalise_job_reply(data: dict) -> dict:
    data = dict(data)
    for key in ("required_skills", "nice_to_have"):
        data[key] = _fit_list(_split_if_text(data.get(key)), 60)
    for key, limit in (("title", 200), ("canonical_role", 100)):
        data[key] = _fit_text(data.get(key), limit)
    data["min_experience_years"] = _as_number_or_none(data.get("min_experience_years"))
    if data["min_experience_years"] is not None and not 0 <= data["min_experience_years"] <= MAX_PLAUSIBLE_YEARS:
        data["min_experience_years"] = None
    levels = data.get("education_levels") or []
    if isinstance(levels, str):
        levels = [levels]
    data["education_levels"] = sorted({lvl for lvl in map(_clamp_level, levels) if lvl})
    return data
