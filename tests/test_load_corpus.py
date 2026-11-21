import importlib.util
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pypdf import PdfReader, PdfWriter

from app.ingestion.chunker import Chunk

_spec = importlib.util.spec_from_file_location(
    "load_corpus", Path(__file__).resolve().parent.parent / "scripts" / "load_corpus.py"
)
lc = importlib.util.module_from_spec(_spec)
sys.modules["load_corpus"] = lc
_spec.loader.exec_module(lc)


def _pdf(path: Path, pages: int) -> Path:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    with open(path, "wb") as f:
        writer.write(f)
    return path


def _corpus(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "corpus.yaml"
    p.write_text(body, encoding="utf-8")
    return p


def test_load_corpus_maps_levels(tmp_path):
    _pdf(tmp_path / "a.pdf", 1)
    _pdf(tmp_path / "b.pdf", 1)
    corpus = _corpus(tmp_path, """
documents:
  - {path: a.pdf, title: A, issuer: VSE, level: national, scope: null, source_url: ""}
  - {path: b.pdf, title: B, issuer: BKW, level: operator, scope: BKW, source_url: "", max_pages: 4}
""")
    a, b = lc.load_corpus(corpus, tmp_path)
    assert (a.doc_type, a.hierarchy_priority, a.scope) == ("general_regulation", 1, None)
    assert (b.doc_type, b.hierarchy_priority, b.scope, b.max_pages) == ("grid_provider_rule", 2, "BKW", 4)


def test_load_corpus_reports_all_problems(tmp_path):
    _pdf(tmp_path / "a.pdf", 1)
    corpus = _corpus(tmp_path, """
documents:
  - {path: a.pdf, title: A, issuer: VSE, level: regional}
  - {path: a.pdf, title: A, issuer: X, level: operator}
  - {path: missing.pdf, title: M, issuer: X, level: national}
  - {path: a.pdf, issuer: X, level: national}
""")
    with pytest.raises(ValueError) as e:
        lc.load_corpus(corpus, tmp_path)
    msg = str(e.value)
    assert "level must be one of" in msg
    assert "operator documents need a scope" in msg
    assert "missing.pdf: file not found" in msg
    assert "missing title" in msg


def _entry(path="a.pdf", max_pages=None, level="operator", scope="BKW"):
    return lc.CorpusEntry(path=path, title="T", issuer="I", level=level, scope=scope,
                          source_url="", max_pages=max_pages)


def test_plan_skips_completed_and_reloads_partial():
    entries = [_entry("done.pdf"), _entry("broken.pdf"), _entry("new.pdf")]
    existing = [
        {"id": "1", "file_path": "done.pdf", "ingestion_status": "completed"},
        {"id": "2", "file_path": "broken.pdf", "ingestion_status": "failed"},
        {"id": "3", "file_path": "broken.pdf", "ingestion_status": "processing"},
    ]
    actions = {e.path: (a, ids) for e, a, ids in lc.plan(entries, existing)}
    assert actions["done.pdf"] == ("skip", [])
    assert actions["broken.pdf"] == ("reload", ["2", "3"])
    assert actions["new.pdf"] == ("load", [])


def test_first_pages_truncates(tmp_path):
    src = _pdf(tmp_path / "big.pdf", 10)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    out = lc.first_pages(src, 4, out_dir)
    assert out.name == "big.pdf"
    assert len(PdfReader(str(out)).pages) == 4


def _deps(pages_seen: list[int]):
    db = MagicMock()
    db.insert_document.return_value = {"id": str(uuid.uuid4())}
    parser = MagicMock()

    async def parse(path):
        pages_seen.append(len(PdfReader(path).pages))
        return {"result": {}}, [{"title": "S", "content": "x", "page": 1}]

    parser.parse_pdf = parse
    chunker = MagicMock()
    chunker.chunk_sections.return_value = [
        Chunk(content="c1", section_title="S", page_number=1, chunk_index=0, token_count=3)
    ]
    embedder = MagicMock()
    embedder.embed_texts = AsyncMock(return_value=[[0.1] * 1536])
    return db, parser, chunker, embedder


async def test_ingest_stores_scope_and_limits_pages(tmp_path):
    _pdf(tmp_path / "a.pdf", 10)
    pages_seen: list[int] = []
    db, parser, chunker, embedder = _deps(pages_seen)

    n = await lc.ingest(_entry(max_pages=4), tmp_path, db, parser, chunker, embedder)

    assert n == 1
    assert pages_seen == [4]
    kwargs = db.insert_document.call_args.kwargs
    assert kwargs["file_path"] == "a.pdf"
    assert kwargs["grid_provider"] == "BKW"
    assert kwargs["doc_type"] == "grid_provider_rule"
    assert chunker.chunk_sections.call_args.kwargs["doc_title"] == "T"
    record = db.insert_chunks.call_args.args[0][0]
    assert (record["grid_provider"], record["hierarchy_priority"]) == ("BKW", 2)
    assert db.update_document.call_args.args[1] == {"ingestion_status": "completed"}


async def test_ingest_marks_failed_on_error(tmp_path):
    _pdf(tmp_path / "a.pdf", 2)
    db, parser, chunker, embedder = _deps([])
    embedder.embed_texts = AsyncMock(side_effect=RuntimeError("boom"))

    with pytest.raises(RuntimeError):
        await lc.ingest(_entry(), tmp_path, db, parser, chunker, embedder)
    assert db.update_document.call_args.args[1] == {"ingestion_status": "failed"}
