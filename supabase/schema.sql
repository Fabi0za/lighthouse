-- Lighthouse store: documents are versions of watched sources.
-- Design: docs/plans/2026-11-21-versioned-store-design.md
-- Apply to an empty schema; everything is reloadable from corpus.yaml.

create extension if not exists vector;

-- ---------------------------------------------------------------------------
-- Sources: a watched publication
-- ---------------------------------------------------------------------------
create table sources (
    id uuid primary key default gen_random_uuid(),
    title text not null,
    issuer text not null,
    level text not null,
    authority_rank integer not null,
    address text unique,              -- address watched now; moves on promotion
    listing_address text,             -- page that links to the file
    confirmed_at timestamptz,         -- last confirmed by a person; null = never
    created_at timestamptz not null default now()
);

-- Where a source applies. No rows = applies everywhere.
create table source_scopes (
    source_id uuid not null references sources(id) on delete cascade,
    scope text not null,
    primary key (source_id, scope)
);

-- ---------------------------------------------------------------------------
-- Flags: cases the system could not settle, or that it holds for a person
-- ---------------------------------------------------------------------------
create table flags (
    id uuid primary key default gen_random_uuid(),
    source_id uuid not null references sources(id),
    kind text not null
        check (kind in ('new_version', 'candidate', 'check_failed', 'confirmation_overdue')),
    detail jsonb not null default '{}',
    raised_at timestamptz not null default now(),
    resolved_at timestamptz,          -- null = open
    resolution text
);

-- ---------------------------------------------------------------------------
-- Documents: one version of a source
-- ---------------------------------------------------------------------------
create table documents (
    id uuid primary key default gen_random_uuid(),
    source_id uuid not null references sources(id) on delete restrict,
    status text not null default 'pending'
        check (status in ('pending', 'current', 'retired')),
    flag_id uuid references flags(id),
    title text not null,              -- as shown to the model, with version label
    address text,                     -- where this version was obtained
    file_path text,
    file_sha256 text not null,        -- hash of the file bytes
    text_sha256 text,                 -- hash of normalised parsed text; decides "new version"
    parsed_output jsonb,              -- retained record of the version's content
    ingestion_status text not null default 'pending',
    created_at timestamptz not null default now(),
    became_current_at timestamptz,
    retired_at timestamptz,
    unique (source_id, text_sha256),
    check (status <> 'current' or ingestion_status = 'completed'),
    check (status <> 'pending' or flag_id is not null),
    check ((status = 'retired') = (retired_at is not null))
);

create unique index documents_one_current_per_source
    on documents (source_id) where status = 'current';

-- Fingerprints never change once set: a version cannot be rewritten in place.
create function documents_fingerprints_immutable() returns trigger
language plpgsql as $$
begin
    if new.file_sha256 is distinct from old.file_sha256
       or (old.text_sha256 is not null and new.text_sha256 is distinct from old.text_sha256) then
        raise exception 'fingerprints of document % cannot change', old.id
            using errcode = '23514';
    end if;
    return new;
end $$;

create trigger documents_fingerprints_immutable
    before update on documents
    for each row execute function documents_fingerprints_immutable();

-- A flag cannot be resolved while a pending version still points at it.
create function flags_resolve_guard() returns trigger
language plpgsql as $$
begin
    if new.resolved_at is not null and old.resolved_at is null
       and exists (select 1 from documents where flag_id = new.id and status = 'pending') then
        raise exception 'flag % still holds a pending document', new.id
            using errcode = '23514';
    end if;
    return new;
end $$;

create trigger flags_resolve_guard
    before update on flags
    for each row execute function flags_resolve_guard();

-- ---------------------------------------------------------------------------
-- Chunks: only current (and briefly pending) versions have any
-- ---------------------------------------------------------------------------
create table document_chunks (
    id uuid primary key default gen_random_uuid(),
    document_id uuid not null references documents(id) on delete cascade,
    content text not null,
    section_title text not null,
    page_number integer not null,
    chunk_index integer not null,
    embedding vector(1536),
    token_count integer not null
);

-- Full-text search column (German config)
alter table document_chunks add column content_tsv tsvector
    generated always as (to_tsvector('german', content)) stored;

-- HNSW: no tuning needed at this size
create index document_chunks_embedding_idx
    on document_chunks using hnsw (embedding vector_cosine_ops);

create index document_chunks_content_tsv_idx
    on document_chunks using gin (content_tsv);

-- ---------------------------------------------------------------------------
-- Answers and the versions they saw
-- ---------------------------------------------------------------------------
create table query_logs (
    id uuid primary key default gen_random_uuid(),
    question text not null,
    detected_filters jsonb not null default '{}',
    retrieved_chunks jsonb not null default '[]',
    reranked_chunks jsonb not null default '[]',   -- chunk text the model saw
    llm_prompt text not null,
    llm_response text not null,
    formatted_answer jsonb not null default '{}',
    model_used text not null,
    latency_ms integer not null,
    created_at timestamptz not null default now()
);

-- One row per distinct version among the top-8 chunks passed to the model.
create table query_log_documents (
    query_log_id uuid not null references query_logs(id) on delete cascade,
    document_id uuid not null references documents(id) on delete restrict,
    primary key (query_log_id, document_id)
);

create index query_log_documents_document_idx on query_log_documents (document_id);

-- ---------------------------------------------------------------------------
-- Evaluation
-- ---------------------------------------------------------------------------
create table eval_questions (
    id uuid primary key default gen_random_uuid(),
    question text not null,
    question_type text not null default 'answerable',
    expected_answer text,
    required_source_docs jsonb not null default '[]',
    required_facts jsonb not null default '[]',
    category text
);

create table eval_runs (
    id uuid primary key default gen_random_uuid(),
    run_at timestamptz not null default now(),
    config_snapshot jsonb not null default '{}',
    results jsonb not null default '[]',
    aggregate_scores jsonb not null default '{}',
    notes text
);

-- ---------------------------------------------------------------------------
-- Privileges for the backend role.
-- The app connects with the secret key (sb_secret_...), which acts as service_role.
-- On this project, tables created in the SQL editor were not readable by service_role
-- (error 42501 "permission denied") until these grants were run.
-- anon/authenticated are deliberately not granted: these tables have no row-level security.
-- ---------------------------------------------------------------------------
grant usage on schema public to service_role;
grant select, insert, update, delete on all tables in schema public to service_role;
grant execute on all functions in schema public to service_role;
