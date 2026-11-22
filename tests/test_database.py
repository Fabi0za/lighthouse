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


def test_hold_version_inserts_flag_before_pending_document(db, mock_supabase):
    flag_id, doc_id = str(uuid.uuid4()), str(uuid.uuid4())
    mock_supabase.execute.side_effect = [
        MagicMock(data=[{"id": flag_id}]),
        MagicMock(data=[{"id": doc_id, "status": "pending"}]),
    ]
    source_key = "bkw-vorgaben"

    doc = db.hold_version(source_key, "Doc", "V2", "https://example.org/v2.pdf", 4, "abc")

    tables = [c.args[0] for c in mock_supabase.table.call_args_list]
    assert tables == ["flags", "versions"]
    flag_row = mock_supabase.insert.call_args_list[0].args[0]
    assert flag_row == {"source_key": source_key, "kind": "new_version"}
    doc_row = mock_supabase.insert.call_args_list[1].args[0]
    assert doc_row["flag_id"] == flag_id
    assert doc_row["status"] == "pending"
    assert doc_row["source_key"] == source_key
    assert doc_row["file_sha256"] == "abc"
    assert (doc_row["title"], doc_row["version_label"], doc_row["page_limit"]) == ("Doc", "V2", 4)
    assert doc_row["obtained_from"] == "https://example.org/v2.pdf"
    assert "file_path" not in doc_row
    assert doc["id"] == doc_id


def test_hold_version_passes_kind(db, mock_supabase):
    mock_supabase.execute.side_effect = [MagicMock(data=[{"id": "f"}]), MagicMock(data=[{"id": "d"}])]
    db.hold_version("s", "T", None, None, None, "abc", kind="candidate")
    assert mock_supabase.insert.call_args_list[0].args[0]["kind"] == "candidate"


def test_promote_version_calls_rpc(db, mock_supabase):
    doc_id = uuid.uuid4()
    db.promote_version(doc_id, "promoted (auto)")
    mock_supabase.rpc.assert_called_once_with(
        "promote_version", {"p_version_id": str(doc_id), "p_resolution": "promoted (auto)"}
    )


def test_reject_version_calls_rpc(db, mock_supabase):
    doc_id = uuid.uuid4()
    db.reject_version(doc_id, "rejected")
    mock_supabase.rpc.assert_called_once_with(
        "reject_version", {"p_version_id": str(doc_id), "p_resolution": "rejected"}
    )


def test_log_answer_calls_rpc_and_returns_id(db, mock_supabase):
    answer_id = str(uuid.uuid4())
    mock_supabase.rpc.return_value.execute.return_value = MagicMock(data=answer_id)
    result = db.log_answer({"question": "q"}, ["d1", "d2"])
    mock_supabase.rpc.assert_called_once_with(
        "log_answer", {"p_answer": {"question": "q"}, "p_version_ids": ["d1", "d2"]}
    )
    assert result == answer_id






def test_delete_pending_version_refuses_non_pending(db, mock_supabase):
    mock_supabase.execute.return_value = MagicMock(data=[{"id": "d", "status": "current", "flag_id": "f"}])
    with pytest.raises(ValueError):
        db.delete_pending_version("d", "dismissed")


def test_delete_pending_version_deletes_then_resolves_flag(db, mock_supabase):
    mock_supabase.execute.return_value = MagicMock(data=[{"id": "d", "status": "pending", "flag_id": "f"}])
    db.delete_pending_version("d", "dismissed (same text)")
    tables = [c.args[0] for c in mock_supabase.table.call_args_list]
    assert tables == ["versions", "chunks", "versions", "flags"]
    update = mock_supabase.update.call_args.args[0]
    assert update["resolution"] == "dismissed (same text)"
    assert "resolved_at" in update


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


def test_hold_version_writes_source_key(db, mock_supabase):
    mock_supabase.execute.side_effect = [MagicMock(data=[{"id": "f"}]), MagicMock(data=[{"id": "v"}])]
    db.hold_version("s", "T", None, None, None, "h")
    assert mock_supabase.insert.call_args_list[0].args[0]["source_key"] == "s"
    assert mock_supabase.insert.call_args_list[1].args[0]["source_key"] == "s"

