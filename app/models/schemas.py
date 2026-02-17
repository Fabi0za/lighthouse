from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel


class DocumentCreate(BaseModel):
    title: str
    doc_type: str
    grid_provider: str | None = None
    hierarchy_priority: int


class DocumentResponse(BaseModel):
    id: uuid.UUID
    title: str
    doc_type: str
    grid_provider: str | None = None
    hierarchy_priority: int
    ingestion_status: str
    file_path: str | None = None


class DocumentUpdate(BaseModel):
    title: str | None = None
    doc_type: str | None = None
    grid_provider: str | None = None
    hierarchy_priority: int | None = None


class ChunkMetadata(BaseModel):
    document_id: uuid.UUID
    section_title: str
    page_number: int
    chunk_index: int
    doc_type: str
    grid_provider: str | None = None
    hierarchy_priority: int


class QueryRequest(BaseModel):
    question: str


class QuerySource(BaseModel):
    document_title: str
    section: str
    page: int


class QueryResponse(BaseModel):
    answer: str
    sources: list[QuerySource]
    confidence: str
    log_id: uuid.UUID


class QueryLogResponse(BaseModel):
    id: uuid.UUID
    question: str
    detected_filters: dict[str, Any]
    retrieved_chunks: list[dict[str, Any]]
    reranked_chunks: list[dict[str, Any]]
    llm_prompt: str
    llm_response: str
    formatted_answer: dict[str, Any]
    model_used: str
    latency_ms: int


class EvalRunRequest(BaseModel):
    notes: str | None = None


class EvalRunResponse(BaseModel):
    id: uuid.UUID
    config_snapshot: dict[str, Any]
    aggregate_scores: dict[str, Any]
    results: list[dict[str, Any]]
    notes: str | None = None
