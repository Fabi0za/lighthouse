from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile

from app.config import Settings
from app.ingestion.chunker import Chunker
from app.ingestion.embedder import Embedder
from app.ingestion.parser import ReductoParser
from app.ingestion.versions import load_version
from app.models.database import DatabaseClient
from app.models.schemas import (
    DocumentUpdate,
    EvalRunRequest,
    QueryRequest,
)
from app.pipeline import QueryPipeline
from eval.runner import EvalRunner


def create_app(
    pipeline: QueryPipeline | None = None,
    db: DatabaseClient | None = None,
    parser: ReductoParser | None = None,
    chunker: Chunker | None = None,
    embedder: Embedder | None = None,
    settings: Settings | None = None,
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

    @app.post("/ingest")
    async def ingest(
        file: UploadFile = File(...),
        source_id: str = Form(...),
        title: str = Form(...),
        address: str | None = Form(None),
    ) -> dict[str, Any]:
        """Load an uploaded file as a version of an existing source (see app/ingestion/versions.py)."""
        if not all([db, parser, chunker, embedder]):
            raise HTTPException(status_code=503, detail="Ingestion services not initialized")

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(await file.read())
            tmp_path = Path(tmp.name)
        try:
            action, document_id = await load_version(
                db, {"id": source_id}, tmp_path, title, address,
                parser, chunker, embedder, stored_path=file.filename,
            )
            return {"action": action, "document_id": document_id}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            tmp_path.unlink(missing_ok=True)

    @app.post("/eval/run")
    async def run_eval(request: EvalRunRequest | None = None) -> dict[str, Any]:
        if not all([db, pipeline]):
            raise HTTPException(status_code=503, detail="Pipeline not initialized")

        config_snapshot = {}
        if settings:
            config_snapshot = {
                "embedding_model": settings.embedding_model,
                "llm_model": settings.llm_model,
                "chunk_size": settings.chunk_size,
                "chunk_overlap": settings.chunk_overlap,
                "retrieval_top_k": settings.retrieval_top_k,
                "rerank_top_n": settings.rerank_top_n,
            }

        notes = request.notes if request else None
        judge_key = settings.anthropic_api_key if settings else None
        runner = EvalRunner(
            db=db,
            pipeline=pipeline,
            config_snapshot=config_snapshot,
            notes=notes,
            anthropic_api_key=judge_key,
        )
        return await runner.run()

    @app.get("/eval/runs")
    def list_eval_runs() -> list[dict[str, Any]]:
        if db is None:
            raise HTTPException(status_code=503, detail="Database not initialized")
        return db.list_eval_runs()

    return app
