from __future__ import annotations

from app.config import ConfigError, Settings
from app.llm.base import LLMError, LLMProvider, LLMResponse, ToolCall
from app.llm.ollama import OllamaProvider
from app.llm.openai_compat import OpenAICompatibleProvider

__all__ = [
    "ConfigError",
    "LLMError",
    "LLMProvider",
    "LLMResponse",
    "ToolCall",
    "OllamaProvider",
    "OpenAICompatibleProvider",
    "build_llm",
]


def build_llm(settings: Settings) -> LLMProvider | None:
    """Return the configured provider, or None for the deterministic router."""
    if settings.llm_provider == "none":
        return None

    if settings.llm_provider == "ollama":
        if not settings.ollama_model:
            raise ConfigError(
                "OLLAMA_MODEL is not set. Run `ollama list` and put an installed, "
                "tool-capable model name in .env (for example OLLAMA_MODEL=llama3.1)."
            )
        return OllamaProvider(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            timeout=settings.llm_timeout_seconds,
            temperature=settings.llm_temperature,
        )

    if settings.llm_provider == "openai":
        if not settings.openai_base_url or not settings.openai_model:
            raise ConfigError(
                "OPENAI_BASE_URL and OPENAI_MODEL must be set when LLM_PROVIDER=openai."
            )
        return OpenAICompatibleProvider(
            base_url=settings.openai_base_url,
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            timeout=settings.llm_timeout_seconds,
            temperature=settings.llm_temperature,
        )

    raise ConfigError(f"Unsupported LLM provider: {settings.llm_provider}")
