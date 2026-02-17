import uuid
from unittest.mock import MagicMock

import pytest

from app.models.database import DatabaseClient


@pytest.fixture
def mock_supabase():
    client = MagicMock()
    client.table.return_value = client
    client.select.return_value = client
    client.insert.return_value = client
    client.update.return_value = client
    client.delete.return_value = client
    client.eq.return_value = client
    client.execute.return_value = MagicMock(data=[{"id": str(uuid.uuid4()), "title": "Test"}])
    return client


@pytest.fixture
def db(mock_supabase):
    return DatabaseClient(client=mock_supabase)


def test_list_documents(db, mock_supabase):
    result = db.list_documents()
    mock_supabase.table.assert_called_with("documents")
    assert len(result) == 1


def test_insert_document(db, mock_supabase):
    result = db.insert_document(
        title="Test Doc",
        doc_type="product_manual",
        hierarchy_priority=5,
        file_path="/tmp/test.pdf",
    )
    mock_supabase.table.assert_called_with("documents")
    assert result is not None


def test_delete_document_chunks(db, mock_supabase):
    doc_id = uuid.uuid4()
    db.delete_chunks_for_document(doc_id)
    mock_supabase.table.assert_called_with("document_chunks")


def test_insert_chunks(db, mock_supabase):
    doc_id = uuid.uuid4()
    chunks = [
        {
            "document_id": str(doc_id),
            "content": "test content",
            "section_title": "Section 1",
            "page_number": 1,
            "chunk_index": 0,
            "doc_type": "product_manual",
            "hierarchy_priority": 5,
            "embedding": [0.1] * 1536,
            "token_count": 50,
        }
    ]
    db.insert_chunks(chunks)
    mock_supabase.table.assert_called_with("document_chunks")
