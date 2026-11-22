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


def test_reranker_scores_header_and_text_like_the_embedding():
    reranker = CohereReranker(api_key="k", top_n=1, model="rerank-v3.5")
    reranker.client = MagicMock()
    reranker.client.rerank.return_value = SimpleNamespace(results=[SimpleNamespace(index=0, relevance_score=0.9)])
    chunk = {"content": "Steuerdraht 2 ist optional.", "version_title": "Vorgaben", "version_label": "V1.3",
             "section_title": "4. Steuern"}
    result = reranker.rerank([chunk], query="q")
    assert reranker.client.rerank.call_args.kwargs["documents"] == ["[Vorgaben (V1.3) — 4. Steuern]\nSteuerdraht 2 ist optional."]
    assert result[0]["content"] == "Steuerdraht 2 ist optional."  # the chunk itself is unchanged
