import uuid

from app.models import schemas
from app.models.schemas import (
    ChunkMetadata,
    DocumentResponse,
    DocumentUpdate,
    QueryRequest,
    QueryResponse,
    QuerySource,
)


def test_document_response_is_a_version():
    doc = DocumentResponse(
        id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        status="current",
        title="Test Doc (V1.3)",
        ingestion_status="completed",
    )
    assert doc.status == "current"
    assert not hasattr(doc, "doc_type")
    assert not hasattr(doc, "grid_provider")


def test_document_update_allows_only_title():
    assert set(DocumentUpdate.model_fields) == {"title"}


def test_document_create_removed():
    assert not hasattr(schemas, "DocumentCreate")


def test_query_request():
    req = QueryRequest(question="How do I wire component X for Provider Y?")
    assert req.question == "How do I wire component X for Provider Y?"


def test_query_response_structure():
    source = QuerySource(document_title="Wiring Manual", section="Chapter 3", page=42)
    resp = QueryResponse(
        answer="You should wire it this way.",
        sources=[source],
        confidence="high",
        log_id=uuid.uuid4(),
    )
    assert len(resp.sources) == 1
    assert resp.confidence == "high"


def test_chunk_metadata():
    meta = ChunkMetadata(
        document_id=uuid.uuid4(),
        section_title="Wiring Diagrams",
        page_number=15,
        chunk_index=3,
    )
    assert meta.page_number == 15
    assert set(ChunkMetadata.model_fields) == {"document_id", "section_title", "page_number", "chunk_index"}
