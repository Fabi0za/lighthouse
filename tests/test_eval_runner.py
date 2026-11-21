import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval.metrics import answer_correctness
from eval.runner import EvalRunner


@pytest.fixture
def mock_deps():
    db = MagicMock()
    db.get_eval_questions.return_value = [
        {
            "id": str(uuid.uuid4()),
            "question": "How do I wire X?",
            "question_type": "answerable",
            "expected_answer": "Wire X to terminal Y.",
            "required_source_docs": [str(uuid.uuid4())],
            "required_facts": ["terminal Y"],
            "category": "wiring",
        },
        {
            "id": str(uuid.uuid4()),
            "question": "What is the capital of France?",
            "question_type": "unanswerable",
            "expected_answer": None,
            "required_source_docs": [],
            "required_facts": [],
            "category": "out_of_scope",
        },
    ]
    db.insert_eval_run.return_value = {"id": str(uuid.uuid4())}

    pipeline = AsyncMock()
    pipeline.run.return_value = {
        "answer": "Wire X to terminal Y [Manual, Wiring, Page 5].",
        "sources": [{"document_title": "Manual", "section": "Wiring", "page": 5}],
        "confidence": "high",
        "log_id": str(uuid.uuid4()),
        "retrieved_chunks": [{"document_id": str(uuid.uuid4()), "content": "chunk"}],
        "reranked_chunks": [{"document_id": str(uuid.uuid4()), "content": "chunk"}],
    }

    return {"db": db, "pipeline": pipeline}


@pytest.mark.asyncio
async def test_eval_runner_processes_all_questions(mock_deps):
    runner = EvalRunner(db=mock_deps["db"], pipeline=mock_deps["pipeline"], config_snapshot={})
    results = await runner.run()

    assert "aggregate_scores" in results
    assert "results" in results
    assert len(results["results"]) == 2
    mock_deps["pipeline"].run.assert_called()


@pytest.mark.asyncio
async def test_eval_runner_stores_results(mock_deps):
    runner = EvalRunner(db=mock_deps["db"], pipeline=mock_deps["pipeline"], config_snapshot={"chunk_size": 500})
    await runner.run()

    mock_deps["db"].insert_eval_run.assert_called_once()


@pytest.mark.asyncio
async def test_eval_runner_computes_retrieval_recall(mock_deps):
    # Set required_source_docs on the answerable question
    doc_id = mock_deps["db"].get_eval_questions.return_value[0]["required_source_docs"][0]
    # Make pipeline return chunks that include the required doc
    mock_deps["pipeline"].run.return_value["retrieved_chunks"] = [
        {"document_id": doc_id, "content": "relevant chunk"},
    ]
    mock_deps["pipeline"].run.return_value["reranked_chunks"] = [
        {"document_id": doc_id, "content": "relevant chunk"},
    ]

    runner = EvalRunner(db=mock_deps["db"], pipeline=mock_deps["pipeline"], config_snapshot={})
    results = await runner.run()

    answerable_result = [r for r in results["results"] if r["question_type"] == "answerable"][0]
    assert answerable_result["retrieval_recall"] == 1.0


@pytest.mark.asyncio
async def test_eval_runner_retrieval_recall_zero_when_wrong_docs(mock_deps):
    mock_deps["pipeline"].run.return_value["retrieved_chunks"] = [
        {"document_id": "wrong-doc-id", "content": "irrelevant chunk"},
    ]
    mock_deps["pipeline"].run.return_value["reranked_chunks"] = [
        {"document_id": "wrong-doc-id", "content": "irrelevant chunk"},
    ]

    runner = EvalRunner(db=mock_deps["db"], pipeline=mock_deps["pipeline"], config_snapshot={})
    results = await runner.run()

    answerable_result = [r for r in results["results"] if r["question_type"] == "answerable"][0]
    assert answerable_result["retrieval_recall"] == 0.0


@pytest.mark.asyncio
async def test_eval_runner_answer_correctness_none_without_api_key(mock_deps):
    """Without anthropic_api_key, answer_correctness should be None."""
    runner = EvalRunner(db=mock_deps["db"], pipeline=mock_deps["pipeline"], config_snapshot={})
    results = await runner.run()

    for r in results["results"]:
        assert r["answer_correctness"] is None


def _patch_judge(results):
    """Patch the Anthropic client used by the judge to return the given fact results."""
    from types import SimpleNamespace

    from eval.metrics import FactResult, JudgeVerdict

    verdict = JudgeVerdict(results=[FactResult(**r) for r in results])
    response = SimpleNamespace(stop_reason="end_turn", parsed_output=verdict)
    patcher = patch("eval.metrics.anthropic.AsyncAnthropic")
    cls = patcher.start()
    cls.return_value.messages.parse = AsyncMock(return_value=response)
    cls.return_value.close = AsyncMock()
    return patcher, cls.return_value


@pytest.mark.asyncio
async def test_answer_correctness_parses_judge_response():
    """Test that answer_correctness correctly parses the judge LLM response."""
    patcher, client = _patch_judge([{"fact": "terminal Y", "present": True, "reason": "mentioned"}])
    try:
        result = await answer_correctness(
            question="How do I wire X?",
            generated_answer="Wire X to terminal Y.",
            expected_answer="Wire X to terminal Y.",
            required_facts=["terminal Y"],
            anthropic_api_key="test-key",
        )
    finally:
        patcher.stop()

    assert result["score"] == 1.0
    assert len(result["details"]) == 1
    assert result["details"][0]["present"] is True
    assert client.messages.parse.call_args.kwargs["model"] == "claude-haiku-5-5"


@pytest.mark.asyncio
async def test_answer_correctness_partial_score():
    """Test partial score when some facts are missing."""
    patcher, _ = _patch_judge([
        {"fact": "fact A", "present": True, "reason": "found"},
        {"fact": "fact B", "present": False, "reason": "missing"},
    ])
    try:
        result = await answer_correctness(
            question="Test?",
            generated_answer="Only fact A here.",
            expected_answer="Both fact A and fact B.",
            required_facts=["fact A", "fact B"],
            anthropic_api_key="test-key",
        )
    finally:
        patcher.stop()

    assert result["score"] == 0.5
