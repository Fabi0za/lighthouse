"""promote_version, reject_version, log_answer and current-only search, on a real Postgres."""
from __future__ import annotations

import json

import pytest

from tests.db.conftest import make_document, make_source

psycopg = pytest.importorskip("psycopg")
from psycopg import errors

VEC = "[" + ",".join(["1"] + ["0"] * 1535) + "]"


def add_chunk(conn, doc_id: str, content: str = "Steuerdraht fuer Doppeltarif") -> str:
    return str(conn.execute(
        "insert into document_chunks (document_id, content, section_title, page_number, "
        "chunk_index, embedding, token_count) values (%s, %s, 'S', 1, 0, %s::vector, 5) returning id",
        (doc_id, content, VEC),
    ).fetchone()[0])


def chunk_count(conn, doc_id: str) -> int:
    return conn.execute(
        "select count(*) from document_chunks where document_id = %s", (doc_id,)
    ).fetchone()[0]


def doc(conn, doc_id: str) -> dict:
    cur = conn.execute("select * from documents where id = %s", (doc_id,))
    cols = [c.name for c in cur.description]
    return dict(zip(cols, cur.fetchone()))


def flag_of(conn, doc_id: str) -> dict:
    row = conn.execute(
        "select f.resolved_at, f.resolution from flags f join documents d on d.flag_id = f.id "
        "where d.id = %s", (doc_id,)
    ).fetchone()
    return {"resolved_at": row[0], "resolution": row[1]}


def promote(conn, doc_id: str, resolution: str = "promoted (auto)") -> None:
    conn.execute("select promote_version(%s, %s)", (doc_id, resolution))


def search_ids(conn) -> tuple[set, set]:
    vec = {str(r[0]) for r in conn.execute(
        "select document_id from match_document_chunks(%s::vector, 40)", (VEC,)).fetchall()}
    kw = {str(r[0]) for r in conn.execute(
        "select document_id from keyword_search_chunks('Steuerdraht', 40)").fetchall()}
    return vec, kw


# --- promote ---------------------------------------------------------------

def test_promote_first_version(pg):
    s = make_source(pg)
    d = make_document(pg, s, address="https://example.org/v1.pdf", text_sha256="t1")
    promote(pg, d)
    row = doc(pg, d)
    assert row["status"] == "current"
    assert row["became_current_at"] is not None
    assert flag_of(pg, d)["resolved_at"] is not None
    assert flag_of(pg, d)["resolution"] == "promoted (auto)"
    addr = pg.execute("select address from sources where id = %s", (s,)).fetchone()[0]
    assert addr == "https://example.org/v1.pdf"


def test_promote_retires_previous(pg):
    s = make_source(pg)
    v1 = make_document(pg, s, text_sha256="t1", file_sha256="f1")
    pg.execute("update documents set parsed_output = %s where id = %s", (json.dumps({"x": 1}), v1))
    add_chunk(pg, v1)
    promote(pg, v1)
    v2 = make_document(pg, s, text_sha256="t2")
    add_chunk(pg, v2)
    promote(pg, v2)
    old = doc(pg, v1)
    assert old["status"] == "retired"
    assert old["retired_at"] is not None
    assert chunk_count(pg, v1) == 0
    assert old["parsed_output"] == {"x": 1}
    assert (old["file_sha256"], old["text_sha256"]) == ("f1", "t1")
    assert doc(pg, v2)["status"] == "current"
    assert chunk_count(pg, v2) == 1


def test_promote_keeps_address_when_null(pg):
    s = make_source(pg)
    v1 = make_document(pg, s, address="https://example.org/a.pdf", text_sha256="t1")
    promote(pg, v1)
    v2 = make_document(pg, s, address=None, text_sha256="t2")
    promote(pg, v2)
    addr = pg.execute("select address from sources where id = %s", (s,)).fetchone()[0]
    assert addr == "https://example.org/a.pdf"


def test_promote_not_loaded_fails_atomically(pg_db_url):
    with psycopg.connect(pg_db_url) as conn:
        s = make_source(conn)
        v1 = make_document(conn, s, text_sha256="t1")
        add_chunk(conn, v1)
        promote(conn, v1)
        v2 = make_document(conn, s, text_sha256="t2", ingestion_status="processing")
        conn.commit()
        with pytest.raises(errors.RaiseException):
            promote(conn, v2)
        conn.rollback()
    with psycopg.connect(pg_db_url) as fresh:
        assert doc(fresh, v1)["status"] == "current"
        assert chunk_count(fresh, v1) == 1
        assert doc(fresh, v2)["status"] == "pending"


@pytest.mark.parametrize("status", ["current", "retired"])
def test_promote_requires_pending(pg, status):
    s = make_source(pg)
    d = make_document(pg, s, status=status, text_sha256="t1",
                      retired_at="2026-01-01" if status == "retired" else None)
    with pytest.raises(errors.RaiseException):
        promote(pg, d)


# --- reject ----------------------------------------------------------------

def test_reject_version(pg):
    s = make_source(pg)
    d = make_document(pg, s, text_sha256="t1")
    add_chunk(pg, d)
    pg.execute("select reject_version(%s, 'rejected')", (d,))
    row = doc(pg, d)
    assert row["status"] == "retired"
    assert row["became_current_at"] is None
    assert chunk_count(pg, d) == 0
    assert flag_of(pg, d)["resolution"] == "rejected"


def test_reject_requires_pending(pg):
    s = make_source(pg)
    d = make_document(pg, s, text_sha256="t1")
    promote(pg, d)
    with pytest.raises(errors.RaiseException):
        pg.execute("select reject_version(%s, 'rejected')", (d,))


# --- search ----------------------------------------------------------------

def test_search_excludes_retired(pg):
    s = make_source(pg)
    v1 = make_document(pg, s, text_sha256="t1")
    add_chunk(pg, v1)
    promote(pg, v1)
    v2 = make_document(pg, s, text_sha256="t2")
    add_chunk(pg, v2)
    promote(pg, v2)
    vec, kw = search_ids(pg)
    assert vec == {v2} and kw == {v2}


def test_search_excludes_pending(pg):
    s = make_source(pg)
    v1 = make_document(pg, s, text_sha256="t1")
    add_chunk(pg, v1)
    promote(pg, v1)
    v2 = make_document(pg, s, text_sha256="t2")
    add_chunk(pg, v2)  # loaded, not yet promoted
    vec, kw = search_ids(pg)
    assert vec == {v1} and kw == {v1}


def test_search_returns_source_fields_and_scopes(pg):
    a = make_source(pg, title="A")
    pg.execute("insert into source_scopes values (%s, 'X'), (%s, 'Y')", (a, a))
    b = make_source(pg, title="B")
    for s in (a, b):
        d = make_document(pg, s, text_sha256="t-" + s)
        add_chunk(pg, d)
        promote(pg, d)
    for fn, arg in (("match_document_chunks", f"'{VEC}'::vector"),
                    ("keyword_search_chunks", "'Steuerdraht'")):
        cur = pg.execute(f"select * from {fn}({arg}, 40)")
        cols = [c.name for c in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        for col in ("id", "document_id", "source_id", "content", "section_title", "page_number",
                    "chunk_index", "level", "authority_rank", "scopes", "token_count",
                    "document_title"):
            assert col in cols, (fn, col)
        by_source = {str(r["source_id"]): r for r in rows}
        assert sorted(by_source[a]["scopes"]) == ["X", "Y"]
        assert by_source[b]["scopes"] == []
        assert by_source[a]["level"] == "operator"
        assert by_source[a]["authority_rank"] == 2


# --- log_answer --------------------------------------------------------------

def test_log_answer_dedupes_versions(pg):
    s1, s2 = make_source(pg, title="A"), make_source(pg, title="B")
    d1 = make_document(pg, s1, status="current")
    d2 = make_document(pg, s2, status="current")
    log = {"question": "q", "detected_filters": {}, "retrieved_chunks": [], "reranked_chunks": [],
           "llm_prompt": "p", "llm_response": "r", "formatted_answer": {}, "model_used": "m",
           "latency_ms": 12}
    ids = [d1, d1, d2, d1, d2, d2, d1, d1]
    log_id = pg.execute("select log_answer(%s::jsonb, %s::uuid[])", (json.dumps(log), ids)).fetchone()[0]
    rows = pg.execute(
        "select document_id from query_log_documents where query_log_id = %s", (log_id,)
    ).fetchall()
    assert {str(r[0]) for r in rows} == {d1, d2}
    stored = pg.execute("select question, latency_ms from query_logs where id = %s", (log_id,)).fetchone()
    assert stored == ("q", 12)
