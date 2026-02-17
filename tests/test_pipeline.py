import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.pipeline import QueryPipeline


@pytest.fixture
def mock_deps():
    query_parser = MagicMock()
    query_parser.parse.return_value = MagicMock(
        original_question="How do I wire X for GridCo?",
        detected_provider="GridCo",
        to_filters=lambda: {"grid_provider": "GridCo"},
    )

    vector_search = AsyncMock()
    vector_search.search.return_value = [
        {
            "content": "Wire X to terminal Y.",
            "section_title": "Wiring",
            "page_number": 5,
            "doc_type": "product_manual",
            "document_title": "Manual A",
            "grid_provider": "GridCo",
            "hierarchy_priority": 5,
            "similarity": 0.9,
        },
    ]

    reranker = MagicMock()
    reranker.rerank.return_value = [
        {
            "content": "Wire X to terminal Y.",
            "section_title": "Wiring",
            "page_number": 5,
            "doc_type": "product_manual",
            "document_title": "Manual A",
            "grid_provider": "GridCo",
            "hierarchy_priority": 5,
            "similarity": 0.9,
            "rerank_score": 1.2,
        },
    ]

    llm = AsyncMock()
    llm.generate.return_value = "Wire X to terminal Y [Manual A, Wiring, Page 5].\n\nConfidence: high"
    llm.model = "claude-sonnet-4-6"

    formatter = MagicMock()
    formatter.format.return_value = {
        "answer": "Wire X to terminal Y [Manual A, Wiring, Page 5].",
        "sources": [{"document_title": "Manual A", "section": "Wiring", "page": 5}],
        "confidence": "high",
    }

    logger = MagicMock()
    logger.log.return_value = uuid.uuid4()

    return {
        "query_parser": query_parser,
        "vector_search": vector_search,
        "reranker": reranker,
        "llm": llm,
        "formatter": formatter,
        "logger": logger,
    }


@pytest.mark.asyncio
async def test_pipeline_returns_response(mock_deps):
    pipeline = QueryPipeline(**mock_deps)
    result = await pipeline.run("How do I wire X for GridCo?")

    assert result["answer"] == "Wire X to terminal Y [Manual A, Wiring, Page 5]."
    assert result["confidence"] == "high"
    assert "log_id" in result


@pytest.mark.asyncio
async def test_pipeline_calls_all_steps(mock_deps):
    pipeline = QueryPipeline(**mock_deps)
    await pipeline.run("How do I wire X for GridCo?")

    mock_deps["query_parser"].parse.assert_called_once()
    mock_deps["vector_search"].search.assert_called_once()
    mock_deps["reranker"].rerank.assert_called_once()
    mock_deps["llm"].generate.assert_called_once()
    mock_deps["formatter"].format.assert_called_once()
    mock_deps["logger"].log.assert_called_once()
