"""Only service_role can read or write the store; anon and authenticated cannot.

On Supabase, default privileges may grant anon and authenticated table access, so the
tests grant it here too and rely on row level security and function revokes to block them.
"""
from __future__ import annotations

import pytest

from tests.db.conftest import answer_json, make_source, make_version
from tests.db.test_schema import TABLES

psycopg = pytest.importorskip("psycopg")
from psycopg import errors

WRITE_FUNCTIONS = {
    "begin_load": "select begin_load('s', 't', null, null, null, 'f', 'k')",
    "fail_load": "select fail_load(gen_random_uuid(), 'load_failed', 'f', null)",
    "discard_version": "select discard_version(gen_random_uuid())",
    "promote_version": "select promote_version(gen_random_uuid())",
    "reject_version": "select reject_version(gen_random_uuid())",
    "log_answer": "select log_answer('{}'::jsonb, '{}'::uuid[])",
    "save_source": "select save_source('s', 'national', '{}'::text[], null)",
    "record_eval_run": "select record_eval_run('{}'::jsonb)",
    "save_eval_question": "select save_eval_question('{}'::jsonb)",
    "hold_candidate": "select hold_candidate(gen_random_uuid(), 'u', null)",
    "approve_candidate": "select approve_candidate(gen_random_uuid())",
    "raise_check_failed": "select raise_check_failed('s', 'u', null)",
    "resolve_overdue": "select resolve_overdue('s')",
    "confirm_source": "select confirm_source('s')",
    "raise_overdue_flags": "select raise_overdue_flags(interval '1 day')",
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
        pg.execute("insert into sources (key, level) values ('t', 'national')")


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
    pg.execute("select promote_version(%s)", (d,))
    answer_id = pg.execute("select log_answer(%s::jsonb, %s::uuid[])",
                        (answer_json(), [d])
                        ).fetchone()[0]
    assert answer_id is not None


VIEWS = {"eval_questions_to_review", "eval_run_scores"}


def test_views_run_with_the_callers_rights(pg):
    rows = pg.execute(
        "select c.relname, c.reloptions from pg_class c join pg_namespace n on n.oid = c.relnamespace "
        "where n.nspname = 'public' and c.relkind = 'v'").fetchall()
    assert {r[0] for r in rows} == VIEWS
    for name, options in rows:
        assert "security_invoker=true" in (options or []), name


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_role_sees_no_rows_through_views(pg, role):
    from tests.db.conftest import make_source, make_version
    s = make_source(pg)
    make_version(pg, s, status="retired", retired_at="2026-01-01", text_sha256="t12")
    pg.execute("insert into eval_questions values ('q', 'Q?', 'answerable', 'standard', null)")
    pg.execute("insert into eval_question_sources values ('q', %s, 't12')", (s,))
    _grant_like_supabase(pg, role)
    pg.execute(f"set local role {role}")
    for view in sorted(VIEWS):
        assert pg.execute(f"select count(*) from {view}").fetchone()[0] == 0, view


def test_service_role_raises_flags_and_reads_views(pg):
    from tests.db.conftest import make_reference_rows, make_source
    make_reference_rows(pg)
    s = make_source(pg)
    pg.execute("set local role service_role")
    v = pg.execute("select begin_load(%s, 'Doc', null, null, null, 'f1', 'test-a')", (s,)).fetchone()[0]
    number = pg.execute("select fail_load(%s, 'load_failed', 'data/a.pdf', 'boom')", (v,)).fetchone()[0]
    assert isinstance(number, int)  # the identity column works for service_role
    for view in sorted(VIEWS):
        pg.execute(f"select count(*) from {view}")


PUBLIC_ROLE_CHECK = """
    select r.rolname, p.proname
    from pg_proc p join pg_namespace n on n.oid = p.pronamespace
    cross join (select rolname from pg_roles where rolname in ('anon', 'authenticated')) r
    where n.nspname = 'public' and p.prokind = 'f'
      and not exists (select 1 from pg_depend d where d.objid = p.oid and d.deptype = 'e')
      and has_function_privilege(r.rolname, p.oid, 'execute')
    order by 1, 2
"""


def test_no_function_executable_by_anon_or_authenticated(pg):
    assert pg.execute(PUBLIC_ROLE_CHECK).fetchall() == []


def test_service_role_executes_every_function(pg):
    missing = pg.execute(
        "select p.proname from pg_proc p join pg_namespace n on n.oid = p.pronamespace "
        "where n.nspname = 'public' and p.prokind = 'f' "
        "and not exists (select 1 from pg_depend d where d.objid = p.oid and d.deptype = 'e') "
        "and not has_function_privilege('service_role', p.oid, 'execute')").fetchall()
    assert missing == []
