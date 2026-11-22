import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def mock_pipeline():
    pipeline = AsyncMock()
    pipeline.run.return_value = {
        "answer": "Wire X to terminal Y.",
        "sources": [{"version_title": "Manual A", "section": "Wiring", "page": 5}],
        "confidence": "high",
        "answer_id": str(uuid.uuid4()),
    }
    return pipeline


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.list_versions.return_value = [
        {"id": str(uuid.uuid4()), "title": "Test Doc", "source_key": str(uuid.uuid4()),
         "status": "current", "ingestion_status": "completed"}
    ]
    db.get_answer.return_value = {
        "id": str(uuid.uuid4()), "question": "test?", "detected_scope": None,
        "retrieved_chunks": [],
        "reranked_chunks": [{"version_title": "T", "version_label": "V1.3", "section_title": "S",
                             "page_number": 2}],
        "llm_prompt": "p",
        "llm_response": "Antwort.\n\nConfidence: high",
        "indexing_settings_key": "ik", "answer_settings_key": "ak",
        "latency_ms": 100,
    }
    return db


@pytest.fixture
def client(mock_pipeline, mock_db):
    from app.main import create_app
    app = create_app(pipeline=mock_pipeline, db=mock_db)
    return TestClient(app)


def test_query_endpoint(client, mock_pipeline):
    response = client.post("/query", json={"question": "How do I wire X?"})
    assert response.status_code == 200
    data = response.json()
    assert "answer" in data
    assert "sources" in data
    assert "confidence" in data
    assert "answer_id" in data


def test_list_versions(client):
    response = client.get("/versions")
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_get_answer(client):
    answer_id = uuid.uuid4()
    response = client.get(f"/answers/{answer_id}")
    assert response.status_code == 200
    assert "question" in response.json()


def test_ingest_is_gone(client):
    assert client.post("/ingest").status_code == 404


def test_documents_are_read_only(client):
    """No route can change or delete a version: retired versions are the record."""
    writes = [
        (route.path, sorted(route.methods & {"POST", "PUT", "PATCH", "DELETE"}))
        for route in client.app.routes
        if route.path.startswith("/versions") and route.methods & {"POST", "PUT", "PATCH", "DELETE"}
    ]
    assert writes == []


def test_old_paths_are_gone(client):
    assert client.get("/documents").status_code == 404
    assert client.get(f"/query/{uuid.uuid4()}").status_code == 404


def test_get_answer_derives_formatted_and_lists_versions(client, mock_db):
    mock_db.versions_seen.return_value = [
        {"source_key": "bkw-vorgaben-niederspannung", "version_label": "V1.3", "status": "current"}]
    data = client.get(f"/answers/{uuid.uuid4()}").json()
    assert data["formatted"] == {"answer": "Antwort.", "confidence": "high",
                                 "sources": [{"version_title": "T (V1.3)", "section": "S", "page": 2}]}
    assert data["versions"] == mock_db.versions_seen.return_value
