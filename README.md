# Lighthouse

When someone asks how an installation must be set up, the right answer depends on documents that other people write and change on their own schedule: national rules, each network operator's rules, manufacturers' manuals. An assistant that answers from such documents has no defence against a document being superseded. A publisher changes a file in place, or publishes a new version at a new address while the old one stays online, and the assistant keeps answering from the old version without anyone noticing.

Lighthouse covers what has to happen from the moment a new version exists until the assistant demonstrably answers from it. The problem statement is in [docs/project-brief.md](docs/project-brief.md); the rules every part of the store follows are in [docs/conventions.md](docs/conventions.md).

## What the system does

- Holds every document as a **version** of a watched **source**, identified by the fingerprint of its text, never by its file name, address or date.
- Makes a new version current where the case is clear (new content from a listed file), retires the old one and keeps it on record; search sees current versions only.
- Raises a **flag** for every case it cannot settle: a possible successor found elsewhere (held for a person), a check that could not complete (a failed parse or load, an unreachable address), a source not confirmed for too long.
- Records which versions every answer saw, and lists the earlier answers that relied on a version once it is retired.
- Records the settings every version and answer was made with, and refuses to mix indexing settings in one search.

## What a person does

- Decides what is watched: sources, their levels, scopes and watch addresses, in `corpus.yaml`.
- Resolves flags: approves or rejects a held candidate, confirms a source.
- Re-confirms each source from time to time (`CONFIRMATION_MAX_AGE_DAYS`, default 180).

## What it does not do

- User accounts, sign-in or permissions beyond the one backend role. The API is unauthenticated and meant for local use.
- Performance tuning: index parameters, caching, latency targets.
- A review screen, or delivering flags to a person (mail, chat). Flags are rows; `scripts/flags.py` lists them.
- Fetching pages and detecting that something changed; finding the sources for a new rule-maker. Existing tools do that; Lighthouse starts where a monitor reports.
- Improving how questions are answered: prompt tuning, retrieval quality, citation parsing, conflict handling between sources.
- Storing original files. The parsed text is the retained record of each version.

## How it works

```
corpus.yaml ─► load_corpus.py ─► parse (Reducto) ─► fingerprint ─► chunk ─► embed (Cohere) ─► versions, chunks
question ─► scope detection ─► vector search (current versions, top 40) ─► rerank (Cohere, top 8) ─► Claude ─► answer + versions seen
```

- **Sources and versions.** A source has a fixed key, a level (its rank decides which source prevails) and scopes. Each version has the title and version label as printed, where it was obtained, and its file and text fingerprints. Statuses: loading, failed, held, current, retired.
- **Flags.** Numbered, with a kind and reason from fixed lists and a detail naming the file or address. Routine loads raise none.
- **Settings.** `indexing_settings` (embedding model, dimensions, chunk size and overlap, chunker version, fingerprint rule) and `answer_settings` (retrieval depth, rerank depth and model, answer model, prompt version). Keys are built from the values.
- **Eval.** Questions with readable keys, required sources by key and the version their expected answer was written from, numbered facts. Each run records one result per question, linked to the answer it scored.

The schema, its rules and the tests per rule are described in [the design](docs/plans/2026-11-21-versioned-store-design.md). Measurements are in [docs/baseline.md](docs/baseline.md), changes in [docs/CHANGELOG.md](docs/CHANGELOG.md), open gaps in [docs/build-notes.md](docs/build-notes.md).

## Tech stack

- Python 3.11, FastAPI
- Supabase (PostgreSQL with pgvector, HNSW index)
- Reducto for PDF parsing
- Cohere for embeddings (`embed-v5.0-pro`, 1536 dimensions) and reranking (`rerank-v3.5`)
- Anthropic for the answer model (`claude-sonnet-5-5`) and the eval judge (`claude-haiku-5-5`)

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # then fill in the keys
```

Required keys: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `REDUCTO_API_KEY`, `ANTHROPIC_API_KEY`, `COHERE_API_KEY`. The other settings in `.env.example` have defaults. A key the settings do not know is refused at startup.

**Database.** Apply `supabase/schema.sql` to an empty `public` schema in the Supabase SQL editor. It creates every table, view and function, grants `service_role` access, enables row level security on every table with no policies (so the `anon` and `authenticated` roles see nothing), and limits the write functions to `service_role`. It drops nothing; everything is reloadable from `corpus.yaml`.

**Run the API.** `python run.py` serves it at `http://localhost:8000`.

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/query` | Ask a question; the answer is logged with the versions it saw |
| `GET` | `/answers/{answer_id}` | An answer's trace, formatted answer, versions seen and settings |
| `GET` | `/versions` | All versions (read only) |
| `POST` | `/eval/run` | Run the eval questions and record the run |
| `GET` | `/eval/runs` | Eval runs with their scores |

## Scripts

```bash
# Load levels, scopes, sources and versions from corpus.yaml, oldest version first.
# Bytes already stored are skipped, the same text in new bytes is dismissed, new content
# becomes current and retires the previous version. --parsed-cache DIR reads
# DIR/<pdf sha256>.json instead of calling the parser.
python scripts/load_corpus.py [--dry-run] [--parsed-cache DIR]

# Ask one question through the pipeline
python scripts/ask.py "Your question here"

# Flags: list, approve or reject a held candidate, confirm a source, raise overdue flags,
# report an unreachable address
python scripts/flags.py list
python scripts/flags.py approve VERSION_ID | reject VERSION_ID | confirm SOURCE_KEY
python scripts/flags.py raise-overdue [--max-age-days N]
python scripts/flags.py report-unreachable SOURCE_KEY ADDRESS [--message TEXT]

# Answers that saw a version, newest first, with the other versions each saw
python scripts/answers.py saw --source SOURCE_KEY --label "VERSION LABEL"
python scripts/answers.py saw --version VERSION_ID

# Eval questions from eval/questions.yaml
python scripts/load_eval_questions.py [--file eval/questions.yaml]
```

Experiments (they change nothing in the store unless stated):

- `scripts/experiments/version_baseline.py {current|stale} --runs 3 --out FILE` runs the baseline questions on the BKW V1.2 / V1.3 pair (`current` logs its answers).
- `scripts/experiments/fingerprint_check.py` compares the old and current text fingerprint rule on cached parser output.
- `scripts/experiments/sections_check.py` compares sections and chunks with page headers as headings and as page furniture.

## Tests

```bash
.venv/bin/pytest -q                                                   # unit tests, mocked
TEST_DATABASE_URL=postgresql://localhost/postgres .venv/bin/pytest -q  # including the database tests
```

The database tests in `tests/db/` run against a real Postgres with pgvector and are skipped without `TEST_DATABASE_URL`. Each run creates a throwaway database, applies `supabase/schema.sql` unchanged and drops it afterwards. One-time setup on macOS (Homebrew's pgvector is built for Postgres 18):

```bash
brew install postgresql@18 pgvector
brew services start postgresql@18
```

## Project structure

```
app/
├── config.py            # settings (pydantic-settings); unknown keys are refused
├── settings_rows.py     # indexing and answer settings rows and their keys
├── dependencies.py      # wires the pipeline
├── main.py              # FastAPI routes
├── pipeline.py          # question → search → rerank → answer → log
├── answers/logger.py    # stores each answer with the versions it saw
├── models/database.py   # Supabase client: one method per table read or SQL function
├── ingestion/           # parser, fingerprint, chunker, embedder, load_version
├── retrieval/           # scope detection, vector search, Cohere reranker
└── generation/          # prompt, answer model client, formatter
eval/                    # metrics, runner, questions.yaml
scripts/                 # loaders, flags, answers, ask, experiments/
supabase/schema.sql      # the whole store: tables, views, functions, grants
tests/                   # unit tests; tests/db/ against a real Postgres
```
