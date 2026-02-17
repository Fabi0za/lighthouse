import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.retrieval.search import VectorSearch


def mock_db():
    db = MagicMock()
    db.vector_search.return_value = [
        {
            "id": str(uuid.uuid4()),
            "content": "Wiring instructions for component X.",
            "section_title": "Wiring",
            "page_number": 5,
            "doc_type": "product_manual",
            "grid_provider": None,
            "hierarchy_priority": 5,
            "similarity": 0.85,
        },
        {
            "id": str(uuid.uuid4()),
            "content": "General wiring standards.",
            "section_title": "Standards",
            "page_number": 2,
            "doc_type": "general_regulation",
            "grid_provider": None,
            "hierarchy_priority": 1,
            "similarity": 0.78,
        },
    ]
    return db


def mock_embedder():
    embedder = AsyncMock()
    embedder.embed_query.return_value = [0.1] * 1536
    return embedder


@pytest.mark.asyncio
async def test_search_returns_chunks():
    db = mock_db()
    embedder = mock_embedder()
    search = VectorSearch(db=db, embedder=embedder, top_k=20)
    results = await search.search("How do I wire component X?")
    assert len(results) == 2
    embedder.embed_query.assert_called_once_with("How do I wire component X?")
    db.vector_search.assert_called_once()


@pytest.mark.asyncio
async def test_search_passes_top_k():
    db = mock_db()
    embedder = mock_embedder()
    search = VectorSearch(db=db, embedder=embedder, top_k=10)
    await search.search("test query")
    db.vector_search.assert_called_once_with([0.1] * 1536, 10)
