"""Structured extraction through a local Ollama model. See `resume.py`."""

from app.llm.client import LLMClient, LLMUnavailable, get_client, llm_enabled
from app.llm.prompts import JOB_SYSTEM_PROMPT, MAX_INPUT_CHARS, RESUME_SYSTEM_PROMPT
from app.llm.resume import (
    JobFacts,
    ResumeFacts,
    clear_jd_cache,
    experience_months,
    parse_job_description,
    parse_month,
    parse_resume_facts,
)
from app.llm.schema import _clamp_level  # exercised directly by the tests

__all__ = [
    "JOB_SYSTEM_PROMPT",
    "JobFacts",
    "LLMClient",
    "LLMUnavailable",
    "MAX_INPUT_CHARS",
    "RESUME_SYSTEM_PROMPT",
    "ResumeFacts",
    "_clamp_level",
    "clear_jd_cache",
    "experience_months",
    "get_client",
    "llm_enabled",
    "parse_job_description",
    "parse_month",
    "parse_resume_facts",
]
