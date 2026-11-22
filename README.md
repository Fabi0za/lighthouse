# Lighthouse

Hierarchical RAG system for electrical installation technical documents (German). Field engineers ask natural language questions and get precise, cited answers that respect document hierarchy — grid provider rules override general regulations.

## How it works

```
PDF Upload → Reducto API → Table-Aware Chunking → Embeddings → Supabase pgvector (HNSW)
                                                                        │
User Question → Query Parser → Vector Search (top-40) → Cohere Rerank (top-8) → Claude → Cited Answer
```

- **Table-aware chunking**: preserves table structure, adds contextual headers (document title + section)
- **Neural re-ranking**: Cohere rerank-v3.5 replaces rule-based scoring for better relevance
- **Versioned sources**: each document is a version of a watched source; search uses current versions only, retired versions are kept without chunks, and every answer records the versions it saw. Search results carry the source's level, priority and scopes
- **Safety-first**: refuses to answer when context is insufficient rather than guessing
- **Full trace logging**: every query logs retrieved chunks, reranked chunks, prompt, and response

## Current eval results

55 questions across 5 German technical PDFs (791 chunks):

| Metric | Score |
|--------|-------|
| Refusal accuracy | 94.5% |
| Retrieval recall | 100% |
| Answer correctness | 84% |

Evaluated with LLM-as-judge (GPT-4o-mini at the time, with OpenAI `text-embedding-3-small` embeddings) against required facts per question. The judge is now Claude Haiku 5.5 and embeddings are Cohere `embed-v5.0-pro`; these results have not been re-measured since.

Eval questions live in `eval/questions.yaml` (format in `scripts/load_eval_questions.py`); load them with `python scripts/load_eval_questions.py`.

## Tech stack

- **Python 3.11** / FastAPI
- **Supabase** (PostgreSQL + pgvector with HNSW index)
- **Reducto API** for PDF parsing
- **Cohere** for embeddings (`embed-v5.0-pro`, 1536d via `output_dimension`)
- **Anthropic** for the answer model (`claude-sonnet-5-5`)
- **Cohere** for neural re-ranking (`rerank-v3.5`)
- **Claude Haiku 5.5** as the eval judge

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
- `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`
- `REDUCTO_API_KEY`
- `ANTHROPIC_API_KEY` (LLM and eval judge)
- `COHERE_API_KEY` (embeddings and re-ranking)

Defaults: `RETRIEVAL_TOP_K=40`, `RERANK_TOP_N=8`.

### 3. Set up database

Run `supabase/schema.sql` in your Supabase SQL Editor to create tables, HNSW index, and search functions. The script ends with grants for `service_role` (the role behind the secret key); without them every query fails with `permission denied` (42501).

`schema.sql` must be applied to an empty database: it creates tables and functions but drops nothing. On a project that has the old tables, drop them first (everything is reloadable from `corpus.yaml`). It also enables row level security on every table and limits the write functions to `service_role`.

### 4. Run

```bash
python run.py
```

The API will be available at `http://localhost:8000`.

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/query` | Ask a question, get a cited answer |
| `GET` | `/answers/{answer_id}` | An answer's full trace, its formatted answer, the versions it saw and the settings it used |
| `GET` | `/versions` | List all versions |
| `POST` | `/eval/run` | Run evaluation suite |
| `GET` | `/eval/runs` | List evaluation runs |

Versions are never deleted; a newer version retires the old one. The API has no authentication and is meant for local use only. Versions are loaded with `scripts/load_corpus.py`.

## Scripts

```bash
# Load every source and version in corpus.yaml, oldest version first.
# Versions are matched by content fingerprint: bytes already stored are skipped,
# new bytes with the same text are dismissed, new content becomes current and
# retires the previous version. corpus.yaml defines levels, scopes and sources;
# sources are identified by a key that never changes, and the load stops if the
# store holds a source that corpus.yaml no longer lists.
# --parsed-cache DIR reads DIR/<pdf sha256>.json instead of calling the parser.
python scripts/load_corpus.py [--dry-run] [--parsed-cache DIR]

# Query the system
python scripts/ask.py "Your question here"

# Flags a person handles: list them, approve or reject a held candidate, confirm a
# source, raise overdue flags (CONFIRMATION_MAX_AGE_DAYS, default 180), report an
# unreachable address.
python scripts/flags.py list
python scripts/flags.py approve VERSION_ID | reject VERSION_ID | confirm SOURCE_KEY
python scripts/flags.py raise-overdue [--max-age-days N]
python scripts/flags.py report-unreachable SOURCE_KEY ADDRESS [--message TEXT]

# Eval questions from eval/questions.yaml (versions named by source key and label)
python scripts/load_eval_questions.py [--file eval/questions.yaml]

# Answers that saw a version, newest first, with the other versions each saw
python scripts/answers.py saw --source SOURCE_KEY --label "VERSION LABEL"
python scripts/answers.py saw --version VERSION_ID
```

## Tests

Unit tests use mocks and need nothing else:

```bash
.venv/bin/pytest -q
```

The schema tests in `tests/db/` run against a real Postgres with pgvector and are skipped unless `TEST_DATABASE_URL` is set. Each run creates a throwaway database, applies `supabase/schema.sql` and drops it afterwards.

One-time setup (macOS, Homebrew; pgvector is built for Postgres 18, not 17):

```bash
brew install postgresql@18 pgvector
brew services start postgresql@18
```

Full suite, including the database tests:

```bash
TEST_DATABASE_URL=postgresql://localhost/postgres .venv/bin/pytest -q
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
│   ├── chunker.py         # Table-aware, section-based chunking
│   └── embedder.py        # Cohere embeddings
├── retrieval/
│   ├── query_parser.py    # Scope detection
│   ├── reranker.py        # Cohere neural reranker
│   └── search.py          # Vector search
├── generation/
│   ├── llm.py             # Answer model client (Anthropic)
│   ├── prompts.py         # Prompt templates
│   └── formatter.py       # Response formatting
└── answers/
    └── logger.py          # Stores each answer with the versions it saw
eval/
├── metrics.py             # Retrieval recall, refusal accuracy, LLM-as-judge correctness
└── runner.py              # Eval runner
supabase/
└── schema.sql             # Database schema, HNSW index, vector search function
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
