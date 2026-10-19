# The API with PaddleOCR built in. Linux gets a current paddlepaddle and runs
# the models on it; the macOS x86_64 pin in pyproject.toml does not apply here.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# OpenCV (pulled in by PaddleOCR) needs these at import time.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /srv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra ocr

COPY app ./app
RUN mkdir -p /srv/data/uploads

ENV PATH="/srv/.venv/bin:$PATH" \
    OCR_ENGINE=paddleocr \
    OCR_INFERENCE_ENGINE=paddle \
    LLM_BASE_URL=http://ollama:11434/v1 \
    UPLOAD_DIR=/srv/data/uploads \
    DATABASE_URL=sqlite:////srv/data/verifier.sqlite3

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
