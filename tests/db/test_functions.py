"""log_answer and current-only search, on a real Postgres. Lifecycle functions: test_lifecycle.py."""
from __future__ import annotations

import json

import pytest

from tests.db.conftest import make_reference_rows, make_source, make_version

psycopg = pytest.importorskip("psycopg")
from psycopg import errors

VEC = "[" + ",".join(["1"] + ["0"] * 1535) + "]"


def add_chunk(conn, doc_id: str, content: str = "Steuerdraht fuer Doppeltarif") -> str:
    return str(conn.execute(
        "insert into chunks (version_id, content, section_title, page_number, "
        "chunk_index, embedding, token_count) values (%s, %s, 'S', 1, 0, %s::vector, 5) returning id",
        (doc_id, content, VEC),
    ).fetchone()[0])


def chunk_count(conn, doc_id: str) -> int:
    return conn.execute(
        "select count(*) from chunks where version_id = %s", (doc_id,)
    ).fetchone()[0]


def doc(conn, doc_id: str) -> dict:
    cur = conn.execute("select * from versions where id = %s", (doc_id,))
    cols = [c.name for c in cur.description]
    return dict(zip(cols, cur.fetchone()))


def flag_of(conn, doc_id: str) -> dict:
    row = conn.execute(
        "select f.resolved_at, f.resolution from flags f join versions d on d.flag_id = f.id "
        "where d.id = %s", (doc_id,)
    ).fetchone()
    return {"resolved_at": row[0], "resolution": row[1]}


def promote(conn, version_id: str) -> int:
    """Promote as the routine load does; returns how many answers saw the retired version."""
    return conn.execute("select promote_version(%s)", (version_id,)).fetchone()[0]


def search_ids(conn) -> set:
    return {str(r[0]) for r in conn.execute(
        "select version_id from match_chunks(%s::vector, 40)", (VEC,)).fetchall()}


# --- search ----------------------------------------------------------------

def test_search_excludes_retired(pg):
    s = make_source(pg)
    v1 = make_version(pg, s, text_sha256="t1")
    add_chunk(pg, v1)
    promote(pg, v1)
    v2 = make_version(pg, s, text_sha256="t2")
    add_chunk(pg, v2)
    promote(pg, v2)
    assert search_ids(pg) == {v2}


def test_search_excludes_pending(pg):
    s = make_source(pg)
    v1 = make_version(pg, s, text_sha256="t1")
    add_chunk(pg, v1)
    promote(pg, v1)
    v2 = make_version(pg, s, text_sha256="t2")
    add_chunk(pg, v2)  # loaded, not yet promoted
    assert search_ids(pg) == {v1}


def test_search_returns_source_fields_and_scopes(pg):
    a = make_source(pg, key="a")
    pg.execute("insert into source_scopes (source_key, scope_key) values (%s, 'ekz')", (a,))
    b = make_source(pg, key="b", level="national")
    for s in (a, b):
        d = make_version(pg, s, text_sha256="t-" + s)
        add_chunk(pg, d)
        promote(pg, d)
    cur = pg.execute(f"select * from match_chunks('{VEC}'::vector, 40)")
    cols = [c.name for c in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    for col in ("id", "version_id", "source_key", "content", "section_title", "page_number",
                "chunk_index", "level", "rank", "scopes", "token_count",
                "version_title", "version_label"):
        assert col in cols, col
    by_source = {str(r["source_key"]): r for r in rows}
    assert sorted(by_source[a]["scopes"]) == ["bkw", "ekz"]
    assert by_source[b]["scopes"] == []
    assert (by_source[a]["level"], by_source[a]["rank"]) == ("operator", 2)
    assert (by_source[b]["level"], by_source[b]["rank"]) == ("national", 1)


# --- log_answer --------------------------------------------------------------

def test_log_answer_dedupes_versions(pg):
    s1, s2 = make_source(pg, key="a"), make_source(pg, key="b")
    d1 = make_version(pg, s1, status="current")
    d2 = make_version(pg, s2, status="current")
    log = {"question": "q", "detected_scope": None, "retrieved_chunks": [], "reranked_chunks": [],
           "llm_prompt": "p", "llm_response": "r", "formatted_answer": {}, "model_used": "m",
           "latency_ms": 12}
    ids = [d1, d1, d2, d1, d2, d2, d1, d1]
    answer_id = pg.execute("select log_answer(%s::jsonb, %s::uuid[])", (json.dumps(log), ids)).fetchone()[0]
    rows = pg.execute(
        "select version_id from answer_versions where answer_id = %s", (answer_id,)
    ).fetchall()
    assert {str(r[0]) for r in rows} == {d1, d2}
    stored = pg.execute("select question, latency_ms from answers where id = %s", (answer_id,)).fetchone()
    assert stored == ("q", 12)


def _answer(scope):
    return json.dumps({"question": "q", "llm_prompt": "p", "llm_response": "r",
                       "model_used": "m", "latency_ms": 1, "detected_scope": scope})


def test_detected_scope_is_stored(pg):
    make_reference_rows(pg)
    answer_id = pg.execute("select log_answer(%s::jsonb, '{}'::uuid[])", (_answer("bkw"),)).fetchone()[0]
    stored = pg.execute("select detected_scope from answers where id = %s", (answer_id,)).fetchone()[0]
    assert stored == "bkw"


def test_detected_scope_is_a_reference(pg):
    make_reference_rows(pg)
    with pytest.raises(errors.ForeignKeyViolation):
        pg.execute("select log_answer(%s::jsonb, '{}'::uuid[])", (_answer("x"),))


def test_answers_have_no_detected_filters(pg):
    cols = {r[0] for r in pg.execute(
        "select column_name from information_schema.columns where table_name = 'answers'")}
    assert "detected_scope" in cols and "detected_filters" not in cols



# --- answers_that_saw --------------------------------------------------------

def _log(conn, question, version_ids, at):
    answer_id = conn.execute("select log_answer(%s::jsonb, %s::uuid[])", (json.dumps(
        {"question": question, "llm_prompt": "p", "llm_response": "r", "model_used": "m", "latency_ms": 1}),
        version_ids)).fetchone()[0]
    conn.execute("update answers set created_at = %s where id = %s", (at, answer_id))
    return answer_id


def test_answers_that_saw_lists_answers_newest_first_with_the_other_versions(pg):
    a, b = make_source(pg, key="bkw-vorgaben"), make_source(pg, key="bkw-notfall")
    va = make_version(pg, a, status="current", version_label="V1.2")
    vb = make_version(pg, b, status="current")  # no label: shown by title
    other = make_version(pg, make_source(pg, key="unrelated"), status="current")
    older = _log(pg, "Q1", [va], "2026-11-01")
    newer = _log(pg, "Q2", [va, vb], "2026-11-20")
    _log(pg, "Q3", [other], "2026-11-21")

    rows = pg.execute("select * from answers_that_saw(%s)", (va,)).fetchall()

    assert [(r[0], r[2], r[3]) for r in rows] == [
        (newer, "Q2", ["bkw-notfall (Doc)"]),
        (older, "Q1", []),
    ]
    assert rows[0][1] > rows[1][1]


def test_answers_that_saw_an_unseen_version_is_empty(pg):
    v = make_version(pg, make_source(pg), status="current")
    assert pg.execute("select * from answers_that_saw(%s)", (v,)).fetchall() == []
