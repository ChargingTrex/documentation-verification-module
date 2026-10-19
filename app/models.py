"""
What the verifier stores.

A `Subject` (a student or an employee) has `Document`s; each document has
the `Extraction`s read off it; a `Verification` ties one CV to one ID card
and records the verdict. ID numbers are never stored in full -- the
extraction payload carries `id_last4` only.
"""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class Subject(Base):
    __tablename__ = "subjects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    #: "student" or "employee"
    type: Mapped[str] = mapped_column(String(20), index=True)
    #: PRN, employee id, or whatever the caller uses to find them again.
    external_ref: Mapped[str | None] = mapped_column(String(100), index=True, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    documents: Mapped[list["Document"]] = relationship(back_populates="subject")
    verifications: Mapped[list["Verification"]] = relationship(back_populates="subject")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    subject_id: Mapped[str | None] = mapped_column(ForeignKey("subjects.id"), index=True, nullable=True)
    #: "cv", "aadhaar" or "pan"
    kind: Mapped[str] = mapped_column(String(20), index=True)
    #: Where the bytes went (a random name under UPLOAD_DIR).
    path: Mapped[str] = mapped_column(String(500))
    filename: Mapped[str] = mapped_column(String(255))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    subject: Mapped[Subject | None] = relationship(back_populates="documents")
    extractions: Mapped[list["Extraction"]] = relationship(back_populates="document")


class Extraction(Base):
    __tablename__ = "extractions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    #: "llm", "regex" or "ocr" -- the path that produced the payload.
    source: Mapped[str] = mapped_column(String(20))
    #: The model or OCR engine behind it, e.g. "gemma4:e4b", "pp-ocrv5".
    engine: Mapped[str | None] = mapped_column(String(100), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    document: Mapped[Document] = relationship(back_populates="extractions")


class Verification(Base):
    __tablename__ = "verifications"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    subject_id: Mapped[str] = mapped_column(ForeignKey("subjects.id"), index=True)
    cv_document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    id_document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"))
    name_score: Mapped[float] = mapped_column(Float)
    #: "match", "review" or "mismatch"
    verdict: Mapped[str] = mapped_column(String(20), index=True)
    checks_passed: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_now)

    subject: Mapped[Subject] = relationship(back_populates="verifications")
