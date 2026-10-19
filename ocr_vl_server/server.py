"""
A tiny HTTP front for PaddleOCR-VL 1.5, for the `ocr-vl` container.

The main API talks to this over `PaddleOCRVLEngine`. It exists because
PaddleOCR-VL needs PaddlePaddle >= 3.2.1, which has no macOS x86_64 wheel,
so on an Intel Mac the pipeline can only run inside Linux.

    uvicorn ocr_vl_server.server:app --host 0.0.0.0 --port 8118
"""

from __future__ import annotations

import io
import os

from fastapi import FastAPI, File, HTTPException, UploadFile

app = FastAPI(title="PaddleOCR-VL server")
_pipeline = None
PIPELINE_VERSION = os.getenv("OCR_VL_PIPELINE_VERSION", "v1.5")


def pipeline():
    global _pipeline
    if _pipeline is None:
        from paddleocr import PaddleOCRVL

        _pipeline = PaddleOCRVL(pipeline_version=PIPELINE_VERSION, device="cpu")
    return _pipeline


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "engine": f"paddleocr-vl-{PIPELINE_VERSION.lstrip('v')}"}


@app.post("/ocr")
async def ocr(file: UploadFile = File(...)) -> dict:
    import numpy as np
    from PIL import Image

    data = await file.read()
    try:
        image = np.array(Image.open(io.BytesIO(data)).convert("RGB"))[:, :, ::-1]
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not open the image: {exc}") from exc

    lines = []
    for result in pipeline().predict(image):
        payload = getattr(result, "json", None)
        data_ = payload.get("res", payload) if isinstance(payload, dict) else result
        for block in data_.get("parsing_res_list") or []:
            content = (block.get("block_content") or "").strip()
            if not content:
                continue
            for part in content.split("\n"):
                if part.strip():
                    bbox = block.get("block_bbox")
                    lines.append({"text": part.strip(), "score": None,
                                  "box": bbox.tolist() if hasattr(bbox, "tolist") else bbox})
    return {"engine": f"paddleocr-vl-{PIPELINE_VERSION.lstrip('v')}", "lines": lines}
