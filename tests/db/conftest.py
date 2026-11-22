"""Fixtures for tests against a real Postgres with pgvector.

Set TEST_DATABASE_URL to an admin connection (e.g. postgresql://localhost/postgres).
When it is unset, every test that uses these fixtures is skipped.
Each session creates a fresh database, applies supabase/schema.sql unchanged, and drops it.
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest

psycopg = pytest.importorskip("psycopg")

SCHEMA = Path(__file__).resolve().parents[2] / "supabase" / "schema.sql"
ADMIN_URL = os.environ.get("TEST_DATABASE_URL")


def _with_db(url: str, dbname: str) -> str:
    base, _, _ = url.rpartition("/")
    return f"{base}/{dbname}"


def _create_database() -> tuple[str, str]:
    name = f"lighthouse_test_{os.getpid()}_{uuid.uuid4().hex[:6]}"
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'create database "{name}"')
    url = _with_db(ADMIN_URL, name)
    with psycopg.connect(url, autocommit=True) as conn:
        # Roles Supabase provides. service_role bypasses row level security there;
        # anon and authenticated do not.
        for role in ("service_role", "anon", "authenticated"):
            conn.execute(
                f"do $$ begin create role {role} nologin; "
                "exception when duplicate_object then null; end $$;"
            )
        conn.execute("alter role service_role bypassrls")
        conn.execute(SCHEMA.read_text(encoding="utf-8"))
    return name, url


def _drop_database(name: str) -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'drop database if exists "{name}" with (force)')


@pytest.fixture(scope="session")
def _session_db():
    if not ADMIN_URL:
        pytest.skip("TEST_DATABASE_URL not set")
    name, url = _create_database()
    yield url
    _drop_database(name)


@pytest.fixture
def pg(_session_db):
    """A connection inside a transaction that is rolled back after the test."""
    with psycopg.connect(_session_db) as conn:
        yield conn
        conn.rollback()


@pytest.fixture
def pg_db_url():
    """A fresh database with the schema applied, for tests that must commit."""
    if not ADMIN_URL:
        pytest.skip("TEST_DATABASE_URL not set")
    name, url = _create_database()
    yield url
    _drop_database(name)


# --- row helpers -------------------------------------------------------------

def make_reference_rows(conn) -> None:
    """Levels national (rank 1) and operator (rank 2, needs a scope); scopes bkw, ekz;
    indexing settings test-a and test-b; answer settings test-answers."""
    conn.execute(
        "insert into levels (key, rank, requires_scope) values "
        "('national', 1, false), ('operator', 2, true) on conflict do nothing"
    )
    conn.execute(
        "insert into scopes (key, name) values ('bkw', 'BKW Energie AG'), "
        "('ekz', 'Elektrizitätswerke des Kantons Zürich') on conflict do nothing"
    )
    conn.execute(
        "insert into indexing_settings (key, embedding_model, dimensions, chunk_size, chunk_overlap, "
        "chunker_version, fingerprint_rule) values ('test-a', 'm', 1536, 500, 50, 1, 1), "
        "('test-b', 'm', 1536, 400, 50, 1, 1) "
        "on conflict do nothing"
    )
    conn.execute(
        "insert into answer_settings (key, retrieval_top_k, rerank_top_n, rerank_model, answer_model, "
        "prompt_version) values ('test-answers', 40, 8, 'r', 'a', 1) on conflict do nothing"
    )


def answer_json(**over) -> str:
    """An answer as log_answer takes it, under the test settings."""
    answer = {"question": "q", "llm_prompt": "p", "llm_response": "r", "latency_ms": 1,
              "indexing_settings_key": "test-a", "answer_settings_key": "test-answers"}
    return json.dumps({**answer, **over})


def make_source(conn, key: str = "source", watch_address: str | None = None,
                level: str = "operator") -> str:
    """A source; an operator-level source gets scope bkw so it passes the scope rule."""
    make_reference_rows(conn)
    conn.execute("insert into sources (key, level, watch_address) values (%s, %s, %s)",
                 (key, level, watch_address))
    if level == "operator":
        conn.execute("insert into source_scopes (source_key, scope_key) values (%s, 'bkw')", (key,))
    return key


def make_flag(conn, source_key: str, kind: str = "candidate", reason: str = "possible_successor",
              detail: str = '{"address": "https://example.org/x.pdf"}') -> int:
    return conn.execute(
        "insert into flags (source_key, kind, reason, detail) values (%s, %s, %s, %s::jsonb) returning id",
        (source_key, kind, reason, detail),
    ).fetchone()[0]


def resolve_flag(conn, flag_id: int, resolution: str = "rejected", resolved_by: str = "person") -> None:
    conn.execute(
        "update flags set resolved_at = now(), resolution = %s, resolved_by = %s where id = %s",
        (resolution, resolved_by, flag_id),
    )


def make_version(
    conn,
    source_key: str,
    status: str = "loading",
    flag_id: int | None = None,
    text_sha256: str | None = None,
    file_sha256: str | None = None,
    retired_at: str | None = None,
    obtained_from: str | None = None,
    version_label: str | None = None,
    page_limit: int | None = None,
    indexing_settings_key: str = "test-a",
) -> str:
    """A version; held gets an open candidate flag and failed a load_failed flag unless flag_id is given.
    Held, current and retired versions get a fingerprint unless text_sha256 is given."""
    if text_sha256 is None and status in ("held", "current", "retired"):
        text_sha256 = uuid.uuid4().hex
    if flag_id is None and status == "held":
        flag_id = make_flag(conn, source_key)
    if flag_id is None and status == "failed":
        flag_id = make_flag(conn, source_key, "check_failed", "load_failed", '{"file": "data/a.pdf"}')
    return str(conn.execute(
        "insert into versions (source_key, status, flag_id, title, version_label, obtained_from, "
        "page_limit, file_sha256, text_sha256, retired_at, indexing_settings_key) "
        "values (%s, %s, %s, 'Doc', %s, %s, %s, %s, %s, %s, %s) returning id",
        (source_key, status, flag_id, version_label, obtained_from, page_limit,
         file_sha256 or uuid.uuid4().hex, text_sha256, retired_at, indexing_settings_key),
    ).fetchone()[0])
