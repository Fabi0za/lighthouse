import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def mock_db():
    db = MagicMock()
    doc_id = str(uuid.uuid4())
    db.insert_document.return_value = {"id": doc_id, "title": "Test", "ingestion_status": "pending"}
    db.update_document.return_value = {"id": doc_id, "ingestion_status": "completed"}
    db.delete_chunks_for_document.return_value = None
    db.insert_chunks.return_value = None
    return db


@pytest.fixture
def mock_parser():
    parser = AsyncMock()
    parser.parse_pdf.return_value = (
        {"result": {"blocks": []}},
        [{"title": "Section 1", "content": "Test content " * 50, "page": 1}],
    )
    return parser


@pytest.fixture
def mock_chunker():
    chunker = MagicMock()
    chunker.chunk_sections.return_value = [
        MagicMock(content="chunk text", section_title="Section 1", page_number=1, chunk_index=0, token_count=50),
    ]
    return chunker


@pytest.fixture
def mock_embedder():
    embedder = AsyncMock()
    embedder.embed_texts.return_value = [[0.1] * 1536]
    return embedder


@pytest.fixture
def client(mock_db, mock_parser, mock_chunker, mock_embedder):
    app = create_app(
        db=mock_db,
        parser=mock_parser,
        chunker=mock_chunker,
        embedder=mock_embedder,
    )
    return TestClient(app)


def test_ingest_endpoint(client, mock_db, mock_parser):
    response = client.post(
        "/ingest",
        data={
            "title": "Test Document",
            "doc_type": "product_manual",
            "hierarchy_priority": "5",
        },
        files={"file": ("test.pdf", b"fake pdf content", "application/pdf")},
    )
    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert data["ingestion_status"] == "completed"
