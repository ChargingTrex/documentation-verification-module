# AGENTS.md — Document Verifier build plan

How a coding agent builds this service. Phases in order; a phase's
checkpoint must pass -- actually run, output shown -- before the next starts.

## Ground rules
- Announce the phase/task before touching code. Tests first where practical.
- Every task ends with `uv run pytest` green. Commit per task, message named
  `phase-N: <task>`.
- No test may need Ollama, PaddleOCR or the network. Opt-in markers:
  `paddle`, `ollama`.
- Privacy: ID numbers are stored as `id_last4` only; uploads get random
  names; the LLM is a local Ollama, never a third-party API.
- Settings live in `app/config.py`; read them at call time, not import time.

## Phase 0 — Scaffold  ✅
- [x] uv project, FastAPI shell, `/health`, static UI shell at `/`
- [x] SQLAlchemy models: Subject, Document, Extraction, Verification (SQLite default)
- [x] Dockerfile + docker-compose (api, ollama; ocr-vl under profile `vl`)
- [x] Ollama upgraded; `gemma4:e4b` pulled
- **Checkpoint:** `/health` 200 naming the model; `/docs` renders; `/` serves the shell.

## Phase 1 — Resume engine (ported from the portal)  ✅
- [x] `extraction/text.py`, `extraction/facts.py` + 62 tests, verbatim
- [x] `llm/` ported DRF → Pydantic; prompt and schema gain `address`
- [x] `matching/` ported; `ExtractedProfile.llm_model`
- [x] `extraction/address.py` regex fallback; `extraction/record.py` with `field_sources`
- [x] `POST /documents/cv`, `GET /documents/{id}`, `GET /subjects/{id}`, `POST /match/screen`
- **Checkpoint:** fixture PDFs give the reference experience/education with
  `field_sources` all regex; with Ollama up, name/address/education come back `llm`.

## Phase 2 — OCR + ID cards
- [x] `ocr/engine.py`: `OCREngine` protocol; `PaddleOCREngine` (PaddlePaddle or
      onnxruntime -- the latter on an Intel Mac, where the models do not load on
      paddlepaddle 3.0.0), `PaddleOCRVLEngine` (HTTP), `StubEngine`
- [x] `ocr/aadhaar.py` (Verhoeff checksum, name/DOB/gender/address), `ocr/pan.py`
- [x] `POST /documents/id`; synthetic card fixtures (Pillow) with the lines embedded
- [x] `Dockerfile.ocr-vl` + `ocr_vl_server/` + `bench/ocr_bench.py`
- [x] PaddleOCR model variants measured on three real scans (README table); defaults kept
- [ ] Benchmark PaddleOCR vs PaddleOCR-VL 1.5 (needs the Docker image; `bench/ocr_bench.py`)
- **Checkpoint (passed 2026-10-19):** stub parsers pass on 4 Aadhaar + 3 PAN
  layouts; on real scans PaddleOCR read the Aadhaar front (name, DOB, gender,
  number + checksum), the Aadhaar back (address with PIN and state) and the PAN
  (name, father's name, DOB, PAN format) -- 8/8 fields, 5-12 s per image.

## Phase 3 — Verification + UI
- [x] `verify/names.py` (normalise, initials capped at review, token_set_ratio, thresholds)
- [x] `verify/service.py`, `POST /verify`, `POST /verify/documents`, `GET /verifications/{id}`
- [x] `static/index.html`: upload both, verdict banner, per-field source badges
- [x] Real documents: pdfium before PyPDF2 (glyph-per-line PDFs), top-line name on the regex path
- **Checkpoint (passed 2026-10-19):** Aarav CV vs "Aarav Mehta" Aadhaar → match;
  vs Kabir → mismatch; "A. Mehta" → review. A real resume vs a real Aadhaar of a
  different person → mismatch at 23, with name/email/phone/address/experience
  read on the regex path. LLM pass with `gemma4:e4b`: pending the model download.
