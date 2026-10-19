"""
Verification: a CV plus the ID cards the subject handed in.

Aadhaar has two sides -- the front carries the name, DOB and gender, the
back the address -- so it is taken as up to two files. A PAN is one file.
Any combination is accepted as long as at least one card image is given:
Aadhaar alone (one or both sides), PAN alone, or both cards.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.documents import save_cv, save_id
from app.api.subjects import latest_extraction, resolve_subject
from app.db import get_session
from app.models import Document, Subject, Verification
from app.ocr.aadhaar import merge_aadhaar
from app.ocr.cards import IdCardFacts
from app.schemas import SubjectType, VerificationResult
from app.verify.service import verify_documents

router = APIRouter(tags=["verification"])


@dataclass
class CardSet:
    """The ID card documents and records of one verification, by card."""

    documents: list[Document]
    aadhaar_front: dict | None = None
    aadhaar_back: dict | None = None
    pan: dict | None = None

    def cards(self) -> dict[str, dict]:
        """One record per card: the two Aadhaar sides merged into one."""
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
    subject_type: SubjectType = Form("student"),
    external_ref: str | None = Form(None),
    subject_id: str | None = Form(None),
    session: Session = Depends(get_session),
):
    """Upload the CV and the cards, read everything, compare the names, store it all."""
    uploads = [(name, upload) for name, upload in (
        ("aadhaar_front", aadhaar_front), ("aadhaar_back", aadhaar_back), ("pan", pan)
    ) if upload is not None and upload.filename]
    if not uploads:
        raise HTTPException(status_code=422, detail="Give at least one ID card: aadhaar_front, aadhaar_back or pan.")

    subject = resolve_subject(session, subject_id, subject_type, external_ref)
    cv_document, cv_record = save_cv(session, await cv.read(), cv.filename or "resume", subject.id)

    cards = CardSet(documents=[])
    for name, upload in uploads:
        kind, side = ("pan", "front") if name == "pan" else ("aadhaar", name.removeprefix("aadhaar_"))
        document, record = save_id(session, await upload.read(), upload.filename or name, kind, subject.id, side)
        cards.documents.append(document)
        setattr(cards, name, record)

    verification = verify_documents(session, subject, cv_document, cv_record, cards.documents, cards.cards())
    session.commit()
    return VerificationResult(**verification.payload)


class VerifyExisting(BaseModel):
    cv_document_id: str
    aadhaar_front_document_id: str | None = None
    aadhaar_back_document_id: str | None = None
    pan_document_id: str | None = None


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
    }
    cards = CardSet(documents=[])
    for name, (document_id, kind) in wanted.items():
        if not document_id:
            continue
        document = session.get(Document, document_id)
        if document is None or document.kind != kind:
            raise HTTPException(status_code=404, detail=f"{name}_document_id is not a {kind} document.")
        extraction = latest_extraction(session, document.id)
        if extraction is None:
            raise HTTPException(status_code=422, detail=f"{name}_document_id has no extraction to compare.")
        cards.documents.append(document)
        setattr(cards, name, extraction.payload)
    if not cards.documents:
        raise HTTPException(status_code=422, detail="Give at least one ID card document id.")

    subject = None
    for document in (cv_document, *cards.documents):
        if document.subject_id:
            subject = session.get(Subject, document.subject_id)
            break
    if subject is None:
        raise HTTPException(status_code=422, detail="No document belongs to a subject; upload with subject_type.")
    for document in (cv_document, *cards.documents):
        if document.subject_id is None:
            document.subject_id = subject.id
        elif document.subject_id != subject.id:
            raise HTTPException(status_code=422, detail="The documents belong to different subjects.")

    cv_extraction = latest_extraction(session, cv_document.id)
    if cv_extraction is None:
        raise HTTPException(status_code=422, detail="The CV has no extraction to compare.")

    verification = verify_documents(
        session, subject, cv_document, cv_extraction.payload, cards.documents, cards.cards()
    )
    session.commit()
    return VerificationResult(**verification.payload)


@router.get("/verifications/{verification_id}", response_model=VerificationResult)
def get_verification(verification_id: str, session: Session = Depends(get_session)):
    verification = session.get(Verification, verification_id)
    if verification is None:
        raise HTTPException(status_code=404, detail="Unknown verification.")
    return VerificationResult(**{**verification.payload, "verification_id": verification.id})
