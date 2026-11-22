import uuid
from unittest.mock import MagicMock

import pytest

from app.models.database import DatabaseClient


@pytest.fixture
def mock_supabase():
    client = MagicMock()
    client.table.return_value = client
    client.select.return_value = client
    client.insert.return_value = client
    client.update.return_value = client
    client.delete.return_value = client
    client.upsert.return_value = client
    client.eq.return_value = client
    client.is_.return_value = client
    client.order.return_value = client
    client.execute.return_value = MagicMock(data=[{"id": str(uuid.uuid4()), "title": "Test"}])
    return client


@pytest.fixture
def db(mock_supabase):
    return DatabaseClient(client=mock_supabase)


def test_list_documents(db, mock_supabase):
    result = db.list_versions()
    mock_supabase.table.assert_called_with("versions")
    assert len(result) == 1


def test_insert_chunks(db, mock_supabase):
    chunks = [{
        "version_id": str(uuid.uuid4()),
        "content": "test content",
        "section_title": "Section 1",
        "page_number": 1,
        "chunk_index": 0,
        "embedding": [0.1] * 1536,
    }]
    db.insert_chunks(chunks)
    mock_supabase.table.assert_called_with("chunks")


def test_log_answer_calls_rpc_and_returns_id(db, mock_supabase):
    answer_id = str(uuid.uuid4())
    mock_supabase.rpc.return_value.execute.return_value = MagicMock(data=answer_id)
    result = db.log_answer({"question": "q"}, ["d1", "d2"])
    mock_supabase.rpc.assert_called_once_with(
        "log_answer", {"p_answer": {"question": "q"}, "p_version_ids": ["d1", "d2"]}
    )
    assert result == answer_id


def test_set_text_fingerprint(db, mock_supabase):
    db.set_text_fingerprint("d", "t1", {"x": 1})
    mock_supabase.update.assert_called_once_with({"text_sha256": "t1", "parsed_output": {"x": 1}})


def test_get_known_scopes(db, mock_supabase):
    mock_supabase.execute.return_value = MagicMock(data=[{"key": "bkw"}, {"key": "ekz"}])
    assert sorted(db.get_known_scopes()) == ["bkw", "ekz"]
    mock_supabase.table.assert_called_with("scopes")


def test_find_source_returns_none_when_missing(db, mock_supabase):
    mock_supabase.execute.return_value = MagicMock(data=[])
    assert db.find_source("nothing") is None
    mock_supabase.eq.assert_called_with("key", "nothing")


def test_find_source_returns_level_and_sorted_scopes(db, mock_supabase):
    mock_supabase.execute.return_value = MagicMock(data=[
        {"key": "s", "level": "operator", "watch_address": None,
         "source_scopes": [{"scope_key": "ekz"}, {"scope_key": "bkw"}]}])
    assert db.find_source("s") == {"key": "s", "level": "operator", "watch_address": None,
                                   "scopes": ["bkw", "ekz"]}


def test_save_source_calls_rpc(db, mock_supabase):
    db.save_source("s", "operator", ["bkw"], "https://example.org/s.pdf")
    mock_supabase.rpc.assert_called_once_with(
        "save_source", {"p_key": "s", "p_level": "operator", "p_scopes": ["bkw"],
                        "p_watch_address": "https://example.org/s.pdf"})


def test_list_source_keys(db, mock_supabase):
    mock_supabase.execute.return_value = MagicMock(data=[{"key": "b"}, {"key": "a"}])
    assert db.list_source_keys() == ["a", "b"]
    mock_supabase.table.assert_called_with("sources")


def test_save_levels_upserts_on_key(db, mock_supabase):
    rows = [{"key": "national", "rank": 1, "requires_scope": False}]
    db.save_levels(rows)
    mock_supabase.table.assert_called_with("levels")
    mock_supabase.upsert.assert_called_once_with(rows, on_conflict="key")


def test_save_scopes_upserts_on_key(db, mock_supabase):
    rows = [{"key": "bkw", "name": "BKW Energie AG"}]
    db.save_scopes(rows)
    mock_supabase.table.assert_called_with("scopes")
    mock_supabase.upsert.assert_called_once_with(rows, on_conflict="key")


def _rpc_returns(mock_supabase, data):
    mock_supabase.rpc.return_value.execute.return_value = MagicMock(data=data)


def test_begin_load_calls_rpc_and_returns_id(db, mock_supabase):
    _rpc_returns(mock_supabase, "v1")
    assert db.begin_load("s", "Doc", "V2", "https://example.org/v2.pdf", 4, "abc", "key-1") == "v1"
    mock_supabase.rpc.assert_called_once_with("begin_load", {
        "p_source_key": "s", "p_title": "Doc", "p_version_label": "V2",
        "p_obtained_from": "https://example.org/v2.pdf", "p_page_limit": 4, "p_file_sha256": "abc",
        "p_indexing_settings_key": "key-1"})


def test_fail_load_calls_rpc_and_returns_flag_number(db, mock_supabase):
    _rpc_returns(mock_supabase, 12)
    assert db.fail_load("v1", "load_failed", "data/a.pdf", "boom") == 12
    mock_supabase.rpc.assert_called_once_with("fail_load", {
        "p_version_id": "v1", "p_reason": "load_failed", "p_file": "data/a.pdf", "p_message": "boom"})


def test_discard_version_calls_rpc(db, mock_supabase):
    db.discard_version("v1")
    mock_supabase.rpc.assert_called_once_with("discard_version", {"p_version_id": "v1", "p_resolved_by": "system"})


def test_resolve_check_calls_rpc(db, mock_supabase):
    db.resolve_check(12)
    mock_supabase.rpc.assert_called_once_with("resolve_check", {"p_flag_id": 12})


def test_list_loading_versions(db, mock_supabase):
    db.list_loading_versions()
    mock_supabase.table.assert_called_with("versions")
    mock_supabase.eq.assert_called_with("status", "loading")


def test_promote_version_calls_rpc_and_returns_answer_count(db, mock_supabase):
    _rpc_returns(mock_supabase, 3)
    assert db.promote_version("v1") == 3
    mock_supabase.rpc.assert_called_once_with("promote_version", {"p_version_id": "v1", "p_resolved_by": "system"})


def test_reject_version_calls_rpc(db, mock_supabase):
    db.reject_version("v1")
    mock_supabase.rpc.assert_called_once_with("reject_version", {"p_version_id": "v1"})


def test_removed_lifecycle_methods(db):
    for name in ("hold_version", "delete_pending_version", "update_version"):
        assert not hasattr(db, name), name


def test_hold_candidate_calls_rpc(db, mock_supabase):
    _rpc_returns(mock_supabase, 7)
    assert db.hold_candidate("v1", "https://example.org/v2.pdf", "evidence") == 7
    mock_supabase.rpc.assert_called_once_with("hold_candidate", {
        "p_version_id": "v1", "p_address": "https://example.org/v2.pdf", "p_message": "evidence"})


def test_approve_candidate_calls_rpc_and_returns_answer_count(db, mock_supabase):
    _rpc_returns(mock_supabase, 2)
    assert db.approve_candidate("v1") == 2
    mock_supabase.rpc.assert_called_once_with("approve_candidate", {"p_version_id": "v1"})


def test_raise_check_failed_calls_rpc(db, mock_supabase):
    _rpc_returns(mock_supabase, 9)
    assert db.raise_check_failed("s", "https://example.org/gone.pdf", "HTTP 404") == 9
    mock_supabase.rpc.assert_called_once_with("raise_check_failed", {
        "p_source_key": "s", "p_address": "https://example.org/gone.pdf", "p_message": "HTTP 404"})


def test_confirm_source_calls_rpc(db, mock_supabase):
    db.confirm_source("s")
    mock_supabase.rpc.assert_called_once_with("confirm_source", {"p_source_key": "s"})


def test_raise_overdue_flags_passes_days(db, mock_supabase):
    _rpc_returns(mock_supabase, 3)
    assert db.raise_overdue_flags(180) == 3
    mock_supabase.rpc.assert_called_once_with("raise_overdue_flags", {"p_max_age": "180 days"})



def test_find_version_by_source_and_label(db, mock_supabase):
    mock_supabase.execute.return_value = MagicMock(data=[{"id": "v12"}])
    assert db.find_version("s", "V1.2") == {"id": "v12"}
    calls = [c.args for c in mock_supabase.eq.call_args_list]
    assert ("source_key", "s") in calls and ("version_label", "V1.2") in calls


def test_answers_that_saw_calls_rpc(db, mock_supabase):
    _rpc_returns(mock_supabase, [{"answer_id": "a"}])
    assert db.answers_that_saw("v1") == [{"answer_id": "a"}]
    mock_supabase.rpc.assert_called_once_with("answers_that_saw", {"p_version_id": "v1"})


def test_list_open_flags_with_held_versions(db, mock_supabase):
    mock_supabase.execute.return_value = MagicMock(data=[{"id": 1}])
    assert db.list_open_flags() == [{"id": 1}]
    mock_supabase.table.assert_called_with("flags")
    mock_supabase.select.assert_called_with("*, versions(id)")
    mock_supabase.is_.assert_called_with("resolved_at", "null")
    mock_supabase.order.assert_called_with("id")


def test_save_indexing_settings_upserts_on_key(db, mock_supabase):
    row = {"key": "k", "embedding_model": "m"}
    db.save_indexing_settings(row)
    mock_supabase.table.assert_called_with("indexing_settings")
    mock_supabase.upsert.assert_called_once_with(row, on_conflict="key")


def test_current_indexing_settings_keys_are_distinct(db, mock_supabase):
    mock_supabase.execute.return_value = MagicMock(data=[
        {"indexing_settings_key": "b"}, {"indexing_settings_key": "a"}, {"indexing_settings_key": "b"}])
    assert db.current_indexing_settings_keys() == ["a", "b"]
    mock_supabase.eq.assert_called_with("status", "current")


def test_save_answer_settings_upserts_on_key(db, mock_supabase):
    db.save_answer_settings({"key": "k"})
    mock_supabase.table.assert_called_with("answer_settings")
    mock_supabase.upsert.assert_called_once_with({"key": "k"}, on_conflict="key")


def test_versions_seen_by_an_answer(db, mock_supabase):
    mock_supabase.execute.return_value = MagicMock(data=[
        {"versions": {"source_key": "s", "version_label": "V1", "status": "retired"}}])
    assert db.versions_seen("a1") == [{"source_key": "s", "version_label": "V1", "status": "retired"}]
    mock_supabase.table.assert_called_with("answer_versions")
    mock_supabase.eq.assert_called_with("answer_id", "a1")


def test_get_eval_questions_with_sources_and_facts(db, mock_supabase):
    mock_supabase.execute.return_value = MagicMock(data=[{
        "key": "q", "question": "Q?", "question_type": "answerable", "case_type": "standard",
        "expected_answer": "A.",
        "eval_question_sources": [{"source_key": "s", "written_from_text_sha256": "t"}],
        "eval_question_facts": [{"position": 2, "text": "b"}, {"position": 1, "text": "a"}]}])
    (q,) = db.get_eval_questions()
    assert q["sources"] == [{"source_key": "s", "written_from_text_sha256": "t"}]
    assert q["facts"] == [{"position": 1, "text": "a"}, {"position": 2, "text": "b"}]
    assert "eval_question_facts" not in q


def test_record_eval_run_calls_rpc(db, mock_supabase):
    _rpc_returns(mock_supabase, "run-1")
    assert db.record_eval_run({"results": []}) == "run-1"
    mock_supabase.rpc.assert_called_once_with("record_eval_run", {"p_run": {"results": []}})


def test_list_eval_runs_reads_the_view(db, mock_supabase):
    db.list_eval_runs()
    mock_supabase.table.assert_called_with("eval_run_scores")



def test_save_eval_question_calls_rpc(db, mock_supabase):
    db.save_eval_question({"key": "q"})
    mock_supabase.rpc.assert_called_once_with("save_eval_question", {"p_question": {"key": "q"}})


def test_set_watch_address_calls_rpc(db, mock_supabase):
    db.set_watch_address("s", "https://example.org/new.pdf")
    mock_supabase.rpc.assert_called_once_with(
        "set_watch_address", {"p_source_key": "s", "p_address": "https://example.org/new.pdf"})

