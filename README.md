# Document Verifier

Reads a CV and a scanned **Aadhaar** and/or **PAN** card, checks that they
belong to the same person, and returns the CV's facts — name, address,
phone, email, education, experience — as JSON ready for a database. Built
for a college placement cell and an HR desk: students and employees.

Everything can run on one machine: a local model reads the CV, PaddleOCR
reads the cards, nothing leaves the box. Or plug in a hosted LLM with an
API key if that suits your setup.

> **Status:** prototype. The readers are tuned on a handful of real
> documents and a set of synthetic ones; expect to add cases. See
> [CONTRIBUTING.md](CONTRIBUTING.md).

## What it does

| Step | How |
| --- | --- |
| Read the CV | PDF/DOCX → text (pdfium, then PyPDF2); regex readers for email, phone, address, name, experience, education level; a local or hosted LLM for the structured reading (education and experience entries, skills, address) |
| Read the cards | PaddleOCR → lines; Aadhaar parser (name, DOB, gender, number with Verhoeff checksum, address from the back) and PAN parser (name, father's name, DOB, PAN format). The card's printed headings identify its type; they never become a name |
| Compare | normalised names, token-set similarity, initials capped at "review"; CV vs every card, cards vs each other; dates of birth across all documents |
| Store | subjects, documents, extractions, verifications — SQLite or PostgreSQL. Only the last four digits of any ID number are kept |
| Show | a one-page UI: verdict, every field with a badge saying what read it (**LLM** / **Regex** / **OCR**), the checks, the raw JSON |

Every CV field says where it came from. Emails and phones are always the
regex readers' when they found any — the patterns are exact — and the model
only fills gaps. `agreement` shows where regex and the model disagree.

## Quick start

```bash
git clone https://github.com/ChargingTrex/documentation-verification-module.git
cd documentation-verification-module
uv sync --extra dev
uv run uvicorn app.main:app --reload --port 8010
open http://localhost:8010         # the UI;  /docs for the API
```

That runs with regex extraction, TF-IDF similarity and the stub OCR
engine. Add the pieces you want:

| Piece | Install | Configure |
| --- | --- | --- |
| **OCR** for ID cards | `uv sync --extra ocr` | `OCR_ENGINE=paddleocr` (default). First run downloads the models |
| **Local LLM** for the CV | [Ollama](https://ollama.com), `ollama pull gemma4:e4b` | `LLM_ENABLED=true` (default); nothing leaves the machine |
| **Hosted LLM** instead | an API key from any OpenAI-compatible provider | `LLM_BASE_URL`, `LLM_MODEL`, `LLM_API_KEY` — see below |
| spaCy similarity | `uv sync --extra nlp && uv run python -m spacy download en_core_web_md` | `MATCHING_BACKEND=auto` |
| Docker | `docker compose up api ollama` | the API with PaddleOCR, plus Ollama |

Copy `.env.example` to `.env` to change anything; every value has a
working default.

### Docker

```bash
docker compose up api ollama                       # API on :8010 with PaddleOCR, plus Ollama
docker compose exec ollama ollama pull gemma4:e4b  # once; the model lives in a volume
```

Or just the API image, bringing your own LLM:

```bash
docker build -t document-verifier .
docker run -p 8010:8000 -v "$(pwd)/data:/srv/data" -v paddlex:/root/.paddlex \
  -e LLM_BASE_URL=https://api.groq.com/openai/v1 -e LLM_MODEL=llama-3.3-70b-versatile -e LLM_API_KEY=... \
  document-verifier
```

Uploads and the SQLite database land in `./data`; the OCR models download
on first use into the `paddlex` volume. Inside the container PaddleOCR
runs on PaddlePaddle's own runtime (Linux has the wheels).

### Using a hosted LLM (API key)

The client speaks the OpenAI chat API, so any provider that implements it
works. In `.env`:

```bash
LLM_BASE_URL=https://api.groq.com/openai/v1     # or OpenAI, OpenRouter, Together, Mistral, Gemini …
LLM_MODEL=llama-3.3-70b-versatile
LLM_API_KEY=gsk_...
# LLM_JSON_MODE=false   # only if the provider rejects response_format=json_object
```

`.env.example` lists the base URLs. `/health` then reports
`"mode": "hosted"` (the key itself is never returned). **This sends the
resume text to that provider** — the cards never go to the LLM, only the
CV — so make sure that is acceptable for the documents you handle. The
default, a local Ollama, sends nothing anywhere.

## API

| Method | Path | What |
| --- | --- | --- |
| `GET` | `/health` | which OCR engine, LLM and similarity backend are live |
| `POST` | `/verify` | `cv` + any of `aadhaar_front`, `aadhaar_back`, `pan` → verdict per card and overall |
| `POST` | `/verify/documents` | the same for documents uploaded earlier |
| `POST` | `/documents/cv` | read a CV on its own → the CV record |
| `POST` | `/documents/id` | read one card (`type`, `side`) → the card record |
| `GET` | `/documents/{id}`, `/subjects/{id}`, `/verifications/{id}` | read back |
| `POST` | `/match/screen` | rank resume texts against a job description (bulk screening) |

Full reference with request/response shapes: [docs/API.md](docs/API.md).
What goes into the database, field by field: [docs/DATA_MODEL.md](docs/DATA_MODEL.md).

```bash
curl -F cv=@resume.pdf -F aadhaar_front=@front.jpg -F aadhaar_back=@back.jpg -F pan=@pan.jpg \
     -F subject_type=student -F external_ref=PRN2022CS001 http://localhost:8010/verify
```

## Privacy

- Uploaded files go to `data/uploads/<cv|aadhaar|pan>/` under random
  names. The folders are in git; their contents are ignored. Never commit a
  real document.
- ID numbers are stored as the last four characters only; the OCR audit
  lines are masked before they are kept.
- The LLM sees the CV text, never the card images. With the default local
  Ollama nothing leaves the machine.
- `.env` holds your API key and is ignored by git.

## OCR notes

- **Intel Mac.** PaddlePaddle stopped shipping macOS x86_64 wheels after
  3.0.0, and the current PP-OCR models do not load on 3.0.0. PaddleOCR ships
  the same models in ONNX form, so on an Intel Mac the engine runs them on
  onnxruntime (`OCR_INFERENCE_ENGINE=auto` picks this; ~5–12 s per card on a
  2018 i7). Elsewhere PaddlePaddle's own runtime is used.
- **Orientation.** Document rotation detection (`OCR_ORIENTATION=true`) is
  on. PaddleOCR's text-line orientation classifier is off
  (`OCR_TEXTLINE_ORIENTATION=false`): on a real PAN scan it flipped lines in
  the top half and lost the name and number.
- **Models, measured.** Three real scans (Aadhaar front, Aadhaar back, PAN)
  through the parsers; fields checked: name, last four digits, DOB, PIN.

  | Models | Fields right | s/image |
  | --- | --- | --- |
  | PaddleOCR 3.7 defaults (PP-OCRv6 medium) | 8 / 8 | 10.0 |
  | PP-OCRv5_mobile_det + PP-OCRv5_mobile_rec | 7 / 8 | 4.9 |
  | PP-OCRv5_server_det + PP-OCRv5_server_rec | 6 / 8 | 51.4 |
  | PP-OCRv5_mobile_det + en_PP-OCRv5_mobile_rec | 5 / 8 | 4.4 |

  Set `OCR_TEXT_DETECTION_MODEL` / `OCR_TEXT_RECOGNITION_MODEL` to change.
- **PaddleOCR-VL 1.5** is wired as a second engine behind a container
  (`docker compose --profile vl up ocr-vl`, `OCR_ENGINE=paddleocr-vl`,
  `uv run python -m bench.ocr_bench`) but has not been benchmarked here yet.

## Timing

On a 2018 Intel i7, CPU only: a card ~5–12 s; the CV under a second on the
regex path, ~3 min with `gemma4:e4b` locally, a few seconds with a hosted
model. The UI says so while it waits.

## Tests

```bash
uv run pytest
```

No test needs Ollama, PaddleOCR or the network: the suite runs on the stub
OCR engine and a fake LLM client. Tests marked `paddle` / `ollama` use the
real engines and are skipped unless the environment says otherwise.

## Layout

```text
app/
  extraction/   text.py (PDF/DOCX → text)  facts.py (regex)  address.py  name.py  record.py
  llm/          client.py (OpenAI-compatible, local or hosted)  prompts.py  schema.py  resume.py
  ocr/          engine.py  cards.py (shared, card-type detection)  aadhaar.py  pan.py  verhoeff.py
  verify/       names.py  service.py
  matching/     backends.py  engine.py (similarity + bulk screening)
  api/          documents.py  subjects.py  verify.py  match.py
  static/       index.html (the UI)
docs/           API.md  DATA_MODEL.md
tests/          fixtures/ (synthetic resumes and cards, generated by make_*.py)
bench/          ocr_bench.py
ocr_vl_server/  the PaddleOCR-VL container's HTTP front
```

Build plan and checkpoints: [AGENTS.md](AGENTS.md). Contributing:
[CONTRIBUTING.md](CONTRIBUTING.md).

## Origin and license

The resume readers and the matching engine were ported from a college
placement portal's `matching` app; the OCR, card parsers and verification
are new. Built with Claude Code.

Licensed under the GNU General Public License v3.0 — see [LICENSE](LICENSE).
