"""LLM access for the NL counterfactual interface (spec addendum Phase 98).

The rest of `backend/nlq` sees only `LLMClient`: one structured call (translation, via forced tool use so the output is
JSON with a declared schema) and one free-text call (explanation, which the caller then verifies). No key means
`LLMUnavailableError`; there is never a silent fallback to a made-up answer.
"""

from __future__ import annotations

import os
from typing import Any, Callable, Dict, List, Optional, Protocol

DEFAULT_MODEL = "claude-sonnet-5"


class LLMUnavailableError(Exception):
    """No API key / client library, or the provider call failed."""


class LLMClient(Protocol):
    def structured(self, system: str, user: str, schema_name: str, schema: Dict[str, Any]) -> Dict[str, Any]: ...

    def text(self, system: str, user: str) -> str: ...


class AnthropicClient:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None, max_tokens: int = 1024) -> None:
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise LLMUnavailableError("ANTHROPIC_API_KEY is not set")
        try:
            import anthropic  # optional dependency (requirements-llm.txt)
        except ImportError as exc:
            raise LLMUnavailableError("the 'anthropic' package is not installed (pip install -r requirements-llm.txt)") from exc
        self._client = anthropic.Anthropic(api_key=key)
        self._model = model or os.environ.get("NETSCOPE_LLM_MODEL", DEFAULT_MODEL)
        self._max_tokens = max_tokens

    def structured(self, system: str, user: str, schema_name: str, schema: Dict[str, Any]) -> Dict[str, Any]:
        try:
            resp = self._client.messages.create(
                model=self._model, max_tokens=self._max_tokens, system=system,
                messages=[{"role": "user", "content": user}],
                tools=[{"name": schema_name, "description": "Return the structured result.", "input_schema": schema}],
                tool_choice={"type": "tool", "name": schema_name},
            )
        except Exception as exc:  # noqa: BLE001 - provider/network failure
            raise LLMUnavailableError(f"LLM call failed: {type(exc).__name__}: {exc}") from exc
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use":
                return dict(block.input)
        raise LLMUnavailableError("the model returned no structured result")

    def text(self, system: str, user: str) -> str:
        try:
            resp = self._client.messages.create(
                model=self._model, max_tokens=self._max_tokens, system=system,
                messages=[{"role": "user", "content": user}],
            )
        except Exception as exc:  # noqa: BLE001
            raise LLMUnavailableError(f"LLM call failed: {type(exc).__name__}: {exc}") from exc
        return "".join(getattr(b, "text", "") for b in resp.content)


class ScriptedLLM:
    """Deterministic stand-in for tests: replays queued answers (or calls a function) and records every prompt it saw."""

    def __init__(self, structured: Any = None, text: Any = None) -> None:
        self._structured, self._text = structured, text
        self.calls: List[Dict[str, str]] = []

    def _next(self, source: Any, *args: Any) -> Any:
        if callable(source):
            return source(*args)
        if isinstance(source, list):
            return source.pop(0)
        return source

    def structured(self, system: str, user: str, schema_name: str, schema: Dict[str, Any]) -> Dict[str, Any]:
        self.calls.append({"kind": "structured", "system": system, "user": user})
        out = self._next(self._structured, system, user)
        if isinstance(out, Exception):
            raise out
        return out

    def text(self, system: str, user: str) -> str:
        self.calls.append({"kind": "text", "system": system, "user": user})
        out = self._next(self._text, system, user)
        if isinstance(out, Exception):
            raise out
        return out


ClientFactory = Callable[[], LLMClient]
