"""Fixtures for tests against a real Postgres with pgvector.

Set TEST_DATABASE_URL to an admin connection (e.g. postgresql://localhost/postgres).
When it is unset, every test that uses these fixtures is skipped.
Each session creates a fresh database, applies supabase/schema.sql unchanged, and drops it.
"""
from __future__ import annotations

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

def make_source(conn, title: str = "Source", address: str | None = None) -> str:
    return str(conn.execute(
        "insert into sources (title, issuer, level, authority_rank, address) "
        "values (%s, 'Issuer', 'operator', 2, %s) returning id",
        (title, address),
    ).fetchone()[0])


def make_flag(conn, source_id: str, kind: str = "new_version") -> str:
    return str(conn.execute(
        "insert into flags (source_id, kind) values (%s, %s) returning id",
        (source_id, kind),
    ).fetchone()[0])


def make_document(
    conn,
    source_id: str,
    status: str = "pending",
    flag_id: str | None = None,
    text_sha256: str | None = None,
    file_sha256: str | None = None,
    ingestion_status: str = "completed",
    retired_at: str | None = None,
    address: str | None = None,
) -> str:
    if status == "pending" and flag_id is None:
        flag_id = make_flag(conn, source_id)
    return str(conn.execute(
        "insert into documents (source_id, status, flag_id, title, address, file_sha256, "
        "text_sha256, ingestion_status, retired_at) "
        "values (%s, %s, %s, 'Doc', %s, %s, %s, %s, %s) returning id",
        (source_id, status, flag_id, address, file_sha256 or uuid.uuid4().hex,
         text_sha256, ingestion_status, retired_at),
    ).fetchone()[0])
