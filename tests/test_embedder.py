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


def test_embedding_input_has_the_header_once():
    from app.ingestion.embedder import embedding_input
    assert embedding_input("T", "V1.3", "S", "text") == "[T (V1.3) — S]\ntext"


def test_embedding_input_without_section_or_label():
    from app.ingestion.embedder import embedding_input
    assert embedding_input("T", None, "", "text") == "[T]\ntext"


def _rate_limited():
    from cohere.errors import TooManyRequestsError
    return TooManyRequestsError(body={"message": "trial key: 100000 tokens per minute"})


def _paced(retries=5):
    sleep = AsyncMock()
    return Embedder(api_key="k", model="m", dimensions=1536, rate_limit_wait_seconds=61,
                    rate_limit_retries=retries, sleep=sleep), sleep


@pytest.mark.asyncio
async def test_rate_limit_is_waited_out(capsys):
    embedder, sleep = _paced()
    mock = AsyncMock(side_effect=[_rate_limited(), _response(2)])
    with patch.object(embedder.client, "embed", mock):
        result = await embedder.embed_texts(["a", "b"])
    assert len(result) == 2
    sleep.assert_awaited_once_with(61)
    assert "embedding rate limit: waiting 61 s (retry 1 of 5)" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_gives_up_after_retries():
    from cohere.errors import TooManyRequestsError
    embedder, sleep = _paced(retries=5)
    mock = AsyncMock(side_effect=[_rate_limited() for _ in range(6)])
    with patch.object(embedder.client, "embed", mock), pytest.raises(TooManyRequestsError):
        await embedder.embed_texts(["a"])
    assert sleep.await_count == 5
    assert mock.call_count == 6


@pytest.mark.asyncio
async def test_other_errors_not_retried():
    embedder, sleep = _paced()
    mock = AsyncMock(side_effect=RuntimeError("bad request"))
    with patch.object(embedder.client, "embed", mock), pytest.raises(RuntimeError):
        await embedder.embed_texts(["a"])
    sleep.assert_not_awaited()
    assert mock.call_count == 1


@pytest.mark.asyncio
async def test_waits_only_for_the_failing_batch():
    embedder, sleep = _paced()
    texts = [f"t{i}" for i in range(MAX_BATCH + 5)]
    mock = AsyncMock(side_effect=[_response(MAX_BATCH), _rate_limited(), _response(5)])
    with patch.object(embedder.client, "embed", mock):
        result = await embedder.embed_texts(texts)
    assert len(result) == MAX_BATCH + 5
    assert [len(c.kwargs["texts"]) for c in mock.call_args_list] == [MAX_BATCH, 5, 5]
