# Data model

What the service stores, and the JSON it writes. SQLite by default
(`data/verifier.sqlite3`); set `DATABASE_URL` for PostgreSQL. Tables are
created on startup (`app/db.py`, `app/models.py`); there are no migrations
yet, so a schema change means a fresh database.

## Tables

```
subjects        id (uuid hex)  type: student|employee  external_ref  created_at
documents       id  subject_id?  kind: cv|aadhaar|pan|marksheet_10|marksheet_12|transcript  side: front|back|null  path  filename  sha256  created_at
extractions     id  document_id  source: llm|regex|ocr  engine (model or OCR engine)  payload JSON  created_at
verifications   id  subject_id  cv_document_id  id_document_ids JSON  name_score  verdict  checks_passed  payload JSON  created_at
```

- A **subject** is the person: a student or an employee, with your own key
  in `external_ref`.
- A **document** is one uploaded file, stored under `UPLOAD_DIR/<kind>/`
  with a random name; `filename` keeps the original name as data only.
- An **extraction** is what was read off one document. `payload` is a
  `CvRecord` (source `llm` or `regex`), an `IdCardRecord` (source `ocr`) or
  an `AcademicRecord` (source `llm` or `regex`; the text itself came from
  the PDF or from OCR, see `text_source`). Re-reading a document adds a new
  row; the API returns the latest.
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
  "school": {"tenth": {"percentage": 92.0, "cgpa": null, "board": "CBSE", "year": 2019},
             "twelfth": {"percentage": 91.0, "cgpa": null, "board": "Tamil Nadu State Board", "year": 2021}},
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
| `school` | the 10th and 12th results the CV *claims* (percentage or CGPA, board, year); checked against the marksheets and the form |
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

## `AcademicRecord` -- `extractions.payload` for a marksheet or transcript, and `academic.*`

```json
{
  "type": "marksheet_10",
  "detected_type": "marksheet_10",
  "full_name": "AARAV MEHTA",
  "father_name": "RAJESH MEHTA",
  "mother_name": "PRIYA MEHTA",
  "roll_last4": "4567",
  "dob": "2003-03-12",
  "board": "CENTRAL BOARD OF SECONDARY EDUCATION",
  "institution": null,
  "year": 2019,
  "subjects": [{"name": "ENGLISH", "marks": 91.0, "max_marks": 100.0, "grade": "A2"}, "…"],
  "total_marks": 460.0,
  "max_total": 500.0,
  "percentage": 92.0,
  "percentage_source": "stated",
  "percentage_computed": 92.0,
  "cgpa": null,
  "sgpa": [],
  "result": "PASS",
  "checks": {"document_type_matches": true, "percentage_matches_rows": true},
  "text_source": "ocr",
  "ocr_engine": "paddleocr",
  "ocr_detail": "default-det/default-rec via onnxruntime",
  "ocr_confidence": 0.93,
  "extraction_source": "regex",
  "llm_model": null,
  "field_sources": {"full_name": "regex", "board": "regex", "year": "regex", "subjects": "regex", "percentage": "regex", "…": "…"},
  "lines": ["CENTRAL BOARD OF SECONDARY EDUCATION", "…", "Roll No: XXXX4567", "…"]
}
```

| Field | Meaning |
| --- | --- |
| `type` / `detected_type` | the slot it was uploaded as, and what its text says it is (`checks.document_type_matches`) |
| `roll_last4` | last four characters of the roll / register / seat number; the full number is masked everywhere |
| `percentage`, `percentage_source` | the printed figure when there is one (`stated`), else what the subject rows or the total add up to (`computed`) |
| `percentage_computed` | what the rows add up to, always, so a printed figure can be checked (`checks.percentage_matches_rows`) |
| `cgpa`, `sgpa` | transcripts: the printed CGPA (or the mean of the SGPAs when not printed) and the semester list; `checks.cgpa_matches_sgpa` |
| `text_source` | `pdf` when the file had text, `ocr` when it was read off pixels |
| `extraction_source`, `field_sources` | as for the CV: the model's reading when it was on, regex otherwise; per field |

## `FormClaims` -- `verifications.payload.form`

What the placement portal's registration form holds for the student,
passed with the request so it is compared like any other source:

```json
{"full_name": "Aarav Mehta", "date_of_birth": "2003-03-12", "email": "…", "phone": "…", "cgpa": 8.4, "degree": "B.E. CSE",
 "tenth_percentage": 92.0, "tenth_cgpa": null, "tenth_year": 2019, "tenth_board": "CBSE",
 "twelfth_percentage": 91.0, "twelfth_cgpa": null, "twelfth_year": 2021, "twelfth_board": "Tamil Nadu State Board"}
```

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
  "id_cards": {"aadhaar": { "…": "an IdCardRecord" }, "pan": { "…": "an IdCardRecord" }},
  "academic": {"marksheet_10": { "…": "an AcademicRecord" }, "transcript": { "…": "an AcademicRecord" }},
  "form": { "…": "the FormClaims given, or null" }
}
```

With academic documents and a form the `checks` list grows: `cgpa_consistent`
(`"form 8.4 vs CV 8.4 vs transcript 8.4"`), `tenth_marks_consistent`,
`twelfth_marks_consistent`, `tenth_year_consistent`, `academic_years_in_order`,
`marksheet_10_percentage_matches_rows`, `transcript_cgpa_matches_sgpa`,
`form_vs_cv_name_match`, `form_email_on_cv`, `form_phone_on_cv`. A figure
check compares every pair of sources that state it and names the pairs
that disagree in `detail` -- `"form 9.1 vs CV 8.4 vs transcript 8.4 -- differ:
form/CV, form/transcript"`.

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
