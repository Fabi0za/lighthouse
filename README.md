# Voltara RAG

Hierarchical RAG system for electrical installation technical documents (German). Field engineers ask natural language questions and get precise, cited answers that respect document hierarchy — grid provider rules override general regulations.

## How it works

```
PDF Upload → Reducto API → Table-Aware Chunking → Embeddings → Supabase pgvector (HNSW)
                                                                        │
User Question → Query Parser → Vector Search (top-40) → Cohere Rerank (top-8) → GPT-4o → Cited Answer
```

- **Table-aware chunking**: preserves table structure, adds contextual headers (document title + section)
- **Neural re-ranking**: Cohere rerank-v3.5 replaces rule-based scoring for better relevance
- **Metadata-enriched retrieval**: chunks tagged with doc type, grid provider, hierarchy priority
- **Safety-first**: refuses to answer when context is insufficient rather than guessing
- **Full trace logging**: every query logs retrieved chunks, reranked chunks, prompt, and response

## Current eval results

55 questions across 5 German technical PDFs (791 chunks):

| Metric | Score |
|--------|-------|
| Refusal accuracy | 94.5% |
| Retrieval recall | 100% |
| Answer correctness | 84% |

Evaluated with LLM-as-judge (GPT-4o-mini) against required facts per question.

The evaluated question set was built from a private document corpus and is not
included here. `scripts/seed_eval_questions.py` ships a small set of generic
example questions instead — swap in your own to reproduce the workflow.

## Tech stack

- **Python 3.11** / FastAPI
- **Supabase** (PostgreSQL + pgvector with HNSW index)
- **Reducto API** for PDF parsing
- **OpenAI** for embeddings (`text-embedding-3-small`, 1536d) and LLM (`gpt-4o`)
- **Cohere** for neural re-ranking (`rerank-v3.5`)
- LLM provider is configurable (Anthropic/OpenAI)

## Setup

### 1. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 2. Configure environment

Copy `.env.example` to `.env` and fill in your API keys:

```bash
cp .env.example .env
```

Required keys:
- `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_SERVICE_KEY`
- `REDUCTO_API_KEY`
- `OPENAI_API_KEY`
- `COHERE_API_KEY`

Optional:
- `ANTHROPIC_API_KEY` (if using Anthropic as LLM provider)

### 3. Set up database

Run `supabase/schema.sql` in your Supabase SQL Editor to create tables, HNSW index, and search functions.

### 4. Run

```bash
python run.py
```

The API will be available at `http://localhost:8000`.

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/query` | Ask a question, get a cited answer |
| `GET` | `/query/{log_id}` | Retrieve full query trace |
| `POST` | `/ingest` | Upload and process a PDF |
| `GET` | `/documents` | List all documents |
| `PUT` | `/documents/{id}` | Update document metadata |
| `DELETE` | `/documents/{id}` | Delete document and its chunks |
| `POST` | `/eval/run` | Run evaluation suite |
| `GET` | `/eval/runs` | List evaluation runs |

## Scripts

```bash
# Ingest a PDF
python scripts/test_ingest.py <pdf_path> [title] [doc_type] [priority]

# Query the system
python scripts/test_query.py "Your question here"

# Compare LLM models (all questions, or a subset by ID)
python scripts/test_models.py [question_id ...]

# Compare rule-based vs Cohere reranking
python scripts/test_cohere_rerank.py [question_id ...]
```

## Tests

```bash
pytest tests/ -v
```

## Project structure

```
app/
├── config.py              # Settings (pydantic-settings)
├── dependencies.py        # Wires all components
├── main.py                # FastAPI routes
├── pipeline.py            # Query orchestrator
├── models/
│   ├── schemas.py         # Pydantic models
│   └── database.py        # Supabase client (vector + keyword search)
├── ingestion/
│   ├── parser.py          # Reducto PDF parser
│   ├── chunker.py         # Table-aware, section-based chunking
│   └── embedder.py        # OpenAI embeddings
├── retrieval/
│   ├── query_parser.py    # Grid provider detection
│   ├── reranker.py        # Cohere neural reranker (+ legacy rule-based)
│   └── search.py          # Vector search (+ hybrid search infrastructure)
├── generation/
│   ├── llm.py             # LLM client (Anthropic/OpenAI)
│   ├── prompts.py         # Prompt templates
│   └── formatter.py       # Response formatting
└── logging/
    └── query_logger.py    # Full query trace logging
eval/
├── metrics.py             # Retrieval recall, refusal accuracy, LLM-as-judge correctness
└── runner.py              # Eval runner
supabase/
└── schema.sql             # Database schema, HNSW index, vector + keyword search functions
```

## Optimization history

Key iterations that moved metrics (55 questions, 5 PDFs):

| Eval | Change | Refusal | Recall | Correctness |
|------|--------|---------|--------|-------------|
| 10 | Baseline (55 questions) | 89.1% | 100% | 65.6% |
| 11 | Table-aware chunker + contextual headers | 89.1% | 100% | 67.7% |
| 13 | Corrected over-specified eval facts | 89.1% | 100% | 75.0% |
| 16 | Cohere rerank-v3.5 | 89.1% | 100% | 76.0% |
| 17 | retrieval_top_k 20 → 40 | 94.5% | 100% | 81.2% |
| 19 | Second eval fact correction | 94.5% | 100% | ~84% |

Changes that were tested and reverted (no improvement): hybrid search (BM25+RRF), prompt tuning, Sonnet 4.6, table reformatting at prompt level.

## Design notes: metadata in retrieval

Chunks carry metadata (`doc_type`, `grid_provider`, `hierarchy_priority`) but this metadata is **not used for filtering during retrieval**. The Postgres `match_document_chunks` function ranks all chunks purely by cosine similarity — no `WHERE` clause.

Where metadata actually gets used:
- **LLM prompt** — each chunk is rendered with its type, priority, and source info so the LLM can prefer higher-priority documents when sources conflict
- **Response formatting** — `document_title`, `section_title`, `page_number` build the citation list
- **Query parser** — detects grid provider names in the question (e.g. "Provider A"), but the detected filter is currently not passed to the search layer

**Why not pre-filter?** There's a tradeoff. Hard filtering (e.g. `WHERE grid_provider = 'Provider A'`) would miss cross-document context — a question like "What does Provider A require differently from the NIN standard?" needs chunks from both. Soft boosting in the reranker is safer but risks losing provider-specific chunks if they score low and get cut off by `top_k`. A hybrid approach (retrieve N unfiltered + N filtered, dedupe) would get the best of both but adds complexity. For now, the broad retrieval with `top_k=40` + neural reranking handles this well enough.
