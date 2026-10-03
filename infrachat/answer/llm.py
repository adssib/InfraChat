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
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Protocol


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
        max_retries: int = 6,
        reasoning_effort: str | None = None,
        allow_empty: bool = False,
    ) -> None:
        self.base_url = base_url
        self.model = model
        self.api_key_env = api_key_env
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.max_retries = max_retries
        self.reasoning_effort = reasoning_effort
        self.allow_empty = allow_empty
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

            # max_retries: the SDK retries 429s with exponential backoff and honours
            # Retry-After. A full eval run is ~87 calls back to back, which exhausts a
            # free tier's tokens-per-minute budget partway through — and a rate-limited
            # question is recorded as an error, which invalidates the whole run for
            # comparison. Retrying is cheaper than re-running 87 questions.
            self._client = OpenAI(base_url=self.base_url, api_key=self._key(),
                                  timeout=self.timeout, max_retries=self.max_retries)
        return self._client

    def _messages(self, system: str, user: str) -> list[dict]:
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def _params(self) -> dict:
        return dict(
            model=self.model,
            temperature=0,          # reproducible runs — see module docstring
            max_tokens=self.max_tokens,
            # Reasoning models only. The generator leaves it unset; the Phase 4
            # rewriter sets "low" — measured 26 reasoning tokens and ~0.5s, against ~9s
            # at the default, for a task that needs recall, not deliberation.
            **({"reasoning_effort": self.reasoning_effort} if self.reasoning_effort else {}),
        )

    @contextmanager
    def _translated_errors(self):
        """Provider errors → one RuntimeError with the fix in it. Shared by both paths."""
        from openai import APIStatusError, APIConnectionError, RateLimitError

        try:
            yield
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

    def _checked(self, text: str, finish_reason: str | None, reasoning_chars: int) -> str:
        # A rewriter may legitimately have nothing to add and stop cleanly with empty
        # content; truncation (finish_reason='length') is a failure for every caller.
        if not text.strip() and self.allow_empty and finish_reason != "length":
            return ""
        if not text.strip():
            # Reasoning models spend `max_tokens` on hidden reasoning first; when the
            # budget runs out `content` is empty. Returning "" would sail into the
            # citation check and be recorded as a grounded refusal — an infrastructure
            # failure misreported as a correct decision, which quietly corrupts the
            # refusal metrics. Fail loudly instead.
            raise RuntimeError(
                f"{self.model} returned an empty completion "
                f"(finish_reason={finish_reason!r}, "
                f"reasoning={reasoning_chars} chars). "
                f"If finish_reason is 'length', raise llm.max_tokens — reasoning tokens "
                f"are spent from the same budget as the answer."
            )
        return text

    def complete(self, system: str, user: str) -> str:
        with self._translated_errors():
            response = self._get_client().chat.completions.create(
                messages=self._messages(system, user), **self._params()
            )
        choice = response.choices[0]
        reasoning = getattr(choice.message, "reasoning", None) or ""
        return self._checked(choice.message.content or "", choice.finish_reason, len(reasoning))

    def stream(
        self,
        system: str,
        user: str,
        *,
        on_token: Callable[[str], None] | None = None,
        on_reasoning: Callable[[str], None] | None = None,
    ) -> Streamed:
        """`complete()`, delivered piece by piece — for the UI, never for the eval.

        Returns the **whole** completion, checked exactly as `complete()` checks it, so
        the citation gate downstream sees the same text either way. The callbacks only
        let a caller *show* the pieces as they arrive; nothing is decided on them.

        `on_reasoning` asks the provider for the model's reasoning stream. Verified on
        Groq with gpt-oss-20b (docs/DEMO-PLAN.md § M3): it arrives in `delta.reasoning`,
        ahead of the first answer token. `include_reasoning` is a Groq parameter, so it is
        only sent when a caller wants reasoning.
        """
        extra = {"include_reasoning": True} if on_reasoning else {}
        content: list[str] = []
        reasoning_chars = 0
        finish_reason = None
        usage: dict = {}
        with self._translated_errors():
            raw = self._get_client().chat.completions.with_raw_response.create(
                messages=self._messages(system, user), stream=True,
                stream_options={"include_usage": True},
                **({"extra_body": extra} if extra else {}), **self._params(),
            )
            headers = raw.headers
            for chunk in raw.parse():
                if chunk.usage:
                    usage = chunk.usage.model_dump(exclude_none=True)
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                finish_reason = choice.finish_reason or finish_reason
                delta = choice.delta
                piece = (delta.model_extra or {}).get("reasoning")
                if piece:
                    reasoning_chars += len(piece)
                    if on_reasoning:
                        on_reasoning(piece)
                if delta.content:
                    content.append(delta.content)
                    if on_token:
                        on_token(delta.content)
        text = self._checked("".join(content), finish_reason, reasoning_chars)
        ratelimit = {k.lower().removeprefix("x-ratelimit-"): v for k, v in headers.items()
                     if k.lower().startswith("x-ratelimit-")}
        return Streamed(text=text, usage=usage, ratelimit=ratelimit)


@dataclass(frozen=True)
class Streamed:
    """What `stream()` returns: the checked text, plus what the provider reported."""

    text: str
    usage: dict             # prompt/completion tokens, as the provider reports them
    ratelimit: dict         # the x-ratelimit-* headers, prefix stripped (Groq: per-minute)


def build(cfg) -> LLMClient:
    """Construct the generator from an LLMConfig — the one place the adapter is named."""
    return OpenAICompatClient(
        base_url=cfg.base_url,
        model=cfg.model,
        api_key_env=cfg.api_key_env,
        max_tokens=cfg.max_tokens,
    )
