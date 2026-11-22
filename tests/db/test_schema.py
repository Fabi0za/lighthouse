"""Constraints and triggers of supabase/schema.sql, on a real Postgres."""
from __future__ import annotations

import pytest

from tests.db.conftest import answer_json, make_flag, make_reference_rows, make_source, make_version, resolve_flag

psycopg = pytest.importorskip("psycopg")
from psycopg import errors

TABLES = {
    "levels", "scopes", "indexing_settings", "answer_settings", "sources", "source_scopes", "versions", "chunks", "flags",
    "answers", "answer_versions", "eval_questions", "eval_question_facts", "eval_question_sources", "eval_runs", "eval_results", "eval_fact_results",
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
    d = make_version(pg, make_source(pg), status="failed")
    pg.execute("update versions set text_sha256 = 't1' where id = %s", (d,))
    with pytest.raises(errors.CheckViolation):
        pg.execute("update versions set text_sha256 = 't2' where id = %s", (d,))


def test_used_version_not_deletable(pg):
    d = make_version(pg, make_source(pg), status="current")
    pg.execute("select log_answer(%s::jsonb, %s::uuid[])", (answer_json(), [d]))
    with pytest.raises(errors.RestrictViolation):
        pg.execute("delete from versions where id = %s", (d,))


def test_scopes_many_per_source(pg):
    s = make_source(pg)
    pg.execute("insert into source_scopes (source_key, scope_key) values (%s, 'ekz')", (s,))
    n = pg.execute("select count(*) from source_scopes where source_key = %s", (s,)).fetchone()[0]
    assert n == 2


def _resolved_flag(conn, source_key):
    f = make_flag(conn, source_key)
    resolve_flag(conn, f)
    return f


# --- version status ----------------------------------------------------------

@pytest.mark.parametrize("status", ["loading", "failed", "held", "current", "retired"])
def test_status_values(pg, status):
    make_version(pg, make_source(pg), status=status,
                 retired_at="2026-01-01" if status == "retired" else None)


def test_pending_is_no_status(pg):
    with pytest.raises(errors.CheckViolation):
        make_version(pg, make_source(pg), status="pending")


def test_loading_needs_no_flag(pg):
    make_version(pg, make_source(pg), status="loading")


def test_held_needs_a_flag(pg):
    s = make_source(pg)
    with pytest.raises(errors.CheckViolation):
        pg.execute("insert into versions (source_key, status, title, file_sha256, indexing_settings_key) "
                   "values (%s, 'held', 'D', 'f', 'test-a')",
                   (s,))


def test_held_rejects_resolved_flag(pg):
    s = make_source(pg)
    with pytest.raises(errors.CheckViolation):
        make_version(pg, s, status="held", flag_id=_resolved_flag(pg, s))


def test_held_rejects_other_sources_flag(pg):
    s, other = make_source(pg, key="a"), make_source(pg, key="b")
    with pytest.raises(errors.CheckViolation):
        make_version(pg, s, status="held", flag_id=make_flag(pg, other))


def test_held_rejects_check_failed_flag(pg):
    s = make_source(pg)
    f = make_flag(pg, s, "check_failed", "load_failed", '{"file": "data/a.pdf"}')
    with pytest.raises(errors.CheckViolation):
        make_version(pg, s, status="held", flag_id=f)


def test_failed_needs_a_check_failed_flag(pg):
    s = make_source(pg)
    with pytest.raises(errors.CheckViolation):
        make_version(pg, s, status="failed", flag_id=make_flag(pg, s))  # a candidate flag


def test_failed_keeps_its_flag_once_resolved(pg):
    s = make_source(pg)
    f = make_flag(pg, s, "check_failed", "load_failed", '{"file": "data/a.pdf"}')
    resolve_flag(pg, f, "fixed", "system")
    make_version(pg, s, status="failed", flag_id=f)


def test_versions_have_no_ingestion_status(pg):
    cols = {r[0] for r in pg.execute(
        "select column_name from information_schema.columns where table_name = 'versions'")}
    assert "ingestion_status" not in cols


def test_reinstating_to_held_needs_an_open_flag(pg):
    s = make_source(pg)
    d = make_version(pg, s, status="retired", retired_at="2026-01-01", text_sha256="t1")
    with pytest.raises(errors.CheckViolation):
        pg.execute(
            "update versions set status = 'held', retired_at = null, flag_id = %s where id = %s",
            (_resolved_flag(pg, s), d),
        )


def test_reinstating_to_held_with_open_flag_succeeds(pg):
    s = make_source(pg)
    d = make_version(pg, s, status="retired", retired_at="2026-01-01", text_sha256="t1")
    pg.execute(
        "update versions set status = 'held', retired_at = null, flag_id = %s where id = %s",
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


def _save(conn, key, level, scopes, watch_address=None):
    conn.execute("select save_source(%s, %s, %s::text[], %s)", (key, level, scopes, watch_address))


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


# --- watch address and confirmation ------------------------------------------

def _confirmed(conn, key):
    return conn.execute("select confirmed_at from sources where key = %s", (key,)).fetchone()[0]


def test_new_source_is_confirmed(pg):
    make_reference_rows(pg)
    _save(pg, "n", "national", [], "https://example.org/n.pdf")
    assert _confirmed(pg, "n") is not None


def test_same_address_keeps_confirmation(pg_db_url):
    with psycopg.connect(pg_db_url) as conn:
        make_reference_rows(conn)
        _save(conn, "n", "national", [], "https://example.org/n.pdf")
        conn.commit()
        first = _confirmed(conn, "n")
        conn.commit()
        _save(conn, "n", "national", [], "https://example.org/n.pdf")
        conn.commit()
        assert _confirmed(conn, "n") == first


def test_new_address_reconfirms(pg_db_url):
    with psycopg.connect(pg_db_url) as conn:
        make_reference_rows(conn)
        _save(conn, "n", "national", [], "https://example.org/old.pdf")
        conn.commit()
        first = _confirmed(conn, "n")
        conn.commit()
        _save(conn, "n", "national", [], "https://example.org/new.pdf")
        conn.commit()
        assert _confirmed(conn, "n") > first
        assert conn.execute("select watch_address from sources where key = 'n'").fetchone()[0] \
            == "https://example.org/new.pdf"


def test_obtained_from_immutable(pg):
    d = make_version(pg, make_source(pg), obtained_from="https://example.org/a.pdf")
    with pytest.raises(errors.CheckViolation):
        pg.execute("update versions set obtained_from = 'https://example.org/b.pdf' where id = %s", (d,))


def test_sources_have_no_listing_address(pg):
    cols = {r[0] for r in pg.execute(
        "select column_name from information_schema.columns where table_name = 'sources'")}
    assert "watch_address" in cols and not cols & {"address", "listing_address", "title", "issuer"}


# --- version label and page limit --------------------------------------------

def test_page_limit_positive(pg):
    with pytest.raises(errors.CheckViolation):
        make_version(pg, make_source(pg), page_limit=0)


@pytest.mark.parametrize("column, value", [("version_label", "'V2'"), ("page_limit", "5")])
def test_label_and_page_limit_immutable(pg, column, value):
    d = make_version(pg, make_source(pg), version_label="V1", page_limit=4)
    with pytest.raises(errors.CheckViolation):
        pg.execute(f"update versions set {column} = {value} where id = %s", (d,))


def test_versions_have_no_file_path(pg):
    cols = {r[0] for r in pg.execute(
        "select column_name from information_schema.columns where table_name = 'versions'")}
    assert {"version_label", "page_limit", "obtained_from"} <= cols and "file_path" not in cols


# --- chunks ------------------------------------------------------------------

VEC = "[" + ",".join(["1"] + ["0"] * 1535) + "]"


def _chunk(conn, version_id, chunk_index=0, embedding=VEC, section_title="S"):
    conn.execute(
        "insert into chunks (version_id, content, section_title, page_number, chunk_index, embedding) "
        "values (%s, 'c', %s, 1, %s, %s::vector)", (version_id, section_title, chunk_index, embedding))


def test_chunk_index_unique_per_version(pg):
    v = make_version(pg, make_source(pg))
    _chunk(pg, v, 0)
    with pytest.raises(errors.UniqueViolation):
        _chunk(pg, v, 0)


def test_embedding_required(pg):
    with pytest.raises(errors.NotNullViolation):
        _chunk(pg, make_version(pg, make_source(pg)), embedding=None)


def test_section_title_may_be_empty(pg):
    _chunk(pg, make_version(pg, make_source(pg)), section_title="")


def test_chunks_have_no_token_count(pg):
    cols = {r[0] for r in pg.execute(
        "select column_name from information_schema.columns where table_name = 'chunks'")}
    assert "token_count" not in cols
