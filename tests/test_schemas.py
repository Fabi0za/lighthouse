import uuid

from app.models.schemas import (
    DocumentCreate,
    DocumentResponse,
    ChunkMetadata,
    QueryRequest,
    QueryResponse,
    QuerySource,
    QueryLogResponse,
)


def test_document_create_valid():
    doc = DocumentCreate(
        title="Grid Provider X Wiring Rules",
        doc_type="grid_provider_rule",
        grid_provider="Provider X",
        hierarchy_priority=10,
    )
    assert doc.title == "Grid Provider X Wiring Rules"
    assert doc.doc_type == "grid_provider_rule"
    assert doc.grid_provider == "Provider X"
    assert doc.hierarchy_priority == 10


def test_document_create_optional_provider():
    doc = DocumentCreate(
        title="General Regulations",
        doc_type="general_regulation",
        hierarchy_priority=1,
    )
    assert doc.grid_provider is None


def test_document_response_has_id_and_status():
    doc = DocumentResponse(
        id=uuid.uuid4(),
        title="Test Doc",
        doc_type="product_manual",
        hierarchy_priority=5,
        ingestion_status="completed",
    )
    assert doc.ingestion_status == "completed"


def test_query_request():
    req = QueryRequest(question="How do I wire component X for Provider Y?")
    assert req.question == "How do I wire component X for Provider Y?"


def test_query_response_structure():
    source = QuerySource(
        document_title="Wiring Manual",
        section="Chapter 3",
        page=42,
    )
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
        doc_type="product_manual",
        hierarchy_priority=5,
    )
    assert meta.page_number == 15
    assert meta.grid_provider is None
