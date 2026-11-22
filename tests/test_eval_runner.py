from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from eval.metrics import answer_correctness
from eval.runner import EvalRunner

QUESTIONS = [
    {
        "key": "bkw-steuerdraht-2",
        "question": "Muss ein Steuerdraht 2 vorgesehen werden?",
        "question_type": "answerable",
        "case_type": "changed_between_versions",
        "expected_answer": "Nein, optional.",
        "sources": [{"source_key": "bkw-vorgaben-niederspannung", "written_from_text_sha256": "t13"}],
        "facts": [{"position": 1, "text": "Steuerdraht 2 ist optional"},
                  {"position": 2, "text": "Klemmen für Steuerdraht 1 und 0"}],
    },
    {
        "key": "hauptstadt-frankreich",
        "question": "Was ist die Hauptstadt von Frankreich?",
        "question_type": "unanswerable",
        "case_type": "not_covered",
        "expected_answer": None,
        "sources": [],
        "facts": [],
    },
]


def _pipeline(answer_ids=("a1", "a2"), source_key="bkw-vorgaben-niederspannung"):
    pipeline = AsyncMock()
    pipeline.indexing_settings_key = "ik"
    pipeline.answer_settings_key = "ak"
    pipeline.run.side_effect = [
        {"answer": "Steuerdraht 2 ist optional.", "answer_id": aid,
         "retrieved_chunks": [{"source_key": source_key}], "reranked_chunks": []}
        for aid in answer_ids
    ]
    return pipeline


def _db():
    db = MagicMock()
    db.get_eval_questions.return_value = QUESTIONS
    db.record_eval_run.return_value = "run-1"
    return db


def _judge(details=None, error=None):
    if error:
        return patch("eval.runner.answer_correctness", AsyncMock(side_effect=error))
    return patch("eval.runner.answer_correctness", AsyncMock(return_value={"score": 0.5, "details": details}))


@pytest.mark.asyncio
async def test_runner_records_one_run_with_answer_ids_and_settings():
    db = _db()
    with _judge([{"fact": "f1", "present": True, "reason": "ok"},
                 {"fact": "f2", "present": False, "reason": "missing"}]):
        out = await EvalRunner(db, _pipeline(), judge_model="claude-haiku-5-5", notes="n",
                               anthropic_api_key="k").run()
    db.record_eval_run.assert_called_once()
    run = db.record_eval_run.call_args.args[0]
    assert (run["indexing_settings_key"], run["answer_settings_key"], run["judge_model"], run["notes"]) == (
        "ik", "ak", "claude-haiku-5-5", "n")
    first, second = run["results"]
    assert (first["question_key"], first["answer_id"], first["answer_correctness"]) == ("bkw-steuerdraht-2", "a1", 0.5)
    assert second["answer_id"] == "a2" and second["answer_correctness"] is None
    assert out["run_id"] == "run-1"


@pytest.mark.asyncio
async def test_runner_scores_facts_by_position():
    db = _db()
    with _judge([{"fact": "f1", "present": True, "reason": "ok"},
                 {"fact": "f2", "present": False, "reason": "missing"}]):
        await EvalRunner(db, _pipeline(), judge_model="j", anthropic_api_key="k").run()
    facts = db.record_eval_run.call_args.args[0]["results"][0]["facts"]
    assert facts == [{"position": 1, "present": True, "reason": "ok"},
                     {"position": 2, "present": False, "reason": "missing"}]


@pytest.mark.asyncio
async def test_runner_judge_failure_is_recorded_and_the_run_continues():
    db = _db()
    with _judge(error=RuntimeError("Judge returned no verdict")):
        await EvalRunner(db, _pipeline(), judge_model="j", anthropic_api_key="k").run()
    first, second = db.record_eval_run.call_args.args[0]["results"]
    assert first["answer_correctness"] is None
    assert first["judge_error"] == "RuntimeError: Judge returned no verdict"
    assert first["facts"] == []
    assert second["question_key"] == "hauptstadt-frankreich"  # the run went on


@pytest.mark.asyncio
async def test_runner_judge_with_wrong_number_of_facts_is_a_judge_error():
    db = _db()
    with _judge([{"fact": "f1", "present": True, "reason": "ok"}]):  # two facts asked
        await EvalRunner(db, _pipeline(), judge_model="j", anthropic_api_key="k").run()
    first = db.record_eval_run.call_args.args[0]["results"][0]
    assert first["answer_correctness"] is None and "expected 2 verdicts, got 1" in first["judge_error"]


@pytest.mark.asyncio
async def test_runner_without_judge_key_scores_nothing_and_records_no_error():
    db = _db()
    await EvalRunner(db, _pipeline(), judge_model="j").run()
    first = db.record_eval_run.call_args.args[0]["results"][0]
    assert (first["answer_correctness"], first["judge_error"]) == (None, None)


@pytest.mark.asyncio
async def test_runner_recall_by_source_key():
    db = _db()
    await EvalRunner(db, _pipeline(source_key="other-source"), judge_model="j").run()
    first, second = db.record_eval_run.call_args.args[0]["results"]
    assert first["retrieval_recall"] == 0.0
    assert second["retrieval_recall"] is None  # no required sources


@pytest.mark.asyncio
async def test_runner_refusal_scored_by_question_type():
    db = _db()
    await EvalRunner(db, _pipeline(), judge_model="j").run()
    first, second = db.record_eval_run.call_args.args[0]["results"]
    assert first["refusal_correct"] is True and second["refusal_correct"] is False


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
            facts=["terminal Y"],
            anthropic_api_key="test-key",
            model="claude-haiku-5-5",
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
            facts=["fact A", "fact B"],
            anthropic_api_key="test-key",
            model="claude-haiku-5-5",
        )
    finally:
        patcher.stop()

    assert result["score"] == 0.5
