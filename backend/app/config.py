"""Runtime configuration. Everything comes from environment variables."""
import os
from dataclasses import dataclass, field


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    # Key pool: key ids are key_1, key_2, ... in this order.
    llm_api_keys: list[str] = field(default_factory=list, repr=False)
    llm_model: str = "gemini/gemini-2.5-flash-lite"
    database_url: str = "sqlite:///./app.db"
    allowed_origins: list[str] = field(default_factory=lambda: ["http://localhost:3000"])
    enable_failure_simulation: bool = False
    default_system_prompt: str = "You are a helpful, concise assistant."
    # LiteLLM in-memory cache
    cache_enabled: bool = True
    # Provider calls
    request_timeout_seconds: float = 30.0
    key_cooldown_seconds: float = 20.0
    llm_max_tokens: int | None = None
    # Offline mode: LiteLLM returns a canned reply (used by tests / keyless demos)
    llm_mock: bool = False

    @property
    def sqlite_path(self) -> str:
        url = self.database_url
        prefix = "sqlite:///"
        if not url.startswith(prefix):
            raise ValueError("DATABASE_URL must look like sqlite:////data/app.db")
        return url[len(prefix):]


def load_settings() -> Settings:
    env = os.environ
    max_tokens = env.get("LLM_MAX_TOKENS")
    return Settings(
        llm_api_keys=_as_list(env.get("LLM_API_KEYS")),
        llm_model=env.get("LLM_MODEL", Settings.llm_model).strip(),
        database_url=env.get("DATABASE_URL", Settings.database_url).strip(),
        allowed_origins=[o.rstrip("/") for o in _as_list(env.get("ALLOWED_ORIGINS"))]
        or ["http://localhost:3000"],
        enable_failure_simulation=_as_bool(env.get("ENABLE_FAILURE_SIMULATION")),
        default_system_prompt=env.get("DEFAULT_SYSTEM_PROMPT", Settings.default_system_prompt),
        cache_enabled=_as_bool(env.get("CACHE_ENABLED"), True),
        request_timeout_seconds=float(env.get("REQUEST_TIMEOUT_SECONDS", "30")),
        key_cooldown_seconds=float(env.get("KEY_COOLDOWN_SECONDS", "20")),
        llm_max_tokens=int(max_tokens) if max_tokens else None,
        llm_mock=_as_bool(env.get("LLM_MOCK")),
    )
