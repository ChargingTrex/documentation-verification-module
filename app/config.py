"""
Settings, read from the environment and an optional `.env`.

One object, `settings`, imported everywhere. Modules read attributes at call
time (never at import), so a test can set `settings.llm_enabled = False` and
have it take effect. Every value has a working default: a clean checkout runs
with SQLite, regex extraction and the stub OCR engine, no `.env` needed.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- app ---
    app_debug: bool = True
    log_level: str = "INFO"

    # --- storage ---
    database_url: str = f"sqlite:///{BASE_DIR / 'data' / 'verifier.sqlite3'}"
    upload_dir: Path = BASE_DIR / "data" / "uploads"
    max_upload_bytes: int = 10 * 1024 * 1024

    # --- OCR ---
    #: paddleocr (in-process PP-OCR), paddleocr-vl (HTTP to the ocr-vl
    #: container), or stub (fixture text; the default for tests).
    ocr_engine: str = "paddleocr"
    ocr_lang: str = "en"
    #: auto -> onnxruntime on an Intel Mac, paddle elsewhere; or name one.
    ocr_inference_engine: str = "auto"
    #: Detect and undo a rotated document before recognition. Cheap and safe
    #: on the real scans tried.
    ocr_orientation: bool = True
    #: Also classify each text line's orientation. Off: on a real PAN scan it
    #: flipped lines in the top half and lost the name and number.
    ocr_textline_orientation: bool = False
    #: PaddleOCR model names; unset -> PaddleOCR's defaults for the version
    #: installed. e.g. PP-OCRv5_mobile_det / PP-OCRv5_mobile_rec.
    ocr_text_detection_model: str | None = None
    ocr_text_recognition_model: str | None = None
    ocr_vl_base_url: str = "http://localhost:8118"

    # --- LLM: any OpenAI-compatible chat API ---
    # Default: a local Ollama, no key, nothing leaves the machine. To use a
    # hosted provider instead, point LLM_BASE_URL at its /v1 and set
    # LLM_API_KEY -- and accept that resumes are then sent to that provider.
    llm_enabled: bool = True
    llm_base_url: str = "http://localhost:11434/v1"
    llm_model: str = "gemma4:e4b"
    llm_api_key: str | None = None
    #: Ask for `response_format: json_object`. Off for providers that reject it.
    llm_json_mode: bool = True
    #: gemma4:e4b on a 2018 Intel i7 (CPU only) takes ~3 minutes per resume.
    llm_timeout_seconds: float = 600.0

    # --- matching engine ---
    matching_backend: str = "auto"
    spacy_model: str = "en_core_web_md"
    default_similarity_threshold: float | None = None

    # --- name verification (token_set_ratio, 0-100) ---
    name_match_threshold: int = 85
    name_review_threshold: int = 70

    @field_validator("upload_dir", mode="after")
    @classmethod
    def _absolute_upload_dir(cls, value: Path) -> Path:
        return value if value.is_absolute() else BASE_DIR / value

    @field_validator("llm_base_url", "ocr_vl_base_url", mode="after")
    @classmethod
    def _strip_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


settings = Settings()
