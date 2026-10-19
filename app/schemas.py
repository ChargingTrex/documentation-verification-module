"""
The API's request and response shapes -- and the canonical extraction JSON.

`CvRecord` and `IdCardRecord` are what the database stores and what the
portal will consume later, so their field names follow the LLM reply schema
(`app/llm/schema.py`) rather than inventing new ones.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SubjectType = Literal["student", "employee"]
IdType = Literal["aadhaar", "pan"]
Source = Literal["llm", "regex", "ocr", "none"]


class _Out(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Address(_Out):
    raw: str
    pincode: str | None = None
    state: str | None = None


class EducationEntry(_Out):
    degree: str | None = None
    level: Literal["UG", "Masters", "PG"] | None = None
    field: str | None = None
    institution: str | None = None
    start: str | None = None
    end: str | None = None
    cgpa: float | None = None


class ExperienceEntry(_Out):
    role: str | None = None
    organization: str | None = None
    kind: str | None = None
    start: str | None = None
    end: str | None = None
    is_current: bool = False
    summary: str | None = None


class CvRecord(_Out):
    """Everything read off one CV, with the source of every field."""

    full_name: str | None
    emails: list[str]
    phones: list[str]
    address: Address | None
    education: list[EducationEntry]
    experience: list[ExperienceEntry]
    experience_years: float
    education_levels: list[str]
    highest_education_level: str | None
    skills: list[str]
    cgpa: float | None = None
    date_of_birth: str | None = None
    #: "llm" when the model's reading was used, else "regex".
    extraction_source: str
    llm_model: str | None = None
    #: Per field: "llm", "regex" or "none".
    field_sources: dict[str, Source]
    regex_facts: dict
    agreement: dict
    text_length: int


class IdCardRecord(_Out):
    """What was read off an Aadhaar or PAN card. Never the full number."""

    type: IdType
    full_name: str | None
    id_last4: str | None
    dob: str | None = None
    year_of_birth: int | None = None
    gender: Literal["M", "F", "O"] | None = None
    father_name: str | None = None
    address: Address | None = None
    phones: list[str] = Field(default_factory=list)
    ocr_engine: str
    #: The models and runtime behind it, e.g. "PP-OCRv6_medium_det/PP-OCRv6_medium_rec via onnxruntime".
    ocr_detail: str | None = None
    ocr_confidence: float | None = None
    #: Which checks ran, e.g. {"aadhaar_checksum": true}.
    checks: dict[str, bool] = Field(default_factory=dict)
    #: Raw OCR lines, for audit and parser tuning.
    lines: list[str] = Field(default_factory=list)


class DocumentOut(_Out):
    document_id: str
    subject_id: str | None
    kind: str
    filename: str
    sha256: str


class CvUploadResponse(DocumentOut):
    cv: CvRecord


class IdUploadResponse(DocumentOut):
    id_card: IdCardRecord


class NameMatch(_Out):
    cv: str | None
    id: str | None
    cv_normalised: str | None
    id_normalised: str | None
    score: float
    verdict: Literal["match", "review", "mismatch"]
    method: str


class VerificationResult(_Out):
    verification_id: str
    subject_id: str
    subject_type: SubjectType
    cv_document_id: str
    id_document_id: str
    name_match: NameMatch
    checks: list[dict]
    cv: CvRecord
    id_card: IdCardRecord


class ScreenRequest(BaseModel):
    """Bulk screening: a pool of candidate texts against one job description."""

    candidates: dict[str, str] = Field(..., description="identifier -> resume text")
    job_description: str
    similarity_threshold: float | None = Field(None, ge=0, le=1)
    min_experience_years: float | None = Field(None, ge=0)
    required_education: list[Literal["UG", "Masters", "PG"]] | None = None
