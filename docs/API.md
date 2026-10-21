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
| `aadhaar_front` | file | at least one document | name, DOB, gender, number |
| `aadhaar_back` | file | at least one document | address, number |
| `pan` | file | at least one document | PAN card |
| `marksheet_10` | file | at least one document | 10th standard marksheet (image or PDF) |
| `marksheet_12` | file | at least one document | 12th standard marksheet |
| `transcript` | file | at least one document | college transcript / consolidated grade card |
| `form` | JSON string | no | the registration form's claims -- see below |
| `subject_type` | `student` \| `employee` | no (default `student`) | |
| `external_ref` | string | no | PRN, employee id -- your key for the person |
| `subject_id` | string | no | attach to an existing subject instead of creating one |

Any combination of documents is accepted as long as at least one besides
the CV is present.

```bash
curl -F cv=@resume.pdf -F aadhaar_front=@front.jpg -F aadhaar_back=@back.jpg -F pan=@pan.jpg \
     -F marksheet_10=@tenth.jpg -F marksheet_12=@twelfth.jpg -F transcript=@grades.pdf \
     -F 'form={"full_name":"Aarav Mehta","date_of_birth":"2003-03-12","cgpa":8.4,"tenth_percentage":92.0,"twelfth_percentage":91.0}' \
     -F subject_type=student -F external_ref=PRN2022CS001 http://localhost:8010/verify
```

**`form`** carries what the student typed into the placement portal's
registration form, so every figure can be checked three ways: form claim,
CV claim, document evidence. Keys (all optional): `full_name`,
`date_of_birth` (YYYY-MM-DD), `email`, `phone`, `cgpa`, `degree`,
`tenth_percentage`, `tenth_cgpa`, `tenth_year`, `tenth_board`,
`twelfth_percentage`, `twelfth_cgpa`, `twelfth_year`, `twelfth_board`.

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
- `name_matches` also holds `form_vs_cv`, `form_vs_aadhaar`, `form_vs_pan`
  when a `form` with a name was given.
- `checks` is the list a reviewer reads. Identity: `cv_name_found`,
  `<doc>_name_found`, `<doc>_name_match`, `card_type_matches` (the card's
  printed headings agree with the slot it was uploaded in),
  `aadhaar_number_found`, `aadhaar_checksum` (Verhoeff), `aadhaar_sides_agree`
  (front and back print the same number), `pan_format`, `pan_individual`
  (fourth letter P), `aadhaar_vs_pan_name_match`, `form_vs_*_name_match`,
  `form_email_on_cv`, `form_phone_on_cv`. Academic:
  `<sheet>_document_type_matches` (a 10th sheet in the 12th slot),
  `<sheet>_percentage_matches_rows` (the printed percentage equals what the
  subject rows add up to), `transcript_cgpa_matches_sgpa`. Figures, each
  compared **pairwise across every source that states it** -- form, CV,
  document -- with the pairs that disagree named in `detail`:
  `cgpa_consistent` (form / CV / transcript, ±0.1), `tenth_marks_consistent`
  and `twelfth_marks_consistent` (form / CV / marksheet, ±0.5 %),
  `tenth_cgpa_consistent`, `twelfth_cgpa_consistent`, `tenth_year_consistent`,
  `twelfth_year_consistent`, `academic_years_in_order` (10th < 12th < degree),
  `dob_consistent` (form, CV, cards, sheets).

Timing on a CPU-only laptop: a card ~5–12 s; the CV under a second on the
regex path, ~3 min with a local 4B model, a few seconds with a hosted one.

---

## `POST /verify/documents`

The same verdict for documents uploaded earlier with `/documents/cv`,
`/documents/id` and `/documents/academic`. JSON body:

```json
{"cv_document_id": "…", "aadhaar_front_document_id": "…", "aadhaar_back_document_id": "…", "pan_document_id": "…",
 "marksheet_10_document_id": "…", "marksheet_12_document_id": "…", "transcript_document_id": "…",
 "form": {"cgpa": 8.4, "tenth_percentage": 92.0}}
```

At least one document id besides the CV. The documents must belong to one
subject (a document without a subject is attached to the others' subject).

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

## `POST /documents/academic`

Read a marksheet or transcript on its own.

| Field | Type | Required |
| --- | --- | --- |
| `file` | image or PDF | yes |
| `type` | `marksheet_10` \| `marksheet_12` \| `transcript` | yes |
| `subject_type`, `external_ref`, `subject_id` | as above | no |

A PDF with text is read as text; a scan goes through OCR. Response:
`{document_id, subject_id, kind, filename, sha256, academic: AcademicRecord}`
-- name, father's/mother's name, roll number (last four), DOB, board or
university, year, subject rows, total, percentage (printed, and what the
rows add up to), CGPA, SGPAs, result, each with its source.

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
