"""Provider configuration and dotenv loading. Secret values are never returned or logged."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

OPENROUTER_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1"
LOCAL_PROVIDER_ALIASES = {"local", "lm-studio", "lm_studio", "lmstudio"}
MAX_ATTEMPT_CAP = 5


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def parse_env_text(text: str) -> dict[str, str]:
    """Parse dotenv content into a mapping. Later duplicate keys win."""
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            values[key] = value[1:-1]
        else:
            values[key] = value.split(" #", 1)[0].rstrip()
    return values


def load_env_file(path: str | Path) -> int:
    """Apply KEY=VALUE pairs from a dotenv file, never overriding a variable already set.

    Returns how many variables were applied. A missing file is not an error.
    """
    env_path = Path(path)
    if not env_path.is_file():
        return 0
    applied = 0
    for key, value in parse_env_text(env_path.read_text(encoding="utf-8")).items():
        if key in os.environ:
            continue
        os.environ[key] = value
        applied += 1
    return applied


def load_project_env(root: str | Path | None = None) -> int:
    """Load the project-root `.env` file if one exists."""
    return load_env_file((Path(root) if root else project_root()) / ".env")


def is_local_provider(provider: str) -> bool:
    return (provider or "").strip().casefold() in LOCAL_PROVIDER_ALIASES


def _positive_float(name: str, default: float) -> float:
    raw = os.getenv(name, "")
    if not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be numeric.") from error
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero.")
    return value


def _attempts(name: str, default: int) -> int:
    raw = os.getenv(name, "")
    if not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be a whole number.") from error
    return max(1, min(value, MAX_ATTEMPT_CAP))


@dataclass(frozen=True)
class LLMSettings:
    """Resolved provider settings for one process. `api_key` must never be rendered."""
    provider: str
    base_url: str
    model: str
    api_key: str
    timeout_seconds: float
    temperature: float
    max_attempts: int
    referer: str | None = None
    application: str | None = None

    @property
    def is_local(self) -> bool:
        return is_local_provider(self.provider)

    @property
    def is_openrouter(self) -> bool:
        return self.provider.strip().casefold() == "openrouter"

    def describe(self) -> dict[str, object]:
        """Secret-free view safe for logs, traces, and API responses."""
        return {"provider": self.provider, "model": self.model,
                "base_url": self.base_url, "api_key_configured": bool(self.api_key),
                "timeout_seconds": self.timeout_seconds, "temperature": self.temperature,
                "max_attempts": self.max_attempts, "local": self.is_local}


class LLMConfigurationError(ValueError):
    """Required server-side LLM settings are absent or invalid."""


def resolve_llm_settings() -> LLMSettings:
    """Resolve provider settings from the environment.

    `LLM_PROVIDER=openrouter` selects the OpenRouter variable names; every other
    provider keeps the existing `LLM_*` names so local and generic OpenAI-compatible
    setups are unaffected.
    """
    provider = os.getenv("LLM_PROVIDER", "openai-compatible")
    openrouter = provider.strip().casefold() == "openrouter"
    local = is_local_provider(provider)
    key_name = "OPENROUTER_API_KEY" if openrouter else "LLM_API_KEY"
    model_name = "OPENROUTER_MODEL" if openrouter else "LLM_MODEL"

    api_key = os.getenv(key_name, "") or (os.getenv("LLM_API_KEY", "") if openrouter else "")
    model = os.getenv(model_name, "") or (os.getenv("LLM_MODEL", "") if openrouter else "")
    if not api_key and not local:
        raise LLMConfigurationError(
            f"LLM mode requires the server-side {key_name} environment variable.")
    if not model:
        raise LLMConfigurationError(f"LLM mode requires the {model_name} environment variable.")

    default_base = OPENROUTER_DEFAULT_BASE_URL if openrouter else OPENAI_DEFAULT_BASE_URL
    base_url = os.getenv("OPENROUTER_BASE_URL" if openrouter else "LLM_BASE_URL", "") or default_base
    try:
        timeout = _positive_float("LLM_TIMEOUT_SECONDS", 45.0)
        temperature_raw = os.getenv("LLM_TEMPERATURE", "")
        temperature = float(temperature_raw) if temperature_raw.strip() else 0.0
        max_attempts = _attempts("LLM_MAX_ATTEMPTS", 2)
    except ValueError as error:
        raise LLMConfigurationError(str(error)) from error
    if not 0 <= temperature <= 2:
        raise LLMConfigurationError("LLM_TEMPERATURE must be between 0 and 2.")

    return LLMSettings(provider=provider, base_url=base_url, model=model, api_key=api_key,
        timeout_seconds=timeout, temperature=temperature, max_attempts=max_attempts,
        referer=os.getenv("OPENROUTER_SITE_URL") or None,
        application=os.getenv("OPENROUTER_APP_NAME") or None)
