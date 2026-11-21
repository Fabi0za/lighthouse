from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pypdf import PdfReader, PdfWriter

from app.ingestion.chunker import Chunk
from app.ingestion.fingerprint import file_sha256, text_sha256
from app.ingestion.versions import first_pages, load_version

SECTIONS = [{"title": "S", "content": "Steuerdraht 2 ist optional", "page": 1}]
SOURCE = {"id": "src-1"}


def _pdf(path: Path, pages: int = 1) -> Path:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    with open(path, "wb") as f:
        writer.write(f)
    return path


def _deps(existing: list[dict] | None = None, sections=SECTIONS, pages_seen: list[int] | None = None):
    db = MagicMock()
    db.list_versions.return_value = existing or []
    db.hold_version.return_value = {"id": "new-doc", "status": "pending", "flag_id": "flag-1"}
    parser = MagicMock()

    async def parse(path):
        if pages_seen is not None:
            pages_seen.append(len(PdfReader(path).pages))
        return {"result": {"raw": True}}, sections

    parser.parse_pdf = parse
    chunker = MagicMock()
    chunker.chunk_sections.return_value = [
        Chunk(content="c1", section_title="S", page_number=1, chunk_index=0, token_count=3)
    ]
    embedder = MagicMock()
    embedder.embed_texts = AsyncMock(return_value=[[0.1] * 1536])
    return db, parser, chunker, embedder


async def test_new_file_promoted(tmp_path):
    f = _pdf(tmp_path / "v2.pdf")
    db, parser, chunker, embedder = _deps()

    action, doc_id = await load_version(db, SOURCE, f, "Doc (V2)", "https://example.org/v2.pdf",
                                        parser, chunker, embedder)

    assert (action, doc_id) == ("promoted", "new-doc")
    db.hold_version.assert_called_once_with(
        "src-1", "Doc (V2)", "https://example.org/v2.pdf", str(f), file_sha256(f)
    )
    db.set_text_fingerprint.assert_called_once_with("new-doc", text_sha256(SECTIONS), {"result": {"raw": True}})
    assert chunker.chunk_sections.call_args.kwargs["doc_title"] == "Doc (V2)"
    db.update_document.assert_called_with("new-doc", {"ingestion_status": "completed"})
    db.promote_version.assert_called_once_with("new-doc", "promoted (auto)")


async def test_same_bytes_skipped(tmp_path):
    f = _pdf(tmp_path / "v1.pdf")
    existing = [{"id": "old", "status": "current", "file_sha256": file_sha256(f), "text_sha256": "t"}]
    db, parser, chunker, embedder = _deps(existing)

    assert await load_version(db, SOURCE, f, "Doc", None, parser, chunker, embedder) == ("skipped", "old")
    db.hold_version.assert_not_called()


async def test_same_bytes_as_retired_version_skipped(tmp_path):
    f = _pdf(tmp_path / "v1.pdf")
    existing = [{"id": "old", "status": "retired", "file_sha256": file_sha256(f), "text_sha256": "t"}]
    db, parser, chunker, embedder = _deps(existing)

    assert await load_version(db, SOURCE, f, "Doc", None, parser, chunker, embedder) == ("skipped", "old")


async def test_same_text_new_bytes_is_dismissed(tmp_path):
    f = _pdf(tmp_path / "repackaged.pdf")
    existing = [{"id": "old", "status": "current", "file_sha256": "other-bytes",
                 "text_sha256": text_sha256(SECTIONS)}]
    db, parser, chunker, embedder = _deps(existing)

    action, doc_id = await load_version(db, SOURCE, f, "Doc", None, parser, chunker, embedder)

    assert (action, doc_id) == ("dismissed", "old")
    db.delete_pending_version.assert_called_once_with("new-doc", "dismissed (same text)")
    db.set_text_fingerprint.assert_not_called()
    db.insert_chunks.assert_not_called()
    db.promote_version.assert_not_called()


async def test_plan_resumes_pending_row(tmp_path):
    f = _pdf(tmp_path / "v2.pdf")
    existing = [{"id": "stale", "status": "pending", "file_sha256": file_sha256(f), "text_sha256": None}]
    db, parser, chunker, embedder = _deps(existing)
    order = []
    db.delete_pending_version.side_effect = lambda *a: order.append(("delete", a))
    db.hold_version.side_effect = lambda *a, **k: order.append(("hold", a)) or {"id": "new-doc"}

    action, _ = await load_version(db, SOURCE, f, "Doc", None, parser, chunker, embedder)

    assert action == "promoted"
    assert order[0] == ("delete", ("stale", "dismissed (reload)"))
    assert order[1][0] == "hold"


async def test_failure_marks_failed_and_keeps_flag(tmp_path):
    f = _pdf(tmp_path / "v2.pdf")
    db, parser, chunker, embedder = _deps()
    embedder.embed_texts = AsyncMock(side_effect=RuntimeError("boom"))

    with pytest.raises(RuntimeError):
        await load_version(db, SOURCE, f, "Doc", None, parser, chunker, embedder)

    db.update_document.assert_called_with("new-doc", {"ingestion_status": "failed"})
    db.promote_version.assert_not_called()
    db.delete_pending_version.assert_not_called()


async def test_chunk_records_have_no_removed_columns(tmp_path):
    f = _pdf(tmp_path / "v2.pdf")
    db, parser, chunker, embedder = _deps()

    await load_version(db, SOURCE, f, "Doc", None, parser, chunker, embedder)

    record = db.insert_chunks.call_args.args[0][0]
    assert set(record) == {"document_id", "content", "section_title", "page_number",
                           "chunk_index", "embedding", "token_count"}
    assert record["document_id"] == "new-doc"


async def test_max_pages_limits_parse_but_not_fingerprint(tmp_path):
    f = _pdf(tmp_path / "big.pdf", 10)
    pages_seen: list[int] = []
    db, parser, chunker, embedder = _deps(pages_seen=pages_seen)

    await load_version(db, SOURCE, f, "Doc", None, parser, chunker, embedder, max_pages=4)

    assert pages_seen == [4]
    assert db.hold_version.call_args.args[4] == file_sha256(f)


async def test_stored_path_overrides_file_path(tmp_path):
    f = _pdf(tmp_path / "v2.pdf")
    db, parser, chunker, embedder = _deps()

    await load_version(db, SOURCE, f, "Doc", None, parser, chunker, embedder, stored_path="data/v2.pdf")

    assert db.hold_version.call_args.args[3] == "data/v2.pdf"


async def test_empty_parse_fails(tmp_path):
    f = _pdf(tmp_path / "v2.pdf")
    db, parser, chunker, embedder = _deps()
    chunker.chunk_sections.return_value = []

    with pytest.raises(RuntimeError):
        await load_version(db, SOURCE, f, "Doc", None, parser, chunker, embedder)
    db.promote_version.assert_not_called()


def test_first_pages_truncates(tmp_path):
    src = _pdf(tmp_path / "big.pdf", 10)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    out = first_pages(src, 4, out_dir)
    assert out.name == "big.pdf"
    assert len(PdfReader(str(out)).pages) == 4
