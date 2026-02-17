import uuid
from unittest.mock import MagicMock

from app.logging.query_logger import QueryLogger


def test_log_query_builds_correct_payload():
    mock_db = MagicMock()
    mock_db.insert_query_log.return_value = {"id": str(uuid.uuid4())}

    logger = QueryLogger(db=mock_db)
    log_id = logger.log(
        question="How do I wire X?",
        detected_filters={"grid_provider": "GridCo"},
        retrieved_chunks=[{"content": "chunk1", "similarity": 0.9}],
        reranked_chunks=[{"content": "chunk1", "rerank_score": 1.1}],
        llm_prompt="full prompt text",
        llm_response="The answer is...",
        formatted_answer={"answer": "The answer is...", "sources": [], "confidence": "high"},
        model_used="claude-sonnet-4-6",
        latency_ms=1234,
    )

    mock_db.insert_query_log.assert_called_once()
    call_data = mock_db.insert_query_log.call_args[0][0]
    assert call_data["question"] == "How do I wire X?"
    assert call_data["detected_filters"] == {"grid_provider": "GridCo"}
    assert call_data["latency_ms"] == 1234
    assert log_id is not None
