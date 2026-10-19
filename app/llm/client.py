"""
A thin client for the OpenAI-compatible chat API a local Ollama serves at `/v1`.

The same client works against Ollama on a laptop and a private server. No
third-party API ever receives a document: resumes and ID cards stay on
machines the organisation controls. When the server is down, or the reply
never validates, `LLMUnavailable` is raised and callers fall back to regex.
"""

from __future__ import annotations

import logging

from app.config import settings

logger = logging.getLogger(__name__)


class LLMUnavailable(Exception):
    """The model could not be reached, or never produced valid JSON."""


class LLMClient:
    def __init__(self, base_url: str, model: str, timeout: float):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def _post(self, path: str, payload: dict) -> dict:
        import httpx

        # A short connect timeout: a server that is down should cost an
        # upload two seconds, not the whole read budget.
        timeout = httpx.Timeout(self.timeout, connect=2.0)
        try:
            response = httpx.post(f"{self.base_url}{path}", json=payload, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMUnavailable(f"LLM request to {path} failed: {exc}") from exc

    def chat_json(self, system: str, user: str) -> str:
        """The model's reply, asked for as a JSON object. Returned unparsed."""
        body = self._post(
            "/chat/completions",
            {
                "model": self.model,
                "temperature": 0,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        )
        try:
            return body["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMUnavailable(f"Unexpected chat response shape: {body!r:.200}") from exc


def llm_enabled() -> bool:
    return bool(settings.llm_enabled)


def get_client() -> LLMClient:
    """A client built from settings. Raises LLMUnavailable when disabled."""
    if not settings.llm_enabled:
        raise LLMUnavailable("The LLM is disabled (LLM_ENABLED is false).")
    return LLMClient(
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        timeout=settings.llm_timeout_seconds,
    )
