"""load_version against a real Postgres, through a psycopg stand-in for DatabaseClient.

The stand-in calls the same SQL functions as DatabaseClient, one committed call each as over
REST, so every rule of the schema applies: statuses, flags, the unique text fingerprint.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pypdf import PdfWriter

from app.ingestion.chunker import Chunk
from app.ingestion.versions import load_version
from tests.db.conftest import make_reference_rows

psycopg = pytest.importorskip("psycopg")
from psycopg.rows import dict_row

VEC = [1.0] + [0.0] * 1535
SECTIONS = [{"title": "S", "content": "Steuerdraht 2 ist optional", "page": 1}]


class PgDb:
    def __init__(self, conn):
        self.c = conn

    def _call(self, sql, args=()):
        try:
            row = self.c.execute(sql, args).fetchone()
        except Exception:
            self.c.rollback()  # each client call is its own transaction, as over REST
            raise
        self.c.commit()
        return row

    def list_versions(self, source_key):
        return self.c.execute("select * from versions where source_key = %s", (source_key,)).fetchall()

    def begin_load(self, source_key, title, version_label, obtained_from, page_limit, file_sha256):
        return str(self._call("select begin_load(%s, %s, %s, %s, %s, %s) as id",
                              (source_key, title, version_label, obtained_from, page_limit, file_sha256))["id"])

    def fail_load(self, version_id, reason, file, message):
        return self._call("select fail_load(%s, %s, %s, %s) as id", (version_id, reason, file, message))["id"]

    def discard_version(self, version_id):
        self._call("select discard_version(%s)", (version_id,))

    def set_text_fingerprint(self, version_id, text_sha256, parsed_output):
        self._call("update versions set text_sha256 = %s, parsed_output = %s where id = %s returning id",
                   (text_sha256, json.dumps(parsed_output), version_id))

    def insert_chunks(self, chunks):
        for ch in chunks:
            self.c.execute(
                "insert into chunks (version_id, content, section_title, page_number, chunk_index, "
                "embedding, token_count) values (%s, %s, %s, %s, %s, %s::vector, %s)",
                (ch["version_id"], ch["content"], ch["section_title"], ch["page_number"],
                 ch["chunk_index"], str(ch["embedding"]), ch["token_count"]))
        self.c.commit()

    def promote_version(self, version_id, resolved_by="system"):
        return self._call("select promote_version(%s, %s) as n", (version_id, resolved_by))["n"]


def _pdf(path: Path, height: int) -> Path:
    w = PdfWriter()
    w.add_blank_page(width=200, height=height)
    with open(path, "wb") as f:
        w.write(f)
    return path


def _deps(fail_embedding: bool = False, fail_parse: bool = False):
    parser = MagicMock()
    parser.parse_pdf = AsyncMock(side_effect=TimeoutError("parser timed out")) if fail_parse \
        else AsyncMock(return_value=({"result": {}}, SECTIONS))
    chunker = MagicMock()
    chunker.chunk_sections.return_value = [
        Chunk(content="c", section_title="S", page_number=1, chunk_index=0, token_count=3)]
    embedder = MagicMock()
    embedder.embed_texts = AsyncMock(side_effect=RuntimeError("rate limit")) if fail_embedding \
        else AsyncMock(return_value=[VEC])
    return parser, chunker, embedder


def _statuses(conn, source_key):
    return sorted(r["status"] for r in conn.execute(
        "select status from versions where source_key = %s", (source_key,)).fetchall())


def _flags(conn, source_key):
    return conn.execute("select * from flags where source_key = %s order by id", (source_key,)).fetchall()


@pytest.fixture
def db(pg_db_url):
    with psycopg.connect(pg_db_url, row_factory=dict_row) as conn:
        yield PgDb(conn)


@pytest.fixture
def source(db):
    make_reference_rows(db.c)
    db.c.execute("insert into sources (key, level) values ('s', 'operator')")
    db.c.execute("insert into source_scopes (source_key, scope_key) values ('s', 'bkw')")
    db.c.commit()
    return "s"


async def test_routine_load_raises_no_flag(db, source, tmp_path):
    action, _ = await load_version(db, source, _pdf(tmp_path / "a.pdf", 200), "Doc", None, *_deps())
    assert action == "promoted"
    assert _statuses(db.c, source) == ["current"]
    assert _flags(db.c, source) == []


async def test_repackaged_file_leaves_no_row_and_no_flag(db, source, tmp_path):
    await load_version(db, source, _pdf(tmp_path / "a.pdf", 200), "Doc", None, *_deps())
    action, _ = await load_version(db, source, _pdf(tmp_path / "b.pdf", 300), "Doc", None, *_deps())
    assert action == "dismissed"
    assert _statuses(db.c, source) == ["current"]
    assert _flags(db.c, source) == []


async def test_failed_parse_raises_parse_failed(db, source, tmp_path):
    with pytest.raises(TimeoutError):
        await load_version(db, source, _pdf(tmp_path / "a.pdf", 200), "Doc", None,
                           *_deps(fail_parse=True), listed_path="data/a.pdf")
    assert _statuses(db.c, source) == ["failed"]
    (flag,) = _flags(db.c, source)
    assert (flag["kind"], flag["reason"], flag["resolved_at"]) == ("check_failed", "parse_failed", None)
    assert flag["detail"] == {"file": "data/a.pdf", "message": "TimeoutError: parser timed out"}


async def test_failed_embedding_raises_load_failed_then_retry_fixes_it(db, source, tmp_path):
    f = _pdf(tmp_path / "v1.pdf", 200)
    with pytest.raises(RuntimeError):
        await load_version(db, source, f, "Doc", None, *_deps(fail_embedding=True))
    assert _statuses(db.c, source) == ["failed"]
    assert [x["reason"] for x in _flags(db.c, source)] == ["load_failed"]

    action, _ = await load_version(db, source, f, "Doc", None, *_deps())

    assert action == "promoted"
    assert _statuses(db.c, source) == ["current"]
    (flag,) = _flags(db.c, source)
    assert (flag["resolution"], flag["resolved_by"]) == ("fixed", "system")


async def test_failed_version_replaced_by_other_bytes_with_same_text(db, source, tmp_path):
    with pytest.raises(RuntimeError):
        await load_version(db, source, _pdf(tmp_path / "a.pdf", 200), "Doc", None, *_deps(fail_embedding=True))

    action, _ = await load_version(db, source, _pdf(tmp_path / "b.pdf", 300), "Doc", None, *_deps())

    assert action == "promoted"
    assert _statuses(db.c, source) == ["current"]
    (flag,) = _flags(db.c, source)
    assert flag["resolution"] == "fixed"


async def test_crash_while_loading_is_resumed(db, source, tmp_path):
    f = _pdf(tmp_path / "a.pdf", 200)
    from app.ingestion.fingerprint import file_sha256
    db.begin_load(source, "Doc", None, None, None, file_sha256(f))  # then the process died

    action, _ = await load_version(db, source, f, "Doc", None, *_deps())

    assert action == "promoted"
    assert _statuses(db.c, source) == ["current"]
    assert _flags(db.c, source) == []
