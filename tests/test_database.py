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
    result = db.list_documents()
    mock_supabase.table.assert_called_with("documents")
    assert len(result) == 1


def test_insert_chunks(db, mock_supabase):
    chunks = [{
        "document_id": str(uuid.uuid4()),
        "content": "test content",
        "section_title": "Section 1",
        "page_number": 1,
        "chunk_index": 0,
        "embedding": [0.1] * 1536,
        "token_count": 50,
    }]
    db.insert_chunks(chunks)
    mock_supabase.table.assert_called_with("document_chunks")


def test_hold_version_inserts_flag_before_pending_document(db, mock_supabase):
    flag_id, doc_id = str(uuid.uuid4()), str(uuid.uuid4())
    mock_supabase.execute.side_effect = [
        MagicMock(data=[{"id": flag_id}]),
        MagicMock(data=[{"id": doc_id, "status": "pending"}]),
    ]
    source_id = str(uuid.uuid4())

    doc = db.hold_version(source_id, "Doc V2", "https://example.org/v2.pdf", "data/v2.pdf", "abc")

    tables = [c.args[0] for c in mock_supabase.table.call_args_list]
    assert tables == ["flags", "documents"]
    flag_row = mock_supabase.insert.call_args_list[0].args[0]
    assert flag_row == {"source_id": source_id, "kind": "new_version"}
    doc_row = mock_supabase.insert.call_args_list[1].args[0]
    assert doc_row["flag_id"] == flag_id
    assert doc_row["status"] == "pending"
    assert doc_row["source_id"] == source_id
    assert doc_row["file_sha256"] == "abc"
    assert doc["id"] == doc_id


def test_hold_version_passes_kind(db, mock_supabase):
    mock_supabase.execute.side_effect = [MagicMock(data=[{"id": "f"}]), MagicMock(data=[{"id": "d"}])]
    db.hold_version("s", "T", None, None, "abc", kind="candidate")
    assert mock_supabase.insert.call_args_list[0].args[0]["kind"] == "candidate"


def test_promote_version_calls_rpc(db, mock_supabase):
    doc_id = uuid.uuid4()
    db.promote_version(doc_id, "promoted (auto)")
    mock_supabase.rpc.assert_called_once_with(
        "promote_version", {"p_document_id": str(doc_id), "p_resolution": "promoted (auto)"}
    )


def test_reject_version_calls_rpc(db, mock_supabase):
    doc_id = uuid.uuid4()
    db.reject_version(doc_id, "rejected")
    mock_supabase.rpc.assert_called_once_with(
        "reject_version", {"p_document_id": str(doc_id), "p_resolution": "rejected"}
    )


def test_log_answer_calls_rpc_and_returns_id(db, mock_supabase):
    log_id = str(uuid.uuid4())
    mock_supabase.rpc.return_value.execute.return_value = MagicMock(data=log_id)
    result = db.log_answer({"question": "q"}, ["d1", "d2"])
    mock_supabase.rpc.assert_called_once_with(
        "log_answer", {"p_log": {"question": "q"}, "p_document_ids": ["d1", "d2"]}
    )
    assert result == log_id


def test_find_source_returns_none_when_missing(db, mock_supabase):
    mock_supabase.execute.return_value = MagicMock(data=[])
    assert db.find_source("Nothing") is None


def test_find_source_raises_on_two_matches(db, mock_supabase):
    mock_supabase.execute.return_value = MagicMock(data=[{"id": "a"}, {"id": "b"}])
    with pytest.raises(ValueError):
        db.find_source("Twice")


def test_insert_source_writes_scopes(db, mock_supabase):
    source_id = str(uuid.uuid4())
    mock_supabase.execute.side_effect = [MagicMock(data=[{"id": source_id}]), MagicMock(data=[])]
    db.insert_source("T", "I", "operator", 2, ["A", "B"], None, None)
    tables = [c.args[0] for c in mock_supabase.table.call_args_list]
    assert tables == ["sources", "source_scopes"]
    assert mock_supabase.insert.call_args_list[1].args[0] == [
        {"source_id": source_id, "scope": "A"},
        {"source_id": source_id, "scope": "B"},
    ]


def test_insert_source_without_scopes_writes_no_scope_rows(db, mock_supabase):
    mock_supabase.execute.side_effect = [MagicMock(data=[{"id": "s"}])]
    db.insert_source("T", "I", "national", 1, [], None, None)
    assert [c.args[0] for c in mock_supabase.table.call_args_list] == ["sources"]


def test_delete_pending_version_refuses_non_pending(db, mock_supabase):
    mock_supabase.execute.return_value = MagicMock(data=[{"id": "d", "status": "current", "flag_id": "f"}])
    with pytest.raises(ValueError):
        db.delete_pending_version("d", "dismissed")


def test_delete_pending_version_deletes_then_resolves_flag(db, mock_supabase):
    mock_supabase.execute.return_value = MagicMock(data=[{"id": "d", "status": "pending", "flag_id": "f"}])
    db.delete_pending_version("d", "dismissed (same text)")
    tables = [c.args[0] for c in mock_supabase.table.call_args_list]
    assert tables == ["documents", "document_chunks", "documents", "flags"]
    update = mock_supabase.update.call_args.args[0]
    assert update["resolution"] == "dismissed (same text)"
    assert "resolved_at" in update


def test_set_text_fingerprint(db, mock_supabase):
    db.set_text_fingerprint("d", "t1", {"x": 1})
    mock_supabase.update.assert_called_once_with({"text_sha256": "t1", "parsed_output": {"x": 1}})


def test_get_known_scopes(db, mock_supabase):
    mock_supabase.execute.return_value = MagicMock(data=[{"scope": "A"}, {"scope": "B"}, {"scope": "A"}])
    assert sorted(db.get_known_scopes()) == ["A", "B"]
    mock_supabase.table.assert_called_with("source_scopes")


def test_get_scopes(db, mock_supabase):
    mock_supabase.execute.return_value = MagicMock(data=[{"scope": "B"}, {"scope": "A"}])
    assert db.get_scopes("s") == ["A", "B"]
    mock_supabase.table.assert_called_with("source_scopes")


def test_update_source(db, mock_supabase):
    db.update_source("s", {"issuer": "New"})
    mock_supabase.table.assert_called_with("sources")
    mock_supabase.update.assert_called_once_with({"issuer": "New"})
    mock_supabase.eq.assert_called_with("id", "s")


def test_set_scopes_replaces_rows(db, mock_supabase):
    db.set_scopes("s", ["A", "B"])
    assert [c.args[0] for c in mock_supabase.table.call_args_list] == ["source_scopes", "source_scopes"]
    mock_supabase.delete.assert_called_once()
    assert mock_supabase.insert.call_args.args[0] == [
        {"source_id": "s", "scope": "A"}, {"source_id": "s", "scope": "B"}]


def test_set_scopes_to_none_only_deletes(db, mock_supabase):
    db.set_scopes("s", [])
    mock_supabase.insert.assert_not_called()
