"""
The candidate's name off the top of a resume, without a model.

Resumes put the name first: the first line (or the first after a "RESUME"
banner) that reads as two to five name-like tokens, or one token with an
initial ("R.Karthik"). It is a fallback for when the LLM is off, and the
record marks it `regex`; the model's reading wins when there is one.
"""

from __future__ import annotations

import re

_LINES_TO_TRY = 8
_TOKEN = r"[A-Za-z][A-Za-z.'\-]*"
_NAME = re.compile(rf"^{_TOKEN}(?:\s+{_TOKEN}){{0,4}}$")
_NOT_A_NAME = re.compile(
    r"\b(?:resume|curriculum|vitae|cv|profile|bio-?data|summary|objective|contact|portfolio|"
    r"address|email|phone|mobile|linkedin|github|education|experience|skills|projects|"
    r"certifications?|achievements?|languages?|hobbies|interests|references?|"
    r"engineer|developer|student|analyst|manager|intern|fresher|b\.?tech|m\.?tech|mba|bsc|msc)\b",
    re.IGNORECASE,
)


def find_name(text: str) -> str | None:
    lines = [line.strip() for line in (text or "").split("\n") if line.strip()]
    for line in lines[:_LINES_TO_TRY]:
        if len(line) > 60 or not _NAME.match(line) or _NOT_A_NAME.search(line):
            continue
        tokens = line.split()
        # One bare word is a heading ("SKILLS"), not a person; one word with
        # an initial ("R.Karthik") is.
        if len(tokens) == 1 and "." not in line:
            continue
        if all(len(token.strip(".")) <= 1 for token in tokens):
            continue
        return line
    return None
