from __future__ import annotations

import json
import uuid
from typing import Any

import httpx

from app.llm.base import LLMError, LLMResponse, ToolCall


def _as_arguments(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value if value is not None else {}


class OllamaProvider:
    name = "ollama"

    def __init__(self, base_url: str, model: str, timeout: float = 60.0, temperature: float = 0.1):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.temperature = temperature

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMResponse:
        payload = {
            "model": self.model,
            "messages": self._convert_messages(messages),
            "stream": False,
            "options": {"temperature": self.temperature},
        }
        if tools:
            payload["tools"] = tools

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(f"{self.base_url}/api/chat", json=payload)
        except httpx.ConnectError as exc:
            raise LLMError(
                f"Could not connect to Ollama at {self.base_url}.",
                hint="Start it with `ollama serve`, or set LLM_PROVIDER=none for offline mode.",
            ) from exc
        except httpx.TimeoutException as exc:
            raise LLMError(
                "Ollama did not respond in time.",
                hint="The model may still be loading. Try again, or use a smaller model.",
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMError("Ollama request failed.", hint=str(exc)) from exc

        if response.status_code == 404:
            raise LLMError(
                f"Ollama model '{self.model}' was not found.",
                hint=f"Run `ollama pull {self.model}` or set OLLAMA_MODEL to an installed model.",
            )
        if response.status_code >= 400:
            raise LLMError(
                f"Ollama returned HTTP {response.status_code}.",
                hint=_safe_body(response),
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise LLMError("Ollama returned a malformed response.") from exc

        message = body.get("message") or {}
        tool_calls = [
            ToolCall(
                id=call.get("id") or f"call_{uuid.uuid4().hex[:8]}",
                name=(call.get("function") or {}).get("name", ""),
                arguments=_as_arguments((call.get("function") or {}).get("arguments")),
            )
            for call in (message.get("tool_calls") or [])
            if (call.get("function") or {}).get("name")
        ]
        return LLMResponse(content=message.get("content") or "", tool_calls=tool_calls)

    def _convert_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        converted: list[dict[str, Any]] = []
        for message in messages:
            role = message["role"]
            if role == "tool":
                converted.append(
                    {
                        "role": "tool",
                        "content": message.get("content", ""),
                        "tool_name": message.get("name", ""),
                    }
                )
            elif role == "assistant" and message.get("tool_calls"):
                converted.append(
                    {
                        "role": "assistant",
                        "content": message.get("content", ""),
                        "tool_calls": [
                            {
                                "function": {
                                    "name": call["name"],
                                    "arguments": call["arguments"],
                                }
                            }
                            for call in message["tool_calls"]
                        ],
                    }
                )
            else:
                converted.append({"role": role, "content": message.get("content", "")})
        return converted

    async def health(self) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.base_url}/api/tags")
            if response.status_code >= 400:
                return {"status": "error", "detail": f"HTTP {response.status_code}"}
            models = [m.get("name", "") for m in response.json().get("models", [])]
        except httpx.HTTPError as exc:
            return {"status": "unreachable", "detail": str(exc)}
        installed = any(m == self.model or m.split(":")[0] == self.model.split(":")[0] for m in models)
        return {
            "status": "ok" if installed else "model_missing",
            "model": self.model,
            "installed_models": models[:20],
        }


def _safe_body(response: httpx.Response) -> str:
    try:
        text = response.text
    except Exception:  # pragma: no cover - defensive
        return ""
    return text[:300]
