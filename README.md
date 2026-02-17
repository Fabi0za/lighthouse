# Voltara RAG

Hierarchical RAG system for electrical installation technical documents. Field engineers ask natural language questions and get precise, cited answers that respect document hierarchy — grid provider rules override general regulations.

## How it works

```
PDF Upload → Reducto API → Chunking → Embeddings → Supabase pgvector
                                                          │
User Question → Query Parser → Vector Search (top-20) → Re-rank (top-8) → LLM → Cited Answer
```

- **Metadata-enriched retrieval**: chunks tagged with doc type, grid provider, hierarchy priority
- **Re-ranking**: provider boost + hierarchy weighting ensures the right documents take precedence
- **Safety-first**: refuses to answer when context is insufficient rather than guessing
- **Full trace logging**: every query logs retrieved chunks, reranked chunks, prompt, and response

## Tech stack

- **Python 3.11** / FastAPI
- **Supabase** (PostgreSQL + pgvector)
- **Reducto API** for PDF parsing
- **OpenAI** for embeddings (`text-embedding-3-small`) and LLM (`gpt-4o`)
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

### 3. Set up database

Run `supabase/schema.sql` in your Supabase SQL Editor to create tables and the vector search function.

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
│   └── database.py        # Supabase client
├── ingestion/
│   ├── parser.py          # Reducto PDF parser
│   ├── chunker.py         # Section-aware chunking
│   └── embedder.py        # OpenAI embeddings
├── retrieval/
│   ├── query_parser.py    # Grid provider detection
│   ├── reranker.py        # Metadata-aware re-ranking
│   └── search.py          # Vector similarity search
├── generation/
│   ├── llm.py             # LLM client (Anthropic/OpenAI)
│   ├── prompts.py         # Prompt templates
│   └── formatter.py       # Response formatting
└── logging/
    └── query_logger.py    # Full query trace logging
eval/
├── metrics.py             # Retrieval recall, refusal accuracy
└── runner.py              # Eval runner
supabase/
└── schema.sql             # Database schema + vector search function
```
