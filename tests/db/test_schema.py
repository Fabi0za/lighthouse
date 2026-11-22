"""Constraints and triggers of supabase/schema.sql, on a real Postgres."""
from __future__ import annotations

import pytest

from tests.db.conftest import make_flag, make_reference_rows, make_source, make_version

psycopg = pytest.importorskip("psycopg")
from psycopg import errors

TABLES = {
    "levels", "scopes", "sources", "source_scopes", "versions", "chunks", "flags",
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
            "insert into versions (source_key, status, title, file_sha256) "
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
    pg.execute("insert into source_scopes (source_key, scope_key) values (%s, 'ekz')", (s,))
    n = pg.execute("select count(*) from source_scopes where source_key = %s", (s,)).fetchone()[0]
    assert n == 2


def _resolved_flag(conn, source_key):
    f = make_flag(conn, source_key)
    conn.execute("update flags set resolved_at = now(), resolution = 'done' where id = %s", (f,))
    return f


def test_pending_rejects_resolved_flag(pg):
    s = make_source(pg)
    with pytest.raises(errors.CheckViolation):
        make_version(pg, s, flag_id=_resolved_flag(pg, s))


def test_pending_rejects_other_sources_flag(pg):
    s, other = make_source(pg, key="a"), make_source(pg, key="b")
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


# --- levels and scopes -------------------------------------------------------

def test_level_must_exist(pg):
    make_reference_rows(pg)
    with pytest.raises(errors.ForeignKeyViolation):
        pg.execute("insert into sources (key, level) values ('t', 'x')")


def test_scope_must_exist(pg):
    s = make_source(pg)
    with pytest.raises(errors.ForeignKeyViolation):
        pg.execute("insert into source_scopes (source_key, scope_key) values (%s, 'x')", (s,))


def test_rank_unique(pg):
    make_reference_rows(pg)
    with pytest.raises(errors.UniqueViolation):
        pg.execute("insert into levels (key, rank) values ('other', 1)")


def test_rank_direction_is_stated(pg):
    comment = pg.execute(
        "select col_description('levels'::regclass, attnum) from pg_attribute "
        "where attrelid = 'levels'::regclass and attname = 'rank'"
    ).fetchone()[0]
    assert "Higher rank wins" in comment


@pytest.mark.parametrize("key", ["BKW", "b k w", "bkw_", "-bkw"])
def test_scope_key_format(pg, key):
    with pytest.raises(errors.CheckViolation):
        pg.execute("insert into scopes (key, name) values (%s, 'n')", (key,))


# --- source keys -------------------------------------------------------------

@pytest.mark.parametrize("key", ["BKW Vorgaben", "bkw_vorgaben", "bkw--vorgaben", "-bkw", "bkw-"])
def test_source_key_format_rejected(pg, key):
    make_reference_rows(pg)
    with pytest.raises(errors.CheckViolation):
        pg.execute("insert into sources (key, level) values (%s, 'national')", (key,))


def test_source_key_format_accepted(pg):
    make_reference_rows(pg)
    pg.execute("insert into sources (key, level) values ('bkw-vorgaben-niederspannung', 'national')")


def test_source_key_immutable(pg):
    s = make_source(pg, level="national")
    with pytest.raises(errors.CheckViolation):
        pg.execute("update sources set key = 'other' where key = %s", (s,))


def _save(conn, key, level, scopes):
    conn.execute("select save_source(%s, %s, %s::text[])", (key, level, scopes))


def _scopes(conn, key):
    return sorted(r[0] for r in conn.execute(
        "select scope_key from source_scopes where source_key = %s", (key,)))


def test_operator_source_needs_scope(pg_db_url):
    with psycopg.connect(pg_db_url) as conn:
        make_reference_rows(conn)
        conn.commit()
        _save(conn, "s", "operator", [])
        with pytest.raises(errors.CheckViolation):
            conn.commit()


def test_removing_last_scope_of_operator_source_fails(pg_db_url):
    with psycopg.connect(pg_db_url) as conn:
        make_reference_rows(conn)
        _save(conn, "s", "operator", ["bkw"])
        conn.commit()
        conn.execute("delete from source_scopes where source_key = 's'")
        with pytest.raises(errors.CheckViolation):
            conn.commit()


def test_national_source_without_scope(pg_db_url):
    with psycopg.connect(pg_db_url) as conn:
        make_reference_rows(conn)
        _save(conn, "n", "national", [])
        conn.commit()


def test_save_source_replaces_scopes_and_level(pg):
    make_reference_rows(pg)
    _save(pg, "s", "operator", ["bkw"])
    _save(pg, "s", "operator", ["ekz"])
    assert _scopes(pg, "s") == ["ekz"]
    _save(pg, "s", "national", [])
    assert _scopes(pg, "s") == []
    assert pg.execute("select level from sources where key = 's'").fetchone()[0] == "national"

