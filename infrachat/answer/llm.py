"""The LLMClient seam — one OpenAI-compatible adapter covering every provider we'd use.

Groq, OpenAI, Together, OpenRouter and a local Ollama server all expose the same wire
format, so switching provider is `base_url` + `model` in config — no code change. That is
the whole reason the seam is shaped this way (docs/SPEC.md § LLM calling).

**`temperature=0` is not a style preference.** docs/EVAL.md requires runs to be
reproducible and comparable across configurations; a sampling temperature above zero
means the same question can produce a grounded answer on one run and a refusal on the
next, and the measured delta between phases would include that noise.
"""

from __future__ import annotations

import os
from typing import Protocol


class LLMClient(Protocol):
    """(system prompt, user prompt) → completion text."""

    def complete(self, system: str, user: str) -> str: ...


class MissingAPIKey(RuntimeError):
    """The configured env var is unset — raised with the command to fix it."""


class OpenAICompatClient:
    """Any OpenAI-compatible chat-completions endpoint.

    The key is read from the environment **at call time**, never stored on the object, so
    it cannot leak into a repr, a traceback frame, or a logged config dump.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key_env: str,
        *,
        max_tokens: int = 4096,
        timeout: float = 60.0,
    ) -> None:
        self.base_url = base_url
        self.model = model
        self.api_key_env = api_key_env
        self.max_tokens = max_tokens
        self.timeout = timeout
        self._client = None

    def _key(self) -> str:
        key = os.environ.get(self.api_key_env)
        if not key:
            raise MissingAPIKey(
                f"${self.api_key_env} is not set. Export your key:\n"
                f"    export {self.api_key_env}='...'\n"
                f"(configured provider: {self.base_url})"
            )
        return key

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI  # imported lazily: `ingest` must not need it

            self._client = OpenAI(base_url=self.base_url, api_key=self._key(),
                                  timeout=self.timeout)
        return self._client

    def complete(self, system: str, user: str) -> str:
        from openai import APIStatusError, APIConnectionError, RateLimitError

        try:
            response = self._get_client().chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0,          # reproducible runs — see module docstring
                max_tokens=self.max_tokens,
            )
        except RateLimitError as e:
            raise RuntimeError(
                f"rate limited by {self.base_url} — free tiers cap requests per minute. "
                f"Wait and retry, or switch provider in config.yaml.\n  {e}"
            ) from e
        except APIConnectionError as e:
            raise RuntimeError(f"cannot reach {self.base_url}: {e}") from e
        except APIStatusError as e:
            hint = ""
            if e.status_code == 401:
                hint = f"  → check ${self.api_key_env} is a valid key for {self.base_url}"
            elif e.status_code == 404:
                hint = f"  → model {self.model!r} may not exist on this provider"
            raise RuntimeError(f"{self.base_url} returned {e.status_code}: {e.message}\n{hint}") from e

        choice = response.choices[0]
        text = choice.message.content or ""
        if not text.strip():
            # Reasoning models spend `max_tokens` on hidden reasoning first; when the
            # budget runs out `content` is empty. Returning "" would sail into the
            # citation check and be recorded as a grounded refusal — an infrastructure
            # failure misreported as a correct decision, which quietly corrupts the
            # refusal metrics. Fail loudly instead.
            reasoning = getattr(choice.message, "reasoning", None) or ""
            raise RuntimeError(
                f"{self.model} returned an empty completion "
                f"(finish_reason={choice.finish_reason!r}, "
                f"reasoning={len(reasoning)} chars). "
                f"If finish_reason is 'length', raise llm.max_tokens — reasoning tokens "
                f"are spent from the same budget as the answer."
            )
        return text


def build(cfg) -> LLMClient:
    """Construct the generator from an LLMConfig — the one place the adapter is named."""
    return OpenAICompatClient(
        base_url=cfg.base_url,
        model=cfg.model,
        api_key_env=cfg.api_key_env,
        max_tokens=cfg.max_tokens,
    )
