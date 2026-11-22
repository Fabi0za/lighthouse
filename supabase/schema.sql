-- Lighthouse store: versions of watched sources.
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
-- Versions: one version of a source
-- ---------------------------------------------------------------------------
create table versions (
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

create unique index versions_one_current_per_source
    on versions (source_id) where status = 'current';

-- Fingerprints never change once set: a version cannot be rewritten in place.
create function versions_fingerprints_immutable() returns trigger
language plpgsql as $$
begin
    if new.file_sha256 is distinct from old.file_sha256
       or (old.text_sha256 is not null and new.text_sha256 is distinct from old.text_sha256) then
        raise exception 'fingerprints of version % cannot change', old.id
            using errcode = '23514';
    end if;
    return new;
end $$;

create trigger versions_fingerprints_immutable
    before update on versions
    for each row execute function versions_fingerprints_immutable();

-- A flag cannot be resolved while a pending version still points at it.
create function flags_resolve_guard() returns trigger
language plpgsql as $$
begin
    if new.resolved_at is not null and old.resolved_at is null
       and exists (select 1 from versions where flag_id = new.id and status = 'pending') then
        raise exception 'flag % still holds a pending version', new.id
            using errcode = '23514';
    end if;
    return new;
end $$;

create trigger flags_resolve_guard
    before update on flags
    for each row execute function flags_resolve_guard();

-- A pending version must be held by an open flag of its own source (checked when a
-- version is inserted as pending or set back to pending, e.g. when reinstated).
create function versions_pending_needs_open_flag() returns trigger
language plpgsql as $$
begin
    if new.status = 'pending' and not exists (
        select 1 from flags f
        where f.id = new.flag_id and f.resolved_at is null and f.source_id = new.source_id
    ) then
        raise exception 'pending version % needs an open flag of source %', new.id, new.source_id
            using errcode = '23514';
    end if;
    return new;
end $$;

create trigger versions_pending_needs_open_flag
    before insert or update of status, flag_id, source_id on versions
    for each row execute function versions_pending_needs_open_flag();

-- ---------------------------------------------------------------------------
-- Chunks: only current (and briefly pending) versions have any
-- ---------------------------------------------------------------------------
create table chunks (
    id uuid primary key default gen_random_uuid(),
    version_id uuid not null references versions(id) on delete cascade,
    content text not null,
    section_title text not null,
    page_number integer not null,
    chunk_index integer not null,
    embedding vector(1536),
    token_count integer not null
);

-- HNSW: no tuning needed at this size
create index chunks_embedding_idx
    on chunks using hnsw (embedding vector_cosine_ops);

-- ---------------------------------------------------------------------------
-- Answers and the versions they saw
-- ---------------------------------------------------------------------------
create table answers (
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
create table answer_versions (
    answer_id uuid not null references answers(id) on delete cascade,
    version_id uuid not null references versions(id) on delete restrict,
    primary key (answer_id, version_id)
);

create index answer_versions_version_idx on answer_versions (version_id);

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
create function promote_version(p_version_id uuid, p_resolution text) returns void
language plpgsql as $$
declare
    v versions;
begin
    select * into v from versions where id = p_version_id;
    if not found then
        raise exception 'version % not found', p_version_id;
    end if;
    perform 1 from sources where id = v.source_id for update;
    select * into v from versions where id = p_version_id for update;
    if v.status <> 'pending' then
        raise exception 'version % is %, not pending', p_version_id, v.status;
    end if;
    if v.ingestion_status <> 'completed' then
        raise exception 'version % is not loaded (ingestion_status %)', p_version_id, v.ingestion_status;
    end if;

    delete from chunks
        where version_id in (select id from versions where source_id = v.source_id and status = 'current');
    update versions set status = 'retired', retired_at = now()
        where source_id = v.source_id and status = 'current';
    update versions set status = 'current', became_current_at = now()
        where id = p_version_id;
    if v.address is not null then
        update sources set address = v.address where id = v.source_id;
    end if;
    update flags set resolved_at = now(), resolution = p_resolution where id = v.flag_id;
end $$;

-- Retire a pending version that should not become current; delete its chunks; resolve the flag.
create function reject_version(p_version_id uuid, p_resolution text) returns void
language plpgsql as $$
declare
    v versions;
begin
    select * into v from versions where id = p_version_id for update;
    if not found then
        raise exception 'version % not found', p_version_id;
    end if;
    if v.status <> 'pending' then
        raise exception 'version % is %, not pending', p_version_id, v.status;
    end if;
    delete from chunks where version_id = p_version_id;
    update versions set status = 'retired', retired_at = now() where id = p_version_id;
    update flags set resolved_at = now(), resolution = p_resolution where id = v.flag_id;
end $$;

-- Store an answer and the distinct versions its top-8 came from, in one transaction.
create function log_answer(p_answer jsonb, p_version_ids uuid[]) returns uuid
language plpgsql as $$
declare
    v_id uuid;
begin
    insert into answers (question, detected_filters, retrieved_chunks, reranked_chunks,
                            llm_prompt, llm_response, formatted_answer, model_used, latency_ms)
    values (p_answer->>'question',
            coalesce(p_answer->'detected_filters', '{}'),
            coalesce(p_answer->'retrieved_chunks', '[]'),
            coalesce(p_answer->'reranked_chunks', '[]'),
            p_answer->>'llm_prompt',
            p_answer->>'llm_response',
            coalesce(p_answer->'formatted_answer', '{}'),
            p_answer->>'model_used',
            (p_answer->>'latency_ms')::integer)
    returning id into v_id;

    insert into answer_versions (answer_id, version_id)
        select distinct v_id, d from unnest(p_version_ids) as d;
    return v_id;
end $$;

-- ---------------------------------------------------------------------------
-- Search: current versions only
-- ---------------------------------------------------------------------------
create function match_chunks(
    query_embedding vector(1536),
    match_count integer default 20
)
returns table (
    id uuid,
    version_id uuid,
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
    version_title text
)
language sql stable
as $$
    select
        c.id,
        c.version_id,
        s.id,
        c.content,
        c.section_title,
        c.page_number,
        c.chunk_index,
        s.level,
        s.authority_rank,
        coalesce((select array_agg(ss.scope order by ss.scope)
                  from source_scopes ss where ss.source_id = s.id), '{}'),
        c.token_count,
        1 - (c.embedding <=> query_embedding),
        v.title
    from chunks c
    join versions v on v.id = c.version_id and v.status = 'current'
    join sources s on s.id = v.source_id
    order by c.embedding <=> query_embedding
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
alter table versions enable row level security;
alter table chunks enable row level security;
alter table answers enable row level security;
alter table answer_versions enable row level security;
alter table eval_questions enable row level security;
alter table eval_runs enable row level security;

revoke execute on function promote_version(uuid, text) from public, anon, authenticated;
revoke execute on function reject_version(uuid, text) from public, anon, authenticated;
revoke execute on function log_answer(jsonb, uuid[]) from public, anon, authenticated;
