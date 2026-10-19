# Document Verifier

A small service that reads a CV and a scanned Aadhaar or PAN card, checks
that the names agree, and returns the CV's facts -- name, address, phone,
email, education, experience -- as JSON ready for a database. For students
and employees. Spun out of the placement portal's resume engine; this is the
initial prototype.

Everything runs on the machine you run it on: a local Ollama model reads the
CV, PaddleOCR reads the card. No document leaves the box.

## Run it

```bash
uv sync --extra dev            # base + tests, no OCR or LLM needed
uv run uvicorn app.main:app --reload
open http://localhost:8000     # the UI;  /docs for the API
```

Optional pieces, each off or stubbed until installed:

| Piece | Install | Then |
| --- | --- | --- |
| LLM reading of the CV | upgrade Ollama, `ollama pull gemma4:e4b` | `LLM_ENABLED=true` (default) |
| OCR for ID cards | `uv sync --extra ocr` | `OCR_ENGINE=paddleocr` (default) |
| spaCy similarity | `uv sync --extra nlp && uv run python -m spacy download en_core_web_md` | `MATCHING_BACKEND=auto` |
| PaddleOCR-VL 1.5 (benchmark only) | `docker compose --profile vl up ocr-vl` | `OCR_ENGINE=paddleocr-vl` |

Without any of them the service still works: regex extraction, TF-IDF
similarity, and the stub OCR engine (fixture text).

**Intel Mac note.** PaddlePaddle stopped shipping macOS x86_64 wheels after
3.0.0, and the current PP-OCR models do not load on 3.0.0. PaddleOCR ships
the same models in ONNX form, so on an Intel Mac the pipeline runs them on
onnxruntime (`OCR_INFERENCE_ENGINE=auto` picks this; ~9 s per card on a
2018 i7, first run downloads the models). PaddleOCR-VL needs a newer
PaddlePaddle and so runs only in Docker on an Intel Mac.

## API

| Method | Path | What |
| --- | --- | --- |
| `GET` | `/health` | which OCR engine, LLM and similarity backend are live |
| `POST` | `/documents/cv` | multipart `file` (PDF/DOCX) → the CV record with per-field sources |
| `POST` | `/documents/id` | multipart `file` + `type=aadhaar\|pan` → the card record (Phase 2) |
| `POST` | `/verify` | CV + ID card in one call → verdict (Phase 3) |
| `GET` | `/subjects/{id}` | a subject's documents and latest verification |
| `POST` | `/match/screen` | rank resume texts against a job description |

Every CV field carries its source in `field_sources`: `"llm"` (the model
read it), `"regex"` (a pattern read it) or `"none"`. Emails and phones are
always regex's when it found any; the model only fills gaps. `agreement`
shows where regex and the model read the same resume differently.

Timing on a 2018 Intel i7 (CPU only): a card ~5–12 s, a resume on the regex
path under a second, with `gemma4:e4b` ~3.5 min. The UI says so while it waits.

## OCR engine choice (measured)

Three real scans (Aadhaar front, Aadhaar back, PAN) run through
`PaddleOCR` on onnxruntime, CPU, orientation models off, then the parsers.
Fields checked: name, last four digits, date of birth, PIN code.

| Models | Fields right | s/image |
| --- | --- | --- |
| PaddleOCR 3.7 defaults (PP-OCRv6 medium) | 8 / 8 | 10.0 |
| PP-OCRv5_mobile_det + PP-OCRv5_mobile_rec | 7 / 8 | 4.9 |
| PP-OCRv5_server_det + PP-OCRv5_server_rec | 6 / 8 | 51.4 |
| PP-OCRv5_mobile_det + en_PP-OCRv5_mobile_rec | 5 / 8 | 4.4 |

The defaults stay. Of PaddleOCR's two orientation models, document
rotation detection (`OCR_ORIENTATION=true`, the default) is harmless; the
text-line orientation classifier (`OCR_TEXTLINE_ORIENTATION`, off) flipped
lines in the top half of the PAN scan and lost the name and number, so it
stays off. A card's printed headings ("INCOME TAX DEPARTMENT", "GOVT. OF
INDIA") are fuzzy-rejected as names even when OCR garbles them. PaddleOCR-VL 1.5 (`docker compose --profile
vl up ocr-vl`, then `uv run python -m bench.ocr_bench`) has not been run on
this machine yet: it needs the ~8 GB Linux image.

## Tests

```bash
uv run pytest
```

No test needs Ollama or PaddleOCR. Tests marked `paddle` / `ollama` run the
real engines and are skipped unless the environment says otherwise.

## Layout

```
app/
  extraction/   text.py (PDF/DOCX → text)  facts.py (regex)  address.py  record.py
  llm/          client.py  prompts.py  schema.py  resume.py
  ocr/          engine.py  aadhaar.py  pan.py            (Phase 2)
  verify/       names.py  service.py                     (Phase 3)
  matching/     backends.py  engine.py (similarity + bulk screening)
  api/          documents.py  subjects.py  match.py  verify.py
  static/       index.html (the UI)
tests/          fixtures/resumes, fixtures/idcards
bench/          ocr_bench.py: PP-OCRv5 vs PaddleOCR-VL   (Phase 2)
```

See `AGENTS.md` for the build plan and checkpoints.
