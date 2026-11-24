import litellm
import pytest

from tests.conftest import chat, make_client

METADATA_FIELDS = {
    "resolution_source", "model", "latency_ms", "input_tokens",
    "output_tokens", "key_id", "fallback_attempts",
}


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "keys_configured": 2, "cache_enabled": True}


def test_chat_contract(client):
    r = chat(client, "s-1", "What is the capital of France?")
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] == "s-1"
    assert body["reply"]
    meta = body["metadata"]
    assert METADATA_FIELDS <= set(meta)
    assert meta["resolution_source"] == "LIVE_INFERENCE"
    assert meta["key_id"] == "key_1"
    assert meta["fallback_attempts"] == 0
    assert isinstance(meta["latency_ms"], int) and meta["latency_ms"] >= 1
    assert meta["input_tokens"] > 0 and meta["output_tokens"] > 0


def test_cache_hit_across_sessions(client):
    first = chat(client, "a", "Same question").json()
    second = chat(client, "b", "Same question").json()  # new session, same first message
    assert second["metadata"]["resolution_source"] == "LLM_CACHE"
    assert second["reply"] == first["reply"]
    assert second["metadata"]["key_id"] is None
    assert second["metadata"]["fallback_attempts"] == 0
    assert second["metadata"]["input_tokens"] == first["metadata"]["input_tokens"]
    assert second["metadata"]["output_tokens"] == first["metadata"]["output_tokens"]


def test_different_message_never_cached(client):
    chat(client, "a", "Question one")
    other = chat(client, "b", "Question two").json()
    assert other["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert "Question two" in other["reply"]


def test_multi_turn_history_is_sent_to_llm(client):
    r1 = chat(client, "m", "My name is Abhay").json()
    r2 = chat(client, "m", "What is my name?").json()
    # mock reply reports how many messages were sent: system+user, then system+user+assistant+user
    assert "context: 2 messages" in r1["reply"]
    assert "context: 4 messages" in r2["reply"]
    assert r2["metadata"]["input_tokens"] > r1["metadata"]["input_tokens"] - 1


def test_sessions_are_separate(client):
    chat(client, "s1", "hello one")
    chat(client, "s2", "hello two")
    m1 = client.get("/sessions/s1/messages").json()["messages"]
    m2 = client.get("/sessions/s2/messages").json()["messages"]
    assert [m["content"] for m in m1 if m["role"] == "user"] == ["hello one"]
    assert [m["content"] for m in m2 if m["role"] == "user"] == ["hello two"]


def test_tokens_are_per_request_not_cumulative(client):
    a = chat(client, "x1", "equal length 1").json()["metadata"]["input_tokens"]
    b = chat(client, "x2", "equal length 2").json()["metadata"]["input_tokens"]
    assert abs(a - b) <= 2


def test_history_endpoint_order_and_shape(client):
    chat(client, "h", "first")
    chat(client, "h", "second")
    body = client.get("/sessions/h/messages").json()
    assert body["session_id"] == "h"
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["user", "assistant", "user", "assistant"]
    assert body["messages"][0]["content"] == "first"
    assert "metadata" not in body["messages"][0]
    meta = body["messages"][1]["metadata"]
    assert {"resolution_source", "input_tokens", "output_tokens"} <= set(meta)
    assert all(m["role"] != "system" for m in body["messages"])


def test_unknown_session_404(client):
    r = client.get("/sessions/nope/messages")
    assert r.status_code == 404
    assert r.json() == {"detail": "session not found"}


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"session_id": "s"},
        {"message": "hi"},
        {"session_id": "", "message": "hi"},
        {"session_id": "s", "message": ""},
        {"session_id": "s", "message": "    "},
        {"session_id": "s", "message": "x" * 4001},
        {"session_id": "s" * 129, "message": "hi"},
    ],
)
def test_validation_422(client, payload):
    r = client.post("/chat", json=payload)
    assert r.status_code == 422
    assert "detail" in r.json()


def test_message_of_4000_chars_after_trim_is_ok(client):
    assert chat(client, "long", "  " + "x" * 4000 + "  ").status_code == 200


def test_malformed_json_422(client):
    r = client.post("/chat", content="{not json", headers={"Content-Type": "application/json"})
    assert r.status_code == 422
    assert "detail" in r.json()


def test_failed_request_not_in_history(client):
    r = chat(client, "f", "will fail", headers={"X-Simulate-Failure": "*=429"})
    assert r.status_code == 503
    assert client.get("/sessions/f/messages").status_code == 404
    assert chat(client, "f", "").status_code == 422
    assert client.get("/sessions/f/messages").status_code == 404


@pytest.mark.parametrize("header", ["key_1=429", "key_1=500", "key_1=502", "key_1=503"])
def test_failover_to_key_2(client, header):
    r = chat(client, "fo", f"hello {header}", headers={"X-Simulate-Failure": header})
    assert r.status_code == 200
    meta = r.json()["metadata"]
    assert meta["key_id"] == "key_2"
    assert meta["fallback_attempts"] == 1
    assert meta["resolution_source"] == "LIVE_INFERENCE"
    assert "provider" not in r.json()["reply"].lower()


def test_failover_works_even_if_message_is_cached(client):
    chat(client, "c1", "cached text")
    r = chat(client, "c2", "cached text", headers={"X-Simulate-Failure": "key_1=429"})
    assert r.status_code == 200
    assert r.json()["metadata"]["key_id"] == "key_2"


def test_all_keys_fail_503(client):
    for header in ["*=429", "key_1=429,key_2=500"]:
        r = chat(client, "all", "anything", headers={"X-Simulate-Failure": header})
        assert r.status_code == 503
        assert r.json() == {"detail": "all providers unavailable"}


def test_simulation_ignored_when_disabled(tmp_path):
    from app.config import Settings
    from app.main import create_app
    from fastapi.testclient import TestClient

    settings = Settings(
        llm_api_keys=["a", "b"], database_url=f"sqlite:///{tmp_path}/d.db",
        enable_failure_simulation=False, llm_mock=True,
    )
    c = TestClient(create_app(settings))
    r = chat(c, "s", "hi", headers={"X-Simulate-Failure": "*=429"})
    assert r.status_code == 200
    assert r.json()["metadata"]["key_id"] == "key_1"


def test_real_provider_errors_fall_back(tmp_path, monkeypatch):
    """Real LiteLLM exceptions (429 then 500) must fail over to the next key."""
    from app.config import Settings
    from app.main import create_app
    from fastapi.testclient import TestClient

    real = litellm.completion  # captured before patching

    def fake_completion(**kwargs):
        if kwargs["api_key"] == "k1":
            raise litellm.RateLimitError("quota", llm_provider="gemini", model="m")
        return real(**{**kwargs, "mock_response": "from key two"})

    settings = Settings(llm_api_keys=["k1", "k2"], database_url=f"sqlite:///{tmp_path}/r.db", llm_mock=False)
    c = TestClient(create_app(settings))
    monkeypatch.setattr("app.llm.litellm.completion", fake_completion)
    r = chat(c, "s", "hello")
    assert r.status_code == 200
    assert r.json()["metadata"]["key_id"] == "key_2"
    assert r.json()["metadata"]["fallback_attempts"] == 1
    assert r.json()["reply"] == "from key two"

    def always_fail(**kwargs):
        raise litellm.InternalServerError("boom", llm_provider="gemini", model="m")

    monkeypatch.setattr("app.llm.litellm.completion", always_fail)
    r = chat(c, "s2", "hello again")
    assert r.status_code == 503
    assert r.json() == {"detail": "all providers unavailable"}
    monkeypatch.setattr("app.llm.litellm.completion", real)


def test_system_prompt_saved_for_session(client):
    chat(client, "sp", "hi", system_prompt="You are a pirate")
    chat(client, "sp", "again")
    # system prompt persisted for the session: 2 prior msgs + system + user = 4 sent
    msgs = client.get("/sessions/sp/messages").json()["messages"]
    assert len(msgs) == 4


def test_history_survives_restart(tmp_path):
    c1 = make_client(tmp_path)
    chat(c1, "persist", "remember me")
    c2 = make_client(tmp_path)  # new app instance, same SQLite file
    msgs = c2.get("/sessions/persist/messages").json()["messages"]
    assert msgs[0]["content"] == "remember me"


def test_cors_allows_frontend_origin_and_custom_header(client):
    r = client.options(
        "/chat",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-simulate-failure",
        },
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "x-simulate-failure" in r.headers["access-control-allow-headers"].lower()
