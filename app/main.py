"""
Document Verifier -- FastAPI entry point.

    uv run uvicorn app.main:app --reload

Routers are added as the phases land (see AGENTS.md). `/health` says which
OCR engine, LLM and similarity backend are live, so a smoke test can tell a
regex-only run from a full one.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import academic, documents, match, subjects, verify
from app.config import settings
from app.db import init_db

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    logging.basicConfig(level=settings.log_level.upper())
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    init_db()
    yield


app = FastAPI(
    title="Document Verifier",
    description="Resume extraction, Aadhaar/PAN OCR and name verification.",
    version="0.1.0",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.include_router(documents.router)
app.include_router(academic.router)
app.include_router(subjects.router)
app.include_router(match.router)
app.include_router(verify.router)


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict:
    from app.llm.client import llm_info
    from app.matching.backends import backend_info

    return {
        "status": "ok",
        "ocr_engine": settings.ocr_engine,
        "llm": llm_info(),
        "matching": backend_info(),
        "database": "sqlite" if settings.is_sqlite else "postgres",
    }
