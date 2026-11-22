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
-- Indexing settings: what turns a version's text into searchable chunks. Rows are made
-- from the app's configuration; the key names the values. Current versions never mix
-- settings: chunks embedded differently cannot be compared in one search.
-- ---------------------------------------------------------------------------
create table indexing_settings (
    key text primary key check (key ~ '^[a-z0-9.]+(-[a-z0-9.]+)*$'),
    embedding_model text not null,
    dimensions integer not null check (dimensions = 1536),  -- the width of chunks.embedding
    chunk_size integer not null check (chunk_size > 0),
    chunk_overlap integer not null check (chunk_overlap >= 0 and chunk_overlap < chunk_size),
    chunker_version integer not null check (chunker_version > 0),  -- raised when chunking code changes
    fingerprint_rule integer not null check (fingerprint_rule > 0), -- raised when the text fingerprint rule changes
    unique (embedding_model, dimensions, chunk_size, chunk_overlap, chunker_version, fingerprint_rule)
);

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
    indexing_settings_key text not null references indexing_settings(key),
    file_sha256 text not null,        -- hash of the file bytes
    text_sha256 text,                 -- hash of normalised parsed text; decides "new version"
    parsed_output jsonb,              -- retained record of the version's content
    created_at timestamptz not null default now(),
    became_current_at timestamptz,
    retired_at timestamptz,
    unique (source_key, text_sha256),
    check (status not in ('held', 'failed') or flag_id is not null),
    constraint versions_fingerprinted check (status in ('loading', 'failed') or text_sha256 is not null),
    check ((status = 'retired') = (retired_at is not null))
);

create unique index versions_one_current_per_source
    on versions (source_key) where status = 'current';

-- What a version is and where it came from never change once set: it cannot be
-- rewritten in place.
create function versions_record_immutable() returns trigger
language plpgsql as $$
begin
    -- While a version is being loaded (again) its text fingerprint and parsed output may
    -- be replaced: a retry can parse the file differently. Past loading they are fixed.
    if new.file_sha256 is distinct from old.file_sha256
       or (not (new.status = 'loading' and old.status in ('loading', 'failed'))
           and ((old.text_sha256 is not null and new.text_sha256 is distinct from old.text_sha256)
                or (old.parsed_output is not null and new.parsed_output is distinct from old.parsed_output))) then
        raise exception 'fingerprints of version % cannot change', old.id
            using errcode = '23514';
    end if;
    if old.obtained_from is not null and new.obtained_from is distinct from old.obtained_from then
        raise exception 'obtained_from of version % cannot change', old.id
            using errcode = '23514';
    end if;
    if new.version_label is distinct from old.version_label
       or new.page_limit is distinct from old.page_limit
       or new.indexing_settings_key is distinct from old.indexing_settings_key then
        raise exception 'label, page limit and indexing settings of version % cannot change', old.id
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

-- Current versions share one set of indexing settings.
create function versions_no_mixed_settings() returns trigger
language plpgsql as $$
declare
    other text;
begin
    if new.status = 'current' then
        select indexing_settings_key into other from versions
            where status = 'current' and source_key <> new.source_key
              and indexing_settings_key <> new.indexing_settings_key
            limit 1;
        if found then
            raise exception 'version % uses indexing settings %, but current versions use %',
                new.id, new.indexing_settings_key, other using errcode = '23514';
        end if;
    end if;
    return new;
end $$;

create trigger versions_no_mixed_settings
    before insert or update of status on versions
    for each row execute function versions_no_mixed_settings();

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
    section_title text not null default '',  -- empty when the text has no heading
    page_number integer not null,
    chunk_index integer not null,
    embedding vector(1536) not null,
    unique (version_id, chunk_index)
);

-- HNSW: no tuning needed at this size
create index chunks_embedding_idx
    on chunks using hnsw (embedding vector_cosine_ops);

-- ---------------------------------------------------------------------------
-- Answers and the versions they saw
-- ---------------------------------------------------------------------------
-- What an answer depends on besides the indexed text: retrieval and rerank depth, the
-- rerank and answer models, and the prompt version. Rows are made from the app's
-- configuration; the key names the values.
create table answer_settings (
    key text primary key check (key ~ '^[a-z0-9.]+(-[a-z0-9.]+)*$'),
    retrieval_top_k integer not null check (retrieval_top_k > 0),
    rerank_top_n integer not null check (rerank_top_n > 0 and rerank_top_n <= retrieval_top_k),
    rerank_model text not null,
    answer_model text not null,
    prompt_version integer not null check (prompt_version > 0),  -- raised when the prompt changes
    unique (retrieval_top_k, rerank_top_n, rerank_model, answer_model, prompt_version)
);

create table answers (
    id uuid primary key default gen_random_uuid(),
    question text not null,
    detected_scope text references scopes(key),     -- scope named in the question, if any
    retrieved_chunks jsonb not null default '[]',
    reranked_chunks jsonb not null default '[]',   -- chunk text the model saw
    llm_prompt text not null,
    llm_response text not null,
    indexing_settings_key text not null references indexing_settings(key),
    answer_settings_key text not null references answer_settings(key),
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
-- An eval question. key is how people and eval/questions.yaml name it.
create table eval_questions (
    key text primary key check (key ~ '^[a-z0-9]+(-[a-z0-9]+)*$'),
    question text not null,
    question_type text not null check (question_type in ('answerable', 'unanswerable')),
    case_type text not null
        check (case_type in ('standard', 'changed_between_versions', 'not_covered', 'unknown_scope')),
    expected_answer text
);

-- The facts a correct answer contains, one per row, judged one by one.
create table eval_question_facts (
    question_key text not null references eval_questions(key) on delete cascade,
    position integer not null check (position > 0),
    text text not null,
    primary key (question_key, position)
);

-- The sources a question needs, each with the version its expected answer was written
-- from (by text fingerprint, which a reload does not change).
create table eval_question_sources (
    question_key text not null references eval_questions(key) on delete cascade,
    source_key text not null,
    written_from_text_sha256 text not null,
    primary key (question_key, source_key),
    foreign key (source_key, written_from_text_sha256) references versions (source_key, text_sha256)
);

-- Questions whose expected answer was written from a version that is no longer current
-- (or whose source has no current version): they need a person to check them.
create view eval_questions_to_review with (security_invoker = true) as
    select qs.question_key, qs.source_key, qs.written_from_text_sha256,
           cur.text_sha256 as current_text_sha256
    from eval_question_sources qs
    left join versions cur on cur.source_key = qs.source_key and cur.status = 'current'
    where cur.text_sha256 is distinct from qs.written_from_text_sha256;

-- One run of the eval questions, under the settings the answers were made with.
create table eval_runs (
    id uuid primary key default gen_random_uuid(),
    run_at timestamptz not null default now(),
    indexing_settings_key text not null references indexing_settings(key),
    answer_settings_key text not null references answer_settings(key),
    judge_model text not null,
    notes text
);

-- One result per question in a run, linked to the answer it scored. A failed judgement
-- has no score and keeps the error; it is never counted as zero.
create table eval_results (
    run_id uuid not null references eval_runs(id) on delete cascade,
    question_key text not null references eval_questions(key),
    answer_id uuid not null references answers(id),
    refusal_correct boolean not null,
    retrieval_recall numeric check (retrieval_recall between 0 and 1),
    answer_correctness numeric check (answer_correctness between 0 and 1),
    judge_error text,
    primary key (run_id, question_key),
    check (judge_error is null or answer_correctness is null)
);

create table eval_fact_results (
    run_id uuid not null,
    question_key text not null,
    position integer not null,
    present boolean not null,
    reason text,
    primary key (run_id, question_key, position),
    foreign key (run_id, question_key) references eval_results (run_id, question_key) on delete cascade,
    foreign key (question_key, position) references eval_question_facts (question_key, position)
);

-- Scores of each run, derived from its results. Averages skip results without a value;
-- scored counts judged results, not_scored the ones whose judgement failed.
create view eval_run_scores with (security_invoker = true) as
    select r.id as run_id, r.run_at,
           count(e.question_key) as questions,
           count(e.answer_correctness) as scored,
           count(e.judge_error) as not_scored,
           avg(e.refusal_correct::int) as refusal_accuracy,
           avg(e.retrieval_recall) as retrieval_recall,
           avg(e.answer_correctness) as answer_correctness
    from eval_runs r
    left join eval_results e on e.run_id = r.id
    group by r.id, r.run_at;

-- ---------------------------------------------------------------------------
-- Version lifecycle. The Supabase client has no multi-statement transactions,
-- so each swap is one function call.
-- ---------------------------------------------------------------------------

-- Start loading a file as a version of a source. A routine load raises no flag.
-- If the source already has a loading or failed version with these bytes (a crash or
-- a failure earlier), that version is taken up again; its flag, if any, stays open
-- until the load succeeds.
create function begin_load(p_source_key text, p_title text, p_version_label text,
                           p_obtained_from text, p_page_limit integer, p_file_sha256 text,
                           p_indexing_settings_key text)
returns uuid
language plpgsql as $$
declare
    v_id uuid;
begin
    select id into v_id from versions
        where source_key = p_source_key and file_sha256 = p_file_sha256
          and indexing_settings_key = p_indexing_settings_key
          and status in ('loading', 'failed')
        for update;
    if found then
        -- left by the earlier attempt: chunks, and a fingerprint a new parse may not match
        delete from chunks where version_id = v_id;
        update versions set status = 'loading', text_sha256 = null, parsed_output = null where id = v_id;
        return v_id;
    end if;
    insert into versions (source_key, status, title, version_label, obtained_from, page_limit, file_sha256,
                          indexing_settings_key)
        values (p_source_key, 'loading', p_title, p_version_label, p_obtained_from, p_page_limit,
                p_file_sha256, p_indexing_settings_key)
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

-- Remove a loading or failed version that will not be kept. By the system: same text as
-- another version, or replaced by a newer file; its open flag is resolved as fixed. By a
-- person (scripts/flags.py discard): the file is given up; the flag is resolved as rejected.
create function discard_version(p_version_id uuid, p_resolved_by text default 'system') returns void
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
    update flags set resolved_at = now(), resolved_by = p_resolved_by,
                     resolution = case p_resolved_by when 'person' then 'rejected' else 'fixed' end
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

-- A person resolves a check that failed (e.g. an address that was unreachable is back).
-- A load failure whose failed version still exists is resolved by retrying or discarding it.
create function resolve_check(p_flag_id bigint) returns void
language plpgsql as $$
declare
    f flags;
begin
    select * into f from flags where id = p_flag_id for update;
    if not found then
        raise exception 'flag % not found', p_flag_id;
    end if;
    if f.kind <> 'check_failed' or f.resolved_at is not null then
        raise exception 'flag % is not an open check_failed flag', p_flag_id;
    end if;
    if exists (select 1 from versions where flag_id = p_flag_id and status = 'failed') then
        raise exception 'flag % holds a failed version: retry the load or discard the version', p_flag_id;
    end if;
    update flags set resolved_at = now(), resolution = 'fixed', resolved_by = 'person'
        where id = p_flag_id;
end $$;

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
                         llm_prompt, llm_response, indexing_settings_key, answer_settings_key, latency_ms)
    values (p_answer->>'question',
            p_answer->>'detected_scope',
            coalesce(p_answer->'retrieved_chunks', '[]'),
            coalesce(p_answer->'reranked_chunks', '[]'),
            p_answer->>'llm_prompt',
            p_answer->>'llm_response',
            p_answer->>'indexing_settings_key',
            p_answer->>'answer_settings_key',
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

-- The answers that saw a version (it was among their top chunks), newest first, with
-- the other versions each of them saw, as "<source key> (<label, or title if none>)".
create function answers_that_saw(p_version_id uuid)
returns table (answer_id uuid, created_at timestamptz, question text, other_versions text[])
language sql stable as $$
    select a.id, a.created_at, a.question,
           array(select o.source_key || ' (' || coalesce(o.version_label, o.title) || ')'
                 from answer_versions ao join versions o on o.id = ao.version_id
                 where ao.answer_id = a.id and ao.version_id <> p_version_id
                 order by 1)
    from answers a
    join answer_versions av on av.answer_id = a.id and av.version_id = p_version_id
    order by a.created_at desc;
$$;

-- Insert or update an eval question with its sources and facts, in one transaction.
-- p_question: {key, question, question_type, case_type, expected_answer,
--              sources: [{source_key, written_from_text_sha256}], facts: [text, ...]}
-- Once a question has eval results, its question text and facts are fixed (earlier fact
-- verdicts refer to them): changing them needs a new key. Sources, expected answer and
-- types may change, e.g. after a review against a newer version.
create function save_eval_question(p_question jsonb) returns void
language plpgsql as $$
declare
    k text := p_question->>'key';
    v_facts text[] := array(select jsonb_array_elements_text(coalesce(p_question->'facts', '[]')));
    old_facts text[];
    old_question text;
begin
    select question into old_question from eval_questions where key = k;
    old_facts := array(select text from eval_question_facts where question_key = k order by position);
    if exists (select 1 from eval_results where question_key = k)
       and (old_question is distinct from p_question->>'question' or old_facts is distinct from v_facts) then
        raise exception 'eval question % has results: its question and facts cannot change; use a new key', k;
    end if;

    insert into eval_questions (key, question, question_type, case_type, expected_answer)
        values (k, p_question->>'question', p_question->>'question_type', p_question->>'case_type',
                p_question->>'expected_answer')
        on conflict (key) do update set question = excluded.question,
            question_type = excluded.question_type, case_type = excluded.case_type,
            expected_answer = excluded.expected_answer;
    delete from eval_question_sources where question_key = k;
    insert into eval_question_sources (question_key, source_key, written_from_text_sha256)
        select k, s->>'source_key', s->>'written_from_text_sha256'
        from jsonb_array_elements(coalesce(p_question->'sources', '[]')) as s;
    if old_facts is distinct from v_facts then
        delete from eval_question_facts where question_key = k;
        insert into eval_question_facts (question_key, position, text)
            select k, n, f from unnest(v_facts) with ordinality as x(f, n);
    end if;
end $$;

-- Store an eval run with all its results and fact results, in one transaction.
-- p_run: {indexing_settings_key, answer_settings_key, judge_model, notes,
--         results: [{question_key, answer_id, refusal_correct, retrieval_recall,
--                    answer_correctness, judge_error, facts: [{position, present, reason}]}]}
create function record_eval_run(p_run jsonb) returns uuid
language plpgsql as $$
declare
    v_id uuid;
begin
    insert into eval_runs (indexing_settings_key, answer_settings_key, judge_model, notes)
        values (p_run->>'indexing_settings_key', p_run->>'answer_settings_key',
                p_run->>'judge_model', p_run->>'notes')
        returning id into v_id;
    insert into eval_results (run_id, question_key, answer_id, refusal_correct, retrieval_recall,
                              answer_correctness, judge_error)
        select v_id, r->>'question_key', (r->>'answer_id')::uuid, (r->>'refusal_correct')::boolean,
               (r->>'retrieval_recall')::numeric, (r->>'answer_correctness')::numeric, r->>'judge_error'
        from jsonb_array_elements(coalesce(p_run->'results', '[]')) as r;
    insert into eval_fact_results (run_id, question_key, position, present, reason)
        select v_id, r->>'question_key', (f->>'position')::integer, (f->>'present')::boolean, f->>'reason'
        from jsonb_array_elements(coalesce(p_run->'results', '[]')) as r,
             jsonb_array_elements(coalesce(r->'facts', '[]')) as f;
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
    source_key text,
    content text,
    section_title text,
    page_number integer,
    chunk_index integer,
    level text,
    rank integer,
    scopes text[],
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
-- bypasses row level security. Every function runs with the caller's rights, and execute
-- is revoked from everyone but service_role, so a public key cannot call any of them.
-- anon and authenticated must exist (they do on Supabase; the test setup creates them).
alter table levels enable row level security;
alter table scopes enable row level security;
alter table indexing_settings enable row level security;
alter table answer_settings enable row level security;
alter table sources enable row level security;
alter table source_scopes enable row level security;
alter table flags enable row level security;
alter table versions enable row level security;
alter table chunks enable row level security;
alter table answers enable row level security;
alter table answer_versions enable row level security;
alter table eval_questions enable row level security;
alter table eval_question_facts enable row level security;
alter table eval_question_sources enable row level security;
alter table eval_runs enable row level security;
alter table eval_results enable row level security;
alter table eval_fact_results enable row level security;

-- New functions are executable by PUBLIC by default. Nothing in this schema is for the
-- public roles: revoke every function from them; service_role keeps its explicit grant.
revoke execute on all functions in schema public from public, anon, authenticated;
