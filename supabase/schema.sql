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

-- Full-text search column (German config)
alter table document_chunks add column if not exists content_tsv tsvector
    generated always as (to_tsvector('german', content)) stored;

-- Index for vector similarity search (HNSW: no tuning needed, exact at <10k rows)
create index if not exists document_chunks_embedding_idx
    on document_chunks using hnsw (embedding vector_cosine_ops);

-- Index for full-text keyword search
create index if not exists document_chunks_content_tsv_idx
    on document_chunks using gin (content_tsv);

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
    similarity float,
    document_title text
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
        1 - (dc.embedding <=> query_embedding) as similarity,
        d.title as document_title
    from document_chunks dc
    join documents d on d.id = dc.document_id
    order by dc.embedding <=> query_embedding
    limit match_count;
$$;

-- Keyword (full-text) search function
create or replace function keyword_search_chunks(
    search_query text,
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
    rank float,
    document_title text
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
        ts_rank(dc.content_tsv, websearch_to_tsquery('german', search_query)) as rank,
        d.title as document_title
    from document_chunks dc
    join documents d on d.id = dc.document_id
    where dc.content_tsv @@ websearch_to_tsquery('german', search_query)
    order by rank desc
    limit match_count;
$$;

-- Privileges for the backend role.
-- The app connects with the secret key (sb_secret_...), which acts as service_role.
-- On this project, tables created in the SQL editor were not readable by service_role
-- (error 42501 "permission denied") until these grants were run.
-- anon/authenticated are deliberately not granted: these tables have no row-level security.
grant usage on schema public to service_role;
grant select, insert, update, delete on all tables in schema public to service_role;
grant execute on all functions in schema public to service_role;
