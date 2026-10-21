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
- [x] The card says what it is (`detected_type`, `card_type_matches`)

## Phase 4 — Academic documents and the registration form
- [x] `academic/parser.py`: 10th / 12th marksheets and transcripts from text lines -- board, year, name,
      roll (last four), DOB, subject rows, total, printed and recomputed percentage, CGPA/SGPA, result;
      `detect_academic_type`
- [x] `academic/service.py`: PDF text or OCR → regex reading + LLM reading (`llm/academic.py`) → record with sources
- [x] CV readers gain 10th/12th marks (`extraction/school.py`, `school` in the LLM schema)
- [x] `POST /documents/academic`; `/verify` takes `marksheet_10`, `marksheet_12`, `transcript` and a `form` JSON
      (the portal's registration form) -- CGPA, school marks and years, DOB compared pairwise across form / CV / document
- [x] UI: academic inputs, a registration-form section, one panel per sheet
- **Checkpoint (passed 2026-10-21, synthetic sheets):** a CV claiming CGPA 8.4 / 92% / 91% against a 10th sheet,
  a 12th sheet and a transcript → every figure check passes; the same CV with 9.1 / 95% → `cgpa_consistent` and
  `tenth_marks_consistent` fail naming the pairs; a sheet whose rows add up to 82.6% against a printed 88.5% is
  flagged; a 10th sheet in the 12th slot is flagged. Not yet run on real marksheets.

## Phase 3 checkpoint record
- **Checkpoint (passed 2026-10-19):** Aarav CV vs "Aarav Mehta" Aadhaar → match;
  vs Kabir → mismatch; "A. Mehta" → review. A real resume vs a real Aadhaar of a
  different person → mismatch at 23, with name/email/phone/address/experience
  read on the regex path. With `gemma4:e4b` on: name, address, education,
  experience, skills, DOB badged `llm`; email/phone `regex`; regex and model
  agree on experience years and education level. ~3.5 min per resume on this CPU.
