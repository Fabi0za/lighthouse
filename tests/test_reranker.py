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


def test_reranker_diversity_avoids_same_section():
    """When many chunks come from the same section, diversity selection
    should promote chunks from other sections into the top-N."""
    reranker = Reranker(top_n=4, diversity_penalty=0.5)
    chunks = [
        _chunk(content="general rule A", similarity=0.95),
        _chunk(content="general rule B", similarity=0.93),
        _chunk(content="general rule C", similarity=0.91),
        _chunk(content="general rule D", similarity=0.89),
        # Different section, slightly lower score — should still make top-4
        {
            **_chunk(content="altitude exception", similarity=0.85),
            "section_title": "Anhang 1",
        },
    ]
    # All first 4 chunks have section_title="Section" (from _chunk helper)
    result = reranker.rerank(chunks, detected_provider=None)
    contents = [r["content"] for r in result]
    assert "altitude exception" in contents


def test_reranker_diversity_across_documents():
    """Chunks from different documents should be preferred over redundant
    chunks from the same document."""
    reranker = Reranker(top_n=3, diversity_penalty=0.5)
    doc_a = str(uuid.uuid4())
    doc_b = str(uuid.uuid4())
    chunks = [
        {**_chunk(content="doc A chunk 1", similarity=0.95), "document_id": doc_a},
        {**_chunk(content="doc A chunk 2", similarity=0.93), "document_id": doc_a},
        {**_chunk(content="doc A chunk 3", similarity=0.91), "document_id": doc_a},
        {**_chunk(content="doc B chunk 1", similarity=0.85), "document_id": doc_b, "section_title": "Other"},
    ]
    result = reranker.rerank(chunks, detected_provider=None)
    doc_ids = [r.get("document_id") for r in result]
    assert doc_b in doc_ids


def test_reranker_diversity_zero_penalty_behaves_like_before():
    """With diversity_penalty=0, behavior should match pure score ranking."""
    reranker = Reranker(top_n=3, diversity_penalty=0.0)
    chunks = [
        _chunk(content="A", similarity=0.95),
        _chunk(content="B", similarity=0.93),
        _chunk(content="C", similarity=0.91),
        {**_chunk(content="D", similarity=0.85), "section_title": "Other"},
    ]
    result = reranker.rerank(chunks, detected_provider=None)
    # Pure score order — D should NOT make it in
    contents = [r["content"] for r in result]
    assert contents == ["A", "B", "C"]
