import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def make_client(tmp_path, **overrides) -> TestClient:
    settings = Settings(
        llm_api_keys=["test-key-1", "test-key-2"],
        database_url=f"sqlite:///{tmp_path}/test.db",
        enable_failure_simulation=True,
        llm_mock=True,  # LiteLLM returns a canned reply: no network, real cache logic
        **overrides,
    )
    return TestClient(create_app(settings))


@pytest.fixture
def client(tmp_path):
    return make_client(tmp_path)


def chat(client, session_id, message, headers=None, **extra):
    return client.post("/chat", json={"session_id": session_id, "message": message, **extra}, headers=headers or {})
