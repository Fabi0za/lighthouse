import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.pipeline import QueryPipeline


@pytest.fixture
def mock_deps():
    query_parser = MagicMock()
    query_parser.parse.return_value = MagicMock(
        original_question="How do I wire X for BKW?",
        detected_scope="bkw",
    )

    vector_search = AsyncMock()
    vector_search.search.return_value = [
        {
            "content": "Wire X to terminal Y.",
            "section_title": "Wiring",
            "page_number": 5,
            "version_id": "d1",
            "level": "operator",
            "version_title": "Manual A",
            "scopes": ["bkw"],
            "rank": 2,
            "similarity": 0.9,
        },
    ]

    reranker = MagicMock()
    reranker.rerank.return_value = [
        {
            "content": "Wire X to terminal Y.",
            "section_title": "Wiring",
            "page_number": 5,
            "version_id": "d1",
            "level": "operator",
            "version_title": "Manual A",
            "scopes": ["bkw"],
            "rank": 2,
            "similarity": 0.9,
            "rerank_score": 1.2,
        },
    ]

    llm = AsyncMock()
    llm.generate.return_value = "Wire X to terminal Y [Manual A, Wiring, Page 5].\n\nConfidence: high"
    llm.model = "claude-sonnet-5-5"

    formatter = MagicMock()
    formatter.format.return_value = {
        "answer": "Wire X to terminal Y [Manual A, Wiring, Page 5].",
        "sources": [{"version_title": "Manual A", "section": "Wiring", "page": 5}],
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
        "indexing_settings_key": "ik",
        "answer_settings_key": "ak",
    }


@pytest.mark.asyncio
async def test_pipeline_returns_response(mock_deps):
    pipeline = QueryPipeline(**mock_deps)
    result = await pipeline.run("How do I wire X for BKW?")

    assert result["answer"] == "Wire X to terminal Y [Manual A, Wiring, Page 5]."
    assert result["confidence"] == "high"
    assert "answer_id" in result


@pytest.mark.asyncio
async def test_pipeline_calls_all_steps(mock_deps):
    pipeline = QueryPipeline(**mock_deps)
    await pipeline.run("How do I wire X for BKW?")

    mock_deps["query_parser"].parse.assert_called_once()
    mock_deps["vector_search"].search.assert_called_once()
    mock_deps["reranker"].rerank.assert_called_once()
    mock_deps["llm"].generate.assert_called_once()
    mock_deps["formatter"].format.assert_called_once()
    mock_deps["logger"].log.assert_called_once()


@pytest.mark.asyncio
async def test_pipeline_logs_distinct_versions_of_the_top_chunks(mock_deps):
    mock_deps["reranker"].rerank.return_value = [
        {"content": "a", "version_id": "d1", "version_title": "A"},
        {"content": "b", "version_id": "d1", "version_title": "A"},
        {"content": "c", "version_id": "d2", "version_title": "B"},
    ]
    pipeline = QueryPipeline(**mock_deps)
    await pipeline.run("q")
    assert mock_deps["logger"].log.call_args.kwargs["version_ids"] == ["d1", "d2"]


@pytest.mark.asyncio
async def test_pipeline_returns_retrieved_and_reranked_chunks(mock_deps):
    pipeline = QueryPipeline(**mock_deps)
    result = await pipeline.run("How do I wire X for BKW?")
    assert result["retrieved_chunks"] == mock_deps["vector_search"].search.return_value
    assert result["reranked_chunks"] == mock_deps["reranker"].rerank.return_value


@pytest.mark.asyncio
async def test_pipeline_logs_detected_scope(mock_deps):
    pipeline = QueryPipeline(**mock_deps)
    question = "How do I wire X for BKW?"
    await pipeline.run(question)
    assert mock_deps["logger"].log.call_args.kwargs["detected_scope"] == "bkw"
    mock_deps["reranker"].rerank.assert_called_once_with(
        mock_deps["vector_search"].search.return_value, query=question
    )


@pytest.mark.asyncio
async def test_pipeline_logs_settings_keys(mock_deps):
    await QueryPipeline(**mock_deps).run("q")
    kwargs = mock_deps["logger"].log.call_args.kwargs
    assert (kwargs["indexing_settings_key"], kwargs["answer_settings_key"]) == ("ik", "ak")
    assert not {"model_used", "formatted_answer"} & set(kwargs)
