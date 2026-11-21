import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.retrieval.search import HybridSearch, VectorSearch


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
            "authority_rank": 5,
            "similarity": 0.85,
        },
        {
            "id": chunk2_id,
            "content": "General wiring standards.",
            "section_title": "Standards",
            "page_number": 2,
            "level": "operator",
            "scopes": [],
            "authority_rank": 1,
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


@pytest.mark.asyncio
async def test_hybrid_search_calls_both():
    db = mock_db()
    embedder = mock_embedder()
    search = HybridSearch(db=db, embedder=embedder, top_k=20)
    results = await search.search("How do I wire component X?")
    assert len(results) == 2
    db.vector_search.assert_called_once()
    db.keyword_search.assert_called_once_with("How do I wire component X?", 20)


@pytest.mark.asyncio
async def test_hybrid_search_rrf_merges_unique_results():
    db = mock_db()
    embedder = mock_embedder()

    # Keyword search returns one overlapping and one new chunk
    new_chunk_id = str(uuid.uuid4())
    db.keyword_search.return_value = [
        {
            "id": db._chunk1_id,  # same as vector result #1
            "content": "Wiring instructions for component X.",
            "section_title": "Wiring",
            "page_number": 5,
            "level": "operator",
            "scopes": [],
            "authority_rank": 5,
            "rank": 0.5,
        },
        {
            "id": new_chunk_id,
            "content": "New keyword-only result.",
            "section_title": "Other",
            "page_number": 1,
            "level": "operator",
            "scopes": [],
            "authority_rank": 1,
            "rank": 0.3,
        },
    ]

    search = HybridSearch(db=db, embedder=embedder, top_k=20)
    results = await search.search("test query")

    # Should have 3 unique chunks
    assert len(results) == 3

    # Chunk appearing in both should have highest RRF score
    rrf_scores = {r["id"]: r["rrf_score"] for r in results}
    assert rrf_scores[db._chunk1_id] > rrf_scores[db._chunk2_id]
    assert rrf_scores[db._chunk1_id] > rrf_scores[new_chunk_id]
