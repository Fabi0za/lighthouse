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
-- Version lifecycle. The Supabase client has no multi-statement transactions,
-- so each swap is one function call.
-- ---------------------------------------------------------------------------

-- Make a pending, fully loaded version current; retire the previous current
-- version and delete its chunks; move the source's address; resolve the flag.
create function promote_version(p_document_id uuid, p_resolution text) returns void
language plpgsql as $$
declare
    v documents;
begin
    select * into v from documents where id = p_document_id;
    if not found then
        raise exception 'document % not found', p_document_id;
    end if;
    perform 1 from sources where id = v.source_id for update;
    select * into v from documents where id = p_document_id for update;
    if v.status <> 'pending' then
        raise exception 'document % is %, not pending', p_document_id, v.status;
    end if;
    if v.ingestion_status <> 'completed' then
        raise exception 'document % is not loaded (ingestion_status %)', p_document_id, v.ingestion_status;
    end if;

    delete from document_chunks
        where document_id in (select id from documents where source_id = v.source_id and status = 'current');
    update documents set status = 'retired', retired_at = now()
        where source_id = v.source_id and status = 'current';
    update documents set status = 'current', became_current_at = now()
        where id = p_document_id;
    if v.address is not null then
        update sources set address = v.address where id = v.source_id;
    end if;
    update flags set resolved_at = now(), resolution = p_resolution where id = v.flag_id;
end $$;

-- Retire a pending version that should not become current; delete its chunks; resolve the flag.
create function reject_version(p_document_id uuid, p_resolution text) returns void
language plpgsql as $$
declare
    v documents;
begin
    select * into v from documents where id = p_document_id for update;
    if not found then
        raise exception 'document % not found', p_document_id;
    end if;
    if v.status <> 'pending' then
        raise exception 'document % is %, not pending', p_document_id, v.status;
    end if;
    delete from document_chunks where document_id = p_document_id;
    update documents set status = 'retired', retired_at = now() where id = p_document_id;
    update flags set resolved_at = now(), resolution = p_resolution where id = v.flag_id;
end $$;

-- Store an answer and the distinct versions its top-8 came from, in one transaction.
create function log_answer(p_log jsonb, p_document_ids uuid[]) returns uuid
language plpgsql as $$
declare
    v_id uuid;
begin
    insert into query_logs (question, detected_filters, retrieved_chunks, reranked_chunks,
                            llm_prompt, llm_response, formatted_answer, model_used, latency_ms)
    values (p_log->>'question',
            coalesce(p_log->'detected_filters', '{}'),
            coalesce(p_log->'retrieved_chunks', '[]'),
            coalesce(p_log->'reranked_chunks', '[]'),
            p_log->>'llm_prompt',
            p_log->>'llm_response',
            coalesce(p_log->'formatted_answer', '{}'),
            p_log->>'model_used',
            (p_log->>'latency_ms')::integer)
    returning id into v_id;

    insert into query_log_documents (query_log_id, document_id)
        select distinct v_id, d from unnest(p_document_ids) as d;
    return v_id;
end $$;

-- ---------------------------------------------------------------------------
-- Search: current versions only
-- ---------------------------------------------------------------------------
create function match_document_chunks(
    query_embedding vector(1536),
    match_count integer default 20
)
returns table (
    id uuid,
    document_id uuid,
    source_id uuid,
    content text,
    section_title text,
    page_number integer,
    chunk_index integer,
    level text,
    authority_rank integer,
    scopes text[],
    token_count integer,
    similarity float,
    document_title text
)
language sql stable
as $$
    select
        dc.id,
        dc.document_id,
        s.id,
        dc.content,
        dc.section_title,
        dc.page_number,
        dc.chunk_index,
        s.level,
        s.authority_rank,
        coalesce((select array_agg(ss.scope order by ss.scope)
                  from source_scopes ss where ss.source_id = s.id), '{}'),
        dc.token_count,
        1 - (dc.embedding <=> query_embedding),
        d.title
    from document_chunks dc
    join documents d on d.id = dc.document_id and d.status = 'current'
    join sources s on s.id = d.source_id
    order by dc.embedding <=> query_embedding
    limit match_count;
$$;

create function keyword_search_chunks(
    search_query text,
    match_count integer default 20
)
returns table (
    id uuid,
    document_id uuid,
    source_id uuid,
    content text,
    section_title text,
    page_number integer,
    chunk_index integer,
    level text,
    authority_rank integer,
    scopes text[],
    token_count integer,
    rank float,
    document_title text
)
language sql stable
as $$
    select
        dc.id,
        dc.document_id,
        s.id,
        dc.content,
        dc.section_title,
        dc.page_number,
        dc.chunk_index,
        s.level,
        s.authority_rank,
        coalesce((select array_agg(ss.scope order by ss.scope)
                  from source_scopes ss where ss.source_id = s.id), '{}'),
        dc.token_count,
        ts_rank(dc.content_tsv, websearch_to_tsquery('german', search_query)),
        d.title
    from document_chunks dc
    join documents d on d.id = dc.document_id and d.status = 'current'
    join sources s on s.id = d.source_id
    where dc.content_tsv @@ websearch_to_tsquery('german', search_query)
    order by 12 desc
    limit match_count;
$$;

-- ---------------------------------------------------------------------------
-- Privileges for the backend role.
-- The app connects with the secret key (sb_secret_...), which acts as service_role.
-- On this project, tables created in the SQL editor were not readable by service_role
-- (error 42501 "permission denied") until these grants were run.
-- anon/authenticated are deliberately not granted (see row level security below).
-- ---------------------------------------------------------------------------
grant usage on schema public to service_role;
grant select, insert, update, delete on all tables in schema public to service_role;
grant execute on all functions in schema public to service_role;

-- Only the backend may read or write the store. Supabase exposes the public schema to the
-- anon and authenticated roles through its API, and its default privileges can grant them
-- table access. Row level security with no policies denies them every row; service_role
-- bypasses row level security. The write functions run with the caller's rights, and
-- execute is revoked from everyone but service_role, so a public key cannot call them.
-- anon and authenticated must exist (they do on Supabase; the test setup creates them).
alter table sources enable row level security;
alter table source_scopes enable row level security;
alter table flags enable row level security;
alter table documents enable row level security;
alter table document_chunks enable row level security;
alter table query_logs enable row level security;
alter table query_log_documents enable row level security;
alter table eval_questions enable row level security;
alter table eval_runs enable row level security;

revoke execute on function promote_version(uuid, text) from public, anon, authenticated;
revoke execute on function reject_version(uuid, text) from public, anon, authenticated;
revoke execute on function log_answer(jsonb, uuid[]) from public, anon, authenticated;
