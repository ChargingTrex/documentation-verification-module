"""
A postal address out of resume text, without a model.

Indian resumes put the address near the top, either labelled ("Address: ...")
or as a line or two ending in a six-digit PIN code. This reads both shapes.
It is the fallback for when the LLM is off; the model's own reading is
preferred when present, and `describe_address` structures either one.
"""

from __future__ import annotations

import re

STATES = (
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat",
    "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh",
    "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab", "Rajasthan",
    "Sikkim", "Tamil Nadu", "Tamilnadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand",
    "West Bengal", "Andaman and Nicobar Islands", "Chandigarh", "Dadra and Nagar Haveli",
    "Daman and Diu", "Delhi", "New Delhi", "Jammu and Kashmir", "Ladakh", "Lakshadweep",
    "Puducherry", "Pondicherry",
)

_STATE = re.compile(
    r"\b(" + "|".join(re.escape(s) for s in sorted(STATES, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)
# Six digits, first non-zero, not part of a longer number or a phone.
_PIN = re.compile(r"(?<![\d\-+])([1-9]\d{5})(?![\d\-])")
_LABEL = re.compile(
    r"^\s*(?:permanent\s+|current\s+|present\s+|postal\s+|residential\s+|home\s+)?"
    r"address\s*[:\-–]?\s*",
    re.IGNORECASE,
)
# Words that make a line read as an address, used to pull in the lines above a PIN.
_CUE = re.compile(
    r"\b(?:street|st\.|road|rd\.?|nagar|lane|colony|apartment|apt\.?|flat|house|sector|phase|"
    r"block|near|opp(?:osite)?\.?|district|dist\.?|taluk|village|post|p\.?o\.?|layout|cross|"
    r"main|extension|extn\.?|town|city|pin(?:\s*code)?|door|plot|floor|tower|villa|chawl|"
    r"gali|marg|chowk|bazaar|peth|wadi|puram|palayam|halli|pur|garh|ganj)\b"
    r"|\d+\s*/\s*\d+|#\s?\d+|\bno\.?\s*\d+",
    re.IGNORECASE,
)
# Lines an address never contains: emails, URLs, phone numbers.
_NOISE = re.compile(
    r"@|https?://|www\.|linkedin|github|(?<![\d])(?:\+?91[\s\-]?|0)?[6-9]\d{4}[\s\-]?\d{5}(?!\d)",
    re.IGNORECASE,
)
_HEADER = re.compile(
    r"^\s*(?:education|experience|work experience|skills|projects|objective|summary|profile|"
    r"certifications|achievements|languages|hobbies|interests|references)\s*:?\s*$",
    re.IGNORECASE,
)


def describe_address(raw: str) -> dict:
    """Structure an address string: the raw text, its PIN code and its state."""
    raw = " ".join((raw or "").replace("\n", ", ").split()).strip(" ,")
    pin = _PIN.search(raw)
    state = _STATE.search(raw)
    canonical = None
    if state:
        word = state.group(1).lower()
        canonical = {"tamilnadu": "Tamil Nadu", "pondicherry": "Puducherry", "new delhi": "Delhi"}.get(
            word, state.group(1).title()
        )
    return {
        "raw": raw,
        "pincode": pin.group(1) if pin else None,
        "state": canonical,
    }


def find_address(text: str) -> dict | None:
    """The address a resume states, or None. Labelled first, then PIN-anchored."""
    lines = [line.strip() for line in (text or "").split("\n")]

    for index, line in enumerate(lines):
        if _LABEL.match(line):
            body = _LABEL.sub("", line, count=1).strip()
            chunk = [body] if body else []
            if not body or not _PIN.search(body):
                for following in lines[index + 1 : index + 4]:
                    if not following or _NOISE.search(following) or _HEADER.match(following):
                        break
                    chunk.append(following)
                    if _PIN.search(following):
                        break
            raw = ", ".join(part for part in chunk if part)
            if raw:
                return describe_address(raw)

    for index, line in enumerate(lines):
        if not _PIN.search(line) or _NOISE.search(line):
            continue
        if not (_CUE.search(line) or _STATE.search(line) or "," in line):
            continue
        chunk = [line]
        for previous in reversed(lines[max(0, index - 2) : index]):
            if previous and not _NOISE.search(previous) and not _HEADER.match(previous) and (
                _CUE.search(previous) or "," in previous
            ):
                chunk.insert(0, previous)
            else:
                break
        return describe_address(", ".join(chunk))

    return None
