"""load_version against real Postgres constraints, through a psycopg stand-in for DatabaseClient.

The stand-in issues the same writes as DatabaseClient (one statement per client call, each
committed), so the unique text fingerprint, the open-flag rule and promote_version all apply.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
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

    def _one(self, sql, args=()):
        try:
            row = self.c.execute(sql, args).fetchone()
        except Exception:
            self.c.rollback()  # each client call is its own transaction, as over REST
            raise
        self.c.commit()
        return row

    def list_versions(self, source_key):
        return self.c.execute("select * from versions where source_key = %s", (source_key,)).fetchall()

    def get_version(self, doc_id):
        return self.c.execute("select * from versions where id = %s", (doc_id,)).fetchone()

    def hold_version(self, source_key, title, version_label, obtained_from, page_limit, file_sha256,
                     kind="new_version"):
        flag = self._one("insert into flags (source_key, kind) values (%s, %s) returning id", (source_key, kind))
        return self._one(
            "insert into versions (source_key, status, flag_id, title, version_label, obtained_from, "
            "page_limit, file_sha256) values (%s, 'pending', %s, %s, %s, %s, %s, %s) returning *",
            (source_key, flag["id"], title, version_label, obtained_from, page_limit, file_sha256))

    def update_version(self, doc_id, updates):
        (k, v), = updates.items()
        self._one(f"update versions set {k} = %s where id = %s returning id", (v, doc_id))

    def set_text_fingerprint(self, doc_id, text_sha256, parsed_output):
        self._one("update versions set text_sha256 = %s, parsed_output = %s where id = %s returning id",
                  (text_sha256, json.dumps(parsed_output), doc_id))


    def insert_chunks(self, chunks):
        for ch in chunks:
            self.c.execute(
                "insert into chunks (version_id, content, section_title, page_number, chunk_index, "
                "embedding, token_count) values (%s, %s, %s, %s, %s, %s::vector, %s)",
                (ch["version_id"], ch["content"], ch["section_title"], ch["page_number"],
                 ch["chunk_index"], str(ch["embedding"]), ch["token_count"]))
        self.c.commit()

    def promote_version(self, doc_id, resolution):
        self.c.execute("select promote_version(%s, %s)", (doc_id, resolution))
        self.c.commit()

    def delete_pending_version(self, doc_id, resolution):
        doc = self.get_version(doc_id)
        assert doc and doc["status"] == "pending"
        self.c.execute("delete from chunks where version_id = %s", (doc_id,))
        self.c.execute("delete from versions where id = %s", (doc_id,))
        self.c.execute("update flags set resolved_at = %s, resolution = %s where id = %s",
                       (datetime.now(UTC), resolution, doc["flag_id"]))
        self.c.commit()


def _pdf(path: Path, height: int) -> Path:
    w = PdfWriter()
    w.add_blank_page(width=200, height=height)
    with open(path, "wb") as f:
        w.write(f)
    return path


def _deps(fail_embedding: bool):
    parser = MagicMock()
    parser.parse_pdf = AsyncMock(return_value=({"result": {}}, SECTIONS))
    chunker = MagicMock()
    chunker.chunk_sections.return_value = [
        Chunk(content="c", section_title="S", page_number=1, chunk_index=0, token_count=3)]
    embedder = MagicMock()
    embedder.embed_texts = AsyncMock(side_effect=RuntimeError("rate limit")) if fail_embedding \
        else AsyncMock(return_value=[VEC])
    return parser, chunker, embedder


def _state(conn, source_key):
    docs = conn.execute("select status, ingestion_status from versions where source_key = %s",
                        (source_key,)).fetchall()
    open_flags = conn.execute("select count(*) as n from flags where source_key = %s and resolved_at is null",
                              (source_key,)).fetchone()["n"]
    return sorted((d["status"], d["ingestion_status"]) for d in docs), open_flags


@pytest.fixture
def db(pg_db_url):
    with psycopg.connect(pg_db_url, row_factory=dict_row) as conn:
        yield PgDb(conn)


@pytest.fixture
def source(db):
    make_reference_rows(db.c)
    db.c.commit()
    db.c.execute("insert into sources (key, level) values ('s', 'operator')")
    db.c.execute("insert into source_scopes (source_key, scope_key) values ('s', 'bkw')")
    db.c.commit()
    return "s"


async def test_failed_load_after_text_fingerprint_reloads_cleanly(db, source, tmp_path):
    f = _pdf(tmp_path / "v1.pdf", 200)
    with pytest.raises(RuntimeError):
        await load_version(db, source, f, "Doc", None, *_deps(fail_embedding=True))
    assert _state(db.c, source) == ([("pending", "failed")], 1)

    action, _ = await load_version(db, source, f, "Doc", None, *_deps(fail_embedding=False))

    assert action == "promoted"
    assert _state(db.c, source) == ([("current", "completed")], 0)


async def test_stale_pending_row_with_same_text_but_new_bytes_does_not_block(db, source, tmp_path):
    with pytest.raises(RuntimeError):
        await load_version(db, source, _pdf(tmp_path / "a.pdf", 200), "Doc", None,
                           *_deps(fail_embedding=True))

    action, _ = await load_version(db, source, _pdf(tmp_path / "b.pdf", 300), "Doc", None,
                                   *_deps(fail_embedding=False))

    assert action == "promoted"
    assert _state(db.c, source) == ([("current", "completed")], 0)


async def test_repackaged_current_version_is_dismissed_without_open_flag(db, source, tmp_path):
    await load_version(db, source, _pdf(tmp_path / "a.pdf", 200), "Doc", None,
                       *_deps(fail_embedding=False))

    action, _ = await load_version(db, source, _pdf(tmp_path / "b.pdf", 300), "Doc", None,
                                   *_deps(fail_embedding=False))

    assert action == "dismissed"
    assert _state(db.c, source) == ([("current", "completed")], 0)
