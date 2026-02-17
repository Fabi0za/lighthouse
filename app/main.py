from __future__ import annotations

import os
import tempfile
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, UploadFile, File, Form

from app.models.schemas import (
    DocumentUpdate,
    QueryRequest,
    EvalRunRequest,
)
from app.models.database import DatabaseClient
from app.pipeline import QueryPipeline
from app.ingestion.parser import ReductoParser
from app.ingestion.chunker import Chunker
from app.ingestion.embedder import Embedder


def create_app(
    pipeline: QueryPipeline | None = None,
    db: DatabaseClient | None = None,
    parser: ReductoParser | None = None,
    chunker: Chunker | None = None,
    embedder: Embedder | None = None,
) -> FastAPI:
    app = FastAPI(title="RAG Technical Knowledge Assistant")

    @app.post("/query")
    async def query(request: QueryRequest) -> dict[str, Any]:
        if pipeline is None:
            raise HTTPException(status_code=503, detail="Pipeline not initialized")
        return await pipeline.run(request.question)

    @app.get("/query/{log_id}")
    def get_query_log(log_id: uuid.UUID) -> dict[str, Any]:
        if db is None:
            raise HTTPException(status_code=503, detail="Database not initialized")
        result = db.get_query_log(log_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Query log not found")
        return result

    @app.get("/documents")
    def list_documents() -> list[dict[str, Any]]:
        if db is None:
            raise HTTPException(status_code=503, detail="Database not initialized")
        return db.list_documents()

    @app.put("/documents/{doc_id}")
    def update_document(doc_id: uuid.UUID, update: DocumentUpdate) -> dict[str, Any]:
        if db is None:
            raise HTTPException(status_code=503, detail="Database not initialized")
        updates = update.model_dump(exclude_none=True)
        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")
        return db.update_document(doc_id, updates)

    @app.delete("/documents/{doc_id}")
    def delete_document(doc_id: uuid.UUID) -> dict[str, str]:
        if db is None:
            raise HTTPException(status_code=503, detail="Database not initialized")
        db.delete_chunks_for_document(doc_id)
        db.delete_document(doc_id)
        return {"status": "deleted"}

    @app.post("/ingest")
    async def ingest(
        file: UploadFile = File(...),
        title: str = Form(...),
        doc_type: str = Form(...),
        hierarchy_priority: int = Form(...),
        grid_provider: str | None = Form(None),
    ) -> dict[str, Any]:
        if not all([db, parser, chunker, embedder]):
            raise HTTPException(status_code=503, detail="Ingestion services not initialized")

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name

        try:
            doc = db.insert_document(
                title=title,
                doc_type=doc_type,
                hierarchy_priority=hierarchy_priority,
                file_path=file.filename,
                grid_provider=grid_provider,
            )
            doc_id = doc["id"]

            db.update_document(uuid.UUID(doc_id), {"ingestion_status": "processing"})
            raw_output, sections = await parser.parse_pdf(tmp_path)

            db.update_document(uuid.UUID(doc_id), {"raw_reducto_output": raw_output})

            chunks = chunker.chunk_sections(sections)

            texts = [c.content for c in chunks]
            embeddings = await embedder.embed_texts(texts)

            chunk_records = [
                {
                    "document_id": doc_id,
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

            result = db.update_document(uuid.UUID(doc_id), {"ingestion_status": "completed"})
            return result
        except Exception as e:
            if "doc_id" in locals():
                db.update_document(uuid.UUID(doc_id), {"ingestion_status": "failed"})
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            os.unlink(tmp_path)

    @app.post("/eval/run")
    async def run_eval(request: EvalRunRequest | None = None) -> dict[str, str]:
        return {"status": "not yet implemented"}

    @app.get("/eval/runs")
    def list_eval_runs() -> list[dict[str, Any]]:
        if db is None:
            raise HTTPException(status_code=503, detail="Database not initialized")
        return db.list_eval_runs()

    return app
