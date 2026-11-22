"""Load one file as a version of a source, identified by fingerprint, never by path.

Used by scripts/load_corpus.py.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from pypdf import PdfReader, PdfWriter

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


async def load_version(
    db,
    source_key: str,
    file: Path,
    title: str,
    obtained_from: str | None,
    parser,
    chunker,
    embedder,
    max_pages: int | None = None,
    stored_path: str | None = None,
    parsed_cache: Path | None = None,
) -> tuple[str, str]:
    """Load file as a version of the source with source_key. Returns (action, version_id).

    action is "skipped" (these bytes are already a version), "dismissed" (new bytes,
    same text: repackaging) or "promoted" (new content, now current).
    On failure the version is marked failed and its flag stays open.

    With parsed_cache, a file <file_sha256>.json in that directory is used as the
    parser's output instead of parsing (max_pages is then ignored: the cached output
    is whatever was parsed before). Without it, the file is always parsed.
    """
    file = Path(file)
    file_hash = file_sha256(file)
    versions = db.list_versions(source_key)

    for v in versions:
        if v.get("file_sha256") == file_hash:
            if v.get("status") != "pending":
                return "skipped", v["id"]
            db.delete_pending_version(v["id"], "dismissed (reload)")
    versions = [v for v in versions if v.get("file_sha256") != file_hash]

    doc = db.hold_version(source_key, title, obtained_from, stored_path or str(file), file_hash)
    doc_id = doc["id"]
    try:
        db.update_version(doc_id, {"ingestion_status": "processing"})
        cached = cached_output(parsed_cache, file_hash)
        if cached:
            raw_output = json.loads(cached.read_text(encoding="utf-8"))
            sections = parser._extract_sections(raw_output)
        else:
            with tempfile.TemporaryDirectory() as tmp:
                parse_path = first_pages(file, max_pages, Path(tmp)) if max_pages else file
                raw_output, sections = await parser.parse_pdf(str(parse_path))

        text_hash = text_sha256(sections)
        for v in versions:
            if v.get("text_sha256") != text_hash or v["id"] == doc_id:
                continue
            if v.get("status") == "pending":
                # Left by an interrupted load of other bytes with the same text.
                db.delete_pending_version(v["id"], "dismissed (reload)")
                continue
            db.delete_pending_version(doc_id, "dismissed (same text)")
            return "dismissed", v["id"]
        db.set_text_fingerprint(doc_id, text_hash, raw_output)

        chunks = chunker.chunk_sections(sections, doc_title=title)
        if not chunks:
            raise RuntimeError("parser returned no content")
        embeddings = await embedder.embed_texts([c.content for c in chunks])
        db.insert_chunks([
            {
                "version_id": doc_id,
                "content": c.content,
                "section_title": c.section_title,
                "page_number": c.page_number,
                "chunk_index": c.chunk_index,
                "embedding": embeddings[i],
                "token_count": c.token_count,
            }
            for i, c in enumerate(chunks)
        ])
        db.update_version(doc_id, {"ingestion_status": "completed"})
    except Exception:
        db.update_version(doc_id, {"ingestion_status": "failed"})
        raise

    db.promote_version(doc_id, "promoted (auto)")
    return "promoted", doc_id
