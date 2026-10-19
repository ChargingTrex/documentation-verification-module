"""
One CV + the ID cards given -> a verification record.

A subject may hand in an Aadhaar (front, back, or both sides), a PAN, or
both cards. The CV name is compared with every card; when both cards are
present they are compared with each other too. The overall verdict is the
worst of the CV-vs-card comparisons: one card that does not match is a
problem however well the other does. Everything else is a check the
reviewer sees alongside the verdict.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Document, Subject, Verification
from app.verify.names import compare

_SEVERITY = {"mismatch": 0, "review": 1, "match": 2}


def overall_verdict(matches: dict[str, dict]) -> dict:
    """The worst CV-vs-card comparison, or a 'missing' result with no cards."""
    cv_matches = [m for key, m in matches.items() if key != "aadhaar_vs_pan"]
    if not cv_matches:
        return compare(None, None).as_dict()
    return min(cv_matches, key=lambda m: (_SEVERITY[m["verdict"]], m["score"]))


def checks_for(cv: dict, id_cards: dict[str, dict], matches: dict[str, dict]) -> list[dict]:
    checks = [
        {"name": "cv_name_found", "passed": bool(cv.get("full_name")),
         "detail": "The CV reading has a name" if cv.get("full_name") else "No name was read off the CV"},
    ]
    for kind, card in id_cards.items():
        checks.append({"name": f"{kind}_name_found", "passed": bool(card.get("full_name")),
                       "detail": f"Sides read: {', '.join(card.get('sides') or []) or 'unknown'}"})
        match = matches.get(kind)
        if match:
            checks.append({"name": f"{kind}_name_match", "passed": match["verdict"] == "match",
                           "detail": f"{match['verdict']} at {match['score']:.0f} ({match['method']})"})
        for check, passed in (card.get("checks") or {}).items():
            checks.append({"name": check, "passed": bool(passed), "detail": None})
    if "aadhaar_vs_pan" in matches:
        match = matches["aadhaar_vs_pan"]
        checks.append({"name": "aadhaar_vs_pan_name_match", "passed": match["verdict"] == "match",
                       "detail": f"{match['verdict']} at {match['score']:.0f} ({match['method']})"})

    dobs = {"cv": cv.get("date_of_birth")}
    dobs.update({kind: card.get("dob") for kind, card in id_cards.items()})
    known = {source: dob for source, dob in dobs.items() if dob}
    if len(known) >= 2:
        same = len(set(known.values())) == 1
        checks.append({"name": "dob_consistent", "passed": same,
                       "detail": " vs ".join(f"{source} {dob}" for source, dob in known.items())})
    return checks


def verify_documents(
    session: Session,
    subject: Subject,
    cv_document: Document,
    cv: dict,
    id_documents: list[Document],
    id_cards: dict[str, dict],
) -> Verification:
    if not id_cards:
        raise ValueError("At least one ID card is needed.")

    matches: dict[str, dict] = {
        kind: compare(cv.get("full_name"), card.get("full_name")).as_dict() for kind, card in id_cards.items()
    }
    if "aadhaar" in id_cards and "pan" in id_cards:
        matches["aadhaar_vs_pan"] = compare(
            id_cards["aadhaar"].get("full_name"), id_cards["pan"].get("full_name")
        ).as_dict()
    verdict = overall_verdict(matches)
    checks = checks_for(cv, id_cards, matches)

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
