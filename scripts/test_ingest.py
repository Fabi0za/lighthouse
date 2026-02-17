"""Quick script to test PDF ingestion end-to-end."""
import asyncio
import sys

from app.config import get_settings
from app.ingestion.parser import ReductoParser
from app.ingestion.chunker import Chunker
from app.ingestion.embedder import Embedder
from app.models.database import DatabaseClient


async def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/test_ingest.py <pdf_path> [title] [doc_type] [priority]")
        sys.exit(1)

    pdf_path = sys.argv[1]
    title = sys.argv[2] if len(sys.argv) > 2 else pdf_path.split("/")[-1]
    doc_type = sys.argv[3] if len(sys.argv) > 3 else "product_manual"
    priority = int(sys.argv[4]) if len(sys.argv) > 4 else 5

    settings = get_settings()
    db = DatabaseClient()
    parser = ReductoParser(api_key=settings.reducto_api_key)
    chunker = Chunker(chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap)
    embedder = Embedder(
        api_key=settings.openai_api_key,
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
    )

    print(f"1. Parsing PDF: {pdf_path}")
    raw_output, sections = await parser.parse_pdf(pdf_path)
    print(f"   Found {len(sections)} sections")
    for s in sections[:5]:
        print(f"   - {s['title']} (page {s['page']}, {len(s['content'])} chars)")
    if len(sections) > 5:
        print(f"   ... and {len(sections) - 5} more")

    print(f"\n2. Chunking sections")
    chunks = chunker.chunk_sections(sections)
    print(f"   Created {len(chunks)} chunks")

    print(f"\n3. Embedding {len(chunks)} chunks")
    texts = [c.content for c in chunks]
    embeddings = await embedder.embed_texts(texts)
    print(f"   Got {len(embeddings)} embeddings (dim={len(embeddings[0])})")

    print(f"\n4. Storing in Supabase")
    doc = db.insert_document(
        title=title,
        doc_type=doc_type,
        hierarchy_priority=priority,
        file_path=pdf_path,
    )
    doc_id = doc["id"]
    print(f"   Document ID: {doc_id}")

    db.update_document(doc_id, {"raw_reducto_output": raw_output})

    chunk_records = [
        {
            "document_id": doc_id,
            "content": c.content,
            "section_title": c.section_title,
            "page_number": c.page_number,
            "chunk_index": c.chunk_index,
            "doc_type": doc_type,
            "hierarchy_priority": priority,
            "embedding": embeddings[i],
            "token_count": c.token_count,
        }
        for i, c in enumerate(chunks)
    ]
    db.insert_chunks(chunk_records)
    db.update_document(doc_id, {"ingestion_status": "completed"})
    print(f"   Stored {len(chunk_records)} chunks")

    print(f"\n✓ Ingestion complete!")

    await parser.close()
    await embedder.close()


if __name__ == "__main__":
    asyncio.run(main())
