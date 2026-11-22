from unittest.mock import AsyncMock, MagicMock

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def _settings():
    return Settings(_env_file=None, supabase_url="http://localhost", supabase_service_key="k",
                    reducto_api_key="k", anthropic_api_key="")


def _client(db, pipeline, settings=None):
    return TestClient(create_app(pipeline=pipeline, db=db, settings=settings))


def test_eval_run_records_a_run_without_config_snapshot():
    db = MagicMock()
    db.get_eval_questions.return_value = []
    db.record_eval_run.return_value = "run-1"
    pipeline = AsyncMock()
    pipeline.indexing_settings_key, pipeline.answer_settings_key = "ik", "ak"

    response = _client(db, pipeline, _settings()).post("/eval/run", json={"notes": "test run"})

    assert response.status_code == 200
    run = db.record_eval_run.call_args.args[0]
    assert "config_snapshot" not in run
    assert (run["judge_model"], run["notes"]) == ("claude-haiku-5-5", "test run")
    assert response.json()["run_id"] == "run-1"


def test_eval_run_needs_settings():
    assert _client(MagicMock(), AsyncMock()).post("/eval/run").status_code == 503


def test_list_eval_runs_reads_the_scores_view():
    db = MagicMock()
    db.list_eval_runs.return_value = [{"run_id": "r", "questions": 2, "scored": 1, "not_scored": 1}]
    assert _client(db, AsyncMock()).get("/eval/runs").json() == db.list_eval_runs.return_value
