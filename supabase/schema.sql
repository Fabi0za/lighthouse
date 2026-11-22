-- Lighthouse store: versions of watched sources.
-- Design: docs/plans/2026-11-21-versioned-store-design.md
-- Apply to an empty schema; everything is reloadable from corpus.yaml.

create extension if not exists vector;

-- ---------------------------------------------------------------------------
-- Levels and scopes: lists that grow, kept as tables (data comes from corpus.yaml)
-- ---------------------------------------------------------------------------
create table levels (
    key text primary key check (key ~ '^[a-z]+(-[a-z]+)*$'),
    rank integer not null unique check (rank > 0),
    requires_scope boolean not null default false   -- a source of this level needs a scope
);

comment on column levels.rank is
    'Higher rank wins: where sources conflict, the source whose level has the higher rank prevails.';

-- Where a source applies, e.g. one operator's network.
create table scopes (
    key text primary key check (key ~ '^[a-z]+(-[a-z]+)*$'),
    name text not null
);

-- ---------------------------------------------------------------------------
-- Sources: a watched publication
-- ---------------------------------------------------------------------------
-- The key is how people and corpus.yaml name a source: publisher-publication,
-- lowercase, no version or year. It never changes.
create table sources (
    key text primary key check (key ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
    level text not null references levels(key),
    watch_address text unique,        -- address a person decided to watch
    confirmed_at timestamptz,         -- last confirmed by a person; null = never
    created_at timestamptz not null default now()
);

-- Where a source applies. No rows = applies everywhere.
create table source_scopes (
    source_key text not null references sources(key) on delete cascade,
    scope_key text not null references scopes(key),
    primary key (source_key, scope_key)
);

create function sources_key_immutable() returns trigger
language plpgsql as $$
begin
    if new.key is distinct from old.key then
        raise exception 'source key % cannot change', old.key using errcode = '23514';
    end if;
    return new;
end $$;

create trigger sources_key_immutable
    before update on sources
    for each row execute function sources_key_immutable();

-- A source whose level requires a scope has at least one, checked at commit so that
-- a source and its scopes can be written in one transaction (save_source).
create function sources_scope_required() returns trigger
language plpgsql as $$
declare
    k text;
begin
    if tg_table_name = 'sources' then
        k := new.key;
    else
        k := old.source_key;
    end if;
    if exists (select 1 from sources s join levels l on l.key = s.level
               where s.key = k and l.requires_scope)
       and not exists (select 1 from source_scopes where source_key = k) then
        raise exception 'source % needs a scope for its level', k using errcode = '23514';
    end if;
    return null;
end $$;

create constraint trigger sources_scope_required
    after insert or update of level on sources
    deferrable initially deferred
    for each row execute function sources_scope_required();

create constraint trigger source_scopes_scope_required
    after delete on source_scopes
    deferrable initially deferred
    for each row execute function sources_scope_required();

-- ---------------------------------------------------------------------------
-- Flags: cases the system could not settle, or that it holds for a person
-- ---------------------------------------------------------------------------
-- A flag is a case a person must handle. id is the running number people use ("flag 12").
create table flags (
    id bigint generated always as identity primary key,
    source_key text not null references sources(key),
    kind text not null
        check (kind in ('candidate', 'check_failed', 'confirmation_overdue')),
    reason text not null
        check (reason in ('possible_successor', 'unreachable', 'parse_failed', 'load_failed', 'overdue')),
    detail jsonb not null,
    raised_at timestamptz not null default now(),
    resolved_at timestamptz,          -- null = open
    resolution text check (resolution in ('promoted', 'rejected', 'fixed', 'confirmed')),
    resolved_by text check (resolved_by in ('system', 'person')),
    constraint flags_reason_matches_kind check ((kind, reason) in (
        ('candidate', 'possible_successor'),
        ('check_failed', 'unreachable'), ('check_failed', 'parse_failed'), ('check_failed', 'load_failed'),
        ('confirmation_overdue', 'overdue'))),
    constraint flags_resolved_together check (
        (resolved_at is null) = (resolution is null) and (resolution is null) = (resolved_by is null)),
    constraint flags_detail_shape check (
        jsonb_typeof(detail) = 'object'
        and (detail - 'file' - 'address' - 'message') = '{}'::jsonb
        and (detail ? 'file') <> (detail ? 'address')
        and (detail ? 'file') = (reason in ('parse_failed', 'load_failed')))
);

-- A source is overdue for confirmation at most once at a time.
create unique index flags_one_open_overdue_per_source
    on flags (source_key) where kind = 'confirmation_overdue' and resolved_at is null;

comment on column flags.detail is
    'Which file or address the flag is about, and an optional message for the person: '
    '{"file": "<path as listed in corpus.yaml>"} for parse_failed and load_failed, '
    '{"address": "<url>"} for the other reasons; either may add "message": "<text>".';

-- ---------------------------------------------------------------------------
-- Versions: one version of a source
-- ---------------------------------------------------------------------------
create table versions (
    id uuid primary key default gen_random_uuid(),
    source_key text not null references sources(key) on delete restrict,
    -- loading: being loaded, not yet visible; failed: the load failed (flagged);
    -- held: loaded, waiting for a person (flagged as candidate); current: searched;
    -- retired: replaced or rejected, kept on record without chunks.
    status text not null default 'loading'
        check (status in ('loading', 'failed', 'held', 'current', 'retired')),
    flag_id bigint references flags(id),
    title text not null,              -- title as printed on the version
    version_label text,               -- version statement as printed on the cover; null if none
    obtained_from text,               -- where this version was obtained; never changes once set
    page_limit integer check (page_limit > 0),  -- only the first N pages were loaded; null = all
    file_sha256 text not null,        -- hash of the file bytes
    text_sha256 text,                 -- hash of normalised parsed text; decides "new version"
    parsed_output jsonb,              -- retained record of the version's content
    created_at timestamptz not null default now(),
    became_current_at timestamptz,
    retired_at timestamptz,
    unique (source_key, text_sha256),
    check (status not in ('held', 'failed') or flag_id is not null),
    check ((status = 'retired') = (retired_at is not null))
);

create unique index versions_one_current_per_source
    on versions (source_key) where status = 'current';

-- What a version is and where it came from never change once set: it cannot be
-- rewritten in place.
create function versions_record_immutable() returns trigger
language plpgsql as $$
begin
    if new.file_sha256 is distinct from old.file_sha256
       or (old.text_sha256 is not null and new.text_sha256 is distinct from old.text_sha256) then
        raise exception 'fingerprints of version % cannot change', old.id
            using errcode = '23514';
    end if;
    if old.obtained_from is not null and new.obtained_from is distinct from old.obtained_from then
        raise exception 'obtained_from of version % cannot change', old.id
            using errcode = '23514';
    end if;
    if new.version_label is distinct from old.version_label
       or new.page_limit is distinct from old.page_limit then
        raise exception 'label and page limit of version % cannot change', old.id
            using errcode = '23514';
    end if;
    return new;
end $$;

create trigger versions_record_immutable
    before update on versions
    for each row execute function versions_record_immutable();

-- A flag cannot be resolved while a held version still points at it.
create function flags_resolve_guard() returns trigger
language plpgsql as $$
begin
    if new.resolved_at is not null and old.resolved_at is null
       and exists (select 1 from versions where flag_id = new.id and status = 'held') then
        raise exception 'flag % still holds a held version', new.id
            using errcode = '23514';
    end if;
    return new;
end $$;

create trigger flags_resolve_guard
    before update on flags
    for each row execute function flags_resolve_guard();

-- A held version waits for a person: it needs an open candidate flag of its own source.
-- A failed version was flagged when its load failed: it needs a check_failed flag of its
-- own source (still open, or resolved once a retry succeeded).
create function versions_status_needs_flag() returns trigger
language plpgsql as $$
begin
    if new.status = 'held' and not exists (
        select 1 from flags f
        where f.id = new.flag_id and f.source_key = new.source_key
          and f.kind = 'candidate' and f.resolved_at is null
    ) then
        raise exception 'held version % needs an open candidate flag of source %', new.id, new.source_key
            using errcode = '23514';
    end if;
    if new.status = 'failed' and not exists (
        select 1 from flags f
        where f.id = new.flag_id and f.source_key = new.source_key and f.kind = 'check_failed'
    ) then
        raise exception 'failed version % needs a check_failed flag of source %', new.id, new.source_key
            using errcode = '23514';
    end if;
    return new;
end $$;

create trigger versions_status_needs_flag
    before insert or update of status, flag_id, source_key on versions
    for each row execute function versions_status_needs_flag();

-- ---------------------------------------------------------------------------
-- Chunks: only current versions, and versions being loaded or held, have any
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
    detected_scope text references scopes(key),     -- scope named in the question, if any
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

-- Start loading a file as a version of a source. A routine load raises no flag.
-- If the source already has a loading or failed version with these bytes (a crash or
-- a failure earlier), that version is taken up again; its flag, if any, stays open
-- until the load succeeds.
create function begin_load(p_source_key text, p_title text, p_version_label text,
                           p_obtained_from text, p_page_limit integer, p_file_sha256 text)
returns uuid
language plpgsql as $$
declare
    v_id uuid;
begin
    select id into v_id from versions
        where source_key = p_source_key and file_sha256 = p_file_sha256
          and status in ('loading', 'failed')
        for update;
    if found then
        delete from chunks where version_id = v_id;   -- left by the earlier attempt
        update versions set status = 'loading' where id = v_id;
        return v_id;
    end if;
    insert into versions (source_key, status, title, version_label, obtained_from, page_limit, file_sha256)
        values (p_source_key, 'loading', p_title, p_version_label, p_obtained_from, p_page_limit,
                p_file_sha256)
        returning id into v_id;
    return v_id;
end $$;

-- Mark a load as failed and flag it for a person (check_failed, parse_failed or
-- load_failed). A version that fails again keeps its one open flag, with the newer
-- reason and message. Returns the flag number.
create function fail_load(p_version_id uuid, p_reason text, p_file text, p_message text)
returns bigint
language plpgsql as $$
declare
    v versions;
    v_flag bigint;
    v_detail jsonb := jsonb_strip_nulls(jsonb_build_object('file', p_file, 'message', p_message));
begin
    select * into v from versions where id = p_version_id for update;
    if not found then
        raise exception 'version % not found', p_version_id;
    end if;
    if v.status <> 'loading' then
        raise exception 'version % is %, not loading', p_version_id, v.status;
    end if;
    select id into v_flag from flags
        where id = v.flag_id and kind = 'check_failed' and resolved_at is null;
    if found then
        update flags set reason = p_reason, detail = v_detail where id = v_flag;
    else
        insert into flags (source_key, kind, reason, detail)
            values (v.source_key, 'check_failed', p_reason, v_detail)
            returning id into v_flag;
    end if;
    update versions set status = 'failed', flag_id = v_flag where id = p_version_id;
    return v_flag;
end $$;

-- Remove a loading or failed version that will not be kept (same text as another
-- version, or replaced by a newer file). Its flag, if open, is resolved: fixed by
-- the system, since a newer file took its place.
create function discard_version(p_version_id uuid) returns void
language plpgsql as $$
declare
    v versions;
begin
    select * into v from versions where id = p_version_id for update;
    if not found then
        raise exception 'version % not found', p_version_id;
    end if;
    if v.status not in ('loading', 'failed') then
        raise exception 'version % is %, only loading or failed versions can be discarded',
            p_version_id, v.status;
    end if;
    delete from chunks where version_id = p_version_id;
    delete from versions where id = p_version_id;
    update flags set resolved_at = now(), resolution = 'fixed', resolved_by = 'system'
        where id = v.flag_id and resolved_at is null;
end $$;

-- Make a loading (routine) or held (approved) version current; retire the previous
-- current version and delete its chunks; resolve the version's flag, if any. The source
-- is not changed. Returns how many earlier answers saw the version that was retired.
create function promote_version(p_version_id uuid, p_resolved_by text default 'system')
returns integer
language plpgsql as $$
declare
    v versions;
    v_seen integer;
begin
    select * into v from versions where id = p_version_id;
    if not found then
        raise exception 'version % not found', p_version_id;
    end if;
    perform 1 from sources where key = v.source_key for update;
    select * into v from versions where id = p_version_id for update;
    if v.status not in ('loading', 'held') then
        raise exception 'version % is %, not loading or held', p_version_id, v.status;
    end if;

    select count(distinct av.answer_id) into v_seen
        from answer_versions av join versions old on old.id = av.version_id
        where old.source_key = v.source_key and old.status = 'current';
    delete from chunks
        where version_id in (select id from versions where source_key = v.source_key and status = 'current');
    update versions set status = 'retired', retired_at = now()
        where source_key = v.source_key and status = 'current';
    update versions set status = 'current', became_current_at = now()
        where id = p_version_id;
    update flags set resolved_at = now(), resolved_by = p_resolved_by,
                     resolution = case kind when 'candidate' then 'promoted' else 'fixed' end
        where id = v.flag_id and resolved_at is null;
    return v_seen;
end $$;

-- A person rejects a held candidate: it is retired, its chunks deleted, its flag resolved.
create function reject_version(p_version_id uuid) returns void
language plpgsql as $$
declare
    v versions;
begin
    select * into v from versions where id = p_version_id for update;
    if not found then
        raise exception 'version % not found', p_version_id;
    end if;
    if v.status <> 'held' then
        raise exception 'version % is %, not held', p_version_id, v.status;
    end if;
    delete from chunks where version_id = p_version_id;
    update versions set status = 'retired', retired_at = now() where id = p_version_id;
    update flags set resolved_at = now(), resolution = 'rejected', resolved_by = 'person'
        where id = v.flag_id;
end $$;

-- A loaded version that may succeed the current one is held for a person under a
-- candidate flag, with the address where it was found and the evidence.
create function hold_candidate(p_version_id uuid, p_address text, p_message text) returns bigint
language plpgsql as $$
declare
    v versions;
    v_flag bigint;
begin
    select * into v from versions where id = p_version_id for update;
    if not found then
        raise exception 'version % not found', p_version_id;
    end if;
    if v.status <> 'loading' then
        raise exception 'version % is %, not loading', p_version_id, v.status;
    end if;
    -- the load succeeded, so an earlier failure of it is fixed
    update flags set resolved_at = now(), resolution = 'fixed', resolved_by = 'system'
        where id = v.flag_id and resolved_at is null;
    insert into flags (source_key, kind, reason, detail)
        values (v.source_key, 'candidate', 'possible_successor',
                jsonb_strip_nulls(jsonb_build_object('address', p_address, 'message', p_message)))
        returning id into v_flag;
    update versions set status = 'held', flag_id = v_flag where id = p_version_id;
    return v_flag;
end $$;

-- A person approves a held candidate: it becomes current, and the source's watch address
-- moves to where the candidate was obtained, which confirms the source. Returns how many
-- earlier answers saw the version that was retired.
create function approve_candidate(p_version_id uuid) returns integer
language plpgsql as $$
declare
    v versions;
    v_seen integer;
begin
    select * into v from versions where id = p_version_id;
    if not found then
        raise exception 'version % not found', p_version_id;
    end if;
    if v.status <> 'held' then
        raise exception 'version % is %, not held', p_version_id, v.status;
    end if;
    if v.obtained_from is null then
        raise exception 'version % has no obtained_from address to watch', p_version_id;
    end if;
    v_seen := promote_version(p_version_id, 'person');
    update sources set watch_address = v.obtained_from, confirmed_at = now() where key = v.source_key;
    perform resolve_overdue(v.source_key);
    return v_seen;
end $$;

-- What a monitor reports when a watched address cannot be reached or has moved.
create function raise_check_failed(p_source_key text, p_address text, p_message text) returns bigint
language sql as $$
    insert into flags (source_key, kind, reason, detail)
        values (p_source_key, 'check_failed', 'unreachable',
                jsonb_strip_nulls(jsonb_build_object('address', p_address, 'message', p_message)))
        returning id;
$$;

-- Resolve a source's open overdue flag once a person has confirmed it.
create function resolve_overdue(p_source_key text) returns void
language sql as $$
    update flags set resolved_at = now(), resolution = 'confirmed', resolved_by = 'person'
        where source_key = p_source_key and kind = 'confirmation_overdue' and resolved_at is null;
$$;

-- A person confirms that a source is still what is watched.
create function confirm_source(p_source_key text) returns void
language plpgsql as $$
begin
    update sources set confirmed_at = now() where key = p_source_key;
    if not found then
        raise exception 'source % not found', p_source_key;
    end if;
    perform resolve_overdue(p_source_key);
end $$;

-- Flag every source not confirmed within p_max_age (or never), once per source.
-- Returns how many flags it raised. When to run it is up to whoever schedules it.
create function raise_overdue_flags(p_max_age interval) returns integer
language plpgsql as $$
declare
    n integer;
begin
    insert into flags (source_key, kind, reason, detail)
        select s.key, 'confirmation_overdue', 'overdue', jsonb_build_object('address', s.watch_address)
        from sources s
        where (s.confirmed_at is null or s.confirmed_at < now() - p_max_age)
          and not exists (select 1 from flags f where f.source_key = s.key
                          and f.kind = 'confirmation_overdue' and f.resolved_at is null);
    get diagnostics n = row_count;
    return n;
end $$;

-- Store an answer and the distinct versions its top-8 came from, in one transaction.
create function log_answer(p_answer jsonb, p_version_ids uuid[]) returns uuid
language plpgsql as $$
declare
    v_id uuid;
begin
    insert into answers (question, detected_scope, retrieved_chunks, reranked_chunks,
                            llm_prompt, llm_response, formatted_answer, model_used, latency_ms)
    values (p_answer->>'question',
            p_answer->>'detected_scope',
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

-- Insert or update a source's level, watch address and scopes, in one transaction.
-- Called when a person has listed the source (corpus.yaml): adding the source or
-- setting a new watch address stamps confirmed_at; otherwise it is kept.
create function save_source(p_key text, p_level text, p_scopes text[], p_watch_address text)
returns void
language plpgsql as $$
begin
    insert into sources (key, level, watch_address, confirmed_at)
        values (p_key, p_level, p_watch_address, now())
        on conflict (key) do update set
            level = excluded.level,
            watch_address = excluded.watch_address,
            confirmed_at = case
                when sources.watch_address is distinct from excluded.watch_address then now()
                else sources.confirmed_at end;
    if (select confirmed_at from sources where key = p_key) = now() then
        perform resolve_overdue(p_key);   -- adding the source or a new address confirms it
    end if;
    delete from source_scopes where source_key = p_key and scope_key <> all (p_scopes);
    insert into source_scopes (source_key, scope_key)
        select p_key, unnest(p_scopes) on conflict do nothing;
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
    source_key text,
    content text,
    section_title text,
    page_number integer,
    chunk_index integer,
    level text,
    rank integer,
    scopes text[],
    token_count integer,
    similarity float,
    version_title text,
    version_label text
)
language sql stable
as $$
    select
        c.id,
        c.version_id,
        s.key,
        c.content,
        c.section_title,
        c.page_number,
        c.chunk_index,
        s.level,
        l.rank,
        coalesce((select array_agg(ss.scope_key order by ss.scope_key)
                  from source_scopes ss where ss.source_key = s.key), '{}'),
        c.token_count,
        1 - (c.embedding <=> query_embedding),
        v.title,
        v.version_label
    from chunks c
    join versions v on v.id = c.version_id and v.status = 'current'
    join sources s on s.key = v.source_key
    join levels l on l.key = s.level
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
alter table levels enable row level security;
alter table scopes enable row level security;
alter table sources enable row level security;
alter table source_scopes enable row level security;
alter table flags enable row level security;
alter table versions enable row level security;
alter table chunks enable row level security;
alter table answers enable row level security;
alter table answer_versions enable row level security;
alter table eval_questions enable row level security;
alter table eval_runs enable row level security;

revoke execute on function begin_load(text, text, text, text, integer, text) from public, anon, authenticated;
revoke execute on function fail_load(uuid, text, text, text) from public, anon, authenticated;
revoke execute on function discard_version(uuid) from public, anon, authenticated;
revoke execute on function promote_version(uuid, text) from public, anon, authenticated;
revoke execute on function reject_version(uuid) from public, anon, authenticated;
revoke execute on function hold_candidate(uuid, text, text) from public, anon, authenticated;
revoke execute on function approve_candidate(uuid) from public, anon, authenticated;
revoke execute on function raise_check_failed(text, text, text) from public, anon, authenticated;
revoke execute on function resolve_overdue(text) from public, anon, authenticated;
revoke execute on function confirm_source(text) from public, anon, authenticated;
revoke execute on function raise_overdue_flags(interval) from public, anon, authenticated;
revoke execute on function log_answer(jsonb, uuid[]) from public, anon, authenticated;
revoke execute on function save_source(text, text, text[], text) from public, anon, authenticated;
