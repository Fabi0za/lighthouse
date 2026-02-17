# Hierarchical RAG Technical Knowledge Assistant — Design Document

**Date**: 2026-02-17
**Status**: Approved

## Problem

Field engineers and technical staff manually search through 50–100 dense technical documents (product manuals, compatibility lists, regulatory frameworks, grid provider–specific installation rules) to answer installation and compliance questions. These documents are interconnected and hierarchical — general regulations define baseline requirements while grid provider–specific documents override or tighten certain rules.

The current process is slow, error-prone, and depends on tribal knowledge. A wrong answer can lead to safety issues or regulatory non-compliance.

## Solution

A Retrieval-Augmented Generation (RAG) system that lets technical employees ask natural language questions and get precise, cited answers that pull from the right documents — respecting document hierarchy, synthesizing across multiple sources, and refusing to answer when context is insufficient.

**Approach**: Hierarchical RAG with metadata-enriched retrieval. Each document chunk is tagged with metadata (document type, grid provider, hierarchy level). At query time, the system detects context from the question, retrieves relevant chunks, re-ranks by metadata relevance and hierarchy priority, and the LLM generates a cited answer.

## Constraints

- **Accuracy is safety-critical** — wrong answers risk safety issues or regulatory non-compliance
- **Citations required** — every claim must reference source document, section, and page
- **Correct refusal** — the system must say "I don't have enough information" rather than guess
- **Document hierarchy** — grid provider rules override general regulations; the system must respect this

## Architecture

### High-Level Flow

```
PDF Upload → Reducto API → Raw Output Stored → Chunking → Embeddings → Supabase pgvector
                                                                              │
User Question → Query Parser → Embed → Vector Search (top-20) → Re-rank (top-8) → LLM → Cited Answer
                    │                         │                       │              │          │
                    └─ detect provider/       └─ metadata             └─ hierarchy   └─ prompt  └─ full trace
                       component hints           filtering               priority      engineering   logged
```

### Tech Stack

- **Language**: Python
- **API**: FastAPI + Uvicorn
- **Database**: Supabase (PostgreSQL + pgvector extension)
- **PDF Parsing**: Reducto API
- **LLM**: Provider-agnostic (Claude, GPT, etc. — configurable)
- **Embeddings**: Provider-agnostic (start with OpenAI `text-embedding-3-small`)
- **HTTP Client**: httpx
- **Config**: pydantic-settings
- **Token Counting**: tiktoken

## Component Design

### 1. Document Ingestion Pipeline

**Flow**: PDF + metadata → Reducto API → store raw output → chunk → embed → store in pgvector

**Supabase Tables**:

**`documents`**:
| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| title | TEXT | Document title |
| doc_type | TEXT | `general_regulation`, `grid_provider_rule`, `product_manual`, `compatibility_list` |
| grid_provider | TEXT | Grid provider name (nullable — not all docs are provider-specific) |
| hierarchy_priority | INTEGER | Higher = takes precedence in conflicts |
| file_path | TEXT | Original file location |
| ingestion_status | TEXT | `pending`, `processing`, `completed`, `failed` |
| raw_reducto_output | JSONB | Full parsed output from Reducto (enables re-chunking without re-calling API) |
| created_at | TIMESTAMPTZ | Ingestion timestamp |
| updated_at | TIMESTAMPTZ | Last update |

**`document_chunks`**:
| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| document_id | UUID | FK to documents |
| content | TEXT | Chunk text |
| section_title | TEXT | Heading/section this chunk belongs to |
| page_number | INTEGER | Source page |
| chunk_index | INTEGER | Order within document |
| doc_type | TEXT | Denormalized from parent document |
| grid_provider | TEXT | Denormalized from parent document |
| hierarchy_priority | INTEGER | Denormalized from parent document |
| embedding | VECTOR(1536) | Embedding vector |
| token_count | INTEGER | Chunk size in tokens |

**`hierarchy_rules`**:
| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| parent_doc_id | UUID | The general/overridden document |
| child_doc_id | UUID | The specific/overriding document |
| scope | TEXT | What aspect is overridden (e.g., "wiring rules chapter 5") |
| notes | TEXT | Human-readable explanation |

**Chunking Strategy**:
- Section-aware chunking based on headings/structure from Reducto output
- Target: ~500 tokens per chunk, 50-token overlap
- Metadata (section title, page number) attached to each chunk
- Tune chunk size based on eval results — re-chunking from stored raw Reducto output is fast

**Re-ingestion**: Delete old chunks for a `document_id` and re-ingest from raw output or new PDF. Simple and reliable at this scale.

### 2. Retrieval & Answer Generation

**Query Flow**:

1. **Query preprocessing**: Extract structured hints — detect grid provider names and component references via keyword matching against known values from the document registry.

2. **Vector retrieval**: Embed query with the same model used for ingestion. Query Supabase pgvector for top-20 similar chunks. Use Supabase RPC calling a `match_documents` Postgres function. Fall back to raw SQL via asyncpg if RPC becomes limiting.

3. **Metadata-aware re-ranking** (rule-based, not ML):
   - Boost chunks matching detected grid provider
   - Apply hierarchy priority: higher-priority docs score higher when content overlaps
   - Filter irrelevant doc types when possible
   - Return top-8 chunks after re-ranking

4. **Answer generation**: Pass re-ranked chunks to LLM with system prompt that instructs:
   - Answer based only on provided context
   - When sources conflict, prefer the higher-priority document and explain the override
   - Cite every claim with `[Doc Title, Section, Page]`
   - Say "I don't have enough information to answer this confidently" when context is insufficient
   - LLM provider swappable via config

5. **Response format**:
   ```
   Answer: [synthesized answer with inline citations]

   Sources:
   - [Doc Title] — Section X, Page Y
   - [Doc Title] — Section Z, Page W

   Confidence: high | medium | low
   ```

### 3. Query Logging

Every query produces a full trace stored in Supabase, retrievable via API.

**`query_logs`**:
| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key, used as `log_id` in API |
| question | TEXT | Raw user question |
| detected_filters | JSONB | Extracted provider/component hints |
| retrieved_chunks | JSONB | All top-20 chunks with similarity scores |
| reranked_chunks | JSONB | Top-8 chunks after re-ranking with final scores |
| llm_prompt | TEXT | Full prompt sent to LLM |
| llm_response | TEXT | Raw LLM response |
| formatted_answer | JSONB | Final formatted answer with citations |
| model_used | TEXT | Which LLM model was used |
| latency_ms | INTEGER | Total query processing time |
| created_at | TIMESTAMPTZ | Timestamp |

### 4. Evaluation Framework

**Golden Dataset** (Supabase `eval_questions` table — single source of truth):
| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| question | TEXT | Natural language question as a technician would ask |
| question_type | TEXT | `answerable` or `unanswerable` |
| expected_answer | TEXT | Expert-written expected answer |
| required_source_docs | JSONB | Document IDs that should be retrieved |
| required_facts | JSONB | Key claims the answer must contain |
| category | TEXT | e.g., `wiring`, `compliance`, `compatibility`, `multi-doc` |

**Metrics**:
- **Retrieval recall**: Did top-N chunks include content from required source documents?
- **Answer correctness**: Does the answer contain required facts? (LLM-as-judge)
- **Citation accuracy**: Are citations present and do they point to real, supporting sources?
- **Hallucination detection**: Claims not grounded in retrieved context? (LLM-as-judge)
- **Hierarchy compliance**: Did the system correctly prefer higher-priority documents in conflicts?
- **Refusal accuracy** (binary): Did the system refuse unanswerable questions? Did it NOT refuse answerable ones?

**Eval Runs** (Supabase `eval_runs` table):
| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| run_at | TIMESTAMPTZ | When the eval ran |
| config_snapshot | JSONB | Chunk size, K, N, model, prompt version — what was tested |
| results | JSONB | Per-question scores |
| aggregate_scores | JSONB | Overall metrics |
| notes | TEXT | What changed in this run |

**Workflow**: Change chunking/prompt/re-ranking → run eval CLI → compare against previous run → decide.

**Bootstrapping**: Start with 20–30 answerable questions + 5–10 unanswerable questions crafted with domain experts. Grow the set from real query log failures.

### 5. API Design

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /ingest | Upload PDF with metadata, triggers ingestion |
| POST | /query | Submit question, returns cited answer |
| GET | /query/{log_id} | Retrieve full query trace for debugging |
| GET | /documents | List ingested documents with metadata |
| PUT | /documents/{id} | Update document metadata |
| DELETE | /documents/{id} | Remove document and its chunks |
| POST | /eval/run | Trigger eval run |
| GET | /eval/runs | List eval run results |

### 6. Project Structure

```
rag/
├── app/
│   ├── main.py              # FastAPI routes (thin wrappers)
│   ├── pipeline.py           # Query orchestration (parse → search → rerank → LLM → format → log)
│   ├── config.py             # Settings (DB, API keys, model config)
│   ├── models/
│   │   ├── schemas.py        # Pydantic request/response models
│   │   └── database.py       # Supabase client, table definitions
│   ├── ingestion/
│   │   ├── parser.py         # Reducto API integration
│   │   ├── chunker.py        # Chunking strategies
│   │   └── embedder.py       # Embedding generation (provider-agnostic)
│   ├── retrieval/
│   │   ├── search.py         # Vector search + metadata filtering
│   │   ├── reranker.py       # Metadata-aware re-ranking logic
│   │   └── query_parser.py   # Extract provider/component hints from questions
│   ├── generation/
│   │   ├── llm.py            # LLM provider abstraction
│   │   ├── prompts.py        # System/user prompt templates
│   │   └── formatter.py      # Response formatting + citation assembly
│   └── logging/
│       └── query_logger.py   # Full query trace logging
├── eval/
│   ├── runner.py             # Eval CLI — reads from Supabase eval_questions
│   └── metrics.py            # Scoring functions
├── tests/
├── pyproject.toml
├── .env.example
└── docs/
    └── plans/
```

## MVP Scope

The MVP delivers:
- PDF ingestion via Reducto (text-only, no table/diagram extraction)
- Metadata-enriched vector retrieval with hierarchy-aware re-ranking
- LLM-generated cited answers with refusal capability
- Full query trace logging
- Eval framework with golden dataset (answerable + unanswerable)
- FastAPI endpoints for ingestion, querying, debugging, and eval

## Future Iterations (Post-MVP, Driven by Eval)

- **Structured table extraction**: Enhance Reducto parsing to extract tables as structured markdown
- **Diagram handling**: Extract diagrams as images, generate descriptions via vision models, return images to users
- **Slack integration**: Bot that receives questions in channels/DMs and returns answers
- **Agentic retrieval**: Multi-step retrieval for complex multi-hop questions (evolve from single-pass if eval shows need)
- **Deployment**: Move from local development to cloud hosting
