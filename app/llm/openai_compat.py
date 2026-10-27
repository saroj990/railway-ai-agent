from __future__ import annotations

import json
import uuid
from typing import Any

import httpx

from app.llm.base import LLMError, LLMResponse, ToolCall


class OpenAICompatibleProvider:
    """Adapter for any endpoint that implements POST /chat/completions."""

    name = "openai"

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout: float = 60.0,
        temperature: float = 0.1,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.temperature = temperature

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMResponse:
        payload = {
            "model": self.model,
            "messages": self._convert_messages(messages),
            "temperature": self.temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions", json=payload, headers=headers
                )
        except httpx.ConnectError as exc:
            raise LLMError(
                f"Could not connect to the LLM endpoint at {self.base_url}.",
                hint="Check OPENAI_BASE_URL and that the server is running.",
            ) from exc
        except httpx.TimeoutException as exc:
            raise LLMError("The LLM endpoint did not respond in time.") from exc
        except httpx.HTTPError as exc:
            raise LLMError("The LLM request failed.", hint=str(exc)) from exc

        if response.status_code == 401:
            raise LLMError(
                "The LLM endpoint rejected the API key.",
                hint="Check OPENAI_API_KEY.",
            )
        if response.status_code >= 400:
            raise LLMError(
                f"The LLM endpoint returned HTTP {response.status_code}.",
                hint=response.text[:300],
            )

        try:
            body = response.json()
            message = body["choices"][0]["message"]
        except (ValueError, KeyError, IndexError) as exc:
            raise LLMError("The LLM endpoint returned a malformed response.") from exc

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
                        "tool_call_id": message.get("tool_call_id", ""),
                        "content": message.get("content", ""),
                    }
                )
            elif role == "assistant" and message.get("tool_calls"):
                converted.append(
                    {
                        "role": "assistant",
                        "content": message.get("content") or None,
                        "tool_calls": [
                            {
                                "id": call["id"],
                                "type": "function",
                                "function": {
                                    "name": call["name"],
                                    "arguments": json.dumps(call["arguments"]),
                                },
                            }
                            for call in message["tool_calls"]
                        ],
                    }
                )
            else:
                converted.append({"role": role, "content": message.get("content", "")})
        return converted

    async def health(self) -> dict[str, Any]:
        if not self.api_key:
            return {"status": "ok", "detail": "No API key configured (allowed for local endpoints)."}
        return {"status": "ok"}


def _as_arguments(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value if value is not None else {}
