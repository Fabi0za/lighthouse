import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.ingestion.embedder import Embedder


@pytest.fixture
def embedder():
    return Embedder(api_key="test-key", model="text-embedding-3-small", dimensions=1536)


def test_embedder_init(embedder):
    assert embedder.model == "text-embedding-3-small"
    assert embedder.dimensions == 1536


@pytest.mark.asyncio
async def test_embed_single_text(embedder):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [{"embedding": [0.1] * 1536}]
    }
    with patch.object(embedder.client, "post", new_callable=AsyncMock, return_value=mock_response):
        result = await embedder.embed_texts(["test text"])
        assert len(result) == 1
        assert len(result[0]) == 1536


@pytest.mark.asyncio
async def test_embed_multiple_texts(embedder):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [
            {"embedding": [0.1] * 1536},
            {"embedding": [0.2] * 1536},
        ]
    }
    with patch.object(embedder.client, "post", new_callable=AsyncMock, return_value=mock_response):
        result = await embedder.embed_texts(["text one", "text two"])
        assert len(result) == 2
