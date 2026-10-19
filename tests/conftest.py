"""Fixtures shared by every test."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# A throwaway database and upload dir for the whole run. Set before `app`
# is imported, because the engine is built when `app.db` loads.
_TMP = tempfile.mkdtemp(prefix="verifier-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.sqlite3"
os.environ["UPLOAD_DIR"] = f"{_TMP}/uploads"

from app import config  # noqa: E402
from app.matching.engine import MatchingEngine
from tests.fixtures.make_resumes import render_samples
from tests.fixtures.samples import SAMPLE_RESUMES


@pytest.fixture(autouse=True)
def _offline_defaults():
    """Tests never reach a model server or load OCR models unless they opt in."""
    snapshot = config.settings.model_dump()
    config.settings.llm_enabled = False
    config.settings.ocr_engine = "stub"
    yield
    for key, value in snapshot.items():
        setattr(config.settings, key, value)


@pytest.fixture
def settings():
    """The live settings object; whatever a test changes is restored after."""
    snapshot = config.settings.model_dump()
    yield config.settings
    for key, value in snapshot.items():
        setattr(config.settings, key, value)


@pytest.fixture
def api():
    """A test client with the app's lifespan run (tables created)."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="session")
def sample_resume_dir(tmp_path_factory) -> Path:
    """Real PDF and DOCX files, rendered once for the whole session."""
    out = tmp_path_factory.mktemp("resumes")
    render_samples(out)
    return out


@pytest.fixture(scope="session")
def card_dir(tmp_path_factory) -> Path:
    """Synthetic Aadhaar/PAN card PNGs with their lines embedded, rendered once."""
    from tests.fixtures.make_idcards import render_cards

    out = tmp_path_factory.mktemp("idcards")
    render_cards(out)
    return out


@pytest.fixture(scope="session")
def engine() -> MatchingEngine:
    """
    The engine on whichever backend this machine has.

    Session-scoped because loading the spaCy model is slow and the engine is
    stateless once built.
    """
    return MatchingEngine()


@pytest.fixture(scope="session")
def sample_texts(engine, sample_resume_dir) -> dict[str, str]:
    """Every sample resume parsed out of its real binary file."""
    texts = {}
    for sample in SAMPLE_RESUMES:
        with (sample_resume_dir / sample.filename).open("rb") as handle:
            texts[sample.key] = engine.parse_resume(handle, sample.filename).raw_text
    return texts
