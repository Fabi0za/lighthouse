"""Replace a document with a new PDF version, preserving the document_id.

Usage:
    python scripts/replace_document.py <doc_id> <path_to_new_pdf>

The script:
1. Reads existing document metadata (title, doc_type, etc.)
2. Deletes old chunks
3. Parses, chunks, and embeds the new PDF
4. Inserts new chunks under the same document_id
5. Updates the document record with new raw output and status
"""
from __future__ import annotations

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid

from app.config import get_settings
from app.ingestion.chunker import Chunker
from app.ingestion.embedder import Embedder
from app.ingestion.parser import ReductoParser
from app.models.database import DatabaseClient


async def replace_document(doc_id_str: str, pdf_path: str) -> None:
    if not os.path.exists(pdf_path):
        print(f"Error: File not found: {pdf_path}")
        sys.exit(1)

    doc_id = uuid.UUID(doc_id_str)
    settings = get_settings()
    db = DatabaseClient()

    # 1. Read existing document
    doc = db.get_document(doc_id)
    if doc is None:
        print(f"Error: Document {doc_id} not found.")
        sys.exit(1)

    title = doc["title"]
    doc_type = doc["doc_type"]
    hierarchy_priority = doc["hierarchy_priority"]
    grid_provider = doc.get("grid_provider")

    print(f"Replacing: {title}")
    print(f"  doc_id:   {doc_id}")
    print(f"  type:     {doc_type}")
    print(f"  priority: {hierarchy_priority}")
    print(f"  provider: {grid_provider}")
    print(f"  new PDF:  {pdf_path}")

    # 2. Count and delete old chunks
    old_chunks = (
        db.client.table("document_chunks")
        .select("id")
        .eq("document_id", str(doc_id))
        .execute()
    )
    old_count = len(old_chunks.data)
    db.delete_chunks_for_document(doc_id)
    print(f"\nDeleted {old_count} old chunks.")

    # 3. Parse new PDF
    db.update_document(doc_id, {"ingestion_status": "processing"})
    parser = ReductoParser(api_key=settings.reducto_api_key)
    try:
        raw_output, sections = await parser.parse_pdf(pdf_path)
    finally:
        await parser.close()

    db.update_document(doc_id, {
        "raw_reducto_output": raw_output,
        "file_path": pdf_path,
    })
    print(f"Parsed {len(sections)} sections.")

    # 4. Chunk
    chunker = Chunker(chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap)
    chunks = chunker.chunk_sections(sections, doc_title=title)
    print(f"Created {len(chunks)} chunks.")

    # 5. Embed
    embedder = Embedder(
        api_key=settings.openai_api_key,
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
    )
    texts = [c.content for c in chunks]
    embeddings = await embedder.embed_texts(texts)
    print(f"Generated {len(embeddings)} embeddings.")

    # 6. Insert new chunks
    chunk_records = [
        {
            "document_id": str(doc_id),
            "content": c.content,
            "section_title": c.section_title,
            "page_number": c.page_number,
            "chunk_index": c.chunk_index,
            "doc_type": doc_type,
            "grid_provider": grid_provider,
            "hierarchy_priority": hierarchy_priority,
            "embedding": embeddings[i],
            "token_count": c.token_count,
        }
        for i, c in enumerate(chunks)
    ]
    db.insert_chunks(chunk_records)

    # 7. Update document status
    db.update_document(doc_id, {"ingestion_status": "completed"})

    print(f"\nDone. {old_count} old chunks -> {len(chunks)} new chunks.")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python scripts/replace_document.py <doc_id> <path_to_pdf>")
        sys.exit(1)

    asyncio.run(replace_document(sys.argv[1], sys.argv[2]))
