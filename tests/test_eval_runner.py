import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

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
