# Data model

What the service stores, and the JSON it writes. SQLite by default
(`data/verifier.sqlite3`); set `DATABASE_URL` for PostgreSQL. Tables are
created on startup (`app/db.py`, `app/models.py`); there are no migrations
yet, so a schema change means a fresh database.

## Tables

```
subjects        id (uuid hex)  type: student|employee  external_ref  created_at
documents       id  subject_id?  kind: cv|aadhaar|pan  side: front|back|null  path  filename  sha256  created_at
extractions     id  document_id  source: llm|regex|ocr  engine (model or OCR engine)  payload JSON  created_at
verifications   id  subject_id  cv_document_id  id_document_ids JSON  name_score  verdict  checks_passed  payload JSON  created_at
```

- A **subject** is the person: a student or an employee, with your own key
  in `external_ref`.
- A **document** is one uploaded file, stored under `UPLOAD_DIR/<kind>/`
  with a random name; `filename` keeps the original name as data only.
- An **extraction** is what was read off one document. `payload` is a
  `CvRecord` (source `llm` or `regex`) or an `IdCardRecord` (source `ocr`).
  Re-reading a document adds a new row; the API returns the latest.
- A **verification** ties one CV to the cards it was checked against.
  `payload` is the full `VerificationResult`; the columns beside it exist
  so a verdict can be listed and filtered without opening the JSON.

Nothing stored contains a full Aadhaar or PAN number: records carry
`id_last4`, and the audit `lines` are masked (`XXXX XXXX 0124`,
`XXXXXX234F`).

## `CvRecord` -- `extractions.payload` for a CV

```json
{
  "full_name": "Aarav Mehta",
  "emails": ["aarav.mehta@college.edu"],
  "phones": ["9876543210"],
  "address": {"raw": "12, Gandhi Street, T. Nagar, Chennai - 600017, Tamil Nadu", "pincode": "600017", "state": "Tamil Nadu"},
  "education": [
    {"degree": "B.Tech in Computer Engineering", "level": "UG", "field": "Computer Engineering",
     "institution": "Sai University", "start": "2022", "end": "2026", "cgpa": 8.4}
  ],
  "experience": [
    {"role": "Backend Intern", "organization": "Acme", "kind": "internship",
     "start": "2025-06", "end": "2025-08", "is_current": false, "summary": "Built REST APIs."}
  ],
  "experience_years": 0.2,
  "education_levels": ["UG"],
  "highest_education_level": "UG",
  "skills": ["Python", "Django", "PostgreSQL"],
  "cgpa": 8.4,
  "date_of_birth": "2003-03-12",
  "extraction_source": "llm",
  "llm_model": "gemma4:e4b",
  "field_sources": {
    "full_name": "llm", "emails": "regex", "phones": "regex", "address": "llm",
    "education": "llm", "experience": "llm", "skills": "llm",
    "experience_years": "llm", "education_levels": "llm", "cgpa": "regex", "date_of_birth": "llm"
  },
  "regex_facts": {"experience_years": 0.2, "experience_source": "date_ranges", "education_levels": ["UG"],
                  "age": null, "date_of_birth": null, "emails": ["aarav.mehta@college.edu"],
                  "phones": ["9876543210"], "cgpa": 8.4, "address": {"…": "…"}, "full_name": "Aarav Mehta"},
  "agreement": {"experience_years": {"regex": 0.2, "llm": 0.2, "agree": true},
                "education_level": {"regex": "UG", "llm": "UG", "agree": true},
                "cgpa": {"regex": 8.4, "llm": 8.4, "agree": true}},
  "text_length": 2457
}
```

| Field | Meaning |
| --- | --- |
| `extraction_source` | `llm` when the model's reading was used, `regex` when it was off or failed (the regex path always runs) |
| `field_sources` | per field: `llm`, `regex` or `none`. Emails and phones are regex's whenever it found any -- the patterns are exact -- and the model only fills gaps |
| `experience_years` | from the model's dated entries when it found any (computed in Python from the dates, never taken from the model's arithmetic), else regex's reading of stated durations and date ranges |
| `education_levels` | `UG`, `Masters`, `PG`; the model's when it found any, else regex's |
| `agreement` | where regex and the model read the same resume differently; a reviewer's cue |
| `regex_facts` | the regex reading in full, kept for audit |
| `level`, `kind` | closed vocabularies: `UG|Masters|PG`, `internship|part_time|full_time|volunteer|freelance` |

## `IdCardRecord` -- `extractions.payload` for a card, and `id_cards.*`

```json
{
  "type": "aadhaar",
  "detected_type": "aadhaar",
  "sides": ["front", "back"],
  "full_name": "Aarav Mehta",
  "id_last4": "0124",
  "dob": "2003-03-12",
  "year_of_birth": 2003,
  "gender": "M",
  "father_name": null,
  "address": {"raw": "S/O: Rajesh Mehta, 12 Gandhi Street, T Nagar, Chennai, Tamil Nadu - 600017", "pincode": "600017", "state": "Tamil Nadu"},
  "phones": [],
  "ocr_engine": "paddleocr",
  "ocr_detail": "default-det/default-rec via onnxruntime",
  "ocr_confidence": 0.86,
  "checks": {"aadhaar_number_found": true, "aadhaar_checksum": true, "aadhaar_sides_agree": true, "card_type_matches": true},
  "lines": ["front: GOVERNMENT OF INDIA", "front: Aarav Mehta", "front: DOB: 12/03/2003", "front: MALE",
            "front: XXXX XXXX 0124", "back: Address:", "back: …", "back: XXXX XXXX 0124"]
}
```

| Field | Meaning |
| --- | --- |
| `type` | the slot it was uploaded as: `aadhaar` or `pan` |
| `detected_type` | what the printed headings say it is; `null` when unclear. `checks.card_type_matches` is false when it disagrees with `type` |
| `sides` | which images were read; an Aadhaar front and back are merged into one record |
| `id_last4` | last four characters of the number -- the full number is never stored |
| `gender` | `M`, `F`, `O` |
| `father_name` | PAN cards only |
| `checks` | Aadhaar: `aadhaar_number_found`, `aadhaar_checksum` (Verhoeff), `aadhaar_sides_agree`. PAN: `pan_format`, `pan_individual`. Both: `card_type_matches` |
| `lines` | the OCR lines, numbers masked, prefixed with the side when both were read; for audit and parser tuning |

## `VerificationResult` -- `verifications.payload`

```json
{
  "verification_id": "…",
  "subject_id": "…",
  "subject_type": "student",
  "external_ref": "PRN2022CS001",
  "cv_document_id": "…",
  "documents": [
    {"document_id": "…", "kind": "cv", "side": null, "filename": "resume.pdf"},
    {"document_id": "…", "kind": "aadhaar", "side": "front", "filename": "front.jpg"},
    {"document_id": "…", "kind": "pan", "side": "front", "filename": "pan.jpg"}
  ],
  "name_match": {"cv": "Aarav Mehta", "id": "AARAV MEHTA", "cv_normalised": "AARAV MEHTA", "id_normalised": "AARAV MEHTA",
                 "score": 100.0, "verdict": "match", "method": "exact"},
  "name_matches": {
    "aadhaar": {"…": "…"},
    "pan": {"…": "…"},
    "aadhaar_vs_pan": {"…": "…"}
  },
  "checks": [
    {"name": "cv_name_found", "passed": true, "detail": "The CV reading has a name"},
    {"name": "aadhaar_name_found", "passed": true, "detail": "Sides read: front"},
    {"name": "aadhaar_name_match", "passed": true, "detail": "match at 100 (exact)"},
    {"name": "card_type_matches", "passed": true, "detail": null},
    {"name": "aadhaar_number_found", "passed": true, "detail": null},
    {"name": "aadhaar_checksum", "passed": true, "detail": null},
    {"name": "pan_name_found", "passed": true, "detail": "Sides read: front"},
    {"name": "pan_name_match", "passed": true, "detail": "match at 100 (exact)"},
    {"name": "pan_format", "passed": true, "detail": null},
    {"name": "pan_individual", "passed": true, "detail": null},
    {"name": "aadhaar_vs_pan_name_match", "passed": true, "detail": "match at 100 (exact)"},
    {"name": "dob_consistent", "passed": true, "detail": "aadhaar 2003-03-12 vs pan 2003-03-12"}
  ],
  "cv": { "…": "a CvRecord" },
  "id_cards": {"aadhaar": { "…": "an IdCardRecord" }, "pan": { "…": "an IdCardRecord" }}
}
```

| Field | Meaning |
| --- | --- |
| `name_match` | the overall verdict: the worst of the CV-vs-card comparisons |
| `name_matches` | CV vs each card; `aadhaar_vs_pan` when both cards were given |
| `verdict` | `match` (score ≥ `NAME_MATCH_THRESHOLD`, default 85), `review` (≥ `NAME_REVIEW_THRESHOLD`, 70), `mismatch` |
| `method` | `exact`, `token_set` (rapidfuzz token-set ratio: word order and middle names do not matter), `initials_capped` (an initial can only confirm up to `review`), `missing` (a name was not read) |
| `checks` | the reviewer's list; every entry is `{name, passed, detail}` |

## A note on the name comparison

Names are normalised (accents stripped, upper case, honorifics such as
Mr/Dr/Shri/Smt removed, punctuation dropped) before comparison, so
`"Dr. S. Kumar"` and `"S KUMAR"` compare equal. The normalised forms are
returned so a reviewer can see exactly what was compared.
