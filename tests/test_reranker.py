import uuid

from app.retrieval.reranker import Reranker


def _chunk(
    content="test",
    similarity=0.8,
    doc_type="general_regulation",
    grid_provider=None,
    hierarchy_priority=1,
):
    return {
        "id": str(uuid.uuid4()),
        "content": content,
        "section_title": "Section",
        "page_number": 1,
        "doc_type": doc_type,
        "grid_provider": grid_provider,
        "hierarchy_priority": hierarchy_priority,
        "similarity": similarity,
    }


def test_reranker_boosts_matching_provider():
    reranker = Reranker(top_n=2)
    chunks = [
        _chunk(content="general rule", similarity=0.9, hierarchy_priority=1),
        _chunk(content="provider specific", similarity=0.7, grid_provider="GridCo", hierarchy_priority=5),
    ]
    result = reranker.rerank(chunks, detected_provider="GridCo")
    assert result[0]["content"] == "provider specific"


def test_reranker_applies_hierarchy_priority():
    reranker = Reranker(top_n=2)
    chunks = [
        _chunk(content="low priority", similarity=0.85, hierarchy_priority=1),
        _chunk(content="high priority", similarity=0.80, hierarchy_priority=10),
    ]
    result = reranker.rerank(chunks, detected_provider=None)
    assert result[0]["content"] == "high priority"


def test_reranker_limits_to_top_n():
    reranker = Reranker(top_n=3)
    chunks = [_chunk(similarity=0.9 - i * 0.1) for i in range(10)]
    result = reranker.rerank(chunks, detected_provider=None)
    assert len(result) == 3


def test_reranker_preserves_scores():
    reranker = Reranker(top_n=5)
    chunks = [_chunk(similarity=0.8)]
    result = reranker.rerank(chunks, detected_provider=None)
    assert "rerank_score" in result[0]


def test_reranker_no_chunks():
    reranker = Reranker(top_n=5)
    result = reranker.rerank([], detected_provider=None)
    assert result == []
