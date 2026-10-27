from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env", override=False)

VALID_LLM_PROVIDERS = ("ollama", "openai", "none")


class ConfigError(RuntimeError):
    """Raised when the environment configuration is invalid."""


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


@dataclass(frozen=True)
class Settings:
    llm_provider: str = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = ""
    openai_base_url: str = ""
    openai_api_key: str = ""
    openai_model: str = ""
    llm_timeout_seconds: float = 60.0
    llm_temperature: float = 0.1
    agent_max_tool_rounds: int = 6
    railway_db_path: Path = BASE_DIR / "data" / "railways.db"
    max_message_chars: int = 2000
    max_sessions: int = 500
    history_limit: int = 24

    @property
    def llm_model(self) -> str:
        return self.openai_model if self.llm_provider == "openai" else self.ollama_model

    @property
    def llm_base_url(self) -> str:
        return self.openai_base_url if self.llm_provider == "openai" else self.ollama_base_url


def load_settings() -> Settings:
    provider = (_env("LLM_PROVIDER", "ollama") or "ollama").lower()
    if provider not in VALID_LLM_PROVIDERS:
        raise ConfigError(
            f"LLM_PROVIDER must be one of {', '.join(VALID_LLM_PROVIDERS)}; got {provider!r}"
        )

    db_raw = _env("RAILWAY_DB_PATH", "data/railways.db")
    db_path = Path(db_raw).expanduser()
    if not db_path.is_absolute():
        db_path = (BASE_DIR / db_path).resolve()

    return Settings(
        llm_provider=provider,
        ollama_base_url=_env("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/"),
        ollama_model=_env("OLLAMA_MODEL"),
        openai_base_url=_env("OPENAI_BASE_URL").rstrip("/"),
        openai_api_key=_env("OPENAI_API_KEY"),
        openai_model=_env("OPENAI_MODEL"),
        llm_timeout_seconds=_env_float("LLM_TIMEOUT_SECONDS", 60.0),
        llm_temperature=_env_float("LLM_TEMPERATURE", 0.1),
        agent_max_tool_rounds=_env_int("AGENT_MAX_TOOL_ROUNDS", 6),
        railway_db_path=db_path,
        max_message_chars=_env_int("MAX_MESSAGE_CHARS", 2000),
        max_sessions=_env_int("MAX_SESSIONS", 500),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()


def reset_settings_cache() -> None:
    """Test helper: forget cached settings after changing the environment."""
    get_settings.cache_clear()
