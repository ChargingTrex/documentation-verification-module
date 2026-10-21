"""
Verification: a CV plus the documents the subject handed in.

ID cards: Aadhaar (front and/or back -- the front carries the name, DOB and
gender, the back the address) and PAN. Academic: the 10th and 12th
marksheets and the college transcript, held against what the CV claims.
Any combination is accepted as long as at least one document besides the
CV is given.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.academic import save_academic
from app.api.documents import save_cv, save_id
from app.api.subjects import latest_extraction, resolve_subject
from app.db import get_session
from app.models import Document, Subject, Verification
from app.ocr.aadhaar import merge_aadhaar
from app.ocr.cards import IdCardFacts
from app.schemas import FormClaims, SubjectType, VerificationResult
from app.verify.service import verify_documents

router = APIRouter(tags=["verification"])

ACADEMIC_KINDS = ("marksheet_10", "marksheet_12", "transcript")


def parse_form(raw: str | None) -> dict | None:
    """The registration form's claims, from a JSON string in a multipart field."""
    if not raw or not raw.strip():
        return None
    import json

    from pydantic import ValidationError

    try:
        return FormClaims.model_validate(json.loads(raw)).model_dump()
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail=f"form is not valid: {str(exc)[:300]}") from exc


@dataclass
class DocumentSet:
    """Everything but the CV in one verification: documents and their records."""

    documents: list[Document] = field(default_factory=list)
    aadhaar_front: dict | None = None
    aadhaar_back: dict | None = None
    pan: dict | None = None
    academic: dict[str, dict] = field(default_factory=dict)

    def cards(self) -> dict[str, dict]:
        """One record per ID card: the two Aadhaar sides merged into one."""
        result: dict[str, dict] = {}
        if self.aadhaar_front or self.aadhaar_back:
            front = _facts(self.aadhaar_front) if self.aadhaar_front else None
            back = _facts(self.aadhaar_back) if self.aadhaar_back else None
            result["aadhaar"] = merge_aadhaar(front, back).as_dict()
        if self.pan:
            result["pan"] = self.pan
        return result


def _facts(record: dict) -> IdCardFacts:
    """A stored card record back into the dataclass the merge works on."""
    return IdCardFacts(**{key: record.get(key) for key in IdCardFacts.__dataclass_fields__ if key in record})


@router.post("/verify", response_model=VerificationResult)
async def verify(
    cv: UploadFile = File(..., description="PDF or DOCX resume"),
    aadhaar_front: UploadFile | None = File(None, description="Aadhaar card, front side"),
    aadhaar_back: UploadFile | None = File(None, description="Aadhaar card, back side (address)"),
    pan: UploadFile | None = File(None, description="PAN card"),
    marksheet_10: UploadFile | None = File(None, description="10th standard marksheet"),
    marksheet_12: UploadFile | None = File(None, description="12th standard marksheet"),
    transcript: UploadFile | None = File(None, description="College transcript / consolidated grade card"),
    form: str | None = Form(
        None,
        description='The registration form\'s claims as JSON, e.g. {"full_name": "...", "cgpa": 8.4, '
                    '"tenth_percentage": 92.4, "twelfth_percentage": 88, "date_of_birth": "2003-03-12", '
                    '"email": "...", "phone": "..."}',
    ),
    subject_type: SubjectType = Form("student"),
    external_ref: str | None = Form(None),
    subject_id: str | None = Form(None),
    session: Session = Depends(get_session),
):
    """Upload the CV and the documents, read everything, compare, store it all."""
    claims = parse_form(form)
    uploads = [(name, upload) for name, upload in (
        ("aadhaar_front", aadhaar_front), ("aadhaar_back", aadhaar_back), ("pan", pan),
        ("marksheet_10", marksheet_10), ("marksheet_12", marksheet_12), ("transcript", transcript),
    ) if upload is not None and upload.filename]
    if not uploads:
        raise HTTPException(
            status_code=422,
            detail="Give at least one document besides the CV: aadhaar_front, aadhaar_back, pan, "
                   "marksheet_10, marksheet_12 or transcript.",
        )

    subject = resolve_subject(session, subject_id, subject_type, external_ref)
    cv_document, cv_record = save_cv(session, await cv.read(), cv.filename or "resume", subject.id)

    docs = DocumentSet()
    for name, upload in uploads:
        data = await upload.read()
        if name in ACADEMIC_KINDS:
            document, record = save_academic(session, data, upload.filename or name, name, subject.id)
            docs.academic[name] = record
        else:
            kind, side = ("pan", "front") if name == "pan" else ("aadhaar", name.removeprefix("aadhaar_"))
            document, record = save_id(session, data, upload.filename or name, kind, subject.id, side)
            setattr(docs, name, record)
        docs.documents.append(document)

    verification = verify_documents(
        session, subject, cv_document, cv_record, docs.documents, docs.cards(), docs.academic, claims
    )
    session.commit()
    return VerificationResult(**verification.payload)


class VerifyExisting(BaseModel):
    cv_document_id: str
    form: FormClaims | None = None
    aadhaar_front_document_id: str | None = None
    aadhaar_back_document_id: str | None = None
    pan_document_id: str | None = None
    marksheet_10_document_id: str | None = None
    marksheet_12_document_id: str | None = None
    transcript_document_id: str | None = None


@router.post("/verify/documents", response_model=VerificationResult)
def verify_existing(body: VerifyExisting, session: Session = Depends(get_session)):
    """Compare documents that were uploaded separately."""
    cv_document = session.get(Document, body.cv_document_id)
    if cv_document is None or cv_document.kind != "cv":
        raise HTTPException(status_code=404, detail="cv_document_id is not a CV document.")

    wanted = {
        "aadhaar_front": (body.aadhaar_front_document_id, "aadhaar"),
        "aadhaar_back": (body.aadhaar_back_document_id, "aadhaar"),
        "pan": (body.pan_document_id, "pan"),
        "marksheet_10": (body.marksheet_10_document_id, "marksheet_10"),
        "marksheet_12": (body.marksheet_12_document_id, "marksheet_12"),
        "transcript": (body.transcript_document_id, "transcript"),
    }
    docs = DocumentSet()
    for name, (document_id, kind) in wanted.items():
        if not document_id:
            continue
        document = session.get(Document, document_id)
        if document is None or document.kind != kind:
            raise HTTPException(status_code=404, detail=f"{name}_document_id is not a {kind} document.")
        extraction = latest_extraction(session, document.id)
        if extraction is None:
            raise HTTPException(status_code=422, detail=f"{name}_document_id has no extraction to compare.")
        docs.documents.append(document)
        if name in ACADEMIC_KINDS:
            docs.academic[name] = extraction.payload
        else:
            setattr(docs, name, extraction.payload)
    if not docs.documents:
        raise HTTPException(status_code=422, detail="Give at least one document id besides the CV.")

    subject = None
    for document in (cv_document, *docs.documents):
        if document.subject_id:
            subject = session.get(Subject, document.subject_id)
            break
    if subject is None:
        raise HTTPException(status_code=422, detail="No document belongs to a subject; upload with subject_type.")
    for document in (cv_document, *docs.documents):
        if document.subject_id is None:
            document.subject_id = subject.id
        elif document.subject_id != subject.id:
            raise HTTPException(status_code=422, detail="The documents belong to different subjects.")

    cv_extraction = latest_extraction(session, cv_document.id)
    if cv_extraction is None:
        raise HTTPException(status_code=422, detail="The CV has no extraction to compare.")

    verification = verify_documents(
        session, subject, cv_document, cv_extraction.payload, docs.documents, docs.cards(), docs.academic,
        body.form.model_dump() if body.form else None,
    )
    session.commit()
    return VerificationResult(**verification.payload)


@router.get("/verifications/{verification_id}", response_model=VerificationResult)
def get_verification(verification_id: str, session: Session = Depends(get_session)):
    verification = session.get(Verification, verification_id)
    if verification is None:
        raise HTTPException(status_code=404, detail="Unknown verification.")
    return VerificationResult(**{**verification.payload, "verification_id": verification.id})
