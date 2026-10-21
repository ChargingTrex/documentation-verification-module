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
    #: {"tenth": {percentage, cgpa, board, year} | None, "twelfth": ...} -- what the CV claims.
    school: dict[str, dict | None] = Field(default_factory=lambda: {"tenth": None, "twelfth": None})
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
    #: What the printed headings say the card is; None when unclear. A
    #: `card_type_matches: false` check means it was uploaded in the wrong slot.
    detected_type: IdType | None = None
    #: ["front"], ["back"] or ["front", "back"] -- which images were read.
    sides: list[str] = Field(default_factory=list)
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


AcademicType = Literal["marksheet_10", "marksheet_12", "transcript"]


class SubjectRow(_Out):
    name: str | None = None
    marks: float | None = None
    max_marks: float | None = None
    grade: str | None = None


class AcademicRecord(_Out):
    """A 10th / 12th marksheet or a college transcript. Roll numbers kept as last four only."""

    type: AcademicType
    detected_type: AcademicType | None = None
    full_name: str | None = None
    father_name: str | None = None
    mother_name: str | None = None
    roll_last4: str | None = None
    dob: str | None = None
    board: str | None = None
    institution: str | None = None
    year: int | None = None
    subjects: list[SubjectRow] = Field(default_factory=list)
    total_marks: float | None = None
    max_total: float | None = None
    percentage: float | None = None
    #: "stated" (printed), "computed" (from the rows), or None.
    percentage_source: str | None = None
    percentage_computed: float | None = None
    cgpa: float | None = None
    sgpa: list[float] = Field(default_factory=list)
    result: str | None = None
    checks: dict[str, bool] = Field(default_factory=dict)
    #: "pdf" when the file had text, "ocr" when it was read off pixels.
    text_source: str
    ocr_engine: str | None = None
    ocr_detail: str | None = None
    ocr_confidence: float | None = None
    extraction_source: str
    llm_model: str | None = None
    field_sources: dict[str, Source]
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


class AcademicUploadResponse(DocumentOut):
    academic: AcademicRecord


class NameMatch(_Out):
    cv: str | None
    id: str | None
    cv_normalised: str | None
    id_normalised: str | None
    score: float
    verdict: Literal["match", "review", "mismatch"]
    method: str


class FormClaims(BaseModel):
    """
    What the student typed into the placement portal's registration form.

    A third source beside the CV and the documents: every figure here is
    held against both. All optional; unknown keys are ignored.
    """

    model_config = ConfigDict(extra="ignore")

    full_name: str | None = Field(None, max_length=150)
    date_of_birth: str | None = Field(None, max_length=20, description="YYYY-MM-DD")
    email: str | None = Field(None, max_length=254)
    phone: str | None = Field(None, max_length=30)
    cgpa: float | None = Field(None, ge=0, le=10, description="current degree, 10-point scale")
    degree: str | None = Field(None, max_length=200)
    tenth_percentage: float | None = Field(None, ge=0, le=100)
    tenth_cgpa: float | None = Field(None, ge=0, le=10)
    tenth_year: int | None = Field(None, ge=1950, le=2100)
    tenth_board: str | None = Field(None, max_length=100)
    twelfth_percentage: float | None = Field(None, ge=0, le=100)
    twelfth_cgpa: float | None = Field(None, ge=0, le=10)
    twelfth_year: int | None = Field(None, ge=1950, le=2100)
    twelfth_board: str | None = Field(None, max_length=100)


class VerifiedDocument(_Out):
    document_id: str
    kind: str
    side: str | None = None
    filename: str


class VerificationResult(_Out):
    verification_id: str
    subject_id: str
    subject_type: SubjectType
    external_ref: str | None = None
    cv_document_id: str
    documents: list[VerifiedDocument]
    #: The overall verdict: the worst of the CV-vs-card comparisons.
    name_match: NameMatch
    #: CV vs each card given, plus "aadhaar_vs_pan" when both were.
    name_matches: dict[str, NameMatch]
    checks: list[dict]
    cv: CvRecord
    #: "aadhaar" and/or "pan".
    id_cards: dict[str, IdCardRecord]
    #: "marksheet_10", "marksheet_12", "transcript" -- whichever were given.
    academic: dict[str, AcademicRecord] = Field(default_factory=dict)
    #: The registration form's claims, when they were given.
    form: FormClaims | None = None


class ScreenRequest(BaseModel):
    """Bulk screening: a pool of candidate texts against one job description."""

    candidates: dict[str, str] = Field(..., description="identifier -> resume text")
    job_description: str
    similarity_threshold: float | None = Field(None, ge=0, le=1)
    min_experience_years: float | None = Field(None, ge=0)
    required_education: list[Literal["UG", "Masters", "PG"]] | None = None
