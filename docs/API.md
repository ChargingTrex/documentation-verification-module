# API reference

Base URL in development: `http://localhost:8010`. Interactive docs with
try-it-out forms are served at `/docs` (Swagger UI) and `/redoc`.

All uploads are `multipart/form-data`. Responses are JSON. Errors follow
FastAPI's shape: `{"detail": "..."}` with `400` (bad upload), `404`
(unknown id), `422` (unreadable file or invalid field).

Upload limits: `MAX_UPLOAD_BYTES` (default 10 MB). CVs: `.pdf`, `.docx`.
Cards: `.png`, `.jpg`, `.jpeg`, `.webp`, `.pdf` (first page).

---

## `GET /health`

Which pieces are live. Safe to poll.

```json
{
  "status": "ok",
  "ocr_engine": "paddleocr",
  "llm": {"enabled": true, "model": "gemma4:e4b", "base_url": "http://localhost:11434/v1",
          "mode": "local", "api_key_set": false},
  "matching": {"ok": true, "backend": "tfidf", "detail": "scikit-learn TfidfVectorizer, word 1-2 grams",
               "suggested_threshold": 0.1},
  "database": "sqlite"
}
```

`llm.mode` is `local` (an Ollama on this machine or network, no key),
`hosted` (a provider reached with `LLM_API_KEY`) or `off`. The key itself is
never returned.

---

## `POST /verify`

The main call: one CV plus the ID cards, in one request.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `cv` | file | yes | PDF or DOCX |
| `aadhaar_front` | file | one of the three | name, DOB, gender, number |
| `aadhaar_back` | file | one of the three | address, number |
| `pan` | file | one of the three | PAN card |
| `subject_type` | `student` \| `employee` | no (default `student`) | |
| `external_ref` | string | no | PRN, employee id -- your key for the person |
| `subject_id` | string | no | attach to an existing subject instead of creating one |

Any combination of card files is accepted as long as at least one is
present: Aadhaar front only, both sides, PAN only, or everything.

```bash
curl -F cv=@resume.pdf -F aadhaar_front=@front.jpg -F aadhaar_back=@back.jpg -F pan=@pan.jpg \
     -F subject_type=employee -F external_ref=EMP-0042 http://localhost:8010/verify
```

Response: a **`VerificationResult`** (see [DATA_MODEL.md](DATA_MODEL.md)).
The short version:

```json
{
  "verification_id": "…", "subject_id": "…", "subject_type": "employee", "external_ref": "EMP-0042",
  "cv_document_id": "…",
  "documents": [{"document_id": "…", "kind": "cv", "side": null, "filename": "resume.pdf"},
                {"document_id": "…", "kind": "aadhaar", "side": "front", "filename": "front.jpg"},
                {"document_id": "…", "kind": "aadhaar", "side": "back", "filename": "back.jpg"},
                {"document_id": "…", "kind": "pan", "side": "front", "filename": "pan.jpg"}],
  "name_match": {"cv": "Aarav Mehta", "id": "Aarav Mehta", "score": 100.0, "verdict": "match", "method": "exact", "...": "…"},
  "name_matches": {"aadhaar": {"…": "…"}, "pan": {"…": "…"}, "aadhaar_vs_pan": {"…": "…"}},
  "checks": [{"name": "aadhaar_checksum", "passed": true, "detail": null}, "…"],
  "cv": {"full_name": "Aarav Mehta", "emails": ["…"], "phones": ["…"], "address": {"…": "…"},
         "education": [], "experience": [], "field_sources": {"full_name": "llm", "emails": "regex", "…": "…"},
         "...": "…"},
  "id_cards": {"aadhaar": {"type": "aadhaar", "detected_type": "aadhaar", "sides": ["front", "back"],
                           "full_name": "Aarav Mehta", "id_last4": "0124", "...": "…"},
               "pan": {"…": "…"}}
}
```

- `name_match` is the overall verdict: the **worst** of the CV-vs-card
  comparisons. `match` ≥ `NAME_MATCH_THRESHOLD` (85), `review` ≥
  `NAME_REVIEW_THRESHOLD` (70), else `mismatch`. A name with initials can
  reach `review` at most.
- `name_matches` has one entry per card given and `aadhaar_vs_pan` when
  both were.
- `checks` is the list a reviewer reads: `cv_name_found`,
  `<card>_name_found`, `<card>_name_match`, `card_type_matches` (the card's
  printed headings agree with the slot it was uploaded in),
  `aadhaar_number_found`, `aadhaar_checksum` (Verhoeff), `aadhaar_sides_agree`
  (front and back print the same number), `pan_format`, `pan_individual`
  (fourth letter P), `aadhaar_vs_pan_name_match`, `dob_consistent` (across
  every document that states a date of birth).

Timing on a CPU-only laptop: a card ~5–12 s; the CV under a second on the
regex path, ~3 min with a local 4B model, a few seconds with a hosted one.

---

## `POST /verify/documents`

The same verdict for documents uploaded earlier with `/documents/cv` and
`/documents/id`. JSON body:

```json
{"cv_document_id": "…", "aadhaar_front_document_id": "…", "aadhaar_back_document_id": "…", "pan_document_id": "…"}
```

At least one card id. The documents must belong to one subject (a document
without a subject is attached to the others' subject).

---

## `POST /documents/cv`

Read a CV on its own.

| Field | Type | Required |
| --- | --- | --- |
| `file` | PDF or DOCX | yes |
| `subject_type`, `external_ref`, `subject_id` | as above | no |

Response: `{document_id, subject_id, kind: "cv", filename, sha256, cv: CvRecord}`.

## `POST /documents/id`

Read one card image on its own.

| Field | Type | Required |
| --- | --- | --- |
| `file` | image or PDF | yes |
| `type` | `aadhaar` \| `pan` | yes |
| `side` | `front` \| `back` | no (default `front`; `back` is Aadhaar only) |
| `subject_type`, `external_ref`, `subject_id` | as above | no |

Response: `{document_id, subject_id, kind, filename, sha256, id_card: IdCardRecord}`.

## `GET /documents/{document_id}`

The document row and its latest extraction (`extraction`, with
`extraction_source` = `llm` / `regex` / `ocr` and `extraction_engine`).

## `GET /subjects/{subject_id}`

The subject, every document with its latest extraction, and
`latest_verification`.

## `GET /verifications/{verification_id}`

A stored `VerificationResult`.

---

## `POST /match/screen`

Bulk screening from the placement portal's engine: rank resume texts
against a job description, with hard filters applied first.

```json
{
  "candidates": {"PRN001": "resume text…", "PRN002": "…"},
  "job_description": "Backend engineer, Django, PostgreSQL…",
  "similarity_threshold": 0.1,
  "min_experience_years": 2,
  "required_education": ["UG"]
}
```

Response: `{backend, threshold, considered, shortlisted, below_threshold, excluded, ranked: [...], below_threshold_results: [...], excluded_results: [...]}`; each result carries `identifier`, `similarity_score`, `passed_threshold`, `excluded_by`, `experience_years`, `education_levels`.

---

## `GET /`

The single-page UI: upload a CV and the cards, see the verdict, every field
with its source badge (LLM / Regex / OCR), the checks, and the raw JSON.
