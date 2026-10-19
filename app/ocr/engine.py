"""
OCR engines behind one interface.

`read(data, filename)` returns text lines in reading order, each with its
confidence and box. Three engines:

- `PaddleOCREngine`    -- PaddleOCR's PP-OCR pipeline, in-process. The default.
                          Runs on onnxruntime where PaddlePaddle cannot (Intel Mac).
- `PaddleOCRVLEngine`  -- PaddleOCR-VL 1.5 behind HTTP (the `ocr-vl`
                          container; it needs a PaddlePaddle this Mac cannot run).
- `StubEngine`         -- lines embedded in a PNG's metadata by the fixture
                          generator, or a sidecar JSON. Tests and CI only.

Boxes PP-OCR returns are per text line but not in reading order, and a label
and its value ("DOB:" / "12/03/2003") often come back as two boxes. `rows()`
sorts them top to bottom and joins the boxes that share a row, which is the
shape the card parsers expect.
"""

from __future__ import annotations

import io
import json
import logging
import statistics
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.config import settings

logger = logging.getLogger(__name__)


class OCRError(Exception):
    """The image could not be read."""


@dataclass
class OcrLine:
    text: str
    score: float | None = None
    #: [[x, y], ...] polygon, or [xmin, ymin, xmax, ymax]; None when unknown.
    box: list | None = None

    def as_dict(self) -> dict:
        return asdict(self)


class OCREngine(Protocol):
    name: str

    def read(self, data: bytes, filename: str) -> list[OcrLine]: ...


# --- images -------------------------------------------------------------------


def load_image(data: bytes, filename: str):
    """A PIL image out of an upload: PDFs render their first page."""
    from PIL import Image

    if Path(filename or "").suffix.lower() == ".pdf":
        try:
            import pypdfium2 as pdfium

            page = pdfium.PdfDocument(data)[0]
            return page.render(scale=200 / 72).to_pil().convert("RGB")
        except Exception as exc:
            raise OCRError(f"Could not render the PDF: {exc}") from exc
    try:
        return Image.open(io.BytesIO(data)).convert("RGB")
    except Exception as exc:
        raise OCRError(f"Could not open the image: {exc}") from exc


def _bounds(box) -> tuple[float, float, float, float] | None:
    if not box:
        return None
    if isinstance(box[0], (int, float)) and len(box) == 4:
        return float(box[0]), float(box[1]), float(box[2]), float(box[3])
    xs = [float(p[0]) for p in box]
    ys = [float(p[1]) for p in box]
    return min(xs), min(ys), max(xs), max(ys)


def rows(lines: list[OcrLine]) -> list[OcrLine]:
    """Sort boxes into reading order and join the ones sharing a row."""
    placed = [(line, _bounds(line.box)) for line in lines if line.text and line.text.strip()]
    if not placed or any(bounds is None for _, bounds in placed):
        return [line for line, _ in placed]

    heights = [b[3] - b[1] for _, b in placed]
    tolerance = max(4.0, statistics.median(heights) * 0.5)
    placed.sort(key=lambda item: ((item[1][1] + item[1][3]) / 2, item[1][0]))

    grouped: list[list[tuple[OcrLine, tuple]]] = []
    for item in placed:
        centre = (item[1][1] + item[1][3]) / 2
        if grouped:
            row_centre = statistics.mean((b[1] + b[3]) / 2 for _, b in grouped[-1])
            if abs(centre - row_centre) <= tolerance:
                grouped[-1].append(item)
                continue
        grouped.append([item])

    joined = []
    for row in grouped:
        row.sort(key=lambda item: item[1][0])
        scores = [line.score for line, _ in row if line.score is not None]
        joined.append(
            OcrLine(
                text=" ".join(line.text.strip() for line, _ in row),
                score=min(scores) if scores else None,
                box=[
                    min(b[0] for _, b in row), min(b[1] for _, b in row),
                    max(b[2] for _, b in row), max(b[3] for _, b in row),
                ],
            )
        )
    return joined


# --- engines ------------------------------------------------------------------


def default_inference_engine() -> str:
    """
    Which runtime PaddleOCR should use for its models.

    PaddlePaddle has no macOS x86_64 wheel newer than 3.0.0, and the current
    PP-OCR models do not load on 3.0.0 -- but PaddleOCR ships the same models
    in ONNX form, and onnxruntime runs them anywhere. So: onnxruntime on an
    Intel Mac, PaddlePaddle's own runtime elsewhere.
    """
    import platform
    import sys

    if sys.platform == "darwin" and platform.machine() == "x86_64":
        return "onnxruntime"
    return "paddle"


class PaddleOCREngine:
    """PaddleOCR's text detection + recognition pipeline, loaded once per process."""

    name = "paddleocr"

    def __init__(
        self,
        lang: str | None = None,
        inference_engine: str | None = None,
        det_model: str | None = None,
        rec_model: str | None = None,
    ):
        self.lang = lang or settings.ocr_lang
        requested = (inference_engine or settings.ocr_inference_engine).strip().lower()
        self.inference_engine = default_inference_engine() if requested == "auto" else requested
        self.det_model = det_model or settings.ocr_text_detection_model or None
        self.rec_model = rec_model or settings.ocr_text_recognition_model or None
        self._ocr = None
        self.detail: str | None = None

    def _build(self, orientation: bool):
        from paddleocr import PaddleOCR

        models = {}
        if self.det_model:
            models["text_detection_model_name"] = self.det_model
        if self.rec_model:
            models["text_recognition_model_name"] = self.rec_model
        return PaddleOCR(
            lang=self.lang,
            use_doc_orientation_classify=orientation,
            use_doc_unwarping=False,
            use_textline_orientation=orientation and settings.ocr_textline_orientation,
            device="cpu",
            engine=self.inference_engine,
            **models,
        )

    def _model(self):
        if self._ocr is None:
            try:
                import paddleocr  # noqa: F401
            except ImportError as exc:
                raise OCRError("PaddleOCR is not installed (uv sync --extra ocr).") from exc
            try:
                self._ocr = self._build(orientation=settings.ocr_orientation)
            except Exception as exc:
                if not settings.ocr_orientation:
                    raise OCRError(f"PaddleOCR could not start: {exc}") from exc
                logger.warning("PaddleOCR orientation models unavailable (%s); running without them.", exc)
                try:
                    self._ocr = self._build(orientation=False)
                except Exception as inner:
                    raise OCRError(f"PaddleOCR could not start: {inner}") from inner
            det = self.det_model or getattr(self._ocr, "text_detection_model_name", None) or "default-det"
            rec = self.rec_model or getattr(self._ocr, "text_recognition_model_name", None) or "default-rec"
            self.detail = f"{det}/{rec} via {self.inference_engine}"
        return self._ocr

    def read(self, data: bytes, filename: str) -> list[OcrLine]:
        import numpy as np

        image = np.array(load_image(data, filename))[:, :, ::-1]  # RGB -> BGR
        try:
            results = list(self._model().predict(image))
        except Exception as exc:
            raise OCRError(f"PaddleOCR failed: {exc}") from exc

        lines: list[OcrLine] = []
        for result in results:
            payload = getattr(result, "json", None)
            data_ = payload.get("res", payload) if isinstance(payload, dict) else result
            texts = list(data_.get("rec_texts") or [])
            scores = list(data_.get("rec_scores") or [])
            polys = list(data_.get("rec_polys") if data_.get("rec_polys") is not None else data_.get("dt_polys") or [])
            for index, text in enumerate(texts):
                poly = polys[index] if index < len(polys) else None
                lines.append(
                    OcrLine(
                        text=str(text),
                        score=float(scores[index]) if index < len(scores) else None,
                        box=poly.tolist() if hasattr(poly, "tolist") else poly,
                    )
                )
        return rows(lines)


class PaddleOCRVLEngine:
    """PaddleOCR-VL 1.5, served by the `ocr-vl` container (see ocr_vl_server/)."""

    name = "paddleocr-vl-1.5"

    def __init__(self, base_url: str | None = None, timeout: float = 600.0):
        self.base_url = (base_url or settings.ocr_vl_base_url).rstrip("/")
        self.timeout = timeout

    def read(self, data: bytes, filename: str) -> list[OcrLine]:
        import httpx

        try:
            response = httpx.post(
                f"{self.base_url}/ocr",
                files={"file": (filename or "image", data)},
                timeout=httpx.Timeout(self.timeout, connect=5.0),
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OCRError(f"PaddleOCR-VL server at {self.base_url} failed: {exc}") from exc
        return rows([OcrLine(**item) for item in body.get("lines", [])])


class StubEngine:
    """
    Fixture text instead of pixels.

    The card generator writes the lines it drew into the PNG's `ocr_lines`
    text chunk; a `<stem>.ocr.json` beside a file works for anything else.
    """

    name = "stub"

    def __init__(self, lines: list[str] | None = None, sidecar_dir: Path | None = None):
        self._lines = lines
        self.sidecar_dir = sidecar_dir

    def read(self, data: bytes, filename: str) -> list[OcrLine]:
        if self._lines is not None:
            return [OcrLine(text=line, score=1.0) for line in self._lines]

        from PIL import Image

        try:
            image = Image.open(io.BytesIO(data))
            embedded = getattr(image, "text", {}).get("ocr_lines")
        except Exception:
            embedded = None
        if embedded:
            return [OcrLine(**item) if isinstance(item, dict) else OcrLine(text=item, score=1.0)
                    for item in json.loads(embedded)]

        if self.sidecar_dir is not None:
            sidecar = self.sidecar_dir / f"{Path(filename).stem}.ocr.json"
            if sidecar.exists():
                return [OcrLine(text=line, score=1.0) for line in json.loads(sidecar.read_text())]

        raise OCRError("The stub OCR engine has no text for this file (no ocr_lines metadata or sidecar).")


@lru_cache(maxsize=None)
def _engine_named(name: str) -> OCREngine:
    if name in ("paddleocr", "pp-ocr", "pp-ocrv5"):
        return PaddleOCREngine()
    if name == "paddleocr-vl":
        return PaddleOCRVLEngine()
    if name == "stub":
        return StubEngine()
    raise ValueError(f"Unknown OCR_ENGINE '{name}'. Use paddleocr, paddleocr-vl or stub.")


def get_ocr_engine() -> OCREngine:
    """The configured engine, built once per process."""
    return _engine_named(settings.ocr_engine.strip().lower())
