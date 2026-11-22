"""Only service_role can read or write the store; anon and authenticated cannot.

On Supabase, default privileges may grant anon and authenticated table access, so the
tests grant it here too and rely on row level security and function revokes to block them.
"""
from __future__ import annotations

import pytest

from tests.db.conftest import make_version, make_source
from tests.db.test_schema import TABLES

psycopg = pytest.importorskip("psycopg")
from psycopg import errors

WRITE_FUNCTIONS = {
    "promote_version": "select promote_version(gen_random_uuid(), 'x')",
    "reject_version": "select reject_version(gen_random_uuid(), 'x')",
    "log_answer": "select log_answer('{}'::jsonb, '{}'::uuid[])",
}


def _grant_like_supabase(conn, role):
    conn.execute(f"grant usage on schema public to {role}")
    conn.execute(f"grant select, insert, update, delete on all tables in schema public to {role}")


def test_rls_enabled_on_every_table(pg):
    rows = pg.execute(
        "select relname from pg_class c join pg_namespace n on n.oid = c.relnamespace "
        "where n.nspname = 'public' and c.relkind = 'r' and c.relrowsecurity"
    ).fetchall()
    assert {r[0] for r in rows} == TABLES


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_role_sees_no_rows(pg, role):
    s = make_source(pg)
    make_version(pg, s, status="current")
    _grant_like_supabase(pg, role)
    pg.execute(f"set local role {role}")
    for table in sorted(TABLES):
        assert pg.execute(f"select count(*) from {table}").fetchone()[0] == 0, table


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_role_cannot_insert(pg, role):
    _grant_like_supabase(pg, role)
    pg.execute(f"set local role {role}")
    with pytest.raises(errors.InsufficientPrivilege):
        pg.execute("insert into sources (title, issuer, level) values ('t', 'i', 'national')")


@pytest.mark.parametrize("role", ["anon", "authenticated"])
@pytest.mark.parametrize("fn", sorted(WRITE_FUNCTIONS))
def test_role_cannot_call_write_functions(pg, role, fn):
    _grant_like_supabase(pg, role)
    pg.execute(f"set local role {role}")
    with pytest.raises(errors.InsufficientPrivilege):
        pg.execute(WRITE_FUNCTIONS[fn])


def test_public_has_no_execute_on_write_functions(pg):
    for fn in WRITE_FUNCTIONS:
        ok = pg.execute(
            "select has_function_privilege('public', p.oid, 'execute') "
            "from pg_proc p where p.proname = %s", (fn,)
        ).fetchone()[0]
        assert ok is False, fn


def test_service_role_reads_and_writes(pg):
    s = make_source(pg)
    d = make_version(pg, s, text_sha256="t1")
    pg.execute("set local role service_role")
    assert pg.execute("select count(*) from sources").fetchone()[0] >= 1
    pg.execute("select promote_version(%s, 'promoted (auto)')", (d,))
    answer_id = pg.execute("select log_answer(%s::jsonb, %s::uuid[])",
                        ('{"question":"q","llm_prompt":"p","llm_response":"r","model_used":"m","latency_ms":1}', [d])
                        ).fetchone()[0]
    assert answer_id is not None
