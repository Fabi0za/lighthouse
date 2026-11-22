import uuid
from unittest.mock import MagicMock

from app.answers.logger import AnswerLogger


def _log(logger, version_ids):
    return logger.log(
        question="How do I wire X?",
        detected_scope="bkw",
        retrieved_chunks=[{"content": "chunk1", "similarity": 0.9}],
        reranked_chunks=[{"content": "chunk1", "rerank_score": 1.1}],
        llm_prompt="full prompt text",
        llm_response="The answer is...",
        latency_ms=1234,
        indexing_settings_key="embed-v5.0-pro-1536-500-50-c1",
        answer_settings_key="top40-rerank8-rerank-v3.5-claude-sonnet-5-5-p1",
        version_ids=version_ids,
    )


def test_log_stores_answer_with_versions_in_one_call():
    mock_db = MagicMock()
    answer_id = uuid.uuid4()
    mock_db.log_answer.return_value = str(answer_id)

    result = _log(AnswerLogger(db=mock_db), ["d1", "d2"])

    mock_db.log_answer.assert_called_once()
    call_data, ids = mock_db.log_answer.call_args.args
    assert call_data["question"] == "How do I wire X?"
    assert call_data["detected_scope"] == "bkw"
    assert call_data["latency_ms"] == 1234
    assert call_data["indexing_settings_key"] == "embed-v5.0-pro-1536-500-50-c1"
    assert call_data["answer_settings_key"] == "top40-rerank8-rerank-v3.5-claude-sonnet-5-5-p1"
    assert not {"model_used", "formatted_answer"} & set(call_data)
    assert ids == ["d1", "d2"]
    assert result == answer_id
    mock_db.insert_query_log.assert_not_called()
