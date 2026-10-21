"""
Where uploads go.

Every upload is validated (extension, size) and stored under UPLOAD_DIR with
a random name: the original filename is untrusted and is kept only as a
column. Nothing else writes files.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from pathlib import Path

from app.config import settings

CV_EXTENSIONS = {".pdf", ".docx"}
ID_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".pdf"}
ACADEMIC_EXTENSIONS = ID_EXTENSIONS


class UploadError(ValueError):
    """The upload was refused before anything was stored."""


@dataclass(frozen=True)
class StoredFile:
    path: Path
    sha256: str
    size: int


def validate_upload(filename: str, size: int, allowed: set[str]) -> str:
    """Return the lowercase suffix, or raise UploadError."""
    suffix = Path(filename or "").suffix.lower()
    if suffix not in allowed:
        raise UploadError(
            f"Unsupported file type '{suffix or filename}'. Allowed: {', '.join(sorted(allowed))}."
        )
    if size > settings.max_upload_bytes:
        limit_mb = settings.max_upload_bytes / (1024 * 1024)
        raise UploadError(f"File is larger than the {limit_mb:.0f}MB limit.")
    if size == 0:
        raise UploadError("The file is empty.")
    return suffix


def store_upload(data: bytes, filename: str, kind: str, allowed: set[str]) -> StoredFile:
    suffix = validate_upload(filename, len(data), allowed)
    folder = settings.upload_dir / kind
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{uuid.uuid4().hex}{suffix}"
    path.write_bytes(data)
    return StoredFile(path=path, sha256=hashlib.sha256(data).hexdigest(), size=len(data))
