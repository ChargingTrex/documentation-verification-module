"""
One CV + the documents given (+ the registration form) -> a verification record.

A subject may hand in an Aadhaar (front, back, or both sides), a PAN, a
10th marksheet, a 12th marksheet, a college transcript -- any of them --
and the placement portal may pass along what the student typed into its
registration form. Three kinds of source, then: the form (a claim), the
CV (a claim), the documents (evidence).

The CV name is compared with every document; the two ID cards with each
other; the form name with the CV and the cards. The overall verdict is the
worst of the CV-vs-ID-card comparisons (identity first); when no card was
given, the worst of the academic documents. Every figure that more than
one source states -- CGPA, 10th and 12th marks and years, date of birth --
is compared pairwise across the sources that have it, the way the portal
compares roster, transcript and resume CGPA. Every finding is a check the
reviewer reads alongside the verdict.
"""

from __future__ import annotations

from itertools import combinations

from sqlalchemy.orm import Session

from app.extraction.facts import find_phones
from app.models import Document, Subject, Verification
from app.verify.names import compare

_SEVERITY = {"mismatch": 0, "review": 1, "match": 2}
#: Two CGPAs this close are the same figure.
CGPA_TOLERANCE = 0.1
#: Two school percentages this close are the same figure.
PERCENT_TOLERANCE = 0.5

LABELS = {
    "form": "form", "cv": "CV", "aadhaar": "Aadhaar", "pan": "PAN",
    "marksheet_10": "10th marksheet", "marksheet_12": "12th marksheet", "transcript": "transcript",
}


def overall_verdict(matches: dict[str, dict], id_kinds: set[str]) -> dict:
    """The worst CV-vs-card comparison; without cards, the worst CV-vs-academic one."""
    cards = [m for key, m in matches.items() if key in id_kinds]
    pool = cards or [m for key, m in matches.items() if key in ("marksheet_10", "marksheet_12", "transcript")]
    if not pool:
        return compare(None, None).as_dict()
    return min(pool, key=lambda m: (_SEVERITY[m["verdict"]], m["score"]))


def _pairwise(name: str, values: dict[str, float | int | None], tolerance: float, unit: str = "") -> dict | None:
    """One check comparing every pair of sources that state the figure."""
    present = {source: float(value) for source, value in values.items() if value is not None}
    if len(present) < 2:
        return None
    disagreeing = [
        (a, b) for a, b in combinations(present, 2) if round(abs(present[a] - present[b]), 4) > tolerance
    ]
    detail = " vs ".join(f"{LABELS.get(s, s)} {v:g}{unit}" for s, v in present.items())
    if disagreeing:
        detail += " -- differ: " + ", ".join(f"{LABELS.get(a, a)}/{LABELS.get(b, b)}" for a, b in disagreeing)
    return {"name": name, "passed": not disagreeing, "detail": detail}


def figure_checks(form: dict, cv: dict, academic: dict[str, dict], id_cards: dict[str, dict]) -> list[dict]:
    """CGPA, school marks and years, DOB: each held across every source that has it."""
    checks: list[dict] = []
    school = cv.get("school") or {}

    checks.append(_pairwise("cgpa_consistent", {
        "form": form.get("cgpa"),
        "cv": cv.get("cgpa"),
        "transcript": (academic.get("transcript") or {}).get("cgpa"),
    }, CGPA_TOLERANCE))

    for stage, kind, key in (("tenth", "marksheet_10", "tenth"), ("twelfth", "marksheet_12", "twelfth")):
        claim = school.get(stage) or {}
        sheet = academic.get(kind) or {}
        checks.append(_pairwise(f"{stage}_marks_consistent", {
            "form": form.get(f"{key}_percentage"),
            "cv": claim.get("percentage"),
            kind: sheet.get("percentage"),
        }, PERCENT_TOLERANCE, "%"))
        checks.append(_pairwise(f"{stage}_cgpa_consistent", {
            "form": form.get(f"{key}_cgpa"),
            "cv": claim.get("cgpa"),
            kind: sheet.get("cgpa"),
        }, CGPA_TOLERANCE))
        checks.append(_pairwise(f"{stage}_year_consistent", {
            "form": form.get(f"{key}_year"),
            "cv": claim.get("year"),
            kind: sheet.get("year"),
        }, 0))

    years = [(kind, academic[kind]["year"]) for kind in ("marksheet_10", "marksheet_12", "transcript")
             if academic.get(kind) and academic[kind].get("year")]
    if len(years) >= 2:
        ordered = all(a[1] < b[1] for a, b in zip(years, years[1:]))
        checks.append({"name": "academic_years_in_order", "passed": ordered,
                       "detail": ", ".join(f"{LABELS[k]} {y}" for k, y in years)})

    dobs = {"form": form.get("date_of_birth"), "cv": cv.get("date_of_birth")}
    dobs.update({kind: record.get("dob") for kind, record in {**id_cards, **academic}.items()})
    known = {source: dob for source, dob in dobs.items() if dob}
    if len(known) >= 2:
        checks.append({"name": "dob_consistent", "passed": len(set(known.values())) == 1,
                       "detail": " vs ".join(f"{LABELS.get(s, s)} {d}" for s, d in known.items())})
    return [check for check in checks if check is not None]


def form_checks(form: dict, cv: dict, id_cards: dict[str, dict], matches: dict[str, dict]) -> list[dict]:
    """The form's name, email and phone against the CV and the cards."""
    checks: list[dict] = []
    for key, match in matches.items():
        if key.startswith("form_vs_"):
            checks.append({"name": f"{key}_name_match", "passed": match["verdict"] == "match",
                           "detail": f"{match['verdict']} at {match['score']:.0f} ({match['method']})"})
    if form.get("email") and cv.get("emails"):
        on_cv = form["email"].strip().lower() in [e.lower() for e in cv["emails"]]
        checks.append({"name": "form_email_on_cv", "passed": on_cv,
                       "detail": "The form's email is on the CV" if on_cv else "The form's email is not among the CV's"})
    if form.get("phone") and cv.get("phones"):
        wanted = find_phones(form["phone"]) or [form["phone"]]
        on_cv = any(p in cv["phones"] for p in wanted)
        checks.append({"name": "form_phone_on_cv", "passed": on_cv,
                       "detail": "The form's phone is on the CV" if on_cv else "The form's phone is not among the CV's"})
    return checks


def checks_for(
    cv: dict, id_cards: dict[str, dict], academic: dict[str, dict], matches: dict[str, dict], form: dict
) -> list[dict]:
    checks = [
        {"name": "cv_name_found", "passed": bool(cv.get("full_name")),
         "detail": "The CV reading has a name" if cv.get("full_name") else "No name was read off the CV"},
    ]
    for kind, record in {**id_cards, **academic}.items():
        detail = f"Sides read: {', '.join(record.get('sides') or [])}" if kind in id_cards else \
            f"Read from {record.get('text_source', 'text')}" + (f" via {record['ocr_engine']}" if record.get("ocr_engine") else "")
        checks.append({"name": f"{kind}_name_found", "passed": bool(record.get("full_name")), "detail": detail})
        match = matches.get(kind)
        if match:
            checks.append({"name": f"{kind}_name_match", "passed": match["verdict"] == "match",
                           "detail": f"{match['verdict']} at {match['score']:.0f} ({match['method']})"})
        for check, passed in (record.get("checks") or {}).items():
            name = check if kind in id_cards else f"{kind}_{check}"
            checks.append({"name": name, "passed": bool(passed), "detail": None})
    if "aadhaar_vs_pan" in matches:
        match = matches["aadhaar_vs_pan"]
        checks.append({"name": "aadhaar_vs_pan_name_match", "passed": match["verdict"] == "match",
                       "detail": f"{match['verdict']} at {match['score']:.0f} ({match['method']})"})

    checks.extend(form_checks(form, cv, id_cards, matches))
    checks.extend(figure_checks(form, cv, academic, id_cards))
    return checks


def verify_documents(
    session: Session,
    subject: Subject,
    cv_document: Document,
    cv: dict,
    id_documents: list[Document],
    id_cards: dict[str, dict],
    academic: dict[str, dict] | None = None,
    form: dict | None = None,
) -> Verification:
    academic = academic or {}
    form = {k: v for k, v in (form or {}).items() if v not in (None, "")}
    if not id_cards and not academic:
        raise ValueError("At least one ID card or academic document is needed.")

    matches: dict[str, dict] = {
        kind: compare(cv.get("full_name"), record.get("full_name")).as_dict()
        for kind, record in {**id_cards, **academic}.items()
    }
    if "aadhaar" in id_cards and "pan" in id_cards:
        matches["aadhaar_vs_pan"] = compare(
            id_cards["aadhaar"].get("full_name"), id_cards["pan"].get("full_name")
        ).as_dict()
    if form.get("full_name"):
        matches["form_vs_cv"] = compare(form["full_name"], cv.get("full_name")).as_dict()
        for kind, record in id_cards.items():
            matches[f"form_vs_{kind}"] = compare(form["full_name"], record.get("full_name")).as_dict()

    verdict = overall_verdict(matches, set(id_cards))
    checks = checks_for(cv, id_cards, academic, matches, form)

    payload = {
        "subject_id": subject.id,
        "subject_type": subject.type,
        "external_ref": subject.external_ref,
        "cv_document_id": cv_document.id,
        "documents": [
            {"document_id": d.id, "kind": d.kind, "side": d.side, "filename": d.filename}
            for d in [cv_document, *id_documents]
        ],
        "name_match": verdict,
        "name_matches": matches,
        "checks": checks,
        "cv": cv,
        "id_cards": id_cards,
        "academic": academic,
        "form": form or None,
    }
    verification = Verification(
        subject_id=subject.id,
        cv_document_id=cv_document.id,
        id_document_ids=[d.id for d in id_documents],
        name_score=verdict["score"],
        verdict=verdict["verdict"],
        checks_passed=sum(1 for check in checks if check["passed"]),
        payload=payload,
    )
    session.add(verification)
    session.flush()
    payload["verification_id"] = verification.id
    return verification
