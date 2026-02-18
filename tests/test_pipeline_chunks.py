import pytest
from unittest.mock import AsyncMock, MagicMock

from app.pipeline import QueryPipeline


@pytest.fixture
def pipeline():
    query_parser = MagicMock()
    parsed = MagicMock()
    parsed.to_filters.return_value = {}
    parsed.detected_provider = None
    query_parser.parse.return_value = parsed

    vector_search = AsyncMock()
    vector_search.search.return_value = [
        {"document_id": "doc-1", "content": "chunk 1", "similarity": 0.9},
    ]

    reranker = MagicMock()
    reranker.rerank.return_value = [
        {"document_id": "doc-1", "content": "chunk 1", "similarity": 0.9, "final_score": 0.95},
    ]

    llm = AsyncMock()
    llm.generate.return_value = "Answer text\n\nConfidence: high"
    llm.model = "test-model"

    formatter = MagicMock()
    formatter.format.return_value = {
        "answer": "Answer text",
        "sources": [],
        "confidence": "high",
    }

    logger = MagicMock()
    logger.log.return_value = "log-id-123"

    return QueryPipeline(
        query_parser=query_parser,
        vector_search=vector_search,
        reranker=reranker,
        llm=llm,
        formatter=formatter,
        logger=logger,
    )


@pytest.mark.asyncio
async def test_pipeline_returns_retrieved_chunks(pipeline):
    result = await pipeline.run("test question")
    assert "retrieved_chunks" in result
    assert len(result["retrieved_chunks"]) == 1
    assert result["retrieved_chunks"][0]["document_id"] == "doc-1"


@pytest.mark.asyncio
async def test_pipeline_returns_reranked_chunks(pipeline):
    result = await pipeline.run("test question")
    assert "reranked_chunks" in result
    assert len(result["reranked_chunks"]) == 1
    assert result["reranked_chunks"][0]["final_score"] == 0.95
