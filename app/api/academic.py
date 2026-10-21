"""Marksheets and transcripts: upload one on its own."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.academic.service import analyse_academic
from app.api.subjects import resolve_subject
from app.db import get_session
from app.models import Document, Extraction
from app.ocr.engine import OCRError
from app.schemas import AcademicType, AcademicUploadResponse
from app.storage import ACADEMIC_EXTENSIONS, UploadError, store_upload

router = APIRouter(prefix="/documents", tags=["documents"])


def save_academic(
    session: Session, data: bytes, filename: str, kind: str, subject_id: str | None
) -> tuple[Document, dict]:
    """Store the file, read it, persist both. Shared with /verify."""
    try:
        stored = store_upload(data, filename, kind, ACADEMIC_EXTENSIONS)
    except UploadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        record = analyse_academic(data, filename, kind)
    except OCRError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    document = Document(subject_id=subject_id, kind=kind, path=str(stored.path), filename=filename, sha256=stored.sha256)
    session.add(document)
    session.flush()
    session.add(
        Extraction(
            document_id=document.id,
            source=record["extraction_source"],
            engine=record.get("llm_model") or record.get("ocr_engine"),
            payload=record,
        )
    )
    return document, record


@router.post("/academic", response_model=AcademicUploadResponse)
async def upload_academic(
    file: UploadFile = File(..., description="Marksheet or transcript: PNG, JPEG, WEBP or PDF"),
    type: AcademicType = Form(..., description="marksheet_10 | marksheet_12 | transcript"),
    subject_id: str | None = Form(None),
    subject_type: str | None = Form(None, description="student | employee; creates a subject"),
    external_ref: str | None = Form(None),
    session: Session = Depends(get_session),
):
    data = await file.read()
    subject = resolve_subject(session, subject_id, subject_type, external_ref)
    document, record = save_academic(session, data, file.filename or type, type, subject.id if subject else None)
    session.commit()
    return AcademicUploadResponse(
        document_id=document.id,
        subject_id=document.subject_id,
        kind=document.kind,
        filename=document.filename,
        sha256=document.sha256,
        academic=record,
    )
