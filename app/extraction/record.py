"""
From an engine reading to the CV record the database stores.

`ExtractedProfile` carries what regex read, what the model read, and which
won for the two figures the engine arbitrates (experience years, education
levels). This module turns that into one flat record and, for every field,
says where the value came from -- `"llm"`, `"regex"` or `"none"` -- so the UI
can badge it and a reviewer knows what to trust.

Rules:
- Emails and phones are regex's: the patterns are exact and cannot be
  talked into anything. The model's lists only fill a gap.
- Name, address, education entries, experience entries, skills come from
  the model; regex can only supply the top-line name, an address
  (PIN-anchored) and a bare education level.
"""

from __future__ import annotations

from app.extraction.address import describe_address
from app.matching.engine import ExtractedProfile

LLM, REGEX, NONE = "llm", "regex", "none"


def cv_record(profile: ExtractedProfile) -> dict:
    regex = profile.regex_facts or {}
    facts = profile.facts or {}
    from_llm = profile.extraction_source == LLM
    sources: dict[str, str] = {}

    def pick_list(name: str) -> list:
        regex_value = list(regex.get(name) or [])
        if regex_value:
            sources[name] = REGEX
            return regex_value
        llm_value = [v for v in (facts.get(name) or []) if isinstance(v, str) and v.strip()]
        sources[name] = LLM if llm_value else NONE
        return llm_value

    emails = pick_list("emails")
    phones = pick_list("phones")

    full_name = (facts.get("full_name") or "").strip() or None
    if full_name:
        sources["full_name"] = LLM
    elif regex.get("full_name"):
        full_name = regex["full_name"]
        sources["full_name"] = REGEX
    else:
        sources["full_name"] = NONE

    if facts.get("address"):
        address = describe_address(facts["address"])
        sources["address"] = LLM
    elif regex.get("address"):
        address = regex["address"]
        sources["address"] = REGEX
    else:
        address = None
        sources["address"] = NONE

    if facts.get("education"):
        education = facts["education"]
        sources["education"] = LLM
    elif regex.get("education_levels"):
        education = [{"degree": None, "level": level} for level in regex["education_levels"]]
        sources["education"] = REGEX
    else:
        education = []
        sources["education"] = NONE

    experience = facts.get("experience") or []
    sources["experience"] = LLM if experience else NONE

    skills = facts.get("skills") or []
    sources["skills"] = LLM if skills else NONE

    # The engine's arbitration (see MatchingEngine.analyse_resume): the model's
    # date-derived total wins whenever it found dated work, even over a stated
    # claim -- a statement is the one thing a resume can make up freely; its
    # levels win when it found any.
    sources["experience_years"] = LLM if from_llm and facts.get("experience_months") else REGEX
    sources["education_levels"] = LLM if from_llm and facts.get("education_levels") else REGEX

    cgpa = regex.get("cgpa")
    sources["cgpa"] = REGEX if cgpa is not None else (LLM if facts.get("cgpa") is not None else NONE)
    if cgpa is None:
        cgpa = facts.get("cgpa")

    date_of_birth = regex.get("date_of_birth") or facts.get("date_of_birth")
    sources["date_of_birth"] = (
        REGEX if regex.get("date_of_birth") else (LLM if facts.get("date_of_birth") else NONE)
    )

    return {
        "full_name": full_name,
        "emails": emails,
        "phones": phones,
        "address": address,
        "education": education,
        "experience": experience,
        "experience_years": profile.experience_years,
        "education_levels": sorted(profile.education_levels),
        "highest_education_level": profile.highest_education_level,
        "skills": skills,
        "cgpa": cgpa,
        "date_of_birth": date_of_birth,
        "extraction_source": profile.extraction_source,
        "llm_model": profile.llm_model,
        "field_sources": sources,
        "regex_facts": regex,
        "agreement": profile.agreement,
        "text_length": len(profile.raw_text),
    }
