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
        "token_count": 50,
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
    assert db.begin_load("s", "Doc", "V2", "https://example.org/v2.pdf", 4, "abc") == "v1"
    mock_supabase.rpc.assert_called_once_with("begin_load", {
        "p_source_key": "s", "p_title": "Doc", "p_version_label": "V2",
        "p_obtained_from": "https://example.org/v2.pdf", "p_page_limit": 4, "p_file_sha256": "abc"})


def test_fail_load_calls_rpc_and_returns_flag_number(db, mock_supabase):
    _rpc_returns(mock_supabase, 12)
    assert db.fail_load("v1", "load_failed", "data/a.pdf", "boom") == 12
    mock_supabase.rpc.assert_called_once_with("fail_load", {
        "p_version_id": "v1", "p_reason": "load_failed", "p_file": "data/a.pdf", "p_message": "boom"})


def test_discard_version_calls_rpc(db, mock_supabase):
    db.discard_version("v1")
    mock_supabase.rpc.assert_called_once_with("discard_version", {"p_version_id": "v1"})


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

