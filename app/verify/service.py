"""
One CV + one ID card -> a verification record.

The name comparison is the verdict; everything else is a check the reviewer
sees alongside it (was a name found on each document, did the Aadhaar
number pass its checksum, do the dates of birth agree when both exist).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Document, Subject, Verification
from app.verify.names import compare


def checks_for(cv: dict, id_card: dict, name_match: dict) -> list[dict]:
    checks = [
        {"name": "cv_name_found", "passed": bool(cv.get("full_name")),
         "detail": "The CV reading has a name" if cv.get("full_name") else "No name was read off the CV"},
        {"name": "id_name_found", "passed": bool(id_card.get("full_name")),
         "detail": "The card reading has a name" if id_card.get("full_name") else "No name was read off the card"},
        {"name": "name_match", "passed": name_match["verdict"] == "match",
         "detail": f"{name_match['verdict']} at {name_match['score']:.0f} ({name_match['method']})"},
    ]
    for check, passed in (id_card.get("checks") or {}).items():
        checks.append({"name": check, "passed": bool(passed), "detail": None})
    if cv.get("date_of_birth") and id_card.get("dob"):
        same = cv["date_of_birth"] == id_card["dob"]
        checks.append({"name": "dob_consistent", "passed": same,
                       "detail": f"CV {cv['date_of_birth']} vs card {id_card['dob']}"})
    return checks


def verify_documents(
    session: Session,
    subject: Subject,
    cv_document: Document,
    cv: dict,
    id_document: Document,
    id_card: dict,
) -> Verification:
    name_match = compare(cv.get("full_name"), id_card.get("full_name")).as_dict()
    checks = checks_for(cv, id_card, name_match)
    payload = {
        "subject_id": subject.id,
        "subject_type": subject.type,
        "external_ref": subject.external_ref,
        "cv_document_id": cv_document.id,
        "id_document_id": id_document.id,
        "name_match": name_match,
        "checks": checks,
        "cv": cv,
        "id_card": id_card,
    }
    verification = Verification(
        subject_id=subject.id,
        cv_document_id=cv_document.id,
        id_document_id=id_document.id,
        name_score=name_match["score"],
        verdict=name_match["verdict"],
        checks_passed=sum(1 for check in checks if check["passed"]),
        payload=payload,
    )
    session.add(verification)
    session.flush()
    payload["verification_id"] = verification.id
    return verification
