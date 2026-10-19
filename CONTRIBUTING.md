# Contributing

Thanks for looking. This is a prototype of a document verification service
for Indian students and employees: it reads a CV and a scanned Aadhaar or
PAN card and checks that they belong to the same person. Contributions that
make the readers more accurate on real documents are the most valuable.

## Set up

```bash
git clone https://github.com/ChargingTrex/documentation-verification-module.git
cd documentation-verification-module
uv sync --extra dev          # base + tests; no OCR or LLM needed
uv run pytest                # should be green
uv run uvicorn app.main:app --reload --port 8010
```

Optional pieces:

- `uv sync --extra ocr` for real OCR (PaddleOCR). On an Intel Mac it runs
  on onnxruntime automatically; see the README.
- Ollama with `gemma4:e4b`, or a hosted OpenAI-compatible provider with
  `LLM_API_KEY`, for the structured reading of the CV.

## Ground rules

- **No test may need Ollama, PaddleOCR or the network.** The suite runs on
  the stub OCR engine (`OCR_ENGINE=stub`, set by `tests/conftest.py`) and
  `tests/fakes.py::FakeLLMClient`. Tests that need the real engines take
  the `paddle` / `ollama` markers and are skipped by default.
- **Never commit a real document.** `data/uploads/` is gitignored except
  for its empty folders; fixtures are synthetic (`tests/fixtures/make_*.py`
  generate them). If you need a regression test for a real-world read,
  reproduce the *shape* of the OCR lines with made-up names and numbers --
  see `TestPanHeuristics` in `tests/test_idcards.py` for the pattern.
- **ID numbers never leave the parsers in full.** Records carry `id_last4`
  only, and the audit `lines` are masked. Keep it that way.
- Settings live in `app/config.py` and are read at call time, so tests can
  change them; document any new one in `.env.example`.
- Match the surrounding code: a module docstring that says why the module
  exists, comments where a rule is not obvious, no comments where it is.

## Where things are

```
app/extraction/   text out of PDF/DOCX; regex readers (facts, address, name); the CV record
app/llm/          the OpenAI-compatible client, prompts, reply schema, resume reading
app/ocr/          OCR engines; Aadhaar and PAN parsers; card-type detection
app/verify/       name comparison; the verification record
app/matching/     similarity backends and bulk screening (ported from the placement portal)
app/api/          FastAPI routers
app/static/       the single-page UI
docs/             API reference and data model
bench/            OCR engine benchmark
```

## Making a change

1. Write the failing test first where you can -- the parsers in particular
   are easiest to improve by adding a case that currently reads wrong.
2. `uv run pytest` green.
3. One commit per change, message in the imperative, saying why.
4. Open a pull request. Say what document shape or provider you tested on,
   without pasting the document.

Contributions are accepted under the project's license, GPL-3.0 (see
`LICENSE`).

## Good first contributions

- Parser cases: layouts of Aadhaar (PVC card, e-Aadhaar printout, masked
  Aadhaar) and PAN (old layout without labels, laminated scans) that read
  wrong. Each is a short test plus a rule.
- Address structuring: city and district from the raw address line.
- A `/verify` benchmark on a varied set of synthetic cards (`bench/`).
- The PaddleOCR-VL comparison (`Dockerfile.ocr-vl`, `bench/ocr_bench.py`)
  has not been run on real hardware yet.
- Other ID documents (voter ID, driving licence, passport) following the
  pattern in `app/ocr/pan.py`.
