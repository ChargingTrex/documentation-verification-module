"""
Does the name on the CV match the name on the ID card?

Names are normalised (accents off, upper case, honorifics and punctuation
out) and compared with rapidfuzz's token-set ratio, which ignores word
order ("Mehta Aarav" is "Aarav Mehta") and treats a missing middle name as
a subset, not a difference. An initial can never confirm a full name --
"A. Mehta" might be anyone -- so a name carrying initials is capped at the
review band however well the letters line up.

Verdicts: `match` at or above NAME_MATCH_THRESHOLD, `review` at or above
NAME_REVIEW_THRESHOLD, else `mismatch`. A human decides the review band.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass

from app.config import settings

HONORIFICS = {
    "MR", "MRS", "MS", "MISS", "MX", "DR", "PROF", "ER", "ADV",
    "SHRI", "SMT", "SRI", "KUMARI", "KUM", "SELVI", "THIRU", "THIRUMATHI", "JANAB",
}


def normalise(name: str | None) -> str:
    if not name:
        return ""
    text = unicodedata.normalize("NFKD", name)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^A-Za-z]+", " ", text).upper()
    tokens = [token for token in text.split() if token not in HONORIFICS]
    return " ".join(tokens)


def has_initials(normalised: str) -> bool:
    return any(len(token) == 1 for token in normalised.split())


@dataclass
class NameMatch:
    cv: str | None
    id: str | None
    cv_normalised: str | None
    id_normalised: str | None
    score: float
    verdict: str
    method: str

    def as_dict(self) -> dict:
        return asdict(self)


def verdict_for(score: float) -> str:
    if score >= settings.name_match_threshold:
        return "match"
    if score >= settings.name_review_threshold:
        return "review"
    return "mismatch"


def compare(cv_name: str | None, id_name: str | None) -> NameMatch:
    a, b = normalise(cv_name), normalise(id_name)
    if not a or not b:
        return NameMatch(cv_name, id_name, a or None, b or None, 0.0, "mismatch", "missing")

    if a == b:
        return NameMatch(cv_name, id_name, a, b, 100.0, "match", "exact")

    from rapidfuzz import fuzz

    score = float(round(fuzz.token_set_ratio(a, b), 1))
    method = "token_set"
    if has_initials(a) or has_initials(b):
        cap = float(settings.name_match_threshold - 1)
        if score > cap:
            score, method = cap, "initials_capped"
    return NameMatch(cv_name, id_name, a, b, score, verdict_for(score), method)
