from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.config import Settings
from app.providers.local import LocalTimetableProvider


@pytest.fixture
def client(provider, settings) -> TestClient:
    app = create_app(settings=settings, provider=provider)
    return TestClient(app)


def test_health_reports_dataset(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["railway_provider"] == "local_sqlite"
    assert body["dataset"]["trains"] == 4
    assert body["dataset"]["dataset_date"] == "2026-01-01"


def test_chat_search_returns_tables(client):
    response = client.post(
        "/chat",
        json={"message": "Trains from Alpha Jn to Beta Nagar on 2026-11-15"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["session_id"]
    assert body["tool_results"][0]["ok"] is True
    assert "| Train |" in body["reply"]
    assert body["sources"][0]["kind"] == "scheduled"


def test_chat_follow_up_uses_conversation_context(client):
    first = client.post("/chat", json={"message": "Schedule of train 00002"}).json()
    second = client.post(
        "/chat",
        json={"message": "What are its stops?", "session_id": first["session_id"]},
    )
    assert second.status_code == 200
    body = second.json()
    assert body["session_id"] == first["session_id"]
    assert body["tool_results"][0]["tool"] == "get_train_schedule"
    assert "Beta Nagar" in body["reply"]


def test_chat_asks_for_missing_date(client):
    response = client.post("/chat", json={"message": "Trains from Alpha Jn to Beta Nagar"})
    body = response.json()
    assert response.status_code == 200
    assert "journey date" in body["reply"].lower()
    assert body["tool_results"] == []


def test_unsupported_live_status_is_explained(client):
    response = client.post("/chat", json={"message": "Is train 00001 running late today?"})
    body = response.json()
    assert response.status_code == 200
    assert body["tool_results"][0]["error"]["code"] == "feature_unsupported"
    assert body["degraded"] is True
    assert "not configured" in body["reply"].lower()


def test_empty_message_rejected(client):
    assert client.post("/chat", json={"message": ""}).status_code == 422


def test_message_too_long_rejected(provider, fixture_db):
    settings = Settings(llm_provider="none", railway_db_path=fixture_db, max_message_chars=20)
    client = TestClient(create_app(settings=settings, provider=provider))
    response = client.post("/chat", json={"message": "x" * 40})
    assert response.status_code == 400


def test_invalid_session_id_rejected(client):
    response = client.post("/chat", json={"message": "hello", "session_id": "bad id!"})
    assert response.status_code == 400


def test_config_error_returns_503(provider, fixture_db):
    settings = Settings(llm_provider="ollama", ollama_model="", railway_db_path=fixture_db)
    app = create_app(settings=settings, provider=provider)
    client = TestClient(app)
    response = client.post("/chat", json={"message": "hello"})
    assert response.status_code == 503
    assert "OLLAMA_MODEL" in response.json()["detail"]
    assert client.get("/health").json()["status"] == "degraded"


def test_index_and_static_assets_served(client):
    assert client.get("/").status_code == 200
    assert client.get("/static/app.js").status_code == 200


def test_missing_dataset_degrades_health(tmp_path):
    provider = LocalTimetableProvider(tmp_path / "missing.db")
    settings = Settings(llm_provider="none", railway_db_path=tmp_path / "missing.db")
    client = TestClient(create_app(settings=settings, provider=provider))
    health = client.get("/health").json()
    assert health["status"] == "degraded"
    assert health["dataset"]["status"] == "missing"
