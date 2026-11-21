"""Load every document listed in corpus.yaml through the existing ingestion pipeline.

Usage:
    python scripts/load_corpus.py [--corpus corpus.yaml] [--dry-run]

Idempotent: a document whose file_path is already stored with ingestion_status
"completed" is skipped. A document left behind by an interrupted run (any other
status) is deleted, chunks included, and loaded again.

The steps mirror POST /ingest in app/main.py: parse (Reducto), chunk with the
document title, embed (search_document), store document and chunks.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pypdf import PdfReader, PdfWriter

from app.config import get_settings
from app.ingestion.chunker import Chunker
from app.ingestion.embedder import Embedder
from app.ingestion.parser import ReductoParser
from app.models.database import DatabaseClient

LEVEL_MAPPING = {
    "national": ("general_regulation", 1),
    "operator": ("grid_provider_rule", 2),
}
REQUIRED_FIELDS = ("path", "title", "issuer", "level")


@dataclass
class CorpusEntry:
    path: str
    title: str
    issuer: str
    level: str
    scope: str | None
    source_url: str
    max_pages: int | None

    @property
    def doc_type(self) -> str:
        return LEVEL_MAPPING[self.level][0]

    @property
    def hierarchy_priority(self) -> int:
        return LEVEL_MAPPING[self.level][1]


def load_corpus(corpus_path: Path, repo_root: Path) -> list[CorpusEntry]:
    """Read and validate corpus.yaml. Raises ValueError listing every problem found."""
    data = yaml.safe_load(corpus_path.read_text(encoding="utf-8")) or {}
    raw_entries = data.get("documents") or []
    entries: list[CorpusEntry] = []
    problems: list[str] = []
    seen: set[str] = set()

    for i, raw in enumerate(raw_entries, 1):
        label = raw.get("path") or f"entry {i}"
        missing = [f for f in REQUIRED_FIELDS if not raw.get(f)]
        if missing:
            problems.append(f"{label}: missing {', '.join(missing)}")
            continue
        if raw["level"] not in LEVEL_MAPPING:
            problems.append(f"{label}: level must be one of {sorted(LEVEL_MAPPING)}")
            continue
        if raw["level"] == "operator" and not raw.get("scope"):
            problems.append(f"{label}: operator documents need a scope")
            continue
        if raw["path"] in seen:
            problems.append(f"{label}: listed twice")
            continue
        if not (repo_root / raw["path"]).is_file():
            problems.append(f"{label}: file not found")
            continue
        max_pages = raw.get("max_pages")
        if max_pages is not None and (not isinstance(max_pages, int) or max_pages < 1):
            problems.append(f"{label}: max_pages must be a positive integer")
            continue
        seen.add(raw["path"])
        entries.append(
            CorpusEntry(
                path=raw["path"],
                title=raw["title"],
                issuer=raw["issuer"],
                level=raw["level"],
                scope=raw.get("scope"),
                source_url=raw.get("source_url") or "",
                max_pages=max_pages,
            )
        )

    if problems:
        raise ValueError("corpus.yaml has problems:\n  " + "\n  ".join(problems))
    return entries


def plan(entries: list[CorpusEntry], existing: list[dict[str, Any]]) -> list[tuple[CorpusEntry, str, list[str]]]:
    """Decide per entry: 'skip' (already completed), 'reload' (stale rows to delete) or 'load'.

    Returns (entry, action, ids_to_delete).
    """
    by_path: dict[str, list[dict[str, Any]]] = {}
    for doc in existing:
        by_path.setdefault(doc.get("file_path"), []).append(doc)

    decisions = []
    for entry in entries:
        docs = by_path.get(entry.path, [])
        if any(d.get("ingestion_status") == "completed" for d in docs):
            decisions.append((entry, "skip", []))
        elif docs:
            decisions.append((entry, "reload", [d["id"] for d in docs]))
        else:
            decisions.append((entry, "load", []))
    return decisions


def first_pages(src: Path, max_pages: int, out_dir: Path) -> Path:
    """Write the first max_pages pages of src to out_dir, keeping the file name."""
    reader = PdfReader(str(src))
    writer = PdfWriter()
    for page in reader.pages[:max_pages]:
        writer.add_page(page)
    out = out_dir / src.name
    with open(out, "wb") as f:
        writer.write(f)
    return out


async def ingest(entry: CorpusEntry, repo_root: Path, db, parser, chunker, embedder) -> int:
    """Run one document through the pipeline. Returns the number of chunks stored."""
    src = repo_root / entry.path
    doc = db.insert_document(
        title=entry.title,
        doc_type=entry.doc_type,
        hierarchy_priority=entry.hierarchy_priority,
        file_path=entry.path,
        grid_provider=entry.scope,
    )
    doc_id = doc["id"]
    try:
        db.update_document(uuid.UUID(doc_id), {"ingestion_status": "processing"})
        with tempfile.TemporaryDirectory() as tmp:
            parse_path = first_pages(src, entry.max_pages, Path(tmp)) if entry.max_pages else src
            raw_output, sections = await parser.parse_pdf(str(parse_path))
        db.update_document(uuid.UUID(doc_id), {"raw_reducto_output": raw_output})

        chunks = chunker.chunk_sections(sections, doc_title=entry.title)
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
                "doc_type": entry.doc_type,
                "grid_provider": entry.scope,
                "hierarchy_priority": entry.hierarchy_priority,
                "embedding": embeddings[i],
                "token_count": c.token_count,
            }
            for i, c in enumerate(chunks)
        ])
        db.update_document(uuid.UUID(doc_id), {"ingestion_status": "completed"})
        return len(chunks)
    except Exception:
        db.update_document(uuid.UUID(doc_id), {"ingestion_status": "failed"})
        raise


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--corpus", default="corpus.yaml")
    ap.add_argument("--dry-run", action="store_true", help="show what would happen, change nothing")
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    corpus_path = Path(args.corpus)
    if not corpus_path.is_absolute():
        corpus_path = repo_root / corpus_path

    try:
        entries = load_corpus(corpus_path, repo_root)
    except ValueError as e:
        print(e)
        return 2

    db = DatabaseClient()
    decisions = plan(entries, db.list_documents())

    for entry, action, stale in decisions:
        pages = f", first {entry.max_pages} pages" if entry.max_pages else ""
        note = f" ({len(stale)} stale row(s) to delete)" if stale else ""
        print(f"{action:6}  {entry.path}  [{entry.level}/{entry.scope or '-'}{pages}]{note}")

    if args.dry_run:
        return 0

    settings = get_settings()
    parser = ReductoParser(api_key=settings.reducto_api_key)
    chunker = Chunker(chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap)
    embedder = Embedder(
        api_key=settings.cohere_api_key,
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
    )

    loaded = skipped = failed = 0
    try:
        for entry, action, stale in decisions:
            if action == "skip":
                skipped += 1
                continue
            for doc_id in stale:
                db.delete_document(uuid.UUID(doc_id))
            print(f"\nLoading {entry.path} ...", flush=True)
            try:
                n = await ingest(entry, repo_root, db, parser, chunker, embedder)
                print(f"  stored {n} chunks")
                loaded += 1
            except Exception as e:  # noqa: BLE001 - report and continue with the next document
                print(f"  FAILED: {type(e).__name__}: {e}")
                failed += 1
    finally:
        await parser.close()
        await embedder.close()

    print(f"\nDone: {loaded} loaded, {skipped} skipped, {failed} failed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
