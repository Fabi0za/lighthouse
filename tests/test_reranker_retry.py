from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from cohere.errors import TooManyRequestsError

from app.retrieval.reranker import CohereReranker


def test_reranker_retries_on_rate_limit():
    reranker = CohereReranker(api_key="k", top_n=1, model="rerank-v3.5")
    ok = SimpleNamespace(results=[SimpleNamespace(index=0, relevance_score=0.9)])
    reranker.client = MagicMock()
    reranker.client.rerank.side_effect = [TooManyRequestsError(body=None), ok]
    with patch("app.retrieval.reranker.time.sleep") as sleep:
        result = reranker.rerank([{"content": "c"}], query="q")
    assert result == [{"content": "c", "rerank_score": 0.9}]
    sleep.assert_called_once()


def test_reranker_imports_the_error_directly():
    import app.retrieval.reranker as module
    assert module.TooManyRequestsError is TooManyRequestsError
