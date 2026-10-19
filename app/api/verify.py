"""Verification: CV + ID card in one call, or two documents already uploaded."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.documents import save_cv, save_id
from app.api.subjects import latest_extraction, resolve_subject
from app.db import get_session
from app.models import Document, Subject, Verification
from app.schemas import IdType, SubjectType, VerificationResult
from app.verify.service import verify_documents

router = APIRouter(tags=["verification"])


@router.post("/verify", response_model=VerificationResult)
async def verify(
    cv: UploadFile = File(..., description="PDF or DOCX resume"),
    id_card: UploadFile = File(..., description="Scanned Aadhaar or PAN card"),
    id_type: IdType = Form(...),
    subject_type: SubjectType = Form("student"),
    external_ref: str | None = Form(None),
    subject_id: str | None = Form(None),
    session: Session = Depends(get_session),
):
    """Upload both documents, read both, compare the names, store everything."""
    subject = resolve_subject(session, subject_id, subject_type, external_ref)
    cv_data, id_data = await cv.read(), await id_card.read()
    cv_document, cv_record = save_cv(session, cv_data, cv.filename or "resume", subject.id)
    id_document, id_record = save_id(session, id_data, id_card.filename or "card", id_type, subject.id)
    verification = verify_documents(session, subject, cv_document, cv_record, id_document, id_record)
    session.commit()
    return VerificationResult(**verification.payload)


class VerifyExisting(BaseModel):
    cv_document_id: str
    id_document_id: str


@router.post("/verify/documents", response_model=VerificationResult)
def verify_existing(body: VerifyExisting, session: Session = Depends(get_session)):
    """Compare two documents that were uploaded separately."""
    cv_document = session.get(Document, body.cv_document_id)
    id_document = session.get(Document, body.id_document_id)
    if cv_document is None or cv_document.kind != "cv":
        raise HTTPException(status_code=404, detail="cv_document_id is not a CV document.")
    if id_document is None or id_document.kind not in ("aadhaar", "pan"):
        raise HTTPException(status_code=404, detail="id_document_id is not an ID card document.")

    subject = None
    for document in (cv_document, id_document):
        if document.subject_id:
            subject = session.get(Subject, document.subject_id)
            break
    if subject is None:
        raise HTTPException(status_code=422, detail="Neither document belongs to a subject; upload with subject_type.")
    for document in (cv_document, id_document):
        if document.subject_id is None:
            document.subject_id = subject.id
        elif document.subject_id != subject.id:
            raise HTTPException(status_code=422, detail="The two documents belong to different subjects.")

    cv_extraction = latest_extraction(session, cv_document.id)
    id_extraction = latest_extraction(session, id_document.id)
    if cv_extraction is None or id_extraction is None:
        raise HTTPException(status_code=422, detail="A document has no extraction to compare.")

    verification = verify_documents(
        session, subject, cv_document, cv_extraction.payload, id_document, id_extraction.payload
    )
    session.commit()
    return VerificationResult(**verification.payload)


@router.get("/verifications/{verification_id}", response_model=VerificationResult)
def get_verification(verification_id: str, session: Session = Depends(get_session)):
    verification = session.get(Verification, verification_id)
    if verification is None:
        raise HTTPException(status_code=404, detail="Unknown verification.")
    return VerificationResult(**{**verification.payload, "verification_id": verification.id})
