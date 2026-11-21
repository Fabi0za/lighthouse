import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def mock_pipeline():
    pipeline = AsyncMock()
    pipeline.run.return_value = {
        "answer": "Wire X to terminal Y.",
        "sources": [{"document_title": "Manual A", "section": "Wiring", "page": 5}],
        "confidence": "high",
        "log_id": str(uuid.uuid4()),
    }
    return pipeline


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.list_documents.return_value = [
        {"id": str(uuid.uuid4()), "title": "Test Doc", "source_id": str(uuid.uuid4()),
         "status": "current", "ingestion_status": "completed"}
    ]
    db.get_document.return_value = {
        "id": str(uuid.uuid4()), "title": "Test Doc", "source_id": str(uuid.uuid4()),
        "status": "current", "ingestion_status": "completed"
    }
    db.get_query_log.return_value = {
        "id": str(uuid.uuid4()), "question": "test?", "detected_filters": {},
        "retrieved_chunks": [], "reranked_chunks": [], "llm_prompt": "p",
        "llm_response": "r", "formatted_answer": {}, "model_used": "test",
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
    assert "log_id" in data


def test_list_documents(client):
    response = client.get("/documents")
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_get_query_log(client):
    log_id = uuid.uuid4()
    response = client.get(f"/query/{log_id}")
    assert response.status_code == 200
    assert "question" in response.json()


def test_documents_cannot_be_deleted(client):
    response = client.delete(f"/documents/{uuid.uuid4()}")
    assert response.status_code == 405
