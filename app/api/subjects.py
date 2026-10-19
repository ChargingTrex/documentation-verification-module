"""Subjects: the student or employee a set of documents belongs to."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Document, Extraction, Subject, Verification

router = APIRouter(prefix="/subjects", tags=["subjects"])


def resolve_subject(
    session: Session,
    subject_id: str | None,
    subject_type: str | None,
    external_ref: str | None,
) -> Subject | None:
    """
    An existing subject by id, else a new one when a type was given, else None.

    An upload may arrive before anyone knows who it is for; the document then
    has no subject and `/verify` attaches one.
    """
    if subject_id:
        subject = session.get(Subject, subject_id)
        if subject is None:
            raise HTTPException(status_code=404, detail=f"Unknown subject '{subject_id}'.")
        return subject
    if subject_type:
        if subject_type not in ("student", "employee"):
            raise HTTPException(status_code=422, detail="subject_type must be 'student' or 'employee'.")
        subject = Subject(type=subject_type, external_ref=external_ref or None)
        session.add(subject)
        session.flush()
        return subject
    return None


def latest_extraction(session: Session, document_id: str) -> Extraction | None:
    return session.scalars(
        select(Extraction)
        .where(Extraction.document_id == document_id)
        .order_by(Extraction.created_at.desc())
        .limit(1)
    ).first()


@router.get("/{subject_id}")
def get_subject(subject_id: str, session: Session = Depends(get_session)) -> dict:
    subject = session.get(Subject, subject_id)
    if subject is None:
        raise HTTPException(status_code=404, detail="Unknown subject.")
    documents = session.scalars(
        select(Document).where(Document.subject_id == subject_id).order_by(Document.created_at)
    ).all()
    latest = session.scalars(
        select(Verification)
        .where(Verification.subject_id == subject_id)
        .order_by(Verification.created_at.desc())
        .limit(1)
    ).first()
    return {
        "subject_id": subject.id,
        "type": subject.type,
        "external_ref": subject.external_ref,
        "created_at": subject.created_at,
        "documents": [
            {
                "document_id": d.id,
                "kind": d.kind,
                "filename": d.filename,
                "sha256": d.sha256,
                "created_at": d.created_at,
                "extraction": (e.payload if (e := latest_extraction(session, d.id)) else None),
            }
            for d in documents
        ],
        "latest_verification": latest.payload if latest else None,
    }
