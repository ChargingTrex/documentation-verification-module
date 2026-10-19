"""Document uploads: a CV now, ID cards in Phase 2."""

from __future__ import annotations

import io

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.subjects import latest_extraction, resolve_subject
from app.db import get_session
from app.extraction.record import cv_record
from app.extraction.text import ResumeParseError, extract_text
from app.matching.engine import get_engine
from app.models import Document, Extraction
from app.schemas import CvUploadResponse, DocumentOut
from app.storage import CV_EXTENSIONS, UploadError, store_upload

router = APIRouter(prefix="/documents", tags=["documents"])


def analyse_cv_bytes(data: bytes, filename: str) -> dict:
    """Text out of the file, facts out of the text, one record out of both."""
    try:
        text = extract_text(io.BytesIO(data), filename)
    except ResumeParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    profile = get_engine().analyse_resume(text)
    return cv_record(profile)


def save_cv(session: Session, data: bytes, filename: str, subject_id: str | None) -> tuple[Document, dict]:
    """Store the file, read it, persist both. Shared with /verify."""
    try:
        stored = store_upload(data, filename, "cv", CV_EXTENSIONS)
    except UploadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    record = analyse_cv_bytes(data, filename)
    document = Document(
        subject_id=subject_id, kind="cv", path=str(stored.path), filename=filename, sha256=stored.sha256
    )
    session.add(document)
    session.flush()
    session.add(
        Extraction(
            document_id=document.id,
            source=record["extraction_source"],
            engine=record["llm_model"],
            payload=record,
        )
    )
    return document, record


@router.post("/cv", response_model=CvUploadResponse)
async def upload_cv(
    file: UploadFile = File(..., description="PDF or DOCX resume"),
    subject_id: str | None = Form(None),
    subject_type: str | None = Form(None, description="student | employee; creates a subject"),
    external_ref: str | None = Form(None, description="PRN / employee id"),
    session: Session = Depends(get_session),
):
    data = await file.read()
    subject = resolve_subject(session, subject_id, subject_type, external_ref)
    document, record = save_cv(session, data, file.filename or "resume", subject.id if subject else None)
    session.commit()
    return CvUploadResponse(
        document_id=document.id,
        subject_id=document.subject_id,
        kind=document.kind,
        filename=document.filename,
        sha256=document.sha256,
        cv=record,
    )


@router.get("/{document_id}")
def get_document(document_id: str, session: Session = Depends(get_session)) -> dict:
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Unknown document.")
    extraction = latest_extraction(session, document_id)
    return {
        **DocumentOut(
            document_id=document.id,
            subject_id=document.subject_id,
            kind=document.kind,
            filename=document.filename,
            sha256=document.sha256,
        ).model_dump(),
        "created_at": document.created_at,
        "extraction": extraction.payload if extraction else None,
        "extraction_source": extraction.source if extraction else None,
        "extraction_engine": extraction.engine if extraction else None,
    }
