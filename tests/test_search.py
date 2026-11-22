import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.retrieval.search import VectorSearch


def mock_db():
    db = MagicMock()
    chunk1_id = str(uuid.uuid4())
    chunk2_id = str(uuid.uuid4())
    db.vector_search.return_value = [
        {
            "id": chunk1_id,
            "content": "Wiring instructions for component X.",
            "section_title": "Wiring",
            "page_number": 5,
            "level": "operator",
            "scopes": [],
            "rank": 5,
            "similarity": 0.85,
        },
        {
            "id": chunk2_id,
            "content": "General wiring standards.",
            "section_title": "Standards",
            "page_number": 2,
            "level": "operator",
            "scopes": [],
            "rank": 1,
            "similarity": 0.78,
        },
    ]
    db.keyword_search.return_value = []
    db._chunk1_id = chunk1_id
    db._chunk2_id = chunk2_id
    return db


def mock_embedder():
    embedder = AsyncMock()
    embedder.embed_query.return_value = [0.1] * 1536
    return embedder


@pytest.mark.asyncio
async def test_vector_search_returns_chunks():
    db = mock_db()
    embedder = mock_embedder()
    search = VectorSearch(db=db, embedder=embedder, top_k=20)
    results = await search.search("How do I wire component X?")
    assert len(results) == 2
    embedder.embed_query.assert_called_once_with("How do I wire component X?")
    db.vector_search.assert_called_once()
