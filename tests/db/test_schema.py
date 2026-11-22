"""Constraints and triggers of supabase/schema.sql, on a real Postgres."""
from __future__ import annotations

import pytest

from tests.db.conftest import make_version, make_flag, make_source

psycopg = pytest.importorskip("psycopg")
from psycopg import errors

TABLES = {
    "sources", "source_scopes", "versions", "chunks", "flags",
    "answers", "answer_versions", "eval_questions", "eval_runs",
}


def test_schema_applies(pg):
    rows = pg.execute(
        "select table_name from information_schema.tables where table_schema = 'public'"
    ).fetchall()
    names = {r[0] for r in rows}
    assert TABLES <= names
    assert not names & {"hierarchy_rules", "documents", "document_chunks", "query_logs",
                        "query_log_documents"}


def test_second_current_rejected(pg):
    s = make_source(pg)
    make_version(pg, s, status="current")
    with pytest.raises(errors.UniqueViolation):
        make_version(pg, s, status="current")


def test_same_text_twice_rejected(pg):
    s = make_source(pg)
    make_version(pg, s, text_sha256="t1")
    with pytest.raises(errors.UniqueViolation):
        make_version(pg, s, text_sha256="t1")


def test_current_requires_completed(pg):
    s = make_source(pg)
    with pytest.raises(errors.CheckViolation):
        make_version(pg, s, status="current", ingestion_status="pending")


def test_pending_requires_flag(pg):
    s = make_source(pg)
    with pytest.raises(errors.CheckViolation):
        pg.execute(
            "insert into versions (source_id, status, title, file_sha256) "
            "values (%s, 'pending', 'Doc', 'f')",
            (s,),
        )


def test_retired_requires_date(pg):
    s = make_source(pg)
    with pytest.raises(errors.CheckViolation):
        make_version(pg, s, status="retired")


def test_current_rejects_retired_date(pg):
    s = make_source(pg)
    with pytest.raises(errors.CheckViolation):
        make_version(pg, s, status="current", retired_at="2026-01-01")


def test_file_fingerprint_immutable(pg):
    d = make_version(pg, make_source(pg))
    with pytest.raises(errors.CheckViolation):
        pg.execute("update versions set file_sha256 = 'other' where id = %s", (d,))


def test_text_fingerprint_set_once(pg):
    d = make_version(pg, make_source(pg))
    pg.execute("update versions set text_sha256 = 't1' where id = %s", (d,))
    with pytest.raises(errors.CheckViolation):
        pg.execute("update versions set text_sha256 = 't2' where id = %s", (d,))


def test_flag_not_resolvable_while_pending(pg):
    s = make_source(pg)
    f = make_flag(pg, s)
    make_version(pg, s, flag_id=f)
    with pytest.raises(errors.CheckViolation):
        pg.execute("update flags set resolved_at = now() where id = %s", (f,))


def test_flag_resolvable_without_pending_document(pg):
    f = make_flag(pg, make_source(pg))
    pg.execute("update flags set resolved_at = now(), resolution = 'dismissed' where id = %s", (f,))


def test_used_version_not_deletable(pg):
    d = make_version(pg, make_source(pg), status="current")
    log = pg.execute(
        "insert into answers (question, llm_prompt, llm_response, model_used, latency_ms) "
        "values ('q', 'p', 'r', 'm', 1) returning id"
    ).fetchone()[0]
    pg.execute("insert into answer_versions (answer_id, version_id) values (%s, %s)", (log, d))
    with pytest.raises(errors.RestrictViolation):
        pg.execute("delete from versions where id = %s", (d,))


def test_scopes_many_per_source(pg):
    s = make_source(pg)
    pg.execute("insert into source_scopes (source_id, scope) values (%s, 'A'), (%s, 'B')", (s, s))
    n = pg.execute("select count(*) from source_scopes where source_id = %s", (s,)).fetchone()[0]
    assert n == 2


def _resolved_flag(conn, source_id):
    f = make_flag(conn, source_id)
    conn.execute("update flags set resolved_at = now(), resolution = 'done' where id = %s", (f,))
    return f


def test_pending_rejects_resolved_flag(pg):
    s = make_source(pg)
    with pytest.raises(errors.CheckViolation):
        make_version(pg, s, flag_id=_resolved_flag(pg, s))


def test_pending_rejects_other_sources_flag(pg):
    s, other = make_source(pg, title="A"), make_source(pg, title="B")
    with pytest.raises(errors.CheckViolation):
        make_version(pg, s, flag_id=make_flag(pg, other))


def test_reinstating_to_pending_needs_an_open_flag(pg):
    s = make_source(pg)
    d = make_version(pg, s, status="retired", retired_at="2026-01-01", text_sha256="t1")
    with pytest.raises(errors.CheckViolation):
        pg.execute(
            "update versions set status = 'pending', retired_at = null, flag_id = %s where id = %s",
            (_resolved_flag(pg, s), d),
        )


def test_reinstating_to_pending_with_open_flag_succeeds(pg):
    s = make_source(pg)
    d = make_version(pg, s, status="retired", retired_at="2026-01-01", text_sha256="t1")
    pg.execute(
        "update versions set status = 'pending', retired_at = null, flag_id = %s where id = %s",
        (make_flag(pg, s), d),
    )
