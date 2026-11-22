from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pypdf import PdfReader, PdfWriter

from app.ingestion.chunker import Chunk
from app.ingestion.fingerprint import file_sha256, text_sha256
from app.ingestion.versions import first_pages, load_version

SECTIONS = [{"title": "S", "content": "Steuerdraht 2 ist optional", "page": 1}]
SOURCE = "src-1"


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
    db.begin_load.return_value = "new-doc"
    db.promote_version.return_value = 0
    parser = MagicMock()

    async def parse(path):
        if pages_seen is not None:
            pages_seen.append(len(PdfReader(path).pages))
        return {"result": {"raw": True}}, sections

    parser.parse_pdf = parse
    chunker = MagicMock()
    chunker.chunk_sections.return_value = [
        Chunk(content="c1", section_title="S", page_number=1, chunk_index=0)
    ]
    embedder = MagicMock()
    embedder.embed_texts = AsyncMock(return_value=[[0.1] * 1536])
    return db, parser, chunker, embedder


async def test_new_file_promoted(tmp_path):
    f = _pdf(tmp_path / "v2.pdf")
    db, parser, chunker, embedder = _deps()

    action, doc_id, _ = await load_version(db, SOURCE, f, "Doc", "https://example.org/v2.pdf",
                                        parser, chunker, embedder, version_label="V2")

    assert (action, doc_id) == ("promoted", "new-doc")
    db.begin_load.assert_called_once_with(
        "src-1", "Doc", "V2", "https://example.org/v2.pdf", None, file_sha256(f)
    )
    db.set_text_fingerprint.assert_called_once_with("new-doc", text_sha256(SECTIONS), {"result": {"raw": True}})
    chunker.chunk_sections.assert_called_once_with(SECTIONS)
    embedder.embed_texts.assert_awaited_once_with(["[Doc (V2) — S]\nc1"])
    assert db.insert_chunks.call_args.args[0][0]["content"] == "c1"  # stored without the header
    db.promote_version.assert_called_once_with("new-doc")
    db.fail_load.assert_not_called()


async def test_same_bytes_skipped(tmp_path):
    f = _pdf(tmp_path / "v1.pdf")
    existing = [{"id": "old", "status": "current", "file_sha256": file_sha256(f), "text_sha256": "t"}]
    db, parser, chunker, embedder = _deps(existing)

    assert await load_version(db, SOURCE, f, "Doc", None, parser, chunker, embedder) == ("skipped", "old", None)
    db.begin_load.assert_not_called()


async def test_same_bytes_as_retired_version_skipped(tmp_path):
    f = _pdf(tmp_path / "v1.pdf")
    existing = [{"id": "old", "status": "retired", "file_sha256": file_sha256(f), "text_sha256": "t"}]
    db, parser, chunker, embedder = _deps(existing)

    assert await load_version(db, SOURCE, f, "Doc", None, parser, chunker, embedder) == ("skipped", "old", None)


async def test_same_text_new_bytes_is_dismissed(tmp_path):
    f = _pdf(tmp_path / "repackaged.pdf")
    existing = [{"id": "old", "status": "current", "file_sha256": "other-bytes",
                 "text_sha256": text_sha256(SECTIONS)}]
    db, parser, chunker, embedder = _deps(existing)

    action, doc_id, _ = await load_version(db, SOURCE, f, "Doc", None, parser, chunker, embedder)

    assert (action, doc_id) == ("dismissed", "old")
    db.discard_version.assert_called_once_with("new-doc")
    db.set_text_fingerprint.assert_not_called()
    db.insert_chunks.assert_not_called()
    db.promote_version.assert_not_called()


async def test_chunk_records_have_no_removed_columns(tmp_path):
    f = _pdf(tmp_path / "v2.pdf")
    db, parser, chunker, embedder = _deps()

    await load_version(db, SOURCE, f, "Doc", None, parser, chunker, embedder)

    record = db.insert_chunks.call_args.args[0][0]
    assert set(record) == {"version_id", "content", "section_title", "page_number",
                           "chunk_index", "embedding"}
    assert record["version_id"] == "new-doc"


async def test_max_pages_limits_parse_but_not_fingerprint(tmp_path):
    f = _pdf(tmp_path / "big.pdf", 10)
    pages_seen: list[int] = []
    db, parser, chunker, embedder = _deps(pages_seen=pages_seen)

    await load_version(db, SOURCE, f, "Doc", None, parser, chunker, embedder, max_pages=4)

    assert pages_seen == [4]
    assert db.begin_load.call_args.args[4] == 4  # page_limit recorded on the version
    assert db.begin_load.call_args.args[5] == file_sha256(f)


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


# --- parsed-output cache -------------------------------------------------------

def _cache(tmp_path, f, raw):
    import json
    d = tmp_path / "cache"
    d.mkdir(exist_ok=True)
    (d / f"{file_sha256(f)}.json").write_text(json.dumps(raw), encoding="utf-8")
    return d


async def test_cache_hit_uses_cached_output_instead_of_parser(tmp_path):
    f = _pdf(tmp_path / "v2.pdf", 10)
    raw = {"result": {"cached": True}}
    cache = _cache(tmp_path, f, raw)
    pages_seen: list[int] = []
    db, parser, chunker, embedder = _deps(pages_seen=pages_seen)
    parser._extract_sections = MagicMock(return_value=SECTIONS)

    action, _, _ = await load_version(db, SOURCE, f, "Doc", None, parser, chunker, embedder,
                                   max_pages=4, parsed_cache=cache)

    assert action == "promoted"
    assert pages_seen == []  # parse_pdf never called, no truncation
    parser._extract_sections.assert_called_once_with(raw)
    db.set_text_fingerprint.assert_called_once_with("new-doc", text_sha256(SECTIONS), raw)


async def test_cache_miss_parses(tmp_path):
    f = _pdf(tmp_path / "v2.pdf")
    other = _pdf(tmp_path / "other.pdf", 2)
    cache = _cache(tmp_path, other, {"result": {}})
    pages_seen: list[int] = []
    db, parser, chunker, embedder = _deps(pages_seen=pages_seen)

    await load_version(db, SOURCE, f, "Doc", None, parser, chunker, embedder, parsed_cache=cache)

    assert pages_seen == [1]


def test_cached_output_path(tmp_path):
    from app.ingestion.versions import cached_output
    f = _pdf(tmp_path / "v.pdf")
    assert cached_output(None, file_sha256(f)) is None
    assert cached_output(tmp_path, file_sha256(f)) is None
    cache = _cache(tmp_path, f, {})
    assert cached_output(cache, file_sha256(f)) == cache / f"{file_sha256(f)}.json"


@pytest.mark.parametrize("status", ["loading", "failed"])
async def test_unfinished_version_with_same_text_but_other_bytes_is_discarded(tmp_path, status):
    f = _pdf(tmp_path / "v2b.pdf")
    existing = [{"id": "stale", "status": status, "file_sha256": "older-bytes",
                 "text_sha256": text_sha256(SECTIONS)}]
    db, parser, chunker, embedder = _deps(existing)

    action, doc_id, _ = await load_version(db, SOURCE, f, "Doc", None, parser, chunker, embedder)

    assert (action, doc_id) == ("promoted", "new-doc")
    db.discard_version.assert_called_once_with("stale")
    db.set_text_fingerprint.assert_called_once()


async def test_chunk_header_uses_display_title_without_label(tmp_path):
    f = _pdf(tmp_path / "v.pdf")
    db, parser, chunker, embedder = _deps()
    await load_version(db, SOURCE, f, "Merkblatt", None, parser, chunker, embedder)
    embedder.embed_texts.assert_awaited_once_with(["[Merkblatt — S]\nc1"])


@pytest.mark.parametrize("status", ["loading", "failed"])
async def test_unfinished_version_with_same_bytes_is_taken_up_again(tmp_path, status):
    f = _pdf(tmp_path / "v2.pdf")
    existing = [{"id": "new-doc", "status": status, "file_sha256": file_sha256(f), "text_sha256": None}]
    db, parser, chunker, embedder = _deps(existing)

    action, doc_id, _ = await load_version(db, SOURCE, f, "Doc", None, parser, chunker, embedder)

    assert (action, doc_id) == ("promoted", "new-doc")
    db.begin_load.assert_called_once()
    db.discard_version.assert_not_called()


async def test_parser_error_is_parse_failed(tmp_path):
    f = _pdf(tmp_path / "v2.pdf")
    db, parser, chunker, embedder = _deps()
    parser.parse_pdf = AsyncMock(side_effect=TimeoutError("parser timed out"))

    with pytest.raises(TimeoutError):
        await load_version(db, SOURCE, f, "Doc", None, parser, chunker, embedder, listed_path="data/v2.pdf")

    db.fail_load.assert_called_once_with("new-doc", "parse_failed", "data/v2.pdf",
                                         "TimeoutError: parser timed out")
    db.promote_version.assert_not_called()


async def test_later_error_is_load_failed(tmp_path):
    f = _pdf(tmp_path / "v2.pdf")
    db, parser, chunker, embedder = _deps()
    embedder.embed_texts = AsyncMock(side_effect=RuntimeError("rate limit"))

    with pytest.raises(RuntimeError):
        await load_version(db, SOURCE, f, "Doc", None, parser, chunker, embedder)

    db.fail_load.assert_called_once_with("new-doc", "load_failed", "v2.pdf", "RuntimeError: rate limit")
    db.promote_version.assert_not_called()


async def test_first_version_retires_nothing(tmp_path):
    f = _pdf(tmp_path / "v1.pdf")
    db, parser, chunker, embedder = _deps()
    result = await load_version(db, SOURCE, f, "Doc", None, parser, chunker, embedder)
    assert result.retired_seen_by is None


async def test_promotion_reports_answers_that_saw_the_retired_version(tmp_path):
    f = _pdf(tmp_path / "v2.pdf")
    existing = [{"id": "old", "status": "current", "file_sha256": "other-bytes", "text_sha256": "other-text"}]
    db, parser, chunker, embedder = _deps(existing)
    db.promote_version.return_value = 2
    result = await load_version(db, SOURCE, f, "Doc", None, parser, chunker, embedder)
    assert (result.action, result.version_id, result.retired_seen_by) == ("promoted", "new-doc", 2)

