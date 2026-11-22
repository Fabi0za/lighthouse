import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def app_with_eval():
    db = MagicMock()
    db.get_eval_questions.return_value = [
        {
            "id": str(uuid.uuid4()),
            "question": "Test?",
            "question_type": "answerable",
            "expected_answer": "Yes.",
            "required_source_docs": [],
            "required_facts": [],
            "category": "test",
        },
    ]
    db.insert_eval_run.return_value = {"id": str(uuid.uuid4())}

    pipeline = AsyncMock()
    pipeline.run.return_value = {
        "answer": "Yes.",
        "sources": [],
        "confidence": "high",
        "answer_id": str(uuid.uuid4()),
        "retrieved_chunks": [],
        "reranked_chunks": [],
    }

    app = create_app(pipeline=pipeline, db=db)
    return TestClient(app)


def test_eval_run_endpoint_returns_results(app_with_eval):
    response = app_with_eval.post("/eval/run", json={"notes": "test run"})
    assert response.status_code == 200
    data = response.json()
    assert "aggregate_scores" in data
    assert "results" in data
