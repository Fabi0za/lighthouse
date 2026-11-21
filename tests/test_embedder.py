from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.ingestion.embedder import MAX_BATCH, Embedder


def _response(n: int, value: float = 0.1):
    return SimpleNamespace(embeddings=SimpleNamespace(float_=[[value] * 1536 for _ in range(n)]))


@pytest.fixture
def embedder():
    return Embedder(api_key="test-key", model="embed-v5.0-pro", dimensions=1536)


def test_embedder_init(embedder):
    assert embedder.model == "embed-v5.0-pro"
    assert embedder.dimensions == 1536


@pytest.mark.asyncio
async def test_embed_texts_uses_search_document(embedder):
    mock = AsyncMock(return_value=_response(2))
    with patch.object(embedder.client, "embed", mock):
        result = await embedder.embed_texts(["text one", "text two"])
    assert len(result) == 2 and len(result[0]) == 1536
    kwargs = mock.call_args.kwargs
    assert kwargs["input_type"] == "search_document"
    assert kwargs["model"] == "embed-v5.0-pro"
    assert kwargs["output_dimension"] == 1536
    assert kwargs["embedding_types"] == ["float"]


@pytest.mark.asyncio
async def test_embed_query_uses_search_query(embedder):
    mock = AsyncMock(return_value=_response(1))
    with patch.object(embedder.client, "embed", mock):
        result = await embedder.embed_query("question")
    assert len(result) == 1536
    assert mock.call_args.kwargs["input_type"] == "search_query"
    assert mock.call_args.kwargs["texts"] == ["question"]


@pytest.mark.asyncio
async def test_embed_texts_batches_at_limit(embedder):
    texts = [f"t{i}" for i in range(MAX_BATCH + 5)]
    mock = AsyncMock(side_effect=[_response(MAX_BATCH), _response(5)])
    with patch.object(embedder.client, "embed", mock):
        result = await embedder.embed_texts(texts)
    assert len(result) == MAX_BATCH + 5
    assert mock.call_count == 2
    assert len(mock.call_args_list[1].kwargs["texts"]) == 5
