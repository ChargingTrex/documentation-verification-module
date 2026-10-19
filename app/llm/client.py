"""
A thin client for an OpenAI-compatible chat API.

The default target is a local Ollama (`/v1`, no key): nothing leaves the
machine. The same client speaks to any hosted provider that implements the
OpenAI chat API -- OpenAI, Groq, Together, OpenRouter, Mistral, Gemini's
OpenAI endpoint -- when `LLM_BASE_URL` points at it and `LLM_API_KEY` is set.
That is a privacy decision: the resume text is then sent to that provider.

When the server is down, or the reply never validates, `LLMUnavailable` is
raised and callers fall back to regex.
"""

from __future__ import annotations

import logging

from app.config import settings

logger = logging.getLogger(__name__)


class LLMUnavailable(Exception):
    """The model could not be reached, or never produced valid JSON."""


class LLMClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        timeout: float,
        api_key: str | None = None,
        json_mode: bool = True,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.api_key = api_key or None
        self.json_mode = json_mode

    @property
    def is_local(self) -> bool:
        """True for localhost / private-network targets: no key, no data leaving."""
        host = self.base_url.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]
        return host in ("localhost", "127.0.0.1", "0.0.0.0", "ollama", "host.docker.internal") or host.startswith(
            ("10.", "192.168.", "172.")
        )

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _post(self, path: str, payload: dict) -> dict:
        import httpx

        # A short connect timeout: a server that is down should cost an
        # upload two seconds, not the whole read budget.
        timeout = httpx.Timeout(self.timeout, connect=5.0)
        try:
            response = httpx.post(f"{self.base_url}{path}", json=payload, headers=self._headers(), timeout=timeout)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMUnavailable(f"LLM request to {path} failed: {exc}") from exc

    def chat_json(self, system: str, user: str) -> str:
        """The model's reply, asked for as a JSON object. Returned unparsed."""
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if self.json_mode:
            payload["response_format"] = {"type": "json_object"}
        body = self._post("/chat/completions", payload)
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
        api_key=settings.llm_api_key,
        json_mode=settings.llm_json_mode,
    )


def llm_info() -> dict:
    """What /health reports: enough to tell a local model from a hosted one, never the key."""
    if not settings.llm_enabled:
        return {"enabled": False, "model": None, "base_url": settings.llm_base_url, "mode": "off"}
    client = get_client()
    return {
        "enabled": True,
        "model": client.model,
        "base_url": client.base_url,
        "mode": "local" if client.is_local and not client.api_key else "hosted",
        "api_key_set": bool(client.api_key),
    }
