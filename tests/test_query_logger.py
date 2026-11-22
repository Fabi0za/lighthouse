import uuid
from unittest.mock import MagicMock

from app.logging.query_logger import QueryLogger


def _log(logger, document_ids):
    return logger.log(
        question="How do I wire X?",
        detected_filters={"scope": "BKW"},
        retrieved_chunks=[{"content": "chunk1", "similarity": 0.9}],
        reranked_chunks=[{"content": "chunk1", "rerank_score": 1.1}],
        llm_prompt="full prompt text",
        llm_response="The answer is...",
        formatted_answer={"answer": "The answer is...", "sources": [], "confidence": "high"},
        model_used="claude-sonnet-4-6",
        latency_ms=1234,
        document_ids=document_ids,
    )


def test_log_stores_answer_with_versions_in_one_call():
    mock_db = MagicMock()
    log_id = uuid.uuid4()
    mock_db.log_answer.return_value = str(log_id)

    result = _log(QueryLogger(db=mock_db), ["d1", "d2"])

    mock_db.log_answer.assert_called_once()
    call_data, ids = mock_db.log_answer.call_args.args
    assert call_data["question"] == "How do I wire X?"
    assert call_data["detected_filters"] == {"scope": "BKW"}
    assert call_data["latency_ms"] == 1234
    assert ids == ["d1", "d2"]
    assert result == log_id
    mock_db.insert_query_log.assert_not_called()
