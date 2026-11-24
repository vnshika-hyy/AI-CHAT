"""LiteLLM gateway: key pool, automatic fail-over and response caching."""
import logging
import math
import os
import time
from dataclasses import dataclass

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")  # no network call on import

import litellm  # noqa: E402
from litellm.caching.caching import Cache  # noqa: E402

from .config import Settings  # noqa: E402

logger = logging.getLogger("app.llm")

SIMULATABLE_STATUSES = {429, 500, 502, 503}
LIVE_INFERENCE = "LIVE_INFERENCE"
LLM_CACHE = "LLM_CACHE"


class AllProvidersUnavailable(Exception):
    """Every key in the pool failed for this request."""


@dataclass
class LLMResult:
    reply: str
    resolution_source: str
    model: str
    input_tokens: int
    output_tokens: int
    key_id: str | None
    fallback_attempts: int


def configure_litellm(settings: Settings) -> None:
    """Enable LiteLLM's built-in in-memory cache (cache key = model + full message list)."""
    litellm.drop_params = True
    litellm.suppress_debug_info = True
    litellm.set_verbose = False
    if not settings.cache_enabled:
        litellm.cache = None
        return
    litellm.cache = Cache(type="local")


def parse_simulation(header: str | None) -> dict[str, int]:
    """Parse 'key_1=429,key_2=500' or '*=429'. Invalid pairs are ignored."""
    result: dict[str, int] = {}
    if not header:
        return result
    for pair in header.split(","):
        key, sep, status = pair.strip().partition("=")
        key, status = key.strip(), status.strip()
        if sep and key and status.isdigit() and int(status) in SIMULATABLE_STATUSES:
            result[key] = int(status)
    return result


class KeyPool:
    """Ordered keys (key_1, key_2, ...). Recently failed keys are tried last."""

    def __init__(self, keys: list[str], cooldown_seconds: float):
        self.keys = [(f"key_{i}", k) for i, k in enumerate(keys, start=1)]
        self.cooldown = cooldown_seconds
        self._cooling_until: dict[str, float] = {}

    def __len__(self) -> int:
        return len(self.keys)

    def ordered(self) -> list[tuple[str, str]]:
        now = time.monotonic()
        ready = [kv for kv in self.keys if self._cooling_until.get(kv[0], 0) <= now]
        cooling = [kv for kv in self.keys if kv not in ready]
        return ready + cooling

    def mark_failed(self, key_id: str) -> None:
        if self.cooldown > 0:
            self._cooling_until[key_id] = time.monotonic() + self.cooldown


class LLMGateway:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.pool = KeyPool(settings.llm_api_keys, settings.key_cooldown_seconds)
        configure_litellm(settings)
        self._warm_up()

    def _warm_up(self) -> None:
        """Run two offline mock calls so LiteLLM's lazy imports happen at startup, not on a user's first cache hit."""
        if litellm.cache is None:
            return
        try:
            probe = [{"role": "user", "content": "__warmup__"}]
            for _ in range(2):
                litellm.completion(
                    model=self.settings.llm_model, messages=probe, api_key="warmup",
                    mock_response="ok", num_retries=0,
                )
        except Exception as exc:  # warm-up must never block startup
            logger.warning("warm-up skipped (%s)", type(exc).__name__)

    @property
    def cache_enabled(self) -> bool:
        return litellm.cache is not None

    def complete(self, messages: list[dict], simulate: dict[str, int] | None = None) -> LLMResult:
        simulate = simulate or {}
        attempts = 0
        for key_id, api_key in self.pool.ordered():
            sim_status = simulate.get(key_id) or simulate.get("*")
            if sim_status:
                # Test hook: behave as if this provider key returned `sim_status`.
                logger.warning("%s: simulated HTTP %s (this request only)", key_id, sim_status)
                attempts += 1
                continue
            try:
                response = self._call(messages, api_key, bypass_cache=bool(simulate))
                reply = (response.choices[0].message.content or "").strip()
                if not reply:
                    raise ValueError("empty completion")
            except Exception as exc:  # any provider failure -> try the next key
                logger.warning("%s failed (%s); trying next key", key_id, type(exc).__name__)
                self.pool.mark_failed(key_id)
                attempts += 1
                continue

            cached = bool(getattr(response, "_hidden_params", {}).get("cache_hit"))
            input_tokens, output_tokens = self._usage(response, messages, reply)
            return LLMResult(
                reply=reply,
                resolution_source=LLM_CACHE if cached else LIVE_INFERENCE,
                model=self.settings.llm_model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                key_id=None if cached else key_id,
                fallback_attempts=0 if cached else attempts,
            )
        raise AllProvidersUnavailable()

    def _call(self, messages: list[dict], api_key: str, bypass_cache: bool):
        kwargs: dict = dict(
            model=self.settings.llm_model,
            messages=messages,
            api_key=api_key,
            timeout=self.settings.request_timeout_seconds,
            num_retries=0,  # we do our own fail-over across keys
            temperature=0.3,
        )
        if self.settings.llm_max_tokens:
            kwargs["max_tokens"] = self.settings.llm_max_tokens
        if bypass_cache:
            # Failure-simulation requests must produce a real, live answer.
            kwargs["cache"] = {"no-cache": True}
        if self.settings.llm_mock:
            last_user = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
            kwargs["mock_response"] = f"Mock reply (context: {len(messages)} messages) to: {last_user[:300]}"
        return litellm.completion(**kwargs)

    def _usage(self, response, messages: list[dict], reply: str) -> tuple[int, int]:
        usage = getattr(response, "usage", None)
        prompt = getattr(usage, "prompt_tokens", None)
        completion = getattr(usage, "completion_tokens", None)
        if prompt is None:
            prompt = litellm.token_counter(model=self.settings.llm_model, messages=messages)
        if completion is None:
            completion = litellm.token_counter(model=self.settings.llm_model, text=reply)
        return int(prompt), int(completion)


def elapsed_ms(start: float) -> int:
    """Whole milliseconds since `start` (perf_counter), at least 1."""
    return max(1, math.ceil((time.perf_counter() - start) * 1000))
