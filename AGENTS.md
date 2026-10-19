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

## Phase 1 — Resume engine (ported from the portal)
- [x] `extraction/text.py`, `extraction/facts.py` + 62 tests, verbatim
- [x] `llm/` ported DRF → Pydantic; prompt and schema gain `address`
- [x] `matching/` ported; `ExtractedProfile.llm_model`
- [x] `extraction/address.py` regex fallback; `extraction/record.py` with `field_sources`
- [ ] `POST /documents/cv`, `GET /documents/{id}`, `GET /subjects/{id}`, `POST /match/screen`
- **Checkpoint:** fixture PDFs give the reference experience/education with
  `field_sources` all regex; with Ollama up, name/address/education come back `llm`.

## Phase 2 — OCR + ID cards
- [ ] `ocr/engine.py`: `OCREngine` protocol; `PaddleOCRv5Engine`, `PaddleOCRVLEngine` (HTTP), `StubEngine`
- [ ] `ocr/aadhaar.py` (Verhoeff checksum, name/DOB/gender/address), `ocr/pan.py`
- [ ] `POST /documents/id`; synthetic card fixtures (Pillow) + stub OCR JSON
- [ ] `Dockerfile.ocr-vl` + `bench/ocr_bench.py`; results table in README
- **Checkpoint:** stub parsers pass on 3 Aadhaar + 3 PAN layouts; PP-OCRv5
  reads name + last-4 on one real render of each; benchmark recorded.

## Phase 3 — Verification + UI
- [ ] `verify/names.py` (normalise, initials, token_set_ratio, thresholds)
- [ ] `verify/service.py`, `POST /verify`, `GET /verifications/{id}`
- [ ] `static/index.html`: upload both, verdict banner, per-field source badges
- **Checkpoint:** Aarav CV vs "AARAV MEHTA" Aadhaar → match; vs Kabir → mismatch;
  "A. Mehta" → review; badges show LLM/Regex/OCR.
