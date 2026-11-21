# Hierarchical RAG Technical Knowledge Assistant — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a hierarchical RAG system that lets field engineers query electrical installation documents and get cited, hierarchy-aware answers via a FastAPI API.

**Architecture:** PDF ingestion via Reducto with metadata-enriched chunking into Supabase pgvector. Query pipeline: parse question → vector search (top-20) → metadata-aware re-rank (top-8) → LLM generates cited answer. Full query trace logging. Eval framework with golden dataset.

**Tech Stack:** Python 3.12, FastAPI, Supabase (pgvector), Reducto API, httpx, pydantic-settings, tiktoken. LLM/embedding providers are configurable.

---

### Task 1: Project Scaffolding & Dependencies

**Files:**
- Create: `pyproject.toml`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `app/__init__.py`
- Create: `app/config.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

**Step 1: Create pyproject.toml**

```toml
[project]
name = "rag"
version = "0.1.0"
description = "Hierarchical RAG for electrical installation technical documents"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.34.0",
    "supabase>=2.0.0",
    "httpx>=0.28.0",
    "pydantic>=2.0.0",
    "pydantic-settings>=2.0.0",
    "tiktoken>=0.8.0",
    "python-multipart>=0.0.18",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
    "pytest-httpx>=0.35.0",
    "ruff>=0.8.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
target-version = "py312"
line-length = 100
```

**Step 2: Create .env.example**

```env
SUPABASE_URL=http://localhost:54321
SUPABASE_KEY=your-supabase-anon-key
SUPABASE_SERVICE_KEY=your-supabase-service-role-key
REDUCTO_API_KEY=your-reducto-api-key
OPENAI_API_KEY=your-openai-api-key
ANTHROPIC_API_KEY=your-anthropic-api-key
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIMENSIONS=1536
LLM_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-4-6
CHUNK_SIZE=500
CHUNK_OVERLAP=50
RETRIEVAL_TOP_K=20
RERANK_TOP_N=8
```

**Step 3: Create .gitignore**

```
__pycache__/
*.pyc
.env
.venv/
*.egg-info/
dist/
.ruff_cache/
.pytest_cache/
```

**Step 4: Create app/config.py**

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    supabase_url: str
    supabase_key: str
    supabase_service_key: str
    reducto_api_key: str
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    llm_provider: str = "anthropic"
    llm_model: str = "claude-sonnet-4-6"
    chunk_size: int = 500
    chunk_overlap: int = 50
    retrieval_top_k: int = 20
    rerank_top_n: int = 8

    model_config = {"env_file": ".env"}


settings = Settings()
```

**Step 5: Create empty __init__.py files and conftest.py**

`app/__init__.py` — empty file.

`tests/__init__.py` — empty file.

`tests/conftest.py`:
```python
import pytest
from app.config import Settings


@pytest.fixture
def test_settings():
    return Settings(
        supabase_url="http://localhost:54321",
        supabase_key="test-key",
        supabase_service_key="test-service-key",
        reducto_api_key="test-reducto-key",
        openai_api_key="test-openai-key",
        anthropic_api_key="test-anthropic-key",
    )
```

**Step 6: Install dependencies**

Run: `cd /path/to/lighthouse && python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"`
Expected: All packages installed successfully.

**Step 7: Run a sanity check**

Run: `python -c "from app.config import Settings; print('Config loaded')"`
Expected: `Config loaded` (may warn about missing .env, that's fine)

**Step 8: Commit**

```bash
git add pyproject.toml .env.example .gitignore app/__init__.py app/config.py tests/__init__.py tests/conftest.py
git commit -m "feat: project scaffolding with dependencies and config"
```

---

### Task 2: Pydantic Schemas

**Files:**
- Create: `app/models/__init__.py`
- Create: `app/models/schemas.py`
- Create: `tests/test_schemas.py`

**Step 1: Write the failing test**

`tests/test_schemas.py`:
```python
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
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_schemas.py -v`
Expected: FAIL — cannot import schemas

**Step 3: Write minimal implementation**

`app/models/__init__.py` — empty file.

`app/models/schemas.py`:
```python
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
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_schemas.py -v`
Expected: All 6 tests PASS

**Step 5: Commit**

```bash
git add app/models/ tests/test_schemas.py
git commit -m "feat: add Pydantic schemas for documents, queries, eval"
```

---

### Task 3: Supabase Database Client

**Files:**
- Create: `app/models/database.py`
- Create: `tests/test_database.py`

This module wraps the Supabase client and provides typed methods for each table operation. Tests mock the Supabase client.

**Step 1: Write the failing test**

`tests/test_database.py`:
```python
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.database import DatabaseClient


@pytest.fixture
def mock_supabase():
    client = MagicMock()
    client.table.return_value = client
    client.select.return_value = client
    client.insert.return_value = client
    client.update.return_value = client
    client.delete.return_value = client
    client.eq.return_value = client
    client.execute.return_value = MagicMock(data=[{"id": str(uuid.uuid4()), "title": "Test"}])
    return client


@pytest.fixture
def db(mock_supabase):
    return DatabaseClient(client=mock_supabase)


def test_list_documents(db, mock_supabase):
    result = db.list_documents()
    mock_supabase.table.assert_called_with("documents")
    assert len(result) == 1


def test_insert_document(db, mock_supabase):
    result = db.insert_document(
        title="Test Doc",
        doc_type="product_manual",
        hierarchy_priority=5,
        file_path="/tmp/test.pdf",
    )
    mock_supabase.table.assert_called_with("documents")
    assert result is not None


def test_delete_document_chunks(db, mock_supabase):
    doc_id = uuid.uuid4()
    db.delete_chunks_for_document(doc_id)
    mock_supabase.table.assert_called_with("document_chunks")


def test_insert_chunks(db, mock_supabase):
    doc_id = uuid.uuid4()
    chunks = [
        {
            "document_id": str(doc_id),
            "content": "test content",
            "section_title": "Section 1",
            "page_number": 1,
            "chunk_index": 0,
            "doc_type": "product_manual",
            "hierarchy_priority": 5,
            "embedding": [0.1] * 1536,
            "token_count": 50,
        }
    ]
    db.insert_chunks(chunks)
    mock_supabase.table.assert_called_with("document_chunks")
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_database.py -v`
Expected: FAIL — cannot import DatabaseClient

**Step 3: Write minimal implementation**

`app/models/database.py`:
```python
from __future__ import annotations

import uuid
from typing import Any

from supabase import create_client

from app.config import settings


class DatabaseClient:
    def __init__(self, client=None):
        if client is None:
            self.client = create_client(settings.supabase_url, settings.supabase_service_key)
        else:
            self.client = client

    def list_documents(self) -> list[dict[str, Any]]:
        return self.client.table("documents").select("*").execute().data

    def get_document(self, doc_id: uuid.UUID) -> dict[str, Any] | None:
        result = (
            self.client.table("documents")
            .select("*")
            .eq("id", str(doc_id))
            .execute()
        )
        return result.data[0] if result.data else None

    def insert_document(
        self,
        title: str,
        doc_type: str,
        hierarchy_priority: int,
        file_path: str,
        grid_provider: str | None = None,
    ) -> dict[str, Any]:
        data = {
            "title": title,
            "doc_type": doc_type,
            "hierarchy_priority": hierarchy_priority,
            "file_path": file_path,
            "ingestion_status": "pending",
        }
        if grid_provider:
            data["grid_provider"] = grid_provider
        return self.client.table("documents").insert(data).execute().data[0]

    def update_document(self, doc_id: uuid.UUID, updates: dict[str, Any]) -> dict[str, Any]:
        return (
            self.client.table("documents")
            .update(updates)
            .eq("id", str(doc_id))
            .execute()
            .data[0]
        )

    def delete_document(self, doc_id: uuid.UUID) -> None:
        self.client.table("documents").delete().eq("id", str(doc_id)).execute()

    def insert_chunks(self, chunks: list[dict[str, Any]]) -> None:
        self.client.table("document_chunks").insert(chunks).execute()

    def delete_chunks_for_document(self, doc_id: uuid.UUID) -> None:
        self.client.table("document_chunks").delete().eq("document_id", str(doc_id)).execute()

    def vector_search(self, query_embedding: list[float], top_k: int = 20) -> list[dict[str, Any]]:
        return self.client.rpc(
            "match_document_chunks",
            {
                "query_embedding": query_embedding,
                "match_count": top_k,
            },
        ).execute().data

    def insert_query_log(self, log_data: dict[str, Any]) -> dict[str, Any]:
        return self.client.table("query_logs").insert(log_data).execute().data[0]

    def get_query_log(self, log_id: uuid.UUID) -> dict[str, Any] | None:
        result = (
            self.client.table("query_logs")
            .select("*")
            .eq("id", str(log_id))
            .execute()
        )
        return result.data[0] if result.data else None

    def get_eval_questions(self) -> list[dict[str, Any]]:
        return self.client.table("eval_questions").select("*").execute().data

    def insert_eval_run(self, run_data: dict[str, Any]) -> dict[str, Any]:
        return self.client.table("eval_runs").insert(run_data).execute().data[0]

    def list_eval_runs(self) -> list[dict[str, Any]]:
        return self.client.table("eval_runs").select("*").execute().data

    def get_known_providers(self) -> list[str]:
        result = (
            self.client.table("documents")
            .select("grid_provider")
            .not_.is_("grid_provider", "null")
            .execute()
        )
        return list({row["grid_provider"] for row in result.data})
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_database.py -v`
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add app/models/database.py tests/test_database.py
git commit -m "feat: add Supabase database client with typed methods"
```

---

### Task 4: Embedding Provider Abstraction

**Files:**
- Create: `app/ingestion/__init__.py`
- Create: `app/ingestion/embedder.py`
- Create: `tests/test_embedder.py`

**Step 1: Write the failing test**

`tests/test_embedder.py`:
```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.ingestion.embedder import Embedder


@pytest.fixture
def embedder():
    return Embedder(api_key="test-key", model="text-embedding-3-small", dimensions=1536)


def test_embedder_init(embedder):
    assert embedder.model == "text-embedding-3-small"
    assert embedder.dimensions == 1536


@pytest.mark.asyncio
async def test_embed_single_text(embedder):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [{"embedding": [0.1] * 1536}]
    }
    with patch.object(embedder.client, "post", new_callable=AsyncMock, return_value=mock_response):
        result = await embedder.embed_texts(["test text"])
        assert len(result) == 1
        assert len(result[0]) == 1536


@pytest.mark.asyncio
async def test_embed_multiple_texts(embedder):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [
            {"embedding": [0.1] * 1536},
            {"embedding": [0.2] * 1536},
        ]
    }
    with patch.object(embedder.client, "post", new_callable=AsyncMock, return_value=mock_response):
        result = await embedder.embed_texts(["text one", "text two"])
        assert len(result) == 2
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_embedder.py -v`
Expected: FAIL — cannot import Embedder

**Step 3: Write minimal implementation**

`app/ingestion/__init__.py` — empty file.

`app/ingestion/embedder.py`:
```python
from __future__ import annotations

import httpx


class Embedder:
    def __init__(self, api_key: str, model: str = "text-embedding-3-small", dimensions: int = 1536):
        self.api_key = api_key
        self.model = model
        self.dimensions = dimensions
        self.client = httpx.AsyncClient(
            base_url="https://api.openai.com/v1",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=60.0,
        )

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        response = await self.client.post(
            "/embeddings",
            json={
                "input": texts,
                "model": self.model,
                "dimensions": self.dimensions,
            },
        )
        response.raise_for_status()
        data = response.json()
        return [item["embedding"] for item in data["data"]]

    async def embed_query(self, text: str) -> list[float]:
        results = await self.embed_texts([text])
        return results[0]

    async def close(self):
        await self.client.aclose()
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_embedder.py -v`
Expected: All 3 tests PASS

**Step 5: Commit**

```bash
git add app/ingestion/__init__.py app/ingestion/embedder.py tests/test_embedder.py
git commit -m "feat: add embedding provider with OpenAI API integration"
```

---

### Task 5: Chunking Strategy

**Files:**
- Create: `app/ingestion/chunker.py`
- Create: `tests/test_chunker.py`

**Step 1: Write the failing test**

`tests/test_chunker.py`:
```python
from app.ingestion.chunker import Chunker, Chunk


def test_chunker_splits_text():
    chunker = Chunker(chunk_size=50, chunk_overlap=10)
    text = "word " * 200  # ~200 tokens
    chunks = chunker.chunk_text(text, section_title="Section 1", page_number=1)
    assert len(chunks) > 1
    assert all(isinstance(c, Chunk) for c in chunks)


def test_chunk_has_metadata():
    chunker = Chunker(chunk_size=50, chunk_overlap=10)
    text = "word " * 200
    chunks = chunker.chunk_text(text, section_title="Wiring Rules", page_number=5)
    assert chunks[0].section_title == "Wiring Rules"
    assert chunks[0].page_number == 5
    assert chunks[0].chunk_index == 0
    assert chunks[1].chunk_index == 1


def test_chunk_respects_size_limit():
    chunker = Chunker(chunk_size=50, chunk_overlap=10)
    text = "word " * 200
    chunks = chunker.chunk_text(text, section_title="Test", page_number=1)
    for chunk in chunks:
        assert chunk.token_count <= 55  # small tolerance


def test_chunk_overlap():
    chunker = Chunker(chunk_size=50, chunk_overlap=10)
    text = "word " * 200
    chunks = chunker.chunk_text(text, section_title="Test", page_number=1)
    # Verify overlap: end of chunk N should overlap with start of chunk N+1
    if len(chunks) >= 2:
        words_0 = chunks[0].content.split()
        words_1 = chunks[1].content.split()
        overlap_words = words_0[-10:]
        assert overlap_words == words_1[:10]


def test_short_text_single_chunk():
    chunker = Chunker(chunk_size=500, chunk_overlap=50)
    text = "Short text that fits in one chunk."
    chunks = chunker.chunk_text(text, section_title="Intro", page_number=1)
    assert len(chunks) == 1
    assert chunks[0].content == "Short text that fits in one chunk."


def test_chunk_from_reducto_sections():
    chunker = Chunker(chunk_size=100, chunk_overlap=20)
    sections = [
        {"title": "Overview", "content": "word " * 50, "page": 1},
        {"title": "Wiring", "content": "wire " * 150, "page": 3},
    ]
    all_chunks = chunker.chunk_sections(sections)
    assert all_chunks[0].section_title == "Overview"
    wiring_chunks = [c for c in all_chunks if c.section_title == "Wiring"]
    assert len(wiring_chunks) > 1
    assert wiring_chunks[0].page_number == 3
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_chunker.py -v`
Expected: FAIL — cannot import Chunker

**Step 3: Write minimal implementation**

`app/ingestion/chunker.py`:
```python
from __future__ import annotations

from dataclasses import dataclass

import tiktoken


@dataclass
class Chunk:
    content: str
    section_title: str
    page_number: int
    chunk_index: int
    token_count: int


class Chunker:
    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.encoder = tiktoken.get_encoding("cl100k_base")

    def chunk_text(
        self,
        text: str,
        section_title: str,
        page_number: int,
        start_index: int = 0,
    ) -> list[Chunk]:
        words = text.split()
        if not words:
            return []

        chunks = []
        pos = 0
        chunk_idx = start_index

        while pos < len(words):
            # Take chunk_size worth of tokens (approximate with words, then verify)
            end = pos + self.chunk_size
            chunk_words = words[pos:end]
            chunk_text = " ".join(chunk_words)
            token_count = len(self.encoder.encode(chunk_text))

            # Adjust if over token limit
            while token_count > self.chunk_size and len(chunk_words) > 1:
                chunk_words = chunk_words[:-1]
                chunk_text = " ".join(chunk_words)
                token_count = len(self.encoder.encode(chunk_text))

            chunks.append(
                Chunk(
                    content=chunk_text,
                    section_title=section_title,
                    page_number=page_number,
                    chunk_index=chunk_idx,
                    token_count=token_count,
                )
            )
            chunk_idx += 1

            # Advance position, accounting for overlap
            advance = len(chunk_words) - self.chunk_overlap
            if advance <= 0:
                advance = max(1, len(chunk_words))
            pos += advance

        return chunks

    def chunk_sections(
        self,
        sections: list[dict],
    ) -> list[Chunk]:
        all_chunks = []
        idx = 0
        for section in sections:
            chunks = self.chunk_text(
                text=section["content"],
                section_title=section["title"],
                page_number=section.get("page", 1),
                start_index=idx,
            )
            all_chunks.extend(chunks)
            idx += len(chunks)
        return all_chunks
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_chunker.py -v`
Expected: All 6 tests PASS

**Step 5: Commit**

```bash
git add app/ingestion/chunker.py tests/test_chunker.py
git commit -m "feat: add section-aware chunking with token counting"
```

---

### Task 6: Reducto PDF Parser Integration

**Files:**
- Create: `app/ingestion/parser.py`
- Create: `tests/test_parser.py`

**Step 1: Write the failing test**

`tests/test_parser.py`:
```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.ingestion.parser import ReductoParser


@pytest.fixture
def parser():
    return ReductoParser(api_key="test-key")


@pytest.mark.asyncio
async def test_parse_pdf_returns_sections(parser):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "result": {
            "blocks": [
                {"type": "header", "content": "Chapter 1: Overview", "page": 1},
                {"type": "text", "content": "This is the overview section content.", "page": 1},
                {"type": "header", "content": "Chapter 2: Wiring", "page": 3},
                {"type": "text", "content": "Wiring instructions go here.", "page": 3},
            ]
        }
    }

    with patch.object(parser.client, "post", new_callable=AsyncMock, return_value=mock_response):
        raw_output, sections = await parser.parse_pdf("/tmp/test.pdf")
        assert len(sections) == 2
        assert sections[0]["title"] == "Chapter 1: Overview"
        assert sections[0]["page"] == 1
        assert "overview section content" in sections[0]["content"]
        assert sections[1]["title"] == "Chapter 2: Wiring"


@pytest.mark.asyncio
async def test_parse_pdf_preserves_raw_output(parser):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "result": {
            "blocks": [
                {"type": "text", "content": "Some content", "page": 1},
            ]
        }
    }

    with patch.object(parser.client, "post", new_callable=AsyncMock, return_value=mock_response):
        raw_output, sections = await parser.parse_pdf("/tmp/test.pdf")
        assert raw_output == mock_response.json.return_value


@pytest.mark.asyncio
async def test_parse_pdf_no_headers_uses_default(parser):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "result": {
            "blocks": [
                {"type": "text", "content": "Content without headers.", "page": 1},
            ]
        }
    }

    with patch.object(parser.client, "post", new_callable=AsyncMock, return_value=mock_response):
        raw_output, sections = await parser.parse_pdf("/tmp/test.pdf")
        assert len(sections) == 1
        assert sections[0]["title"] == "Untitled Section"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_parser.py -v`
Expected: FAIL — cannot import ReductoParser

**Step 3: Write minimal implementation**

`app/ingestion/parser.py`:
```python
from __future__ import annotations

from typing import Any

import httpx


class ReductoParser:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = httpx.AsyncClient(
            base_url="https://api.reducto.ai/v1",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=120.0,
        )

    async def parse_pdf(self, file_path: str) -> tuple[dict[str, Any], list[dict]]:
        """Parse a PDF file via Reducto API.

        Returns:
            Tuple of (raw_output, sections) where sections is a list of
            {"title": str, "content": str, "page": int} dicts.
        """
        with open(file_path, "rb") as f:
            response = await self.client.post(
                "/parse",
                files={"file": (file_path.split("/")[-1], f, "application/pdf")},
            )
        response.raise_for_status()
        raw_output = response.json()

        sections = self._extract_sections(raw_output)
        return raw_output, sections

    def _extract_sections(self, raw_output: dict[str, Any]) -> list[dict]:
        blocks = raw_output.get("result", {}).get("blocks", [])
        sections: list[dict] = []
        current_title = "Untitled Section"
        current_content: list[str] = []
        current_page = 1

        for block in blocks:
            if block.get("type") == "header":
                # Save previous section if it has content
                if current_content:
                    sections.append({
                        "title": current_title,
                        "content": " ".join(current_content),
                        "page": current_page,
                    })
                    current_content = []
                current_title = block.get("content", "Untitled Section")
                current_page = block.get("page", current_page)
            else:
                current_content.append(block.get("content", ""))
                if not sections and current_title == "Untitled Section":
                    current_page = block.get("page", current_page)

        # Don't forget the last section
        if current_content:
            sections.append({
                "title": current_title,
                "content": " ".join(current_content),
                "page": current_page,
            })

        return sections

    async def close(self):
        await self.client.aclose()
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_parser.py -v`
Expected: All 3 tests PASS

**Step 5: Commit**

```bash
git add app/ingestion/parser.py tests/test_parser.py
git commit -m "feat: add Reducto PDF parser with section extraction"
```

---

### Task 7: Query Parser (Provider/Component Detection)

**Files:**
- Create: `app/retrieval/__init__.py`
- Create: `app/retrieval/query_parser.py`
- Create: `tests/test_query_parser.py`

**Step 1: Write the failing test**

`tests/test_query_parser.py`:
```python
from app.retrieval.query_parser import QueryParser


def test_detect_known_provider():
    parser = QueryParser(known_providers=["Provider X", "Provider Y", "GridCo"])
    result = parser.parse("How do I wire component A for Provider X?")
    assert result.detected_provider == "Provider X"


def test_detect_no_provider():
    parser = QueryParser(known_providers=["Provider X", "Provider Y"])
    result = parser.parse("What is the general wiring standard?")
    assert result.detected_provider is None


def test_case_insensitive_match():
    parser = QueryParser(known_providers=["Provider X"])
    result = parser.parse("Rules for provider x installations")
    assert result.detected_provider == "Provider X"


def test_query_preserved():
    parser = QueryParser(known_providers=[])
    result = parser.parse("How do I install a meter?")
    assert result.original_question == "How do I install a meter?"


def test_filters_dict():
    parser = QueryParser(known_providers=["GridCo"])
    result = parser.parse("GridCo compliance requirements")
    filters = result.to_filters()
    assert filters["grid_provider"] == "GridCo"


def test_filters_empty_when_no_match():
    parser = QueryParser(known_providers=["GridCo"])
    result = parser.parse("General wiring standards")
    filters = result.to_filters()
    assert "grid_provider" not in filters
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_query_parser.py -v`
Expected: FAIL — cannot import QueryParser

**Step 3: Write minimal implementation**

`app/retrieval/__init__.py` — empty file.

`app/retrieval/query_parser.py`:
```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ParsedQuery:
    original_question: str
    detected_provider: str | None = None

    def to_filters(self) -> dict[str, str]:
        filters = {}
        if self.detected_provider:
            filters["grid_provider"] = self.detected_provider
        return filters


class QueryParser:
    def __init__(self, known_providers: list[str]):
        self.known_providers = known_providers

    def parse(self, question: str) -> ParsedQuery:
        question_lower = question.lower()
        detected_provider = None

        for provider in self.known_providers:
            if provider.lower() in question_lower:
                detected_provider = provider
                break

        return ParsedQuery(
            original_question=question,
            detected_provider=detected_provider,
        )
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_query_parser.py -v`
Expected: All 6 tests PASS

**Step 5: Commit**

```bash
git add app/retrieval/__init__.py app/retrieval/query_parser.py tests/test_query_parser.py
git commit -m "feat: add query parser for grid provider detection"
```

---

### Task 8: Metadata-Aware Re-Ranker

**Files:**
- Create: `app/retrieval/reranker.py`
- Create: `tests/test_reranker.py`

**Step 1: Write the failing test**

`tests/test_reranker.py`:
```python
import uuid

from app.retrieval.reranker import Reranker


def _chunk(
    content="test",
    similarity=0.8,
    doc_type="general_regulation",
    grid_provider=None,
    hierarchy_priority=1,
):
    return {
        "id": str(uuid.uuid4()),
        "content": content,
        "section_title": "Section",
        "page_number": 1,
        "doc_type": doc_type,
        "grid_provider": grid_provider,
        "hierarchy_priority": hierarchy_priority,
        "similarity": similarity,
    }


def test_reranker_boosts_matching_provider():
    reranker = Reranker(top_n=2)
    chunks = [
        _chunk(content="general rule", similarity=0.9, hierarchy_priority=1),
        _chunk(content="provider specific", similarity=0.7, grid_provider="GridCo", hierarchy_priority=5),
    ]
    result = reranker.rerank(chunks, detected_provider="GridCo")
    assert result[0]["content"] == "provider specific"


def test_reranker_applies_hierarchy_priority():
    reranker = Reranker(top_n=2)
    chunks = [
        _chunk(content="low priority", similarity=0.85, hierarchy_priority=1),
        _chunk(content="high priority", similarity=0.80, hierarchy_priority=10),
    ]
    result = reranker.rerank(chunks, detected_provider=None)
    assert result[0]["content"] == "high priority"


def test_reranker_limits_to_top_n():
    reranker = Reranker(top_n=3)
    chunks = [_chunk(similarity=0.9 - i * 0.1) for i in range(10)]
    result = reranker.rerank(chunks, detected_provider=None)
    assert len(result) == 3


def test_reranker_preserves_scores():
    reranker = Reranker(top_n=5)
    chunks = [_chunk(similarity=0.8)]
    result = reranker.rerank(chunks, detected_provider=None)
    assert "rerank_score" in result[0]


def test_reranker_no_chunks():
    reranker = Reranker(top_n=5)
    result = reranker.rerank([], detected_provider=None)
    assert result == []
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_reranker.py -v`
Expected: FAIL — cannot import Reranker

**Step 3: Write minimal implementation**

`app/retrieval/reranker.py`:
```python
from __future__ import annotations

from typing import Any


class Reranker:
    def __init__(
        self,
        top_n: int = 8,
        provider_boost: float = 0.3,
        hierarchy_weight: float = 0.02,
    ):
        self.top_n = top_n
        self.provider_boost = provider_boost
        self.hierarchy_weight = hierarchy_weight

    def rerank(
        self,
        chunks: list[dict[str, Any]],
        detected_provider: str | None,
    ) -> list[dict[str, Any]]:
        if not chunks:
            return []

        scored = []
        for chunk in chunks:
            score = chunk.get("similarity", 0.0)

            # Boost chunks from detected provider
            if detected_provider and chunk.get("grid_provider") == detected_provider:
                score += self.provider_boost

            # Boost by hierarchy priority
            score += chunk.get("hierarchy_priority", 0) * self.hierarchy_weight

            scored.append({**chunk, "rerank_score": score})

        scored.sort(key=lambda c: c["rerank_score"], reverse=True)
        return scored[: self.top_n]
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_reranker.py -v`
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add app/retrieval/reranker.py tests/test_reranker.py
git commit -m "feat: add metadata-aware re-ranker with provider boost and hierarchy weighting"
```

---

### Task 9: Vector Search Module

**Files:**
- Create: `app/retrieval/search.py`
- Create: `tests/test_search.py`

**Step 1: Write the failing test**

`tests/test_search.py`:
```python
import uuid
from unittest.mock import MagicMock

import pytest

from app.retrieval.search import VectorSearch


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.vector_search.return_value = [
        {
            "id": str(uuid.uuid4()),
            "content": "Wiring instructions for component X.",
            "section_title": "Wiring",
            "page_number": 5,
            "doc_type": "product_manual",
            "grid_provider": None,
            "hierarchy_priority": 5,
            "similarity": 0.85,
        },
        {
            "id": str(uuid.uuid4()),
            "content": "General wiring standards.",
            "section_title": "Standards",
            "page_number": 2,
            "doc_type": "general_regulation",
            "grid_provider": None,
            "hierarchy_priority": 1,
            "similarity": 0.78,
        },
    ]
    return db


@pytest.fixture
def mock_embedder():
    embedder = MagicMock()
    embedder.embed_query = MagicMock(return_value=[0.1] * 1536)
    return embedder


def test_search_returns_chunks(mock_db, mock_embedder):
    search = VectorSearch(db=mock_db, embedder=mock_embedder, top_k=20)
    results = search.search("How do I wire component X?")
    assert len(results) == 2
    mock_embedder.embed_query.assert_called_once_with("How do I wire component X?")
    mock_db.vector_search.assert_called_once()


def test_search_passes_top_k(mock_db, mock_embedder):
    search = VectorSearch(db=mock_db, embedder=mock_embedder, top_k=10)
    search.search("test query")
    mock_db.vector_search.assert_called_once_with([0.1] * 1536, 10)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_search.py -v`
Expected: FAIL — cannot import VectorSearch

**Step 3: Write minimal implementation**

`app/retrieval/search.py`:
```python
from __future__ import annotations

from typing import Any

from app.ingestion.embedder import Embedder
from app.models.database import DatabaseClient


class VectorSearch:
    def __init__(self, db: DatabaseClient, embedder: Embedder, top_k: int = 20):
        self.db = db
        self.embedder = embedder
        self.top_k = top_k

    def search(self, query: str) -> list[dict[str, Any]]:
        embedding = self.embedder.embed_query(query)
        return self.db.vector_search(embedding, self.top_k)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_search.py -v`
Expected: All 2 tests PASS

**Step 5: Commit**

```bash
git add app/retrieval/search.py tests/test_search.py
git commit -m "feat: add vector search module"
```

---

### Task 10: LLM Provider Abstraction

**Files:**
- Create: `app/generation/__init__.py`
- Create: `app/generation/llm.py`
- Create: `tests/test_llm.py`

**Step 1: Write the failing test**

`tests/test_llm.py`:
```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.generation.llm import LLMClient


@pytest.fixture
def anthropic_client():
    return LLMClient(
        provider="anthropic",
        api_key="test-key",
        model="claude-sonnet-4-6",
    )


@pytest.fixture
def openai_client():
    return LLMClient(
        provider="openai",
        api_key="test-key",
        model="gpt-4o",
    )


def test_anthropic_client_init(anthropic_client):
    assert anthropic_client.provider == "anthropic"
    assert anthropic_client.model == "claude-sonnet-4-6"


def test_openai_client_init(openai_client):
    assert openai_client.provider == "openai"


@pytest.mark.asyncio
async def test_anthropic_generate(anthropic_client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "content": [{"type": "text", "text": "The answer is 42."}]
    }
    with patch.object(
        anthropic_client.client, "post", new_callable=AsyncMock, return_value=mock_response
    ):
        result = await anthropic_client.generate(
            system_prompt="You are a helpful assistant.",
            user_prompt="What is the answer?",
        )
        assert result == "The answer is 42."


@pytest.mark.asyncio
async def test_openai_generate(openai_client):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "The answer is 42."}}]
    }
    with patch.object(
        openai_client.client, "post", new_callable=AsyncMock, return_value=mock_response
    ):
        result = await openai_client.generate(
            system_prompt="You are a helpful assistant.",
            user_prompt="What is the answer?",
        )
        assert result == "The answer is 42."
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_llm.py -v`
Expected: FAIL — cannot import LLMClient

**Step 3: Write minimal implementation**

`app/generation/__init__.py` — empty file.

`app/generation/llm.py`:
```python
from __future__ import annotations

import httpx


class LLMClient:
    def __init__(self, provider: str, api_key: str, model: str):
        self.provider = provider
        self.model = model

        if provider == "anthropic":
            self.client = httpx.AsyncClient(
                base_url="https://api.anthropic.com/v1",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                timeout=120.0,
            )
        elif provider == "openai":
            self.client = httpx.AsyncClient(
                base_url="https://api.openai.com/v1",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                timeout=120.0,
            )
        else:
            raise ValueError(f"Unsupported LLM provider: {provider}")

    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        if self.provider == "anthropic":
            return await self._generate_anthropic(system_prompt, user_prompt)
        elif self.provider == "openai":
            return await self._generate_openai(system_prompt, user_prompt)
        raise ValueError(f"Unsupported provider: {self.provider}")

    async def _generate_anthropic(self, system_prompt: str, user_prompt: str) -> str:
        response = await self.client.post(
            "/messages",
            json={
                "model": self.model,
                "max_tokens": 4096,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_prompt}],
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["content"][0]["text"]

    async def _generate_openai(self, system_prompt: str, user_prompt: str) -> str:
        response = await self.client.post(
            "/chat/completions",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]

    async def close(self):
        await self.client.aclose()
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_llm.py -v`
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add app/generation/__init__.py app/generation/llm.py tests/test_llm.py
git commit -m "feat: add LLM client abstraction for Anthropic and OpenAI"
```

---

### Task 11: Prompt Templates

**Files:**
- Create: `app/generation/prompts.py`
- Create: `tests/test_prompts.py`

**Step 1: Write the failing test**

`tests/test_prompts.py`:
```python
from app.generation.prompts import build_system_prompt, build_user_prompt


def test_system_prompt_contains_key_instructions():
    prompt = build_system_prompt()
    assert "only" in prompt.lower() and "provided context" in prompt.lower()
    assert "cite" in prompt.lower()
    assert "don't have enough information" in prompt.lower() or "insufficient" in prompt.lower()
    assert "hierarchy" in prompt.lower() or "higher-priority" in prompt.lower()


def test_user_prompt_contains_question_and_context():
    chunks = [
        {
            "content": "Wire component X to terminal Y.",
            "section_title": "Wiring",
            "page_number": 5,
            "doc_type": "product_manual",
            "document_title": "Manual A",
            "hierarchy_priority": 5,
        },
        {
            "content": "General wiring standards require grounding.",
            "section_title": "Standards",
            "page_number": 2,
            "doc_type": "general_regulation",
            "document_title": "Regulations",
            "hierarchy_priority": 1,
        },
    ]
    prompt = build_user_prompt("How do I wire component X?", chunks)
    assert "How do I wire component X?" in prompt
    assert "Wire component X to terminal Y." in prompt
    assert "Manual A" in prompt
    assert "priority: 5" in prompt.lower() or "Priority: 5" in prompt


def test_user_prompt_empty_context():
    prompt = build_user_prompt("Some question?", [])
    assert "Some question?" in prompt
    assert "no context" in prompt.lower() or "no relevant" in prompt.lower()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_prompts.py -v`
Expected: FAIL — cannot import build_system_prompt

**Step 3: Write minimal implementation**

`app/generation/prompts.py`:
```python
from __future__ import annotations

from typing import Any

SYSTEM_PROMPT = """You are a technical knowledge assistant for field engineers working with electrical installation documents. Your role is to provide accurate, cited answers based on the provided context.

Rules:
1. Answer based ONLY on the provided context. Never use information outside the context.
2. Cite every claim with [Document Title, Section, Page X].
3. When sources conflict, prefer the document with higher hierarchy priority and explain the override.
4. If you don't have enough information to answer confidently, say: "I don't have enough information to answer this confidently." Do not guess.
5. When synthesizing across multiple documents, clearly indicate which information comes from which source.
6. End your response with a confidence assessment: high, medium, or low."""


def build_system_prompt() -> str:
    return SYSTEM_PROMPT


def build_user_prompt(question: str, chunks: list[dict[str, Any]]) -> str:
    if not chunks:
        return f"""Question: {question}

No relevant context documents were found. State that you have no relevant context to answer this question."""

    context_parts = []
    for i, chunk in enumerate(chunks, 1):
        title = chunk.get("document_title", "Unknown Document")
        section = chunk.get("section_title", "Unknown Section")
        page = chunk.get("page_number", "?")
        priority = chunk.get("hierarchy_priority", 0)
        doc_type = chunk.get("doc_type", "unknown")
        content = chunk.get("content", "")

        context_parts.append(
            f"[Source {i}] {title} — {section}, Page {page} (Type: {doc_type}, Priority: {priority})\n{content}"
        )

    context_block = "\n\n---\n\n".join(context_parts)

    return f"""Context:
{context_block}

---

Question: {question}

Provide a precise, cited answer based on the context above."""
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_prompts.py -v`
Expected: All 3 tests PASS

**Step 5: Commit**

```bash
git add app/generation/prompts.py tests/test_prompts.py
git commit -m "feat: add prompt templates for RAG answer generation"
```

---

### Task 12: Response Formatter

**Files:**
- Create: `app/generation/formatter.py`
- Create: `tests/test_formatter.py`

**Step 1: Write the failing test**

`tests/test_formatter.py`:
```python
from app.generation.formatter import ResponseFormatter


def test_format_response_extracts_sources():
    formatter = ResponseFormatter()
    raw_response = """The component should be wired to terminal Y [Manual A, Wiring, Page 5]. General standards also require grounding [Regulations, Standards, Page 2].

Confidence: high"""

    chunks = [
        {"document_title": "Manual A", "section_title": "Wiring", "page_number": 5},
        {"document_title": "Regulations", "section_title": "Standards", "page_number": 2},
    ]

    result = formatter.format(raw_response, chunks)
    assert result["answer"] is not None
    assert result["confidence"] == "high"
    assert len(result["sources"]) == 2


def test_format_response_default_confidence():
    formatter = ResponseFormatter()
    raw_response = "Some answer without confidence."
    result = formatter.format(raw_response, [])
    assert result["confidence"] == "low"


def test_format_response_refusal():
    formatter = ResponseFormatter()
    raw_response = "I don't have enough information to answer this confidently."
    result = formatter.format(raw_response, [])
    assert "don't have enough information" in result["answer"]
    assert result["confidence"] == "low"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_formatter.py -v`
Expected: FAIL — cannot import ResponseFormatter

**Step 3: Write minimal implementation**

`app/generation/formatter.py`:
```python
from __future__ import annotations

import re
from typing import Any


class ResponseFormatter:
    def format(
        self,
        raw_response: str,
        chunks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        confidence = self._extract_confidence(raw_response)
        answer = self._strip_confidence_line(raw_response)
        sources = self._build_sources(chunks)

        return {
            "answer": answer,
            "sources": sources,
            "confidence": confidence,
        }

    def _extract_confidence(self, text: str) -> str:
        match = re.search(r"[Cc]onfidence:\s*(high|medium|low)", text)
        return match.group(1) if match else "low"

    def _strip_confidence_line(self, text: str) -> str:
        return re.sub(r"\n*[Cc]onfidence:\s*(high|medium|low)\s*$", "", text).strip()

    def _build_sources(self, chunks: list[dict[str, Any]]) -> list[dict[str, str | int]]:
        seen = set()
        sources = []
        for chunk in chunks:
            key = (
                chunk.get("document_title", ""),
                chunk.get("section_title", ""),
                chunk.get("page_number", 0),
            )
            if key not in seen:
                seen.add(key)
                sources.append({
                    "document_title": chunk.get("document_title", "Unknown"),
                    "section": chunk.get("section_title", "Unknown"),
                    "page": chunk.get("page_number", 0),
                })
        return sources
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_formatter.py -v`
Expected: All 3 tests PASS

**Step 5: Commit**

```bash
git add app/generation/formatter.py tests/test_formatter.py
git commit -m "feat: add response formatter with confidence extraction and source dedup"
```

---

### Task 13: Query Logger

**Files:**
- Create: `app/logging/__init__.py`
- Create: `app/logging/query_logger.py`
- Create: `tests/test_query_logger.py`

**Step 1: Write the failing test**

`tests/test_query_logger.py`:
```python
import uuid
from unittest.mock import MagicMock

from app.logging.query_logger import QueryLogger


def test_log_query_builds_correct_payload():
    mock_db = MagicMock()
    mock_db.insert_query_log.return_value = {"id": str(uuid.uuid4())}

    logger = QueryLogger(db=mock_db)
    log_id = logger.log(
        question="How do I wire X?",
        detected_filters={"grid_provider": "GridCo"},
        retrieved_chunks=[{"content": "chunk1", "similarity": 0.9}],
        reranked_chunks=[{"content": "chunk1", "rerank_score": 1.1}],
        llm_prompt="full prompt text",
        llm_response="The answer is...",
        formatted_answer={"answer": "The answer is...", "sources": [], "confidence": "high"},
        model_used="claude-sonnet-4-6",
        latency_ms=1234,
    )

    mock_db.insert_query_log.assert_called_once()
    call_data = mock_db.insert_query_log.call_args[0][0]
    assert call_data["question"] == "How do I wire X?"
    assert call_data["detected_filters"] == {"grid_provider": "GridCo"}
    assert call_data["latency_ms"] == 1234
    assert log_id is not None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_query_logger.py -v`
Expected: FAIL — cannot import QueryLogger

**Step 3: Write minimal implementation**

`app/logging/__init__.py` — empty file.

`app/logging/query_logger.py`:
```python
from __future__ import annotations

import uuid
from typing import Any

from app.models.database import DatabaseClient


class QueryLogger:
    def __init__(self, db: DatabaseClient):
        self.db = db

    def log(
        self,
        question: str,
        detected_filters: dict[str, Any],
        retrieved_chunks: list[dict[str, Any]],
        reranked_chunks: list[dict[str, Any]],
        llm_prompt: str,
        llm_response: str,
        formatted_answer: dict[str, Any],
        model_used: str,
        latency_ms: int,
    ) -> uuid.UUID:
        log_data = {
            "question": question,
            "detected_filters": detected_filters,
            "retrieved_chunks": retrieved_chunks,
            "reranked_chunks": reranked_chunks,
            "llm_prompt": llm_prompt,
            "llm_response": llm_response,
            "formatted_answer": formatted_answer,
            "model_used": model_used,
            "latency_ms": latency_ms,
        }
        result = self.db.insert_query_log(log_data)
        return uuid.UUID(result["id"])
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_query_logger.py -v`
Expected: 1 test PASS

**Step 5: Commit**

```bash
git add app/logging/__init__.py app/logging/query_logger.py tests/test_query_logger.py
git commit -m "feat: add query logger for full trace storage"
```

---

### Task 14: Query Pipeline Orchestrator

**Files:**
- Create: `app/pipeline.py`
- Create: `tests/test_pipeline.py`

**Step 1: Write the failing test**

`tests/test_pipeline.py`:
```python
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.pipeline import QueryPipeline


@pytest.fixture
def mock_deps():
    query_parser = MagicMock()
    query_parser.parse.return_value = MagicMock(
        original_question="How do I wire X for GridCo?",
        detected_provider="GridCo",
        to_filters=lambda: {"grid_provider": "GridCo"},
    )

    vector_search = MagicMock()
    vector_search.search.return_value = [
        {
            "content": "Wire X to terminal Y.",
            "section_title": "Wiring",
            "page_number": 5,
            "doc_type": "product_manual",
            "document_title": "Manual A",
            "grid_provider": "GridCo",
            "hierarchy_priority": 5,
            "similarity": 0.9,
        },
    ]

    reranker = MagicMock()
    reranker.rerank.return_value = [
        {
            "content": "Wire X to terminal Y.",
            "section_title": "Wiring",
            "page_number": 5,
            "doc_type": "product_manual",
            "document_title": "Manual A",
            "grid_provider": "GridCo",
            "hierarchy_priority": 5,
            "similarity": 0.9,
            "rerank_score": 1.2,
        },
    ]

    llm = AsyncMock()
    llm.generate.return_value = "Wire X to terminal Y [Manual A, Wiring, Page 5].\n\nConfidence: high"

    formatter = MagicMock()
    formatter.format.return_value = {
        "answer": "Wire X to terminal Y [Manual A, Wiring, Page 5].",
        "sources": [{"document_title": "Manual A", "section": "Wiring", "page": 5}],
        "confidence": "high",
    }

    logger = MagicMock()
    logger.log.return_value = uuid.uuid4()

    return {
        "query_parser": query_parser,
        "vector_search": vector_search,
        "reranker": reranker,
        "llm": llm,
        "formatter": formatter,
        "logger": logger,
    }


@pytest.mark.asyncio
async def test_pipeline_returns_response(mock_deps):
    pipeline = QueryPipeline(**mock_deps)
    result = await pipeline.run("How do I wire X for GridCo?")

    assert result["answer"] == "Wire X to terminal Y [Manual A, Wiring, Page 5]."
    assert result["confidence"] == "high"
    assert "log_id" in result


@pytest.mark.asyncio
async def test_pipeline_calls_all_steps(mock_deps):
    pipeline = QueryPipeline(**mock_deps)
    await pipeline.run("How do I wire X for GridCo?")

    mock_deps["query_parser"].parse.assert_called_once()
    mock_deps["vector_search"].search.assert_called_once()
    mock_deps["reranker"].rerank.assert_called_once()
    mock_deps["llm"].generate.assert_called_once()
    mock_deps["formatter"].format.assert_called_once()
    mock_deps["logger"].log.assert_called_once()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline.py -v`
Expected: FAIL — cannot import QueryPipeline

**Step 3: Write minimal implementation**

`app/pipeline.py`:
```python
from __future__ import annotations

import time
import uuid
from typing import Any

from app.generation.formatter import ResponseFormatter
from app.generation.llm import LLMClient
from app.generation.prompts import build_system_prompt, build_user_prompt
from app.logging.query_logger import QueryLogger
from app.retrieval.query_parser import QueryParser
from app.retrieval.reranker import Reranker
from app.retrieval.search import VectorSearch


class QueryPipeline:
    def __init__(
        self,
        query_parser: QueryParser,
        vector_search: VectorSearch,
        reranker: Reranker,
        llm: LLMClient,
        formatter: ResponseFormatter,
        logger: QueryLogger,
    ):
        self.query_parser = query_parser
        self.vector_search = vector_search
        self.reranker = reranker
        self.llm = llm
        self.formatter = formatter
        self.logger = logger

    async def run(self, question: str) -> dict[str, Any]:
        start = time.monotonic()

        # 1. Parse query for metadata hints
        parsed = self.query_parser.parse(question)
        detected_filters = parsed.to_filters()

        # 2. Vector search
        retrieved_chunks = self.vector_search.search(question)

        # 3. Re-rank
        reranked_chunks = self.reranker.rerank(
            retrieved_chunks, detected_provider=parsed.detected_provider
        )

        # 4. Generate answer
        system_prompt = build_system_prompt()
        user_prompt = build_user_prompt(question, reranked_chunks)
        llm_response = await self.llm.generate(system_prompt, user_prompt)

        # 5. Format response
        formatted = self.formatter.format(llm_response, reranked_chunks)

        # 6. Log full trace
        latency_ms = int((time.monotonic() - start) * 1000)
        log_id = self.logger.log(
            question=question,
            detected_filters=detected_filters,
            retrieved_chunks=retrieved_chunks,
            reranked_chunks=reranked_chunks,
            llm_prompt=user_prompt,
            llm_response=llm_response,
            formatted_answer=formatted,
            model_used=self.llm.model,
            latency_ms=latency_ms,
        )

        return {
            "answer": formatted["answer"],
            "sources": formatted["sources"],
            "confidence": formatted["confidence"],
            "log_id": str(log_id),
        }
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline.py -v`
Expected: All 2 tests PASS

**Step 5: Commit**

```bash
git add app/pipeline.py tests/test_pipeline.py
git commit -m "feat: add query pipeline orchestrating parse → search → rerank → LLM → format → log"
```

---

### Task 15: FastAPI Routes

**Files:**
- Create: `app/main.py`
- Create: `tests/test_main.py`

**Step 1: Write the failing test**

`tests/test_main.py`:
```python
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def mock_pipeline():
    pipeline = AsyncMock()
    pipeline.run.return_value = {
        "answer": "Wire X to terminal Y.",
        "sources": [{"document_title": "Manual A", "section": "Wiring", "page": 5}],
        "confidence": "high",
        "log_id": str(uuid.uuid4()),
    }
    return pipeline


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.list_documents.return_value = [
        {"id": str(uuid.uuid4()), "title": "Test Doc", "doc_type": "product_manual",
         "hierarchy_priority": 5, "ingestion_status": "completed"}
    ]
    db.get_document.return_value = {
        "id": str(uuid.uuid4()), "title": "Test Doc", "doc_type": "product_manual",
        "hierarchy_priority": 5, "ingestion_status": "completed"
    }
    db.get_query_log.return_value = {
        "id": str(uuid.uuid4()), "question": "test?", "detected_filters": {},
        "retrieved_chunks": [], "reranked_chunks": [], "llm_prompt": "p",
        "llm_response": "r", "formatted_answer": {}, "model_used": "test",
        "latency_ms": 100,
    }
    return db


@pytest.fixture
def client(mock_pipeline, mock_db):
    from app.main import create_app
    app = create_app(pipeline=mock_pipeline, db=mock_db)
    return TestClient(app)


def test_query_endpoint(client, mock_pipeline):
    response = client.post("/query", json={"question": "How do I wire X?"})
    assert response.status_code == 200
    data = response.json()
    assert "answer" in data
    assert "sources" in data
    assert "confidence" in data
    assert "log_id" in data


def test_list_documents(client):
    response = client.get("/documents")
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_get_query_log(client):
    log_id = uuid.uuid4()
    response = client.get(f"/query/{log_id}")
    assert response.status_code == 200
    assert "question" in response.json()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_main.py -v`
Expected: FAIL — cannot import create_app

**Step 3: Write minimal implementation**

`app/main.py`:
```python
from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, UploadFile, File, Form

from app.models.schemas import (
    DocumentCreate,
    DocumentResponse,
    DocumentUpdate,
    QueryRequest,
    QueryResponse,
    QueryLogResponse,
    EvalRunRequest,
)
from app.models.database import DatabaseClient
from app.pipeline import QueryPipeline


def create_app(
    pipeline: QueryPipeline | None = None,
    db: DatabaseClient | None = None,
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

    @app.post("/eval/run")
    async def run_eval(request: EvalRunRequest | None = None) -> dict[str, str]:
        # Placeholder — implemented in Task 16
        return {"status": "not yet implemented"}

    @app.get("/eval/runs")
    def list_eval_runs() -> list[dict[str, Any]]:
        if db is None:
            raise HTTPException(status_code=503, detail="Database not initialized")
        return db.list_eval_runs()

    return app
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_main.py -v`
Expected: All 3 tests PASS

**Step 5: Commit**

```bash
git add app/main.py tests/test_main.py
git commit -m "feat: add FastAPI routes with thin wrappers over pipeline and DB"
```

---

### Task 16: Eval Metrics

**Files:**
- Create: `eval/__init__.py`
- Create: `eval/metrics.py`
- Create: `tests/test_metrics.py`

**Step 1: Write the failing test**

`tests/test_metrics.py`:
```python
import uuid

from eval.metrics import (
    retrieval_recall,
    refusal_accuracy,
)


def test_retrieval_recall_perfect():
    required_doc_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    retrieved_chunks = [
        {"document_id": required_doc_ids[0]},
        {"document_id": required_doc_ids[1]},
        {"document_id": str(uuid.uuid4())},
    ]
    score = retrieval_recall(required_doc_ids, retrieved_chunks)
    assert score == 1.0


def test_retrieval_recall_partial():
    doc_a = str(uuid.uuid4())
    doc_b = str(uuid.uuid4())
    retrieved_chunks = [{"document_id": doc_a}]
    score = retrieval_recall([doc_a, doc_b], retrieved_chunks)
    assert score == 0.5


def test_retrieval_recall_none():
    score = retrieval_recall([str(uuid.uuid4())], [{"document_id": str(uuid.uuid4())}])
    assert score == 0.0


def test_refusal_accuracy_correct_refusal():
    assert refusal_accuracy(
        question_type="unanswerable",
        answer="I don't have enough information to answer this confidently.",
    ) is True


def test_refusal_accuracy_incorrect_answer_to_unanswerable():
    assert refusal_accuracy(
        question_type="unanswerable",
        answer="The wire should be connected to terminal X.",
    ) is False


def test_refusal_accuracy_correct_answer_to_answerable():
    assert refusal_accuracy(
        question_type="answerable",
        answer="The wire should be connected to terminal X.",
    ) is True


def test_refusal_accuracy_false_refusal():
    assert refusal_accuracy(
        question_type="answerable",
        answer="I don't have enough information to answer this confidently.",
    ) is False
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_metrics.py -v`
Expected: FAIL — cannot import from eval.metrics

**Step 3: Write minimal implementation**

`eval/__init__.py` — empty file.

`eval/metrics.py`:
```python
from __future__ import annotations

from typing import Any

REFUSAL_PHRASES = [
    "i don't have enough information",
    "i do not have enough information",
    "insufficient information",
    "cannot answer",
    "unable to answer",
    "no relevant context",
]


def retrieval_recall(
    required_doc_ids: list[str],
    retrieved_chunks: list[dict[str, Any]],
) -> float:
    if not required_doc_ids:
        return 1.0
    retrieved_ids = {chunk.get("document_id") for chunk in retrieved_chunks}
    found = sum(1 for doc_id in required_doc_ids if doc_id in retrieved_ids)
    return found / len(required_doc_ids)


def refusal_accuracy(question_type: str, answer: str) -> bool:
    answer_lower = answer.lower()
    is_refusal = any(phrase in answer_lower for phrase in REFUSAL_PHRASES)

    if question_type == "unanswerable":
        return is_refusal
    else:
        return not is_refusal
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_metrics.py -v`
Expected: All 7 tests PASS

**Step 5: Commit**

```bash
git add eval/__init__.py eval/metrics.py tests/test_metrics.py
git commit -m "feat: add eval metrics for retrieval recall and refusal accuracy"
```

---

### Task 17: Eval Runner

**Files:**
- Create: `eval/runner.py`
- Create: `tests/test_eval_runner.py`

**Step 1: Write the failing test**

`tests/test_eval_runner.py`:
```python
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from eval.runner import EvalRunner


@pytest.fixture
def mock_deps():
    db = MagicMock()
    db.get_eval_questions.return_value = [
        {
            "id": str(uuid.uuid4()),
            "question": "How do I wire X?",
            "question_type": "answerable",
            "expected_answer": "Wire X to terminal Y.",
            "required_source_docs": [str(uuid.uuid4())],
            "required_facts": ["terminal Y"],
            "category": "wiring",
        },
        {
            "id": str(uuid.uuid4()),
            "question": "What is the capital of France?",
            "question_type": "unanswerable",
            "expected_answer": None,
            "required_source_docs": [],
            "required_facts": [],
            "category": "out_of_scope",
        },
    ]
    db.insert_eval_run.return_value = {"id": str(uuid.uuid4())}

    pipeline = AsyncMock()
    pipeline.run.return_value = {
        "answer": "Wire X to terminal Y [Manual, Wiring, Page 5].",
        "sources": [{"document_title": "Manual", "section": "Wiring", "page": 5}],
        "confidence": "high",
        "log_id": str(uuid.uuid4()),
    }

    return {"db": db, "pipeline": pipeline}


@pytest.mark.asyncio
async def test_eval_runner_processes_all_questions(mock_deps):
    runner = EvalRunner(db=mock_deps["db"], pipeline=mock_deps["pipeline"], config_snapshot={})
    results = await runner.run()

    assert "aggregate_scores" in results
    assert "results" in results
    assert len(results["results"]) == 2
    mock_deps["pipeline"].run.assert_called()


@pytest.mark.asyncio
async def test_eval_runner_stores_results(mock_deps):
    runner = EvalRunner(db=mock_deps["db"], pipeline=mock_deps["pipeline"], config_snapshot={"chunk_size": 500})
    await runner.run()

    mock_deps["db"].insert_eval_run.assert_called_once()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_eval_runner.py -v`
Expected: FAIL — cannot import EvalRunner

**Step 3: Write minimal implementation**

`eval/runner.py`:
```python
from __future__ import annotations

from typing import Any

from app.models.database import DatabaseClient
from app.pipeline import QueryPipeline
from eval.metrics import refusal_accuracy, retrieval_recall


class EvalRunner:
    def __init__(
        self,
        db: DatabaseClient,
        pipeline: QueryPipeline,
        config_snapshot: dict[str, Any],
        notes: str | None = None,
    ):
        self.db = db
        self.pipeline = pipeline
        self.config_snapshot = config_snapshot
        self.notes = notes

    async def run(self) -> dict[str, Any]:
        questions = self.db.get_eval_questions()
        results = []

        for q in questions:
            result = await self._evaluate_question(q)
            results.append(result)

        aggregate = self._aggregate(results)

        run_data = {
            "config_snapshot": self.config_snapshot,
            "results": results,
            "aggregate_scores": aggregate,
            "notes": self.notes,
        }
        self.db.insert_eval_run(run_data)

        return {"aggregate_scores": aggregate, "results": results}

    async def _evaluate_question(self, question: dict[str, Any]) -> dict[str, Any]:
        pipeline_result = await self.pipeline.run(question["question"])

        scores: dict[str, Any] = {
            "question_id": question["id"],
            "question": question["question"],
            "question_type": question["question_type"],
            "answer": pipeline_result["answer"],
        }

        # Refusal accuracy
        scores["refusal_correct"] = refusal_accuracy(
            question["question_type"], pipeline_result["answer"]
        )

        # Retrieval recall (only for answerable questions with required docs)
        required_docs = question.get("required_source_docs", [])
        if required_docs:
            # We'd need the retrieved chunks from the log — for now use sources as proxy
            scores["retrieval_recall"] = None  # Requires query log lookup for full scoring
        else:
            scores["retrieval_recall"] = None

        return scores

    def _aggregate(self, results: list[dict[str, Any]]) -> dict[str, Any]:
        refusal_scores = [r["refusal_correct"] for r in results if r["refusal_correct"] is not None]
        refusal_rate = sum(refusal_scores) / len(refusal_scores) if refusal_scores else 0.0

        return {
            "total_questions": len(results),
            "refusal_accuracy": refusal_rate,
        }
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_eval_runner.py -v`
Expected: All 2 tests PASS

**Step 5: Commit**

```bash
git add eval/runner.py tests/test_eval_runner.py
git commit -m "feat: add eval runner that scores golden dataset and stores results"
```

---

### Task 18: Supabase Schema SQL & Match Function

**Files:**
- Create: `supabase/schema.sql`

This is the SQL to set up all tables and the pgvector match function in Supabase.

**Step 1: Write the schema SQL**

`supabase/schema.sql`:
```sql
-- Enable pgvector extension
create extension if not exists vector;

-- Documents table
create table if not exists documents (
    id uuid primary key default gen_random_uuid(),
    title text not null,
    doc_type text not null,
    grid_provider text,
    hierarchy_priority integer not null default 1,
    file_path text,
    ingestion_status text not null default 'pending',
    raw_reducto_output jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- Document chunks with embeddings
create table if not exists document_chunks (
    id uuid primary key default gen_random_uuid(),
    document_id uuid not null references documents(id) on delete cascade,
    content text not null,
    section_title text not null,
    page_number integer not null,
    chunk_index integer not null,
    doc_type text not null,
    grid_provider text,
    hierarchy_priority integer not null default 1,
    embedding vector(1536),
    token_count integer not null
);

-- Index for vector similarity search
create index if not exists document_chunks_embedding_idx
    on document_chunks using ivfflat (embedding vector_cosine_ops)
    with (lists = 100);

-- Hierarchy rules
create table if not exists hierarchy_rules (
    id uuid primary key default gen_random_uuid(),
    parent_doc_id uuid not null references documents(id),
    child_doc_id uuid not null references documents(id),
    scope text,
    notes text
);

-- Query logs
create table if not exists query_logs (
    id uuid primary key default gen_random_uuid(),
    question text not null,
    detected_filters jsonb not null default '{}',
    retrieved_chunks jsonb not null default '[]',
    reranked_chunks jsonb not null default '[]',
    llm_prompt text not null,
    llm_response text not null,
    formatted_answer jsonb not null default '{}',
    model_used text not null,
    latency_ms integer not null,
    created_at timestamptz not null default now()
);

-- Eval questions (golden dataset)
create table if not exists eval_questions (
    id uuid primary key default gen_random_uuid(),
    question text not null,
    question_type text not null default 'answerable',
    expected_answer text,
    required_source_docs jsonb not null default '[]',
    required_facts jsonb not null default '[]',
    category text
);

-- Eval runs
create table if not exists eval_runs (
    id uuid primary key default gen_random_uuid(),
    run_at timestamptz not null default now(),
    config_snapshot jsonb not null default '{}',
    results jsonb not null default '[]',
    aggregate_scores jsonb not null default '{}',
    notes text
);

-- Vector similarity search function
create or replace function match_document_chunks(
    query_embedding vector(1536),
    match_count integer default 20
)
returns table (
    id uuid,
    document_id uuid,
    content text,
    section_title text,
    page_number integer,
    chunk_index integer,
    doc_type text,
    grid_provider text,
    hierarchy_priority integer,
    token_count integer,
    similarity float
)
language sql stable
as $$
    select
        dc.id,
        dc.document_id,
        dc.content,
        dc.section_title,
        dc.page_number,
        dc.chunk_index,
        dc.doc_type,
        dc.grid_provider,
        dc.hierarchy_priority,
        dc.token_count,
        1 - (dc.embedding <=> query_embedding) as similarity
    from document_chunks dc
    order by dc.embedding <=> query_embedding
    limit match_count;
$$;
```

**Step 2: Commit**

```bash
mkdir -p supabase
git add supabase/schema.sql
git commit -m "feat: add Supabase schema with pgvector tables and match function"
```

---

### Task 19: Ingestion Endpoint (POST /ingest)

**Files:**
- Modify: `app/main.py` — add the `/ingest` endpoint
- Create: `tests/test_ingest.py`

**Step 1: Write the failing test**

`tests/test_ingest.py`:
```python
import uuid
from unittest.mock import AsyncMock, MagicMock, patch
from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def mock_db():
    db = MagicMock()
    doc_id = str(uuid.uuid4())
    db.insert_document.return_value = {"id": doc_id, "title": "Test", "ingestion_status": "pending"}
    db.update_document.return_value = {"id": doc_id, "ingestion_status": "completed"}
    db.delete_chunks_for_document.return_value = None
    db.insert_chunks.return_value = None
    return db


@pytest.fixture
def mock_parser():
    parser = AsyncMock()
    parser.parse_pdf.return_value = (
        {"result": {"blocks": []}},  # raw output
        [{"title": "Section 1", "content": "Test content " * 50, "page": 1}],  # sections
    )
    return parser


@pytest.fixture
def mock_chunker():
    chunker = MagicMock()
    chunker.chunk_sections.return_value = [
        MagicMock(content="chunk text", section_title="Section 1", page_number=1, chunk_index=0, token_count=50),
    ]
    return chunker


@pytest.fixture
def mock_embedder():
    embedder = AsyncMock()
    embedder.embed_texts.return_value = [[0.1] * 1536]
    return embedder


@pytest.fixture
def client(mock_db, mock_parser, mock_chunker, mock_embedder):
    app = create_app(
        db=mock_db,
        parser=mock_parser,
        chunker=mock_chunker,
        embedder=mock_embedder,
    )
    return TestClient(app)


def test_ingest_endpoint(client, mock_db, mock_parser):
    response = client.post(
        "/ingest",
        data={
            "title": "Test Document",
            "doc_type": "product_manual",
            "hierarchy_priority": "5",
        },
        files={"file": ("test.pdf", b"fake pdf content", "application/pdf")},
    )
    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert data["ingestion_status"] == "completed"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_ingest.py -v`
Expected: FAIL — create_app doesn't accept parser/chunker/embedder yet

**Step 3: Update app/main.py to add ingest endpoint**

Add to `create_app` parameters: `parser`, `chunker`, `embedder`. Add the `/ingest` route:

```python
# Add these parameters to create_app signature:
# parser: ReductoParser | None = None,
# chunker: Chunker | None = None,
# embedder: Embedder | None = None,

@app.post("/ingest")
async def ingest(
    file: UploadFile = File(...),
    title: str = Form(...),
    doc_type: str = Form(...),
    hierarchy_priority: int = Form(...),
    grid_provider: str | None = Form(None),
):
    if not all([db, parser, chunker, embedder]):
        raise HTTPException(status_code=503, detail="Ingestion services not initialized")

    # Save uploaded file temporarily
    import tempfile, os
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        # Insert document record
        doc = db.insert_document(
            title=title,
            doc_type=doc_type,
            hierarchy_priority=hierarchy_priority,
            file_path=file.filename,
            grid_provider=grid_provider,
        )
        doc_id = doc["id"]

        # Parse PDF
        db.update_document(uuid.UUID(doc_id), {"ingestion_status": "processing"})
        raw_output, sections = await parser.parse_pdf(tmp_path)

        # Store raw output
        db.update_document(uuid.UUID(doc_id), {"raw_reducto_output": raw_output})

        # Chunk
        chunks = chunker.chunk_sections(sections)

        # Embed
        texts = [c.content for c in chunks]
        embeddings = await embedder.embed_texts(texts)

        # Store chunks
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
        if 'doc_id' in locals():
            db.update_document(uuid.UUID(doc_id), {"ingestion_status": "failed"})
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        os.unlink(tmp_path)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_ingest.py -v`
Expected: 1 test PASS

**Step 5: Commit**

```bash
git add app/main.py tests/test_ingest.py
git commit -m "feat: add POST /ingest endpoint with full PDF ingestion pipeline"
```

---

### Task 20: Integration Wiring & App Entry Point

**Files:**
- Create: `app/dependencies.py`
- Modify: `app/main.py` — add default app creation
- Create: `run.py`

**Step 1: Create dependencies.py**

`app/dependencies.py`:
```python
from app.config import settings
from app.generation.formatter import ResponseFormatter
from app.generation.llm import LLMClient
from app.ingestion.chunker import Chunker
from app.ingestion.embedder import Embedder
from app.ingestion.parser import ReductoParser
from app.logging.query_logger import QueryLogger
from app.models.database import DatabaseClient
from app.pipeline import QueryPipeline
from app.retrieval.query_parser import QueryParser
from app.retrieval.reranker import Reranker
from app.retrieval.search import VectorSearch


def build_dependencies():
    db = DatabaseClient()
    parser = ReductoParser(api_key=settings.reducto_api_key)
    chunker = Chunker(chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap)

    embedder = Embedder(
        api_key=settings.openai_api_key,
        model=settings.embedding_model,
        dimensions=settings.embedding_dimensions,
    )

    llm_api_key = (
        settings.anthropic_api_key if settings.llm_provider == "anthropic"
        else settings.openai_api_key
    )
    llm = LLMClient(
        provider=settings.llm_provider,
        api_key=llm_api_key,
        model=settings.llm_model,
    )

    known_providers = db.get_known_providers()
    query_parser = QueryParser(known_providers=known_providers)

    vector_search = VectorSearch(db=db, embedder=embedder, top_k=settings.retrieval_top_k)
    reranker = Reranker(top_n=settings.rerank_top_n)
    formatter = ResponseFormatter()
    logger = QueryLogger(db=db)

    pipeline = QueryPipeline(
        query_parser=query_parser,
        vector_search=vector_search,
        reranker=reranker,
        llm=llm,
        formatter=formatter,
        logger=logger,
    )

    return {
        "db": db,
        "pipeline": pipeline,
        "parser": parser,
        "chunker": chunker,
        "embedder": embedder,
    }
```

**Step 2: Create run.py**

`run.py`:
```python
import uvicorn

from app.dependencies import build_dependencies
from app.main import create_app

deps = build_dependencies()
app = create_app(**deps)

if __name__ == "__main__":
    uvicorn.run("run:app", host="0.0.0.0", port=8000, reload=True)
```

**Step 3: Commit**

```bash
git add app/dependencies.py run.py
git commit -m "feat: add dependency wiring and app entry point"
```

---

### Task 21: Final Verification

**Step 1: Run all tests**

Run: `pytest tests/ -v`
Expected: All tests PASS

**Step 2: Run linter**

Run: `ruff check app/ eval/ tests/`
Expected: No errors (or fix any that appear)

**Step 3: Commit any fixes**

```bash
git add -A
git commit -m "chore: fix lint issues from final verification"
```
