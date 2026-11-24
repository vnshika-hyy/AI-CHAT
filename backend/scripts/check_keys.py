"""Send one tiny request with each key in LLM_API_KEYS to check the model + keys work.

Usage (from /backend):  LLM_API_KEYS=k1,k2 LLM_MODEL=gemini/gemini-2.5-flash-lite python scripts/check_keys.py
Never prints the keys themselves.
"""
import os

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
import litellm  # noqa: E402

model = os.environ.get("LLM_MODEL", "gemini/gemini-2.5-flash-lite")
keys = [k.strip() for k in os.environ.get("LLM_API_KEYS", "").split(",") if k.strip()]
print(f"model: {model}   keys: {len(keys)}")
for i, key in enumerate(keys, start=1):
    try:
        r = litellm.completion(
            model=model, api_key=key, num_retries=0, timeout=30,
            messages=[{"role": "user", "content": "Reply with the single word: pong"}],
        )
        print(f"key_{i}: OK  -> {r.choices[0].message.content!r}  tokens={r.usage.prompt_tokens}/{r.usage.completion_tokens}")
    except Exception as exc:
        print(f"key_{i}: FAIL ({type(exc).__name__}): {str(exc)[:200].replace(key, '***')}")
