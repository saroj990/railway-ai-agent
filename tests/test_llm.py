from __future__ import annotations

import pytest

from app.config import ConfigError, Settings
from app.llm import build_llm
from app.llm.ollama import OllamaProvider
from app.llm.openai_compat import OpenAICompatibleProvider


def test_none_provider():
    assert build_llm(Settings(llm_provider="none")) is None


def test_ollama_requires_model():
    with pytest.raises(ConfigError, match="OLLAMA_MODEL"):
        build_llm(Settings(llm_provider="ollama", ollama_model=""))


def test_ollama_provider_built():
    provider = build_llm(
        Settings(llm_provider="ollama", ollama_model="llama3.1", ollama_base_url="http://localhost:11434")
    )
    assert isinstance(provider, OllamaProvider)
    assert provider.model == "llama3.1"


def test_openai_requires_endpoint_and_model():
    with pytest.raises(ConfigError, match="OPENAI_BASE_URL"):
        build_llm(Settings(llm_provider="openai"))


def test_openai_provider_built():
    provider = build_llm(
        Settings(
            llm_provider="openai",
            openai_base_url="http://localhost:8000/v1",
            openai_model="local-model",
            openai_api_key="test-key",
        )
    )
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.model == "local-model"
    assert provider.api_key == "test-key"


def test_ollama_message_conversion_round_trips_tool_calls():
    provider = OllamaProvider("http://localhost:11434", "llama3.1")
    converted = provider._convert_messages(
        [
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "c1", "name": "search_trains", "arguments": {"from_station": "A"}}
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "name": "search_trains", "content": "{}"},
        ]
    )
    assert converted[1]["tool_calls"][0]["function"]["name"] == "search_trains"
    assert converted[1]["tool_calls"][0]["function"]["arguments"] == {"from_station": "A"}
    assert converted[2]["tool_name"] == "search_trains"


def test_openai_message_conversion_serialises_arguments():
    provider = OpenAICompatibleProvider("http://localhost:8000/v1", "m")
    converted = provider._convert_messages(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "c1", "name": "search_trains", "arguments": {"a": 1}}],
            },
            {"role": "tool", "tool_call_id": "c1", "name": "search_trains", "content": "{}"},
        ]
    )
    assert converted[0]["tool_calls"][0]["function"]["arguments"] == '{"a": 1}'
    assert converted[1]["tool_call_id"] == "c1"
