"""
Test doubles for the model server.

CI has no Ollama. `FakeLLMClient` stands in for `LLMClient`: chat replies
come from a queue (or a function of the prompt) and nothing opens a socket.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from app.llm import LLMClient, LLMUnavailable


class FakeLLMClient(LLMClient):
    """
    `replies` is a list of chat replies (dicts are JSON-encoded, strings sent
    as-is) consumed in order, or a callable `(system, user) -> reply`.
    `down=True` makes every call raise LLMUnavailable, like a stopped server.
    """

    def __init__(
        self,
        replies: list | Callable[[str, str], object] | None = None,
        *,
        down: bool = False,
        model: str = "fake-llama",
    ):
        super().__init__(base_url="http://fake", model=model, timeout=1)
        self._replies = replies if callable(replies) else list(replies or [])
        self.down = down
        self.prompts: list[tuple[str, str]] = []

    def chat_json(self, system: str, user: str) -> str:
        if self.down:
            raise LLMUnavailable("fake server is down")
        self.prompts.append((system, user))
        if callable(self._replies):
            reply = self._replies(system, user)
        elif self._replies:
            reply = self._replies.pop(0)
        else:
            raise AssertionError("FakeLLMClient ran out of replies")
        return reply if isinstance(reply, str) else json.dumps(reply)


def resume_reply(**overrides) -> dict:
    """A well-formed resume reply; override any key."""
    reply = {
        "full_name": "Aarav Mehta",
        "emails": ["aarav.mehta@college.edu"],
        "phones": [],
        "address": None,
        "age": None,
        "date_of_birth": None,
        "cgpa": None,
        "education": [
            {"degree": "B.Tech in Computer Engineering", "level": "UG", "field": "Computer Engineering",
             "institution": "Sai University", "start": "2022", "end": "2026", "cgpa": None}
        ],
        "experience": [],
        "skills": ["Python", "Django"],
        "projects": [],
        "certifications": [],
        "links": [],
    }
    reply.update(overrides)
    return reply


def job_reply(**overrides) -> dict:
    """A well-formed JD reply; override any key."""
    reply = {
        "title": "Backend Engineer",
        "canonical_role": "Backend Engineer",
        "required_skills": ["Python", "Django", "PostgreSQL"],
        "nice_to_have": ["Celery"],
        "min_experience_years": 2,
        "education_levels": ["UG"],
    }
    reply.update(overrides)
    return reply
