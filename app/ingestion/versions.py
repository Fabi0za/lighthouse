"""Load one file as a version of a source, identified by fingerprint, never by path.

Shared by scripts/load_corpus.py and POST /ingest.
"""
from __future__ import annotations

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


async def load_version(
    db,
    source: dict[str, Any],
    file: Path,
    title: str,
    address: str | None,
    parser,
    chunker,
    embedder,
    max_pages: int | None = None,
    stored_path: str | None = None,
) -> tuple[str, str]:
    """Load file as a version of source. Returns (action, document_id).

    action is "skipped" (these bytes are already a version), "dismissed" (new bytes,
    same text: repackaging) or "promoted" (new content, now current).
    On failure the version is marked failed and its flag stays open.
    """
    file = Path(file)
    source_id = source["id"]
    file_hash = file_sha256(file)
    versions = db.list_versions(source_id)

    for v in versions:
        if v.get("file_sha256") == file_hash:
            if v.get("status") != "pending":
                return "skipped", v["id"]
            db.delete_pending_version(v["id"], "dismissed (reload)")

    doc = db.hold_version(source_id, title, address, stored_path or str(file), file_hash)
    doc_id = doc["id"]
    try:
        db.update_document(doc_id, {"ingestion_status": "processing"})
        with tempfile.TemporaryDirectory() as tmp:
            parse_path = first_pages(file, max_pages, Path(tmp)) if max_pages else file
            raw_output, sections = await parser.parse_pdf(str(parse_path))

        text_hash = text_sha256(sections)
        for v in versions:
            if v.get("text_sha256") == text_hash and v.get("status") != "pending":
                db.delete_pending_version(doc_id, "dismissed (same text)")
                return "dismissed", v["id"]
        db.set_text_fingerprint(doc_id, text_hash, raw_output)

        chunks = chunker.chunk_sections(sections, doc_title=title)
        if not chunks:
            raise RuntimeError("parser returned no content")
        embeddings = await embedder.embed_texts([c.content for c in chunks])
        db.insert_chunks([
            {
                "document_id": doc_id,
                "content": c.content,
                "section_title": c.section_title,
                "page_number": c.page_number,
                "chunk_index": c.chunk_index,
                "embedding": embeddings[i],
                "token_count": c.token_count,
            }
            for i, c in enumerate(chunks)
        ])
        db.update_document(doc_id, {"ingestion_status": "completed"})
    except Exception:
        db.update_document(doc_id, {"ingestion_status": "failed"})
        raise

    db.promote_version(doc_id, "promoted (auto)")
    return "promoted", doc_id
