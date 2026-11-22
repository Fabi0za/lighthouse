"""Load one file as a version of a source, identified by fingerprint, never by path.

Used by scripts/load_corpus.py.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import NamedTuple

from pypdf import PdfReader, PdfWriter

from app.generation.prompts import display_title
from app.ingestion.fingerprint import file_sha256, text_sha256


def first_pages(src: Path, max_pages: int, out_dir: Path) -> Path:
    """Write the first max_pages pages of src to out_dir, keeping the file name."""
    reader = PdfReader(str(src))
    writer = PdfWriter()
    for page in reader.pages[:max_pages]:
        writer.add_page(page)
    out = out_dir / Path(src).name
    with open(out, "wb") as f:
        writer.write(f)
    return out


def cached_output(parsed_cache: Path | None, file_hash: str) -> Path | None:
    """The cached parser output for a file, named <file_sha256>.json, if the cache has one."""
    if parsed_cache is None:
        return None
    path = Path(parsed_cache) / f"{file_hash}.json"
    return path if path.is_file() else None


UNFINISHED = ("loading", "failed")


class LoadResult(NamedTuple):
    action: str                  # skipped, dismissed or promoted
    version_id: str
    retired_seen_by: int | None  # answers that saw the version this one retired; None if none was retired


async def load_version(
    db,
    source_key: str,
    file: Path,
    title: str,
    obtained_from: str | None,
    parser,
    chunker,
    embedder,
    *,
    version_label: str | None = None,
    max_pages: int | None = None,
    parsed_cache: Path | None = None,
    listed_path: str | None = None,
) -> LoadResult:
    """Load file as a version of the source with source_key.

    action is "skipped" (these bytes are already a version), "dismissed" (new bytes,
    same text: repackaging) or "promoted" (new content, now current). A routine load
    raises no flag. On failure the version is marked failed with a check_failed flag
    (parse_failed if the parser failed, load_failed otherwise) naming listed_path, the
    file as listed in corpus.yaml (default: its file name); a later load of the same
    bytes takes the version up again and, on success, resolves that flag.

    With parsed_cache, a file <file_sha256>.json in that directory is used as the
    parser's output instead of parsing (max_pages is then ignored: the cached output
    is whatever was parsed before). Without it, the file is always parsed.
    max_pages is recorded on the version as its page limit.
    """
    file = Path(file)
    file_hash = file_sha256(file)
    versions = db.list_versions(source_key)
    for v in versions:
        if v.get("file_sha256") == file_hash and v.get("status") not in UNFINISHED:
            return LoadResult("skipped", v["id"], None)

    version_id = db.begin_load(source_key, title, version_label, obtained_from, max_pages, file_hash)
    others = [v for v in versions if str(v["id"]) != str(version_id)]
    reason = "parse_failed"
    try:
        cached = cached_output(parsed_cache, file_hash)
        if cached:
            raw_output = json.loads(cached.read_text(encoding="utf-8"))
            sections = parser._extract_sections(raw_output)
        else:
            with tempfile.TemporaryDirectory() as tmp:
                parse_path = first_pages(file, max_pages, Path(tmp)) if max_pages else file
                raw_output, sections = await parser.parse_pdf(str(parse_path))
        reason = "load_failed"

        text_hash = text_sha256(sections)
        for v in others:
            if v.get("text_sha256") != text_hash:
                continue
            if v.get("status") in UNFINISHED:
                db.discard_version(v["id"])  # an earlier, unfinished load of other bytes
                continue
            db.discard_version(version_id)
            return LoadResult("dismissed", v["id"], None)
        db.set_text_fingerprint(version_id, text_hash, raw_output)

        chunks = chunker.chunk_sections(sections, doc_title=display_title(title, version_label))
        if not chunks:
            raise RuntimeError("parser returned no content")
        embeddings = await embedder.embed_texts([c.content for c in chunks])
        db.insert_chunks([
            {
                "version_id": version_id,
                "content": c.content,
                "section_title": c.section_title,
                "page_number": c.page_number,
                "chunk_index": c.chunk_index,
                "embedding": embeddings[i],
            }
            for i, c in enumerate(chunks)
        ])
        seen = db.promote_version(version_id)
    except Exception as e:
        db.fail_load(version_id, reason, listed_path or file.name, f"{type(e).__name__}: {e}")
        raise
    replaced_one = any(v.get("status") == "current" for v in others)
    return LoadResult("promoted", version_id, seen if replaced_one else None)
